# Country page copy slots (copy.json, block `countryData`)

Page: `country.html?ccy=XXX`. Code: `js/country_page.js`, `js/country_chart.js`.

Every key ships as an empty string. A slot that is empty renders no element, so the page shows numbers and charts without words until you fill it. You write words only; numbers, dates, percentages and currency codes are filled in by the page through `{placeholders}`. Use a placeholder exactly as written, with braces. A placeholder a slot does not list is never filled (it renders as nothing).

Dates look like `5 Oct` or `5 Oct 2026`, times like `05:06 UTC`, gaps like `90.3%` (the page adds the `%` and the minus sign). Prices are shown with the currency code by the page, never by you.

## Header

| Key | Labels | Placeholders | Max words |
|---|---|---|---|
| navCountries | Header link to the countries page | none | 2 |
| navRoutes | Header link to the routes page | none | 2 |
| navSources | Header link to the sources page | none | 2 |
| navFindings | Header link to the findings page | none | 2 |
| navHow | Header link to how it works | none | 3 |
| lastReading | Top right, when the newest stored reading came in | {time} 05:10 UTC, {date} 5 Oct, {minutes} whole minutes ago | 8 |

## Headline block

| Key | Labels | Placeholders | Max words |
|---|---|---|---|
| headlineMore | The h1 when the dollar costs more than the official rate | {country}, {gap} (like 90.3%) | 14 |
| headlineLess | The h1 when it costs less | {country}, {gap} | 14 |
| headlineSame | The h1 when the gap rounds to zero | {country} | 14 |
| leadP2p | One line under the h1, for countries priced from person-to-person ads | {country}, {ccy}, {rate} official rate per dollar, {street} street price with code | 25 |
| leadBook | The same line for countries priced from order books | {country} | 20 |
| bigCaption | Under the 88px number (today's gap, the 24-hour median) | {country} | 10 |
| unrankedNote | Shown only for a country whose official rate is frozen so it is not ranked (Sudan) | {country} | 25 |
| withheldTitle | The h1 for a country with no price this hour | {country}, {reason} | 12 |
| withheldBody | The line under it | {country}, {reason} (the pipeline's own reason text) | 25 |
| notFound | Shown when the code in the URL is not a country | {code} | 15 |
| loadFailed | Shown when the data files could not be loaded | none | 15 |

## Stats row (four cells; a cell without data is not drawn)

| Key | Labels | Placeholders | Max words |
|---|---|---|---|
| statToday | The latest hourly gap | none | 4 |
| statMedian30 | Median of the last 30 daily values | none | 4 |
| statRange30 | Lowest to highest of the last 30 daily values | none | 4 |
| statWidest | Largest gap in the stored record (its date shows under the number) | none | 5 |

## Chart section

| Key | Labels | Placeholders | Max words |
|---|---|---|---|
| chartHeading | h2 above the chart | {country} | 10 |
| chartLead | One line under the h2 | {country} | 25 |
| legendOfficial | Legend entry for the blue official-rate line | none | 4 |
| legendBand | Legend entry for the usual range band (10th to 90th percentile of the daily record) | none | 5 |
| layerDaily | Chip that toggles the published daily record line | none | 4 |
| layerBackfill | Chip that toggles the dashed backfilled history (only for countries that have one) | {venue}, {label} (the stored label, "reported, not observed") | 8 |
| unitGap | Chip: chart shows the gap in percent | none | 3 |
| unitPrice | Chip: chart shows the price per dollar and the official rate | none | 3 |
| period7 | Period chip | none | 3 |
| period30 | Period chip | none | 3 |
| periodAll | Period chip, everything stored | none | 4 |
| chartCaption | Centre of the line under the chart (between the first and last date) | none | 10 |
| chartAria | Screen-reader name of the chart | none | 8 |
| chartEmpty | Shown when the chosen period has no readings | none | 12 |
| chartFailed | Shown when a month of readings fails to load | none | 12 |
| tipOfficial | Tooltip row for the official rate | none | 3 |
| tipDaily | Tooltip row for the daily record | none | 3 |
| tipBackfill | Tooltip row for the backfilled history | {venue}, {label} | 5 |
| selWindow | Drag summary: the dates selected | none | 3 |
| selReadings | Drag summary: how many readings fall inside | none | 3 |
| selMedian | Drag summary: median gap inside | none | 4 |
| selRange | Drag summary: lowest to highest gap inside | none | 4 |

## Record position and history notes (under the chart)

The page picks one of the five sentences from the numbers, then appends `recordRange`. The two are joined with a space.

| Key | Labels | Placeholders | Max words |
|---|---|---|---|
| recordWidest | Today's gap is the widest in the record | {lo}, {hi}, {first}, {scope} | 20 |
| recordNarrowest | ... the narrowest | same | 20 |
| recordNearWidest | ... in the widest tenth | same | 20 |
| recordNearNarrowest | ... in the narrowest tenth | same | 20 |
| recordNormal | ... in the usual range | same | 20 |
| recordRange | Second half of that line: the usual range | {lo}, {hi} (percent, no sign), {first} date the record starts, {scope} | 25 |
| recordScopeVenue | Fills {scope} when the backfilled history is shown | {venue}, {label} | 12 |
| recordScopeOwn | Fills {scope} when only our own record is used | none | 6 |
| historyStart | For countries with no backfilled history: when ours starts | {date} | 20 |
| historySegmentSource | Explains the dashed line | {since} date our own record starts, {venue}, {fxSource}, {first}, {last}, {label} | 45 |
| historySegmentMoves | Lists the largest day moves in the dashed history | {moves} (the items below joined with semicolons) | 15 |
| historySegmentMoveItem | One item of that list | {delta} signed number like +5.3, {date} | 8 |

## Latest readings (receipts)

| Key | Labels | Placeholders | Max words |
|---|---|---|---|
| receiptsHeading | h2 above the list | {country} | 8 |
| receiptsLead | One line under it | {country} | 25 |
| receiptsEmpty | No readings stored | none | 10 |
| receiptsFailed | The readings failed to load | none | 10 |
| rcolTime | Column heading | none | 2 |
| rcolSource | Column heading | none | 2 |
| rcolPrice | Column heading | none | 2 |
| rcolGap | Column heading | none | 3 |
| rcolDepth | Column heading | none | 3 |
| rcolRaw | Column heading for the link to the raw file (the link text is the file path, filled by the page) | none | 3 |
| depthAds | Depth cell for a person-to-person reading | {n} ads counted, {total} ads listed on the buy side | 6 |
| depthNone | Depth cell for an order-book reading, which stores no size. Leave empty to show nothing; the page never makes up a depth | none | 4 |
| depthNowFloor | Line above the list: latest dollar depth, when the depth is a floor | {amount} like $5,000, {pct} price move allowed, {held}, {priced} | 20 |
| depthNowMoved | Same line when the price moved before reaching the full size | {amount}, {pct}, {held}, {priced} | 20 |
