# Copy slots: how-it-was-built

The record growth section ("The record grew") on how-it-was-built.html, rendered by js/record_block.js.

Every key lives in `copy.json` under `machineRoom`. All values start empty. The page does not render an element whose key is empty, so the page fills in as the words arrive.

Placeholders are written `{name}` inside the words; the page replaces each with the stored value. Numbers carry no `%`, `S$` or unit words: write them. A placeholder not listed for a key is not available there. Max words is per key.

Numbers, dates (day and month), currency codes and stored ids on the page are data, not copy.

## Record timeline

| Key | What it labels | Placeholders | Max words |
| --- | --- | --- | --- |
| `recordTitle` | Heading of the record section. | none | 8 |
| `recordCount` | Count beside the heading; follows the replay date. | {n} = readings stored up to the replay day. | 4 |
| `axisToday` | Right end of the time axis (the left end is the first date, 10 Aug). | none | 2 |
| `markBackfill` | Marker at the left edge for the backfilled series. All 30 start before 10 Aug 2026 (the first live reading), so they are one marker, not 30. | {n} = number of backfill series, {date} = the earliest first date (with year), {id} = its stored id (parallel_dollar_daily). | 14 |
| `markRoute` | Marker on a day when one or more routes were first priced. | {date}, {n} = routes that day, {ids} = their stored ids, e.g. SGD->PHP. | 10 |
| `markSource` | Marker part for a day when exactly ONE source began (same marker as a route if both, else alone). | {date}, {id} = the stored source id. | 10 |
| `markSources` | Marker part for a day when several sources began. | {date}, {n} = how many. | 8 |