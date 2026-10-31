# Transfer apps keep changing their prices

Prices from the 11:00 UTC hour, 31 Oct.

Transfer apps raise and cut what they charge to send money. The cheapest app when you compare may not be the cheapest when you send.

1,633 · confirmed price changes by transfer apps since our record began

First published 5 Oct 2026. The number updates every hour.

<https://margin.wiki/data/findings.json>

## Rises and cuts, day by day

Bars above the line are price rises, bars below are cuts, counted by day.

## The numbers behind it

Each row is one route: its confirmed changes, how many were rises or cuts, and how many apps moved.

|  |  |  |
| --- | --- | --- |
| Singapore to the Philippines | 175 rises, 195 cuts, 5 apps that changed price. First change 12 Aug, latest change 28 Oct. | 370 price changes |
| New Zealand to the Philippines | 128 rises, 158 cuts, 7 apps that changed price. First change 11 Sep, latest change 28 Oct. | 286 price changes |
| Australia to the Philippines | 124 rises, 125 cuts, 9 apps that changed price. First change 11 Sep, latest change 28 Oct. | 249 price changes |
| United States to Nigeria | 105 rises, 114 cuts, 3 apps that changed price. First change 30 Sep, latest change 28 Oct. | 219 price changes |
| United States to Mexico | 103 rises, 114 cuts, 7 apps that changed price. First change 20 Aug, latest change 28 Oct. | 217 price changes |
| United States to India | 55 rises, 60 cuts, 9 apps that changed price. First change 30 Sep, latest change 28 Oct. | 115 price changes |
| Singapore to India | 39 rises, 65 cuts, 4 apps that changed price. First change 2 Oct, latest change 27 Oct. | 104 price changes |
| United States to Brazil | 13 rises, 14 cuts, 4 apps that changed price. First change 25 Oct, latest change 28 Oct. | 27 price changes |
| Australia to India | 6 rises, 16 cuts, 5 apps that changed price. First change 25 Oct, latest change 28 Oct. | 22 price changes |
| United States to Argentina | 6 rises, 6 cuts, 2 apps that changed price. First change 23 Oct, latest change 28 Oct. | 12 price changes |
| United States to the Philippines | 3 rises, 9 cuts, 3 apps that changed price. First change 23 Oct, latest change 28 Oct. | 12 price changes |

## How we worked it out

We record each app's cost every hour, for each amount sent, against the official rate. A change counts only when one app's daily cost moved against every other app on the same route. It must move the same way, on the same day, by more than a small set amount. Moves that every app shares come from the exchange rate and never count. Each day needs several hourly readings, and a day is judged only once it has ended.

The code that works it out, open for anyone to read:

tools/emit_price_changes.py

tools/emit_pricechange_receipts.py

tools/emit_findings.py

## What this doesn't tell you

Each amount sent counts on its own. An app that changes its price at several amounts counts once for each. The number does not say how big any change was. It covers only the routes and apps we check, from the day each was added.

## Download the data

One line per hour or per price change.

findings_hours_price_changes.csv

1,633 rows

<https://margin.wiki/data/findings_hours_price_changes.csv>

## More findings

|  |  |  |
| --- | --- | --- |
| 02 | Some apps charge more on Saturday, then cut back | 51 Saturday rises that came back |
| 03 | From Singapore to the Philippines, a stablecoin only beats the apps if you send over S$13.5M a month | S$13.5M a month traded on the exchange |
| 04 | Singapore to the Philippines: a stablecoin was almost never the cheapest way to send | 3 of 1,632 hours a stablecoin was cheapest |
| 05 | In 2 countries, people pay more for a dollar from each other than on an exchange | 2 countries where they disagree |
