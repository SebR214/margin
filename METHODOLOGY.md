# Methodology

Every number on this site is one of three things: **measured**, **assumed**, or
**not visible**. This page says which is which. If you find something here that
contradicts the charts, the charts are wrong and I want to know.

## How it works

An official exchange rate is not what a person actually pays to turn their own
money into dollars. This site measures that gap, country by country, and
publishes it every hour.

A number gets made the same way every time: the site collects live buy-side
offers on the exchanges people actually use, takes the median price, and
compares it to the official rate captured in the same pass. Nothing is
modelled or smoothed, and a price never publishes on fewer than ten offers.

Where the prices come from, named plainly rather than typed out and left to
go stale:

__SOURCE_LIST_LIVE__

Three things made this hard. Fees hide inside the exchange rate itself and
move with the size sent, so everything is measured all-in, at several
transfer amounts, rather than as one headline percentage. History cannot be
back-filled, so keeping collection running has always mattered more than
shipping a new feature. And a pipeline nobody is watching will happily invent
a plausible-looking number, so nothing here publishes without tracing back to
a file that was actually collected — and a failed attempt stays up rather
than disappearing.

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
| Off-ramp book (USDT→NGN) | Luno public order book | measured |
| Off-ramp book (USDT→INR) | WazirX public depth, 500 levels requested | measured |
| Exchange fees, USD→NGN / SGD→INR / USD→INR | Luno and WazirX published schedules | published, verified 2026-09-29 |
| Network withdrawal fee, USD→NGN / USD→INR | Coinbase, Ethereum (ERC20), 0.01% of amount (max 20 USDT) | published, read 2026-08-19 |
| Network gas, USD→NGN / USD→INR | not published by Coinbase — see below | **not modelled, and material** |

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

**USD→NGN and USD→INR (added 2026-09-29) carry the same gap, but it is bigger.**
Coinbase does not support USDT on Tron, and neither of these corridors' new
off-ramp venues (Luno for Nigeria, WazirX for India) shares a cheap chain
with Coinbase the way Bitso does over Polygon — the one chain confirmed on
both sides is Ethereum itself (ERC20), where gas is not "fractions of a
cent." Coinbase's own published parts (the 0.01%-capped-at-20-USDT
processing fee) are still carried; the ERC20 gas component is real, dynamic,
and not published anywhere scrapeable, so it stays at zero rather than
invented — which means these two corridors' true cost is understated by
more than USD→MXN's, and more so at the $200 rung than at $50,000. SGD→INR
avoids this: it reuses SGD→PHP's Independent Reserve on-ramp unchanged, and
both Independent Reserve and WazirX confirm USDT over Tron, so its 4.0 USDT
flat network fee is the same one already verified for SGD→PHP, not a new
estimate.

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

**Version 1.1, in force from 2026-09-10.** This section defines what "the margin
index for Nigeria is +12% this week" means, precisely enough to be attacked.
Both questions this section originally left open were answered in the 2026-09-10
brief and are now settled below: the index is the **buy side**, and **broker
quotes are their own source class**.

### What the number is

One figure per country per hour, and one published weekly: **how much more, or
less it costs to buy a dollar in that country than its official exchange rate.**

```
index = (price to BUY one USDT locally / official USD rate - 1) * 100
```

Positive means people there pay above the official rate to obtain dollars.
Negative means below. The weekly figure is the median of that country's hourly
figures across the published week, so one dislocated hour cannot carry a week.

**The buy side, not a midpoint.** This is the single most consequential choice
in the definition and it was made on evidence. A midpoint averages what you pay
to obtain dollars with what you would receive selling them — two different
transactions. On an order book those differ by about a basis point and the
choice is cosmetic. On a peer-to-peer board they can be different markets
entirely: on 2026-09-05 Angola's board asked 825 to buy and 1,120 to sell, a 36%
gap that nobody arbitrages because the two sides are segmented by payment rail
and capital controls. Re-tested with and without the amount filter, the gap
persisted, so it is not an artefact of how ads are selected. A midpoint between
them is the price of nothing.

Ten currencies quote a sell side above their buy side for most hours — AOA and
XOF always, UAH 95%, XAF 73%, EGP 68%, INR 59%, BND 52%, UGX 44%, ZMW 40%, MZN
31%. Under a midpoint rule those ten would have to be filtered out. Under a buy
rule they are publishable, and the gap between the sides becomes its own
published number.

**Round-trip cost.** The distance between the buy side and the sell side is
published beside the index as `round_trip_pct`. It is what a market charges to
go in and come out again, and in a segmented market it is the more interesting
of the two numbers. It is never folded into the index.

### Composition — one number, and where it came from

Per country, per hour, in strict precedence. **The classes are never blended.**

| Rank | Class | Shown as | Rule |
|---|---|---|---|
| 1 | `order_book_median` | from order books | Two or more exchange order books → median of their **ask** |
| 2 | `order_book_single` | from an order book | Exactly one order book → its **ask** |
| 3 | `broker_median` | from broker quotes | Two or more broker quotes → median of their **ask** |
| 4 | `broker_single` | from a broker quote | Exactly one broker → its **ask** |
| 5 | `p2p_buy_median` | from person-to-person ads | No venue → median of the **buy-side** ads |
| 6 | `p2p_fallback` | from an independent price source | Only when rank 5 has no evidence at all for the hour, and only for a currency with a named, checked fallback — today just NGN, whose board is structurally empty most hours (see "An independent price for Nigeria" below) |

Where a venue publishes no two-sided quote — Upbit and Pintu publish a last
price only — the last price stands in for the ask, and the row records that it
did. A last price is a trade that happened rather than one offered, which is a
weaker claim, and the country page says so.

**Every published row prints its class.** A reader must never have to guess
whether a number came from a matching engine or an advertisement, and a country
that moves between classes — because a venue was added, or a board went quiet —
changes class visibly rather than silently.

Why precedence rather than a weighted blend: an order-book mid is a price at
which a trade can occur; a P2P advertisement is a price someone is *asking*,
carrying counterparty risk, a payment-rail requirement and a settlement window.
Averaging the two produces a number that is neither, and no reader could say
what it measures.

#### Settled: brokers are their own class

The rule above says "order books". Some of what the collector treats as a venue
is not one. CriptoYa reports **brokers and fintechs**, which quote a spread to a
retail customer rather than running a book. Under the rule as written, today:

- **Argentina** is classed `order_book_median` on **24 sources, every one of
  them a CriptoYa-reported broker.** Its 3.32% between-exchange spread is partly
  retail markup, which the board already footnotes.
- **Venezuela** is classed `order_book_single` on **one broker**.

Neither country has a real order book behind it. **Resolved in favour of
separate broker classes**, as ranks 3 and 4 above: Argentina is `broker_median`
and reads "from broker quotes", Venezuela is `broker_single`. It costs a column
value and removes a claim the data does not support.

**One consequence, stated because it moves published numbers.** The collector
records CriptoYa on a median-**bid** rule, chosen when the number being measured
was market dislocation and a broker's ask carries retail markup. The index
measures what it costs to buy, so it takes the **ask** — markup included,
because the markup is part of what a person pays. Argentina and Venezuela
therefore read higher on the index than the basis figure in `basis.csv`, and the
two are different quantities on purpose. `basis.csv` is unchanged; nothing is
rewritten.

### The denominator, and where it is a policy number

Every figure is measured against the **`open.er-api.com` USD mid captured in the
same row** as the price. Never a rate looked up later, never a rate from a
different hour.

That reference is not the same kind of object in every country. Four classes,
printed alongside the index:

| Class | Meaning | Examples |
|---|---|---|
| `market` | The reference is itself a market price. The index measures a genuine local premium or discount. | SGD, PHP, THB, MXN, BRL, KRW, IDR, ZAR, PEN, CLP, COP, KES, TZS, UGX |
| `managed` | The reference is a number a central bank sets or defends, which the market trades away from. **The index measures distance from a policy rate, not a market spread.** | ARS, VES, LBP, DZD, SYP, IQD, AFN, MZN, ETB, NGN, AOA, UAH, TND |
| `pegged` | The reference is a hard peg. The index reads near zero by construction, and that *is* the finding. | AED, SAR, QAR, KWD, JOD, BND, XAF, XOF |
| `unmaintained` | The government rate exists on paper but has stopped being updated. What we divide by is whatever aggregate of bank-declared rates is still published, not a defended policy number. | SDG |

**`unmaintained`, added SEB-31.** Sudan's central bank still publishes a rate
page at `cbos.gov.sd`, but it returns the same figure it did on 2026-03-07 —
confirmed by a live fetch, not inferred (PR #77). The `open.er-api` aggregate
we fall back to moved 544 → 512 → 511 in two days over the same window, which
is the behaviour of banks re-quoting for themselves, not a rate the state is
holding in place. Calling that `managed`, as if a policy number were being
defended, is a stronger claim than the evidence supports; `unmaintained` says
only what is known. `tools/agent_status.py` treats a big move in an
`unmaintained` currency as explained by the denominator itself, and reports it
on its own line rather than flagging it as a daily mystery.

The other `managed` currencies were checked against three days of
`data/fx_rates.csv` (2026-09-10 to 2026-09-13) for the same evidence and none
of them qualify yet: LBP was byte-identical (89,500) across all 69 readings,
which is consistent with either a genuinely-held peg or a frozen aggregate and
three days cannot tell the two apart; SYP, IQD and AFN drifted a few hundredths
of a percent, too little to read either way; MMK and ZWL have no rows in
`fx_rates.csv` at all. None of the six is moved. A longer window, or a live
check of the issuing central bank's own page the way PR #77 did for Sudan,
would be needed before any of them could be.

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

**Re-checked 2026-09-27, still open.** Live-checked every free/no-key
candidate raised for this (Fawaz Ahmed's currency-api, CurrencyFreaks,
fxratesapi.com): all are daily under the hood, one behind marketing language
claiming per-minute updates that a live spot-check disproved (see
`collector_fx.py`'s docstring for the evidence). Open Exchange Rates' free
tier is genuinely hourly but requires an API key, which is a registration
step none of this site's other sources need — left for Sebastian to decide,
not switched in unilaterally. Until one of those changes, the receipt shown
for every published number now says so directly: the "official rate" step
carries a line stating the value can be up to 24 hours behind the market
(`copy.json`'s `rateStalenessNote`, rendered by `js/receipt_replay.js`).

### History start, per country, honestly

There is no way to make this look better than it is, so it is published as a
column and stated on every country page.

| Coverage | Countries | From |
|---|---|---|
| Daily backfill, then hourly | IDR, KRW, MXN, THB, TRY | 2024-03-02 to 2024-08-10, depending on the currency |
| Hourly order book | ARS, BRL, PHP, SGD, VES | 2026-08-10 / 2026-08-11 |
| Hourly P2P | BDT, BOB, EGP, ETB, GHS, KES, LBP, NGN, PKR, VND | 2026-09-02 |
| Hourly P2P | the 43 currencies added in the wide expansion | 2026-09-05 |
| Hourly order book | TWD, INR, AUD, NZD (APAC additions) | 2026-09-10 |

India is the one currency to move *class* rather than merely gain a source: it
was withheld under the evidence rule because its P2P board is crossed, and it
now has two real order books instead. Its index history therefore begins
2026-09-10, and the P2P rows collected before that remain in `p2p_basis.csv`
as the record of a market that could not be published.

**Five countries have history before 2026. The rest begin when collection
began.** For the P2P layer this is not a gap that can be closed later: Binance
publishes no historical endpoint for its advertisement board, so those series
can only ever start on the day collection started. An index claiming otherwise
would be inventing its own past.

### What a version bump means

Every published file carries `index_version`. **Version 1.2 is in force from
2026-10-09** (second person-to-person board, below). Version 1.1 ran from
2026-09-10; v1.0 was superseded that day by the evidence rule below, after
a verification sprint found that ten P2P boards were crossed. It is incremented when **any
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

### A second person-to-person board (v1.2, 2026-10-09)

Where a country is priced from person-to-person ads (class `p2p_buy_median`) and
OKX's own board (`data/p2p_okx.csv`, written by `collector_p2p_okx.py` with the
same USD 500 ticket and the same top-of-book median) also has a price **in the same
hour**, the published buy price is the **median of the two boards' medians**. Both
boards are listed in the country's `venues` and the file carries `n_boards: 2`
(`1` where only Binance qualifies). OKX has to meet the same evidence bar in its own
row: `source_ok` true and at least 10 ads (`MIN_BUY_ADS`). Where OKX does not
qualify, or the Binance board fails the v1.1 evidence rule, nothing changes: a
country that is withheld stays withheld, and the CoinGecko stand-in
(`p2p_fallback`) is not blended with OKX. `n_sources` keeps its meaning (the
buy-side ads behind the Binance board). Order-book and broker countries are not
touched. `p2p_basis.csv`, `p2p_okx.csv` and every CSV header are unchanged.

Why this bumps the version: it adds a venue to the set behind a country and
moves the number. Applied to the stored rows of 2026-10-09 05:00 UTC, 27
countries change:

| Country | v1.1 | v1.2 |
|---|---|---|
| AMD | -0.0% | +2.2% |
| AZN | +0.1% | +1.3% |
| BOB | -0.2% | +0.5% |
| CLP | +0.7% | +1.2% |
| COP | -0.4% | -0.1% |
| GEL | +0.1% | +0.5% |
| IQD | +18.8% | +18.8% |
| JOD | +1.2% | +0.8% |
| KES | +0.0% | +0.7% |
| KHR | +2.4% | +2.8% |
| KWD | +1.1% | +1.5% |
| KZT | +8.2% | +7.7% |
| LAK | +2.6% | +4.2% |
| LBP | +0.5% | +2.2% |
| LKR | +3.0% | +7.2% |
| MAD | +3.3% | +3.5% |
| PEN | +0.1% | +0.6% |
| PKR | +2.9% | +3.2% |
| QAR | +5.5% | +14.6% |
| RWF | +0.4% | +1.0% |
| SAR | +3.1% | +4.9% |
| TND | +16.1% | +26.6% |
| TZS | +1.4% | +2.9% |
| UGX | +2.5% | +7.5% |
| VND | +0.9% | +0.9% |
| ZAR | +9.4% | +9.9% |
| ZMW | +4.4% | +7.7% |

The two boards sometimes disagree widely (Tunisia: Binance +16.1%, OKX +37.1%), and
the median of two is their midpoint, so a wide gap moves the figure a long way. Both
prices stay visible on the country page.

### The evidence rule (v1.1)

A peer-to-peer value is published only when **both** of these hold:

1. **At least 10 ads on the buy side.** A median resting on two advertisements
   is not evidence of a market price.
2. **The buyer's price is at or above the seller's price.** Where it is not, the
   two sides are not the same market and neither number describes the other.

Where either fails the hour is still collected and stored; it is simply not
published. The country page says **"not enough evidence this hour"**, prints the
reason, and prints the buy-side price that was withheld together with the round
trip, so nothing is hidden — only unpublished.

**This is not a filter that removes a market.** A filter would make a country
disappear. Here the country keeps its page, its history and its reason, every
hour, and returns to the index the moment its board meets the rule.

On 2026-09-10 the rule withheld 15 of 57: AOA, BND, INR, MZN, UAH, UGX, XAF and
XOF for a crossed book; AFN, BDT, NPR and BWP for too few buy-side ads; ETB, GHS
and NGN because no board exists at all.

`p2p_basis.csv` records `n_ads` as the two sides added together and its schema is
frozen, so the per-side counts the rule needs are written to a sidecar,
`data/p2p_sides.csv` (`ts_utc,ccy,n_buy,n_sell`). Rows collected before that
sidecar existed carry `buy_ads_estimated`, and for those the rule uses "both
sides full" as a conservative stand-in — the only combination of a summed count
that guarantees a full buy side.

**`n_buy` measures whether the page filled, not how deep the board is (SEB-50).**
The collector fetches one page of 10 ads per side; `n_buy` counts how many of
those had a usable price, so it tops out at 10 and stays there whether the
board holds 11 ads or 5,000. A board sitting at "10 buy / 10 sell" every hour
reads as well-evidenced by rule 1 above and gives no way to tell a deep,
liquid board from one that would fail the rule if two more ads were pulled
off it — the finding behind
[SEB-49](https://linear.app/sebastian-roervig/issue/SEB-49/dzd-moved-143-index-points-in-one-hour-with-the-official-rate-flat-and).
Binance's own search response already carries the real count behind the page,
in a `total` field that the collector previously read and discarded, so
`data/p2p_depth.csv` (`ts_utc,ccy,buy_total,sell_total`) now records it — at no
extra request and with no change to the fetched page or the published price.
Empty where the field was unreadable, never 0, and empty for every hour
before this sidecar existed; nothing here is backfilled. **This depth is not
yet part of the publish decision above** — rule 1 still tests `n_buy`. Wiring
real depth into the rule changes which hours count as evidence and is its own
methodology decision, left for a follow-up issue.

### An independent price for Nigeria (SEB-8)

NGN is the one currency this rule withholds for a *structural* reason rather
than a thin or crossed one: Binance delisted its NGN board after the 2024
crackdown, and the search endpoint now answers zero ads on both sides, most
hours, every day (see ROADMAP, "Known-invisible"). A commission asked for a
second source for exactly those hours.

`collector_p2p.py` now reads CoinGecko's public price endpoint
(`api.coingecko.com/api/v3/simple/price?ids=tether&vs_currencies=ngn`) as a
second row, written **only on the hours the ad board itself has zero ads on
both sides.** It is never consulted while the board has ads of its own, and it
is never blended with a board price — the two never coexist for the same hour.

It is a materially different kind of source and the page says so: a single
aggregated price, not two sides of a market, so it carries no buy or sell side
of its own and no round-trip figure. It is shown with its own class,
`p2p_fallback`, "from an independent price source", never folded into
`p2p_buy_median`.

Before being wired in, the one candidate the commission named was checked with
`tools/probe_source.py` against `open.er-api.com`, the same reference this
project already uses as the FX denominator:

```
candidate  https://api.coingecko.com/api/v3/simple/price?ids=tether&vs_currencies=ngn
           field `tether.ngn` reported 1326.44 NGN per dollar
reference  open.er-api.com reported 1327.27 NGN per dollar
difference -0.06%, against the ±1% accept bar (checked 2026-09-12)
```

Well inside the bar, so it is trusted the same as any other row. Because
`data/p2p_basis.csv`'s columns are frozen and were built for a two-sided ad
board, the fallback row uses only the columns that are true of it: `source`
reads `coingecko`, `mid` carries the price, `buy_median`, `sell_median` and
`n_ads` stay empty or zero because none of those were measured. The daily
history in `daily_history()` reads `buy_median` for its P2P leg, so an hour
priced only by the fallback does not (yet) feed the multi-day chart — the
v1.1 evidence rule and the daily series stay exactly as they were for every
other currency; only the current-hour reading on Nigeria's page gains a value
it did not have before.

### Sanity bands and the "unverified" label

A value above **+200%** or below **−3%** is not published in the ranked index
until it has been checked against a reference outside this project and the check
recorded in "Checked against" below. Until then the country keeps its page and
its number, carrying a visible **Unverified** banner that says why, and is left
out of `data/index_latest.json`.

The band is not a claim that such values are wrong. Sudan's +1,203% is correct
arithmetic against an official rate no transaction uses. The band only decides
what gets ranked without a human having looked.

### Settled: thin and broken boards need no filter

The buy-side rule dissolves most of this. A sell median above a buy median is
not a broken board once the sell side is no longer used — it is a segmented
market, and the segmentation is published as `round_trip_pct` rather than
hidden. **No market is filtered out of the index.** What remains:

```
AOA   buy   826.58   sell 1,113.54    sell 35% ABOVE buy, 15 ads
UAH   buy    45.31   sell    47.98    sell above buy
NPR   buy   164.79   sell   150.15    ~10% spread, 12 ads
BWP   0 buy ads against 10 sell       already fails: a mid needs both sides
BND   pegged 1:1 to SGD, reads +639 bps on 18 ads
```

A country with **no buy-side ads at all** has no index value for that hour, and
the row says so with its reason. That is not a filter; it is the absence of a
price. As of 2026-09-05 that is BWP (sell ads only), and NGN, GHS and ETB (no
board at all).

`n_sources` is published beside every value so a reader can judge how thin the
number is, and no minimum is imposed. Imposing one would be a filter, and a
filter would need to be stated here first — which is what this section is for.

## The denominator of record (`data/fx_rates.csv`)

Every index figure is a price divided by an official rate, so the rate deserves
a record of its own rather than arriving invisibly inside a price row.
`data/fx_rates.csv` is that record: one row per currency per hour, carrying the
rate, **the source it came from**, whether the currency is managed, and a
parallel rate where a public feed publishes one.

**There is no intraday source.** Four candidates were called from a US runner on
2026-09-10 and three are worse than what was already in use:

| Source | Currencies | Ours covered | Cadence |
|---|---|---|---|
| `open.er-api` | 166 | **36 of 36** | daily, stamped 00:02 UTC |
| `frankfurter.app` | 29 | 10 of 36 | the ECB daily fix, a day older |
| ECB reference feed | 29 | 10 of 36 | the same daily fix |
| `exchangerate.host` | — | — | refuses without an access key |

`frankfurter` and the ECB feed *are* the same fix and cover almost no emerging
market. So `open.er-api` remains primary on both freshness and coverage, and the
file records that choice on every row instead of leaving it implicit. If an
intraday source ever appears, only the source list changes.

**A central bank outranks an aggregator.** Where one publishes its own reference
rate without a key, it is preferred for its own currency. Today that is
Argentina: BCRA's Comunicación A 3500 rate, which is why Argentina's denominator
now matches the central bank exactly rather than to a tenth of a percent.

**Parallel rates are recorded, never substituted.** For a managed currency the
official rate is a policy number, so where a public feed publishes the parallel
rate it sits in `parallel_rate_per_usd` beside the official one, with its source
named and the gap computed. It is never used as the denominator — swapping it in
would be a version bump under the rules above, and both would then be published
side by side. Blank where no public feed exists; never estimated.

First run, 2026-09-10: ARS parallel +1.09%, BOB −2.01%, VES **+14.03%**.

## Corridors priced

Seven routes, each priced hourly across a five-amount ladder against every
provider the Wise comparison API returns for it.

| Route | Buy the coin | Sell it | Fees verified |
|---|---|---|---|
| Singapore → Philippines | Independent Reserve | Coins.ph | 2026-08-10 |
| Australia → Philippines | Independent Reserve | Coins.ph | 2026-08-10 |
| New Zealand → Philippines | Independent Reserve | Coins.ph | 2026-08-10 |
| United States → Mexico | Coinbase | Bitso | 2026-08-19 |
| United States → Nigeria | Coinbase | Luno | 2026-09-29 |
| United States → India | Coinbase | WazirX | 2026-09-29 |
| Singapore → India | Independent Reserve | WazirX | 2026-09-29 |

The last three were added by the 2026-09-29 pass that grew this site from
four corridors to seven (4→7); see the re-check below for why SGD→INR, in
particular, had been ruled out two days earlier and what changed.

The two APAC routes added on 2026-09-10 introduce **no new fee source**:
Independent Reserve publishes one flat 0.50% brokerage across its markets — its
volume tiers are denominated in AUD, not per currency — and Coins.ph VIP0 is
0.15/0.10 on every book. That is the whole reason they could be built.

**Three APAC routes were probed and, at this point, not built.** The
comparison side is not the constraint: all 19 APAC pairs tested return
providers with Wise present. The crypto leg is. Indodax 404s on both its fee
API and its help page; WazirX's fee *API* returns 403 and its fee page looked,
at this reading, like a JavaScript shell with no fee text; CoinDCX's
`markets_details` is readable but its `maker_fee` and `taker_fee` are both
`null`. A cost built on a fee nobody can check is not a measurement, so at
this point SGD→IDR, SGD→INR and SGD→MYR were absent and this paragraph was
why. (SGD→INR was later built — WazirX's fee *page*, as opposed to its fee
API, turned out to be readable; see the correction after the 2026-09-27
re-check below. SGD→IDR and SGD→MYR remain unbuilt.)

**Re-checked 2026-09-27, specifically to test whether SGD→INR could carry the
route where India's street premium (about 4.5% over official, see the index)
might outweigh a stablecoin route's own cost.** The 2026-09-10 finding still
holds, and two more venues were added to the search:

- `api.wazirx.com/sapi/v1/fees` still returns HTTP 403. `exchangeInfo` lists
  the `usdtinr` market but carries no fee field.
- `api.coindcx.com/exchange/v1/markets_details` still returns `USDTINR` with
  no `maker_fee` / `taker_fee` field at all now, not even a `null` one.
- **ZebPay**, checked for the first time: `zebpay.com/fees` is a real,
  readable page (not a JS shell) with a dated crypto-withdrawal table — USDT
  is 3 (Ethereum, ERC-20) or 8 (Tron, TRC-20), a genuinely checkable number.
  But the INR-leg trading fee is not in that table. The page states fiat
  deposit and withdrawal are both free and lists a single figure for
  converting between assets: "Quick Trade 0.5% onwards." *Onwards* is not a
  fee schedule; it names a floor with no ceiling and no tier definition, so it
  fails the same bar Indodax and WazirX fail on, for a different reason.
- **Giottus**, checked for the first time: no readable first-party fee page
  was reachable (bot-blocked, matching CoinDCX); third-party trackers quote
  contradicting numbers for its own maker/taker table, which is exactly the
  "estimate, not a measurement" problem this file exists to avoid.
- `api.binance.com/api/v3/exchangeInfo` — the largest global venue, checked as
  a control — lists no `INR`, `BDT` or `PKR` pair of any kind. These three
  currencies exist in this site's index only through Binance's P2P
  advertisement board (see the P2P layer below), which has no fee schedule to
  check because it is not an order book with a maker/taker table; it is
  individuals naming their own price.

The conclusion at the time was stronger than the 2026-09-10 version of it:
this looked like not one exchange's bad page, but every venue with an INR,
BDT or PKR order book failing the same check, for four different reasons
(403, `null`, "onwards", bot-blocked). Any corridor into BDT or PKR stays
unbuilt for that reason today. The site would rather publish nothing for a
route than publish a stablecoin cost built on a guessed fee — which is the
one number that would decide whether stablecoins beat apps here, so guessing
it is exactly the guess this file cannot make.

**Corrected two days later, 2026-09-29: SGD→INR was built after all, on a
check this re-check didn't run.** Everything above checked WazirX's fee
*API* (`api.wazirx.com/sapi/v1/fees`, 403; `exchangeInfo`, no fee field) —
not its fee *page*. `wazirx.com/fees?tab=spot_fees` renders live and lists
USDT/INR as an INR market under WazirX's "Pay Per Trade" plan: base tier
(0–500 WRX held, ≤ INR 5 lacs 30-day volume) is a flat 0.40% on every trade,
no maker/taker split, read live 2026-09-29. That is a published, checkable
schedule the same way Independent Reserve's flat schedule is, so SGD→INR
and USD→INR were built on it, in the same pass that added USD→NGN on Luno.
SGD→IDR and SGD→MYR were not re-checked and remain absent for the reasons
above.

## Where a provider's price comes from

Every competitor figure used to come from one place: the comparison Wise
publishes. That is a good source and it is not a neutral one — it is one
company's list of who counts as a competitor, and it does not include everyone.

**The precedence rule.** Where a company publishes its own rate, that is the
number used. Where it does not, the comparison stands in. A company quoting
itself is the more direct evidence. Every published row says which source it
came from, so a reader never has to guess.

Where both exist the comparison figure is still recorded in
`data/providers_latest.json` as `also_quoted_pct`, but it is **not shown beside
the company's own quote**. Putting the two side by side reads as an accusation,
and the ranking is not an argument with anyone's published comparison.

Cost is measured the same way as everywhere else here: how much less the
recipient ends up with than the mid-market rate would give them, counting the
exchange rate and every fee as one number, because that is what a sender
experiences.

| Company | Own published quote | Notes |
|---|---|---|
| Instarem | yes, public quote API | account id is per source country; only SG and AU are verified, so only those two routes are asked |
| Airwallex | yes, public indicative quote | all four routes |
| Revolut | **no** | publishes a live rate on its site, but the quote needs an account and the page blocks non-browsers. Reading it hourly would mean running a headless browser; left out rather than estimated |
| everyone else | no | from the comparison Wise publishes |

One thing the data shows plainly and the site states without comment: a
company's own quote and a third-party comparison of it are **not always the same
number**. Both are recorded. Neither is called wrong.

### How fast the money arrives (`data/provider_delivery.csv`)

Where a provider's own page states a delivery time, that exact phrase is read
and shown verbatim next to its row on sending-money.html — "Same day", "in
seconds", "by Friday" — never reworded, never estimated for a provider that
doesn't state one.

| Company | Own delivery time | Notes |
|---|---|---|
| WorldRemit | yes | read off the same rendered calculator widget `parse_worldremit` already reads for rate and fee — no new request |
| Wise | yes | its own quote API already returns `formattedEstimatedDelivery` per payment option, already plain language |
| Instarem | **no** | its public quote API's response carries no delivery/ETA field (checked live, 2026-10-01) |
| Airwallex | **no** | its public indicative-quote response carries no delivery field (checked live, 2026-10-01) |

A row is sidecared only when a provider's own page actually stated a time that
hour. Absent means it wasn't measured — never shown as "not stated" in its
place.

## When a company has changed its price (`data/price_changes.csv`)

A provider's cost is measured against a mid-market rate. Our snapshot of that
rate and the moment the provider's quote was captured are never the same
instant, so every measured cost wobbles even when nobody has touched their
pricing. Measured over a month of SGD→PHP and USD→MXN:

| | median hour-to-hour | median day-over-day, on daily medians |
|---|---|---|
| every provider, every size | 2 to 4 bps | ~12 bps |

The second number is the one that matters, and the giveaway is *when* it lands:
the same day for every provider in a panel at once — 2026-08-19→20 across all
nine providers on USD→MXN, 2026-08-11→12 across all six on SGD→PHP. Nine
companies do not reprice in unison. That is the reference moving.

So a plain "cost changed by more than X" test reports the reference as news, at
any threshold: at 0.02 percentage points it fires on roughly half of all hours.

**The test used instead is pairwise unanimity.** A provider is recorded as
having changed its price on a day only if its cost moved against **every** other
provider in the same panel, on the same day, in the same direction, by at least
0.02 percentage points, with at least six hourly readings on each of the two
days being compared.

Both sides of each pair are measured against the same rate at the same instant,
so the rate cancels exactly. A move in the reference shifts the whole panel
together and produces no pairwise difference at all — it is silent. A move by
one provider shows up against all of its peers and is reported.

This also survives the case that defeats a basket average. When OFX moved ~90
bps on USD→MXN it dragged any average or median of the panel with it, painting
a false ~18 bps move on every other provider. Pairwise differences are immune,
because the peer being compared against is never the mover.

**What the two cost columns mean.** `new_cost_pct` is the provider's observed
daily median cost on the day of the change. `old_cost_pct` is that figure minus
the confirmed move — what the same day would have cost at the old price. Both
therefore sit on the same day's exchange rate, so their difference is exactly
the move and a row can never contradict itself. The previous day's raw observed
median is kept alongside as `prev_day_cost_pct`; it differs from `old_cost_pct`
by the reference drift, which is precisely the quantity this file refuses to
publish as news.

**Weekend rates.** A rise on a Saturday that comes back on the following Monday
is labelled a weekend rate rather than two repricings. Matched on the event —
one company, one route, one day — not on each amount separately, because a
company raises its price, not its price-at-S$200. Both legs must be present in
the data; nothing is inferred from one leg alone.

The pairing is done when the findings file is built (tools/emit_findings.py), from
the stored rows, not when a row is written. data/price_changes.csv is append-only:
a Saturday rise is written as a plain change, because its Monday cut does not exist
yet, and it is never relabelled. Counting the stored `kind` column would leave most
rises unpaired (on 9 Oct, 104 cuts against 25 rises, with 88 of the matching Saturday
rises still stored as changes). The build applies the same rule to the stored rows
and counts the result. The file itself is not touched. This changes only findings 01
and 02. No published country number changes, so `index_version` does not move.

**What is judged.** Only complete days: the first day in a panel has nothing
before it, and the last is today, still filling. The file is append-only and
never rewrites a row, so a call made on half a day could not be corrected.

**Not backfilled.** The record starts when measurement started — 2026-08-11 for
SGD→PHP, 2026-08-19 for USD→MXN. AUD→PHP and NZD→PHP began on 2026-09-10 and
will produce their first eligible comparison once they have three days.

## The stress signal (`data/stress_signal.csv`)

A standing, public prediction: when a country's street price for a dollar
pulls sharply further from its official rate in a single day, and the official
rate itself did not move enough to explain that, it is flagged and kept on the
record — so what its official rate does afterward can be checked against the
flag, not just asserted.

**The trigger reuses a check that already existed.** `tools/agent_status.py`
already computes, every run, whether a published country's index moved a lot
in a day without its own official or parallel rate moving enough to explain
it — an internal health check, not a public claim. `tools/emit_stress_signal.py`
runs the same comparison and keeps a permanent, append-only record of it
instead of overwriting it hourly:

* **Widened**: the country's premium (`index_pct`, the same figure "The index,
  version 1" defines above) moves further from zero — `|index_pct| ` grows —
  by more than **5 percentage points** in one day.
* **Unexplained**: over the same day, `data/fx_rates.csv`'s daily median
  official rate for that currency moved by less than **2%**. A currency whose
  official rate also moved that day is not a street-price story; it is just
  the currency, and is not flagged.
* Both days being compared must be calendar-adjacent and on or after the
  first day `data/fx_rates.csv` has a row for. A gap in either file's history
  is a gap, not a one-day move, and is skipped rather than spanned.

**Not backtested.** `data/fx_rates.csv` — the official rate this signal checks
a street price against — starts on 2026-09-10, with nothing before it to
compare against. Rather than backfill it into the live layer, which the project
never does, the record starts on that date and runs forward. (The separate
"reported, not observed" history layer below holds official-rate history of its
own; this signal does not read it.) `/stress.html` states the
record's start date and its length in days on every load, so a four-day record
reads as four days, not as an established track record.

**What "since" means.** Each flagged row also carries, in
`data/stress_signal_latest.json` only (not the frozen CSV — this changes every
run), how far the official rate has moved between the day it triggered and the
newest day on record for that currency. That is the "what happened next" half
of the prediction, recomputed on every page load from the same
`data/fx_rates.csv` daily medians.

## The P2P spread signal (`data/p2p_spread_signal.csv`)

Every two-sided P2P reading already carries a buy price and a sell price
(`data/p2p_basis.csv`'s `buy_median`/`sell_median`) — the cost of buying a
dollar on that board that hour and immediately selling it back. A gap that
suddenly widens is a thin-market signal: it caught Algeria pulling 12% in two
hours (SEB-49) while the official rate stayed flat, and CriptoYa's own Algeria
reference confirmed the real market had not moved — the excursion reverted
within three hours.

`tools/emit_spread_signal.py` reads `data/p2p_basis.csv` and, for every
two-sided reading, records:

* `spread_pct` — `(buy_median − sell_median) / mid × 100`, that hour's
  round-trip cost.
* `ccy_mean_spread_pct` — that currency's own mean `spread_pct`, over every
  strictly earlier two-sided reading of the same currency. Never a reading
  from later, so an old row's baseline is never rewritten by what came after
  it — and never a global number: NPR and BWP run a double-digit spread every
  hour and a currency running near 2% does not, so the same number means
  different things on each.
* `spread_ratio` — `spread_pct / ccy_mean_spread_pct`, this reading against
  that baseline. Needs at least 30 strictly earlier readings (roughly a day
  and a quarter at the hourly cadence every currency here keeps) and a
  positive baseline — a currency whose board runs crossed or flat (see "The
  evidence rule" above) has no stable cost to compare against, so its ratio
  stays a gap rather than a number that would blow up or flip sign on an
  ordinary move.

This is a record, not a rule. Nothing reads this file yet, and nothing
withholds or marks an hour because of it — what to do when it fires is a
separate, reader-facing decision (SEB-52).

## The volume-tier crossover (`data/volume_crossover.json`)

At the published BASE-tier fees every venue publishes for a brand-new
account, the stablecoin route loses to the best incumbent fiat rail on
SGD→PHP, at every size on the ladder, in both execution regimes. That is
the headline finding this whole repo exists to defend. It is also not the
end of the story: every venue that charges a trading fee discounts it as
30-day volume rises, and nothing here measured where that discount actually
closes the gap until this file existed.

**What is scraped.** `tools/check_fees.py` already re-reads Independent
Reserve's and Coins.ph's published fee pages monthly to catch drift on the
base tier (`data/fee_checks.csv`) — both pages carry their FULL tier table
in that same fetch, and until this existed every tier past the first one
was fetched and thrown away. `data/fee_tier_schedule.csv` keeps the rest:
28 real tiers from Independent Reserve (AUD 0 to AUD 200,000,000), 10 real
VIP tiers from Coins.ph (PHP 0 to PHP 5,000,000,000), and Bitso's own
`fees.structure` for USD→MXN's off-ramp leg, no scraping needed — its API
already returns the whole schedule as structured JSON. Coinbase's on-ramp
fee for USD→MXN is not in this file: its fee pages sit behind Cloudflare's
bot challenge for both a logged-out visitor and a real headless browser,
confirmed directly rather than assumed, so USD→MXN's crossover is not
computed here — half a real tier schedule is not a crossover.

**What is computed.** `tools/emit_volume_crossover.py` takes every real
SGD→PHP sample at the S$5,000 rung where both legs filled, and for a
candidate monthly SGD volume re-derives `decompose()`'s own money-flow
formula (on-ramp buy, on-ramp fee, network fee, off-ramp sell, off-ramp
fee) from that row's already-recorded vwap, mid and network-fee columns,
substituting in whichever tier's fee that volume would unlock on each
venue independently — Independent Reserve's tiers convert through the
day's live AUD/SGD rate, Coins.ph's through that same row's own real
historical prices scaled to the transaction count the candidate volume
implies, not a separately assumed exchange rate. This is validated before
it is trusted for any new tier: reconstructing a row at its OWN recorded
base-tier fee has to reproduce its recorded `cost_bps_taker` — it does, to
within 0.01 bps across every usable row, checked on every run
(`reconstruction_max_error_bps` in the emitted JSON; the script refuses to
publish a result if that check fails).

**The one approximation.** Recomputing at a different fee re-derives the
exact amount that flows through the off-ramp book (fees are linear, so
this part is exact), but reuses that row's REAL recorded off-ramp VWAP
rather than re-walking a hypothetical order book at the fee-adjusted
amount — this repo has no historical order-book snapshots to re-walk, only
the VWAP summary each pass already recorded. For any real fee-tier delta
(a few dozen bps at most) the traded quantity moves by a fraction of a
percent, well under the book's own recorded slippage. Stated here rather
than hidden: this is a model with one acknowledged simplification, not a
re-measurement from raw order books.

**The result**, at time of writing: the taker crossover sits at roughly
SGD 3.6M/month (the volume that unlocks Independent Reserve's 0.14% tier,
down from 0.50% at the base rate); maker at roughly SGD 2.7M/month
(0.18%). Both numbers, and the full cost-vs-volume curve behind them, are
in `data/volume_crossover.json`, regenerated by re-running the script —
never typed by hand.

## Checked against

Every number here is computed from rows this project collected itself, which
means the project can be internally consistent and still wrong. These are checks
against references it does not control. **A difference over 1% needs an
explanation or the country carries the "unverified" label.**

All figures below captured 2026-09-10, 08:00–09:00 UTC.

### Which side of a peer-to-peer board a buyer pays

Checked first, because everything else rests on it. Binance's search endpoint
takes a `tradeType` from the **user's** side and returns ads whose
`adv.tradeType` is the **advertiser's** — always the mirror:

```
request tradeType=BUY   -> adv.tradeType=SELL   (an advertiser selling to you)
request tradeType=SELL  -> adv.tradeType=BUY    (an advertiser buying from you)
```

Confirmed on VND, INR and EGP. **Request `BUY` is the price a person pays to buy
a dollar**, which is what this project labels the buy side. The labels are
correct and no row has ever been swapped.

The same check disproved the comfortable explanation for the crossed boards. In
India the ten cheapest asks ran 102.44–103.44 while the ten highest bids ran
103.90–103.96: the book is genuinely crossed by 1.5%, not mislabelled. That
finding produced the v1.1 evidence rule rather than a correction.

### South Korea — against Bitcoin, independently of USDT

| | |
|---|---|
| Ours, buy side across three order books | **1,357.00 KRW** |
| Upbit BTC/KRW 106,126,000 ÷ Coinbase BTC/USD 78,050.99 | **1,359.70 KRW** |
| Difference | **0.20%** |

A route with no stablecoin in it at all agrees to a fifth of a percent.

### Nigeria — Luno, against Bitcoin

| | |
|---|---|
| Ours, Luno USDT/NGN ask | **1,372.20 NGN** |
| Luno BTC/NGN 106,869,092 ÷ Coinbase BTC/USD 78,048.98 | **1,369.26 NGN** |
| Difference | **0.21%** |

### Nigeria's fallback — CoinGecko, against `open.er-api.com`

Checked 2026-09-12, before wiring in the `p2p_fallback` source described in
"An independent price for Nigeria (SEB-8)" above.

| | |
|---|---|
| CoinGecko `simple/price`, `tether.ngn` | **1,326.44 NGN** |
| `open.er-api.com`, the same denominator this project uses everywhere | **1,327.27 NGN** |
| Difference | **-0.06%** |

### Argentina — against CriptoYa's own published figure

| | |
|---|---|
| Ours, median broker ask | **1,608.22 ARS** |
| CriptoYa published *dólar cripto* USDT ask | **1,595.00 ARS** |
| Difference | **0.82%** |

**Correction, 2026-09-10.** This section previously claimed the denominator was
1.31% wrong, on the basis that CriptoYa's `oficial` read 1,535 against
`open.er-api`'s 1,515.11. That comparison was mistaken: **1,535 is the retail
*sell* rate, not the official mid.** Checked against the central bank itself —
BCRA's Comunicación A 3500 reference rate, published without a key — the numbers
are:

| | ARS per USD | vs BCRA |
|---|---|---|
| **BCRA reference** | **1,513.50** | — |
| `open.er-api` | 1,515.11 | **+0.11%** |
| CriptoYa `oficial` mid (1,485 / 1,535) | 1,510.00 | −0.23% |
| CriptoYa `oficial` ask — what was wrongly used | 1,535.00 | +1.42% |

`open.er-api` was within **0.11%** of the central bank all along. The index now
takes Argentina's denominator from **BCRA directly**, because a central bank
outranks an aggregator, which puts it at 0.00% by construction.

### Singapore to the Philippines — against Wise's live quote

| | |
|---|---|
| Wise, live: rate 49.4622, fee S$4.63 on S$1,000, received ₱49,233.19 | **44.89 bps all in** |
| Ours, `providers.csv`, same hour | **45.25 bps** |
| Difference | **0.36 bps — 0.004%** |

### Checks that could not be completed

A published Nigerian parallel-rate feed and a public kimchi-premium tracker were
both attempted and neither answered without a key
(`api.kimpga.com` 404, `api.dunamu.com` 404, `api.exchangerate.host` no data).
The Bitcoin-implied routes above stand in for both, and are arguably stronger
because they share no source with the number being checked. Said here rather
than left as a gap someone else has to notice.

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

### Exchanges live as of 2026-09-10

| Currency | Exchanges | Median? |
|---|---|---|
| KRW | Upbit, Bithumb, Coinone | yes, 3 |
| TWD | BitoPro, MAX | yes, 2 |
| INR | WazirX, CoinDCX | yes, 2 |
| AUD | Independent Reserve, BTC Markets (added 2026-10-02, SEB-188) | yes, 2 |
| NZD | Independent Reserve | no — one only |
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

**APAC additions, 2026-09-10.** Taiwan and India each gained two independent
order books, so both carry a median rather than one venue's opinion, and the two
books agree closely on the first reading — Taiwan within 1.6 bps, India within
0.6 bps. Australia and New Zealand had one book each and said so; Australia gained
a second, BTC Markets, on 2026-10-02, so only New Zealand still has one.

Called and rejected, with the reason: **Coinhako (SGD)** 403 behind Cloudflare,
unchanged since 2026-09-02; **Luno (MYR)** answers `ErrMarketUnavailable` — it
runs a MYR book for Bitcoin but none for USDT; **bitFlyer and Coincheck (JPY)**
both answer, but neither lists a USDT/JPY market at all, only BTC. So Singapore
still has one exchange, and Malaysia and Japan have no order book to read.

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

**Now on the site.** Seven days of rows was the bar (a single-figure difference
between two stablecoins is inside the noise of any one hour); the file now
holds well over that. `tools/emit_countries.py` carries the most recent
reading for a country's own venues onto its page as `instrument_check`, keyed
strictly by (currency, venue) — a country never inherits another country's
reading. Below a 0.5% gap the page says nothing, since that is inside the noise
this file exists to measure; above it, the country's page says in plain
language that the dollar itself is trading off, and names the venue.

__STABLE_SPREAD_LIVE__

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

## The history layer ("reported, not observed")

Added 2026-10-03 (SEB-207). Everything this site publishes as a measurement was
observed by its own collector, hour by hour. History from before that is a
different kind of thing, and it is kept as a different kind of thing:

- **Its own files.** `data/history/` only. `tools/backfill_history.py` is the
  only writer; it is idempotent, never overwrites a stored row, and has a
  `--dry-run`. Existing files are untouched: `data/basis_history.csv` keeps its
  header, and new series go in new files.
- **Every row labelled `reported, not observed`, source named.** Candle files:
  `ts_utc, venue, ccy, pair, interval, close, label, source`; official rates:
  `date, ccy, per_usd, label, source`; parallel dollar:
  `date, market, ccy, buy, sell, label, source`.
- **Rows come only from an exchange's or data provider's own history endpoint.**
  Never derived, filled, interpolated or crossed against another series: a row is
  the number the venue or provider reported for that hour or day. If the endpoint
  has no candle for an hour, there is no row. A candle still open when fetched is
  skipped, so a stored row never changes.
- **It never feeds the live layer.** Not the index, not a published price, not
  the observed series (`data/basis.csv`, `samples.csv`, `p2p_basis.csv`, ...), not
  the unbroken-hours count. `tools/check_history_isolation.py` proves it: no code
  outside the history tool names the directory, no emitter walks `data/`
  recursively, `unbroken_hours()` is run with every file open recorded, and the
  label appears in no observed file. A page may compare today against history
  ("widest since 2023 in Upbit's own history") only with the label and the source
  on the page.
- **P2P-only countries have none.** Binance P2P has no history endpoint. Their
  pages say history starts on our first collection date.
- **Depth.** Daily candles are taken at each venue's full offered depth; hourly
  candles from 2025-01-01 (`--hourly-since`), a size cap, not an endpoint limit,
  except where noted. Hourly runs through the latest closed hour.
- **On the country page (SEB-208).** `tools/emit_country_history.py` is the one
  other reader of `data/history/` (`tools/check_history_isolation.py` names it
  as the exception). For a currency with both a venue candle series and an
  official rate series, it computes the same index formula the live chart uses
  -- price to buy one stablecoin divided by the official rate, minus one -- for
  every day the two overlap and that falls strictly before the country's own
  live `history_start`, so the result, `data/country_history_segment/<CCY>.json`,
  never overlaps what the live chart already shows. When a currency has more
  than one venue (Korea: Bithumb, Coinone, Upbit), the venue with the earliest
  first candle wins. A currency with no venue series (Argentina, Nigeria) or no official
  rate gets no file. Only a venue's newest stretch with no hole over 31 days is
  used, and a venue with any print more than 50% from the official rate is passed
  over (rows themselves are never altered). `country.html` draws this as a second, dashed,
  unfilled line on the same `js/chart.js` component -- never a second chart
  type -- marks the three largest day-over-day moves (found by sorting, not
  chosen), and states the venue, the rate source and the date range on the
  page. A currency with no file instead states its live history's own start
  date, per the rule above.

**Probe verdicts, 2026-10-03** (public, login-free endpoints, real requests; none
needed a key). None of these endpoints states a data licence; the use here is
prices as reported by the venue, named on every row, and nothing is resold.

| Candidate | Endpoint | Result | Verdict |
|---|---|---|---|
| Upbit KRW-USDT | `api.upbit.com/v1/candles` | hourly and daily; the endpoint stops at 2024-06-07 | accepted |
| Bithumb KRW-USDT | `api.bithumb.com/v1/candles` | hourly from 2025 as collected (the daily goes to 2023-12-06); `to` is read as KST | accepted |
| Coinone KRW/USDT | `api.coinone.co.kr/public/v2/chart` | hourly and daily; daily from 2023-11-29 | accepted |
| BTCTurk USDTTRY | `graph-api.btcturk.com/v1/klines/history`, `api.btcturk.com/api/v2/ohlc` | hourly and daily; daily from 2018-07-10 | accepted |
| Paribu | `v4.paribu.com/market/usdt-tl/ohlc` | answers with a Cloudflare Access sign-in page; the web chart route 404s | rejected: login wall |
| Indodax USDTIDR | `indodax.com/tradingview/history_v2` | hourly (7-day windows) and daily; the endpoint returns at most ~731 candles per call, so daily is paged in 700-day windows, from 2018-08-24 | accepted |
| Bitkub USDT_THB | `api.bitkub.com/tradingview/history` | hourly and daily; daily from 2018-11-12 | accepted |
| Bitso usdt_mxn | `api.bitso.com/api/v3/ohlc` | with `start`/`end` (epoch ms) windows: hourly from 2025-01-01, daily from 2023-03-21 (the default call returns only the latest ~730) | accepted |
| Mercado Bitcoin USDT-BRL | `mercadobitcoin.net/api`, `mobile.mercadobitcoin.com.br/v4` | HTTP 403 Cloudflare bot challenge | rejected: bot challenge, not evaded |
| Foxbit usdtbrl | `api.foxbit.com.br/rest/v3/markets/usdtbrl/candlesticks` | hourly and daily; daily from 2021-04-07 | accepted |
| BitoPro usdt_twd | `api.bitopro.com/v3/trading-history` | hourly and daily; daily from 2018-09-11 | accepted |
| MAX usdttwd | `max-api.maicoin.com/api/v2/k` | hourly and daily; daily from 2018-04-25 | accepted |
| Independent Reserve Usdt/Aud | `api.independentreserve.com/Public` | market summary and recent trades only, no candle or history endpoint (candle URLs 404). Building candles from trades would be derived | rejected: no history endpoint |
| Coins.ph USDTPHP | `api.pro.coins.ph/openapi/quote/v1/klines` | hourly and daily; daily from 2022-10-29 | accepted |
| BTC Markets USDT-AUD | `api.btcmarkets.net/v3/markets/USDT-AUD/candles` | hourly and daily; daily from 2020-12-01 | accepted |
| WazirX usdtinr | `api.wazirx.com/sapi/v1/klines` | hourly and daily; daily from 2018-07-10. Zero-volume candles (carried-forward prices during the 2024-07 to 2025-10 halt) are not stored: a candle with no trade is a gap | accepted |
| CoinDCX I-USDT_INR | `public.coindcx.com/market_data/candles` | hourly and daily; daily from 2019-02-05. Early (2019-2020) closes are illiquid and erratic; stored as reported, passed over by the segment emitter | accepted |
| Luno USDTNGN, USDTZAR | `api.luno.com/api/exchange/1/candles` | HTTP 401, candles need an API key | rejected: not public |
| Pintu usdt/idr | `api.pintu.co.id/v2/trade/price-changes` | latest price and percentage changes only; candle and chart routes 404 | rejected: no history endpoint |
| Coinbase | login-gated | never scraped | not collected |
| Taiwan official rate | Frankfurter v2 `providers=CBC` (Central Bank of the Republic of China (Taiwan), interbank spot closing, per 1 USD) | daily from 2017-12-29, published monthly; one central bank's own series, not Frankfurter's blended rate | accepted |
| Official rates | Frankfurter (`api.frankfurter.dev`, ECB reference rates) | daily per USD for KRW, TRY, IDR, THB, MXN, BRL, PHP, SGD, AUD, NZD, INR from 2017-12-29 | accepted |
| Parallel dollar, Argentina | ArgentinaDatos `api.argentinadatos.com/v1/cotizaciones/dolares/blue` | daily buy and sell from 2011-01-03; MIT licence | accepted |
| Parallel dollar, Argentina (second) | Bluelytics `api.bluelytics.com.ar/v2/evolution.json` | answers; code is AGPL-3.0, no data licence stated | rejected: licence unclear, and a second source would only duplicate |

**Gaps, stated.** No ECB series for ARS, NGN, VES (Taiwan uses its own central bank, above),
EGP or DZD; official-rate history there is a gap, not an estimate. No history for
any currency priced only through Binance P2P. Parallel-dollar series exist here for
Argentina only; no public series was found and accepted for the other street
markets this site tracks, so they have none. Coinone/Upbit/Bithumb depth is the
endpoints' own limit. Bithumb's daily bucket opens at 15:00 UTC (midnight Korea);
each row's `ts_utc` is the bucket's open exactly as the venue reports it.

**Spot check.** Rows picked at random from the files were matched to the venue's
own endpoint response, one fresh request per row; all matched exactly.

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
| Coinbase | 0.01% | 0.005% | 2026-08-19 |
| Bitso | 0.78% | 0.60% | 2026-08-19 |
| Luno | 0.10% | −0.01% (rebate, USDT/NGN & USDC/NGN specifically) | 2026-09-29 |
| WazirX | 0.40% | 0.40% (flat "Pay Per Trade", no maker/taker split) | 2026-09-29 |

All six are default/base tier: Independent Reserve 30-day volume < AUD 50k;
Coins.ph VIP0; Coinbase's USDT-USD stable pair is flat, not volume-tiered;
Bitso 30-day volume < MXN 20,000; Luno NGN 0–1,500,000 30-day volume; WazirX
0–500 WRX held and ≤ INR 5 lacs 30-day volume. Each row records the full fee
regime in force —
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
interpolated or back-filled. This is the live layer's rule and it has no
exception. History held in its own layer (next sections) never fills a live gap.
