#!/usr/bin/env python3
"""
margin.wiki collector -- corridor cost decomposition, sampled hourly.

Answers one question per sample: for a given corridor and size, what does the
stablecoin rail actually cost all-in, and how does that split between the
*rails* (network fee) and the *doors* (exchange execution + peg deviation)?

The public narrative measures the rail. Every real cost is at the doors.

What accumulates (and cannot be backfilled):
  - on-ramp basis   : where stable trades vs USD mid at the source venue
  - off-ramp basis  : where stable trades vs USD mid at the destination venue
  - book depth      : whether size moves the price at all
  - baseline margin : what the incumbent fiat rail charges at the same instant
  - fee config      : snapshotted per row, so history stays interpretable
                      when fee schedules change

Two execution regimes are recorded every sample:
  TAKER -- crosses the spread, pays published taker fees. What retail does.
  MAKER -- posts and waits, pays published MAKER fees. NOT zero: Independent
           Reserve has no maker discount (flat 0.50%), Coins.ph maker is 0.10%.
           Upper bound on the *benefit*: assumes a fill at posted top-of-book
           and ignores fill risk -- but it no longer assumes free trading.

Design constraints (deliberate):
  - flat CSV, stdlib + requests, no services to babysit
  - failures are RECORDED as rows with source_ok=false, never dropped;
    a gap in the chart must be visible as a gap, not absent
  - every derived number is a pure function, tested offline against real
    captured payloads in --selftest

Usage:
  python3 collector.py --verify     # one pull, print the waterfall, write nothing
  python3 collector.py              # one pull, append to data/samples.csv
  python3 collector.py --selftest   # offline, no network
"""

import argparse
import csv
import datetime as dt
import json
import os
import sys

try:
    import requests
except ImportError:
    requests = None

HTTP_TIMEOUT = 20
UA = {"User-Agent": "margin.wiki collector/1.0 (+https://margin.wiki)"}
HERE = os.path.dirname(os.path.abspath(__file__))
SAMPLES = os.path.join(HERE, "data", "samples.csv")
PROVIDERS = os.path.join(HERE, "data", "providers.csv")

# The full incumbent panel: every provider the Wise comparison API returns, per
# size, per hourly run -- not just the winner kept in samples.csv. Panel history
# cannot be back-filled, so we start persisting it now. cost_bps uses the same
# convention as the corridor (bps below mid), so it is directly comparable to
# cost_bps_taker / cost_bps_maker.
PROVIDER_FIELDS = [
    "ts_utc", "notional_src", "provider", "landed_dst", "cost_bps",
    "rank", "source_ok", "error",
]

# ---------------------------------------------------------------- config
# Fee schedules are the LARGEST single term in the decomposition. They are
# published numbers, not estimates -- but they must be verified against each
# venue's fee page and dated. Until verified, `verified` stays false and the
# methodology page must say so. See METHODOLOGY.md.
CORRIDORS = {
    "SGD->PHP": {
        "src": "SGD", "dst": "PHP", "stable": "USDT",
        "onramp": {
            "venue": "IndependentReserve",
            # 0.50% default tier (30-day volume < AUD 50k), flat brokerage fee.
            # IR publishes NO maker/taker distinction: a posted (maker) order
            # pays the same 0.50%. Source: independentreserve.com/fees
            "taker_bps": 50.0,
            "maker_bps": 50.0,
            "verified": "2026-08-10",
        },
        "offramp": {
            "venue": "Coins.ph",
            "symbol": "USDTPHP",
            # VIP0 schedule effective 2025-08-08: taker 0.15%, maker 0.10%.
            # (Both were previously wrong: 0.25% taker assumed, maker assumed 0.)
            # Source: support.coins.ph VIP fee table.
            "taker_bps": 15.0,
            "maker_bps": 10.0,
            "verified": "2026-08-10",
        },
        # USDT withdrawal from the ON-RAMP venue (IR), TRC20/Tron, flat.
        # Was 1.0 and unsourced from 2026-08-10 to 2026-08-19, which understated
        # the network leg ~4x and the all-in taker cost by ~8 bps at S$5,000.
        # Independent Reserve's published crypto withdrawal table reads
        # "Tether USD | TRON | 4.0 USDT" (and Ethereum 10.0, not used here).
        # Source: https://www.independentreserve.com/fees  read 2026-08-19.
        "network_fee_stable": 4.0,
        # --- ramp fees: the bank leg on each end, in fiat terms. SGD side:
        # Independent Reserve's own SGD deposit table lists PayNow as
        # "Free", no cap stated, and it is the realistic method (not a
        # generic wire assumption) -- FAST is free too above SGD 1,000 but
        # PayNow is free at every size on the ladder including S$200.
        # Source: https://www.independentreserve.com/sg/fees, read 2026-09-29.
        "deposit": {
            "venue": "IndependentReserve", "method": "PayNow",
            "fee_type": "free", "fee_value": 0.0, "fee_ccy": "SGD",
            "source_url": "https://www.independentreserve.com/sg/fees",
            "verified": "2026-09-29",
        },
        # PHP side: Coins.ph's own cash-out fee table lists PESONet at
        # PHP 0.00 for individual accounts, no cap stated (InstaPay is the
        # alternative at a flat PHP 5.00, but PESONet is free and same-day,
        # so it is the rational choice at every rung).
        # Source: https://support.coins.ph/hc/en-us/articles/201919230-What-fees-are-charged-on-cash-outs,
        # read 2026-09-29.
        "withdrawal": {
            "venue": "Coins.ph", "method": "PESONet",
            "fee_type": "free", "fee_value": 0.0, "fee_ccy": "PHP",
            "source_url": "https://support.coins.ph/hc/en-us/articles/201919230-What-fees-are-charged-on-cash-outs",
            "verified": "2026-09-29",
        },
        "ladder": [200, 1000, 5000, 25000, 50000],
        "providers_file": "providers.csv",
    },
    # --- 2026-09-10, APAC. Both legs reuse venues whose published fee
    # schedules are ALREADY verified in data/fee_checks.csv: Independent
    # Reserve's 0.50% brokerage is a single flat schedule across its markets
    # (its own tiers are denominated in AUD volume, not per-currency), and
    # Coins.ph VIP0 is 0.15/0.10 on every book. No new fee source is introduced,
    # which is the only reason these two could be built at all -- Indodax,
    # WazirX and CoinDCX publish nothing readable, so SGD->IDR and SGD->INR are
    # deliberately absent rather than quoted from a fee nobody can check.
    #
    # The on-ramp path already parameterises on `src`, so these need no code:
    # the same IR order-book call serves AUD and NZD as it serves SGD.
    "AUD->PHP": {
        "src": "AUD", "dst": "PHP", "stable": "USDT",
        "onramp": {
            "venue": "IndependentReserve",
            "taker_bps": 50.0,
            "maker_bps": 50.0,
            "verified": "2026-08-10",
        },
        "offramp": {
            "venue": "Coins.ph",
            "symbol": "USDTPHP",
            "taker_bps": 15.0,
            "maker_bps": 10.0,
            "verified": "2026-08-10",
        },
        # Same on-ramp venue as SGD->PHP, so the same published TRC20
        # withdrawal applies: "Tether USD | TRON | 4.0 USDT".
        "network_fee_stable": 4.0,
        # AUD side: IR's own AUD deposit table -- "All AUD deposits using
        # bank transfer are free", no cap stated. Source:
        # https://www.independentreserve.com/au/fees, read 2026-09-29.
        "deposit": {
            "venue": "IndependentReserve", "method": "Bank transfer",
            "fee_type": "free", "fee_value": 0.0, "fee_ccy": "AUD",
            "source_url": "https://www.independentreserve.com/au/fees",
            "verified": "2026-09-29",
        },
        # Same PHP off-ramp venue and rail as SGD->PHP.
        "withdrawal": {
            "venue": "Coins.ph", "method": "PESONet",
            "fee_type": "free", "fee_value": 0.0, "fee_ccy": "PHP",
            "source_url": "https://support.coins.ph/hc/en-us/articles/201919230-What-fees-are-charged-on-cash-outs",
            "verified": "2026-09-29",
        },
        "ladder": [200, 1000, 5000, 25000, 50000],
        "providers_file": "providers_audphp.csv",
    },
    "NZD->PHP": {
        "src": "NZD", "dst": "PHP", "stable": "USDT",
        "onramp": {
            "venue": "IndependentReserve",
            "taker_bps": 50.0,
            "maker_bps": 50.0,
            "verified": "2026-08-10",
        },
        "offramp": {
            "venue": "Coins.ph",
            "symbol": "USDTPHP",
            "taker_bps": 15.0,
            "maker_bps": 10.0,
            "verified": "2026-08-10",
        },
        "network_fee_stable": 4.0,
        # NZD side: IR's own deposit table has NO free bank-transfer or
        # instant-rail line for NZD at all -- unlike SGD (PayNow) and AUD
        # (bank transfer), the only NZD deposit methods listed are SWIFT
        # (minimum NZD 50,000, fee unstated -- it would be the sender's own
        # bank's outgoing wire fee, not IR's, and is not published) and
        # "debit & credit cards: 0% for Australian cards" (not usable by an
        # NZ-resident sender with an NZ-issued card). Below the ladder's top
        # rung there is genuinely no published free method, so this leg is
        # left unpriced rather than guessed at -- a "gap", not a zero.
        # Source: https://www.independentreserve.com/nz/fees, read 2026-09-29
        # (checked against the SG and AU fee pages too -- the NZD deposit
        # section is identical on all three, confirming it is not a
        # per-region rendering quirk).
        "deposit": {
            "venue": "IndependentReserve", "method": None,
            "fee_type": "gap", "fee_value": None, "fee_ccy": "NZD",
            "source_url": "https://www.independentreserve.com/nz/fees",
            "verified": "2026-09-29",
            "note": ("No free NZD deposit method is published below NZD "
                      "50,000. Only SWIFT (NZD 50,000 minimum, fee "
                      "unstated) or Australian-issued cards are listed."),
        },
        # Same PHP off-ramp venue and rail as SGD->PHP.
        "withdrawal": {
            "venue": "Coins.ph", "method": "PESONet",
            "fee_type": "free", "fee_value": 0.0, "fee_ccy": "PHP",
            "source_url": "https://support.coins.ph/hc/en-us/articles/201919230-What-fees-are-charged-on-cash-outs",
            "verified": "2026-09-29",
        },
        "ladder": [200, 1000, 5000, 25000, 50000],
        "providers_file": "providers_nzdphp.csv",
    },
    "USD->MXN": {
        "src": "USD", "dst": "MXN", "stable": "USDT",
        "onramp": {
            "venue": "Coinbase",
            # Coinbase Advanced, USDT-USD *stable pair* schedule: maker 0.5 bps,
            # taker 1.0 bps. Read from a live account 2026-08-19. This is FLAT,
            # not volume tiered -- the stable-pair table has no tier column and
            # stable-pair volume is excluded from the tier calculation.
            # The fee page sits behind login, so there is nothing to scrape:
            # re-verification of these two numbers is MANUAL.
            "taker_bps": 1.0,
            "maker_bps": 0.5,
            "verified": "2026-08-19",
        },
        "offramp": {
            "venue": "Bitso",
            "symbol": "usdt_mxn",
            # Base tier (30-day volume < 20,000 MXN): maker 0.60%, taker 0.78%.
            # Source is Bitso's OWN public API, checked 2026-08-19:
            # api.bitso.com/v3/available_books/ -> fees.flat_rate for usdt_mxn
            # returns {maker: "0.006", taker: "0.0078"}. That settles which of
            # Bitso's two published schedules governs this book: the MXN one.
            "taker_bps": 78.0,
            "maker_bps": 60.0,
            "verified": "2026-08-19",
        },
        # The corridor models POLYGON. Coinbase supports USDT on Ethereum,
        # Solana, Base, Polygon, Arbitrum and Avalanche -- NOT Tron -- and Bitso
        # accepts USDT deposits free on Polygon (bitso.com/fees/transactions,
        # deposits table, read 2026-08-19). Polygon is the cheapest chain both
        # sides support, so it is what a rational sender uses.
        #
        # Coinbase's published USDT withdrawal cost has two parts:
        #   1. a PROCESSING fee of 0.01% of the amount transferred, capped at
        #      20 USDT -- proportional, not flat. Source:
        #      help.coinbase.com/en/coinbase/trading-and-funding/pricing-and-fees/fees
        #      read 2026-08-19: "All USDT withdrawals sent from your Coinbase
        #      account will be charged a processing fee equal to 0.01% of the
        #      amount transferred, with a maximum of 20 USDT."
        #   2. "A separate network transaction fee will also apply" -- gas,
        #      estimated at send time and NOT published. On Polygon this is
        #      fractions of a cent, so it is left at 0.0 rather than invented.
        #      This is the one term here that UNDERSTATES; see METHODOLOGY.
        #
        # The previous flat 1.0 USDT was neither: it was the SGD->PHP TRC20
        # assumption copied across, on a chain Coinbase does not even support
        # for USDT. At USD 200 it read 50 bps; the published fee is 1 bp.
        "network_fee_stable": 0.0,          # unmodelled gas, see above
        "withdraw_pct": 0.0001,             # 0.01%, published
        "withdraw_pct_cap": 20.0,           # USDT, published
        # USD side: Coinbase Exchange's own help article on ACH deposits
        # states outright "There is no fee charged by Coinbase for ACH."
        # ACH is the realistic method (free; wire costs $10 domestic /$25
        # SWIFT, per a separate Coinbase help article, and is NOT the
        # cheaper option here). Source:
        # https://help.coinbase.com/en/exchange/funding/depositing-with-ach,
        # read 2026-09-29 (public article, not the login-gated trading fee
        # page the bps constants above cite).
        "deposit": {
            "venue": "Coinbase", "method": "ACH",
            "fee_type": "free", "fee_value": 0.0, "fee_ccy": "USD",
            "source_url": "https://help.coinbase.com/en/exchange/funding/depositing-with-ach",
            "verified": "2026-09-29",
        },
        # MXN side: Bitso's own fee page lists Bank Transfer (SPEI)
        # withdrawals at "Free of charge", same as its instant Bitso
        # Transfer and debit-card payout options. Source:
        # https://bitso.com/fees/transactions, read 2026-09-29.
        "withdrawal": {
            "venue": "Bitso", "method": "SPEI",
            "fee_type": "free", "fee_value": 0.0, "fee_ccy": "MXN",
            "source_url": "https://bitso.com/fees/transactions",
            "verified": "2026-09-29",
        },
        "ladder": [200, 1000, 5000, 25000, 50000],
        # providers.csv has NO corridor column and its schema is frozen, so it
        # cannot carry a second corridor. This corridor gets its own file with
        # exactly the same header.
        "providers_file": "providers_usdmxn.csv",
    },
    # --- 2026-09-29, SOURCES-2 (4->7 corridors). Nigeria was picked over
    # Argentina for the premium-country slot after live probing both:
    # Argentina's on-shore venues (Buenbit, Ripio, Lemon) have no reachable
    # public API from a plain client -- be.buenbit.com answers 530, the
    # documented Ripio Trade host resolves to a different product, and
    # api.satoshitango.com answers 403 -- while Nigeria's Luno book
    # (api.luno.com, verified live 2026-09-29) is a real, public,
    # unauthenticated order book with a published fee schedule. This is the
    # corridor the site's own thesis has been missing: Nigeria's banks will
    # not sell dollars at the official rate, which is exactly the case for
    # a dollar stablecoin -- unlike the other six corridors, all of which are
    # managed/floating currencies where an ordinary app already competes.
    "USD->NGN": {
        "src": "USD", "dst": "NGN", "stable": "USDT",
        "onramp": {
            "venue": "Coinbase",
            # Same USDT-USD stable pair schedule as USD->MXN: flat, not
            # volume-tiered. Re-verify manually if that corridor's own
            # onramp fee is ever re-verified -- this is the same account,
            # same pair, same number, not a second source.
            "taker_bps": 1.0,
            "maker_bps": 0.5,
            "verified": "2026-08-19",
        },
        "offramp": {
            "venue": "Luno",
            "symbol": "USDTNGN",
            # Luno runs a SPECIAL stablecoin-pair schedule on USDT/NGN and
            # USDC/NGN, distinct from its normal per-pair table: base tier
            # (NGN 0-1,500,000 30-day volume) taker 0.10%, and a MAKER
            # REBATE of -0.01% (Luno pays the maker, not the other way
            # round) rather than the 0.10% maker fee every other pair on
            # the exchange charges at this tier. Read live from Luno's own
            # published fee table for Nigeria-verified accounts:
            # https://guide.luno.com/hc/en-gb/articles/14962563616157-Luno-fees-and-limits-in-Nigeria
            # ("We have special fees and rebates for USDT/NGN and USDC/NGN
            # pairs... Maker Fee rebate for USDC/NGN and USDT/NGN: -0.01%"),
            # read 2026-09-29. decompose()'s maker leg already handles a
            # negative fee correctly (landed = quote * (1 - fee_off), and a
            # negative fee_off makes that a multiply-up) -- no code change
            # needed to model a rebate, only this number.
            "taker_bps": 10.0,
            "maker_bps": -1.0,
            "verified": "2026-09-29",
        },
        # Coinbase does not support USDT on Tron (see USD->MXN above), and
        # Luno's Nigeria-verified accounts support USDT on Tron (TRC-20)
        # ONLY at app version 8.77.0+ as of this reading -- Ethereum (ERC-20)
        # is the one chain confirmed to work on BOTH sides without that
        # version gate (guide.luno.com, "Which transfer network should I
        # choose when sending or receiving USDT?", read 2026-09-29). So this
        # corridor is modelled on Ethereum, not Polygon like USD->MXN --
        # and Ethereum mainnet gas is NOT the "fractions of a cent" USD->MXN
        # could reasonably leave at zero. Coinbase's own published parts are
        # carried (0.01% processing fee, capped 20 USDT); the ERC20 gas
        # component is real, dynamic, and NOT published anywhere scrapeable,
        # so it stays modelled at 0 rather than invented -- which means this
        # corridor's cost is a real UNDERSTATEMENT at every size, more so
        # than USD->MXN's, and more so at S$200 than at S$50,000. Flagged
        # here rather than hidden; see METHODOLOGY.
        "network_fee_stable": 0.0,           # unmodelled ERC20 gas, see above
        "withdraw_pct": 0.0001,              # 0.01%, published (Coinbase)
        "withdraw_pct_cap": 20.0,             # USDT, published (Coinbase)
        "ladder": [200, 1000, 5000, 25000, 50000],
        "providers_file": "providers_usdngn.csv",
    },
    # USD->INR: the world's single biggest real-world remittance corridor.
    # The USD leg is the exact Coinbase wiring USD->MXN already verified --
    # nothing new to check there. The INR leg is WazirX, NOT CoinDCX: both
    # expose a public, unauthenticated order book (CoinDCX's
    # public.coindcx.com/market_data/orderbook is real and live too), but
    # CoinDCX's own fee page (coindcx.com/fees) sits behind a Cloudflare
    # bot-check that blocks a plain client -- the same class of block that
    # ruled out Quidax for the Nigeria leg -- so there is no reachable
    # published number to cite for CoinDCX's fee. WazirX's fee page
    # (wazirx.com/fees) renders live and lists USDT/INR as an INR MARKET
    # (not a USDT-quoted market, a different tab on the same page): base
    # tier (0-500 WRX held, <=INR 5 lacs 30-day volume) is a FLAT 0.40% on
    # every buy/sell trade under its "Pay Per Trade" plan, no maker/taker
    # split (same shape as Independent Reserve's own flat schedule) --
    # read live 2026-09-29, https://wazirx.com/fees?tab=spot_fees.
    "USD->INR": {
        "src": "USD", "dst": "INR", "stable": "USDT",
        "onramp": {
            "venue": "Coinbase",
            "taker_bps": 1.0,
            "maker_bps": 0.5,
            "verified": "2026-08-19",
        },
        "offramp": {
            "venue": "WazirX",
            "symbol": "usdtinr",
            "taker_bps": 40.0,
            "maker_bps": 40.0,
            "verified": "2026-09-29",
        },
        # Same chain constraint as USD->NGN: Coinbase does not withdraw USDT
        # over Tron, and WazirX's own deposit/withdrawal table lists USDT
        # deposits enabled on BOTH Ethereum (ERC20) and Tron (TRC20)
        # (wazirx.com/fees?tab=deposit_withdrawal_fees, read 2026-09-29), so
        # Ethereum is the common chain here too -- same unmodelled-gas
        # caveat as USD->NGN applies.
        "network_fee_stable": 0.0,           # unmodelled ERC20 gas, see above
        "withdraw_pct": 0.0001,
        "withdraw_pct_cap": 20.0,
        "ladder": [200, 1000, 5000, 25000, 50000],
        "providers_file": "providers_usdinr.csv",
    },
    # SGD->INR: reuses the SGD on-ramp SGD->PHP already built (Independent
    # Reserve) untouched, and the same WazirX INR off-ramp as USD->INR.
    # Independent Reserve's own USDT withdrawal is TRC20/Tron, flat 4.0 USDT
    # (already verified for SGD->PHP above) -- and WazirX's deposit table
    # (read for USD->INR, same table) lists Tron (TRC20) USDT deposits as
    # Enabled, so this corridor reuses SGD->PHP's exact network-fee config
    # unchanged, on the chain IR already uses. No new fee source anywhere
    # in this corridor: every number is one already verified for a corridor
    # above, pointed at a new off-ramp venue.
    "SGD->INR": {
        "src": "SGD", "dst": "INR", "stable": "USDT",
        "onramp": {
            "venue": "IndependentReserve",
            "taker_bps": 50.0,
            "maker_bps": 50.0,
            "verified": "2026-08-10",
        },
        "offramp": {
            "venue": "WazirX",
            "symbol": "usdtinr",
            "taker_bps": 40.0,
            "maker_bps": 40.0,
            "verified": "2026-09-29",
        },
        "network_fee_stable": 4.0,
        "ladder": [200, 1000, 5000, 25000, 50000],
        "providers_file": "providers_sgdinr.csv",
    },
}

# Priced alternates to a corridor's one modelled stablecoin/network path --
# SEB-182, queue item 0.1, first slice only (SGD->PHP). A reader who already
# holds a different stablecoin, or whose wallet is cheaper to move on a
# different chain, has no way to see whether that path beats the one shown
# unless it is actually priced, never invented.
#
# Found by live probe 2026-10-02: Independent Reserve's own order-book API
# (api.independentreserve.com/Public/GetOrderBook?primaryCurrencyCode=Usdc)
# answers with a real, live, two-sided USDC/SGD book -- same venue, same
# account, same 0.50% flat brokerage schedule as USDT/SGD (IR's own fee
# page states the brokerage tier is based on 30-day AUD-equivalent volume,
# not quoted per pair). Coins.ph's own depth endpoint
# (api.pro.coins.ph/openapi/quote/v1/depth?symbol=USDCPHP) answers with a
# real, live, two-sided book too, and its exchangeInfo lists USDCPHP as
# "trading" -- and Coins.ph's own fee article ("Understanding Spot Trade
# (Coins Pro) Trading Fees") describes its maker/taker schedule as tiered by
# account-wide rolling volume, not per-pair, so SGD->PHP's own verified
# 15/10 bps carries over unchanged.
#
# The one genuinely new number is the network fee: independentreserve.com/fees
# (read live 2026-10-02 -- the page itself Cloudflare-blocks this box on
# every path tried, fees/sg/au/robots.txt and its Zendesk mirror alike, so
# read through a plain rendering proxy rather than assumed from a cache or a
# competitor) lists USDC withdrawals over TRON at all -- only Ethereum
# (10.0 USDC), Solana (1.0 USDC), Base (1.0 USDC) and Arbitrum One
# (1.0 USDC). No Polygon or Solana USDT network exists on IR's own table
# (USDT lists ONLY Ethereum at 10.0 USDT and TRON at 4.0 USDT) -- so the
# "second USDT network" half of this probe found nothing, and only the
# second-stablecoin half shipped. Of USDC's four networks, Arbitrum One is
# the one independently confirmed on the Coins.ph side too, by its own help
# article "How do I receive USDC through the Arbitrum Network?"
# (support.coins.ph), so that is the pairing modelled, not Solana or Base,
# which tie it on fee but are unconfirmed on the receiving end.
#
# SEB-193, queue item 0.1, third slice (NZD->PHP). Re-probed live, not carried
# over: api.independentreserve.com/Public/GetOrderBook?primaryCurrencyCode=
# Usdc&secondaryCurrencyCode=Nzd answered with a real, live, two-sided
# USDC/NZD book (104 bids, 59 asks, read 2026-10-02). Coins.ph's USDCPHP
# depth book and exchangeInfo "trading" status are the same shared off-ramp
# book SGD->PHP's variant already confirmed live. IR's own nz/fees page --
# Cloudflare-blocked direct (HTTP 403) same as every prior read, fetched
# through the same r.jina.ai rendering-proxy workaround -- still lists
# "USD Coin | Arbitrum One | 1.0 USDC", confirming (not assuming) the
# withdrawal table is the one venue-wide schedule, identical on the NZ page
# too. This is the withdrawal fee only: NZD->PHP's base CORRIDORS entry
# separately records that IR has no free NZD deposit method below NZD 50,000
# (SWIFT-only, unpriced gap) -- that gap belongs to the deposit leg, which
# this variant does not touch or fix.
#
# SEB-189, queue item 0.1, second slice (AUD->PHP). Re-probed live, not
# carried over: api.independentreserve.com/Public/GetOrderBook?primaryCurrencyCode=
# Usdc&secondaryCurrencyCode=Aud answered with a real, live, two-sided
# USDC/AUD book (103 bids, 58 asks, read 2026-10-03). Coins.ph's USDCPHP
# depth book and exchangeInfo "trading" status are the same shared off-ramp
# book the SGD->PHP and NZD->PHP variants already confirmed live -- re-checked
# here, still trading. IR's own au/fees page -- Cloudflare-blocked direct
# (HTTP 403) same as every prior read, fetched through the same r.jina.ai
# rendering-proxy workaround -- still lists "USD Coin | Arbitrum One | 1.0
# USDC", confirming (not assuming) the withdrawal table is the one venue-wide
# schedule, identical on the AU page too.
CORRIDOR_VARIANTS = {
    "SGD->PHP": [
        {
            "stable": "USDC", "network": "ArbitrumOne",
            "offramp_symbol": "USDCPHP",
            "network_fee_stable": 1.0,
            "verified": "2026-10-02",
        },
    ],
    "NZD->PHP": [
        {
            "stable": "USDC", "network": "ArbitrumOne",
            "offramp_symbol": "USDCPHP",
            "network_fee_stable": 1.0,
            "verified": "2026-10-02",
        },
    ],
    "AUD->PHP": [
        {
            "stable": "USDC", "network": "ArbitrumOne",
            "offramp_symbol": "USDCPHP",
            "network_fee_stable": 1.0,
            "verified": "2026-10-03",
        },
    ],
    # SEB-248: WazirX USDCINR depth probe passed (26 asks, 23 bids, 1.75%
    # spread, live 2026-10-05). USDC/INR is listed active under INR Markets
    # on wazirx.com/fees, same 0.40% base-tier flat fee as USDT/INR. WazirX
    # only supports USDC deposits on Ethereum (ERC20) -- no Arbitrum, Solana
    # or Base -- so Ethereum is the only common chain with both Coinbase and
    # Independent Reserve.
    #
    # USD->INR USDC variant NOT WIRED: Coinbase Exchange has no USDC-USD pair
    # (confirmed live 2026-10-05, api.exchange.coinbase.com/products -- USDC
    # lists as base only against SGD, EUR, BRL, GBP, AUD, CAD, INR, never
    # USD). A USDC onramp from USD would need a two-hop USD->USDT->USDC path
    # that fetch_onramp_coinbase does not support, and the issue spec says
    # "reuse decompose() unchanged", which rules out adding it here.
    #
    # SGD->INR: Independent Reserve lists USDC/SGD with a real, live two-sided
    # book (60 ask levels, confirmed live 2026-10-05 -- same book already
    # verified for SGD->PHP's USDC variant). IR USDC/ETH withdrawal: 10.0 USDC
    # (independentreserve.com/fees, read 2026-10-05).
    "SGD->INR": [
        {
            "stable": "USDC", "network": "Ethereum",
            "offramp_symbol": "usdcinr",
            "network_fee_stable": 10.0,
            "verified": "2026-10-05",
        },
    ],
    # SEB-255, 2026-10-09: a second USD on-ramp that can send USDT over Tron, which Coinbase cannot.
    # Candidates tried, with the outcome (all live-checked 2026-10-09):
    #   Kraken   QUALIFIES. Public book api.kraken.com/0/public/Depth?pair=USDTUSD answers (asks 0.99914,
    #            9.9M deep). Kraken's own withdrawal table (support.kraken.com/articles/360000767986,
    #            read 2026-10-09) lists "Tether USD (Tron, USDT - Tron)" with a flat fee of 1.00 USDT
    #            and a 6.00 minimum. Its fee schedule for stablecoin pairs in the base currency
    #            (kraken.com/features/fee-schedule, same date) is 0.20% maker and 0.20% taker at the
    #            base tier ($0+ 30-day volume).
    #   Coinbase already answered: no Tron (see USD->NGN above). Not re-probed.
    # Modelled exactly like the existing Coinbase path: the book walk, the on-ramp trading fee and the
    # network withdrawal fee. Funding the account in USD (ACH or wire) is not modelled for either
    # on-ramp. Kraken's fee is far higher than Coinbase's 1 bp (20 bps against 1 bp), so this variant is
    # NOT cheaper on the numbers modelled here; what it removes is the unmodelled Ethereum gas the
    # Coinbase path leaves at zero. It is published beside the existing path, not in place of it.
    "USD->NGN": [
        {
            "stable": "USDT", "network": "Tron",
            "offramp_symbol": "USDTNGN",
            "network_fee_stable": 1.0,
            "onramp": {"venue": "Kraken", "pair": "USDTUSD", "taker_bps": 20.0, "maker_bps": 20.0,
                       "verified": "2026-10-09"},
            "withdraw_pct": 0.0, "withdraw_pct_cap": None,
            "verified": "2026-10-09",
        },
    ],
    "USD->INR": [
        {
            "stable": "USDT", "network": "Tron",
            "offramp_symbol": "usdtinr",
            "network_fee_stable": 1.0,
            "onramp": {"venue": "Kraken", "pair": "USDTUSD", "taker_bps": 20.0, "maker_bps": 20.0,
                       "verified": "2026-10-09"},
            "withdraw_pct": 0.0, "withdraw_pct_cap": None,
            "verified": "2026-10-09",
        },
    ],
}

VARIANTS_SIDECAR = os.path.join(HERE, "data", "corridor_variants.csv")
VARIANT_FIELDS = [
    "ts", "corridor", "stable", "network", "notional_src",
    "network_fee_stable", "landed_taker", "cost_bps_taker",
    "landed_maker", "cost_bps_maker", "source_ok", "errors",
]

FIELDS = [
    "ts", "corridor", "src", "dst", "stable", "notional_src",
    # benchmark
    "mid_src_per_usd", "mid_dst_per_usd", "mid_src_dst",
    # on-ramp leg
    "onramp_venue", "onramp_top_ask", "onramp_vwap", "onramp_slip_bps",
    "onramp_filled", "onramp_basis_bps",
    # off-ramp leg
    "offramp_venue", "offramp_top_bid", "offramp_vwap", "offramp_slip_bps",
    "offramp_filled", "offramp_basis_bps",
    "offramp_depth_top_level", "offramp_depth_1pct",
    # fee regime in force for THIS row
    "fee_on_taker_bps", "fee_on_maker_bps",
    "fee_off_taker_bps", "fee_off_maker_bps",
    "network_fee_stable", "fees_verified",
    # outcomes
    "landed_taker", "cost_bps_taker", "landed_maker", "cost_bps_maker",
    "baseline_provider", "baseline_landed", "baseline_cost_bps",
    "crypto_wins_taker", "crypto_wins_maker",
    # provenance
    "source_ok", "errors",
]


# ------------------------------------------------------------- pure core
def norm_levels(raw):
    """Accept [[p,q],...] or [{'price':..,'volume':..},...]; return [(p,q)]."""
    out = []
    for lvl in raw or []:
        try:
            if isinstance(lvl, dict):
                p = next(lvl[k] for k in ("price", "Price") if k in lvl)
                q = next(lvl[k] for k in ("volume", "Volume", "qty", "quantity")
                         if k in lvl)
            else:
                p, q = lvl[0], lvl[1]
            p, q = float(p), float(q)
            if p > 0 and q > 0:
                out.append((p, q))
        except (StopIteration, KeyError, IndexError, TypeError, ValueError):
            continue
    return out


def walk_buy(asks, budget):
    """Spend `budget` of quote, consuming asks ascending. -> (base, vwap, filled)."""
    base = spent = 0.0
    for p, q in asks:
        cost = p * q
        if spent + cost <= budget:
            base += q
            spent += cost
        else:
            rem = budget - spent
            base += rem / p
            spent = budget
            return base, (spent / base if base else None), True
    return base, (spent / base if base else None), False


def walk_sell(bids, amount):
    """Sell `amount` of base, consuming bids descending. -> (quote, vwap, filled)."""
    quote = sold = 0.0
    for p, q in bids:
        if sold + q <= amount:
            quote += p * q
            sold += q
        else:
            quote += p * (amount - sold)
            sold = amount
            return quote, (quote / sold if sold else None), True
    return quote, (quote / sold if sold else None), False


def depth_within_pct(bids, pct=0.01):
    """Base units sellable before price falls `pct` below top-of-book."""
    if not bids:
        return 0.0
    floor = bids[0][0] * (1 - pct)
    return sum(q for p, q in bids if p >= floor)


def remaining_after_sell(bids, amount):
    """The unconsumed remainder of `bids` after selling `amount` of base into
    them, consumed descending in the same order walk_sell already uses.
    Does not mutate `bids`. -> [(p, q), ...], possibly empty.
    """
    sold = 0.0
    for i, (p, q) in enumerate(bids):
        if sold + q <= amount:
            sold += q
            continue
        return [(p, q - (amount - sold))] + list(bids[i + 1:])
    return []


def bitso_bids(payload):
    """Bitso payload.bids ({book, price, amount} dicts) -> [(p, q)].

    Pure so it can be tested offline against a real payload. Kept OUT of
    norm_levels on purpose: norm_levels is corridor 1's parser too, and
    teaching it the key "amount" would change behaviour for every venue.
    """
    raw = (payload or {}).get("payload") or {}
    levels = [(lvl.get("price"), lvl.get("amount"))
              for lvl in (raw.get("bids") or []) if isinstance(lvl, dict)]
    return norm_levels(levels)


def bps(x):
    return None if x is None else round(x * 1e4, 2)


def basis_bps_cost(venue_price, usd_mid, side):
    """
    Peg deviation expressed as a COST in bps (positive = you lose).

    side='buy'  : you pay `venue_price` of local per stable. Above USD mid = loss.
    side='sell' : you receive `venue_price` of local per stable. Below mid = loss.
    """
    if not venue_price or not usd_mid:
        return None
    if side == "buy":
        return bps((venue_price - usd_mid) / usd_mid)
    return bps((usd_mid - venue_price) / usd_mid)


def ramp_fee_units(leg_cfg, base_amount):
    """Deposit/withdrawal ramp fee, in that leg's own currency units.

    `base_amount` is what the fee is charged against: the notional being
    deposited for a deposit leg, the amount that landed for a withdrawal
    leg. fee_type "free" and "gap" both return 0.0 -- a "gap" is NOT a
    verified free rail, it means no published fee could be found, and
    charging 0.0 for it must never be read as "measured, and it's free".
    Callers that need to tell the two apart use the *_measured flags
    decompose() also records, and the ramp waterfall sidecar carries the
    distinction through to the reader-facing pages.
    """
    if not leg_cfg:
        return 0.0
    ft = leg_cfg.get("fee_type")
    if ft == "flat":
        return leg_cfg["fee_value"]
    if ft == "pct":
        return base_amount * leg_cfg["fee_value"]
    return 0.0  # "free" (verified zero) or "gap" (unmeasured, never invented)


def decompose(notional, on_book, off_book, mids, cfg):
    """
    Full round trip for one notional under both execution regimes.
    Pure: takes parsed books + rates, returns a dict. No I/O.
    """
    src_usd, dst_usd = mids["src_per_usd"], mids["dst_per_usd"]
    mid = dst_usd / src_usd if (src_usd and dst_usd) else None

    on_fee = cfg["onramp"]["taker_bps"] / 1e4
    off_fee = cfg["offramp"]["taker_bps"] / 1e4
    on_fee_mk = cfg["onramp"]["maker_bps"] / 1e4
    off_fee_mk = cfg["offramp"]["maker_bps"] / 1e4
    # The network leg has two shapes across venues: a flat per-send fee (IR
    # charges 4.0 USDT on Tron) and a proportional processing fee (Coinbase
    # charges 0.01% of the amount, capped at 20 USDT). Model both; a corridor
    # that only has one leaves the other at zero.
    netfee_flat = cfg["network_fee_stable"]
    pct = cfg.get("withdraw_pct", 0.0)
    pct_cap = cfg.get("withdraw_pct_cap")

    # The two ramp legs: the bank fee to get the sender's money ONTO the
    # on-ramp exchange (src currency, charged against the notional), and the
    # bank fee to get it OUT of the off-ramp exchange to a bank account (dst
    # currency, charged against what actually landed). "gap" means no
    # published free method could be found at retail size -- it costs 0.0
    # here (never invented) but is flagged, not silently treated as free;
    # see the ramp waterfall sidecar and CORRIDORS' own citation comments.
    dep_cfg, wd_cfg = cfg.get("deposit"), cfg.get("withdrawal")
    dep_measured = bool(dep_cfg) and dep_cfg.get("fee_type") != "gap"
    wd_measured = bool(wd_cfg) and wd_cfg.get("fee_type") != "gap"
    deposit_fee_src = ramp_fee_units(dep_cfg, notional)
    adjusted_notional = max(0.0, notional - deposit_fee_src)

    asks, bids = on_book.get("asks", []), off_book.get("bids", [])
    top_ask = asks[0][0] if asks else None
    top_bid = bids[0][0] if bids else None

    out = {
        "mid_src_dst": round(mid, 6) if mid else None,
        "onramp_top_ask": top_ask,
        "offramp_top_bid": top_bid,
        "onramp_basis_bps": basis_bps_cost(top_ask, src_usd, "buy"),
        "offramp_basis_bps": basis_bps_cost(top_bid, dst_usd, "sell"),
        "offramp_depth_top_level": bids[0][1] if bids else None,
        "offramp_depth_1pct": round(depth_within_pct(bids), 2) if bids else None,
        "ramp_deposit_measured": dep_measured,
        "ramp_withdrawal_measured": wd_measured,
    }

    gross, on_vwap, on_filled = walk_buy(asks, adjusted_notional)
    out["onramp_vwap"] = round(on_vwap, 6) if on_vwap else None
    out["onramp_filled"] = on_filled
    out["onramp_slip_bps"] = (bps((on_vwap - top_ask) / top_ask)
                              if (on_vwap and top_ask) else None)

    for regime, fee_on, fee_off in (("taker", on_fee, off_fee),
                                    ("maker", on_fee_mk, off_fee_mk)):
        bought = gross * (1 - fee_on)
        proc = bought * pct
        if pct_cap is not None:
            proc = min(proc, pct_cap)
        netfee = netfee_flat + proc
        # Record what the network leg ACTUALLY cost at this size, in USDT, in
        # the column that already exists. A proportional fee cannot be carried
        # by a single config constant, and samples.csv is frozen -- so the
        # per-row value becomes the effective one rather than the config one.
        if regime == "taker":
            out["network_fee_stable"] = round(netfee, 6)
        stable = bought - netfee
        if stable <= 0:
            out[f"landed_{regime}"] = 0.0
            out[f"cost_bps_{regime}"] = None
            if regime == "taker":
                out["offramp_vwap"] = out["offramp_slip_bps"] = None
                out["offramp_filled"] = False
            continue
        quote, off_vwap, off_filled = walk_sell(bids, stable)
        if regime == "taker":
            # How much is left in the book AFTER this rung's own trade, not
            # the untouched-book figure offramp_depth_top_level/
            # offramp_depth_1pct above already carry (SEB-181). None, not an
            # invented zero, when there was no book to walk in the first
            # place -- same rule those two columns already follow.
            remainder = remaining_after_sell(bids, stable) if bids else []
            out["offramp_depth_top_level_after"] = (
                remainder[0][1] if remainder else (0.0 if bids else None))
            out["offramp_depth_1pct_after"] = (
                round(depth_within_pct(remainder), 2) if bids else None)
        landed_before_withdrawal = quote * (1 - fee_off)
        withdrawal_fee_dst = ramp_fee_units(wd_cfg, landed_before_withdrawal)
        landed = max(0.0, landed_before_withdrawal - withdrawal_fee_dst)
        out[f"landed_{regime}"] = round(landed, 2)
        out[f"cost_bps_{regime}"] = (bps(1 - landed / (notional * mid))
                                     if (mid and notional) else None)
        if regime == "taker" and mid and notional:
            # The waterfall shown on corridor.html used to reconstruct its
            # three bars as onramp_basis_bps + fee_on_taker_bps (etc.), summed
            # independently on the original notional. That is a parallel
            # approximation of a chain of multiplicative steps -- a fee applied
            # AFTER basis has already shrunk the amount is not the same as the
            # same fee applied to the original notional -- so the bars did not
            # sum to cost_bps_taker (SEB-corridor-reconcile: off by ~1.5bps on
            # a real AUD->PHP row, exactly this drift's known order of
            # magnitude). Fixed by walking the SAME chain decompose() already
            # computes (deposit -> gross -> bought -> stable -> quote ->
            # landed) and taking each step's own delta, in dst-currency terms,
            # against the fair (zero-friction) target. Telescoping guarantees
            # the parts sum to cost_bps_taker exactly, to the cent, by
            # construction -- not approximately, and not by adjusting a
            # displayed number.
            target = notional * mid
            L1 = adjusted_notional * mid
            L2, L3 = bought * dst_usd, stable * dst_usd
            L4 = landed_before_withdrawal
            out["wf_deposit_bps"] = round(1e4 * (target - L1) / target, 2)
            out["wf_buy_bps"] = round(1e4 * (L1 - L2) / target, 2)
            out["wf_move_bps"] = round(1e4 * (L2 - L3) / target, 2)
            out["wf_sell_bps"] = round(1e4 * (L3 - L4) / target, 2)
            # The withdrawal leg is the remainder against cost_bps_taker, not
            # its own independently-rounded value -- summing four numbers each
            # rounded on their own does not reliably reproduce a fifth,
            # separately rounded number (classic sum-of-rounded-parts drift,
            # same reasoning that used to anchor wf_sell_bps here before this
            # leg existed). Anchoring the LAST leg to what the other four,
            # plus the already-stored total, require is what actually
            # guarantees the bars sum to the cent.
            out["wf_withdrawal_bps"] = round(
                out["cost_bps_taker"] - out["wf_deposit_bps"] - out["wf_buy_bps"]
                - out["wf_move_bps"] - out["wf_sell_bps"], 2)
        if regime == "taker":
            out["offramp_vwap"] = round(off_vwap, 6) if off_vwap else None
            out["offramp_filled"] = off_filled
            out["offramp_slip_bps"] = (bps((top_bid - off_vwap) / top_bid)
                                       if (off_vwap and top_bid) else None)
    return out


def pick_baseline(quotes):
    """Best incumbent fiat rail at this instant -> (name, landed)."""
    if not quotes:
        return None, None
    best = max(quotes, key=lambda q: q[1])
    return best[0], best[1]


def parse_wise(payload):
    """Wise comparison API -> [(provider, landed), ...].

    DELIVERY FIELD, PROBED AND NOT FOUND (SEB-191, 2026-10-02). SEB-176 added
    a stated-delivery-time sidecar fed by providers' own direct APIs; this
    comparison feed (this function's own `payload`, from fetch_baseline()
    calling api.wise.com/v3/comparisons) is a different, unchecked payload
    for the four rails that have no direct API call anywhere in this repo --
    PayPal, Western Union, HSBC Singapore, OFX -- plus Instarem, which does
    have a direct call (collector_providers.py) but no delivery field on it
    either (see that file's module docstring).

    Live-probed sourceCurrency=SGD&targetCurrency=PHP at every ladder size
    (200/1000/5000/25000/50000) -- the exact call fetch_baseline() makes.
    Every quote object carries a `deliveryEstimation` dict
    ({"deliveryDate", "duration", "durationType", "providerGivesEstimate"}).
    For Instarem, PayPal, HSBC Singapore, Western Union and OFX, at every
    size, `providerGivesEstimate` was the only populated field (always
    `true`) -- `deliveryDate`, `duration` and `durationType` were `null`
    every time, for all five. That is the feed saying "this provider
    supports giving an estimate" with no estimate attached, not a delivery
    time with nothing to read -- nothing to wire. (The feed's own Wise
    entry DOES carry a real duration -- e.g. "PT1S" at S$200, "PT65H46M..."
    at S$50,000 -- but Wise already has a direct, narrower delivery read
    from its own quote API, SEB-176's wise_delivery(); out of scope here.)
    No parser or sidecar change follows from this probe: there is no field
    to extend parse_wise() with for any of the five rails this issue asked
    about.
    """
    out = []
    for p in payload.get("providers", []):
        name = p.get("name") or p.get("alias")
        for q in p.get("quotes", []):
            amt = q.get("receivedAmount")
            if amt is None and q.get("rate") is not None:
                amt = (q.get("sourceAmount") or 0) - (q.get("fee") or 0)
                amt *= q["rate"]
            if name and amt:
                out.append((name, float(amt)))
    return out


def provider_rows(ts, notional, quotes, mid):
    """
    The full incumbent panel for one size: one row per provider, ranked cheapest
    first (rank 1 = highest landed = lowest cost). Best quote kept per provider.
    Never raises -- an empty/unavailable panel becomes a single source_ok=False
    row, so a Wise outage is recorded in providers.csv but does NOT fail the
    corridor step (samples.csv keeps landing with baseline=None).
    """
    try:
        if not quotes:
            raise ValueError("empty panel")
        best = {}
        for name, landed in quotes:
            if landed and (name not in best or landed > best[name]):
                best[name] = landed
        if not best:
            raise ValueError("no priced providers")
        ranked = sorted(best.items(), key=lambda kv: kv[1], reverse=True)
        return [{
            "ts_utc": ts, "notional_src": notional, "provider": name,
            "landed_dst": round(landed, 2),
            "cost_bps": bps(1 - landed / (notional * mid)) if (mid and notional) else None,
            "rank": i, "source_ok": True, "error": "",
        } for i, (name, landed) in enumerate(ranked, 1)]
    except Exception as e:
        return [{
            "ts_utc": ts, "notional_src": notional, "provider": None,
            "landed_dst": None, "cost_bps": None, "rank": None,
            "source_ok": False, "error": f"{type(e).__name__}:{e}"[:200],
        }]


# ------------------------------------------------------------------ I/O
def get_json(url):
    r = requests.get(url, timeout=HTTP_TIMEOUT, headers=UA)
    r.raise_for_status()
    return r.json()


def fetch_mids(src, dst):
    """USD-base mids for both legs, from one call. -> {src_per_usd, dst_per_usd}."""
    d = get_json("https://open.er-api.com/v6/latest/USD")
    rates = d.get("rates") or {}
    return {"src_per_usd": float(rates[src]), "dst_per_usd": float(rates[dst])}


def fetch_onramp(cfg, src):
    # Dispatch on the configured venue. IndependentReserve stays the default
    # path, unchanged -- a new corridor must not be able to break corridor 1.
    if cfg["onramp"]["venue"] == "Coinbase":
        return fetch_onramp_coinbase(cfg, src)
    if cfg["onramp"]["venue"] == "Kraken":
        return fetch_onramp_kraken(cfg)
    stable = cfg["stable"].capitalize()
    d = get_json("https://api.independentreserve.com/Public/GetOrderBook"
                 f"?primaryCurrencyCode={stable}&secondaryCurrencyCode={src.capitalize()}")
    asks = sorted(norm_levels(d.get("SellOrders")), key=lambda x: x[0])
    return {"asks": asks}


def fetch_onramp_coinbase(cfg, src):
    """Coinbase Exchange public book, level 2 (aggregated per price).

    Verified live 2026-08-19: public, no auth. Asks arrive as
    [price, size, num_orders] arrays -- norm_levels reads [0] and [1] and
    ignores the third element, so the payload needs no reshaping.
    """
    pair = f"{cfg['stable']}-{src}"
    d = get_json(f"https://api.exchange.coinbase.com/products/{pair}/book?level=2")
    asks = sorted(norm_levels(d.get("asks")), key=lambda x: x[0])
    return {"asks": asks}


def fetch_onramp_kraken(cfg):
    """Kraken public book (SEB-255), no auth. Depth answers {"error": [], "result": {"USDTZUSD":
    {"asks": [[price, volume, timestamp], ...], "bids": [...]}}}; the pair's key is not the name asked
    for, so the one result is taken whatever it is called. norm_levels reads [0] and [1] and ignores the
    timestamp."""
    d = get_json(f"https://api.kraken.com/0/public/Depth?pair={cfg['onramp']['pair']}&count=500")
    if d.get("error"):
        raise ValueError("kraken:" + ";".join(d["error"]))
    book = next(iter((d.get("result") or {}).values()), {})
    asks = sorted(norm_levels(book.get("asks")), key=lambda x: x[0])
    return {"asks": asks}


def fetch_offramp(cfg):
    # Dispatch on the configured venue. Coins.ph stays the default path.
    venue = cfg["offramp"]["venue"]
    if venue == "Bitso":
        return fetch_offramp_bitso(cfg)
    if venue == "Luno":
        return fetch_offramp_luno(cfg)
    if venue == "WazirX":
        return fetch_offramp_wazirx(cfg)
    # NOTE: api.pro.coins.ph -- `api.coins.ph` is NXDOMAIN and silently killed
    # 34 days of collection. Do not "simplify" this hostname.
    sym = cfg["offramp"]["symbol"]
    d = get_json(f"https://api.pro.coins.ph/openapi/quote/v1/depth?symbol={sym}&limit=200")
    bids = sorted(norm_levels(d.get("bids")), key=lambda x: x[0], reverse=True)
    return {"bids": bids}


def fetch_offramp_luno(cfg):
    """Luno public order book. Verified live 2026-09-29, no auth.

    api.luno.com/api/1/orderbook returns bids/asks as lists of
    {"price": "...", "volume": "..."} dicts -- exactly the two keys
    norm_levels already recognises ("price"/"Price", "volume"/"Volume"/
    "qty"/"quantity"), so this needs no reshaping at all, unlike Bitso's
    "amount" key.
    """
    sym = cfg["offramp"]["symbol"]
    d = get_json(f"https://api.luno.com/api/1/orderbook?pair={sym}")
    bids = sorted(norm_levels(d.get("bids")), key=lambda x: x[0], reverse=True)
    return {"bids": bids}


def fetch_offramp_wazirx(cfg):
    """WazirX public order book. Verified live 2026-09-29, no auth.

    api.wazirx.com/sapi/v1/depth returns bids/asks as [price, quantity]
    string-array pairs -- norm_levels's other native shape, same as
    Independent Reserve's array-of-arrays. limit=500 comfortably covers the
    largest ladder rung (S$50,000-equivalent); the live book measured at
    ~500 levels deep carries INR 1.8 trillion of notional on the ask side
    alone, so 500 never truncates a real walk at this corridor's sizes.
    """
    sym = cfg["offramp"]["symbol"]
    d = get_json(f"https://api.wazirx.com/sapi/v1/depth?symbol={sym}&limit=500")
    bids = sorted(norm_levels(d.get("bids")), key=lambda x: x[0], reverse=True)
    return {"bids": bids}


def fetch_offramp_bitso(cfg):
    """Bitso public order book. Verified live 2026-08-19.

    Levels arrive under payload.bids as dicts {book, price, amount}. "amount"
    is NOT one of the quantity keys norm_levels knows, so those dicts would be
    silently dropped -- an empty book, recorded as a real one. Map to
    (price, amount) tuples here instead of teaching norm_levels a new key:
    norm_levels is shared with corridor 1 and stays untouched.
    """
    sym = cfg["offramp"]["symbol"]
    d = get_json(f"https://api.bitso.com/v3/order_book/?book={sym}")
    return {"bids": sorted(bitso_bids(d), key=lambda x: x[0], reverse=True)}


def fetch_baseline(src, dst, amount):
    d = get_json("https://api.wise.com/v3/comparisons"
                 f"?sourceCurrency={src}&targetCurrency={dst}&sendAmount={amount}")
    return parse_wise(d)


# ------------------------------------------------------------- collection
def collect(corridor_key, cfg):
    """One sample across the whole ladder. Never raises; records failures."""
    ts = dt.datetime.now(dt.timezone.utc).isoformat()
    src, dst = cfg["src"], cfg["dst"]
    errors, ok = [], True

    try:
        mids = fetch_mids(src, dst)
    except Exception as e:
        errors.append(f"mid:{type(e).__name__}:{e}")
        mids, ok = {"src_per_usd": None, "dst_per_usd": None}, False

    try:
        on_book = fetch_onramp(cfg, src)
    except Exception as e:
        errors.append(f"onramp:{type(e).__name__}:{e}")
        on_book, ok = {"asks": []}, False

    try:
        off_book = fetch_offramp(cfg)
    except Exception as e:
        errors.append(f"offramp:{type(e).__name__}:{e}")
        off_book, ok = {"bids": []}, False

    fees_verified = "|".join(
        f"{k}:{cfg[k].get('verified') or 'UNVERIFIED'}" for k in ("onramp", "offramp"))

    rows, prows = [], []
    for notional in cfg["ladder"]:
        d = decompose(notional, on_book, off_book, mids, cfg)
        mid = d["mid_src_dst"]

        # The Wise comparison panel is SUPPLEMENTARY: a panel failure records a
        # source_ok=False row in providers.csv but must NOT fail the corridor
        # sample (baseline just goes missing, exactly as before). So it does not
        # touch `ok`, and its errors live in providers.csv, not the corridor row.
        try:
            quotes = fetch_baseline(src, dst, notional)
            bname, blanded = pick_baseline(quotes)
            prows.extend(provider_rows(ts, notional, quotes, mid))
        except Exception as e:
            bname, blanded = None, None
            prows.append({
                "ts_utc": ts, "notional_src": notional, "provider": None,
                "landed_dst": None, "cost_bps": None, "rank": None,
                "source_ok": False, "error": f"baseline:{type(e).__name__}:{e}"[:200],
            })

        bcost = bps(1 - blanded / (notional * mid)) if (blanded and mid) else None

        rows.append({
            "ts": ts, "corridor": corridor_key, "src": src, "dst": dst,
            "stable": cfg["stable"], "notional_src": notional,
            "mid_src_per_usd": mids["src_per_usd"], "mid_dst_per_usd": mids["dst_per_usd"],
            "onramp_venue": cfg["onramp"]["venue"], "offramp_venue": cfg["offramp"]["venue"],
            "fee_on_taker_bps": cfg["onramp"]["taker_bps"],
            "fee_on_maker_bps": cfg["onramp"]["maker_bps"],
            "fee_off_taker_bps": cfg["offramp"]["taker_bps"],
            "fee_off_maker_bps": cfg["offramp"]["maker_bps"],
            "network_fee_stable": cfg["network_fee_stable"],
            "fees_verified": fees_verified,
            "baseline_provider": bname, "baseline_landed": blanded,
            "baseline_cost_bps": bcost,
            "crypto_wins_taker": (None if (bcost is None or d["cost_bps_taker"] is None)
                                  else d["cost_bps_taker"] < bcost),
            "crypto_wins_maker": (None if (bcost is None or d["cost_bps_maker"] is None)
                                  else d["cost_bps_maker"] < bcost),
            "source_ok": ok, "errors": "; ".join(errors)[:500],
            **d,
        })
    return rows, prows


def collect_variants(corridor_key, cfg):
    """One sample across the ladder for every priced alternate path this
    corridor has (CORRIDOR_VARIANTS) -- a different stablecoin and/or network
    than the corridor's own modelled path, run through the SAME decompose()
    against its own live books. Independent fetches, same shape as collect():
    never raises, records failures in the row instead.
    """
    out = []
    for variant in CORRIDOR_VARIANTS.get(corridor_key, []):
        ts = dt.datetime.now(dt.timezone.utc).isoformat()
        src = cfg["src"]
        vcfg = {**cfg, "stable": variant["stable"],
                "network_fee_stable": variant["network_fee_stable"],
                "offramp": {**cfg["offramp"], "symbol": variant["offramp_symbol"]}}
        if variant.get("onramp"):        # a different on-ramp venue, with its own published fees (SEB-255)
            vcfg["onramp"] = variant["onramp"]
            vcfg["withdraw_pct"] = variant.get("withdraw_pct", 0.0)
            vcfg["withdraw_pct_cap"] = variant.get("withdraw_pct_cap")
        errors, ok = [], True
        try:
            mids = fetch_mids(src, cfg["dst"])
        except Exception as e:
            errors.append(f"mid:{type(e).__name__}:{e}")
            mids, ok = {"src_per_usd": None, "dst_per_usd": None}, False
        try:
            on_book = fetch_onramp(vcfg, src)
        except Exception as e:
            errors.append(f"onramp:{type(e).__name__}:{e}")
            on_book, ok = {"asks": []}, False
        try:
            off_book = fetch_offramp(vcfg)
        except Exception as e:
            errors.append(f"offramp:{type(e).__name__}:{e}")
            off_book, ok = {"bids": []}, False

        for notional in cfg["ladder"]:
            d = decompose(notional, on_book, off_book, mids, vcfg)
            out.append({
                "ts": ts, "corridor": corridor_key, "stable": variant["stable"],
                "network": variant["network"], "notional_src": notional,
                "network_fee_stable": d.get("network_fee_stable"),
                "landed_taker": d.get("landed_taker"),
                "cost_bps_taker": d.get("cost_bps_taker"),
                "landed_maker": d.get("landed_maker"),
                "cost_bps_maker": d.get("cost_bps_maker"),
                "source_ok": ok, "errors": "; ".join(errors)[:500],
            })
    return out


def utc_hour(now=None):
    """The current UTC hour, truncated -- the idempotency key for a capture."""
    return (now or dt.datetime.now(dt.timezone.utc)).replace(
        minute=0, second=0, microsecond=0)


def captured_this_hour(path, ts_field, now=None, corridor=None):
    """True if `path` already holds a row stamped in the current UTC hour.

    The schedule fires at :17 and :47 so that GitHub dropping one fire still
    leaves a capture for the hour. That only buys redundancy if the second fire
    is a no-op when the first landed -- otherwise it buys duplicate rows.

    Rows are append-only and in order, so the last row decides. Deliberately
    duplicated in collector_basis.py rather than shared: the two layers stay
    import-independent, so a break in one cannot take down the other.

    `corridor`, when set, narrows the question to rows of that corridor. Two
    corridors share samples.csv, so without it the first corridor captured in
    an hour would gate the second one out of that hour entirely.
    """
    if not os.path.exists(path):
        return False
    last = None
    with open(path, newline="") as f:
        for row in csv.DictReader(f):
            if corridor is not None and row.get("corridor") != corridor:
                continue
            last = row
    if not last or not last.get(ts_field):
        return False
    try:
        ts = dt.datetime.fromisoformat(last[ts_field])
    except ValueError:
        return False
    if ts.tzinfo is None:
        ts = ts.replace(tzinfo=dt.timezone.utc)
    return utc_hour(ts.astimezone(dt.timezone.utc)) == utc_hour(now)


def append(rows):
    os.makedirs(os.path.dirname(SAMPLES), exist_ok=True)
    new = not os.path.exists(SAMPLES)
    with open(SAMPLES, "a", newline="") as f:
        w = csv.DictWriter(f, fieldnames=FIELDS, extrasaction="ignore")
        if new:
            w.writeheader()
        w.writerows(rows)
    return SAMPLES


def providers_path(cfg):
    """Panel file for this corridor. providers.csv has no corridor column and a
    frozen schema, so each corridor gets its own file with the SAME header."""
    return os.path.join(HERE, "data", cfg.get("providers_file", "providers.csv"))


WATERFALL_SIDECAR = os.path.join(HERE, "data", "corridor_waterfall.csv")
WATERFALL_FIELDS = ["ts", "corridor", "notional_src", "wf_buy_bps", "wf_move_bps", "wf_sell_bps"]


def append_waterfall(rows, path=WATERFALL_SIDECAR):
    """The exact-reconciling waterfall legs, keyed the same as samples.csv but
    written separately -- samples.csv's header is frozen, this is new. Only
    rows that actually have the three fields (decompose() skips them when
    stable<=0, same as every other taker-regime field) are written; a missing
    row here is corridor.html's cue to say so, not to invent a number.
    """
    wrows = [{"ts": r["ts"], "corridor": r["corridor"], "notional_src": r["notional_src"],
              "wf_buy_bps": r.get("wf_buy_bps"), "wf_move_bps": r.get("wf_move_bps"),
              "wf_sell_bps": r.get("wf_sell_bps")}
             for r in rows if r.get("wf_buy_bps") is not None]
    if not wrows:
        return None
    os.makedirs(os.path.dirname(path), exist_ok=True)
    new = not os.path.exists(path)
    with open(path, "a", newline="") as f:
        w = csv.DictWriter(f, fieldnames=WATERFALL_FIELDS)
        if new:
            w.writeheader()
        w.writerows(wrows)
    return path


RAMP_WATERFALL_SIDECAR = os.path.join(HERE, "data", "ramp_waterfall.csv")
RAMP_WATERFALL_FIELDS = [
    "ts", "corridor", "notional_src", "wf_deposit_bps", "wf_withdrawal_bps",
    "deposit_measured", "withdrawal_measured",
]


def append_ramp_waterfall(rows, path=RAMP_WATERFALL_SIDECAR):
    """The two ramp legs (deposit into the on-ramp exchange, withdrawal out
    of the off-ramp exchange), same sidecar pattern as WATERFALL_SIDECAR and
    keyed the same way (ts + corridor + notional_src) so corridor.html can
    join it against corridor_waterfall.csv's three legs with one lookup.

    deposit_measured / withdrawal_measured carry the difference between "we
    checked and it's free" and "we could not find a published fee" (a gap
    contributes 0.0 bps here, same as a genuinely free rail, but the reader
    -facing pages must say which -- see ramp_fee_units()'s own docstring).
    """
    wrows = [{"ts": r["ts"], "corridor": r["corridor"], "notional_src": r["notional_src"],
              "wf_deposit_bps": r.get("wf_deposit_bps"),
              "wf_withdrawal_bps": r.get("wf_withdrawal_bps"),
              "deposit_measured": r.get("ramp_deposit_measured"),
              "withdrawal_measured": r.get("ramp_withdrawal_measured")}
             for r in rows if r.get("wf_deposit_bps") is not None]
    if not wrows:
        return None
    os.makedirs(os.path.dirname(path), exist_ok=True)
    new = not os.path.exists(path)
    with open(path, "a", newline="") as f:
        w = csv.DictWriter(f, fieldnames=RAMP_WATERFALL_FIELDS)
        if new:
            w.writeheader()
        w.writerows(wrows)
    return path


DEPTH_SIDECAR = os.path.join(HERE, "data", "samples_depth.csv")
DEPTH_SIDECAR_FIELDS = [
    "ts", "corridor", "notional_src",
    "offramp_depth_top_level_after", "offramp_depth_1pct_after",
]
# Every corridor corridor.html prices (ROADMAP item 6 scoped depth to
# corridor.html, never index.html's wide-layer board, which has no order
# book to walk) -- decompose() already computes this for all of them.
DEPTH_SIDECAR_CORRIDORS = {
    "SGD->PHP", "AUD->PHP", "NZD->PHP", "USD->MXN",
    "USD->NGN", "USD->INR", "SGD->INR",
}


def append_depth_sidecar(rows, path=DEPTH_SIDECAR):
    """Per-ladder-size remaining depth after that rung's own trade (SEB-181),
    keyed the same way as the other sidecars (ts + corridor + notional_src)
    so corridor.html can join it against the row the reader has selected.
    samples.csv's own offramp_depth_top_level/offramp_depth_1pct columns stay
    the pre-trade, corridor-wide figures they always were -- this is a
    separate file, not a widened header.
    """
    wrows = [{"ts": r["ts"], "corridor": r["corridor"], "notional_src": r["notional_src"],
              "offramp_depth_top_level_after": r.get("offramp_depth_top_level_after"),
              "offramp_depth_1pct_after": r.get("offramp_depth_1pct_after")}
             for r in rows
             if r["corridor"] in DEPTH_SIDECAR_CORRIDORS
             and r.get("offramp_depth_top_level_after") is not None]
    if not wrows:
        return None
    os.makedirs(os.path.dirname(path), exist_ok=True)
    new = not os.path.exists(path)
    with open(path, "a", newline="") as f:
        w = csv.DictWriter(f, fieldnames=DEPTH_SIDECAR_FIELDS)
        if new:
            w.writeheader()
        w.writerows(wrows)
    return path


def append_providers(prows, path=PROVIDERS):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    new = not os.path.exists(path)
    with open(path, "a", newline="") as f:
        w = csv.DictWriter(f, fieldnames=PROVIDER_FIELDS, extrasaction="ignore")
        if new:
            w.writeheader()
        w.writerows(prows)
    return path


def append_variants(vrows, path=VARIANTS_SIDECAR):
    """Priced alternate stablecoin/network paths (SEB-182) -- own file, own
    header, keyed by (ts, corridor, stable, network, notional_src). Never
    widens samples.csv, which carries only each corridor's own modelled path.
    """
    if not vrows:
        return None
    os.makedirs(os.path.dirname(path), exist_ok=True)
    new = not os.path.exists(path)
    with open(path, "a", newline="") as f:
        w = csv.DictWriter(f, fieldnames=VARIANT_FIELDS, extrasaction="ignore")
        if new:
            w.writeheader()
        w.writerows(vrows)
    return path


def print_panel(prows, src=None):
    """Print the incumbent panel grouped by size (for --verify).

    `src` labels the size column with the corridor's real send currency. The
    hardcoded "S$" was only ever correct for SGD, so SGD (and an unspecified
    src) keep it and corridor 1's output is unchanged; any other corridor gets
    its own currency rather than a wrong symbol.
    """
    if not prows:
        return
    print("\n  Incumbent panel -- Wise comparison (cost = bps below mid-market):")
    for s in sorted({r["notional_src"] for r in prows}):
        ok = sorted((r for r in prows if r["notional_src"] == s and r["source_ok"]),
                    key=lambda r: r["rank"])
        label = f"S${s:,}" if src in (None, "SGD") else f"{src} {s:,}"
        print(f"  {label}  ({len(ok)} providers)")
        for r in ok:
            print(f"    {r['rank']:>2}. {r['provider']:<20} {r['cost_bps']:>8.1f} bps")
        for r in (r for r in prows if r["notional_src"] == s and not r["source_ok"]):
            print(f"    !! panel unavailable: {r['error']}")
    print()


def print_waterfall(rows):
    if not rows:
        return
    r0 = rows[0]
    print(f"\n  {r0['corridor']}  via {r0['stable']}  "
          f"{r0['onramp_venue']} -> {r0['offramp_venue']}   {r0['ts'][:16]}Z")
    # A venue outage leaves these None. Format defensively: this is a display
    # helper, and a crash here runs BEFORE append() -- it would drop the very
    # incomplete row the run exists to record.
    sbps = lambda v: f"{v:+}" if v is not None else "--"
    print(f"  mid {r0['mid_src_dst'] if r0['mid_src_dst'] is not None else '--'}   "
          f"on-ramp basis {sbps(r0['onramp_basis_bps'])} bps   "
          f"off-ramp basis {sbps(r0['offramp_basis_bps'])} bps")
    if "UNVERIFIED" in (r0["fees_verified"] or ""):
        print("  !! fee schedules UNVERIFIED -- largest term in the stack")
    print("  " + "-" * 74)
    print(f"  {'SEND':>8}{'TAKER':>12}{'MAKER':>12}{'BASELINE':>12}"
          f"{'WINNER':>14}{'FILLED':>10}")
    print("  " + "-" * 74)
    for r in rows:
        t, m, b = r["cost_bps_taker"], r["cost_bps_maker"], r["baseline_cost_bps"]
        fmt = lambda v: f"{v:.0f}bps" if v is not None else "--"
        if None in (t, b):
            win = "--"
        elif t < b:
            win = "crypto (taker)"
        elif m is not None and m < b:
            win = "crypto (maker)"
        else:
            win = r["baseline_provider"] or "baseline"
        filled = "yes" if (r["onramp_filled"] and r["offramp_filled"]) else "THIN"
        print(f"  {r['notional_src']:>8,}{fmt(t):>12}{fmt(m):>12}{fmt(b):>12}"
              f"{win:>14}{filled:>10}")
    print("  " + "-" * 74)
    print("  cost = bps below mid-market. maker = posts at top-of-book, pays "
          "maker fee, assumes fill.\n")


def print_variants(vrows):
    if not vrows:
        return
    fmt = lambda v: f"{v:.0f}bps" if v is not None else "--"
    print("  variants:")
    for r in vrows:
        status = "ok" if r["source_ok"] else f"FAIL: {r['errors']}"
        print(f"    {r['stable']}/{r['network']} @ {r['notional_src']:>6,}: "
              f"taker {fmt(r['cost_bps_taker'])}   ({status})")
    print()


# -------------------------------------------------------------- selftest
# Fixtures are REAL payloads captured 2026-08-10, not synthetic. This tests the
# parsers against the shapes the venues actually return -- the exact class of
# bug (wrong host / wrong shape) that killed the previous collector.
IR_FIXTURE = {"SellOrders": [
    {"Price": 1.2781, "Volume": 5000}, {"Price": 1.2785, "Volume": 2912.05491},
    {"Price": 1.27857, "Volume": 65894.96562}]}
COINS_FIXTURE = {"bids": [
    ["60.680000000000000000", "268022.060000000000000000"],
    ["60.670000000000000000", "56845.970000000000000000"],
    ["60.660000000000000000", "122172.710000000000000000"]]}
MIDS_FIXTURE = {"src_per_usd": 1.279634, "dst_per_usd": 60.857717}

# Corridor 2 payloads, captured live 2026-08-19. Coinbase asks carry a THIRD
# element (num_orders) that norm_levels ignores; Bitso levels are dicts keyed
# "amount", which norm_levels does NOT recognise -- the exact shape that would
# silently produce an empty book if fetch_offramp_bitso stopped reshaping them.
COINBASE_FIXTURE = {"asks": [
    ["0.99916", "28060.73", 1], ["0.99917", "2850.6", 2],
    ["0.99919", "36479.8", 2]]}
BITSO_FIXTURE = {"payload": {"bids": [
    {"book": "usdt_mxn", "price": "17.049", "amount": "8797.60"},
    {"book": "usdt_mxn", "price": "17.048", "amount": "1781.4934"},
    {"book": "usdt_mxn", "price": "17.047", "amount": "9642.67"}]}}
MIDS_FIXTURE_MXN = {"src_per_usd": 1.0, "dst_per_usd": 17.060644}

# Corridors 5/6/7 (2026-09-29, SOURCES-2): Luno (Nigeria) and WazirX (India)
# payloads, captured live 2026-09-29. Luno's levels are {"price","volume"}
# dicts -- norm_levels's native dict shape, no reshaping needed, unlike
# Bitso's "amount" key above. WazirX's are [price, quantity] string-array
# pairs -- norm_levels's other native shape, same as Independent Reserve's.
LUNO_FIXTURE = {"asks": [
    {"price": "1373.0001", "volume": "6002.34"},
    {"price": "1373.0001", "volume": "374.40"},
    {"price": "1373.0001", "volume": "3000.00"}],
    "bids": [
    {"price": "1373.0000", "volume": "8550.09"},
    {"price": "1373.0000", "volume": "3000.00"},
    {"price": "1372.0339", "volume": "5655.01"}]}
WAZIRX_DEPTH_FIXTURE = {"asks": [
    ["101.00", "1622.91"], ["101.07", "93.1"], ["101.1", "49.0"],
    ["101.25", "15.49"], ["101.56", "10.08"]],
    "bids": [
    ["100.26", "36.2"], ["100.23", "598.62"], ["100.22", "1147.98"],
    ["100.21", "48.45"], ["100.20", "1500.0"]]}
MIDS_FIXTURE_NGN = {"src_per_usd": 1.0, "dst_per_usd": 1329.375909}
MIDS_FIXTURE_INR = {"src_per_usd": 1.0, "dst_per_usd": 96.069945}
MIDS_FIXTURE_SGD_INR = {"src_per_usd": 1.277664, "dst_per_usd": 96.069945}


def selftest():
    cfg = CORRIDORS["SGD->PHP"]

    on = {"asks": sorted(norm_levels(IR_FIXTURE["SellOrders"]), key=lambda x: x[0])}
    off = {"bids": sorted(norm_levels(COINS_FIXTURE["bids"]),
                          key=lambda x: x[0], reverse=True)}
    assert on["asks"][0] == (1.2781, 5000.0), on["asks"][:1]
    assert off["bids"][0] == (60.68, 268022.06), off["bids"][:1]
    print("  [ok] parsers handle both real payload shapes (dict + string-array)")

    d = decompose(5000, on, off, MIDS_FIXTURE, cfg)

    assert abs(d["mid_src_dst"] - 47.5587) < 1e-3, d["mid_src_dst"]
    assert abs(d["onramp_basis_bps"] - (-12.0)) < 0.5, d["onramp_basis_bps"]
    assert abs(d["offramp_basis_bps"] - 29.2) < 0.5, d["offramp_basis_bps"]
    print(f"  [ok] basis: on-ramp {d['onramp_basis_bps']:+} bps (stable cheap in SG), "
          f"off-ramp {d['offramp_basis_bps']:+} bps (stable cheap in PH)")

    # Verified fees (2026-08-10): IR flat 50 (no maker discount), Coins taker 15 /
    # maker 10, plus IR's published 4.0 USDT Tron withdrawal (2026-08-19).
    # Taker ~92.2; maker ~87.3. These were ~84.6 / ~79.3 while the network leg
    # was carried at an unsourced 1.0 USDT -- the correction is worth ~7.6 bps
    # at S$5,000. At base-tier fees the regimes still sit only ~5 bps apart (the
    # Coins taker/maker spread; IR is flat), and BOTH lose to the ~66 bps fiat
    # baseline by an even wider margin than before.
    assert abs(d["cost_bps_taker"] - 92.2) < 1.0, d["cost_bps_taker"]
    assert abs(d["cost_bps_maker"] - 87.3) < 1.0, d["cost_bps_maker"]
    gap = d["cost_bps_taker"] - d["cost_bps_maker"]
    assert 4.0 < gap < 6.5, gap  # the only base-tier edge is Coins 15->10 bps
    print(f"  [ok] base-tier fees: taker {d['cost_bps_taker']:.1f} vs maker "
          f"{d['cost_bps_maker']:.1f} bps -- {gap:.1f} bps apart (Coins "
          f"maker/taker spread); both lose to ~66 bps Wise")

    # The waterfall's five bars (deposit, buy, move, sell, withdrawal) must
    # reconcile to the taker total EXACTLY, to the cent -- not approximately.
    # (This replaces an earlier version of this test that only checked the
    # independently-summed basis+fee legs landed within 1.5 bps of the total;
    # that ~1.5 bps gap was real, was the corridor.html reader-visible bug it
    # looks like, and is the reason wf_buy_bps/wf_move_bps/wf_sell_bps exist --
    # a sequential decomposition of the same chain decompose() already walks,
    # not a second, parallel one. wf_deposit_bps/wf_withdrawal_bps extend the
    # same chain to the two ramp legs; both are 0.00 here because SGD->PHP's
    # ramp fees are verified-free on both sides -- see the "deposit"/
    # "withdrawal" configs in CORRIDORS.)
    assert abs(d["wf_deposit_bps"]) < 0.005, d["wf_deposit_bps"]
    wf_sum = (d["wf_deposit_bps"] + d["wf_buy_bps"] + d["wf_move_bps"]
              + d["wf_sell_bps"] + d["wf_withdrawal_bps"])
    assert abs(wf_sum - d["cost_bps_taker"]) < 0.005, (wf_sum, d["cost_bps_taker"])
    print(f"  [ok] waterfall reconciles exactly: {d['wf_deposit_bps']:.2f} + "
          f"{d['wf_buy_bps']:.2f} + {d['wf_move_bps']:.2f} + "
          f"{d['wf_sell_bps']:.2f} + {d['wf_withdrawal_bps']:.2f} = "
          f"{wf_sum:.2f} == {d['cost_bps_taker']:.2f} bps")
    assert d["ramp_deposit_measured"] and d["ramp_withdrawal_measured"], d

    # small size: the flat network fee should dominate. At the real 4.0 USDT
    # withdrawal it is no longer merely large at S$200 -- it is the whole story.
    small = decompose(200, on, off, MIDS_FIXTURE, cfg)
    net_small = cfg["network_fee_stable"] / (200 / on["asks"][0][0]) * 1e4
    assert net_small > 240, net_small
    assert small["cost_bps_taker"] > d["cost_bps_taker"] + 200, small["cost_bps_taker"]
    print(f"  [ok] size effect: at S$200 the flat network fee alone is "
          f"{net_small:.0f} bps ({small['cost_bps_taker']:.0f} bps all-in)")

    # depth: at this book, ladder sizes do not move the price
    assert d["offramp_slip_bps"] == 0.0, d["offramp_slip_bps"]
    assert d["offramp_filled"] and d["onramp_filled"]
    print(f"  [ok] depth: 0.0 bps slippage at S$5k; top level holds "
          f"{d['offramp_depth_top_level']:,.0f} USDT")

    # per-size remaining depth (SEB-181): a bigger ladder rung eats into the
    # book, so what is left afterward must shrink (or at least hold, never
    # grow) as size grows -- never the pre-trade, corridor-wide figure
    # repeated unchanged at every size.
    big = decompose(50000, on, off, MIDS_FIXTURE, cfg)
    assert small["offramp_depth_top_level_after"] is not None
    assert (big["offramp_depth_top_level_after"]
            <= small["offramp_depth_top_level_after"]), (
        big["offramp_depth_top_level_after"], small["offramp_depth_top_level_after"])
    assert big["offramp_depth_1pct_after"] <= small["offramp_depth_1pct_after"]
    assert big["offramp_depth_top_level_after"] <= d["offramp_depth_top_level"]
    print(f"  [ok] per-size depth: after S$200 {small['offramp_depth_top_level_after']:,.0f} "
          f"USDT still at the best price; after S$50,000 only "
          f"{big['offramp_depth_top_level_after']:,.0f} USDT is")

    # no book to walk (the wide-layer shape) -> None, never an invented zero
    nobook = decompose(5000, on, {"bids": []}, MIDS_FIXTURE, cfg)
    assert nobook["offramp_depth_top_level_after"] is None
    assert nobook["offramp_depth_1pct_after"] is None
    print("  [ok] no order book -> remaining depth is None, not an invented zero")

    # thin book must be flagged, never silently truncated
    thin = decompose(5000, on, {"bids": [(60.68, 10.0)]}, MIDS_FIXTURE, cfg)
    assert thin["offramp_filled"] is False
    print("  [ok] thin book flagged (filled=False), not silently truncated")

    # total failure still yields a well-formed row, not a crash
    dead = decompose(5000, {"asks": []}, {"bids": []}, MIDS_FIXTURE, cfg)
    assert dead["landed_taker"] == 0.0 and dead["onramp_top_ask"] is None
    print("  [ok] dead sources degrade to a recorded row, not an exception")

    # wf_*, ramp_*_measured and offramp_depth_*_after are sidecar-only fields
    # (corridor_waterfall.csv, ramp_waterfall.csv, samples_depth.csv) --
    # deliberately absent from FIELDS/samples.csv, whose header is frozen, so
    # they are excluded here rather than added to it.
    SIDECAR_ONLY = {
        "wf_buy_bps", "wf_move_bps", "wf_sell_bps",
        "wf_deposit_bps", "wf_withdrawal_bps",
        "ramp_deposit_measured", "ramp_withdrawal_measured",
        "offramp_depth_top_level_after", "offramp_depth_1pct_after",
    }
    assert set(FIELDS) >= set(dead) - SIDECAR_ONLY | {"ts", "corridor", "source_ok", "errors"}
    print("  [ok] schema covers every derived field")

    # --- corridor 2: USD->MXN (Coinbase -> Bitso), real payloads 2026-08-19 ---
    cfg2 = CORRIDORS["USD->MXN"]
    on2 = {"asks": sorted(norm_levels(COINBASE_FIXTURE["asks"]), key=lambda x: x[0])}
    off2 = {"bids": sorted(bitso_bids(BITSO_FIXTURE), key=lambda x: x[0], reverse=True)}
    # Coinbase's third element (num_orders) must be ignored, not misread as size.
    assert on2["asks"][0] == (0.99916, 28060.73), on2["asks"][:1]
    # The Bitso reshape is the whole point: norm_levels alone drops these dicts.
    assert off2["bids"][0] == (17.049, 8797.6), off2["bids"][:1]
    assert norm_levels(BITSO_FIXTURE["payload"]["bids"]) == [], \
        "norm_levels must NOT know 'amount' -- reshaping is fetch_offramp_bitso's job"
    print("  [ok] corridor 2 parsers: Coinbase 3-element asks, Bitso 'amount' dicts")

    d2 = decompose(1000, on2, off2, MIDS_FIXTURE_MXN, cfg2)
    assert abs(d2["mid_src_dst"] - 17.0606) < 1e-3, d2["mid_src_dst"]
    # USDT trades BELOW 1.00 on Coinbase, so the on-ramp basis is a small GAIN.
    assert abs(d2["onramp_basis_bps"] - (-8.4)) < 0.5, d2["onramp_basis_bps"]
    assert abs(d2["offramp_basis_bps"] - 6.8) < 0.5, d2["offramp_basis_bps"]
    print(f"  [ok] corridor 2 basis: on-ramp {d2['onramp_basis_bps']:+} bps "
          f"(USDT under peg at Coinbase), off-ramp {d2['offramp_basis_bps']:+} bps")

    # Bitso's 78/60 bps dominates: the venue fees, not the rails, are the cost.
    # These were 87.3 / 68.9 while the network leg carried a flat 1.0 USDT
    # copied from corridor 1's Tron assumption -- a chain Coinbase does not
    # support for USDT. Coinbase's published 0.01% processing fee is 1 bp at
    # every size, so the network leg stops being size-dependent here.
    assert abs(d2["cost_bps_taker"] - 78.4) < 1.0, d2["cost_bps_taker"]
    assert abs(d2["cost_bps_maker"] - 59.9) < 1.0, d2["cost_bps_maker"]

    # A proportional fee is the same bps at every size -- that is the whole
    # difference from a flat one, and the reason USD 200 fell 50 bps -> 1 bp.
    net_bps = [round(decompose(n, on2, off2, MIDS_FIXTURE_MXN, cfg2)["network_fee_stable"]
                     / (n / on2["asks"][0][0]) * 1e4, 2) for n in (200, 1000, 5000)]
    assert net_bps == [1.0, 1.0, 1.0], net_bps
    print(f"  [ok] corridor 2 network leg: 0.01% processing fee = "
          f"{net_bps[0]} bps at every size (was 50 bps at USD 200 on a flat 1 USDT)")
    gap2 = d2["cost_bps_taker"] - d2["cost_bps_maker"]
    assert 18.0 < gap2 < 19.0, gap2      # Bitso 78->60 (18) + Coinbase 1->0.5
    print(f"  [ok] corridor 2 fees: taker {d2['cost_bps_taker']:.1f} vs maker "
          f"{d2['cost_bps_maker']:.1f} bps -- {gap2:.1f} bps apart (Bitso 18 + "
          f"Coinbase 0.5)")

    # Same exact reconciliation, second corridor, different size (1,000) and a
    # different fee shape (proportional Coinbase fee, not IR's flat one) --
    # confirms the fix isn't tuned to one corridor's numbers. USD->MXN's ramp
    # fees are verified-free on both sides too (Coinbase ACH, Bitso SPEI).
    assert abs(d2["wf_deposit_bps"]) < 0.005, d2["wf_deposit_bps"]
    wf_sum2 = (d2["wf_deposit_bps"] + d2["wf_buy_bps"] + d2["wf_move_bps"]
               + d2["wf_sell_bps"] + d2["wf_withdrawal_bps"])
    assert abs(wf_sum2 - d2["cost_bps_taker"]) < 0.005, (wf_sum2, d2["cost_bps_taker"])
    print(f"  [ok] corridor 2 waterfall reconciles exactly: {wf_sum2:.2f} == "
          f"{d2['cost_bps_taker']:.2f} bps")
    assert d2["ramp_deposit_measured"] and d2["ramp_withdrawal_measured"], d2

    # --- corridor 3: NZD->PHP's deposit leg is a deliberate GAP, not a zero.
    # No published free NZD deposit method exists on Independent Reserve, so
    # ramp_deposit_measured must be False and the deposit leg must contribute
    # exactly 0.0 bps (never a guessed number) while the total cost is
    # otherwise computed normally.
    cfg3 = CORRIDORS["NZD->PHP"]
    d3 = decompose(5000, on, off, MIDS_FIXTURE, cfg3)
    assert d3["ramp_deposit_measured"] is False, d3["ramp_deposit_measured"]
    assert d3["ramp_withdrawal_measured"] is True, d3["ramp_withdrawal_measured"]
    assert abs(d3["wf_deposit_bps"]) < 0.005, d3["wf_deposit_bps"]
    print("  [ok] NZD->PHP deposit leg recorded as an unmeasured gap (0 bps, "
          "flagged), not a guessed fee")

    assert providers_path(cfg2).endswith("providers_usdmxn.csv")
    assert providers_path(CORRIDORS["SGD->PHP"]).endswith("providers.csv")
    print("  [ok] panel routing: corridor 2 -> providers_usdmxn.csv, "
          "corridor 1 -> providers.csv")

    # --- corridors 5-7 (2026-09-29, SOURCES-2): USD->NGN, USD->INR,
    # SGD->INR. Luno's payload is {"price","volume"} dicts -- norm_levels's
    # native dict shape, the exact test Bitso's "amount" key exists to
    # prove does NOT work by accident; WazirX's is [price, qty] arrays,
    # the same shape Independent Reserve already uses. Neither venue needed
    # a new parser -- this proves it, the same way corridor 2's test proved
    # Coinbase/Bitso needed the reshaping they got.
    on_cb = {"asks": sorted(norm_levels(COINBASE_FIXTURE["asks"]), key=lambda x: x[0])}
    off_luno = {"bids": sorted(norm_levels(LUNO_FIXTURE["bids"]),
                               key=lambda x: x[0], reverse=True)}
    off_wazirx = {"bids": sorted(norm_levels(WAZIRX_DEPTH_FIXTURE["bids"]),
                                 key=lambda x: x[0], reverse=True)}
    assert off_luno["bids"][0] == (1373.0, 8550.09), off_luno["bids"][:1]
    assert off_wazirx["bids"][0] == (100.26, 36.2), off_wazirx["bids"][:1]
    print("  [ok] corridors 5-7 parsers: Luno {price,volume} dicts, WazirX "
          "[price,qty] arrays -- both native norm_levels shapes, no reshaping")

    cfg_ngn = CORRIDORS["USD->NGN"]
    d_ngn = decompose(1000, on_cb, off_luno, MIDS_FIXTURE_NGN, cfg_ngn)
    assert abs(d_ngn["mid_src_dst"] - 1329.3759) < 0.1, d_ngn["mid_src_dst"]
    # USDT trades RICH to the official NGN rate on Luno in this fixture
    # (1373 vs an official mid of 1329.38, a ~3.3% premium) -- Nigeria's
    # banks will not sell dollars at the official rate, so a real premium
    # here is the expected shape of the finding this corridor exists to
    # show, not a bug. basis_bps_cost's sign convention makes that premium
    # a GAIN (negative cost) on the sell leg, which is why cost_bps_taker
    # comes out negative on this fixture -- a real, if fixture-sized, taste
    # of the market this corridor was added to expose.
    assert d_ngn["offramp_basis_bps"] < -300, d_ngn["offramp_basis_bps"]
    # Luno's maker REBATE (-0.01%) must make maker cost_bps a touch BETTER
    # (more negative / less positive) than taker, not worse -- the opposite
    # of every other venue in this file, which is the whole point of
    # modelling it as a negative fee instead of clamping it to zero.
    assert d_ngn["cost_bps_maker"] < d_ngn["cost_bps_taker"], \
        (d_ngn["cost_bps_maker"], d_ngn["cost_bps_taker"])
    print(f"  [ok] corridor 5 (USD->NGN): mid {d_ngn['mid_src_dst']:.2f}, "
          f"taker {d_ngn['cost_bps_taker']:.1f} bps, maker rebate makes "
          f"maker {d_ngn['cost_bps_maker']:.1f} bps cheaper still")

    cfg_inr = CORRIDORS["USD->INR"]
    d_inr = decompose(1000, on_cb, off_wazirx, MIDS_FIXTURE_INR, cfg_inr)
    assert abs(d_inr["mid_src_dst"] - 96.0699) < 0.01, d_inr["mid_src_dst"]
    # WazirX's INR-market fee is flat (0.40% both regimes, no maker/taker
    # split, same shape as Independent Reserve) -- taker and maker must
    # differ ONLY by Coinbase's own 0.5bps onramp spread, not by anything
    # on the offramp leg.
    assert 0.4 < (d_inr["cost_bps_taker"] - d_inr["cost_bps_maker"]) < 0.6, \
        (d_inr["cost_bps_taker"], d_inr["cost_bps_maker"])
    print(f"  [ok] corridor 6 (USD->INR): mid {d_inr['mid_src_dst']:.2f}, "
          f"taker {d_inr['cost_bps_taker']:.1f} bps, flat WazirX fee leaves "
          f"only Coinbase's {d_inr['cost_bps_taker']-d_inr['cost_bps_maker']:.2f}"
          f"bps taker/maker gap")

    cfg_sgdinr = CORRIDORS["SGD->INR"]
    on_ir = {"asks": sorted(norm_levels(IR_FIXTURE["SellOrders"]), key=lambda x: x[0])}
    d_sgdinr = decompose(1000, on_ir, off_wazirx, MIDS_FIXTURE_SGD_INR, cfg_sgdinr)
    assert cfg_sgdinr["network_fee_stable"] == CORRIDORS["SGD->PHP"]["network_fee_stable"] == 4.0
    print(f"  [ok] corridor 7 (SGD->INR): mid {d_sgdinr['mid_src_dst']:.2f}, "
          f"taker {d_sgdinr['cost_bps_taker']:.1f} bps -- reuses SGD->PHP's "
          f"Independent Reserve onramp and its 4.0 USDT TRC20 network fee "
          f"unchanged, only the offramp venue is new")

    assert providers_path(cfg_ngn).endswith("providers_usdngn.csv")
    assert providers_path(cfg_inr).endswith("providers_usdinr.csv")
    assert providers_path(cfg_sgdinr).endswith("providers_sgdinr.csv")
    print("  [ok] panel routing: corridors 5-7 each get their own providers_*.csv\n")

    # --- incumbent panel (data/providers.csv) ---
    WISE_FIXTURE = {"providers": [
        {"name": "Wise", "quotes": [{"receivedAmount": 238000.0}]},
        {"name": "Instarem", "quotes": [{"receivedAmount": 238500.0}]},
        {"name": "Remitly", "quotes": [{"receivedAmount": 237000.0}]},
        # computed from rate/fee, and a second cheaper Wise quote to prove dedup
        {"alias": "WesternUnion", "quotes": [{"sourceAmount": 5000, "fee": 30, "rate": 47.5}]},
        {"name": "Wise", "quotes": [{"receivedAmount": 237500.0}]},
    ]}
    ts, mid = "2026-08-11T00:00:00Z", 47.5587
    q = parse_wise(WISE_FIXTURE)
    pr = provider_rows(ts, 5000, q, mid)
    assert len(pr) == 4, [r["provider"] for r in pr]        # 4 providers, Wise deduped
    assert [r["rank"] for r in pr] == [1, 2, 3, 4]
    assert pr[0]["provider"] == "Instarem" and pr[0]["landed_dst"] == 238500.0
    assert all(r["source_ok"] for r in pr)
    costs = [r["cost_bps"] for r in pr]
    assert costs == sorted(costs), costs                     # rank order == cost order
    assert set(PROVIDER_FIELDS) == set(pr[0])                # schema matches
    print(f"  [ok] panel: {len(pr)} providers ranked cheapest-first, ranks track cost")

    # empty / malformed / unavailable panel -> ONE source_ok=False row, no raise
    for bad in (parse_wise({}), parse_wise({"providers": [{"quotes": [{}]}]}), None, []):
        fr = provider_rows(ts, 200, bad, mid)
        assert len(fr) == 1 and fr[0]["source_ok"] is False and fr[0]["provider"] is None
    print("  [ok] empty/malformed panel -> single source_ok=False row, run continues\n")

    # A venue outage leaves the basis fields None. This crashed the run on
    # 2026-08-16 -- and because it crashed in a print helper that ran BEFORE
    # append(), it took the sample with it. Both halves are locked down here.
    blackout = {f: None for f in FIELDS}
    blackout.update(corridor="SGD->PHP", stable="USDT", notional_src=5000,
                    onramp_venue="IndependentReserve", offramp_venue="Coins.ph",
                    ts="2026-08-16T07:47:13.000000+00:00", source_ok=False)
    print_waterfall([blackout])       # must not raise
    print_panel([])                   # must not raise
    print("  [ok] waterfall renders a None basis as '--' instead of raising\n")

    import tempfile
    with tempfile.TemporaryDirectory() as d:
        p = os.path.join(d, "samples.csv")
        assert captured_this_hour(p, "ts") is False, "missing file -> not captured"
        now = dt.datetime(2026, 8, 18, 14, 5, tzinfo=dt.timezone.utc)
        with open(p, "w", newline="") as f:
            w = csv.DictWriter(f, fieldnames=["ts", "x"])
            w.writeheader()
        assert captured_this_hour(p, "ts", now) is False, "header only -> not captured"
        # a row from the PREVIOUS hour must not suppress this hour's capture
        with open(p, "a", newline="") as f:
            csv.DictWriter(f, fieldnames=["ts", "x"]).writerow(
                {"ts": "2026-08-18T13:47:02.113000+00:00", "x": 1})
        assert captured_this_hour(p, "ts", now) is False, "prior hour -> not captured"
        with open(p, "a", newline="") as f:
            csv.DictWriter(f, fieldnames=["ts", "x"]).writerow(
                {"ts": "2026-08-18T14:17:30.551000+00:00", "x": 2})
        assert captured_this_hour(p, "ts", now) is True, "same hour -> captured"
        # :47 fire, same hour as the :17 row above -> still captured, no dupe
        assert captured_this_hour(
            p, "ts", now.replace(minute=47)) is True, ":47 sees :17's row"
        # next hour reopens capture
        assert captured_this_hour(
            p, "ts", now.replace(hour=15)) is False, "new hour -> not captured"
    print("  [ok] idempotency gate: one capture per UTC hour, reopens on the next\n")

    # Per-corridor gate: two corridors share samples.csv, so corridor 1 landing
    # at :17 must NOT convince corridor 2 that its hour is already captured.
    with tempfile.TemporaryDirectory() as d:
        p = os.path.join(d, "samples.csv")
        now = dt.datetime(2026, 8, 19, 14, 5, tzinfo=dt.timezone.utc)
        with open(p, "w", newline="") as f:
            csv.DictWriter(f, fieldnames=["ts", "corridor"]).writeheader()
        with open(p, "a", newline="") as f:
            csv.DictWriter(f, fieldnames=["ts", "corridor"]).writerow(
                {"ts": "2026-08-19T14:17:02.113000+00:00", "corridor": "SGD->PHP"})
        assert captured_this_hour(p, "ts", now, "SGD->PHP") is True
        assert captured_this_hour(p, "ts", now, "USD->MXN") is False, \
            "corridor 1's capture must not block corridor 2"
        with open(p, "a", newline="") as f:
            csv.DictWriter(f, fieldnames=["ts", "corridor"]).writerow(
                {"ts": "2026-08-19T14:18:44.900000+00:00", "corridor": "USD->MXN"})
        assert captured_this_hour(p, "ts", now, "USD->MXN") is True
        # corridor 1 still reads as captured even though corridor 2's row is last
        assert captured_this_hour(p, "ts", now, "SGD->PHP") is True, \
            "a later corridor-2 row must not hide corridor 1's own capture"
        assert captured_this_hour(
            p, "ts", now.replace(hour=15), "USD->MXN") is False, "new hour reopens"
        # unscoped call is unchanged: last row of ANY corridor decides
        assert captured_this_hour(p, "ts", now) is True
    print("  [ok] per-corridor gate: each corridor claims the hour independently\n")

    # samples_depth.csv: every priced corridor gets a row, an unpriced one
    # does not -- never an invented remaining-depth figure for a corridor
    # with no order book to walk (same limit item 6 already stated).
    with tempfile.TemporaryDirectory() as d:
        p = os.path.join(d, "samples_depth.csv")
        rows_mixed = [
            {"ts": "2026-10-01T00:00:00+00:00", "corridor": "SGD->PHP",
             "notional_src": 200, "offramp_depth_top_level_after": 900.0,
             "offramp_depth_1pct_after": 2000.0},
            {"ts": "2026-10-01T00:00:00+00:00", "corridor": "EUR->ZAR",
             "notional_src": 200, "offramp_depth_top_level_after": 900.0,
             "offramp_depth_1pct_after": 2000.0},
        ]
        assert append_depth_sidecar(rows_mixed, path=p) == p
        with open(p, newline="") as f:
            written = list(csv.DictReader(f))
        assert len(written) == 1 and written[0]["corridor"] == "SGD->PHP", written
    print("  [ok] samples_depth.csv: only priced corridors get a row\n")

    # SEB-255: Kraken's book answers under a key that is not the pair asked for; the one result is read,
    # sorted cheapest ask first, and an error answer raises instead of returning an empty book.
    _real_get = globals()["get_json"]
    try:
        globals()["get_json"] = lambda url, *a, **k: {"error": [], "result": {"USDTZUSD": {
            "asks": [["0.99920", "10.0", 1], ["0.99914", "5.0", 2]], "bids": [["0.99913", "7.0", 3]]}}}
        assert fetch_onramp_kraken({"onramp": {"pair": "USDTUSD"}}) == {"asks": [(0.99914, 5.0), (0.99920, 10.0)]}
        globals()["get_json"] = lambda url, *a, **k: {"error": ["EQuery:Unknown asset pair"], "result": {}}
        try:
            fetch_onramp_kraken({"onramp": {"pair": "NOPE"}})
            raise AssertionError("an error answer must raise")
        except ValueError:
            pass
    finally:
        globals()["get_json"] = _real_get
    for _k in ("USD->NGN", "USD->INR"):
        _v = CORRIDOR_VARIANTS[_k][0]
        assert _v["onramp"]["venue"] == "Kraken" and _v["network"] == "Tron" and _v["network_fee_stable"] == 1.0, _k
    print("  [ok] Kraken on-ramp: book parsed, error answer raises; USD->NGN and USD->INR carry the Tron variant")
    print("  ALL SELFTESTS PASSED\n")


# ------------------------------------------------------------------- cli
def main():
    ap = argparse.ArgumentParser(description="margin.wiki corridor collector")
    ap.add_argument("--corridor", default="SGD->PHP", choices=list(CORRIDORS))
    ap.add_argument("--verify", action="store_true",
                    help="one pull, print waterfall, write nothing (RUN THIS FIRST)")
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--selftest", action="store_true")
    a = ap.parse_args()

    if a.selftest:
        selftest()
        return
    if requests is None:
        sys.exit("pip install requests")

    # Idempotency gate, BEFORE the network: the schedule fires twice an hour so
    # a dropped fire has a partner, not so we capture twice. Gating here also
    # spares the venues a redundant pull on the second fire.
    # Scoped to THIS corridor: both corridors append to samples.csv, so an
    # unscoped gate would let whichever corridor ran first claim the hour.
    if not a.verify and captured_this_hour(SAMPLES, "ts", corridor=a.corridor):
        print(f"  {utc_hour():%Y-%m-%dT%H}Z already captured -> {SAMPLES} "
              f"({a.corridor}), nothing to do")
        return

    cfg = CORRIDORS[a.corridor]
    panel_path = providers_path(cfg)
    rows, prows = collect(a.corridor, cfg)
    vrows = collect_variants(a.corridor, cfg)

    # PERSIST FIRST, DISPLAY SECOND. Display is decoration; the sample is the
    # product. Anything downstream of append() can crash without costing a row
    # -- which is exactly what happened on 2026-08-16, when a TypeError in the
    # waterfall header ran before the write and silently ate five samples.
    wrote = panel_wrote = None
    if not a.verify:
        wrote = append(rows)
        # The panel is supplementary: a write failure is logged, never fatal, so
        # it can't sink the corridor step.
        try:
            append_providers(prows, panel_path)
            panel_wrote = panel_path
        except Exception as e:
            print(f"  [warn] panel write failed (non-fatal): {e}\n", file=sys.stderr)
        # Same non-fatal shape: the waterfall sidecar is supplementary too.
        try:
            append_waterfall(rows)
        except Exception as e:
            print(f"  [warn] waterfall sidecar write failed (non-fatal): {e}\n", file=sys.stderr)
        # Same non-fatal shape: the ramp waterfall sidecar is supplementary too.
        try:
            append_ramp_waterfall(rows)
        except Exception as e:
            print(f"  [warn] ramp waterfall sidecar write failed (non-fatal): {e}\n", file=sys.stderr)
        # Same non-fatal shape: the per-size depth sidecar is supplementary too.
        try:
            append_depth_sidecar(rows)
        except Exception as e:
            print(f"  [warn] depth sidecar write failed (non-fatal): {e}\n", file=sys.stderr)
        # Same non-fatal shape: priced variants are supplementary too.
        try:
            append_variants(vrows)
        except Exception as e:
            print(f"  [warn] variants sidecar write failed (non-fatal): {e}\n", file=sys.stderr)

    if a.json:
        print(json.dumps({"corridor": rows, "panel": prows, "variants": vrows},
                          indent=2, default=str))
    else:
        print_waterfall(rows)
        print_panel(prows, cfg["src"])
        print_variants(vrows)

    if wrote:
        print(f"  appended -> {wrote}")
    if panel_wrote:
        print(f"  panel   -> {panel_wrote} ({len(prows)} rows)\n")

    if not rows[0]["source_ok"]:
        print(f"  [warn] incomplete sample: {rows[0]['errors']}", file=sys.stderr)
        # exit non-zero on a dead CORRIDOR sample so the scheduler surfaces it
        # loudly -- panel state deliberately does not affect this. The row is
        # already on disk by now, so this is a signal, not a discard.
        if not a.verify:
            sys.exit(1)


if __name__ == "__main__":
    main()
