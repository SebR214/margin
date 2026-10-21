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

## First: routes through the existing route machinery
- [ ] 0. Routes go through the existing route machinery, not new collectors. <!-- from:6d768ec8-78bd-4720-9f05-7a8255532873 -->
  Queued by Claude on SEB-301, 21 Oct 02:18 UTC. Replaces how items 1 to 6 are split. Done in a chat session, not by the builder.
  Checked on main on 21 Oct, 02:15 UTC: the jobs ticked as 1a (#571), 1b (#575) and 2a (#576) added three standalone collectors that
  collect.yml never runs. Their CSVs have no rows. They also skip the parts that make a route a route: fees, path costs, steps and
  transfer app quotes. The existing seven routes all run as `collector.py --corridor "X->Y"`.
  (a) Delete `collector_us_ph_usleg.py`, `collector_us_ph_phleg.py`, `collector_route_us_br_us.py` and their empty CSVs. Untick 1a, 1b, 2a.
  (b) Re-split items 1 to 6, one job per route: the corridor in collector.py's corridor table, one `collector.py --corridor` step in
      collect.yml, the route in the provider quotes config. Before each one, post the apps the comparison feed returns; skip under 3.
  (c) Merge rule: a PR that only adds an entry to an existing config table, plus its collect.yml step, merges by itself when one full
      collection run on the branch produces the same headers and still writes rows for every existing corridor.
  (d) Done means data: a job that adds or changes collection is ticked only after its first hourly rows are on main. If none land
      within 2 hours of the merge, untick it and post why.
  Status 21 Oct: (a) and (b) done in this file. The CSVs of (a) were never committed, so there were none to delete.

## More routes
Re-split 21 Oct under item 0: one job per route, through `collector.py --corridor`. Only where both ends already have a live exchange.
A route job adds one entry to `CORRIDORS` in collector.py, one corridor step to collect.yml (and its providers file to the commit
list there), and one entry to `CORRIDOR_CCY` in collector_providers.py. Every fee in the entry is copied from an entry already in the
table, never typed. The `rows:` line says where its first hourly rows must land before the job is ticked (item 0, rule d).
Apps in the comparison feed for each route were read on 20 Oct, 09:30 UTC, and posted on SEB-301; no route had fewer than 3.
Found 21 Oct: a route that collects does not yet show on the Routes page. Eleven other files carry their own list of routes
(tools/emit_routes.py, tools/emit_corridor_summary.py, tools/emit_providers.py, tools/emit_latest.py, tools/emit_price_changes.py,
tools/emit_provider_receipts.py, tools/audit_numbers.py, tools/record_common.py, js/route.js, corridor.html, copy.json).
Old split removed 21 Oct: 1a (#571), 1b (#575), 2a (#576) unticked, their collectors deleted; 1c, 2b, 2c, 3a to 3d, 4a to 4e, 5a to 5c
and 6a to 6d dropped unbuilt.

- [ ] 1. United States to the Philippines (Coinbase, then Coins.ph). Apps in the feed: 8.
  - [ ] 1a. Add the USD->PHP route to collector.py's corridor table, its collect.yml step and the provider quotes config
    files: `collector.py` `.github/workflows/collect.yml` `collector_providers.py`
    rows: `data/samples.csv` `USD->PHP`
    done when: collector.py's CORRIDORS has one new "USD->PHP" entry with src USD, dst PHP, stable USDT, the onramp, network_fee_stable, gas_modelled, withdraw_pct, withdraw_pct_cap and deposit fields copied unchanged from "USD->MXN", the offramp and withdrawal copied unchanged from "SGD->PHP", the same ladder, and providers_file "providers_usdphp.csv"; collect.yml has one new step "Collect corridor sample USD->PHP" after the SGD->INR step, with `if: always() && steps.needed.outputs.proceed == 'true'` and `run: python3 collector.py --corridor "USD->PHP"`, and data/providers_usdphp.csv added to the commit list; collector_providers.py CORRIDOR_CCY has "USD->PHP": ("USD", "PHP"); no other line changes.
    blocked: waits for item 0: the builder cannot yet send collector.py (103,000 characters) and rule d is not in the builder yet (2026-10-21)
- [ ] 2. United States to Brazil (Coinbase, then Foxbit or Mercado Bitcoin). Apps in the feed: 7.
  - [ ] 2a. Add the USD->BRL route to collector.py's corridor table, its collect.yml step and the provider quotes config
    files: `collector.py` `.github/workflows/collect.yml` `collector_providers.py`
    rows: `data/samples.csv` `USD->BRL`
    done when: as 1a, with the Coinbase side copied from "USD->MXN" and a Brazil off-ramp entry.
    blocked: collector.py has no off-ramp for Foxbit or Mercado Bitcoin (it reads Coins.ph, Bitso, Luno and WazirX only), so this is new collector code, not a table entry, and the off-ramp fee must be read from the venue's own fee page, which the builder cannot do (2026-10-21)
- [ ] 3. United States to Indonesia (Coinbase, then Indodax or Pintu). Apps in the feed: 6.
  - [ ] 3a. Add the USD->IDR route to collector.py's corridor table, its collect.yml step and the provider quotes config
    files: `collector.py` `.github/workflows/collect.yml` `collector_providers.py`
    rows: `data/samples.csv` `USD->IDR`
    done when: as 1a, with the Coinbase side copied from "USD->MXN" and an Indonesia off-ramp entry.
    blocked: collector.py has no off-ramp for Indodax or Pintu, and its own notes say Indodax publishes no fee schedule that can be read and checked, so there is no table entry to add (2026-10-21)
- [ ] 4. Singapore to Indonesia (Independent Reserve, then Indodax or Pintu). Apps in the feed: 5.
  - [ ] 4a. Add the SGD->IDR route to collector.py's corridor table, its collect.yml step and the provider quotes config
    files: `collector.py` `.github/workflows/collect.yml` `collector_providers.py`
    rows: `data/samples.csv` `SGD->IDR`
    done when: as 1a, with the Independent Reserve side copied from "SGD->PHP" and an Indonesia off-ramp entry.
    blocked: same as 3a: no Indodax or Pintu off-ramp in collector.py and no readable Indodax fee schedule; collector.py names SGD->IDR as left out on purpose for that reason (2026-10-21)
- [ ] 5. Australia to India (Independent Reserve, then WazirX). Apps in the feed: 11.
  - [ ] 5a. Add the AUD->INR route to collector.py's corridor table, its collect.yml step and the provider quotes config
    files: `collector.py` `.github/workflows/collect.yml` `collector_providers.py`
    rows: `data/samples.csv` `AUD->INR`
    done when: collector.py's CORRIDORS has one new "AUD->INR" entry with src AUD, dst INR, stable USDT, the onramp, network_fee_stable and deposit copied unchanged from "AUD->PHP", the offramp copied unchanged from "SGD->INR", the same ladder, and providers_file "providers_audinr.csv"; collect.yml has one new step "Collect corridor sample AUD->INR" after the SGD->INR step, with `if: always() && steps.needed.outputs.proceed == 'true'` and `run: python3 collector.py --corridor "AUD->INR"`, and data/providers_audinr.csv added to the commit list; collector_providers.py CORRIDOR_CCY has "AUD->INR": ("AUD", "INR"); no other line changes.
    blocked: waits for item 0: the builder cannot yet send collector.py (103,000 characters) and rule d is not in the builder yet (2026-10-21)
- [ ] 6. United States to Turkey (Coinbase, then BtcTurk or Paribu). Apps in the feed: 5.
  - [ ] 6a. Add the USD->TRY route to collector.py's corridor table, its collect.yml step and the provider quotes config
    files: `collector.py` `.github/workflows/collect.yml` `collector_providers.py`
    rows: `data/samples.csv` `USD->TRY`
    done when: as 1a, with the Coinbase side copied from "USD->MXN" and a Turkey off-ramp entry.
    blocked: collector.py has no off-ramp for BtcTurk or Paribu, so this is new collector code, not a table entry, and the off-ramp fee must be read from the venue's own fee page, which the builder cannot do (2026-10-21)

## More apps
- [ ] 7. For every route, list every provider the comparison feed returns that we don't store yet. Add all of them to the stored quotes.
  - [ ] 7a. Collector for every provider the comparison feed returns on each route
    files: `collector_comparison.py` `data/comparison_quotes.csv`
    context: `collector_providers.py`
    venue: `USD` | `https://api.wise.com/v4/comparisons/` | `(not probed: a dollar in dollars)`
    done when: running collector_comparison.py once appends to data/comparison_quotes.csv one row per route and provider that the feed returns (time, route, provider, fee, rate, amount received, source URL), and a provider already stored by collector_providers.py is skipped rather than duplicated.
    blocked: held until item 0 is done: a collection job, so rule d (ticked only when its rows land) must be in the builder first (2026-10-21)
  - [ ] 7b. List the providers the feed returns that we do not store yet, per route
    files: `tools/list_unstored_providers.py` `data/unstored_providers.json`
    context: `collector_providers.py`
    done when: running tools/list_unstored_providers.py writes data/unstored_providers.json with, for every route, the providers present in data/comparison_quotes.csv but absent from the existing provider quotes, and a test finds no provider on both the stored list and the unstored list for the same route.
  - [ ] 7c. Run the comparison collector in the hourly workflow
    files: `.github/workflows/collect.yml`
    done when: collect.yml has one new appended step that runs collector_comparison.py and commits data/comparison_quotes.csv, and no existing step is changed.
    blocked: held until item 0 is done: a collection job, so rule d (ticked only when its rows land) must be in the builder first (2026-10-21)
- [ ] 8. Check which big providers have a public quote of their own we can read the way we read Wise and Airwallex (try Remitly, Western Union, Revolut, Xe, MoneyGram). Add each that works as its own source next to the comparison feed. Post the ones that don't work and why.

## More sources for country prices
- [ ] 9. For each of the 20 markets marked "One source", find a second venue that sells USDT for that currency (exchange order book first, then a broker), probe it, and add it through quarantine. Post which markets still have one source and why.
- [ ] 10. Add a second official-rate source next to ExchangeRate-API for every currency Frankfurter covers, and compare the two hourly in `source_pairs.json`. Don't change which one is published.

## Already approved, finish these
- [ ] 11. Depth record step 2 (SEB-302): OKX ads (no extra calls) and the order books (about 24 extra calls an hour). Not the extra Binance searches, not CriptoYa. After 24 hours post the one-day table on SEB-302.
  Status 20 Oct: the order books are merged (PR #558, data/depth.csv, once an hour). The OKX ads hook is PR #572: it edits collector_p2p_okx.py, so it is not additive and stays open for Seb. The one-day table posts itself once 24 clean hours are stored (PR #573).
- [x] 12. Finding test files (ROADMAP.md step 2), for the five live findings. (PR #559, 2026-10-20)
- [ ] 13. Finding statuses on the site, once each finding has 14 days of retest rows: "Still holds", "Weaker" or "No longer true", with the date first published. Words in copy.json, one short line each.
