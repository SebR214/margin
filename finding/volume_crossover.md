# Stablecoins beat the cheapest app only above about S$13.5M a month, a figure worked out from the exchanges' published fee tiers

Prices from the 15:00 UTC hour, 25 Oct.

Sending five thousand Singapore dollars to the Philippines, a stablecoin would beat the cheapest app only above this monthly volume. Nobody in our data traded that much, and we never saw it happen: the figure is rebuilt from the exchanges' fee tiers. A stablecoin is a coin that stays worth one US dollar.

S$13,471,500 · Singapore dollars sent per month in total. Above it, stablecoins cost less for a transfer of five thousand to the Philippines.

First published 5 Oct 2026. The number updates every hour.

<https://margin.wiki/data/findings.json>

## The stablecoin gets cheaper as monthly volume grows

What sending S$5,000 costs at each fee tier the exchange publishes. The dashed line is what the cheapest app usually costs.

## These rows back the number

Both rows are the same transfer, priced for two ways of buying on the exchange. Costs are for sending S$5,000.

Buying it now

S$43.88 stablecoin cost, highest fee, S$18.47 stablecoin cost, lowest fee, 0.07 percent fee at that volume, S$22.57 cheapest app's usual cost, 1,600 real price checks behind it.

S$13,471,500 Singapore dollars a month

Waiting for your price

S$41.90 stablecoin cost, highest fee, S$17.47 stablecoin cost, lowest fee, 0.1 percent fee at that volume, S$22.57 cheapest app's usual cost, 1,600 real price checks behind it.

S$4,490,500 Singapore dollars a month

## This is how we built it

We take every real check of sending five thousand Singapore dollars to the Philippines by stablecoin. For a given monthly volume, we look up the lower fee each exchange would charge. We rebuild each check's cost with those fees, from its own recorded prices. The number is the lowest volume where its usual cost drops below the cheapest app's usual cost. Both come from the same hours.

The code that works it out, open for anyone to read:

tools/emit_volume_crossover.py

tools/emit_crossover_receipts.py

tools/emit_findings.py

## Read the number with these limits

It covers one route and one amount. The number is rebuilt from real prices, never seen happening. Nobody in our data traded at that volume. It does not mean stablecoins are cheaper for most senders. Below that volume, the cheapest app costs less for this transfer.

## Check every row yourself

The file lists every row behind the number, one line per hour or per price change. The table above summarises them.

findings_hours_volume_crossover.csv

1,601 rows

<https://margin.wiki/data/findings_hours_volume_crossover.csv>

## We also found these

|  |  |  |
| --- | --- | --- |
| 01 | Transfer apps keep changing their prices | 1,481 price changes since 12 Aug |
| 02 | Some apps charge more on Saturday, then cut back | 42 Saturday rises that came back |
| 04 | Singapore to the Philippines: a stablecoin was almost never the cheapest way to send | 3 of 1,564 hours a stablecoin was cheapest |
| 05 | In 2 countries, people pay more for a dollar from each other than on an exchange | 2 countries where they disagree |
