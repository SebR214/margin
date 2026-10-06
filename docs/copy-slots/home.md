# Copy slots: home (index.html)

Home v2 (SEB-240): page order is header, headline, whatLine, big number (bigCaption, bigLink), headlineSub, updatedLine, heatmap, what moved, stablecoin statement. Sections marked REMOVED are no longer rendered on home; their keys stay in copy.json untouched.

Every key lives in `copy.json` under `homeData`. All values start empty. The page does not render an element whose key is empty, so the page fills in as the words arrive.

Placeholders are written `{name}` inside the words; the page replaces each with the stored value. Numbers carry no `%`, `S$` or unit words: write them. A placeholder not listed for a key is not available there. Max words is per key.

Numbers, dates (day and month), currency codes and stored ids on the page are data, not copy.

## Page

| Key | What it labels | Placeholders | Max words |
| --- | --- | --- | --- |
| `metaDescription` | The page description search engines show (set in the head, not on the page). | none | 25 |

## Header

| Key | What it labels | Placeholders | Max words |
| --- | --- | --- | --- |
| `brand` | The site name, top left, links to the home page. | none | 2 |
| `navCountries` | Nav link to countries.html. | none | 2 |
| `navRoutes` | Nav link to sending-money.html (the routes). | none | 2 |
| `navSources` | Nav link to sources.html. | none | 2 |
| `navFindings` | Nav link to findings.html. | none | 2 |
| `navHow` | Nav link to how-it-works.html. | none | 3 |
| `headerLast` | Top right: when the last reading was stored. Shown only when cycle_log.json has the timestamps. | {time} = HH:MM:SS in UTC (from last_reading_utc). Add "UTC" in the words. | 6 |
| `headerNext` | Top right, after headerLast: the live countdown to the next reading, while it is not yet due. | {countdown} = mm:ss (h:mm:ss over an hour), counts down against the visitor's clock. | 6 |
| `headerOverdue` | Same place, used instead of headerNext once the next reading is late (`headerOverdueOne` for one minute). | {minutes} = whole minutes overdue. | 8 |

## Hero

| Key | What it labels | Placeholders | Max words |
| --- | --- | --- | --- |
| `headline` | The page headline (the page's h1). | {readings} {sources} {currencies} {routes} {hours} = latest totals; {gap} = Algeria's gap today in %, {country} = Algeria. Numbers carry no % sign: write it in the words. | 16 |
| `whatLine` | NEW. One line directly under the headline saying what the site is. | {currencies} = number of currencies priced (record_daily.json totals.currencies; falls back to cycle_log steps.currencies.of). | 25 |
| `bigCaption` | NEW. Caption under the page's one big number (Algeria's gap on the last day, always the last day, not the slider; the number is rounded and shows its own % sign). Replaces `bigLabel`. | {country}, {ccy}, {date}, {gap} = the gap with one decimal. | 14 |
| `bigLink` | Link text under the caption to country.html?ccy=DZD. | {country}, {ccy}, {date}, {gap} as bigCaption. | 6 |
| `headlineSub` | The subhead, now under the big number block (key unchanged, writer rewrites). | Same as headline. | 30 |
| `updatedLine` | NEW. One line under the subhead: how current the data is. The only remains of the old "This hour" section on home. | {collected} = currencies with a reading this hour, {of} = currencies expected (cycle_log.json steps.currencies). | 20 |
## Counters (REMOVED)

The five counters, their replay-date logic and `countersNote` are gone from home. Keys `counterReadings`, `counterSources`, `counterCurrencies`, `counterRoutes`, `counterHours`, `countersNote` are unused.
## Shared

| Key | What it labels | Placeholders | Max words |
| --- | --- | --- | --- |
| `dayToday` | The word shown instead of a date when the replay is on the last day (heatmap day label, counters note, widest-gaps title). If empty the date is shown. | none | 2 |

## This hour (REMOVED from home, now js/cycle_block.js)

Moved off home; another agent renders it on how-it-works.html with `renderCycleBlock(containerEl, cycleLog, copyBlock)` from `js/cycle_block.js`. The caller passes a copyBlock object with these keys (same names and placeholders as before, unchanged below): `cycleTitle`, `cycleLine`, `stepCurrencies`, `stepRoutes`, `stepAuditor`, `stepAuditorResult`, `stepAnalyst`, `resultClean`, `resultSourceMissed`, `resultCheckFailed`, `stripTitle`, `stripClean`, `stripMissed`, `stripFailed`. The `homeData` keys of those names are no longer used by home.

| Key | What it labels | Placeholders | Max words |
| --- | --- | --- | --- |
| `cycleTitle` | Heading of the section about the last collection cycle. | none | 4 |
| `cycleLine` | Small line beside the heading. | none | 14 |
| `stepCurrencies` | Row 1: currencies collected in the last cycle. | {collected} = currencies with a reading this hour, {of} = 60. | 14 |
| `stepRoutes` | Row 2: routes priced in the last cycle. | {priced}, {of} = 7. | 14 |
| `stepAuditor` | Row 3: the auditor's check, left text. | {rebuilt} = published numbers the auditor rebuilt from stored readings. | 14 |
| `stepAuditorResult` | Row 3, right side of the row: how many matched. | {matched}, {rebuilt}. | 5 |
| `stepAnalyst` | Row for the analyst. NOT RENDERED while the analyst has not run (cycle_log.json steps.analyst is null, SEB-238). When it has, every plain number field of that object is a placeholder by its own name. | depends on the analyst's stored fields; unknown until it runs | 14 |
| `resultClean` | Last row (amber dot), used when the newest cycle was clean. | none | 14 |
| `resultSourceMissed` | Last row, used when the newest cycle had a source miss. | {sources} = the source ids that missed, {n} = how many. | 14 |
| `resultCheckFailed` | Last row, used when the auditor's check failed that hour. | {sources} = what failed (audit ids), {n}. | 14 |
| `stripTitle` | Title of the 48-square strip next to the rows. | {n} = number of cycles shown (up to 48). | 8 |
| `stripClean` | Legend: a clean cycle (blue square). | none | 3 |
| `stripMissed` | Legend: a source missed (dark blue square). | none | 4 |
| `stripFailed` | Legend: a check failed (amber square). | none | 4 |

## Heatmap

| Key | What it labels | Placeholders | Max words |
| --- | --- | --- | --- |
| `heatTitle` | Heading of the heatmap section. | none | 10 |
| `heatLine` | One line under the heading on how to read the map. | none | 25 |
| `unrankedNote` | Note under the map for each currency that is drawn unranked (today: Sudan, SDG). Appears once per unranked currency. | {ccy} = SDG, {country} = Sudan. | 25 |
| `tipNone` | Hover tip text on a cell with no reading. Cells with a value show the code, date and value without words. | none | 4 |
| `heatPlay` | Play button. If empty the whole button is hidden (no Play). | none | 1 |
| `heatPause` | The same button while playing. If empty the Play word is used. | none | 1 |
| `heatDay` | Label above the day slider. | {date} = the selected day, or the dayToday word on the last day. | 6 |
| `heatSlider` | Screen-reader name of the day slider (aria-label, not shown). | none | 5 |

## Heatmap side panel

The big number moved out of the side panel to the top of the page (see Hero: `bigCaption`, `bigLink`). `bigLabel` is unused.

| Key | What it labels | Placeholders | Max words |
| --- | --- | --- | --- |
| `topTitle` | Title over the 6 widest-gap rows for the selected day. Rows are ranked strictly by the percentage, largest first, and each row shows its number (for example 90%) beside the code and bar. | {date} | 8 |
| `legendTitle` | Title of the colour legend. | none | 6 |
| `legendUnder` | Legend row for the lowest colour step. | {max} = 2 (a number; add the % sign in the words). | 5 |
| `legendBetween` | Legend row used for the three middle colour steps (8 to 25 and so on). | {min}, {max} = the step's two limits, e.g. 2 and 8, 8 and 25, 25 and 50. | 5 |
| `legendOver` | Legend row for the top colour step. | {min} = 50. | 5 |
| `legendNone` | Legend row for a cell with no reading. | none | 5 |
| `legendUnranked` | Legend row for an unranked currency (only shown when one is drawn). | none | 5 |
## Record timeline (REMOVED from home, now js/record_block.js)

Moved off home; another agent renders it on how-it-was-built.html with `renderRecordBlock(containerEl, recordDaily, milestones, copyBlock)` from `js/record_block.js`. The caller passes a copyBlock with these keys (unchanged): `recordTitle`, `recordCount` ({n} = total readings stored), `axisToday`, `markBackfill`, `markRoute`, `markSource`, `markSources`. The block no longer follows a replay day (no cursor). The `homeData` keys of those names are no longer used by home.

| Key | What it labels | Placeholders | Max words |
| --- | --- | --- | --- |
| `recordTitle` | Heading of the record section. | none | 8 |
| `recordCount` | Count beside the heading; follows the replay date. | {n} = readings stored up to the replay day. | 4 |
| `axisToday` | Right end of the time axis (the left end is the first date, 10 Aug). | none | 2 |
| `markBackfill` | Marker at the left edge for the backfilled series. All 30 start before 10 Aug 2026 (the first live reading), so they are one marker, not 30. | {n} = number of backfill series, {date} = the earliest first date (with year), {id} = its stored id (parallel_dollar_daily). | 14 |
| `markRoute` | Marker on a day when one or more routes were first priced. | {date}, {n} = routes that day, {ids} = their stored ids, e.g. SGD->PHP. | 10 |
| `markSource` | Marker part for a day when exactly ONE source began (same marker as a route if both, else alone). | {date}, {id} = the stored source id. | 10 |
| `markSources` | Marker part for a day when several sources began. | {date}, {n} = how many. | 8 |

## What moved

| Key | What it labels | Placeholders | Max words |
| --- | --- | --- | --- |
| `moversTitle` | Heading of the biggest-movers list. | none | 8 |
| `moverLine` | CHANGED (emptied; the writer refills). One line per currency (4 rows) next to its 30-day sparkline. The row links to its country page. | {country}; {baseline} = the median gap before the last 7 days, absolute value with a % sign; {baselineDir} = the dirAbove or dirBelow word by the sign of the baseline; {recent} = median of the last 7 days, absolute with a % sign; {recentDir} = dirAbove or dirBelow by its sign; {since} = first day of the baseline window (first day with a reading, e.g. 5 Sept); {until} = last day of the baseline window (the day before the last 7 days). Baseline per data/movers_week.json `definition`: the median of all days before the last 7. | 24 |
| `dirAbove` | NEW. The word for a positive gap (people pay more than the official rate), slotted into {baselineDir} and {recentDir}. | none | 3 |
| `dirBelow` | NEW. The word for a negative gap (people pay less than the official rate). | none | 3 |
## Findings (REMOVED from home)

The numbered findings cards and their data (data/findings.json) are gone from home. Keys `findingsTitle` and every `finding_*` key are unused.

## Stablecoin statement

| Key | What it labels | Placeholders | Max words |
| --- | --- | --- | --- |
| `stableLine` | NEW. The one stablecoin statement at the bottom, for SGD to PHP only. Rendered only while data/routes_summary.json route SGD->PHP has total_hours_stable_cheapest equal to 0; otherwise nothing is rendered (the claim would be false). | {hours} = hours_priced_any_amount for SGD->PHP, with thousands separator; {since} = the record start date (`start`, with year, e.g. 10 Aug 2026). | 30 |
| `stableLink` | NEW. Link under it to sending-money.html. | {hours}, {since} | 6 |
## Page

| Key | What it labels | Placeholders | Max words |
| --- | --- | --- | --- |
| `loadError` | Shown once at the bottom if any data file failed to load. | {n} = how many files failed. | 16 |

| `runLine` | Under the first line: how long the record has run. | {since}, {hours}, {readings} | 22 |
| `sourcesLine` | Next line, links to the Sources page. | {sources} | 8 |
| `agentsLine` | Next line, links to How it was built. | {agents} | 16 |
| `heatShowAll` | Button under the first 20 heatmap rows; shows the rest. Empty: all rows show. | {n} = number of currencies | 6 |
| `topPriceLine` | Under each "paying most" row: the real price against the official rate. | {price}, {ccy}, {rate} | 12 |
