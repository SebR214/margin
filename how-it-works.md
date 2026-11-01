# How to read this site

Prices from the 22:00 UTC hour, 1 Nov.

## What we measure

Every country has an official exchange rate. In some countries banks won’t sell dollars at that rate, or sell very few, so people buy them from each other and pay more. Every hour we check what people really pay for a dollar in 55 countries and compare it with the official rate.

## What the percentage means

In Algeria, the official rate says a dollar costs 135 DZD. People actually pay 258 DZD. That’s 90.7% more, so Algeria shows +90.7%.

0% means people pay the official rate, and most countries are close to it. A minus means they pay a little less.

<https://margin.wiki/data/index_latest.json>

## Where the price comes from

We get it from local exchanges first, then brokers, then people selling to each other on Binance and OKX. What they sell is mostly stablecoins, digital coins that are always worth one US dollar, so their price is the price of a dollar. If there aren’t enough prices in an hour, that country shows no price. We never guess.

## The cost of sending money

On 11 routes we also check what it costs to send money abroad.

We compare transfer apps with sending it by stablecoin. The cost is how much less the person receiving gets than at the official rate, with every fee we can see included. This hour, sending S$5,000 to the Philippines costs S$18.59 with Wise, the cheapest app. Where a fee can't be seen, the route says so.

<https://margin.wiki/data/routes_hourly.json>

## What our numbers leave out

- A day behind. The official rate updates only once a day. On days a currency moves fast, the gap we show can be a day behind.
- Bank and wallet charges. Money moves into an exchange and out again through a bank, a wallet or the exchange's local partner. Each has its own charge. Some show it as a fee, some bake it into the rate, some set it in a deal with the exchange. We can't see these, so they are left out.
- First-transfer offers. Some app prices are offers for a first transfer. Repeat customers pay more.
- Cash comes from trackers. Cash dollar prices come from public websites that track money changers, not from offers we read ourselves. Where we have one, the country page shows it beside the stablecoin price.

## How to check any number

Each price on a country page links to the file it came from.

A missed hour shows as a blank, never filled in.

Every source, and every day it answered: [Sources →](https://margin.wiki/sources.md)

<https://margin.wiki/data/sources_daily.json>

## How the site is built and run

Plain code collects every price and checks every number. AI only helps write some of the code.

What it costs, what runs when, and everything that has broken: [How it was built →](https://margin.wiki/how-it-was-built.md)
