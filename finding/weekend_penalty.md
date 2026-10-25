# Some apps charge more on Saturday, then cut back

Prices from the 04:00 UTC hour, 25 Oct.

A rise counts when an app charged more on a Saturday and came back down by Tuesday. If your transfer can wait, a weekday can cost less.

42 · Saturday price rises that came back down by the Tuesday after

First published 5 Oct 2026. The number updates every hour.

<https://margin.wiki/data/findings.json>

## Rises that came back, Saturday by Saturday

Each bar is one Saturday since our record began.

## These rows back the number

Each row is one route: its Saturday rises that came back, the cuts that undid them, and how many Saturdays we checked.

|  |  |  |
| --- | --- | --- |
| Singapore to the Philippines | 11 cuts that undid them, 11 Saturdays checked. | 11 Saturday rises that came back |
| Australia to the Philippines | 11 cuts that undid them, 7 Saturdays checked. | 11 Saturday rises that came back |
| United States to Mexico | 8 cuts that undid them, 10 Saturdays checked. | 8 Saturday rises that came back |
| New Zealand to the Philippines | 6 cuts that undid them, 7 Saturdays checked. | 6 Saturday rises that came back |
| Singapore to India | 2 cuts that undid them, 4 Saturdays checked. | 2 Saturday rises that came back |
| United States to India | 2 cuts that undid them, 4 Saturdays checked. | 2 Saturday rises that came back |
| United States to Nigeria | 2 cuts that undid them, 4 Saturdays checked. | 2 Saturday rises that came back |
| United States to ARS | 0 cuts that undid them, 1 Saturday checked. | 0 Saturday rises that came back |
| United States to the Philippines | 0 cuts that undid them, 1 Saturday checked. | 0 Saturday rises that came back |

## This is how we built it

We start from the confirmed price changes. A rise counts when an app raised its price on a Saturday. The same app must then cut its price on the same route by the Tuesday after. Both moves must be in our data. We never assume a return from the rise alone.

The code that works it out, open for anyone to read:

tools/emit_price_changes.py

tools/emit_pricechange_receipts.py

tools/emit_findings.py

## Read the number with these limits

A rise counts once, however many amounts it showed up at. The number does not say how much more a Saturday cost. A route with few Saturdays checked has had little chance to show this.

## Check every row yourself

The file lists every row behind the number, one line per hour or per price change. The table above summarises them.

findings_hours_weekend_penalty.csv

309 rows

<https://margin.wiki/data/findings_hours_weekend_penalty.csv>

## We also found these

|  |  |  |
| --- | --- | --- |
| 01 | Transfer apps keep changing their prices | 1,481 price changes since 12 Aug |
| 03 | Stablecoins beat the cheapest app only above about S$13.5M a month, a figure worked out from the exchanges' published fee tiers | S$13.5M a month traded on the exchange |
| 04 | Singapore to the Philippines: a stablecoin was almost never the cheapest way to send | 3 of 1,553 hours a stablecoin was cheapest |
| 05 | In 2 countries, people pay more for a dollar from each other than on an exchange | 2 countries where they disagree |
