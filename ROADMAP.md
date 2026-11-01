# Roadmap

Updated 24 Oct 2026 (devaluation watch, approved by Seb in chat, SEB-384; events plan of 22 Oct, SEB-311). Seb owns this file. Agents change it only from a spec Seb approved.

## What margin.wiki is

Every hour it prices a dollar in over 50 countries against the official rate, and prices sending money on 11 routes with every fee we can measure.

## In six months (April 2027)

A devaluation watch that makes dated claims per country and scores itself in public, on top of the events record and 25 years of history. Each event in the record is found by code from our own hourly prices, checked against a second source, and retested as new data comes in.

Where it stands (24 Oct 2026, SEB-384): the 25 years of history are built as a time control on the home grid. The claims are not. The first backtest did not show that a big premium comes before an official step, for currencies with controls (a 10% step within 12 months followed 26% of month starts with a premium of 10% or more, and 36% of those under 2%). The watch is built only once a backtest on more data shows the premium does come first. What we do know is where the official rate landed after past breaks, and the table of those landings is in data/history/backtest_landing.csv.

It rests on three things:

1. **Findings that age honestly.** Each finding is retested by code. It shows whether it still holds, got weaker or is no longer true. The original claim and its evidence stay up with their date.
2. **Sources checked against each other.** Every pair of sources measuring the same market is compared hour by hour. An event is confirmed only when two sources agree.
3. **A depth and liquidity record.** What a dollar costs at several amounts, and every ad we can read on the person-to-person boards, not the first 10. Collected from the day it starts.

## What counts as an event

- **Official break:** the official rate steps 3% or more within 3 days.
- **Street slide:** the street price moves 10% or more in 7 days, in a market we publish (10 or more ads).
- **Not an event:** thin markets, slow drifts that never cross the line, and anything caused by our own source breaking. A stale, looping or broken official rate is a data warning, never an event.
- **Confirmed** when two official sources show the step, or two street sources move together. With one source, the record says "one source". No model confirms anything.
- **Each event record holds:** what changed against a set baseline, the street before, how long the official source took to catch up, offer counts and depth where we have them, what happened after, and the quality checks on every source used.
- **Reopened** weekly for 8 weeks as the "after" fills in, then closed. Nothing is ever rewritten.

## Order

Done since 11 Oct: SEB-268, finding test files, source comparisons, depth collection, the routes rebuild (SEB-310).

1. **Coinbase fee correction (SEB-310).** USDT-USD lost stablecoin pricing in May 2025. Fix the fee with its source and date, keep the old fee regime identifiable, and add a check that fails if a venue loses a pair's special pricing.
2. **Read every person-to-person ad,** not 10 per side. Liquidity history can't be added later.
3. **Retest the stress finding against the street price.** 12 of its 13 triggers come from er-api's broken Sudan rate.
4. **The event detector, in shadow mode (SEB-311).** Plain code. Writes event records to a file and publishes nothing. It must show four things before anything goes live:
   - the same data always gives the same events and numbers
   - a broken or stale official rate never shows up as an event
   - it can be replayed over the history we have, including cases that should not trigger
   - every number in a record traces to stored rows, and "not enough evidence" is a valid result
5. **One event page,** built from the record, after the detector passes. Iraq, Sudan and Bolivia are the test cases, not promises. More pages only once the first one holds.
6. **Finding statuses on the site.**

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

- Only the four agents in SEB-301, within their caps. No new agents or loops.
- No model calculates a published number.
- Nothing goes live without a passing test and words Seb approved.
- Prices a source reports from before we started stay labelled "reported, not seen by us" and never mix into our hourly series.
- Stored CSVs are never rewritten.

## Parked

- "Under investigation" page.
- Ask and the public API (SEB-213).
- Agent payments.
- Bringing back the Routes research controls.
