# In 2 countries, people pay more for a dollar from each other than on an exchange

Prices from the 12:00 UTC hour, 28 Oct.

In Turkey, buying a dollar from other people cost 5.2% more than on an exchange in 100% of the hours we checked.

2 · countries where buying from other people cost 2% or more above an exchange in at least 3 of every 4 hours, over the last 30 days

First published 9 Oct 2026. The number updates every hour.

<https://margin.wiki/data/findings.json>

## How far above the exchange people paid, day by day

Each line is one country's typical gap for the day. The dashed line is 2%.

## The numbers behind it

Each row is one country: the typical gap, the share of hours with a gap of 2% or more, the hours checked, and whether the gap is still there.

|  |  |  |
| --- | --- | --- |
| Turkey | 100% of hours 2% or more above, 1,095 hours checked, since 10 Sep, BTCTurk, Paribu against Binance and OKX. Still there. | +5.2% typical gap |
| India | 100% of hours 2% or more above, 939 hours checked, since 10 Sep, WazirX, CoinDCX against Binance and OKX. Still there. | +4.0% typical gap |
| Nigeria | 9% of hours 2% or more above, 441 hours checked, since 9 Oct, Luno against OKX. Gone. | +0.9% typical gap |
| Mexico | 2% of hours 2% or more above, 1,095 hours checked, since 10 Sep, Bitso against Binance and OKX. Gone. | +0.6% typical gap |
| Philippines | 0% of hours 2% or more above, 1,095 hours checked, since 10 Sep, Coins.ph against Binance and OKX. Gone. | +0.2% typical gap |
| Indonesia | 0% of hours 2% or more above, 1,095 hours checked, since 10 Sep, Indodax, Pintu against Binance and OKX. Gone. | +0.1% typical gap |
| Argentina | 0% of hours 2% or more above, 1,095 hours checked, since 10 Sep, 24 brokers through CriptoYa against Binance and OKX. Gone. | −0.8% typical gap |
| Venezuela | 2% of hours 2% or more above, 1,095 hours checked, since 10 Sep, CriptoYa:saldo against Binance and OKX. Gone. | −2.0% typical gap |

## How we worked it out

We take every hour in which a country's published price came from exchanges or brokers, and at least one board where people sell to each other had ten or more buy ads. The gap is that board's price over the official rate, minus the price we published that hour. When two boards answered we use the middle of the two. A gap is still there when, over the last 30 days, there are at least seven days of checked hours and the gap is 2% or more in at least three quarters of them.

The code that works it out, open for anyone to read:

tools/emit_findings.py

tools/emit_index_hourly.py

tools/emit_countries.py

## What this doesn't tell you

Offers from people selling to each other are prices asked, not trades done. Buying on an exchange needs an account there. Binance's board was first checked on 2 Sep and OKX's on 3 Oct.

## Download the data

One line per hour or per price change.

findings_hours_exchange_vs_p2p.csv

7,950 rows

<https://margin.wiki/data/findings_hours_exchange_vs_p2p.csv>

## More findings

|  |  |  |
| --- | --- | --- |
| 01 | Transfer apps keep changing their prices | 1,564 price changes since 12 Aug |
| 02 | Some apps charge more on Saturday, then cut back | 51 Saturday rises that came back |
| 03 | From Singapore to the Philippines, a stablecoin only beats the apps if you send over S$13.5M a month | S$13.5M a month traded on the exchange |
| 04 | Singapore to the Philippines: a stablecoin was almost never the cheapest way to send | 3 of 1,618 hours a stablecoin was cheapest |
