# Singapore to the Philippines: a stablecoin was almost never the cheapest way to send

Prices from the 06:00 UTC hour, 28 Oct.

In 1,609 of the 1,612 hours we priced, a stablecoin did not beat the cheapest app at any of the five amounts.

3 · hours in which a stablecoin was the cheapest way to send

First published 5 Oct 2026. The number updates every hour.

<https://margin.wiki/data/findings.json>

## How much more the stablecoin cost, hour by hour

Sending S$5,000 from Singapore to the Philippines. Below the dark line, the stablecoin was cheaper than every app. The dots are those hours.

## The numbers behind it

Each row is one amount sent from Singapore to the Philippines: the hours we priced, and the hours in which a stablecoin was cheapest.

|  |  |  |
| --- | --- | --- |
| S$200 | 1,612 hours priced. | 0 hours a stablecoin was cheapest |
| S$1,000 | 1,612 hours priced. | 1 hours a stablecoin was cheapest |
| S$5,000 | 1,612 hours priced. | 3 hours a stablecoin was cheapest |
| S$25,000 | 1,612 hours priced. | 3 hours a stablecoin was cheapest |
| S$50,000 | 1,612 hours priced. | 1 hours a stablecoin was cheapest |

## How we worked it out

Every hour we price the stablecoin way and each app for this route. A stablecoin counts as cheapest when its cost is below every app's cost in that hour. The count is the same one the home page and the routes page print.

The code that works it out, open for anyone to read:

tools/emit_routes.py

tools/audit_claims.py

tools/emit_findings.py

## What this doesn't tell you

It covers one route and only the hours we priced. It does not say a stablecoin can never win: on other routes it was the cheapest in some hours, and this route may change.

## Download the data

One line per hour or per price change.

findings_hours_sgd_php_never_cheapest.csv

1,612 rows

<https://margin.wiki/data/findings_hours_sgd_php_never_cheapest.csv>

## More findings

|  |  |  |
| --- | --- | --- |
| 01 | Transfer apps keep changing their prices | 1,564 price changes since 12 Aug |
| 02 | Some apps charge more on Saturday, then cut back | 51 Saturday rises that came back |
| 03 | From Singapore to the Philippines, a stablecoin only beats the apps if you send over S$13.5M a month | S$13.5M a month traded on the exchange |
| 05 | In 2 countries, people pay more for a dollar from each other than on an exchange | 2 countries where they disagree |
