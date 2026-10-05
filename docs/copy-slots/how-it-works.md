# Copy slots: how-it-works.html

Every key lives in `copy.json` under `howItWorks`. All values start empty. The page does not render an element whose key is empty, so the page fills in as the words arrive.

Placeholders are written `{name}` inside the words; the page replaces each with the stored value. Numbers carry no `%`, `S$` or unit words: write them. A placeholder not listed for a key is not available there. Max words is per key.

Numbers, dates (day and month), currency codes and stored ids on the page are data, not copy.

## Hourly collection ("This hour")

Moved off home; another agent renders it on how-it-works.html with `renderCycleBlock(containerEl, cycleLog, copyBlock)` from `js/cycle_block.js`. The caller passes a copyBlock object with these keys (same names and placeholders as docs/copy-slots/home.md "This hour"): `cycleTitle`, `cycleLine`, `stepCurrencies`, `stepRoutes`, `stepAuditor`, `stepAuditorResult`, `stepAnalyst`, `resultClean`, `resultSourceMissed`, `resultCheckFailed`, `stripTitle`, `stripClean`, `stripMissed`, `stripFailed`. 

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