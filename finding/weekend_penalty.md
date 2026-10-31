# Some apps charge more on Saturday, then cut back

Prices from the 05:00 UTC hour, 31 Oct.

A rise counts when an app charged more on a Saturday and came back down by Tuesday. If your transfer can wait, a weekday can cost less.

51 · Saturday price rises that came back down by the Tuesday after

First published 5 Oct 2026. The number updates every hour.

<https://margin.wiki/data/findings.json>

## Rises that came back, Saturday by Saturday

Each bar is one Saturday since our record began.

## The numbers behind it

Each row is one route: its Saturday rises that came back, the cuts that undid them, and how many Saturdays we checked.

|  |  |  |
| --- | --- | --- |
| Australia to the Philippines | 13 cuts that undid them, 7 Saturdays checked. | 13 Saturday rises that came back |
| Singapore to the Philippines | 12 cuts that undid them, 11 Saturdays checked. | 12 Saturday rises that came back |
| United States to Mexico | 9 cuts that undid them, 10 Saturdays checked. | 9 Saturday rises that came back |
| New Zealand to the Philippines | 7 cuts that undid them, 7 Saturdays checked. | 7 Saturday rises that came back |
| Singapore to India | 4 cuts that undid them, 4 Saturdays checked. | 4 Saturday rises that came back |
| United States to India | 3 cuts that undid them, 4 Saturdays checked. | 3 Saturday rises that came back |
| United States to Nigeria | 2 cuts that undid them, 4 Saturdays checked. | 2 Saturday rises that came back |
| United States to the Philippines | 1 cut that undid it, 1 Saturday checked. | 1 Saturday rises that came back |
| United States to Argentina | 0 cuts that undid them, 1 Saturday checked. | 0 Saturday rises that came back |
| Australia to India | 0 cuts that undid them, 0 Saturdays checked. | 0 Saturday rises that came back |
| United States to Brazil | 0 cuts that undid them, 0 Saturdays checked. | 0 Saturday rises that came back |

## How we worked it out

We start from the confirmed price changes. A rise counts when an app raised its price on a Saturday. The same app must then cut its price on the same route by the Tuesday after. Both moves must be in our data. We never assume a return from the rise alone.

The code that works it out, open for anyone to read:

tools/emit_price_changes.py

tools/emit_pricechange_receipts.py

tools/emit_findings.py

## What this doesn't tell you

A rise counts once, however many amounts it showed up at. The number does not say how much more a Saturday cost. A route with few Saturdays checked has had little chance to show this.

## Download the data

One line per hour or per price change.

findings_hours_weekend_penalty.csv

371 rows

<https://margin.wiki/data/findings_hours_weekend_penalty.csv>

## More findings

|  |  |  |
| --- | --- | --- |
| 01 | Transfer apps keep changing their prices | 1,633 price changes since 12 Aug |
| 03 | From Singapore to the Philippines, a stablecoin only beats the apps if you send over S$13.5M a month | S$13.5M a month traded on the exchange |
| 04 | Singapore to the Philippines: a stablecoin was almost never the cheapest way to send | 3 of 1,628 hours a stablecoin was cheapest |
| 05 | In 2 countries, people pay more for a dollar from each other than on an exchange | 2 countries where they disagree |
