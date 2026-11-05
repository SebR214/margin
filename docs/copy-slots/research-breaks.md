# Slots: the history table (SEB-437)

Rule: copy.json "researchData" (page and list row), "homeData" (range toggle, link) and "siteHead" (the page's own title).
All shipped empty. The table draws only when all five column words are filled; a row in the Research list only when its title is.

| Key | Where it shows | Variables | Max words |
| --- | --- | --- | --- |
| researchData.cardTitle3 | Research list, third row, title | none | 8 |
| researchData.cardLine3 | its one line | none | 25 |
| researchData.cardMeta3 | its small grey line | none | 15 |
| researchData.cardNumUnit3 | the small words under the row's count | none | 4 |
| researchData.breaksTitle | table page headline | none | 10 |
| researchData.breaksLead | line under it | none | 25 |
| researchData.breaksLabel | grey note: from exchange history, not our own checks | none | 15 |
| researchData.breaksNote | note under the table: how gap before and after are worked out | none | 40 |
| researchData.colCountry / colDate / colMove / colBefore / colAfter | column heads | none | 4 each |
| researchData.noPrice | cell where no dollar price existed | none | 3 |
| homeData.rangeWeek / rangeMonth / rangeAll | home grid range pills (Week, Month, All) | none | 1 |
| homeData.landTableLink | link under the home block to the table | none | 8 |
| siteHead.pages.research-breaks.html | interim title and description are the Research list's | none | n/a |
| siteHead.breaksTitle / breaksDescription | the table page's own title (set by script) | none | 10 / 25 |

The writer PR also: rewrites homeData.landLine (it said "each row"), the eventPage headings
(headingOfficialUp/Down and chartNote*, colNow: no "before our code spotted it"), and drops events-list keys no longer drawn (tagReported, tagObserved, heatEarlier, tl*).
