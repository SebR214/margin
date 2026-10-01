#!/usr/bin/env python3
"""
margin.wiki provider collector -- quotes from the providers themselves.

Until now every competitor quote came from ONE source: the Wise comparison API.
That is a good source and it is not a neutral one -- it is one company's choice
of who counts as a competitor, and it does not include everybody. This collector
asks providers directly, where they publish a public quote.

    data/provider_quotes.csv
    ts_utc,corridor,size_src,provider,rate,fee_src,received_dst,cost_bps,
    source,source_ok,error

    data/provider_quotes_payout_type.csv   (sidecar, added SEB-124)
    ts_utc,corridor,size_src,provider,payout_type

    data/provider_delivery.csv   (sidecar, added SEB-176)
    ts_utc,corridor,provider,size_src,delivery_stated,source

THE PRECEDENCE RULE. Where a provider publishes its own rate, that is the number
used. Where it does not, the comparison API stands in. A provider quoting itself
is the more direct evidence, and every published row says which it is, so no
reader has to wonder and no source is being called wrong.

HOW FAST THE MONEY ARRIVES (SEB-176). WorldRemit's own calc_text (read below by
parse_worldremit) already carries a "Transfer time" line -- no new request, just
a second regex over text already in hand. Before writing any parser change for
Wise/Instarem/Airwallex, each live endpoint was called from this runner and its
raw JSON body read by hand, 2026-10-01, per this repo's own established method
(see ROADMAP's APAC sprint):
  Wise       YES. Each entry in `paymentOptions` carries its own
             `formattedEstimatedDelivery` (e.g. "in seconds"), already plain
             language, no reformatting needed. Read off the same BANK_TRANSFER
             option parse_wise() already selects (see wise_delivery()).
  Instarem   NO. The live `computed-value` response (checked against SGD->PHP)
             has no delivery/ETA field anywhere in its payload -- not
             `transaction_config`, not the top-level object. Not wired.
  Airwallex  NO. The live `indicativeQuote` response (checked against SGD->PHP)
             is five fields -- ccyPair, clientRate, awxRate, buyAmount,
             sellAmount -- and a createdAt stamp. No delivery field. Not wired.
A sidecar entry present means a provider's own page stated a delivery time and
it was read verbatim; absent means either it wasn't checked (Instarem,
Airwallex) or the check ran and found nothing to read that hour -- never
invented either way.

Cost is measured the same way as everywhere else in this repo: how far below the
mid-market rate the recipient ends up, in bps of the amount sent. Fees and rate
margin are one number, because that is what a sender experiences.

    cost_bps = (1 - received / (amount_sent * mid)) * 10_000

`payout_type` records what the quote actually pays out -- "bank" (bank deposit),
"cash" (cash pickup) or "wallet" -- because those are not like-for-like. The
default comparison on the page is bank deposit; a cash-pickup-only quote is
still collected here but is not ranked against a bank-deposit quote by
tools/emit_providers.py. It lives in the sidecar file above, keyed by
(ts_utc, corridor, size_src, provider), rather than in provider_quotes.csv
itself: that file's header is frozen, and payout_type was never recorded for
the rows collected before this column existed. A sidecar entry present means
it was measured; absent means it wasn't -- never inferred after the fact.

WHO IS HERE, AND WHO IS NOT.
  Instarem   public quote API. The account id is per source country, so only
             the two verified from Instarem's own pages are configured -- SG
             and AU. NZ and US are left blank rather than guessed.
  Airwallex  public indicative-quote API, all four corridors.
  Wise       its own quote API (api.wise.com/v3/quotes), not the comparison
             feed at api.wise.com/v4/comparisons that the rest of this repo's
             `providers*.csv` panels already read. Anonymous POST, no key, no
             cookie -- the same request wise.com's own calculator makes before
             a visitor signs in. All four corridors. The BANK_TRANSFER payIn
             option is used (cheapest bank-funded path, payout also
             BANK_TRANSFER), matching the "bank deposit" default everywhere
             else on this page; Wise's card-funded options are read but
             dropped, since a card-funded transfer is not the thing being
             compared.
  Revolut    publishes a live rate on its currency-converter page, but the
             quote API needs auth (401) and the page returns 403 to anything
             that is not a browser. Collecting it would mean running a headless
             browser in CI. Not done, and recorded here rather than omitted.
  WorldRemit wired for AUD->PHP and NZD->PHP and USD->MXN only, via the ONE
             NARROW EXCEPTION below (headless render of WorldRemit's own
             public calculator, no login, no CAPTCHA). SGD->PHP is NOT
             wired: WorldRemit's own calculator has no Singapore option in
             its send-country list at all (checked live, 2026-09-27 -- no
             en-sg locale page exists, and "Singapore"/"SGD" return "No
             countries found" in the international calculator's own
             country search), a real product gap, not a scraping failure.
             Each render also reads WorldRemit's own per-corridor size
             limit off the page when the ladder exceeds it (e.g. "Send
             amount too high, cannot send more than 9990 AUD" at
             AUD->PHP's 25,000/50,000 tiers; "cannot receive more than
             193000 MXN" / "cannot send more than 30000 USD" at
             USD->MXN's 25,000/50,000 tiers) -- recorded as a normal
             not-offered-at-this-size row, the same as any other
             provider's missing quote, never invented past the limit.
             The rate itself carries WorldRemit's own "First Transfer Rate"
             label -- that is the number the calculator shows an anonymous
             visitor, with no toggle to a different one, so that is the
             number collected and labelled as such.

  Probed and rejected, 2026-09-25 (see the PR that added this line for the
  exact requests tried; none of these get a request from this file):
    Western Union  api.westernunion.com/.../quotes needs OAuth2 or a client
                   certificate; wu.com's own calculator answers 403 to a
                   plain request (Akamai bot check) even before auth is asked.
    Remitly        api.remitly.io/v3/calculator/estimate exists and answers
                   with a real payload shape, but two requests in a row from
                   a plain client draw a 429 NOT_ALLOWED -- not a stable
                   unauthenticated source for an hourly job.
    Ria            riamoneytransfer.com answers 403 to a plain request; the
                   calculator subdomain (dla.riamoneytransfer.com/calculator)
                   is a client-rendered app whose rate call could not be
                   isolated from a page load alone.
    MoneyGram      moneygram.com's pricing path redirects by locale/session
                   and never resolved to a stable public JSON endpoint.
    WorldRemit     the calculator's rate is server-rendered (Next.js SSR);
                   no client-visible JSON endpoint carries it.
    Xe             the public product is the paid Currency Data API
                   (xecdapi.xe.com), account id and key required.
    OFX            no public unauthenticated quote endpoint found; the
                   calculator is served through the marketing site's own
                   routing, not a discoverable JSON API.
    DBS Remit, OCBC, UOB, SingX, HSBC Singapore, CommBank, Westpac, ANZ,
    Xoom           no public unauthenticated quote endpoint found at their
                   conventional paths. Most of these are bank online-banking
                   surfaces gated behind login; none was chased past that.
  ONE NARROW EXCEPTION, owner-approved 2026-09-27 (in chat, not asserted by
  a task or a subagent): a headless browser MAY be used, but ONLY to render
  WorldRemit's own public calculator page and read the price it displays --
  the same page any anonymous visitor sees, filled in the same way a human
  would, nothing requiring a login or account. If a CAPTCHA or bot challenge
  appears at any point, stop; that is still forbidden, exception or not.
  This does NOT extend to Ria: round 2 (2026-09-26, below) found Ria now
  serves a Cloudflare interactive challenge, which is a CAPTCHA wall a
  headless browser does not clear and this exception does not touch.
  Every other provider in this file's lists (Western Union, Remitly,
  MoneyGram, Xe, OFX, DBS/OCBC/UOB/SingX/HSBC Singapore/CommBank/Westpac/
  ANZ/Xoom) stays under the original HARD RULE untouched: no auth
  workaround, no CAPTCHA bypass, no headless browser for any of them.

  OUTCOME, checked live 2026-09-27 (Playwright + Chromium, the render is in
  `render_worldremit()` below): the calculator's own bot-check element
  (data-testid="pxElement") was present on every page but never switched
  from hidden to visible, on any of the three corridors that were wired or
  during the Singapore-support check on the fourth -- no CAPTCHA was hit,
  so nothing needed to stop. Three of the four target routes render
  cleanly: AUD->PHP, NZD->PHP, USD->MXN (worldremit.com/en-au/philippines,
  /en-nz/philippines, /en-us/mexico -- fixed per-country calculator pages,
  no dropdown interaction needed at all beyond typing the send amount).
  SGD->PHP is blocked for a different reason than the one this exception
  was written to get past: WorldRemit's own calculator does not offer
  Singapore as a send country -- there is no en-sg locale page, and typing
  "Singapore" or "SGD" into the international calculator's own send-country
  search returns "No countries found". That is WorldRemit not supporting
  the corridor, not a render failure, so no amount of headless rendering
  fixes it -- recorded as unsupported, not retried. If `pxElement` ever
  does become visible in a future run, `render_worldremit()` reports it as
  a PX_CHALLENGE error on that row rather than trying to clear it, and the
  per-row try/except in `build_rows()` isolates it the same way a 429 or a
  timeout isolates any other provider's row.

  None of the above (other than the WorldRemit exception just described)
  get a scheduled request from this collector -- the HARD
  RULE is no workarounds for auth, CAPTCHAs or headless browsers, and every
  one of them needed one of those three.

  Probed again, round 2, 2026-09-26 (SOURCES spec task 2 -- re-checked live,
  not assumed from the note above; none of these get a request from this
  file either):
    Remitly        api.remitly.io/v3/calculator/estimate still answers with a
                   real payload (base_rate + a promotional DEBIT-only rate),
                   but re-tested today with the ladder's own pacing (five
                   sizes, 0.4s apart) it still drew 429 NOT_ALLOWED on most
                   requests -- three tries spaced 6s apart came back
                   429/200/429. Same failure as 2026-09-25, now confirmed
                   live rather than carried over on faith.
    Western Union  wu.com/router/api/rate still answers 403 (Akamai "Access
                   Denied") to a plain GET. Unchanged.
    Ria             riamoneytransfer.com's own quote path now answers with a
                   Cloudflare interactive challenge ("Just a moment...",
                   cf_chl_opt) rather than a plain 403 -- worse than before,
                   still a hard block per the CAPTCHA rule.
    MoneyGram      moneygram.com/mgo/api/v1/prices redirects to a
                   locale-guessed path (observed: /th/en/... from a request
                   naming SG/PH) which then 404s; the Next.js-rendered
                   locale picker never resolves to one stable JSON path.
                   Unchanged in kind from 2026-09-25.
    WorldRemit     worldremit.com/en/philippines still serves fully via
                   client-side JS with no api reference in the plain HTML.
                   Unchanged.
    Xe             xecdapi.xe.com still needs a key (403 "Authorization
                   header was missing"); the public-facing
                   xe.com/currencyconverter/convert page is Next.js
                   client-rendered and xe.com/api/currencyquote/quote 404s
                   on a plain request. Unchanged in effect.
    Xoom           xoom.com/philippines/send-money is client-rendered
                   (PayPal's checkout stack); no api reference in the plain
                   HTML and a guessed lookup path 404s. Unchanged.
  DBS Singapore chase closed, 2026-09-26: the prior redirect
  (personal/remit/rate-calculator -> error) was re-checked and still
  redirects to /personal/default.page?rd=err. Followed DBS's own site
  navigation instead of guessing further paths: the homepage
  (www.dbs.com.sg) and dbs.com.sg/sitemap.xml both serve a client-side
  "Spinner App" loading shell in plain HTML, with no static links to follow
  -- the whole site is rendered by JS after load, so a plain request cannot
  discover the current remit-rate path by navigation. Rendering it to find
  the real link would need a headless browser, which the HARD RULE forbids.
  Chase closed as blocked, not abandoned by guesswork.

SECOND COMPARISON FEED (SOURCES spec task 1). Wise's comparison API
(api.wise.com/v3/comparisons, read by collector.py / tools/emit_providers.py)
is ONE competitor's list of who counts as a competitor. Four independent
aggregators were probed, 2026-09-26, for a second one -- the public endpoint
each site's own calculator calls, no login, no key:
  Monito         every path (the compare page, a guessed /api/v3/rates, even
                 /robots.txt) answers 403 from CloudFront: "Request blocked."
                 This is an edge WAF block on the whole origin, not a route
                 that needs finding -- there is no plain request that gets
                 past it.
  RemitFinder    the compare page is an Angular SPA (no JSON in the plain
                 HTML); its own robots.txt explicitly disallows /api/* --
                 exactly where a client-rendered app's own calculator would
                 live. Respecting robots.txt here means not asking, not
                 finding a workaround.
  iCompareFX     reachable and not disallowed by robots.txt, but it is a
                 content/review site (guides, "X vs Y" articles, reviews),
                 not a live rate aggregator: its per-country send-money pages
                 are a Nuxt SPA and the server-rendered HTML carries no
                 per-provider rate table, only a single static currency
                 figure. There is no live comparison endpoint to wire.
  CompareRemit   every path, including /robots.txt, answers with Cloudflare's
                 interactive "Just a moment..." managed challenge (a JS
                 puzzle, not a bot-token header) -- the CAPTCHA rule.
None of the four cleared this repo's bar for a source: a plain,
unauthenticated request that returns the number, not a login page, a
CAPTCHA, or a client-side app with no visible endpoint. So no second feed is
fetched by this file yet. What IS added below is the merge rule the SOURCES
spec calls for -- own quote, then the median of two comparison feeds where
both have a price, then whichever feed has it, with a disagreement over
0.15% of the amount kept visible rather than blended away -- as a pure,
tested function (`combine_feed_quotes`) that tools/emit_providers.py can
call the moment a feed clears probe_source.py, the same way a `Commission`
gets wired in once accepted (see ROADMAP.md). Its selftest fixtures are
synthetic, including one forced disagreement, because no live feed exists
yet to produce one -- noted here rather than presented as a real reading.

Usage:
  python3 collector_providers.py --verify     # live pull, print, write nothing
  python3 collector_providers.py              # append data/provider_quotes.csv
  python3 collector_providers.py --selftest   # offline (never touches a
                                               # network or a browser, incl.
                                               # WorldRemit's render path)

WorldRemit needs `pip install playwright && playwright install chromium`
(the ONE NARROW EXCEPTION above) to actually render live; every other
provider here only needs `requests`. Its absence degrades to a per-row
error on WorldRemit's three wired corridors, exactly like any other
provider being down -- it does not stop the rest of this file from
running, and --selftest never needs it installed at all.
"""

import argparse
import csv
import datetime as dt
import json
import os
import re
import sys
import tempfile
import time
import urllib.parse

try:
    import requests
except ImportError:
    requests = None

try:
    from playwright.sync_api import sync_playwright
except ImportError:
    sync_playwright = None

HTTP_TIMEOUT = 20
REQUEST_GAP = 0.4
UA = {"User-Agent": "margin.wiki provider-collector/1.0 (+https://margin.wiki)",
      "accept": "application/json"}
HERE = os.path.dirname(os.path.abspath(__file__))
QUOTES = os.path.join(HERE, "data", "provider_quotes.csv")
PAYOUT_TYPES = os.path.join(HERE, "data", "provider_quotes_payout_type.csv")
DELIVERY = os.path.join(HERE, "data", "provider_delivery.csv")
FX_URL = "https://open.er-api.com/v6/latest/USD"

FIELDS = ["ts_utc", "corridor", "size_src", "provider", "rate", "fee_src",
          "received_dst", "cost_bps", "source", "source_ok", "error"]
KEY_FIELDS = ["ts_utc", "corridor", "size_src", "provider"]
PAYOUT_FIELDS = KEY_FIELDS + ["payout_type"]
DELIVERY_FIELDS = ["ts_utc", "corridor", "provider", "size_src",
                    "delivery_stated", "source"]

# Plausibility floor, bps. Found live 2026-09-28: AUD->PHP Airwallex read
# cost_bps -5.31 every hour (a "provider" that pays the sender, which is
# not a real thing) -- traced to `mid` (fetch_mids, from FX_URL below)
# being fetched from open.er-api.com, which updates roughly once every 24h
# (time_last_update_utc/time_next_update_utc a full day apart), while every
# provider's own quote in this file is live. On the day this was found,
# er-api's snapshot mid for AUD->PHP was 43.800, while Wise's own quote
# (same hour, its `rate` field) put the real mid nearer 43.890 -- a ~0.3%
# (~30bps) gap, an order of magnitude bigger than most providers' actual
# margin. Against a stale-low reference, any provider whose margin is
# thinner than that day's drift (Airwallex's real cost is a 0.5-1% rate
# markup per its own published FX pricing, baked into `rate` rather than
# billed as a separate fee -- feePercent=0 in airwallex_url() is correct,
# Airwallex does not charge a separate fee on local-network payouts) can
# come out negative with no error in the provider's own numbers at all.
# Same class of problem MIN_PLAUSIBLE_COST_BPS in
# collector_stable_venues.py exists for: reject the RESULT, don't clamp it
# to zero (that would hide a reference-rate problem this file cannot fix
# without a paid live-FX feed) and don't publish it as a usable "own"
# quote -- record it, mark source_ok False, and let
# tools/emit_providers.py fall back to the comparison feed or "no price
# this hour" the same way it already does for any other failed quote.
MIN_PLAUSIBLE_PROVIDER_COST_BPS = 0.0


def _implausible_note(cb):
    if cb is None or cb >= MIN_PLAUSIBLE_PROVIDER_COST_BPS:
        return None
    return (f"implausible:{cb:.2f}bps < "
            f"{MIN_PLAUSIBLE_PROVIDER_COST_BPS}bps floor (stale mid vs live quote)")

LADDER = [200, 1000, 5000, 25000, 50000]

# Instarem's quote needs the account id for the SOURCE country. Both of these
# were read from Instarem's own locale pages (en-sg and en-au) rather than
# guessed; a corridor absent from this map is simply not asked.
INSTAREM_ACCOUNT = {
    "SGD->PHP": ("SG", "93"),
    "AUD->PHP": ("AU", "135"),
}
# USD->NGN, USD->INR, SGD->INR (2026-09-29, SOURCES-2 corridors) have no
# entry here -- the account id is per SOURCE country, and neither the US nor
# a second SG account has been read from Instarem's own pages the way SG/AU
# were. Left blank rather than guessed, same rule as NZ/US above.

CORRIDOR_CCY = {
    "SGD->PHP": ("SGD", "PHP"), "AUD->PHP": ("AUD", "PHP"),
    "NZD->PHP": ("NZD", "PHP"), "USD->MXN": ("USD", "MXN"),
    "USD->NGN": ("USD", "NGN"), "USD->INR": ("USD", "INR"),
    "SGD->INR": ("SGD", "INR"),
}

# WorldRemit's own per-country calculator page, checked live 2026-09-27 --
# each one loads with the right send currency already selected, so no
# dropdown interaction is needed at all, just typing the send amount (see
# module docstring, ONE NARROW EXCEPTION). SGD->PHP has no entry: WorldRemit
# has no Singapore send-country option anywhere on its own calculator (no
# en-sg locale page, and the international calculator's own country search
# returns "No countries found" for "Singapore"/"SGD") -- not wired because
# WorldRemit itself does not offer it, not because rendering failed.
WORLDREMIT_URLS = {
    "AUD->PHP": "https://www.worldremit.com/en-au/philippines",
    "NZD->PHP": "https://www.worldremit.com/en-nz/philippines",
    "USD->MXN": "https://www.worldremit.com/en-us/mexico",
}
WORLDREMIT_NAV_TIMEOUT_MS = 30_000
WORLDREMIT_STEP_WAIT_MS = 2_000


# ------------------------------------------------------------- pure core
def _f(x):
    try:
        v = float(x)
        return v if v == v else None
    except (TypeError, ValueError):
        return None


def cost_bps(received, sent, mid):
    """How far below mid-market the recipient lands, in bps of the amount sent."""
    if not received or not sent or not mid:
        return None
    return round((1 - received / (sent * mid)) * 1e4, 2)


def parse_airwallex(d, sent):
    """{"ccyPair","clientRate","buyAmount","sellAmount"} -> (rate, fee, received).

    Airwallex quotes a rate and applies its fee as a percentage the caller
    passes in; the site's own widget passes feePercent=0, so this is the rate
    before any transfer fee. Recorded as a rate with a zero fee and labelled
    "indicative", which is Airwallex's own word for it.
    """
    rate = _f(d.get("clientRate"))
    recv = _f(d.get("buyAmount"))
    if rate and not recv:
        recv = rate * sent
    return (rate, 0.0, recv)


def parse_instarem(d, sent):
    """{"data":{"fx_rate","destination_amount","transaction_fee_amount"}}."""
    x = (d.get("data") or {}) if isinstance(d, dict) else {}
    rate = _f(x.get("fx_rate"))
    fee = _f(x.get("transaction_fee_amount"))
    recv = _f(x.get("destination_amount"))
    if rate and recv is None:
        recv = rate * sent
    return (rate, 0.0 if fee is None else fee, recv)


def parse_wise(d, sent):
    """{"rate","paymentOptions":[{"payIn","payOut","fee":{"total"},
    "targetAmount","disabled"}]} -> (rate, fee, received).

    wise.com's own calculator shows the BANK_TRANSFER payIn option by
    default for a visitor who has not chosen a card -- that is the option
    read here, matching this file's "bank deposit" default everywhere else.
    A disabled option (Wise sometimes disables BANK_TRANSFER by receiving
    country) is not used: that is Wise saying this path is not offered, not
    a quote to publish.
    """
    rate = _f(d.get("rate"))
    for po in (d.get("paymentOptions") or []):
        if po.get("payIn") == "BANK_TRANSFER" and not po.get("disabled"):
            fee = _f(((po.get("fee") or {}).get("total")))
            recv = _f(po.get("targetAmount"))
            return (rate, 0.0 if fee is None else fee, recv)
    return (rate, 0.0, None)


def wise_delivery(d):
    """Wise's own stated delivery time for the same BANK_TRANSFER option
    parse_wise() reads above -- its `formattedEstimatedDelivery` field,
    already plain language (e.g. "in seconds"), read live 2026-10-01 -- or
    None if that option isn't present/enabled on this quote."""
    for po in (d.get("paymentOptions") or []):
        if po.get("payIn") == "BANK_TRANSFER" and not po.get("disabled"):
            val = (po.get("formattedEstimatedDelivery") or "").strip()
            return val or None
    return None


_WR_RATE_RE = re.compile(r"=\s*\n*\s*([\d,]+\.?\d*)")
_WR_FEE_RE = re.compile(r"Fee\s*\n*\s*([\d,]+\.?\d*)")


def parse_worldremit(snapshot, sent):
    """{"calc_text","error_text"} -> (rate, fee, received, error).

    `snapshot` is plain text read off WorldRemit's own rendered calculator
    widget (see `render_worldremit`) -- calc_text is the whole widget's
    innerText (e.g. "You send\\n\\nAUD\\n\\nFirst Transfer Rate...\\n\\n1
    AUD =\\n\\n43.8417 PHP\\n\\n...Fee\\n0 AUD\\n..."), error_text is
    WorldRemit's own inline alert (data-testid="generic-error") when it
    declines the amount, e.g. "Send amount too high, cannot send more than
    9990 AUD". A non-empty error_text is WorldRemit answering "not at this
    size", not a render failure -- returned as a labelled error, never
    silently turned into a missing quote with no reason. The rate carries
    WorldRemit's own "First Transfer Rate" label (there is no toggle to a
    different one on the public page), so that is the number read.
    """
    err = (snapshot.get("error_text") or "").strip()
    if err:
        return (None, None, None, err)
    text = snapshot.get("calc_text") or ""
    m_rate = _WR_RATE_RE.search(text)
    rate = _f(m_rate.group(1).replace(",", "")) if m_rate else None
    m_fee = _WR_FEE_RE.search(text)
    fee = _f(m_fee.group(1).replace(",", "")) if m_fee else None
    if rate is None:
        return (None, fee, None, "no rate displayed")
    recv = round(rate * sent, 4)
    return (rate, 0.0 if fee is None else fee, recv, None)


_WR_SPEED_RE = re.compile(r"Transfer time\s*\n+\s*([^\n]+)")


def wr_delivery(calc_text):
    """WorldRemit's own stated transfer-time line, read off the same
    already-captured calc_text the rate/fee regexes above read (e.g.
    "...Transfer time\\nSame day\\nTotal to pay..." -> "Same day") -- or
    None if this render's widget text carried no such line."""
    m = _WR_SPEED_RE.search(calc_text or "")
    return m.group(1).strip() if m else None


# ------------------------------------------- second comparison feed (task 1)
# 0.15% of the amount sent, expressed in bps of the amount (cost_bps' own
# unit) -- 0.15% == 15 bps. The bar named in the SOURCES spec, not invented
# here.
DISAGREE_TOLERANCE_BPS = 15.0


def combine_feed_quotes(cost_a, cost_b, tol_bps=DISAGREE_TOLERANCE_BPS):
    """Merge one provider's cost_bps from two comparison feeds (A, B).

    THE PRECEDENCE RULE (own quote beats both) is applied by the caller,
    before this is ever reached -- this function only resolves the case
    where there is no own quote and up to two comparison feeds are in play.

      - neither feed has it -> no price.
      - only one feed has it -> that feed's number, unchanged.
      - both have it -> the median of the two (== their mean, for n=2) is
        published as the number to rank by. Both inputs are always
        returned too ("store both"), never discarded, whether or not they
        agree.

    Returns (used_cost_bps, disagree) -- `disagree` is True when the two
    feeds differ by tol_bps (0.15% of the amount) or more, which the caller
    uses to decide whether to print both numbers on the row ("Wise's
    comparison says X, <feed B> says Y"). A disagreement is a finding to
    show, not a reason to hide one number -- the median is still returned,
    it is not thrown out.
    """
    if cost_a is None and cost_b is None:
        return None, False
    if cost_a is None:
        return cost_b, False
    if cost_b is None:
        return cost_a, False
    disagree = abs(cost_a - cost_b) >= tol_bps
    return (cost_a + cost_b) / 2.0, disagree


# ------------------------------------------------------------------ I/O
_last = [0.0]


def _pace():
    wait = REQUEST_GAP - (time.monotonic() - _last[0])
    if wait > 0:
        time.sleep(wait)
    _last[0] = time.monotonic()


def get_json(url, payload=None):
    _pace()
    if payload is None:
        r = requests.get(url, timeout=HTTP_TIMEOUT, headers=UA)
    else:
        # Wise's own quote endpoint is a POST with a JSON body -- the same
        # request wise.com's own calculator makes anonymously, no key, no
        # cookie required.
        r = requests.post(url, json=payload, timeout=HTTP_TIMEOUT, headers=UA)
    r.raise_for_status()
    return r.json()


def fetch_mids(fetch=get_json):
    d = fetch(FX_URL)
    rates = d.get("rates") or {}
    if not rates:
        raise ValueError("er-api returned no rates")
    return {k: float(v) for k, v in rates.items()}


def airwallex_url(src, dst, amount):
    return ("https://www.airwallex.com/api/fx/fxRate/indicativeQuote"
            f"?sellAmount={amount}&sellCcy={src}&buyCcy={dst}&feePercent=0")


def instarem_url(corridor, src, dst, amount):
    cc, acct = INSTAREM_ACCOUNT[corridor]
    return ("https://www.instarem.com/api/v1/public/transaction/computed-value"
            f"?source_currency={src}&destination_currency={dst}"
            f"&instarem_bank_account_id={acct}&country_code={cc}"
            f"&source_amount={amount}")


WISE_URL = "https://api.wise.com/v3/quotes"


def wise_payload(src, dst, amount):
    return {"sourceCurrency": src, "targetCurrency": dst, "sourceAmount": amount}


def render_worldremit(url, sizes):
    """Render WorldRemit's own public calculator once and read the price at
    every ladder size -- the ONE NARROW EXCEPTION described in the module
    docstring: a headless browser, used only to load WorldRemit's own page
    and read what it displays, the same way an anonymous visitor would,
    nothing requiring login or an account. Never called by --selftest.

    One page load, one send-amount field filled once per size -- not one
    page load per size -- because the per-country URLs in WORLDREMIT_URLS
    already load with the right send currency selected; only the amount
    changes across the ladder.

    Returns {size: {"calc_text", "error_text"}}, the raw material
    `parse_worldremit` reads. A CAPTCHA/bot-challenge (WorldRemit's own
    data-testid="pxElement" becoming visible) stops immediately and is
    reported back as an error_text of "PX_CHALLENGE: ..." on every size
    from that point on -- never clicked through, never solved, per the
    HARD RULE this exception does not touch.
    """
    if sync_playwright is None:
        raise RuntimeError("playwright not installed")
    out = {}
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        try:
            page = browser.new_page()
            page.goto(url, wait_until="networkidle", timeout=WORLDREMIT_NAV_TIMEOUT_MS)
            page.wait_for_timeout(1500)
            try:
                reject = page.locator("#onetrust-reject-all-handler")
                if reject.count():
                    reject.click(timeout=5000)
                    page.wait_for_timeout(500)
            except Exception:
                pass  # no cookie banner this time -- not fatal either way

            px = page.locator('[data-testid="pxElement"]')

            def px_visible():
                return px.count() > 0 and px.get_attribute("hidden") is None

            if px_visible():
                raise RuntimeError("PX_CHALLENGE: bot-check shown on page load")

            send_input = page.locator(
                '[data-testid="calculator-v2-send-country-input"] input')
            calc = page.locator('[data-testid="calculator"]')
            err_block = page.locator('[data-testid="generic-error"]')

            for size in sizes:
                if px_visible():
                    out[size] = {"calc_text": "",
                                 "error_text": "PX_CHALLENGE: bot-check shown mid-session"}
                    continue
                send_input.click()
                send_input.fill("")
                send_input.type(str(int(size)), delay=30)
                page.wait_for_timeout(WORLDREMIT_STEP_WAIT_MS)
                if px_visible():
                    out[size] = {"calc_text": "",
                                 "error_text": "PX_CHALLENGE: bot-check shown mid-session"}
                    continue
                calc_text = calc.inner_text() if calc.count() else ""
                error_text = err_block.inner_text() if err_block.count() else ""
                # The widget occasionally hasn't finished re-rendering by
                # WORLDREMIT_STEP_WAIT_MS (observed live, 2026-09-27: one
                # size in a run of five came back with neither a rate nor
                # an error line) -- one extra wait-and-reread before giving
                # up on this size, not a second amount entry.
                if "=" not in calc_text and not error_text:
                    page.wait_for_timeout(WORLDREMIT_STEP_WAIT_MS)
                    calc_text = calc.inner_text() if calc.count() else ""
                    error_text = err_block.inner_text() if err_block.count() else ""
                out[size] = {"calc_text": calc_text, "error_text": error_text}
        finally:
            browser.close()
    return out


# ------------------------------------------------------------- collection
def _row(ts, corridor, size, provider, source):
    return {"ts_utc": ts, "corridor": corridor, "size_src": size,
            "provider": provider, "rate": None, "fee_src": None,
            "received_dst": None, "cost_bps": None, "source": source,
            "source_ok": False, "error": "", "payout_type": "bank",
            "delivery_stated": None, "delivery_source": None}


def build_rows(ts, corridors, mids, fetch=get_json, render=render_worldremit):
    """One row per corridor per size per provider. Never raises."""
    rows, n_ok = [], 0
    for corridor in corridors:
        src, dst = CORRIDOR_CCY[corridor]
        mid = None
        if mids.get(src) and mids.get(dst):
            mid = mids[dst] / mids[src]

        # WorldRemit is rendered once per corridor (one page load, one
        # send-amount field filled per ladder size) rather than once per
        # size like the JSON-API providers below -- see render_worldremit.
        # A total render failure (browser crash, navigation timeout, a
        # PerimeterX challenge on page load) is caught HERE so it produces
        # the same labelled error on every size for this corridor instead
        # of taking down the rest of build_rows -- the same isolation this
        # file already gives every other provider, one level up because
        # the failure can happen before any one size is even attempted.
        wr_snapshots = {}
        if corridor in WORLDREMIT_URLS:
            try:
                wr_snapshots = render(WORLDREMIT_URLS[corridor], LADDER)
            except Exception as e:
                err = f"{type(e).__name__}:{e}"[:300]
                wr_snapshots = {size: {"calc_text": "", "error_text": err}
                                for size in LADDER}

        for size in LADDER:
            # (provider, source host, url, parser, POST payload or None)
            # -- every provider here pays out as a bank deposit, the
            # default comparison, so payout_type is fixed at "bank" in
            # _row() rather than threaded through each job.
            jobs = [("Airwallex", "airwallex.com",
                     airwallex_url(src, dst, size), parse_airwallex, None),
                    ("Wise", "wise.com", WISE_URL, parse_wise,
                     wise_payload(src, dst, size))]
            if corridor in INSTAREM_ACCOUNT:
                jobs.append(("Instarem", "instarem.com",
                             instarem_url(corridor, src, dst, size),
                             parse_instarem, None))
            for provider, source, url, parse, payload in jobs:
                row = _row(ts, corridor, size, provider, source)
                try:
                    if mid is None:
                        raise ValueError(f"no mid for {src}->{dst}")
                    payload_arg = () if payload is None else (payload,)
                    raw = fetch(url, *payload_arg)
                    rate, fee, recv = parse(raw, size)
                    if provider == "Wise":
                        delivery = wise_delivery(raw)
                        if delivery:
                            row["delivery_stated"] = delivery
                            row["delivery_source"] = "wise_formattedEstimatedDelivery"
                    if not rate or not recv:
                        raise ValueError("no usable quote")
                    cb = cost_bps(recv, size, mid)
                    note = _implausible_note(cb)
                    row.update(rate=round(rate, 8), fee_src=fee,
                               received_dst=round(recv, 4), cost_bps=cb,
                               source_ok=(note is None))
                    if note:
                        row["error"] = note
                    else:
                        n_ok += 1
                except Exception as e:
                    row["error"] = f"{type(e).__name__}:{e}"[:300]
                rows.append(row)

            if corridor in WORLDREMIT_URLS:
                row = _row(ts, corridor, size, "WorldRemit", "worldremit.com")
                try:
                    snap = wr_snapshots.get(size) or {"error_text": "no render"}
                    delivery = wr_delivery(snap.get("calc_text"))
                    if delivery:
                        row["delivery_stated"] = delivery
                        row["delivery_source"] = "worldremit_calc_text"
                    if mid is None:
                        raise ValueError(f"no mid for {src}->{dst}")
                    rate, fee, recv, err = parse_worldremit(snap, size)
                    if err:
                        raise RuntimeError(err)
                    if not rate or not recv:
                        raise ValueError("no usable quote")
                    cb = cost_bps(recv, size, mid)
                    note = _implausible_note(cb)
                    row.update(rate=round(rate, 8), fee_src=fee,
                               received_dst=round(recv, 4), cost_bps=cb,
                               source_ok=(note is None))
                    if note:
                        row["error"] = note
                    else:
                        n_ok += 1
                except Exception as e:
                    row["error"] = f"{type(e).__name__}:{e}"[:300]
                rows.append(row)
    return rows, n_ok


def utc_hour(now=None):
    return (now or dt.datetime.now(dt.timezone.utc)).replace(
        minute=0, second=0, microsecond=0)


def captured_this_hour(path, ts_field, now=None):
    if not os.path.exists(path):
        return False
    last = None
    with open(path, newline="") as f:
        for row in csv.DictReader(f):
            last = row
    if not last or not last.get(ts_field):
        return False
    try:
        t = dt.datetime.fromisoformat(last[ts_field])
    except ValueError:
        return False
    if t.tzinfo is None:
        t = t.replace(tzinfo=dt.timezone.utc)
    return utc_hour(t.astimezone(dt.timezone.utc)) == utc_hour(now)


def append(rows):
    """Core fields to the frozen QUOTES header; payout_type and
    delivery_stated to their own sidecars, keyed by KEY_FIELDS, so QUOTES
    never gains a column and no row collected before either sidecar existed
    gets one invented for it. Unlike payout_type (always "bank", written
    for every row), a delivery row is only written when this hour's render
    actually carried a stated delivery time -- a sidecar entry present
    means it was measured, absent means it wasn't, never inferred."""
    os.makedirs(os.path.dirname(QUOTES), exist_ok=True)
    new = not os.path.exists(QUOTES)
    with open(QUOTES, "a", newline="") as f:
        w = csv.DictWriter(f, fieldnames=FIELDS, extrasaction="ignore")
        if new:
            w.writeheader()
        w.writerows(rows)

    new_payout = not os.path.exists(PAYOUT_TYPES)
    with open(PAYOUT_TYPES, "a", newline="") as f:
        w = csv.DictWriter(f, fieldnames=PAYOUT_FIELDS, extrasaction="ignore")
        if new_payout:
            w.writeheader()
        w.writerows(rows)

    delivery_rows = [
        {"ts_utc": r["ts_utc"], "corridor": r["corridor"],
         "provider": r["provider"], "size_src": r["size_src"],
         "delivery_stated": r["delivery_stated"], "source": r["delivery_source"]}
        for r in rows if r.get("delivery_stated")
    ]
    if delivery_rows:
        new_delivery = not os.path.exists(DELIVERY)
        with open(DELIVERY, "a", newline="") as f:
            w = csv.DictWriter(f, fieldnames=DELIVERY_FIELDS, extrasaction="ignore")
            if new_delivery:
                w.writeheader()
            w.writerows(delivery_rows)
    return QUOTES


def print_table(rows):
    print(f"\n  Quotes from the providers themselves   {rows[0]['ts_utc'][:16]}Z")
    print("  " + "-" * 70)
    cur = None
    for r in rows:
        if r["corridor"] != cur:
            cur = r["corridor"]
            print(f"  {cur}")
        ok = f"{r['cost_bps']:>8.2f} bps" if r["source_ok"] else "      --   "
        print(f"     {r['size_src']:>7,}  {r['provider']:<12}{ok}"
              f"   rate {r['rate'] if r['rate'] else '--'}"
              f"{'' if r['source_ok'] else '  ! ' + r['error'][:44]}")
    bad = [r for r in rows if not r["source_ok"]]
    print("  " + "-" * 70)
    print(f"  {len(rows) - len(bad)}/{len(rows)} quotes"
          f"{' -- TOTAL BLACKOUT' if len(bad) == len(rows) else ''}\n")


# -------------------------------------------------------------- selftest
AWX_FIXTURE = {"ccyPair": "SGDPHP", "clientRate": 49.367261,
               "buyAmount": 49367.26, "sellAmount": 1000.00}
INSTA_FIXTURE = {"success": True, "data": {
    "fx_rate": 49.4144, "destination_amount": 49414.4,
    "transaction_fee_amount": 0, "source_currency": "SGD",
    "destination_currency": "PHP"}}
# Trimmed from a real response: one disabled option (BALANCE, Wise's
# multi-currency wallet, not offered in every country) ahead of the
# BANK_TRANSFER option this collector actually reads, so the selftest
# also proves a disabled option is skipped rather than trusted.
WISE_FIXTURE = {"rate": 48.9321, "paymentOptions": [
    {"payIn": "BALANCE", "disabled": True,
     "fee": {"total": 4.60}, "targetAmount": 48708.10},
    {"payIn": "BANK_TRANSFER", "disabled": False,
     "fee": {"total": 4.63}, "targetAmount": 48705.54,
     "formattedEstimatedDelivery": "in seconds"},
    {"payIn": "DEBIT", "disabled": False,
     "fee": {"total": 45.90}, "targetAmount": 46479.13},
]}
MIDS = {"SGD": 1.2728, "PHP": 62.9455, "AUD": 1.5281, "NZD": 1.6902,
        "USD": 1.0, "MXN": 18.35}
TS = "2026-09-10T10:00:00+00:00"

# Trimmed from a real render, 2026-09-27 (see calc_au.html captured while
# probing worldremit.com/en-au/philippines): innerText of the whole
# data-testid="calculator" widget, including the "First Transfer Rate"
# label this collector has no way to bypass -- it is what an anonymous
# visitor is shown, so it is what gets read.
WR_CALC_TEXT_OK = ("You send\n\nUSD\n\nFirst Transfer Rate \U0001f389\n\n"
                    "1 USD =\n\n17.2737 MXN\n\nThey get\n\nMXN\n"
                    "Receive method\nBank Transfer\nReceive method\nFee\n"
                    "0 USD\nTransfer time\nSame day\nTotal to pay\n"
                    "1000 USD\nSend Money")
WR_FIXTURE_OK = {"calc_text": WR_CALC_TEXT_OK, "error_text": ""}
# A real limit message, read live from worldremit.com/en-us/mexico at the
# 25,000 and 50,000 ladder tiers, 2026-09-27 -- WorldRemit declining the
# amount, not a render failure.
WR_FIXTURE_LIMIT = {"calc_text": "",
                     "error_text": "Send amount too high, cannot send more than 30000 USD"}
WR_FIXTURE_PX = {"calc_text": "", "error_text": "PX_CHALLENGE: bot-check shown mid-session"}


def _requested_amount(key, url, payload):
    """Pull the sent amount back out of the request this collector just
    made, so the fake fetch below can return a fixture that is internally
    consistent at every ladder size (200..50000) rather than the one fixed
    number from the 2026-09-10 real capture -- see _scale_fixture."""
    if key == "wise":
        return _f((payload or {}).get("sourceAmount"))
    qs = urllib.parse.urlparse(url).query
    field = "sellAmount" if key == "airwallex" else "source_amount"
    vals = urllib.parse.parse_qs(qs).get(field)
    return _f(vals[0]) if vals else None


def _requested_ccy(key, url, payload):
    """(src, dst) actually asked for -- these fixtures were all captured
    against SGD->PHP, but the selftest also drives USD->MXN through the
    same fake fetch, so _scale_fixture needs to know which corridor's mid
    to rescale the fixture's rate against."""
    if key == "wise":
        p = payload or {}
        return p.get("sourceCurrency"), p.get("targetCurrency")
    qs = urllib.parse.parse_qs(urllib.parse.urlparse(url).query)
    if key == "airwallex":
        src_f, dst_f = "sellCcy", "buyCcy"
    else:
        src_f, dst_f = "source_currency", "destination_currency"
    src = qs.get(src_f, [None])[0]
    dst = qs.get(dst_f, [None])[0]
    return src, dst


# The corridor these fixtures were actually captured against -- used as the
# reference point _scale_fixture rescales a fixture's rate against when the
# selftest asks for a different corridor (USD->MXN) through the same fake.
_FIXTURE_NATIVE_MID = MIDS["PHP"] / MIDS["SGD"]


def _scale_fixture(key, val, sent, src, dst):
    """Recompute a canned fixture's rate and amount fields for the size and
    corridor actually requested, keeping its ORIGINAL MARGIN below mid --
    (fixture_rate / fixture's-own-mid) -- fixed. The fixtures below are
    only internally consistent at the one size (1000) and corridor
    (SGD->PHP) they were captured at; that went unnoticed because nothing
    checked a row's cost_bps for plausibility. The floor added by
    MIN_PLAUSIBLE_PROVIDER_COST_BPS now would flag every other ladder size,
    and every USD->MXN row (mid ~18, fixture rate ~49), as a false
    positive -- an artifact of reusing one fixture everywhere, not of the
    collector -- if this rescaling were skipped."""
    if not sent:
        return val
    mid = MIDS.get(dst, 0) / MIDS[src] if (src and dst and MIDS.get(src)) else None
    scale = (mid / _FIXTURE_NATIVE_MID) if mid else 1.0
    if key == "airwallex":
        rate = _f(val.get("clientRate"))
        if not rate:
            return val
        rate *= scale
        return dict(val, clientRate=round(rate, 8) if scale != 1.0 else rate,
                    buyAmount=round(rate * sent, 4), sellAmount=sent)
    if key == "instarem":
        d = dict(val)
        inner = dict(d.get("data") or {})
        rate = _f(inner.get("fx_rate"))
        fee = _f(inner.get("transaction_fee_amount")) or 0.0
        if rate:
            rate *= scale
            inner["fx_rate"] = round(rate, 8) if scale != 1.0 else rate
            inner["destination_amount"] = round((sent - fee) * rate, 4)
        d["data"] = inner
        return d
    if key == "wise":
        d = dict(val)
        rate = _f(d.get("rate"))
        if rate:
            rate *= scale
            d["rate"] = round(rate, 8) if scale != 1.0 else rate
        scaled = []
        for po in d.get("paymentOptions") or []:
            po2 = dict(po)
            fee = _f((po.get("fee") or {}).get("total")) or 0.0
            if rate:
                po2["targetAmount"] = round((sent - fee) * rate, 4)
            scaled.append(po2)
        d["paymentOptions"] = scaled
        return d
    return val


def _make_fetch(overrides=None):
    overrides = overrides or {}

    def fetch(url, payload=None):
        key = ("wise" if "wise" in url else
               "airwallex" if "airwallex" in url else "instarem")
        default = {"wise": WISE_FIXTURE, "airwallex": AWX_FIXTURE,
                   "instarem": INSTA_FIXTURE}[key]
        val = overrides.get(key, default)
        if isinstance(val, Exception):
            raise val
        sent = _requested_amount(key, url, payload)
        src, dst = _requested_ccy(key, url, payload)
        return _scale_fixture(key, val, sent, src, dst)
    return fetch


def _make_wr_render(per_size=None, raises=None):
    """Fake render_worldremit for --selftest -- no browser, no network, no
    playwright import even attempted. `per_size` overrides individual
    ladder sizes with a specific snapshot (e.g. the limit or PX fixtures
    above); anything not listed gets WR_FIXTURE_OK. `raises`, if given, is
    raised by the fake render itself, standing in for a total render
    failure (browser crash, navigation timeout, a PX challenge on page
    load) that build_rows must catch one level up, before any per-size
    snapshot exists."""
    per_size = per_size or {}

    def render(url, sizes):
        if raises is not None:
            raise raises
        return {size: per_size.get(size, WR_FIXTURE_OK) for size in sizes}
    return render


def selftest():
    assert parse_airwallex(AWX_FIXTURE, 1000) == (49.367261, 0.0, 49367.26)
    assert parse_instarem(INSTA_FIXTURE, 1000) == (49.4144, 0.0, 49414.4)
    assert parse_wise(WISE_FIXTURE, 1000) == (48.9321, 4.63, 48705.54)
    assert parse_instarem({}, 1000) == (None, 0.0, None)
    assert parse_airwallex({}, 1000) == (None, 0.0, None)
    assert parse_wise({}, 1000) == (None, 0.0, None)
    print("  [ok] all three parsers read their real payload; malformed -> no quote")
    print("  [ok] Wise's disabled BALANCE option is skipped for BANK_TRANSFER")

    rate, fee, recv, err = parse_worldremit(WR_FIXTURE_OK, 1000)
    assert (rate, fee, recv, err) == (17.2737, 0.0, 17273.7, None), (rate, fee, recv, err)
    rate, fee, recv, err = parse_worldremit(WR_FIXTURE_LIMIT, 25000)
    assert rate is None and recv is None
    assert err == "Send amount too high, cannot send more than 30000 USD"
    assert parse_worldremit({"calc_text": "", "error_text": ""}, 1000) == \
        (None, None, None, "no rate displayed")
    print("  [ok] parse_worldremit reads the rendered widget's own text; "
          "WorldRemit's own limit message comes back as a labelled error, "
          "never a silently missing quote")

    assert wr_delivery(WR_CALC_TEXT_OK) == "Same day"
    assert wr_delivery("") is None
    assert wr_delivery("You send\n\nUSD\n\nFirst Transfer Rate\n\n1 USD =\n\n17 MXN") is None
    assert wise_delivery(WISE_FIXTURE) == "in seconds"
    assert wise_delivery({}) is None
    assert wise_delivery({"paymentOptions": [{"payIn": "BANK_TRANSFER", "disabled": True,
                                               "formattedEstimatedDelivery": "in seconds"}]}) is None
    print("  [ok] wr_delivery/wise_delivery read a provider's own stated "
          "delivery time verbatim off text/fields already fetched; absent "
          "or a disabled option -> None, never invented")

    mid = MIDS["PHP"] / MIDS["SGD"]
    assert abs(cost_bps(49414.4, 1000, mid) - 8.25) < 3.0
    assert cost_bps(None, 1000, mid) is None and cost_bps(1.0, 0, mid) is None
    print("  [ok] cost is bps below mid-market, None-safe")

    rows, n_ok = build_rows(TS, ["SGD->PHP", "USD->MXN"], MIDS,
                             fetch=_make_fetch(), render=_make_wr_render())
    # SGD->PHP has Airwallex + Wise + Instarem (no WorldRemit -- unsupported
    # corridor, see WORLDREMIT_URLS); USD->MXN has Airwallex + Wise +
    # WorldRemit (no Instarem)
    assert len(rows) == 5 * 3 + 5 * 3 == 30, len(rows)
    assert n_ok == 30, n_ok
    provs = {(r["corridor"], r["provider"]) for r in rows}
    assert ("USD->MXN", "Instarem") not in provs, "unconfigured corridor is not asked"
    assert ("SGD->PHP", "Instarem") in provs
    assert ("USD->MXN", "Wise") in provs, "Wise is asked on every corridor"
    assert ("USD->MXN", "WorldRemit") in provs
    assert ("SGD->PHP", "WorldRemit") not in provs, \
        "WorldRemit has no Singapore send option -- not asked, not guessed"
    print("  [ok] a corridor with no verified account id is not asked, not guessed")
    print("  [ok] WorldRemit is only asked on the corridors it actually offers")

    rows_e, n_e = build_rows(TS, ["SGD->PHP"], MIDS,
                             fetch=_make_fetch({"instarem": RuntimeError("503")}))
    ins = [r for r in rows_e if r["provider"] == "Instarem"]
    assert all(not r["source_ok"] and "503" in r["error"] for r in ins)
    others_ok = [r for r in rows_e if r["provider"] != "Instarem"]
    assert all(r["source_ok"] for r in others_ok), "one down provider isolates"
    assert n_e == 10, n_e
    print("  [ok] one provider down isolates to its own rows")

    rows_w, n_w = build_rows(TS, ["SGD->PHP"], MIDS,
                             fetch=_make_fetch({"wise": RuntimeError("timeout")}))
    wr = [r for r in rows_w if r["provider"] == "Wise"]
    assert all(not r["source_ok"] and "timeout" in r["error"] for r in wr)
    print("  [ok] a Wise failure isolates the same way, never blocks the others")

    rows_m, n_m = build_rows(TS, ["SGD->PHP"], {"SGD": 1.27}, fetch=_make_fetch())
    assert n_m == 0 and all("no mid" in r["error"] for r in rows_m)
    print("  [ok] a missing mid degrades its corridor, never invents a rate")

    # WorldRemit's own per-size limit (a real "not offered at this size",
    # not a bug) isolates to just that size, on just that provider.
    rows_l, n_l = build_rows(TS, ["USD->MXN"], MIDS, fetch=_make_fetch(),
                             render=_make_wr_render({25000: WR_FIXTURE_LIMIT,
                                                      50000: WR_FIXTURE_LIMIT}))
    wr_limited = [r for r in rows_l if r["provider"] == "WorldRemit"
                  and r["size_src"] in (25000, 50000)]
    assert len(wr_limited) == 2
    assert all(not r["source_ok"] and "too high" in r["error"] for r in wr_limited)
    wr_ok = [r for r in rows_l if r["provider"] == "WorldRemit"
             and r["size_src"] not in (25000, 50000)]
    assert all(r["source_ok"] for r in wr_ok)
    other_provs_ok = [r for r in rows_l if r["provider"] != "WorldRemit"]
    assert all(r["source_ok"] for r in other_provs_ok)
    print("  [ok] WorldRemit declining an amount above its own limit isolates "
          "to that size, on that provider, never blocking the rest")

    # A CAPTCHA/bot-challenge appearing mid-session (WorldRemit's own
    # pxElement) must isolate exactly the same way -- never solved, never
    # routed around, just reported as a failed row like any other.
    rows_px, n_px = build_rows(TS, ["USD->MXN"], MIDS, fetch=_make_fetch(),
                               render=_make_wr_render({5000: WR_FIXTURE_PX}))
    px_row = [r for r in rows_px if r["provider"] == "WorldRemit"
              and r["size_src"] == 5000][0]
    assert not px_row["source_ok"] and "PX_CHALLENGE" in px_row["error"]
    print("  [ok] a WorldRemit bot-challenge isolates to its own row, "
          "never attempted past")

    # A total render failure (browser crash, navigation timeout, a
    # PerimeterX challenge on page load itself) is caught one level up in
    # build_rows, before any per-size snapshot exists -- every WorldRemit
    # row for that corridor fails with the same reason, every other
    # provider on the same corridor is untouched.
    rows_crash, n_crash = build_rows(
        TS, ["USD->MXN"], MIDS, fetch=_make_fetch(),
        render=_make_wr_render(raises=RuntimeError("Timeout 30000ms exceeded")))
    wr_crash = [r for r in rows_crash if r["provider"] == "WorldRemit"]
    assert len(wr_crash) == len(LADDER)
    assert all(not r["source_ok"] and "Timeout" in r["error"] for r in wr_crash)
    other_provs_crash = [r for r in rows_crash if r["provider"] != "WorldRemit"]
    assert all(r["source_ok"] for r in other_provs_crash)
    print("  [ok] a total WorldRemit render failure isolates to its own "
          "provider, never blocks Airwallex or Wise on the same corridor")

    assert all(r["payout_type"] == "bank" for r in rows)
    assert set(FIELDS) == set(rows[0]) - {"payout_type", "delivery_stated", "delivery_source"}
    print("  [ok] core schema covers every field but payout_type/delivery\n")

    wr_wise = [r for r in rows if r["provider"] == "Wise"]
    assert all(r["delivery_stated"] == "in seconds" for r in wr_wise)
    wr_worldremit = [r for r in rows if r["provider"] == "WorldRemit"]
    assert wr_worldremit and all(r["delivery_stated"] == "Same day" for r in wr_worldremit)
    assert all(r["delivery_stated"] is None
               for r in rows if r["provider"] in ("Airwallex", "Instarem"))
    print("  [ok] build_rows carries Wise's and WorldRemit's own stated "
          "delivery time; Airwallex/Instarem (no field, probed live) carry none\n")

    # A provider whose own quote beats `mid` by more than the plausibility
    # floor (real live 2026-09-28 case: Airwallex reading a small negative
    # cost against a stale er-api mid) is recorded -- rate, fee, received,
    # cost_bps all kept -- but never published as a usable "own" quote:
    # source_ok is False and the row says why, the same treatment a 503 or
    # a timeout gets, not a silent clamp to zero.
    awx_rich = dict(AWX_FIXTURE, clientRate=MIDS["PHP"] / MIDS["SGD"] * 1.001)
    rows_neg, n_neg = build_rows(
        TS, ["SGD->PHP"], MIDS,
        fetch=_make_fetch({"airwallex": awx_rich}))
    awx_neg = [r for r in rows_neg if r["provider"] == "Airwallex"]
    assert all(r["cost_bps"] is not None and r["cost_bps"] < 0 for r in awx_neg)
    assert all(not r["source_ok"] and "implausible" in r["error"] for r in awx_neg)
    others_neg_ok = [r for r in rows_neg if r["provider"] != "Airwallex"]
    assert all(r["source_ok"] for r in others_neg_ok), \
        "one implausible provider isolates, same as any other failure"
    print("  [ok] a provider quote that implies a negative cost is recorded "
          "(rate/fee/received/cost_bps all kept) but marked not usable, "
          "never silently clamped to zero")

    with tempfile.TemporaryDirectory() as d:
        global QUOTES, PAYOUT_TYPES, DELIVERY
        real_quotes, real_payout, real_delivery = QUOTES, PAYOUT_TYPES, DELIVERY
        QUOTES = os.path.join(d, "provider_quotes.csv")
        PAYOUT_TYPES = os.path.join(d, "provider_quotes_payout_type.csv")
        DELIVERY = os.path.join(d, "provider_delivery.csv")
        try:
            two = [r for r in rows if r["provider"] in ("Airwallex", "Wise")][:2]
            append(two)
            with open(QUOTES, newline="") as f:
                q = list(csv.DictReader(f))
            with open(PAYOUT_TYPES, newline="") as f:
                p = list(csv.DictReader(f))
            assert list(q[0]) == FIELDS, "QUOTES header never widens past FIELDS"
            assert "payout_type" not in q[0]
            assert "delivery_stated" not in q[0]
            assert list(p[0]) == PAYOUT_FIELDS
            assert p[0]["payout_type"] == "bank"
            with open(DELIVERY, newline="") as f:
                dl = list(csv.DictReader(f))
            assert list(dl[0]) == DELIVERY_FIELDS
            assert len(dl) == 1, "only Wise's row (the one with a stated delivery) is sidecared"
            assert dl[0]["provider"] == "Wise"
            assert dl[0]["delivery_stated"] == "in seconds"
            assert dl[0]["source"] == "wise_formattedEstimatedDelivery"

            # append() a batch with no stated delivery at all (e.g. a down
            # WorldRemit hour) must not create the sidecar file -- a sidecar
            # entry present means it was measured, so a file that exists but
            # is empty-of-rows would be indistinguishable from "measured,
            # found nothing" rather than "nothing in this batch had one".
            os.remove(DELIVERY)
            append([r for r in rows if r["provider"] == "Airwallex"][:1])
            assert not os.path.exists(DELIVERY)
        finally:
            QUOTES, PAYOUT_TYPES, DELIVERY = real_quotes, real_payout, real_delivery
    print("  [ok] append() splits payout_type into its own sidecar (every "
          "row) and delivery_stated into its own sidecar (only rows that "
          "actually carried one), both keyed by ts_utc/corridor/size_src/"
          "provider\n")

    # -- second comparison feed (task 1): combine_feed_quotes(). Synthetic
    # fixtures -- no live feed B exists yet (see module docstring), so
    # these are made-up numbers, clearly labelled as such, not a real
    # reading. One of them deliberately forces a >0.15%-of-amount
    # disagreement, per the SOURCES spec's own instruction to do that when
    # none occurs naturally.
    assert combine_feed_quotes(None, None) == (None, False)
    assert combine_feed_quotes(42.0, None) == (42.0, False)
    assert combine_feed_quotes(None, 37.5) == (37.5, False)
    # Agreeing feeds: Wise says 40.0 bps, feed B says 40.2 bps -- 0.2bps
    # apart, nowhere near the 15bps (0.15%) bar. Median is their mean.
    used, disagree = combine_feed_quotes(40.0, 40.2)
    assert abs(used - 40.1) < 1e-9 and disagree is False
    # Forced disagreement: Wise says 40.0 bps, feed B says 70.0 bps -- 30bps
    # apart, double the 15bps bar. Median is still published (55.0) but the
    # row must show both numbers, per the spec ("a finding, not a bug").
    used2, disagree2 = combine_feed_quotes(40.0, 70.0)
    assert abs(used2 - 55.0) < 1e-9 and disagree2 is True
    # Exactly at the bar counts as disagreeing (>= , not >).
    _, at_bar = combine_feed_quotes(0.0, DISAGREE_TOLERANCE_BPS)
    assert at_bar is True
    print("  [ok] combine_feed_quotes: one feed passes through untouched, "
          "two feeds median, forced 30bps gap flags disagree=True\n")

    print("  ALL SELFTESTS PASSED\n")


# ------------------------------------------------------------------- cli
def main():
    ap = argparse.ArgumentParser(description="margin.wiki provider collector")
    ap.add_argument("--verify", action="store_true")
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--selftest", action="store_true")
    a = ap.parse_args()

    if a.selftest:
        selftest()
        return
    if requests is None:
        sys.exit("pip install requests")

    if not a.verify and captured_this_hour(QUOTES, "ts_utc"):
        print(f"  {utc_hour():%Y-%m-%dT%H}Z already captured -> {QUOTES}, nothing to do")
        return

    ts = dt.datetime.now(dt.timezone.utc).isoformat()
    try:
        mids = fetch_mids()
    except Exception as e:
        print(f"  [warn] mid snapshot failed: {type(e).__name__}: {e}", file=sys.stderr)
        mids = {}
    rows, n_ok = build_rows(ts, sorted(CORRIDOR_CCY), mids)

    # PERSIST FIRST, DISPLAY SECOND.
    if not a.verify:
        append(rows)
    if a.json:
        print(json.dumps(rows, indent=2, default=str))
    else:
        print_table(rows)
    if a.verify:
        return
    print(f"  appended -> {QUOTES}\n")
    if n_ok == 0:
        print("  [error] TOTAL BLACKOUT -- no provider quoted", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
