# Copy slots: sources.html (copy.json, block `sourcesData`)

Every key ships as an empty string. A key left empty is not rendered at all (the element is absent). Fill them on a `writer/` branch; change nothing else. Placeholders are written `{name}` and are replaced by the page with stored data; a placeholder you leave out is simply not shown. Numbers, dates, source ids, currency codes, route ids and timestamps are data, not copy. Timestamps appear exactly as stored, for example `2026-10-05T06:06:10Z`, so a trailing "UTC" is not needed (`Z` already says it).

Sentence case, no capitals for emphasis, no jargon. Word limits are maxima.

## Header
| Key | Labels | Placeholders | Max words |
|---|---|---|---|
| pageTitle | browser tab title | none | 4 |
| logo | the site name link, top left (links to the home page) | none | 2 |
| navCountries, navRoutes, navSources, navFindings, navHowItWorks | the five nav links (Sources is the current page) | none | 3 each |
| headerAsOf | top right: when the newest stored reading was taken | {time} stored timestamp, {day} date, {clock} time | 8 |

## Top of page
| Key | Labels | Placeholders | Max words |
|---|---|---|---|
| headline | the h1 | none | 12 |
| headlineSub | the one line under the h1 | none | 25 |
| bigLabel | label under the one big number (sources live, from the record totals) | {n} the number | 10 |
| statLive | stats row, cell 1: sources live | {n} | 6 |
| statWithHistory | cell 2: sources that have history before 10 Aug (counts every source with stored history, including the two that have history only) | {n} | 8 |
| statNoHistory | cell 3: sources with no history | {n} | 6 |

## Filter and legend
| Key | Labels | Placeholders | Max words |
|---|---|---|---|
| filterLabel | accessible name of the filter chip group (not visible) | none | 4 |
| kindAll | chip: show every source | none | 2 |
| kindP2p, kindOrderBook, kindBroker, kindFx, kindProviderQuote, kindOther | chip, and the small label on each row, for the kinds `p2p`, `order_book`, `broker`, `fx`, `provider_quote`, `other` | none | 3 each |
| shown | count beside the legend | {n} shown, {total} all sources | 6 |
| legendHeading | lead-in before the four swatches | none | 4 |
| statusAnsweredEveryHour | swatch and square tooltip: the source answered in every hour that was collected that day | none | 5 |
| statusMissedSome | swatch: it missed some of those hours | none | 4 |
| statusMissedAll | swatch: it missed all of them | none | 4 |
| statusNotYetASource | swatch: the day is before its first reading | none | 5 |

## Lists
| Key | Labels | Placeholders | Max words |
|---|---|---|---|
| liveHeading | h2 above the live sources | {n} count in this list | 5 |
| historyOnlyHeading | h2 above sources with no stored live reading (history only); the list is hidden when empty | {n} | 6 |

## One source row
| Key | Labels | Placeholders | Max words |
|---|---|---|---|
| lastAnswered | when the source last answered | {time} stored timestamp, {day}, {clock} | 6 |
| ageMinutes, ageHours, ageDays | how long before the page's newest reading it answered (measured against the data's own time, not the reader's clock; minutes under 1 hour, hours under 48, then days) | {n} whole number | 8 each |
| neverAnswered | shown instead of "last answered" when no live reading is stored | none | 6 |
| firstSeen | first stored reading | {date} | 6 |
| hoursAnswered | hours with a reading against hours expected, whole record | {answered}, {expected} | 8 |
| stripCaption | caption over the per-day squares | {days} number of days, {first}, {last} dates | 8 |
| stripDay | tooltip and accessible name of each square | {day} date, {status} the status words above | 6 |
| currenciesToggle | button that opens the list of currency codes the source covers (hidden when the source carries none) | {n} | 4 |
| routesToggle | button that opens the list of routes, such as USD->MXN, the source quotes (hidden when none) | {n} | 4 |

## History before 10 Aug
| Key | Labels | Placeholders | Max words |
|---|---|---|---|
| historyHeading | small label above the history column | none | 5 |
| historyLine | one line per stored history series | {series}, {ccy}, {interval}, {first} date, {last} date, {rows} | 12 |
| historyNone | shown when the source has no stored history | none | 5 |
| historyReason | the stored reason no history exists. The reason is stored text from METHODOLOGY.md and is shown exactly as stored; it goes in {reason}. Empty where none is stored | {reason} | 8 around the placeholder |
| historyVerdict | the stored probe verdict and the endpoint it names, shown as stored | {verdict}, {endpoint} | 6 around the placeholders |

## Error
| Key | Labels | Placeholders | Max words |
|---|---|---|---|
| loadFailed | shown if data/sources_daily.json cannot be loaded | none | 12 |
| ageMinuteOne / ageHourOne / ageDayOne | The age line when the count is exactly one (singular). | {n} | 10 |
| currenciesToggleOne / routesToggleOne | The coverage button when a source covers exactly one currency or one route (singular). | {n} | 8 |
| historyLineNoCcy | A history series line when the series has no single currency (for example a set of markets). | {series}, {first}, {last}, {rows} | 12 |

## Added after the owner's review (SEB-240)

| Key | Labels | Placeholders | Max words |
|---|---|---|---|
| statHistoryOnly | Count of sources that gave older prices only (not read every hour) | {n} | 8 |
| reason_snapshot_only, reason_needs_key, reason_blocked, reason_login_only, reason_no_endpoint, reason_other | Why a source has no older prices, in plain words, by kind (no codes, no endpoints) | none | 25 |
| coverageCurrencies, coverageCurrenciesOne, coverageRoutes, coverageRoutesOne | How many currencies or sending routes a source covers (plain count, no code list) | {n} | 8 |
| sourceNames (object) | A readable name for a stored source id | n/a | n/a |
| bigLabel (changed) | Now labels the count of ALL sources | {n} | 6 |
