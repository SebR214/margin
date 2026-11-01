# From Singapore to the Philippines, a stablecoin only beats the apps if you send over S$20.4M a month

Prices from the 17:00 UTC hour, 1 Nov.

Sending S$5,000 to the Philippines, a stablecoin would only beat the cheapest app if you sent more than this every month, because exchanges cut their fees for big traders. Nobody in our data traded that much, so this is worked out from the fees the exchanges publish, not seen happening. A stablecoin is a coin that stays worth one US dollar.

S$20,367,600 · Singapore dollars sent per month in total. Above it, stablecoins cost less for a transfer of five thousand to the Philippines.

First published 5 Oct 2026. The number updates every hour.

<https://margin.wiki/data/findings.json>

## The stablecoin gets cheaper as monthly volume grows

What sending S$5,000 costs at each fee level the exchange publishes. The dashed line is what the cheapest app usually costs.

## The numbers behind it

Both rows are the same transfer, priced for two ways of buying on the exchange. Costs are for sending S$5,000.

Buying at the asking price

At the highest fee the stablecoin costs S$43.80. At the lowest, S$18.39. The cheapest app usually costs S$22.34. From 1,687 price checks.

S$20,367,600 Singapore dollars a month

Setting your price and waiting

At the highest fee the stablecoin costs S$41.81. At the lowest, S$17.39. The cheapest app usually costs S$22.34. From 1,687 price checks.

S$8,986,700 Singapore dollars a month

## How we worked it out

We take every real check of sending five thousand Singapore dollars to the Philippines by stablecoin. For a given monthly volume, we look up the lower fee each exchange would charge. We rebuild each check's cost with those fees, from its own recorded prices. The number is the lowest volume where its usual cost drops below the cheapest app's usual cost. Both come from the same hours.

The code that works it out, open for anyone to read:

tools/emit_volume_crossover.py

tools/emit_crossover_receipts.py

tools/emit_findings.py

## What this doesn't tell you

It covers one route and one amount. The number is rebuilt from real prices, never seen happening. Nobody in our data traded at that volume. It does not mean stablecoins are cheaper for most senders. Below that volume, the cheapest app costs less for this transfer.

## Download the data

One line per hour or per price change.

findings_hours_volume_crossover.csv

1,688 rows

<https://margin.wiki/data/findings_hours_volume_crossover.csv>

## More findings

|  |  |  |
| --- | --- | --- |
| 01 | Transfer apps keep changing their prices | 1,722 price changes since 12 Aug |
| 02 | Some apps charge more on Saturday, then cut back | 51 Saturday rises that came back |
| 04 | Singapore to the Philippines: a stablecoin was almost never the cheapest way to send | 3 of 1,651 hours a stablecoin was cheapest |
| 05 | In 2 countries, people pay more for a dollar from each other than on an exchange | 2 countries where they disagree |
