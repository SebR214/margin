# In 2 countries, people pay more for a dollar from each other than on an exchange

Prices from the 00:00 UTC hour, 27 Oct.

In Turkey, buying a dollar from other people cost 5.1 points more than on an exchange in 100% of the hours we checked.

2 · countries where, over the last 30 days, buying from other people cost 2 points or more above an exchange in at least three of every four hours

First published 9 Oct 2026. The number updates every hour.

<https://margin.wiki/data/findings.json>

## How far above the exchange people paid, day by day

Each line is one country's median gap for the day, in points. The dashed line is 2 points.

## These rows back the number

Each row is one country: the median gap in points, the share of hours with a gap of 2 points or more, the hours checked, and whether the gap persists.

|  |  |  |
| --- | --- | --- |
| Turkey | 100% of hours 2 points or more above, 1,066 hours checked, since 10 Sep, BTCTurk, Paribu against Binance and OKX. The gap persists. | +5.1 points, median gap |
| India | 100% of hours 2 points or more above, 921 hours checked, since 10 Sep, WazirX, CoinDCX against Binance and OKX. The gap persists. | +4.0 points, median gap |
| Nigeria | 8% of hours 2 points or more above, 412 hours checked, since 9 Oct, Luno against OKX. The gap does not persist. | +0.9 points, median gap |
| Mexico | 2% of hours 2 points or more above, 1,066 hours checked, since 10 Sep, Bitso against Binance and OKX. The gap does not persist. | +0.6 points, median gap |
| Philippines | 0% of hours 2 points or more above, 1,066 hours checked, since 10 Sep, Coins.ph against Binance and OKX. The gap does not persist. | +0.2 points, median gap |
| Indonesia | 0% of hours 2 points or more above, 1,066 hours checked, since 10 Sep, Indodax, Pintu against Binance and OKX. The gap does not persist. | +0.1 points, median gap |
| Argentina | 0% of hours 2 points or more above, 1,066 hours checked, since 10 Sep, CriptoYa:astropay, CriptoYa:belo, CriptoYa:binance, CriptoYa:bitsoalpha, CriptoYa:bybit, CriptoYa:cocoscrypto, CriptoYa:cryptomktpro, CriptoYa:decrypto, CriptoYa:eluter, CriptoYa:fiwind, CriptoYa:lemoncash, CriptoYa:letsbit, CriptoYa:mexc, CriptoYa:nexo, CriptoYa:peanut, CriptoYa:ripio, CriptoYa:ripioexchange, CriptoYa:saldo, CriptoYa:satoshitango, CriptoYa:takenos, CriptoYa:tiendacrypto, CriptoYa:universalcoins, CriptoYa:vitawallet, CriptoYa:wallbit against Binance and OKX. The gap does not persist. | −0.8 points, median gap |
| Venezuela | 2% of hours 2 points or more above, 1,066 hours checked, since 10 Sep, CriptoYa:saldo against Binance and OKX. The gap does not persist. | −2.0 points, median gap |

## This is how we built it

We take every hour in which a country's published price came from order books or brokers and at least one board of offers between people had ten or more buy ads. The gap is that board's price over the official rate, minus the price we published that hour. When two boards answered we use the middle of the two. A gap persists when, over the last 30 days, there are at least seven days of checked hours and the gap is 2 points or more in at least three quarters of them.

The code that works it out, open for anyone to read:

tools/emit_findings.py

tools/emit_index_hourly.py

tools/emit_countries.py

## Read the number with these limits

Offers between people are prices asked, not trades done. Buying on an exchange needs an account there. Binance's board was first checked on 2 Sep and OKX's on 3 Oct.

## Check every row yourself

The file lists every row behind the number, one line per hour or per price change. The table above summarises them.

findings_hours_exchange_vs_p2p.csv

7,729 rows

<https://margin.wiki/data/findings_hours_exchange_vs_p2p.csv>

## We also found these

|  |  |  |
| --- | --- | --- |
| 01 | Transfer apps keep changing their prices | 1,503 price changes since 12 Aug |
| 02 | Some apps charge more on Saturday, then cut back | 51 Saturday rises that came back |
| 03 | Stablecoins beat the cheapest app only above about S$13.5M a month, a figure worked out from the exchanges' published fee tiers | S$13.5M a month traded on the exchange |
| 04 | Singapore to the Philippines: a stablecoin was almost never the cheapest way to send | 3 of 1,589 hours a stablecoin was cheapest |
