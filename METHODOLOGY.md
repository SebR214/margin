# Methodology

Every number on this site is one of three things: **measured**, **assumed**, or
**not visible**. This page says which is which. If you find something here that
contradicts the charts, the charts are wrong and I want to know.

## What is being measured

For each corridor, hourly, at a set of notional sizes:

| | Source | Type |
|---|---|---|
| On-ramp book (SGD→USDT) | Independent Reserve public order book | measured |
| Off-ramp book (USDT→PHP) | Coins.ph Pro public depth, 200 levels requested | measured |
| USD mid rates | `open.er-api.com` | measured |
| Incumbent fiat baseline | Wise comparison API (Wise, Instarem, HSBC, OFX, PayPal…) | measured |
| Incumbent panel (every provider) | Wise comparison API → `data/providers.csv` | measured |
| Exchange taker & maker fees | venue published schedules | published, verified 2026-08-10 |
| Network withdrawal fee, SGD→PHP | Independent Reserve, Tron, 4.0 USDT flat | published, read 2026-08-19 |
| Network withdrawal fee, USD→MXN | Coinbase, Polygon, 0.01% of amount (max 20 USDT) | published, read 2026-08-19 |
| Network gas, USD→MXN | not published by Coinbase — see below | **not modelled** |

### The network leg is per corridor, not a constant

It was recorded as "1 USDT, TRC20, flat" for both corridors. That was wrong
twice over. **Coinbase does not support USDT on Tron at all** — its USDT exit
networks are Ethereum, Solana, Base, Polygon, Arbitrum and Avalanche — so the
USD→MXN corridor was being priced on a chain it cannot use, and at a flat fee
that no venue in it charges.

The two corridors now carry what their **sending** venue actually publishes:

- **SGD→PHP** sends from Independent Reserve, whose crypto withdrawal table
  reads `Tether USD | TRON | 4.0 USDT`. Flat, so it dominates small transfers:
  191 bps of the cost at S$200, 7.6 bps at S$5,000.
- **USD→MXN** sends from Coinbase over **Polygon** — the cheapest chain both
  Coinbase and Bitso support, and Bitso accepts Polygon USDT deposits free.
  Coinbase charges "a processing fee equal to 0.01% of the amount transferred,
  with a maximum of 20 USDT". Being proportional, it is 1 bp at *every* size,
  which is why this corridor's cost barely moves along the ladder while
  SGD→PHP's triples at the small end.

**What is not modelled:** Coinbase states "a separate network transaction fee
will also apply" — gas, estimated at send time and never published as a
schedule. On Polygon it is fractions of a cent, so it is left at zero rather
than invented. This is the one term on the site that understates rather than
overstates, and it is stated here rather than buried.

Both books are *walked* for the actual notional, so a size that would move the
price shows up as slippage rather than being priced at top-of-book. Where a book
cannot absorb the size, the row records `filled=false` rather than silently
truncating.

## The two execution regimes

The all-in cost of the stablecoin route is not one number. It depends on how you
execute, and the two answers sit on opposite sides of the incumbent:

- **Taker** — crosses the spread, pays published taker fees on both legs. This is
  what a retail user does when they press "buy".
- **Maker** — posts a resting order and waits, and pays published **maker** fees:
  Coins.ph Pro VIP0 maker is 0.10%, and Independent Reserve has **no maker
  discount at all** — a posted order there still pays the flat 0.50%. Maker is
  *not* free execution.

The maker figure is an **upper bound on the benefit**: it assumes a fill at
posted top-of-book and ignores fill risk, queue position, and the time the money
spends unhedged. But it is no longer optimistic on fees — the maker schedule is
applied on both legs. Because Independent Reserve is flat, the only thing that
separates the two regimes at the base tier is the Coins.ph taker/maker spread
(0.15% vs 0.10%): maker sits ~5 bps below taker and no further.

**At base-tier fees the stablecoin route loses to the fiat baseline in _both_
regimes**, across the whole size ladder — taker ~78–139 bps and maker ~73–134 bps
against Wise/Instarem at ~59–89 bps (live, 2026-08-10). The route only turns
favourable once volume-tier fees kick in (both venues discount on 30-day
volume); that crossover is a finding to be *measured* from history, not assumed.
The earlier "maker beats Wise ~3×" result was an artefact of modelling maker
trading as free — it does not survive fee verification.

## The decomposition

The headline claim of this site is that the cost sits at the doors, not on the
rail. That is arithmetic, and it reconciles:

```
on-ramp basis    stable vs USD mid at the source venue   (can be negative — a gain)
on-ramp fee      published fee (taker or maker per regime)
network fee      flat, so it scales inversely with size
off-ramp basis   stable vs USD mid at the destination venue
off-ramp fee     published fee (taker or maker per regime)
─────────────────────────────────────────────────────────
= all-in cost in bps below mid-market
```

The taker and maker rows use the taker and maker schedules respectively; the
network fee and both basis terms are identical between them. So the taker/maker
gap is exactly the difference between the two fee schedules — nothing more.

"Basis" is peg deviation expressed as a cost. It is a **market price, not a
fee** — it moves hourly, and its sign depends on which way money wants to flow
through that venue. This is the term nobody publishes and the reason this site
collects rather than calculates on demand.

## Basis and its sign

There is one canonical sign convention across this site:

**Positive basis = USDT is _rich_ to the dollar** — one USDT buys more local
currency than one dollar does at the official mid. That is capital paying a
premium to hold dollars offshore (Argentina, Venezuela; historically Turkey).
Negative = USDT trades _cheap_ to the official mid.

```
basis_bps = (usdt_mid_local / fx_mid_local_per_usd − 1) × 10 000
```

The **basis layer** (`data/basis.csv`, which colours the map) reports exactly
this signed number — one row per venue per hour, across Singapore, Philippines,
Turkey, Korea, Indonesia, Thailand and Mexico.

The **decomposition layer** (`data/samples.csv`, the corridor page) expresses
the *same* peg deviation as a **cost on each leg**, because it feeds a cost
waterfall that must sum to the all-in figure — and a cost has the opposite sign
to richness on the leg where you *sell*:

- **on-ramp** (you buy USDT with SGD): cost = **+**richness at the source venue
  — rich USDT is expensive to buy.
- **off-ramp** (you sell USDT for PHP): cost = **−**richness at the destination
  — cheap USDT is bad to sell.

So the two files never disagree; they are the same measurement in two
representations. Worked example, Philippines, 2026-08-10: the basis layer
records Coins.ph at ≈ **−18 bps** (USDT cheap to the dollar in Manila), and the
corridor's off-ramp basis records ≈ **+18 bps of cost** (selling that cheap
USDT costs you ~18 bps). Equal magnitude, sign flipped by the buy/sell
direction, by design.

**Caveat — which "official" rate.** `open.er-api.com` tracks the floating
*market* USD rate, not a central-bank official or pegged rate. For freely
floating currencies (TRY, THB, MXN) the market already equals the FX mid, so
their basis reads small — a near-zero Turkey number means "er-api already
prices the float", not a broken feed. The large premia appear only where an
official peg diverges from the street price, which needs a pegged reference
(ARS, VES — see the parallel-dollar markets below). Stated here so the map is
read correctly.

**Reading the map: it is a divergence detector, not a thermometer.** A flat,
near-zero basis is not "nothing happening" — it is the signal that the local FX
market is open and USDT clears at the dollar mid. Colour appears only where USDT
*diverges* from the official mid: a capital control, an import backlog, a weekend
when banks are shut but crypto is not. The interesting states are the coloured
ones, and a calm Singapore or Thailand is the control group that makes a hot
Argentina legible. The map's legend is built around zero and diverges in both
directions for exactly this reason.

### A worked reading: Indodax −119 bps (2026-08-10)

On the first live pull Indodax showed USDT/IDR ≈ 119 bps below the er-api USD
mid — large enough to check before trusting. The book was fresh (venue timestamp
2 s old) with a 0.6 bps bid/ask spread, so it is neither a stale quote nor a
spread artifact. Against three independent references — fawazahmed0 and Wise both
put USD/IDR ≈ 17,800, and CoinGecko's aggregate USDT/IDR ≈ 17,775 — the number
decomposes: ≈ 30 bps is er-api's IDR sitting above consensus spot (an
FX-reference wrinkle, the same family as the TRY note above), and the remaining
≈ 85 bps is a *genuine* Indodax USDT discount, corroborated by the independent
aggregate also trading below spot. Verdict: **real discount, not an artifact.**
It stays in the data unadjusted; this note is the audit trail.

### The parallel-dollar markets (CriptoYa, snapshot-only)

Argentina and Venezuela are the reason the map exists, and they are measured
differently. There is no single clean exchange book for USDT/ARS or USDT/VES, so
these come from the [CriptoYa](https://criptoya.com) aggregator (attributed on
the site) via its general endpoint.

**Aggregation rule: the median _bid_ across every exchange CriptoYa lists** (raw
`bid`, not the fee-inclusive `totalBid`). Not the bid/ask midpoint — and this
correction matters. CriptoYa aggregates brokers and fintechs, not order books,
and their **ask carries ~100 bps of retail markup** (listed spreads run 70–150
bps, versus a few bps on a real book). A naive midpoint inherits half that
markup. The check that settled it: for Mexico we have both feeds — our Bitso
*order book* read −9 bps, and CriptoYa-MXN's median **bid** read −12 bps (a match)
while its **midpoint** read a spurious **+23**. So the bid is the clean side; the
ask is contaminated. Switching midpoint → median-bid moved the live readings:

| Pair | midpoint (before) | median-bid (after) |
|---|---|---|
| ARS | +532 bps | **+454 bps** |
| VES | +1,363 bps | **+1,311 bps** |
| BRL | +99 bps | **+55 bps** |

Here the FX comparator does the *opposite* job from the floating-currency caveat
above. For ARS and VES, `open.er-api.com` quotes the **official** rate, and that
is exactly what we want: the basis becomes the **parallel-dollar premium**, the
gap between the street price of a dollar and the government's — ARS ≈ **+450 bps**
and VES ≈ **+1,300 bps**, capital paying 4.5% and 13% over the official mid to
hold dollars as USDT. Brazil (BRL, a floating currency) keeps a **~+55 bps**
premium even after the correction: not the near-zero of Mexico/Thailand, but a
real, modest one consistent with Brazil's FX frictions (IOF tax, capital-account
controls) — smaller than the +99 the midpoint claimed, and not an artifact. The
median-bid number is a mild *under*statement of the true premium (the fair mid
sits a little above the bid), which is the safe direction to err.

These venues are **snapshot-only**: CriptoYa exposes no candle history, so they
are absent from `data/basis_history.csv` and carry `source = criptoya` in
`data/basis.csv`. This is how the map tells history-backed from snapshot-only
venues — a venue has a trailing history line iff it appears in basis_history.csv;
ARS/VES/BRL render as a live point with no series, and the legend says so.

## The index, version 1

**Status: DRAFT. Nothing on the site publishes an index number until this is
approved.** This section defines what "the margin index for Nigeria is +12% this
week" would mean, precisely enough to be attacked.

### What the number is

One figure per country per hour, and one published weekly: **how much more, or
less, a dollar costs in that country than its official exchange rate.**

```
index = (local price of one USDT / official USD rate - 1) * 100
```

Positive means people there pay above the official rate to obtain dollars.
Negative means below. The weekly figure is the median of that country's hourly
figures across the published week, so one dislocated hour cannot carry a week.

### Composition — one number, and where it came from

Per country, per hour, in strict precedence. **The classes are never blended.**

| Rank | Class | Rule |
|---|---|---|
| 1 | `order_book_median` | Two or more exchange order books quote USDT against that currency in the same hour → median across them |
| 2 | `order_book_single` | Exactly one order book → that book |
| 3 | `p2p_median` | No order book → median of the two-sided advertisement board |

**Every published row prints its class.** A reader must never have to guess
whether a number came from a matching engine or an advertisement, and a country
that moves between classes — because a venue was added, or a board went quiet —
changes class visibly rather than silently.

Why precedence rather than a weighted blend: an order-book mid is a price at
which a trade can occur; a P2P advertisement is a price someone is *asking*,
carrying counterparty risk, a payment-rail requirement and a settlement window.
Averaging the two produces a number that is neither, and no reader could say
what it measures.

#### Open question 1 — brokers are not order books

The rule above says "order books". Some of what the collector treats as a venue
is not one. CriptoYa reports **brokers and fintechs**, which quote a spread to a
retail customer rather than running a book. Under the rule as written, today:

- **Argentina** is classed `order_book_median` on **24 sources, every one of
  them a CriptoYa-reported broker.** Its 3.32% between-exchange spread is partly
  retail markup, which the board already footnotes.
- **Venezuela** is classed `order_book_single` on **one broker**.

Neither country has a single real order book behind it. Two ways to resolve,
and this needs your decision:

1. **Four classes.** Insert `broker_median` and `broker_single` between the
   order-book classes and P2P. Argentina becomes `broker_median`, Venezuela
   `broker_single`. Most honest, and it changes how two countries are labelled
   but not their numbers.
2. **Leave as written.** Simpler, and defensible only if the published note
   makes clear that "order book" here means "a venue quoting a two-sided price",
   which is a weaker claim than it sounds.

I recommend (1). It costs a column value and removes a claim we cannot support.

### The denominator, and where it is a policy number

Every figure is measured against the **`open.er-api.com` USD mid captured in the
same row** as the price. Never a rate looked up later, never a rate from a
different hour.

That reference is not the same kind of object in every country. Three classes,
printed alongside the index:

| Class | Meaning | Examples |
|---|---|---|
| `market` | The reference is itself a market price. The index measures a genuine local premium or discount. | SGD, PHP, THB, MXN, BRL, KRW, IDR, ZAR, PEN, CLP, COP, KES, TZS, UGX |
| `managed` | The reference is a number a central bank sets or defends, which the market trades away from. **The index measures distance from a policy rate, not a market spread.** | ARS, VES, LBP, SDG, DZD, SYP, IQD, AFN, MZN, ETB, NGN, AOA, UAH |
| `pegged` | The reference is a hard peg. The index reads near zero by construction, and that *is* the finding. | AED, SAR, QAR, KWD, JOD, BND, XAF, XOF |

**For `managed` currencies the headline sentence must carry the qualifier.** Not
"a dollar costs 129× more in Sudan" but "the P2P board prices a dollar 129×
above Sudan's official rate, which is a policy number". The first is nonsense;
the second is the story.

The wide P2P pull of 2026-09-05 makes the point better than argument:

```
SDG   board 7,116   official   510   -> +12,946 bps
DZD   board   246   official   133   ->  +8,422 bps
IQD   board 1,544   official 1,311   ->  +1,779 bps
```

**Rule: publish the official rate, label its class, never quietly substitute a
parallel rate.** If a parallel or street reference is ever adopted for a
country, that is a version bump and **both** references are published side by
side from that point, so no series silently changes meaning.

**Known error term.** `open.er-api.com` publishes a *daily* rate. For `managed`
currencies at hundreds or thousands of bps that is immaterial. For `market`
currencies sitting within 0.25% of the official rate — Singapore, Thailand, the
Philippines, Mexico — a stale daily denominator is a material fraction of the
number. Intraday FX is an open item (ROADMAP P2-3) and until it lands, **the
index for tight `market` currencies should be read as accurate to roughly a
tenth of a percent, not better.**

### History start, per country, honestly

There is no way to make this look better than it is, so it is published as a
column and stated on every country page.

| Coverage | Countries | From |
|---|---|---|
| Daily backfill, then hourly | IDR, KRW, MXN, THB, TRY | 2024-03-02 to 2024-08-10, depending on the currency |
| Hourly order book | ARS, BRL, PHP, SGD, VES | 2026-08-10 / 2026-08-11 |
| Hourly P2P | BDT, BOB, EGP, ETB, GHS, KES, LBP, NGN, PKR, VND | 2026-09-02 |
| Hourly P2P | the 43 currencies added in the wide expansion | 2026-09-05 |

**Five countries have history before 2026. The rest begin when collection
began.** For the P2P layer this is not a gap that can be closed later: Binance
publishes no historical endpoint for its advertisement board, so those series
can only ever start on the day collection started. An index claiming otherwise
would be inventing its own past.

### What a version bump means

Every published file carries `index_version`. It is incremented when **any
change alters what a published number means**, specifically:

- the composition rule or the precedence between classes
- the denominator policy for any country, including adopting a parallel reference
- the amount filter that defines a representative P2P ticket (currently USD 500)
- the venue set behind a country, where it changes the number rather than
  merely widening the sample

A bump is published with its reason, its date, and the list of countries whose
numbers change. Cosmetic or presentational changes never bump the version.

**And the reason a bump is survivable at all:** `data/basis.csv`,
`data/p2p_basis.csv` and `data/basis_history.csv` are **append-only records of
what was observed, not of what was published.** Every index figure at every
version is recomputable from those rows. A definition change therefore
**re-derives** the history under the new rule rather than invalidating it, and
both versions can be published side by side for as long as it takes a reader to
trust the change.

That is also why collection went wide to 53 currencies before this definition
was settled: a raw row not captured in a given hour is gone permanently, while a
definition can be changed and applied backwards at any time.

### Open question 2 — thin and broken boards

Not in the brief for this section, but it blocks publication and belongs here
rather than in a later surprise. The wide pull surfaced boards that are not
markets:

```
AOA   buy   826.58   sell 1,113.54    sell 35% ABOVE buy, 15 ads
UAH   buy    45.31   sell    47.98    sell above buy
NPR   buy   164.79   sell   150.15    ~10% spread, 12 ads
BWP   0 buy ads against 10 sell       already fails: a mid needs both sides
BND   pegged 1:1 to SGD, reads +639 bps on 18 ads
```

A sell median above a buy median is not a spread, it is a broken board. No rule
is proposed here because it is your call, but the index cannot publish these as
they stand. The candidates are a minimum ad count per side, a rejection when
`sell_median > buy_median`, and a maximum plausible spread — each of which is a
filter, and every filter needs stating in this section before it is applied.

## More than one exchange per country

Until 2026-09-02 every country on the board had exactly one exchange behind it,
and that exchange's quote *was* the country's number. That is not defensible:
a thin book, a stale feed or one venue's inventory position becomes a national
statistic. From 2026-09-02 the headline for a country is the **median across
every exchange that reported in the same UTC hour**, and the disagreement
between those exchanges is published alongside it.

**Same hour, or not at all.** Venues are grouped by the UTC hour they were
captured in. Comparing a Seoul print from 14:00 with a São Paulo print from
09:00 would measure the clock, not the market. Only the newest hour that has any
successful row counts; older hours are discarded rather than merged in to pad
the venue count.

**Median, not mean.** One stale or dislocated quote should move the headline as
little as possible. On 2026-09-02 the Argentine feed carried twenty-four
exchanges between −22 and +530 bps; a mean would have been dragged by both ends,
the median was +392.

**Spread is the disagreement, not a bid/ask.** `basis_spread_bps` is the widest
minus the narrowest basis across the exchanges in that hour. A wide spread is a
real finding — a fragmented or thin market — and is shown rather than smoothed.

**A median needs two.** Where only one exchange reports, no median and no spread
are computed and the site says "one exchange only" with the venue named. That is
still true of Singapore, the Philippines, Thailand and Mexico. The number is not
dressed up as a consensus it does not have.

**Aggregates are listed, never counted.** A `CriptoYa (XXX)` row is itself a
median across exchanges. It is still collected and still shown — for Venezuela
and Brazil it is the longest-running number there is — but it is never one of
the exchanges in a cross-venue median, which would place a median beside its own
inputs. For Argentina and Venezuela the individual exchanges CriptoYa lists are
now collected as their own rows (`CriptoYa:<exchange>`), which is what lets those
countries have a median at all.

**P2P books are excluded.** CriptoYa lists P2P venues alongside spot ones. A P2P
advertisement is a different instrument — no matching engine, counterparty risk,
a price that is asked rather than traded — and blending it into a spot median
silently would be exactly the sort of quiet mixing this document exists to
prevent. Any venue whose name contains `p2p` is dropped at collection. P2P is
its own layer, not yet built.

### Exchanges live as of 2026-09-02

| Currency | Exchanges | Median? |
|---|---|---|
| KRW | Upbit, Bithumb, Coinone | yes, 3 |
| BRL | Foxbit, Mercado Bitcoin (+ CriptoYa aggregate) | yes, 2 |
| TRY | BTCTurk, Paribu | yes, 2 |
| IDR | Indodax, Pintu | yes, 2 |
| ARS | 24 exchanges via CriptoYa, P2P excluded | yes |
| VES | 1 non-P2P exchange via CriptoYa | no — one only |
| SGD | Independent Reserve | no — one only |
| PHP | Coins.ph | no — one only |
| THB | Bitkub | no — one only |
| MXN | Bitso | no — one only |

Every endpoint above was called from a US GitHub runner — the environment the
collector actually runs in, not a laptop — on 2026-09-02 and returned a real
USDT quote before it was added. Candidates that were called and rejected are
listed in `collector_basis.py` with their status codes: PDAX (403 on every
path), Coinhako (403), Orbix (no public endpoint), Binance TH (reachable, but
`-1121 Invalid symbol` — it has no USDT/THB book), Binance TR and binance.com
(451), Tokocrypto (451, and no USDT_IDR pair), Reku (404). Nothing was added on
the strength of documentation alone.

Pintu publishes a last price and no order book, so its `usdt_bid` and
`usdt_ask` cells are empty rather than filled with the last price twice.

## Implied crosses (`data/crosses_latest.json`)

Every pair of the ten currencies, priced two ways. For a pair A/B:

```
implied_rate  (B per A) = usdt_mid_B / usdt_mid_A
official_rate (B per A) = fx_mid_per_usd_B / fx_mid_per_usd_A
gap_pct                 = (implied_rate / official_rate - 1) * 100
```

That is the round trip a person would actually take: sell A for USDT on an
A-quoted exchange, buy B with the USDT on a B-quoted one. The gap is how far
that route's rate sits from the official cross at the same moment.

**This is a market-price comparison, not a cost quote.** It contains no exchange
fee, no spread crossed, no withdrawal fee and no network fee. Nobody sending
money will receive `implied_rate`. Those costs are measured, with verified fee
schedules, in the corridor layer — and on the corridor the fees are large enough
to reverse the sign of a favourable-looking gap. What this file measures is
whether two markets' view of a cross has drifted from the official one, which is
the same question basis asks, asked between two countries instead of against the
dollar.

**Same hour, both legs.** A pair is emitted only where both currencies were
captured in the same UTC hour. A Manila print against a five-hour-old Istanbul
print would measure the clock. Where the hours differ the pair is simply absent
— never carried forward.

**One price per currency**: the median across the exchanges that reported that
hour, the same number the board shows, falling back to the aggregated feed where
no individual exchange reported.

Pairs are stored once, alphabetically (`SGD/THB`, not also `THB/SGD`). Reversing
a pair inverts both rates; the gap must be recomputed from the inverted rates,
because `1/(1+g) - 1` is not `-g`.

Regenerated every collector run, alongside `data/latest.json`, and containing no
wall clock for the same reason: identical inputs must produce an identical file.

## USDT versus USDC on the same venue (`data/stable_spread.csv`)

"Stablecoin" is treated everywhere on this site as if it meant one thing. Where
a venue already in the collector also lists **USDC** against the same local
currency, both are captured in the same hour and the difference recorded:

```
spread_bps = (usdc_mid / usdt_mid - 1) * 10_000
```

Positive means USDC trades dearer than USDT in that market.

**Same hour, same run, same quote.** The USDT side is not re-fetched — it is the
mid this run already wrote to `basis.csv`. The layer therefore runs exactly when
the basis layer runs, and is deduped by the same per-hour gate. So the two prices are the same
observation, not two observations minutes apart. A venue whose USDT pull failed
therefore gets no USDC price either: half a spread is not a spread, and the row
says so with `source_ok=False` rather than being skipped.

**Twelve of thirteen venues quote both**, verified from a US runner 2026-09-02:
Independent Reserve, Coins.ph, BTCTurk, Upbit, Indodax, Bitkub, Bithumb,
Coinone, Paribu, Pintu, Foxbit, Mercado Bitcoin. **Bitso is absent entirely** —
it has no `usdc_mxn` book and the API says so (`Unknown OrderBook`). Absent, not
a row of nulls, because a row of nulls would read as a market that failed rather
than one that does not exist.

Bitkub, Paribu, Pintu and Foxbit publish every pair in one payload, so the USDC
price costs no extra request. Those four are also where the easy bug lives: read
the wrong key and the spread comes back as exactly zero, which looks like a
finding. The selftest asserts a non-zero spread for each of them.

Own file, own frozen schema. `basis.csv` carries one price per row; a second
stablecoin would mean either a new column on a frozen schema or a second row
that reads as a second venue.

**Nothing is on the site yet, by design.** Seven days of rows first. A
single-figure basis-point difference between two stablecoins is inside the noise
of any one hour, and a week is the minimum needed to tell a spread from a print.

## Historical basis (the long-range history line)

`data/basis_history.csv` is a one-time backfill (`tools/backfill_basis.py`, not
part of the hourly collector) so the board shows years on day one. One row per
venue per day: `date, venue, ccy, usdt_close, fx_mid, basis_bps, source`, same
sign convention as live.

- **USDT close** is each venue's own daily candle: BTCTurk `v2/ohlc`, Upbit
  `candles/days`, Indodax `history_v2`, Bitkub `tradingview/history`, Bitso
  `v3/ohlc`. Candle depth varies — Indodax and Bitkub reach 2018, BTCTurk 2019
  — but Upbit only listed KRW-USDT in 2024-06 and Bitso's public OHLC window is
  shallow (from 2024-08).
- **FX mid** is [fawazahmed0/currency-api](https://github.com/fawazahmed0/exchange-api):
  free, keyless, dated daily files, with a mirror host for resilience. Its
  history begins **2024-03**, so coverage is the *shorter* of candle depth and
  FX depth — history effectively starts 2024-03 even where candles run to 2018.
  Its limits are the same family as er-api's: a community aggregate that tracks
  the floating market rate, not a central-bank official or pegged rate; daily
  granularity only. Of 892 days, 1 had no FX file and its rows were dropped, not
  guessed.

Result: **~4,200 rows across five venues, 2024-03-02 → present.** The history is
the argument against reading a single snapshot: BTCTurk, near zero today, ran to
**+650 bps** in this window, and Upbit to **+840** — the premium regimes the map
is built to catch, even when the current reading is flat.

**The history/live seam.** History is priced with fawazahmed0; the hourly live
layer is priced with er-api. The two FX feeds differ by tens of bps for some
currencies (e.g. IDR ≈ 18 bps on 2026-08-10, so the same day reads ~−101 bps in
history and ~−119 bps live). This is recorded, not smoothed: the `source` column
marks every historical row's provenance, and aligning the live collector onto
fawazahmed0 to remove the seam is noted as a future upgrade. Also note history
is one daily *close* per venue while live is hourly — the history line is a daily
series, the live point is the latest hour.

## The incumbent panel

`data/samples.csv` keeps only the *winning* incumbent (the cheapest provider) for
each size. But the Wise comparison API returns the whole board — Wise, Instarem,
HSBC, OFX, PayPal, Western Union, banks — and that panel is worth its own record.
Since **2026-08-11**, every provider's quote is persisted to
`data/providers.csv`, one row per provider per size per hourly run:
`ts_utc, notional_src, provider, landed_dst, cost_bps, rank, source_ok, error`.

`cost_bps` uses the **same convention as the corridor** (bps below the USD
mid-market), so a provider's number is directly comparable to `cost_bps_taker`
and `cost_bps_maker` — you can line the stablecoin route up against the entire
fiat field, not just its cheapest member. `rank` is 1 for the cheapest.

**Caveat — advertised, not executed.** These are the retail prices each provider
*advertised* at quote time, as surfaced by Wise's comparison endpoint. They are
not confirmed fills: real transfers can carry promotional rates, KYC-gated
tiers, corridor limits, or slippage on the delivery side. Treat the panel as the
published shop window, comparable across providers and over time, not as
guaranteed execution. Panel history cannot be back-filled, which is why
collection starts now rather than when the display for it ships.

A Wise-API outage is isolated: `providers.csv` gets a `source_ok=false` row for
that run and the corridor sample still lands (with `baseline_provider` empty) —
a panel failure never fails the corridor collector.

### Promotional pricing

Comparison-API quotes can carry **promotional pricing** — first-transfer offers,
new-customer rates, limited-time discounts. These are real prices, really
quoted, and the panel records them exactly as received. Nothing is filtered,
flagged, or normalised away.

The consequence is worth stating plainly, because it changes how the headline
number should be read: **the baseline is the best *advertised* price at that
instant, not necessarily the best *recurring* price.** A promotional rate can
land a provider *above* mid-market — a negative `cost_bps` under this
convention, i.e. the recipient gets more than the mid-market rate implies —
which no rail can sustain across repeat transfers.

This is not hypothetical. On **2026-08-19**, Xoom quoted **−114.0 bps at USD 200**
and **−114.7 bps at USD 1,000** on USD→MXN, ranking first at both sizes while
pricing above mid-market; at USD 5,000 the same provider quoted **+48.1 bps**.
SGD→PHP shows the milder version of the same thing: 76 of its panel rows sit
below mid-market, all Wise or Instarem, but by fractions of a basis point rather
than a hundred.

So a corridor can read "the fiat rail wins by 240 bps" at small sizes on the
strength of an offer that applies once. The honest fix is to record the quote as
given and say so here, rather than to invent a filter for "real" prices — any
such rule would be this project guessing at commercial terms it cannot see. When
a size shows an unusually large gap in the incumbent's favour, check whether the
winning provider is also winning at the larger sizes; a promo usually is not.

## What is not visible

- **Enterprise payout pricing.** What Nium, Thunes, or a Circle partner quotes a
  business is negotiated and private. Nothing here estimates it. A site that
  claimed to would be guessing.
- **OTC and desk execution.** Large flow does not touch these books.
- **Local payout costs.** GCash cash-out, bank receiving fees, and the like are
  excluded because they hit every rail identically — they change how much lands,
  not which rail wins. If you are computing an absolute landed figure rather than
  comparing rails, add them back.
- **KYC and limits.** "Achievable" assumes a funded, verified account at both
  venues. Onboarding time is a real cost and is not priced here.

## Fee verification status

Fees are the largest single term in the taker decomposition, which makes them
the most important thing to get right and the easiest thing to get wrong. Each
row in `data/samples.csv` carries the fee configuration that was in force when
it was written, so history stays interpretable if a venue changes its schedule.

| Venue | Taker | Maker | Verified against published schedule |
|---|---|---|---|
| Independent Reserve | 0.50% | 0.50% (no maker discount) | 2026-08-10 |
| Coins.ph Pro | 0.15% | 0.10% (VIP0, effective 2025-08-08) | 2026-08-10 |

Both are default/base tier (Independent Reserve 30-day volume < AUD 50k;
Coins.ph VIP0). Each row records the full fee regime in force —
`fee_on_taker_bps`, `fee_on_maker_bps`, `fee_off_taker_bps`, `fee_off_maker_bps`.
Two corrections landed on 2026-08-10:

- **Coins.ph taker** was an assumed 0.25%; the published VIP0 schedule is 0.15%.
  That moved the reference taker figure from ~94.8 to ~84.6 bps at S$5,000.
- **Maker was modelled as free** on both legs; it is not. Applying the real maker
  schedule (IR 0.50% flat + Coins 0.10%) moves the S$5,000 maker figure from
  ~19.8 to ~79.6 bps. The previous "maker beats Wise ~3×" result does not
  survive: at base-tier fees the route loses to the ~66 bps fiat baseline in
  **both** regimes, and wins only at volume tiers.

## Data integrity

- Failed pulls are written as rows with `source_ok=false` and the error string,
  never dropped. A gap in the history is visible as a gap.
- The collector exits non-zero on an incomplete sample so the scheduler goes red.
  An earlier version of this project failed silently for 34 days because nothing
  ever alerted; that is the failure mode this is designed against.
- The sample is written to disk **before** anything is printed. On 2026-08-16 it
  was the other way round, and a formatting bug in the summary table — triggered
  by an on-ramp outage leaving the basis `null` — crashed the run before the
  write, destroying five samples that the first bullet promises to record.
  Persistence is never downstream of display.
- Raw samples are public: `data/samples.csv`.

### Capture cadence

Nominal cadence is **one sample per UTC hour**, per layer.

The workflow fires **twice** an hour (`:17` and `:47`), which is not the same
thing as sampling twice an hour. GitHub Actions treats scheduled runs as
best-effort and silently drops them under load: in the week to 2026-08-18, only
125 of 168 expected hourly fires actually ran — **44 missed hours, ~74%
delivery**, clustered at busy UTC hours rather than randomly. Hourly-only
scheduling therefore lost about a quarter of the series to the scheduler alone.

The second fire is a spare, not a second sample. Both collectors gate on the
target CSV: if a row already carries the current UTC hour, the run exits 0
without pulling or writing. So the `:47` fire is a no-op when `:17` landed and a
rescue when it didn't. Duplicate-per-hour rows are not possible by construction,
and the `concurrency: collect` group serialises the pair so they cannot race.

One consequence worth stating: **a run that commits nothing is now a healthy
outcome**, so "nothing changed" can no longer be the rot alarm. Freshness is
checked directly instead (`tools/check_freshness.py`) — the job goes red if the
newest row in either CSV is more than 3 hours old, whether or not that run had
anything to write.

Gaps remain visible in the data: a missing hour is a missing hour, never
interpolated or back-filled.
