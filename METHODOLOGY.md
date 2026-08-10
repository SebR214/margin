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
| Exchange taker fees | venue published schedules | published, verified 2026-08-10 |
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
- **Maker** — posts a resting order and waits, modelled at zero trading fee.

The maker figure is an **upper bound on the benefit**. It assumes a fill at
posted top-of-book and ignores fill risk, queue position, and the time the money
spends unhedged. It is also optimistic on fees: Coins.ph Pro's published VIP0
maker fee is 0.10% (not zero), and Independent Reserve publishes a flat
brokerage fee with **no maker discount at all** — a posted order there still
pays 0.50% at the default tier. Treat the maker line as "what execution is
worth if you get it", not as an achievable price. Everything between the two
lines is execution quality.

## The decomposition

The headline claim of this site is that the cost sits at the doors, not on the
rail. That is arithmetic, and it reconciles:

```
on-ramp basis    stable vs USD mid at the source venue   (can be negative — a gain)
on-ramp fee      published taker fee
network fee      flat, so it scales inversely with size
off-ramp basis   stable vs USD mid at the destination venue
off-ramp fee     published taker fee
─────────────────────────────────────────────────────────
= all-in cost in bps below mid-market
```

"Basis" is peg deviation expressed as a cost. It is a **market price, not a
fee** — it moves hourly, and its sign depends on which way money wants to flow
through that venue. This is the term nobody publishes and the reason this site
collects rather than calculates on demand.

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

| Venue | Taker used | Verified against published schedule |
|---|---|---|
| Independent Reserve | 0.50% (default tier, 30-day volume < AUD 50k) | 2026-08-10 |
| Coins.ph Pro | 0.15% (VIP0, schedule effective 2025-08-08) | 2026-08-10 |

Rows written before 2026-08-10 used an assumed 0.25% Coins.ph taker fee — the
`fee_off_taker_bps` column on each row records what was in force. The verified
schedule is 10 bps cheaper, which moved the reference taker figure from ~94.8
to ~84.6 bps at S$5,000 (still losing to the fiat baseline at ~66 bps).

## Data integrity

- Failed pulls are written as rows with `source_ok=false` and the error string,
  never dropped. A gap in the history is visible as a gap.
- The collector exits non-zero on an incomplete sample so the scheduler goes red.
  An earlier version of this project failed silently for 34 days because nothing
  ever alerted; that is the failure mode this is designed against.
- Raw samples are public: `data/samples.csv`.
