# Transfer apps keep changing their prices

Prices from the 00:00 UTC hour, 26 Oct.

Transfer apps raise and cut what they charge to send money. The cheapest app when you compare may not be the cheapest when you send.

1,494 · confirmed price changes by transfer apps since our record began

First published 5 Oct 2026. The number updates every hour.

<https://margin.wiki/data/findings.json>

## Rises and cuts, day by day

Bars above the line are price rises, bars below are cuts, counted by day.

## These rows back the number

Each row is one route: its confirmed changes, how many were rises or cuts, and how many apps moved.

|  |  |  |
| --- | --- | --- |
| Singapore to the Philippines | 167 rises, 182 cuts, 5 apps that changed price. First change 12 Aug, latest change 24 Oct. | 349 price changes |
| New Zealand to the Philippines | 128 rises, 149 cuts, 7 apps that changed price. First change 11 Sep, latest change 25 Oct. | 277 price changes |
| Australia to the Philippines | 126 rises, 115 cuts, 9 apps that changed price. First change 11 Sep, latest change 24 Oct. | 241 price changes |
| United States to Mexico | 99 rises, 105 cuts, 7 apps that changed price. First change 20 Aug, latest change 24 Oct. | 204 price changes |
| United States to Nigeria | 90 rises, 99 cuts, 3 apps that changed price. First change 30 Sep, latest change 24 Oct. | 189 price changes |
| United States to India | 59 rises, 50 cuts, 9 apps that changed price. First change 30 Sep, latest change 24 Oct. | 109 price changes |
| Singapore to India | 39 rises, 65 cuts, 4 apps that changed price. First change 2 Oct, latest change 24 Oct. | 104 price changes |
| United States to the Philippines | 5 rises, 4 cuts, 3 apps that changed price. First change 23 Oct, latest change 24 Oct. | 9 price changes |
| United States to ARS | 2 rises, 4 cuts, 1 apps that changed price. First change 23 Oct, latest change 25 Oct. | 6 price changes |
| Australia to India | 0 rises, 3 cuts, 1 apps that changed price. First change 25 Oct, latest change 25 Oct. | 3 price changes |
| United States to BRL | 3 rises, 0 cuts, 1 apps that changed price. First change 25 Oct, latest change 25 Oct. | 3 price changes |

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

1,494 rows

<https://margin.wiki/data/findings_hours_price_changes.csv>

## We also found these

|  |  |  |
| --- | --- | --- |
| 02 | Some apps charge more on Saturday, then cut back | 42 Saturday rises that came back |
| 03 | Stablecoins beat the cheapest app only above about S$13.5M a month, a figure worked out from the exchanges' published fee tiers | S$13.5M a month traded on the exchange |
| 04 | Singapore to the Philippines: a stablecoin was almost never the cheapest way to send | 3 of 1,573 hours a stablecoin was cheapest |
| 05 | In 2 countries, people pay more for a dollar from each other than on an exchange | 2 countries where they disagree |
