# Build backlog

The queue. Seb approved it on SEB-301 on 20 Oct 2026. The daily builder takes the top unchecked job, builds it, merges on green,
ticks it with the PR number and date, and posts one line on SEB-301. The Scout splits the next 7 unchecked items into jobs that fit
one builder call (one route, one source or one file at a time, with the exact files listed) every Monday. Claude's Monday review adds
items at the end, and refills the list when fewer than 10 are left. New items queued on SEB-301 under "Queued by Claude" are copied in
at the start of every builder run (tools/backlog.py).

Rules for every item: real CSVs only, never invented numbers. A new venue goes through `tools/probe_source.py` and 7 days of
quarantine before it feeds anything. A change to a published number needs METHODOLOGY.md and an index_version bump, listed in the job's
files. A blocked item gets one line saying why, and the builder moves to the next one. Nothing waits for Seb.

How to read it: a top-level item is `- [ ] N. title`. A job under it is `  - [ ] Na. title`, with `    files:` (backticked paths the builder may
change), optional `    context:` (read-only paths) and `    done when:` lines. The builder works on jobs. An item without jobs is not split yet.

## More routes
Only where both ends already have a live exchange, so no new on-ramp or off-ramp collector is needed. For each: the same five amounts,
the same path costs, transfer app quotes from the comparison feed, and steps stored for every path. Before building a route, post the
list of apps the comparison feed returns for it. Skip a route with fewer than 3 apps and say so. A new route shows on the Routes page
with the same template as the others. No new page.

- [ ] 1. United States to the Philippines (Coinbase or Kraken, then Coins.ph)
  - [x] 1a. US-side leg collector: Coinbase, with Kraken as fallback (PR #571, 2026-10-20)
    files: `collector_us_ph_usleg.py` `data/us_ph_usleg.csv`
    context: `collector_fx.py`
    venue: `USD` | `https://api.exchange.coinbase.com/products/USDT-USD/ticker` | `(not probed: a dollar in dollars; fields ask, bid, price)`
    venue: `USD` | `https://api.kraken.com/0/public/Ticker?pair=USDTUSD` | `(not probed: a dollar in dollars; result.USDTZUSD.a[0] is the ask, b[0] the bid, c[0] the last)`
    done when: running the collector appends one row with a UTC timestamp, the venue used, bid and ask of the dollar stablecoin in US dollars, and the spread in basis points to data/us_ph_usleg.csv, and uses Kraken only when Coinbase fails.
  - [x] 1b. Philippine-side leg collector: Coins.ph (PR #575, 2026-10-20)
    files: `collector_us_ph_phleg.py` `data/us_ph_phleg.csv`
    context: `collector_fx.py`
    venue: `PHP` | `https://api.pro.coins.ph/openapi/quote/v1/ticker/bookTicker?symbol=USDTPHP` | `bidPrice and askPrice`
    done when: running the collector appends one row with a UTC timestamp, the bid and ask of the dollar stablecoin in Philippine pesos on Coins.ph, and the spread in basis points to data/us_ph_phleg.csv, and writes no row when the fetch fails.
  - [ ] 1c. Emitter joining both legs into a US-to-Philippines corridor cost
    files: `tools/emit_us_ph.py`
    blocked: failed: the model returned no files in the agreed form (2026-10-20)
- [ ] 2. United States to Brazil (Coinbase or Kraken, then Foxbit or Mercado Bitcoin)
  - [ ] 2a. US leg collector: Coinbase and Kraken dollar-stablecoin quotes
    files: `collector_route_us_br_us.py` `data/route_us_br_us.csv`
    context: `collector_stable_venues.py`
    venue: `USD` | `https://api.exchange.coinbase.com/products/USDC-USD/book?level=1` | `(not probed: a dollar in dollars)`
    venue: `USD` | `https://api.kraken.com/0/public/Ticker?pair=USDCUSD` | `(not probed: a dollar in dollars)`
    done when: running the collector once appends one row per venue to data/route_us_br_us.csv (UTC timestamp, venue, best bid, best ask, mid), importing its HTTP helper from collector_stable_venues.py and leaving every existing collector and CSV untouched.
  - [ ] 2b. Brazil leg collector: Foxbit and Mercado Bitcoin stablecoin-to-real quotes
    files: `collector_route_us_br_br.py` `data/route_us_br_br.csv`
    context: `collector_stable_venues.py`
    venue: `BRL` | `https://api.foxbit.com.br/rest/v3/markets/usdcbrl/orderbook?depth=1` | `asks[0][0]`
    venue: `BRL` | `https://api.mercadobitcoin.net/api/v4/USDC-BRL/orderbook?limit=1` | `asks[0][0]`
    done when: running the collector once appends one row per venue to data/route_us_br_br.csv (UTC timestamp, venue, best bid in reais, best ask in reais, mid), and a venue that fails writes no row and does not stop the other.
  - [ ] 2c. Emit the United States to Brazil route cost from the two leg files
    files: `tools/emit_route_us_br.py` `data/route_us_br.json`
    context: `tools/record_common.py`
    done when: running the emitter reads data/route_us_br_us.csv and data/route_us_br_br.csv, pairs the newest reading of the cheapest US venue with the newest reading of the best Brazil venue taken close in
- [ ] 3. United States to Indonesia (Coinbase or Kraken, then Indodax or Pintu)
  - [ ] 3a. US leg collector: USDT/USD price on Coinbase and Kraken
    files: `collector_route_us_leg.py` `data/route_us_leg.csv` `.github/workflows/collect.yml`
    context: `collector_stable_venues.py`
    venue: `USD` | `https://api.exchange.coinbase.com/products/USDT-USD/ticker` | `(not probed: a dollar in dollars)`
    venue: `USD` | `https://api.kraken.com/0/public/Ticker?pair=USDTUSD` | `(not probed: a dollar in dollars)`
    done when: running collector_route_us_leg.py appends one timestamped row per venue (venue, bid, ask, last) to data/route_us_leg.csv, a failed venue is written as an empty row with an error note rather than a guessed price, and collect.yml has one appended step that runs it.
  - [ ] 3b. Indonesia leg collector: USDT/IDR price on Indodax and Pintu
    files: `collector_route_id_leg.py` `data/route_id_leg.csv` `.github/workflows/collect.yml`
    context: `collector_stable_venues.py`
    venue: `IDR` | `https://indodax.com/api/ticker/usdtidr` | `ticker.last`
    done when: running collector_route_id_leg.py appends one timestamped row per venue (venue, bid, ask, last in rupiah) to data/route_id_leg.csv, a failed venue is written as an empty row with an error note, and collect.yml has one appended step that runs it.
  - [ ] 3c. Route cost: United States to Indonesia, computed from the two leg files
    files: `tools/route_us_id.py` `data/route_us_id.json`
    context: `tools/record_common.py`
    done when: running tools/route_us_id.py reads data/route_us_leg.csv and data/route_id_leg.csv, takes the cheapest US venue buy price and the best Indonesia venue sell price from the same hour, writes data/route_us_id.json with the cost of the route in basis points against the official dollar-rupiah rate plus the venue names and source rows used, and writes nothing for an hour where either leg is missing.
  - [ ] 3d. WORDS United States to Indonesia route description
    done when: the writer has added a plain-language description of the United States to Indonesia route, naming the US on-ramp venues and the Indonesian exchanges, that states the cost figure comes from data/route_us_id.json.
- [ ] 4. Singapore to Indonesia (Independent Reserve, then Indodax or Pintu)
  - [ ] 4a. Independent Reserve leg: Singapore dollar to USDT price
    files: `collector_sg_id_ir.py` `data/sg_id_ir.csv`
    context: `collector_fx.py`
    done when: running collector_sg_id_ir.py appends one row to data/sg_id_ir.csv with a UTC timestamp, the best bid, the best ask, and the mid-price of USDT in SGD from Independent Reserve, and writes nothing on a fetch error.
  - [ ] 4b. Indodax leg: USDT to Indonesian rupiah price
    files: `collector_sg_id_indodax.py` `data/sg_id_indodax.csv`
    context: `collector_fx.py`
    done when: running collector_sg_id_indodax.py appends one row to data/sg_id_indodax.csv with a UTC timestamp, the buy price, the sell price, and the last price of USDT in IDR from Indodax, and writes nothing on a fetch error.
  - [ ] 4c. Run both Singapore to Indonesia collectors every hour
    files: `.github/workflows/collect.yml`
    done when: collect.yml still parses as YAML, its existing steps are unchanged, and it has appended steps that run collector_sg_id_ir.py and collector_sg_id_indodax.py and commit data/sg_id_ir.csv and data/sg_id_indodax.csv.
  - [ ] 4d. Route cost for Singapore to Indonesia from the two legs
    files: `tools/sg_id_route.py` `data/sg_id_route.json`
    context: `tools/record_common.py`
    done when: running tools/sg_id_route.py reads the newest paired rows of data/sg_id_ir.csv and data/sg_id_indodax.csv, converts one Singapore dollar through USDT to rupiah using ask on the Singapore side and bid on the Indonesian side, compares that with the official SGD to IDR rate from the existing FX record, and writes the cost in basis points, both leg timestamps and the source names to data/sg_id_route.json, writing a null cost with a reason if either leg is missing or stale.
  - [ ] 4e. WORDS Singapore to Indonesia route description
    done when: the writer has added the route's plain-language description, naming Independent Reserve and Indodax as the two legs and saying the cost is measured through USDT.
- [ ] 5. Australia to India (Independent Reserve or BTC Markets, then WazirX or CoinDCX)
  - [ ] 5a. Independent Reserve USDT/AUD leg
    files: `collector_route_ir.py`
    context: `tools/probe_source.py`
    venue: `AUD` | `https://api.independentreserve.com/Public/GetMarketSummary?primaryCurrencyCode=usdt&secondaryCurrencyCode=aud` | `LastPrice`
    done when: a test that feeds the saved Independent Reserve market-summary JSON to `parse()` gets back the best bid and best offer in AUD per USDT as floats, and `fetch()` returns None on an HTTP error or a missing field instead of raising.
  - [ ] 5b. BTC Markets USDT/AUD leg
    files: `collector_route_btcm.py`
    context: `tools/probe_source.py`
    venue: `AUD` | `https://api.btcmarkets.net/v3/markets/USDT-AUD/ticker` | `lastPrice`
    done when: a test that feeds the saved BTC Markets ticker JSON to `parse()` gets back the best bid and best ask in AUD per USDT as floats, and `fetch()` returns None on an HTTP error or a missing field instead of raising.
  - [ ] 5c. WazirX USDT/INR leg
    files: `collector_route_wazirx.py`
    context: `tools/probe_source.py`
- [ ] 6. United States to Turkey (Coinbase or Kraken, then BtcTurk or Paribu)
  - [ ] 6a. US on-ramp collector: Coinbase and Kraken dollar-stablecoin quotes
    files: `collector_us_tr_in.py` `data/us_tr_in.csv`
    context: `collector_stable_venues.py`
    venue: `USD` | `https://api.exchange.coinbase.com/products/USDT-USD/ticker` | `(not probed: a dollar in dollars)`
    venue: `USD` | `https://api.kraken.com/0/public/Ticker?pair=USDTUSD` | `(not probed: a dollar in dollars)`
    done when: running collector_us_tr_in.py appends one row per venue (timestamp, venue, bid, ask, last) to data/us_tr_in.csv, imports its helpers from existing collectors without editing them, and writes no row for a venue whose fetch failed.
  - [ ] 6b. Turkish exit collector: BtcTurk and Paribu stablecoin-to-lira quotes
    files: `collector_us_tr_out.py` `data/us_tr_out.csv`
    context: `collector_stable_venues.py`
    venue: `TRY` | `https://api.btcturk.com/api/v2/ticker?pairSymbol=USDT_TRY` | `data[0].last`
    venue: `TRY` | `https://www.paribu.com/ticker` | `FIL_TL.last`
    done when: running collector_us_tr_out.py appends one row per venue (timestamp, venue, bid, ask, last) to data/us_tr_out.csv, imports its helpers from existing collectors without editing them, and writes no row for a venue whose fetch failed.
  - [ ] 6c. Run both new United States to Turkey collectors in the hourly workflow
    files: `.github/workflows/collect.yml`
    done when: collect.yml has appended steps that run collector_us_tr_in.py and collector_us_tr_out.py and commit their two CSVs, with every existing line unchanged.
  - [ ] 6d. Emitter for the United States to Turkey route
    files: `tools/emit_us_tr.py` `data/us_tr.json`
    context: `collector_fx.py`
    done when: running tools/emit_us_tr.py reads data/us_tr_in.csv and data/us_tr_out.csv, and writes data/us_tr.json

## More apps
- [ ] 7. For every route, list every provider the comparison feed returns that we don't store yet. Add all of them to the stored quotes.
  - [ ] 7a. Collector for every provider the comparison feed returns on each route
    files: `collector_comparison.py` `data/comparison_quotes.csv`
    context: `collector_providers.py`
    venue: `USD` | `https://api.wise.com/v4/comparisons/` | `(not probed: a dollar in dollars)`
    done when: running collector_comparison.py once appends to data/comparison_quotes.csv one row per route and provider that the feed returns (time, route, provider, fee, rate, amount received, source URL), and a provider already stored by collector_providers.py is skipped rather than duplicated.
  - [ ] 7b. List the providers the feed returns that we do not store yet, per route
    files: `tools/list_unstored_providers.py` `data/unstored_providers.json`
    context: `collector_providers.py`
    done when: running tools/list_unstored_providers.py writes data/unstored_providers.json with, for every route, the providers present in data/comparison_quotes.csv but absent from the existing provider quotes, and a test finds no provider on both the stored list and the unstored list for the same route.
  - [ ] 7c. Run the comparison collector in the hourly workflow
    files: `.github/workflows/collect.yml`
    done when: collect.yml has one new appended step that runs collector_comparison.py and commits data/comparison_quotes.csv, and no existing step is changed.
- [ ] 8. Check which big providers have a public quote of their own we can read the way we read Wise and Airwallex (try Remitly, Western Union, Revolut, Xe, MoneyGram). Add each that works as its own source next to the comparison feed. Post the ones that don't work and why.

## More sources for country prices
- [ ] 9. For each of the 20 markets marked "One source", find a second venue that sells USDT for that currency (exchange order book first, then a broker), probe it, and add it through quarantine. Post which markets still have one source and why.
- [ ] 10. Add a second official-rate source next to ExchangeRate-API for every currency Frankfurter covers, and compare the two hourly in `source_pairs.json`. Don't change which one is published.

## Already approved, finish these
- [ ] 11. Depth record step 2 (SEB-302): OKX ads (no extra calls) and the order books (about 24 extra calls an hour). Not the extra Binance searches, not CriptoYa. After 24 hours post the one-day table on SEB-302.
  Status 20 Oct: the order books are merged (PR #558, data/depth.csv, once an hour). The OKX ads hook is PR #572: it edits collector_p2p_okx.py, so it is not additive and stays open for Seb. The one-day table posts itself once 24 clean hours are stored (PR #573).
- [x] 12. Finding test files (ROADMAP.md step 2), for the five live findings. (PR #559, 2026-10-20)
- [ ] 13. Finding statuses on the site, once each finding has 14 days of retest rows: "Still holds", "Weaker" or "No longer true", with the date first published. Words in copy.json, one short line each.
