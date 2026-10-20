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
  blocked: the Scout could not split it: 1c: context file does not exist: collector_us_ph_usd.py; 1c: context file does not exist: collector_us_ph_php.py; 1d: context file does not exist: data/us_ph_usd.csv; 1d: context file does not exist: data/us_ph_php.csv (2026-10-20)
- [ ] 2. United States to Brazil (Coinbase or Kraken, then Foxbit or Mercado Bitcoin)
  blocked: the Scout could not split it: 2c: context file does not exist: collector_us_br_us.py; 2c: context file does not exist: collector_us_br_br.py (2026-10-20)
- [ ] 3. United States to Indonesia (Coinbase or Kraken, then Indodax or Pintu)
  blocked: the Scout could not split it: 3c: context file does not exist: collector_route_us_send.py; 3c: context file does not exist: collector_route_id_recv.py; 3d: context file does not exist: collector_route_us_send.py; 3d: context file does not exist: collector_route_id_recv.py (2026-10-20)
- [ ] 4. Singapore to Indonesia (Independent Reserve, then Indodax or Pintu)
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
