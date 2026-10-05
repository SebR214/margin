# Routes page copy slots (copy.json, block `routeData`)

Page: `sending-money.html` (the routes index and the route page in one). Code: `js/route.js`. The route is chosen by the chips, by `?route=SGD-PHP` or by `#SGD-PHP`; the first stored route is the default. `?amount=5000` picks the amount.

Every key ships as an empty string. A slot that is empty renders no element, so the page shows numbers and charts without words until you fill it. You write words only. Numbers, dates, percentages, currency codes and route labels (`SGD → PHP`, formed from the stored codes) are filled in by the page. Use a placeholder exactly as written, with braces. A placeholder a slot does not list is never filled (it renders as nothing).

Formats the page uses: dates `5 Oct`, times `05:06 UTC`, costs `240.48 SGD` (the sending currency's code), shares `0.96%`. A leading minus means the stablecoin path costs less than the app (or, on the two negative-cost routes, less than the official rate: write nothing that reads a negative number as "a win" without the owner's wording).

Where a slot has a data fallback it is noted: the page still shows the number or code without your words.

## Header

| Key | Labels | Placeholders | Max words |
|---|---|---|---|
| navCountries | Header link to the countries page | none | 2 |
| navRoutes | Header link to this page (shown as the current page) | none | 2 |
| navSources | Header link to the sources page | none | 2 |
| navFindings | Header link to the findings page | none | 2 |
| navHow | Header link to how it works | none | 3 |
| lastReading | Top right: when the newest stored hour of the route files is | {time} 05:00 UTC, {date} 5 Oct, {minutes} whole minutes ago | 8 |

## Route and amount chips

The route chips are the seven stored routes, labelled by the page (`SGD → PHP`). The amount chips read `5,000 SGD`: both are data, not copy.

| Key | Labels | Placeholders | Max words |
|---|---|---|---|
| amountLabel | Short label in front of the amount chips (the amount applies to the whole page: chart, breakdown, comparison and what-would-have-to-change) | {ccy} the route's sending currency code | 5 |

## Headline block

| Key | Labels | Placeholders | Max words |
|---|---|---|---|
| headline | The h1 (24px) | {route} `SGD → PHP`, {send} `SGD`, {recv} `PHP`, {amount} `5,000 SGD` | 14 |
| lead | One line under the h1 | {route}, {send}, {recv}, {amount} | 25 |
| bigCaption | Under the 88px number. The number is the count of hours a stablecoin path was the cheapest way since 10 Aug (any of the five amounts) | {route}, {hours} that same number, {priced} hours priced on this route | 14 |
| loadFailed | Shown alone when the route files could not be loaded | none | 15 |

## Chart section

The chart plots the cheapest stablecoin path (amber) against the cheapest app (blue) hour by hour, the gap shaded. Hover shows one hour; dragging selects a window.

| Key | Labels | Placeholders | Max words |
|---|---|---|---|
| legendStable | Legend entry for the amber line | none | 4 |
| legendApp | Legend entry for the blue line | none | 3 |
| legendGap | Legend entry for the shaded gap (the stablecoin path's extra cost over the app) | none | 6 |
| unitAbs | Chip: cost in the sending currency. Fallback when empty: the currency code alone | {ccy} | 3 |
| unitRel | Chip: cost as a share of the amount. Fallback when empty: `%` | none | 4 |
| period7 | Period chip, last 7 days of stored hours | none | 3 |
| period30 | Period chip, last 30 days | none | 3 |
| periodAll | Period chip, everything stored | {date} first day of collection, `10 Aug` | 4 |
| chartAria | Screen-reader label of the chart | none | 15 |
| chartCaptionAbs | Centre of the line under the chart, when costs are in currency (the first and last date sit either side) | {ccy} | 12 |
| chartCaptionRel | Same, when costs are a share of the amount | none | 12 |
| tipStable | Hover tip: label before the stablecoin path's cost (the page adds the cost and the path id, like `USDC:ArbitrumOne`) | none | 3 |
| tipApp | Hover tip: label before the cheapest app's cost (the page adds the cost and the app's name) | none | 3 |
| tipExtra | Hover tip: label before the stablecoin path minus the app (a number with a minus when the path is cheaper) | none | 3 |

## Stats row (for the dragged window, or the whole period when nothing is dragged)

Computed in code from the stored hours inside the window. A cell with no value is not drawn; a cell whose label slot is empty still shows its number.

| Key | Labels | Placeholders | Max words |
|---|---|---|---|
| statWindow | First and last day of the window (`11 Sep – 21 Sep`) | none | 3 |
| statCheapest | Hours the stablecoin path was cheaper. The value reads `N / M`: N of the M priced hours in the window | none | 6 |
| statTypical | Median of the hourly extra cost (stablecoin path minus cheapest app) | none | 4 |
| statClosest | The hour the path came closest to, or beat, the app (the smallest extra cost). The hour shows under the number | none | 4 |
| statWidest | The hour the gap was widest (the largest extra cost). The hour shows under the number | none | 4 |

## Cost breakdown (date slider)

The slider moves through the stored days; each position shows that day's last stored hour. The stacked bar and the leg rows come from `data/routes_breakdown.json`. Getting in is deposit plus buying the stablecoin; cashing out is selling it plus withdrawing. A leg that is not stored for the hour is an empty slot (no number, no bar). "Converting" is not stored as a leg of its own (it sits inside buying and selling), so it has no row and no slot.

| Key | Labels | Placeholders | Max words |
|---|---|---|---|
| breakdownHeading | h2 above the breakdown | none | 8 |
| breakdownLead | One line under the h2 | none | 20 |
| breakdownLoading | Shown while the breakdown file loads | none | 5 |
| breakdownFailed | Shown when it could not be loaded | none | 12 |
| sliderLabel | Label of the date slider (the chosen hour is appended by the page, `29 Aug, 23:00 UTC`) | none | 3 |
| legGettingIn | Row: deposit plus buying the stablecoin. Empty slot where either is not stored (before 29 Sep) or the deposit fee is unmeasured (NZD to PHP) | none | 4 |
| legOnChain | Row: the network fee for moving the stablecoin. Stored from 23 Sep (29 Sep on the NGN and INR routes) | none | 4 |
| legCashingOut | Row: selling the stablecoin plus withdrawing. Empty slot where either is not stored | none | 4 |
| legTotal | Row: the stablecoin path, all in (the base path's stored total) | none | 5 |
| legApp | Row: the cheapest app, all in | none | 5 |
| legsMissing | Note under the rows, shown only when a leg is empty for the chosen hour | {date} the chosen day | 25 |
| legsUnmeasured | Note, shown only when a deposit or withdrawal fee is flagged unmeasured for that hour | {date} | 25 |

## All routes compared

Rows are the seven routes at the chosen amount; clicking a row switches the whole page to that route. A value that is not stored (the 7-day change on the three routes with six days of data) is an empty slot.

| Key | Labels | Placeholders | Max words |
|---|---|---|---|
| compareHeading | h2 above the comparison | none | 8 |
| compareLead | One line under the h2 | none | 20 |
| metricWin | Chip: share of priced hours the stablecoin path was cheaper | none | 6 |
| metricTypical | Chip: median extra cost | none | 4 |
| metricSwing | Chip: swing (the 90th minus the 10th percentile of the hourly extra cost) | none | 4 |
| metricChange | Chip: change in the typical extra cost over the last 7 days | none | 5 |

## What would have to change

One line per route at the chosen amount, from `data/routes_whatif.json`. The main figure is the median of the last 7 days; the "latest hour" figure sits beneath it. Null values are not drawn.

| Key | Labels | Placeholders | Max words |
|---|---|---|---|
| whatHeading | h2 | none | 8 |
| whatLead | One line under the h2 | {amount} `5,000 SGD`, {ccy} | 20 |
| whatNeeded | Words after the figure: how much cheaper getting in and out must be together for the stablecoin path to match the cheapest app | {route}, {units} `240.48 SGD`, {pp} `0.96%`, {ccy} | 12 |
| whatShare | Optional second line: that figure as a share of the getting-in and cashing-out legs (shown only where those legs are stored) | {pct} `79%` | 12 |
| whatWins | Shown instead of a figure when the 7-day median already has the stablecoin path at or below the app | {route} | 8 |
| whatLatest | Words after the latest hour's figure | {units}, {pp} | 6 |
| whatLatestWins | Shown when the latest hour already has the path at or below the app | none | 8 |

## Added after the owner's review (SEB-240)

| Key | Labels | Placeholders | Max words |
|---|---|---|---|
| notComparable | One line under the compare list and the what-would-have-to-change list saying which routes are left out and why | {routes} | 30 |
| routeNotComparable | Shown under the big number when the selected route is one of those left out | none | 25 |
| whatAppChanged | Shown when the cheapest app changed during the week: names the app that was cheapest most hours | {app} {hours} {of} | 25 |
| whatPathNote | Shown when the what-would-have-to-change figures use a different stablecoin path from the steps shown above | {path} {base} {hour} | 40 |
| whatNeeded (changed) | Now names the cheapest app of the week | {route} {units} {pp} {ccy} {app} | 20 |
| whatLatest (changed) | Names the hour and the cheapest app in it | {units} {pp} {app} {hour} | 20 |
