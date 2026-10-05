# Copy slots: finding.html and findings.html (SEB-240, page 5)

All keys live in `copy.json` under `findingData`. Every key ships as an empty string. An element whose key is empty is not rendered, so the page stays bare until the writer fills it. Numbers, dates, ids, file paths and route/currency codes come from `data/findings.json` and are never copy. No key has placeholders: the page puts data next to the text, it never substitutes into it. Where a number sits beside a label, write the label so it reads after the number ("1,129 rows") or above it.

Published findings, in page order (01, 02, 03 as on the home page): `price_changes`, `weekend_penalty`, `volume_crossover`. `stress_signal` and `p2p_spread_signal` are unpublished and get no page.

## What each finding's number means (do not describe it any other way)

- **price_changes** (788): the number of confirmed price changes since the record began. It counts changes, not days.
- **weekend_penalty** (25): Saturday checks on which a provider charged more than the day before and then came back down within two days. Evidence rows per route: `weekend_up` (the number above, summed over routes), `weekend_back`, `saturdays_judged`.
- **volume_crossover** (4,437,100): the monthly volume in Singapore dollars above which, for S$5,000 sent from Singapore to the Philippines with a market order, the stablecoin route's cost, rebuilt from real samples with the fee tier that volume unlocks, drops below the best other app's typical cost. It was never watched happening. One route, one amount. Its last recheck time is stale (2026-10-02) because no collector step refreshes it; the page shows the stored time as is. Two evidence rows (taker, maker) are two fee schedules for the same route, not two routes.

## Shared keys

| Key | Labels | Max words |
|---|---|---|
| navCountries, navRoutes, navSources, navFindings, navHowItWorks | The five header links (Countries, Routes, Sources, Findings, How it works) | 3 each |
| indexTitle | Browser tab title of findings.html (after "margin.wiki") | 4 |
| indexHeading | h1 of the findings index | 8 |
| indexLine | One line under the index heading | 25 |
| evidenceHeading | h2 of the evidence list | 6 |
| methodHeading | h2 of the method section | 6 |
| methodFilesLabel | Line above the list of method files (links to the files on GitHub) | 15 |
| limitsHeading | h2 of "what it doesn't cover" | 8 |
| relatedHeading | h2 above the cards of the other findings | 6 |
| downloadHeading | h2 of the download section | 6 |
| downloadNote | One line under it: what the file holds (one row per underlying hour or event) | 20 |
| downloadRows | Label after the row count, e.g. "rows" | 2 |
| downloadSize | Label after the file size, e.g. "download size" | 3 |
| lastRecheck | Label for the stored last recheck time (UTC); also used on cards | 4 |
| statRows | Stats cell label: rows in the download | 4 |
| statSize | Stats cell label: file size | 4 |
| statEvidence | Stats cell label: how many evidence rows | 4 |
| notFound | Message when `?id=` is unknown or unpublished | 20 |
| notFoundLink | Link text back to findings.html | 5 |
| side_taker, side_maker | Words under the route code on volume_crossover rows, plain-language names for the two fee schedules | 4 each |

## Unit keys (big number caption and card caption; keyed by the stored unit)

| Key | Caption for |
|---|---|
| unit_price_changes | 788: confirmed price changes since the record began | 
| unit_weekend_increases | 25: Saturdays a provider charged more then came back down within two days |
| unit_sgd_per_month | 4,437,100: monthly volume in S$ (see the exact meaning above) |

Max 15 words each. The number is shown above the caption; do not repeat it.

## Field labels (each evidence number that is not the bar)

Shown as "number label" under each row. Max 5 words each. The bar and its right-hand number is the first field of each finding: `changes`, `weekend_up`, `monthly_volume_sgd`; its label is also shown above the list.

`field_changes`, `field_up` (price rises), `field_down` (price falls), `field_providers` (providers that changed price), `field_first_day`, `field_last_day` (dates), `field_weekend_up`, `field_weekend_back` (came back down within two days), `field_saturdays_judged`, `field_monthly_volume_sgd`, `field_monthly_volume_aud_on_ir` (the same volume in A$ on the other exchange's tier ladder), `field_cost_bps_at_floor` / `field_cost_bps_at_ceiling` (stablecoin route cost in basis points at the lowest and highest fee tier), `field_fee_pct_at_crossover_ir` (exchange fee in percent at the crossover tier), `field_baseline_cost_bps_median` (best other app's typical cost, basis points), `field_n_samples` (samples behind it), `field_rung_sgd` (amount sent, S$).

## Per-finding keys (one set for each of price_changes, weekend_penalty, volume_crossover)

| Key | Labels | Max words |
|---|---|---|
| title_<id> | h1 on the finding page; card title on the index and in related findings | 10 |
| claim_<id> | The claim: one line under the h1 | 30 |
| evidenceBasis_<id> | One line under the evidence heading saying what each row counts | 25 |
| method_<id> | Paragraph on how the number is built | 90 |
| limits_<id> | Paragraph on what the finding does not cover | 90 |

## Data notes for the writer

- Evidence is present for all three published findings (7 route rows, 7 route rows, 2 rows).
- Download: `data/findings_hours_<id>.csv` with its stored row count and size read from the file.
- Related findings are cards for the other two published findings.
- Last recheck is the stored `last_recheck_utc`, shown in UTC.
