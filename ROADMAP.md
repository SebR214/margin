# Roadmap

Updated 11 Oct 2026. Seb owns this file. Agents change it only from a spec Seb approved.

## What margin.wiki is

Every hour it prices a dollar in 60 countries against the official rate, and prices sending money on 7 routes with every fee we can measure.

## In six months (April 2027)

The same site, plus three things it doesn't have today.

1. **Findings that age honestly.** Each finding is retested by code. It shows whether it still holds, got weaker or is no longer true. The original claim and its evidence stay up with their date.
2. **Sources checked against each other.** Every pair of sources measuring the same market is compared hour by hour. A gap that lasts is flagged as a possible finding.
3. **A depth record.** What a dollar costs at several amounts, not just at the best price, collected from the day it starts.

## Order

1. SEB-268, items 1 to 11. Data checks and fixes come first.
2. Write down how a finding is tested (below) before building anything else, so new comparisons are stored in a form that can be retested.
3. Source comparisons. Only compare sources that are comparable: same kind of market, same amount, same hour. A gap must last past a set threshold before it counts. Use each source's own history where both have one.
4. Depth collection.
5. Finding statuses on the site.

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
- Linking country prices to route costs. Only the Philippines and Mexico overlap.
- Ask and the public API (SEB-213).
- Agent payments.
- Bringing back the Routes research controls.
