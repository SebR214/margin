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
(ARS, VES — arriving with the aggregator source). Stated here so the map is
read correctly.

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
