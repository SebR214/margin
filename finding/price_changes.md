# Transfer apps keep changing their prices

Prices from the 13:00 UTC hour, 23 Oct.

Transfer apps raise and cut what they charge to send money. The cheapest app when you compare may not be the cheapest when you send.

1,366 · confirmed price changes by transfer apps since our record began

First published 5 Oct 2026. The number updates every hour.

<https://margin.wiki/data/findings.json>

## Rises and cuts, day by day

Bars above the line are price rises, bars below are cuts, counted by day.

## These rows back the number

Each row is one route: its confirmed changes, how many were rises or cuts, and how many apps moved.

|  |  |  |
| --- | --- | --- |
| Singapore to the Philippines | 166 rises, 173 cuts, 5 apps that changed price. First change 12 Aug, latest change 22 Oct. | 339 price changes |
| New Zealand to the Philippines | 118 rises, 138 cuts, 7 apps that changed price. First change 11 Sep, latest change 22 Oct. | 256 price changes |
| Australia to the Philippines | 116 rises, 110 cuts, 9 apps that changed price. First change 11 Sep, latest change 22 Oct. | 226 price changes |
| United States to Mexico | 89 rises, 97 cuts, 7 apps that changed price. First change 20 Aug, latest change 22 Oct. | 186 price changes |
| United States to Nigeria | 80 rises, 90 cuts, 3 apps that changed price. First change 30 Sep, latest change 22 Oct. | 170 price changes |
| United States to India | 50 rises, 45 cuts, 9 apps that changed price. First change 30 Sep, latest change 22 Oct. | 95 price changes |
| Singapore to India | 34 rises, 60 cuts, 4 apps that changed price. First change 2 Oct, latest change 22 Oct. | 94 price changes |

## This is how we built it

We record each app's cost every hour, for each amount sent, against the real exchange rate. A change counts only when one app's daily cost moved against every other app on the same route. It must move the same way, on the same day, by more than a small set amount. Moves that every app shares come from the exchange rate and never count. Each day needs several hourly readings, and a day is judged only once it has ended.

The code that works it out, open for anyone to read:

tools/emit_price_changes.py

tools/emit_pricechange_receipts.py

tools/emit_findings.py

## Read the number with these limits

Each amount sent counts on its own. An app that changes its price at several amounts counts once for each. The number does not say how big any change was. It covers only the routes and apps we check, from the day each was added.

## Check every row yourself

The file lists every row behind the number, one line per hour or per price change. The table above summarises them.

findings_hours_price_changes.csv

1,366 rows

<https://margin.wiki/data/findings_hours_price_changes.csv>

## We also found these

|  |  |  |
| --- | --- | --- |
| 02 | Some apps charge more on Saturday, then cut back | 42 Saturday rises that came back |
| 03 | Stablecoins beat the cheapest app only above about S$20.4M a month, a figure worked out from the exchanges' published fee tiers | S$20.4M a month traded on the exchange |
| 04 | Singapore to the Philippines: a stablecoin was almost never the cheapest way to send | 3 of 1,514 hours a stablecoin was cheapest |
| 05 | In 2 countries, people pay more for a dollar from each other than on an exchange | 2 countries where they disagree |
