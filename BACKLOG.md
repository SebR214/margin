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
  - [ ] 1a. US-side leg collector: Coinbase, with Kraken as fallback
    files: `collector_us_ph_usleg.py` `data/us_ph_usleg.csv`
    context: `collector_fx.py`
    done when: running the collector appends one row with a UTC timestamp, the venue used, bid and ask of the dollar stablecoin in US dollars, and the spread in basis points to data/us_ph_usleg.csv, and uses Kraken only when Coinbase fails.
  - [ ] 1b. Philippine-side leg collector: Coins.ph
    files: `collector_us_ph_phleg.py` `data/us_ph_phleg.csv`
    context: `collector_fx.py`
    done when: running the collector appends one row with a UTC timestamp, the bid and ask of the dollar stablecoin in Philippine pesos on Coins.ph, and the spread in basis points to data/us_ph_phleg.csv, and writes no row when the fetch fails.
  - [ ] 1c. Emitter joining both legs into a US-to-Philippines corridor cost
    files: `tools/emit_us_ph.py`
- [ ] 2. United States to Brazil (Coinbase or Kraken, then Foxbit or Mercado Bitcoin)
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
- [ ] 6. United States to Turkey (Coinbase or Kraken, then BtcTurk or Paribu)

## More apps
- [ ] 7. For every route, list every provider the comparison feed returns that we don't store yet. Add all of them to the stored quotes.
- [ ] 8. Check which big providers have a public quote of their own we can read the way we read Wise and Airwallex (try Remitly, Western Union, Revolut, Xe, MoneyGram). Add each that works as its own source next to the comparison feed. Post the ones that don't work and why.

## More sources for country prices
- [ ] 9. For each of the 20 markets marked "One source", find a second venue that sells USDT for that currency (exchange order book first, then a broker), probe it, and add it through quarantine. Post which markets still have one source and why.
- [ ] 10. Add a second official-rate source next to ExchangeRate-API for every currency Frankfurter covers, and compare the two hourly in `source_pairs.json`. Don't change which one is published.

## Already approved, finish these
- [ ] 11. Depth record step 2 (SEB-302): OKX ads (no extra calls) and the order books (about 24 extra calls an hour). Not the extra Binance searches, not CriptoYa. After 24 hours post the one-day table on SEB-302.
- [ ] 12. Finding test files (ROADMAP.md step 2), for the five live findings.
- [ ] 13. Finding statuses on the site, once each finding has 14 days of retest rows: "Still holds", "Weaker" or "No longer true", with the date first published. Words in copy.json, one short line each.
