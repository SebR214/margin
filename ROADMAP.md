# Roadmap

Updated 31 Oct 2026 (three levers, agreed with Seb in chat).  Seb owns this file. Agents change it only from a spec Seb approved.

## What margin.wiki is

Every hour it prices a dollar where people actually buy one, in 53 countries today, against the official rate. It also prices sending money on 9 routes with every fee we can measure, as a benchmark for the stablecoin. The transfer apps are benchmarks, not the subject.

## In six months (April 2027)

Three things, decided with Seb on 31 Oct 2026. Each is a month or more of build. Everything else is maintenance.

**1. Every dollar for sale on earth, plus cash.** Today: 53 currencies, mostly one or two boards each. Then: every currency any person-to-person board quotes (Binance, OKX, Bybit, KuCoin, Bitget, HTX, Noones), every ad, every hour, about 100 currencies and five to seven prices per dollar. And the cash dollar: the public money-changer trackers in about 15 countries (Argentina, Lebanon, Egypt, Nigeria, Pakistan, Sri Lanka, Venezuela and more), hourly, with whatever history they publish. Every country page then shows three dollars: official, cash, stablecoin. The site's first question, "is the stablecoin the cheap dollar", finally gets asked against cash. This is the moat: the most complete record of informal dollar prices that exists, and it compounds every hour. It needs storage first: raw ad and offer files leave the site repo for a data repo, because the site repo is at 540 MB and GitHub Pages stops at 1 GB.

**2. Three things you can see in the data.** The cash dollar against the stablecoin against the official rate, per country, hourly. Contagion: which countries' gaps move together, from our own hourly record, drawn on the map. The flow: every ad with a seller id since 24 Oct, so seller counts, depth and concentration per country, and the one test that matters, whether the book thins before a break. A dataset ships only with the sentence it changes on an existing page. No new chart pages.

**3. The machine does the reading.** Rule unchanged: no model touches a published number. One writer, a Sonnet call per confirmed currency break and one per day for home, gets a facts file from code plus search results, writes the prose with a link on every claim, and every number in its output is checked against the facts file by the claims audit before anything publishes. Event pages become the history of currency breaks, written by the site. The home page says what happened today and why.

**Alive, mostly by code.** The site's sentences are fixed and its numbers are not, which is why it feels dead. The home headline names today's largest move, computed every hour. A "what changed this week" block: countries that crossed 5%, events detected, sources added, findings whose status moved. Confirmed events become pages on their own. Research pieces re-run on a schedule.

**The devaluation watch (SEB-384)** is parked, not dead. The backtest on three managed currencies did not show the premium comes before the break. The cash trackers in lever 1 bring parallel-rate history for ten more countries. The watch is re-tested when that history is in, and built only if it passes.

It rests on three things that stay:

1. **Findings that age honestly.** Each finding is retested by code. It shows whether it still holds, got weaker or is no longer true. The original claim and its evidence stay up with their date.
2. **Sources checked against each other.** Every pair of sources measuring the same market is compared hour by hour. An event is confirmed only when two sources agree.
3. **A depth and liquidity record.** What a dollar costs at several amounts, and every ad on the boards, with who sells it.

## Who builds what

The research chat (Opus or Fable, the main chat of the Margin.Wiki project) decides what gets built and splits it. Mechanical work (a new collector from the template, one new file, one new test) goes into BACKLOG.md in the builder's job form and the Aider builder merges it on green. Judgment work (storage, templates, pages, methods, the writer) goes into a Linear issue for a Claude Code session Seb starts. The researcher agent is retired: the gap list (`tools/gap_report.py`) is a tool the research chat runs, not an agent that writes jobs.

## What counts as an event

- **Official break:** the official rate steps 3% or more within 3 days.
- **Street slide:** the street price moves 10% or more in 7 days, in a market we publish (10 or more ads).
- **Not an event:** thin markets, slow drifts that never cross the line, and anything caused by our own source breaking. A stale, looping or broken official rate is a data warning, never an event.
- **Confirmed** when two official sources show the step, or two street sources move together. With one source, the record says "one source". No model confirms anything.
- **Each event record holds:** what changed against a set baseline, the street before, how long the official source took to catch up, offer counts and depth where we have them, what happened after, and the quality checks on every source used.
- **Reopened** weekly for 8 weeks as the "after" fills in, then closed. Nothing is ever rewritten.

## Order

Done since 11 Oct: SEB-268, finding test files, source comparisons, depth collection, the routes rebuild (SEB-310), every ad and who sells it, the shadow detector (SEB-311, rules v4), the wide history pull, the time control on home, the Research section, finding statuses, daily files and the size guard (#719), one collection alarm (#720).

1. **Storage and the collector template (SEB-422).** Raw tables move to a data repo. One template for a board × currency collector, with its probe, quarantine and test. The gap list tool. Retire the researcher. Then the research chat writes the first fifty jobs into BACKLOG.md and the builder runs.
2. **Alive by code (SEB-423).** The computed home headline, the what-changed block, confirmed events as pages, research re-runs on a schedule.
3. **The writer (in SEB-423).** After alive-by-code is live.
4. **The cash dollar (SEB-422, step 3).** Tracker collectors from the template. Three dollars per country page.
5. **Three things you can see (SEB-424).** Cash against stablecoin, contagion on the map, the flow. Each one as the sentence it changes.

## How a finding is tested

Each finding has a test file that sets out:
- the exact calculation
- the data window
- the minimum number of observations
- what makes the test invalid
- the thresholds for holding, weaker and no longer true

Each finding has its own trigger: new hourly rows for price findings, a changed fee table for fee findings. "Rechecked" shows when the test actually ran. Each retest adds a row. Nothing earlier is overwritten.

## Publication gate

A number or finding goes live only when its test passes and these checks pass: sign direction, currency direction, source selection, stale prices, and at least one case with a known answer. Running without errors is not enough.

## What gets built

Anything new must do at least one of these:
- create a comparison that didn't exist
- start a history that can't be filled in later
- retest a claim the site already makes

Fixes that keep collection running or make existing numbers right always qualify.

## Never

- No new agents or loops. The collector, the builder, the checks and the writer, within their caps.
- No model calculates a published number.
- Nothing goes live without a passing test and words Seb approved.
- Prices a source reports from before we started stay labelled "reported, not seen by us" and never mix into our hourly series.
- Stored CSVs are never rewritten.

## Parked

- "Under investigation" page.
- Ask and the public API (SEB-213).
- Agent payments.
- Bringing back the Routes research controls.
