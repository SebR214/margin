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
| Network withdrawal fee | 1 USDT, TRC20, flat | assumed |

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

## Historical basis (the map's history line)

`data/basis_history.csv` is a one-time backfill (`tools/backfill_basis.py`, not
part of the hourly collector) so the map shows years on day one. One row per
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
- Raw samples are public: `data/samples.csv`.
