# SGD→PHP Off-Ramp Depth Monitor — v1 Spec

**One-line pitch:** *the thing that shows what stablecoins actually cost once you force them to pesos — at real size, across venues, over time.*

## The reframe

We kept picking the tighter option (cost-only, one crypto route, defer speed, defer XSGD). Each was right locally; stacked, they reduce the product to "Wise's numbers + one crypto rail in a table" — a comparison chart, which is a commodity.

The fix is not more rails (wider is still a chart). It's going deep on the one number the industry keeps opaque: **the achievable PH off-ramp rate at size, per venue, over time.** The fiat rails stop being the point and become the baseline reference line everyone already knows.

## The proprietary core

Nobody publishes achievable PH off-ramp rates at size across venues, hourly, as a time series. That dataset is the product. Everything else is context around it.

The featured artifact: *"effective USDT→PHP off-ramp rate for ₱-equivalent of S$1k / S$5k / S$10k / S$25k through Coins.ph (and PDAX, P2P as they come online), sampled hourly, accumulating."*

## Scope

**In v1 (the star):** off-ramp leg, varied along two axes — **size** (a notional ladder) and **venue** — accumulated over **time**.

**In v1 (supporting, kept simple):**
- On-ramp (SG→USDT via Independent Reserve): relatively deep/clean; treated as a stable cost component, not a slippage story.
- Fiat rails (Wise comparison): a baseline reference line, not a focus. No effort spent widening it.
- Mid-market benchmark: cross-checked across ≥2 FX feeds.

**Deferred (v2+):** speed / time-to-land axis; XSGD as a second coin/route; additional corridors (SGD→IDR); Binance P2P; live public dashboard polish.

## Data model — two clocks, one irreversible

- **Off-ramp book snapshots — hourly (the asset).** Pull full depth per venue, walk the bids at each notional in the ladder, store the result. This history cannot be backfilled, so the schema must be right on day one and collection must start ASAP.
- **On-ramp book + mid-rate — hourly.** For the full round-trip cost number.
- **Provider markups (fiat) — daily.** Revolut-style: store each provider's markup% + fee schedule slowly; recompute effective cost against the live mid at read time. No need to re-scrape fiat hourly.

Snapshot schema (venue-generic so adding a venue never resets history):

```
ts, corridor, leg(off-ramp), venue, stable(USDT),
notional_src, notional_src_ccy(SGD),
top_of_book_rate, achievable_rate, avg_fill_rate,
slippage_bps_vs_top, depth_to_1pct_slippage,
book_levels_used, filled_fully(bool), source_ok(bool)
```

## Featured findings (what the monitor reveals)

- **Slippage-by-size curve:** how the achievable rate decays as notional grows on a thin book — the exact cost the "10-cent transfer" pitch hides.
- **Cross-venue best:** which venue gives the deepest achievable rate at each size (real, unpublished).
- **Crossover vs baseline:** the size at which the best crypto off-ramp stops beating the fiat reference line. Hypothesis: crypto wins OFW-size, loses SME-size. To be confirmed/refuted by real data — either is publishable.
- **Time series:** overnight/weekend book-thinning, when each rail actually wins — the thing only weeks of running can show ("didn't just spin it up for the interview").

## Venue access reality (honest)

- **Coins.ph** — clean public depth API. **Anchor v1 here; start the clock now.**
- **PDAX** — book is auth-gated/staging. Verify access before relying on it; add as venue #2 if it pans out.
- **Binance P2P** — not an order book; an ad-listing marketplace. "Achievable at size" = filtering ads by amount + payment method, plus counterparty friction. First expansion, not a v1 blocker.

## Why schema-first, and why now

History is the moat and it's irreversible. Priority order: (1) lock the snapshot schema, (2) get the Coins.ph collector running hourly and reliably, (3) let it accumulate, (4) build the viewer later. The frontend can wait; the collection clock cannot.

## v1 success criteria

- Collector runs hourly, unattended, appending clean snapshots for weeks with source-failure gaps recorded (not silently dropped).
- Size × venue × time surface is queryable from the accumulated data.
- One real-money calibration send confirms the achievable-rate math matches reality.
- Minimal viewer that renders the slippage-by-size curve and the time series (polish deferred).

## Open questions / risks

- Thin-book hypothesis is unproven — first real pull may show deeper PH books; story adjusts.
- PDAX public access unconfirmed.
- Coins.ph depth `limit` may cap visible levels below large notionals — check max depth returned.
- KYC/account limits mean "achievable" assumes a set-up user with both accounts; note as a caveat, not a blocker.
