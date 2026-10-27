# Build backlog

The queue. Since 25 Oct 2026 (Seb's plan) two kinds of writer add to it: the researcher (tools/researcher.py, one Sonnet call a week,
3 jobs at the end under "Proposed by the researcher") and Seb or a chat, by hand, in the same form. Nothing else writes items. The Aider
builder takes the top ready job, builds it, merges on green and ticks it with the PR number and date. The Sunday scorecard
(tools/scorecard.py) is the only evidence of what track A shipped. Items queued on SEB-301 under "Queued by Claude" are still copied
in at the start of every builder run (tools/backlog.py).

Track A takes only jobs a cheap model can't get wrong (tools/job_shape.py): new files (a new collector file, a new sidecar CSV, a
new finding test, a new history file, a new script), collect.yml growing by one step, a new row in the source registry. Each job
names the test that proves it. A job that changes an existing collector, a page or a method is track B: the builder skips it and it is
built in Seb's own sessions.

Rules for every item: real CSVs only, never invented numbers. A new venue goes through `tools/probe_source.py` and 7 days of
quarantine before it feeds anything. A blocked item gets one line saying why, and the builder moves to the next one. Nothing waits for Seb.

How to read it: a top-level item is `- [ ] N. title`. A job under it is `  - [ ] Na. title`, with `    files:` (backticked paths the builder may
change), optional `    context:` (read-only paths) and `    done when:` lines. The builder works on jobs. An item without jobs is not split yet.

## First: routes through the existing route machinery
- [x] 0. Routes go through the existing route machinery, not new collectors. <!-- from:6d768ec8-78bd-4720-9f05-7a8255532873 --> (done: PRs #581, #583, #584, 21 Oct)
  blocked: the Scout could not split it: 0a: the builder may not change tools/check_route_machinery.py (2026-10-25)
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
  Status 21 Oct: (a) PR #584 (their CSVs were never committed, so there were none to delete). (b) PR #581 and this file. (c) and (d)
  PR #583: check_additive.py takes new route entries, the builder writes `built:` for a collection job and watchdog.yml ticks it
  when its rows land. The builder now sends collector.py, collect.yml and collector_providers.py in parts (`excerpt:` lines).

## Built in a Claude chat session, not by the builder (Seb, 21 Oct)
Queued on SEB-301 on 21 Oct. Seb asked for both to be built in chat. The jobs list no files, so the builder never takes them.
"Cleaner type and more space" was withdrawn by Seb the same day and was never copied here.

- [x] 14. More space and clean line breaks, on every page. Archivo stays; words, sizes, colours and charts do not change. <!-- from:14c13a1a-7160-450d-93e8-82cc6ac6578d --> (PR #588, 2026-10-21)
- [ ] 15. Machine view: every page readable by AI agents, with a Human/Machine switch. <!-- from:d1b506d1-47b4-4f4a-8031-402fa434eb86 -->
  - [x] 15a. tools/emit_markdown.py writes a .md twin of every page each hour, one collect.yml step (PR #590, 2026-10-21)
  - [x] 15b. llms.txt at the site root, from the same script (PR #590, 2026-10-21)
  - [ ] 15c. A Human/Machine switch at the bottom of every page
    blocked: needs words in copy.json; only the writer agent may change them (copy-lock) and they need Seb's approval; the switch's code and CSS are merged and live, the panel just shows nothing until those words exist (2026-10-21)
  - [x] 15d. A link rel="alternate" type="text/markdown" in every page's head (PR #590, 2026-10-21)

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

- [x] 1. United States to the Philippines (Coinbase, then Coins.ph). Apps in the feed: 8. (done 2026-10-22)
  - [x] 1a. Add the USD->PHP route to collector.py's corridor table, its collect.yml step and the provider quotes config (PR #640, 2026-10-22)
    track: aider
    files: `collector.py` `.github/workflows/collect.yml` `collector_providers.py` `data/providers_usdphp.csv`
    context: `data/providers_usdars.csv`
    rows: `data/samples.csv` `USD->PHP`
    excerpt: `collector.py` `^CORRIDORS = \{` `^\}`
    excerpt: `.github/workflows/collect.yml` `- name: Collect corridor sample SGD->INR` `--corridor "SGD->INR"`
    excerpt: `.github/workflows/collect.yml` `for f in data/samples.csv` `; do$`
    excerpt: `collector_providers.py` `^CORRIDOR_CCY = \{` `^\}`
    done when: collector.py's CORRIDORS has one new "USD->PHP" entry with src USD, dst PHP, stable USDT, the onramp, network_fee_stable, gas_modelled, withdraw_pct, withdraw_pct_cap and deposit fields copied unchanged from "USD->MXN", the offramp and withdrawal copied unchanged from "SGD->PHP", the same ladder, and providers_file "providers_usdphp.csv"; collect.yml has one new step "Collect corridor sample USD->PHP" after the SGD->INR step, with `if: always() && steps.needed.outputs.proceed == 'true'` and `run: python3 collector.py --corridor "USD->PHP"`, and data/providers_usdphp.csv added to the commit list; collector_providers.py CORRIDOR_CCY has "USD->PHP": ("USD", "PHP"); in the new entry the Coinbase on-ramp source_url is the literal string "https://help.coinbase.com/en/exchange/trading-and-funding/exchange-fees", never the name COINBASE_FEES_URL (the additive check accepts literals only); every existing entry keeps COINBASE_FEES_URL exactly as it is (do not replace the name anywhere else); no constant is added and no line outside the new entries changes; data/providers_usdphp.csv is a new file holding only the header line of data/providers_usdars.csv, copied exactly, and no rows (the route emitters fail without it).
- [x] 2. United States to Brazil (Coinbase, then Foxbit or Mercado Bitcoin). Apps in the feed: 7. (done 2026-10-24)
  - [x] 2a. Add the USD->BRL route to collector.py's corridor table, its collect.yml step and the provider quotes config (PR #663, 2026-10-24)
    files: `collector.py` `.github/workflows/collect.yml` `collector_providers.py`
    rows: `data/samples.csv` `USD->BRL`
    done when: as 1a, with the Coinbase side copied from "USD->MXN" and a Brazil off-ramp entry.
- [x] 3. United States to Indonesia (Coinbase, then Indodax or Pintu). Apps in the feed: 6. (cut 25 Oct: Turkey and Indonesia routes were cut on purpose, near-zero premium)
  - [ ] 3a. Add the USD->IDR route to collector.py's corridor table, its collect.yml step and the provider quotes config
    files: `collector.py` `.github/workflows/collect.yml` `collector_providers.py`
    rows: `data/samples.csv` `USD->IDR`
    done when: as 1a, with the Coinbase side copied from "USD->MXN" and an Indonesia off-ramp entry.
    blocked: collector.py has no off-ramp for Indodax or Pintu, and its own notes say Indodax publishes no fee schedule that can be read and checked, so there is no table entry to add (2026-10-21)
- [x] 4. Singapore to Indonesia (Independent Reserve, then Indodax or Pintu). Apps in the feed: 5. (cut 25 Oct: Turkey and Indonesia routes were cut on purpose, near-zero premium)
  - [ ] 4a. Add the SGD->IDR route to collector.py's corridor table, its collect.yml step and the provider quotes config
    files: `collector.py` `.github/workflows/collect.yml` `collector_providers.py`
    rows: `data/samples.csv` `SGD->IDR`
    done when: as 1a, with the Independent Reserve side copied from "SGD->PHP" and an Indonesia off-ramp entry.
    blocked: same as 3a: no Indodax or Pintu off-ramp in collector.py and no readable Indodax fee schedule; collector.py names SGD->IDR as left out on purpose for that reason (2026-10-21)
- [x] 5. Australia to India (Independent Reserve, then WazirX). Apps in the feed: 11. (done 2026-10-24)
  - [x] 5a. Add the AUD->INR route to collector.py's corridor table, its collect.yml step and the provider quotes config (PR #662, 2026-10-24)
    track: aider
    files: `collector.py` `.github/workflows/collect.yml` `collector_providers.py`
    rows: `data/samples.csv` `AUD->INR`
    excerpt: `collector.py` `^CORRIDORS = \{` `^\}`
    excerpt: `.github/workflows/collect.yml` `- name: Collect corridor sample SGD->INR` `--corridor "SGD->INR"`
    excerpt: `.github/workflows/collect.yml` `for f in data/samples.csv` `; do$`
    excerpt: `collector_providers.py` `^CORRIDOR_CCY = \{` `^\}`
    done when: collector.py's CORRIDORS has one new "AUD->INR" entry with src AUD, dst INR, stable USDT, the onramp, network_fee_stable and deposit copied unchanged from "AUD->PHP", the offramp copied unchanged from "SGD->INR", the same ladder, and providers_file "providers_audinr.csv"; collect.yml has one new step "Collect corridor sample AUD->INR" after the SGD->INR step, with `if: always() && steps.needed.outputs.proceed == 'true'` and `run: python3 collector.py --corridor "AUD->INR"`, and data/providers_audinr.csv added to the commit list; collector_providers.py CORRIDOR_CCY has "AUD->INR": ("AUD", "INR"); no other line changes.
- [x] 6. United States to Turkey (Coinbase, then BtcTurk or Paribu). Apps in the feed: 5. (cut 25 Oct: Turkey and Indonesia routes were cut on purpose, near-zero premium)
  - [ ] 6a. Add the USD->TRY route to collector.py's corridor table, its collect.yml step and the provider quotes config
    files: `collector.py` `.github/workflows/collect.yml` `collector_providers.py`
    rows: `data/samples.csv` `USD->TRY`
    done when: as 1a, with the Coinbase side copied from "USD->MXN" and a Turkey off-ramp entry.
    blocked: needs-claude: collector.py has no off-ramp for BtcTurk or Paribu, so this is new collector code, not a table entry, and the off-ramp fee must be read from the venue's own fee page, which the builder cannot do (2026-10-21)

## More apps
- [ ] 7. For every route, list every provider the comparison feed returns that we don't store yet. Add all of them to the stored quotes.
  - [ ] 7a. Collector for every provider the comparison feed returns on each route
    files: `collector_comparison.py` `data/comparison_quotes.csv` `.github/workflows/collect.yml`
    context: `collector_providers.py`
    rows: `data/comparison_quotes.csv`
    excerpt: `.github/workflows/collect.yml` `- name: Collect corridor sample SGD->INR` `--corridor "SGD->INR"`
    excerpt: `.github/workflows/collect.yml` `for f in data/samples.csv` `; do$`
    venue: `USD` | `https://api.wise.com/v4/comparisons/` | `(not probed: a dollar in dollars)`
    done when: running collector_comparison.py once appends to data/comparison_quotes.csv one row per route and provider that the feed returns (time, route, provider, fee, rate, amount received, source URL), and a provider already stored by collector_providers.py is skipped rather than duplicated. collect.yml has one new step after the SGD->INR corridor step, with `if: always() && steps.needed.outputs.proceed == 'true'` and `run: python3 collector_comparison.py`, and data/comparison_quotes.csv added to the commit list; no existing step changes.
    blocked: failed: the model returned no files or edits in the agreed form (2026-10-23)
  - [x] 7b. List the providers the feed returns that we do not store yet, per route (PR #691, 2026-10-25)
    files: `tools/list_unstored_providers.py` `data/unstored_providers.json`
    context: `collector_providers.py`
    done when: running tools/list_unstored_providers.py writes data/unstored_providers.json with, for every route, the providers present in data/comparison_quotes.csv but absent from the existing provider quotes, and a test finds no provider on both the stored list and the unstored list for the same route.
- [x] 8. Check which big providers have a public quote of their own we can read the way we read Wise and Airwallex (try Remitly, Western Union, Revolut, Xe, MoneyGram). Add each that works as its own source next to the comparison feed. Post the ones that don't work and why. (cut 25 Oct: more apps were cut on purpose, the apps are benchmarks)
  blocked: the Scout could not split it: the answer holds no job in the agreed form (2026-10-25)

## More sources for country prices
- [x] 9. For each of the 20 markets marked "One source", find a second venue that sells USDT for that currency (exchange order book first, then a broker), probe it, and add it through quarantine. Post which markets still have one source and why. (PR #652, 2026-10-23: BitOasis and OKX spot for AED, OKX spot for SGD, Binance TH for THB, Binance spot for MXN, all in quarantine; first rows on main 23 Oct 08:06 UTC)
- [x] 10. Add a second official-rate source next to ExchangeRate-API for every currency Frankfurter covers, and compare the two hourly in `source_pairs.json`. Don't change which one is published. (PR #651, 2026-10-23: Frankfurter v2, all 60 currencies, data/fx_second.csv, first rows on main 23 Oct 08:14 UTC)

## Already approved, finish these
- [x] 11. Depth record step 2 (SEB-302): OKX ads (no extra calls) and the order books (about 24 extra calls an hour). Not the extra Binance searches, not CriptoYa. After 24 hours post the one-day table on SEB-302. (done: PRs #558, #572, #573, 20 Oct. OKX ads land in data/depth.csv)
  Status 20 Oct: the order books are merged (PR #558, data/depth.csv, once an hour). The OKX ads hook is PR #572: it edits collector_p2p_okx.py, so it is not additive and stays open for Seb. The one-day table posts itself once 24 clean hours are stored (PR #573).
- [x] 12. Finding test files (ROADMAP.md step 2), for the five live findings. (PR #559, 2026-10-20)
- [ ] 13. Finding statuses on the site, once each finding has 14 days of retest rows: "Still holds", "Weaker" or "No longer true", with the date first published. Words in copy.json, one short line each.

## Queued by Claude
Copied from SEB-301 comments by tools/backlog.py. The Scout splits them into jobs like the rest.

- [x] 16. **Routes: is the official rate behind route costs stale?** Singapore to the Philippines at S$5,000 says "Wise paid out S$7.26 more than the official rate this hour" (09:00 UTC, 21 Oct), and S$2.03 more at 07:00. "Sell and withdraw" on the stablecoin also reads −S$17.13. Wise pricing above the official rate at S$5,000 most likely means the official rate we compare against is hours old while Wise uses the live market rate. Finding 03 also moved from S$8.9M (11 Oct) to S$20.4M, which a stale baseline could explain. Post on SEB-301: for each route, the hours since 11 Aug where the cheapest app priced above the official rate, the age of the official rate in those hours, and how far the official rate was from the median of the apps' own rates that hour. Seb decides on any method change after. <!-- from:f5f329e2-2289-46e3-9351-3d69ad348555 --> (replaced by the live official rate, PR #613, SEB-310 item 3, 2026-10-22)
- [ ] 17. **Find a first source for every country that has never had a price.** On the live home map (21 Oct), these have no price on any day shown: Afghanistan, Angola, Botswana, Brunei, Ethiopia, Ghana, Nepal. From data/p2p_basis.csv, they fail because Binance has too few ads (2 to 5 against the 10 needed) or none at all. Count the full list from the files first, since there may be more. For each one, probe at least two other venues that sell USDT for that currency (a local exchange order book first, then a broker or another person-to-person board), add any that pass through quarantine, and post one line per country: the source found, or why none exists. <!-- from:6f423526-977f-4d72-b6a5-7ef3b6738159 -->
- [x] 18. **Watchdog flapping overnight.** Between 18:30 and 21:30 UTC on 20 Oct it went down and up four times: a cancelled collector run counted as down, then claims `routeData.bigCaption` and `homeData.updatedLine` were each false for 3 runs. For each claim, post the values that made it false. Then either fix the number or the claim's test, whichever is wrong. Don't reword the reader text. A cancelled run is not a failure and must not count toward the limit. <!-- from:69cd2ec1-979b-4185-a434-d0c3a73de8b4 --> (done 2026-10-25)
  - [x] 18a. Stop the watchdog flapping on cancelled runs and stale claims (PR #693, 2026-10-25)
    track: aider
    files: `.github/workflows/watchdog.yml` `tools/check_collector_health.py` `tools/audit_claims.py` `claims.json`
    done when: a cancelled or still-running collect.yml run never counts toward the down limit in watchdog.yml or tools/check_collector_health.py, with a test in tests/ that feeds a cancelled run and expects no down; running `python3 tools/audit_claims.py` on main passes for `routeData.bigCaption` and `homeData.updatedLine`, and if a claim's test no longer matches the page since the routes rebuild (PR #616), the claim's test is fixed, not the reader text; no copy.json line changes.

## Proposed by the researcher
Written by tools/researcher.py, one Sonnet call a week. Track A rules in tools/job_shape.py.

- [x] 19. Retest the p2p_spread_signal finding for the first time (done 2026-10-25)
  - [x] 19a. Retest the p2p_spread_signal finding for the first time (PR #696, 2026-10-25)
    track: aider
    proposed: researcher 2026-10-25 (gap: stale_findings: p2p_spread_signal, last_retest null)
    files: `findings_tests/p2p_spread_signal.json` `tests/agent_spread_signal_test.py`
    context: `data/findings.json` `data/p2p_spread_signal.csv` `data/finding_tests.csv` `findings_tests/price_changes.json`
    done when: tests/agent_spread_signal_test.py loads findings_tests/p2p_spread_signal.json and checks it has the same keys as findings_tests/price_changes.json: calculation, data window, minimum observations, invalid-if, and thresholds for holding, weaker and no longer true. It then runs the test calculation on a small inline table of 40 made-up hourly rows, using only the columns of data/p2p_spread_signal.csv, where the signal clearly holds, and expects the result 'holds'. It runs the same calculation on 40 rows where the signal is reversed and expects 'no longer true'. With 5 rows it expects 'not enough evidence'. Every threshold in the JSON must be read from the file by the test, not typed into the test.
- [x] 20. Diagnose why Binance P2P and OKX P2P disagree in the flagged markets (PR #687, 2026-10-25)
  - [x] 20a. Diagnose why Binance P2P and OKX P2P disagree in the flagged markets (PR #687, 2026-10-25)
    track: aider
    proposed: researcher 2026-10-25 (gap: disagree: TND binance_p2p vs okx_p2p median_gap_pct 19.88 over 488 hours, flag true (also INR 22.54, NPR 15.04, QAR 8.89, LKR 8.83))
    files: `tools/diagnose_disagree.py` `data/disagree_diagnosis.json` `tests/agent_diagnose_disagree.py`
    context: `data/source_pairs.json` `data/p2p_okx.csv` `data/p2p_sides.csv` `data/p2p_ads.csv`
    done when: tools/diagnose_disagree.py reads the pairs with flag true in data/source_pairs.json and, for each pair, the latest 168 hours of Binance and OKX rows. It writes data/disagree_diagnosis.json with, per pair: which side (buy or sell) carries the gap, the median ad count per venue, the median minimum order size per venue where the column exists, and one label chosen by code: 'one side thin' (fewer than 10 ads on either venue), 'one side moves alone' (the gap sits on the same side in over 80% of hours), or 'unexplained'. tests/agent_diagnose_disagree.py builds inline rows for a fake pair XXX. Binance sell 100 and OKX sell 120 for 10 hours, with 20 ads each, must give 'one side moves alone' on the sell side and gap 20.0. The same pair with OKX at 4 ads must give 'one side thin'. A pair with 5 hours of rows must give 'not enough evidence'. The test also runs the script on the real CSVs and checks that every number in the JSON is a finite float.
- [ ] 21. Bybit P2P collector for DZD and SDG, the two markets where only Binance P2P is seen
  - [ ] 21a. Bybit P2P collector for DZD and SDG, the two markets where only Binance P2P is seen
    track: aider
    proposed: researcher 2026-10-27 (gap: one_source: DZD (sources_seen only binance_p2p); one_source: SDG (sources_seen only binance_p2p))
    files: `collector_bybit_p2p.py` `data/p2p_bybit.csv` `tests/agent_bybit_p2p.py` `.github/workflows/collect.yml`
    context: `collector_p2p_okx.py` `collector_venue_common.py` `.github/workflows/collect.yml`
    rows: `data/p2p_bybit.csv`
    done when: collector_bybit_p2p.py reads the currency list from the one_source entries in data/gap_report.json, reads the public Bybit P2P ad list with no key, and adds one hourly collect.yml step. First hourly rows land in data/p2p_bybit.csv. tests/agent_bybit_p2p.py runs the selftest on an inline sample of 3 sell ads for DZD priced 100, 102 and 104 and checks the best price is 100, the median is 102 and the ad count is 3. An empty ad list must write no row and must not raise.
- [ ] 22. Quidax USDT/NGN spot collector as a second Nigeria source
  - [ ] 22a. Quidax USDT/NGN spot collector as a second Nigeria source
    track: aider
    proposed: researcher 2026-10-27 (gap: one_source: NGN (sources_behind_price only Luno))
    files: `collector_quidax_ngn.py` `data/quidax_ngn.csv` `tests/agent_quidax_ngn.py` `.github/workflows/collect.yml`
    context: `collector_stable_venues.py` `collector_venue_common.py` `.github/workflows/collect.yml`
    rows: `data/quidax_ngn.csv`
    done when: collector_quidax_ngn.py reads the public Quidax usdtngn ticker with no key and adds one hourly collect.yml step. First hourly rows land in data/quidax_ngn.csv with columns for time, bid, ask and last. tests/agent_quidax_ngn.py runs the selftest on an inline ticker sample with buy 1500 and sell 1510 and checks the row has bid 1500 and ask 1510. A sample with a missing sell field must write no row and must not raise.
    built: PR #711 (2026-10-27)
- [ ] 23. Satang Pro USDT/THB collector as a second Thailand exchange source
  - [ ] 23a. Satang Pro USDT/THB collector as a second Thailand exchange source
    track: aider
    proposed: researcher 2026-10-27 (gap: one_source: THB (sources_behind_price only Bitkub))
    files: `collector_satang_thb.py` `data/satang_thb.csv` `tests/agent_satang_thb.py` `.github/workflows/collect.yml`
    context: `collector_stable_venues.py` `collector_venue_common.py` `.github/workflows/collect.yml`
    rows: `data/satang_thb.csv`
    done when: collector_satang_thb.py reads the public Satang Pro usdt_thb order book or ticker with no key and adds one hourly collect.yml step. First hourly rows land in data/satang_thb.csv with columns for time, bid and ask. tests/agent_satang_thb.py runs the selftest on an inline sample with best bid 32.0 and best ask 32.5 and checks the row holds exactly those two values. A sample where bid is above ask must write no row and be logged as crossed.
- [ ] 24. Explain why seen sources are not behind the price in one-source markets
  - [ ] 24a. Explain why seen sources are not behind the price in one-source markets
    track: aider
    proposed: researcher 2026-10-27 (gap: one_source: AED (sources_seen BitOasis, OKX spot (AED), binance_p2p but only binance_p2p behind the price))
    files: `tools/one_source_reasons.py` `data/one_source_reasons.json` `tests/agent_one_source_reasons.py`
    context: `data/gap_report.json` `data/index_latest.json` `data/source_pairs.json` `data/source_registry.json`
    done when: tools/one_source_reasons.py reads data/gap_report.json and, for each one_source currency, lists every source seen but not behind the price with a reason taken from a stored field in data/index_latest.json, data/source_pairs.json or data/source_registry.json, or the text no stored reason. It writes data/one_source_reasons.json. tests/agent_one_source_reasons.py uses an inline fixture for AED with seen BitOasis, OKX spot (AED) and binance_p2p and behind binance_p2p, and checks BitOasis and OKX spot (AED) are listed as not behind with a reason string and binance_p2p is not listed. It also checks that a fixture with no stored fields gives the text no stored reason, and that the output has one entry per one_source currency.
- [ ] 25. Third-source arbiter for flagged source disagreements
  - [ ] 25a. Third-source arbiter for flagged source disagreements
    track: aider
    proposed: researcher 2026-10-27 (gap: disagree: TND binance_p2p vs okx_p2p median_gap_pct 20.0 flag true)
    files: `tools/disagree_arbiter.py` `data/disagree_arbiter.json` `tests/agent_disagree_arbiter.py`
    context: `data/source_pairs.json` `data/disagree_diagnosis.json` `data/p2p_kucoin.csv` `data/stable_venues.csv`
    done when: tools/disagree_arbiter.py takes each pair with flag true in the disagree list of data/gap_report.json, finds the latest price of any third source for the same currency in the stored CSVs, and writes data/disagree_arbiter.json saying which of the two it sits closer to, or the text no third source. tests/agent_disagree_arbiter.py uses an inline fixture with a at 100, b at 120 and a third source at 101 and checks the result says closer to a. It checks a third source at 119 says closer to b, and a fixture with no third source gives no third source and not a guess.
- [ ] 26. Retest coverage check: every finding has a dated retest row
  - [ ] 26a. Retest coverage check: every finding has a dated retest row
    track: aider
    proposed: researcher 2026-10-27 (gap: stale_findings: p2p_spread_signal last_retest null)
    files: `tools/retest_coverage.py` `data/retest_coverage.json` `tests/agent_retest_coverage.py`
    context: `data/findings.json` `data/finding_tests.csv` `data/finding_status.json`
    done when: tools/retest_coverage.py reads every finding id in data/findings.json and counts its rows and last row date in data/finding_tests.csv. It writes data/retest_coverage.json with one entry per finding holding row count, last retest date and days since, plus a list of findings with zero rows. tests/agent_retest_coverage.py uses an inline fixture of 2 findings, one with rows on two dates and one with none, and checks the first shows count 2 with the later date as last retest and the second is in the zero-rows list. It also checks the output has one entry per finding in the fixture.
- [ ] 27. Near-miss report for countries with no price
  - [ ] 27a. Near-miss report for countries with no price
    track: aider
    proposed: researcher 2026-10-27 (gap: no_price: BWP (too few people selling to call it a price))
    files: `tools/no_price_near_miss.py` `data/no_price_near_miss.json` `tests/agent_no_price_near_miss.py`
    context: `data/no_price_sources.json` `data/index_latest.json` `data/p2p_sides.csv` `tools/gate_common.py`
    done when: tools/no_price_near_miss.py reads each currency in the no_price list of data/gap_report.json, reads the stored ad-count threshold from tools/gate_common.py, and counts from data/p2p_sides.csv the sell ads each hour of the last 7 days. It writes data/no_price_near_miss.json with, per currency, the median ad count, the threshold and the number of hours at or above it. tests/agent_no_price_near_miss.py uses an inline fixture with a threshold of 10 and 4 hourly counts of 3, 8, 10 and 12 for one currency and checks the median is 9, hours at or above is 2 and the currency is marked near miss only when the median is at least half the threshold. A currency with no rows must be listed as no data.
- [ ] 28. Daily gap history for flagged source pairs
  - [ ] 28a. Daily gap history for flagged source pairs
    track: aider
    proposed: researcher 2026-10-27 (gap: disagree: LKR binance_p2p vs okx_p2p median_gap_pct 8.79 hours 553 flag true)
    files: `tools/pair_gap_daily.py` `data/pair_gap_daily.csv` `tests/agent_pair_gap_daily.py`
    context: `data/source_pairs.json` `tools/emit_source_pairs.py` `data/index_hourly.csv` `data/p2p_okx.csv`
    done when: tools/pair_gap_daily.py reuses the pairing logic of tools/emit_source_pairs.py, takes the pairs with flag true in the disagree list of data/gap_report.json and writes data/pair_gap_daily.csv with one row per currency, pair and UTC day holding the median gap in percent and the hours counted. tests/agent_pair_gap_daily.py uses an inline fixture of two days with hourly prices where source a is 100 and source b is 110 on day one for 3 hours and b is 120 on day two for 2 hours, and checks day one has median gap 10.0 with 3 hours and day two has 20.0 with 2 hours. An hour where one source has no price must be skipped, not counted as zero.
