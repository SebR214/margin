# Transfer apps keep changing their prices

Prices from the 03:00 UTC hour, 1 Nov.

Transfer apps raise and cut what they charge to send money. The cheapest app when you compare may not be the cheapest when you send.

1,722 · confirmed price changes by transfer apps since our record began

First published 5 Oct 2026. The number updates every hour.

<https://margin.wiki/data/findings.json>

## Rises and cuts, day by day

Bars above the line are price rises, bars below are cuts, counted by day.

## The numbers behind it

Each row is one route: its confirmed changes, how many were rises or cuts, and how many apps moved.

|  |  |  |
| --- | --- | --- |
| Singapore to the Philippines | 180 rises, 195 cuts, 5 apps that changed price. First change 12 Aug, latest change 31 Oct. | 375 price changes |
| New Zealand to the Philippines | 133 rises, 163 cuts, 7 apps that changed price. First change 11 Sep, latest change 31 Oct. | 296 price changes |
| Australia to the Philippines | 129 rises, 130 cuts, 9 apps that changed price. First change 11 Sep, latest change 31 Oct. | 259 price changes |
| United States to Nigeria | 110 rises, 119 cuts, 3 apps that changed price. First change 30 Sep, latest change 31 Oct. | 229 price changes |
| United States to Mexico | 108 rises, 117 cuts, 7 apps that changed price. First change 20 Aug, latest change 31 Oct. | 225 price changes |
| United States to India | 60 rises, 65 cuts, 9 apps that changed price. First change 30 Sep, latest change 31 Oct. | 125 price changes |
| Singapore to India | 44 rises, 70 cuts, 4 apps that changed price. First change 2 Oct, latest change 31 Oct. | 114 price changes |
| United States to Brazil | 18 rises, 18 cuts, 4 apps that changed price. First change 25 Oct, latest change 31 Oct. | 36 price changes |
| Australia to India | 11 rises, 16 cuts, 5 apps that changed price. First change 25 Oct, latest change 31 Oct. | 27 price changes |
| United States to the Philippines | 8 rises, 12 cuts, 4 apps that changed price. First change 23 Oct, latest change 31 Oct. | 20 price changes |
| United States to Argentina | 8 rises, 8 cuts, 3 apps that changed price. First change 23 Oct, latest change 31 Oct. | 16 price changes |

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

1,722 rows

<https://margin.wiki/data/findings_hours_price_changes.csv>

## More findings

|  |  |  |
| --- | --- | --- |
| 02 | Some apps charge more on Saturday, then cut back | 51 Saturday rises that came back |
| 03 | From Singapore to the Philippines, a stablecoin only beats the apps if you send over S$13.5M a month | S$13.5M a month traded on the exchange |
| 04 | Singapore to the Philippines: a stablecoin was almost never the cheapest way to send | 3 of 1,637 hours a stablecoin was cheapest |
| 05 | In 2 countries, people pay more for a dollar from each other than on an exchange | 2 countries where they disagree |
