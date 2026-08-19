# ROADMAP — margin.wiki

Written 2026-08-18. **This is the working source of truth.** Start every session
by reading it, and update it when something ships. It supersedes the build-order
section of `HANDOFF-v2.md` (items 1–7 are all done); HANDOFF is still worth
reading once for the *why* — the architecture split, the venue survey, and the
geo-block warnings, which have not changed.

## The sentence this is building toward

> "I built a live board of stablecoin capital-flow pressure across ~10 countries,
> with a fully audited cost decomposition of one corridor showing the
> 'stablecoins are cheap' narrative is a fee-tier story, running unattended
> since August."

Every session should make that sentence more true. It said "map" until
2026-08-18; the map was cut, so the sentence changed to match the thing that
actually exists rather than the other way round.

---

## Shipped

**Collection — two layers, deliberately independent.**

| | File | Scope | Since | Rows |
|---|---|---|---|---|
| Deep layer | `collector.py` | SGD→PHP, ladder S$200 / 1k / 5k / 25k / 50k, full fee-verified decomposition | 2026-08-10 | 770 |
| Wide layer | `collector_basis.py` | 10 venues, USDT vs official USD mid | 2026-08-10 | 1,519 |
| Panel | `collector.py` → `providers.csv` | every rail the Wise comparison API returns, per size | 2026-08-11 | 2,944 |
| Backfill | `tools/backfill_basis.py` | daily basis, 5 venues (TRY, KRW, IDR, THB, MXN) | 2024-03-02 → 2026-08-10 | 4,198 |

Venues live: Independent Reserve (SGD), Coins.ph (PHP), BTCTurk (TRY), Upbit
(KRW), Indodax (IDR), Bitkub (THB), Bitso (MXN), CriptoYa (ARS, VES, BRL).

**Scheduling.** `collect.yml` fires `17,47 * * * *`. Both collectors are
idempotent per UTC hour — the second fire is a no-op when the first landed and a
rescue when it didn't. Rot is caught by `tools/check_freshness.py` (3h limit),
not by "this run staged nothing", which is now a healthy outcome.

**Site.** Live at margin.wiki via GitHub Pages (`CNAME`, `.nojekyll`, React
vendored to `vendor/`, no external runtime deps). `index.html` is the basis &
corridor board, `corridor.html` the SGD→PHP detail, `methodology.html` renders
`METHODOLOGY.md` at runtime so it cannot drift.

**Fee verification.** IR 0.50% flat (no maker discount), Coins.ph Pro 0.15/0.10
VIP0, both verified 2026-08-10. The correction that killed the original
"maker beats Wise 3×" headline is documented in METHODOLOGY rather than quietly
removed.

---

## In flight

1. **Cadence verification** — waiting on a week of `:17`/`:47` data to confirm
   the drop rate actually fell. No action until then (see P0-1).

## Recently shipped — 2026-08-19

1. **Corridor 2 collection (USD→MXN) shipped 2026-08-19.** Coinbase on-ramp →
   Bitso off-ramp, same method and same fields as SGD→PHP, sampled hourly by
   `collect.yml`. Panel rows go to `data/providers_usdmxn.csv` (providers.csv
   has no corridor column and a frozen schema); the hourly idempotency gate is
   now per-corridor, so the two corridors never contend for an hour. Display is
   the next issue — no site changes. Issue #7.

## Recently shipped — 2026-08-18

1. **Site upgrade (A/B/C)** — `index.html`.
   - **A.** Provider leaderboard — whole fiat field at the selected size with the
     USDT route inserted into the ranking; size pills share state with the
     corridor pills.
   - **B.** Ten-market small-multiples grid above the hero; per-tile scale with a
     shared zero line (a uniform band cannot hold VES at +1,407 bps next to SGD
     at −9; the choice is stated on the page). Click loads a market into the hero.
   - **C.** Auto-conclusions — largest 7-day move, record check, corridor trend —
     each computed at render time and rendered only while its condition holds.
   - Also fixes two pre-existing mobile overflows (corridor x-tick labels; a
     missing `data-grid="split"`).
2. **Doc truth-up** — deleted `START_THE_CLOCK.md` (v1-era, described files and
   workflows that no longer exist) and `data/world.geo.json` (orphaned by the
   redesign). The map is **cut, not deferred**: HANDOFF's north-star sentence and
   METHODOLOGY's "the map's history line" heading now describe the board that
   exists. The ten-market grid shipped above covers the ground the map was for.

---

## Next, prioritised

### P0 — history is the only thing that cannot be rebuilt

1. **Confirm twice-hourly actually lifts delivery.** Measure over a full week.
   Baseline was 125 of 168 expected hours (~74%) with a single fire. If GitHub
   still drops *both* fires in an hour often enough to matter, escalate to an
   external trigger (`repository_dispatch` from a cheap always-on cron) rather
   than accepting the loss — a missing hour is gone permanently.
2. ~~**Put fee verification on a clock.**~~ **Shipped 2026-08-18.**
   `tools/check_fees.py` re-reads both published schedules, diffs the base tier
   against the `CORRIDORS` constants it imports from `collector.py`, and appends
   one row per checked value to `data/fee_checks.csv`. Any drift or unreadable
   page is a row *and* a non-zero exit — it never edits the constant, because a
   silently corrected fee is the failure mode the check exists to catch.
   `.github/workflows/fees.yml` runs it monthly (`23 3 1 * *`) and commits the
   evidence even when the run goes red. Both pages render the stamp from the
   CSV: "fees verified N days ago", or "fees UNVERIFIED — last clean check
   YYYY-MM-DD" when the latest run has any bad row, or nothing at all when the
   file is absent. First clean run 2026-08-18: IR 0.50% flat and Coins.ph VIP0
   0.15/0.10 both still match the 2026-08-10 hand verification. Issue #4.

### P1 — the demo

1. **The two write-ups** still open from the README:
   the taker/maker crossover, and why stablecoins are worst at remittance sizes
   (~156 bps at S$200). Both are now answerable from collected data rather than
   asserted — that was the point of waiting.

### P2 — debt and polish

1. **`README.md` Status is stale** — "One week of history" and "Front end" are
   both done; the run order still says the schedule is `:17`.
2. **Dead v1 code**: `corridor_monitor.py` and `corridor_monitor_v1_spec.md` are
   superseded by `collector.py`. Keep `data/offramp_snapshots.csv` — the 34-day
   silent-failure record is deliberate history.
3. **Intraday FX mids.** `open.er-api.com` is daily. Fine for TRY/ARS/VES at
   100+ bps, genuinely sloppy for SGD/THB/PHP, which are exactly the markets the
   corridor depends on. HANDOFF flagged this as a later upgrade; it is now the
   main precision ceiling on the corridor number.
4. **A second corridor** — explicitly *not yet*. HANDOFF: do not add one before
   the demo is polished.

---

## Invariants — do not regress these

- **Loud failure.** Non-zero exits on bad data; no green run on a rotting CSV.
  v1 died silently for 34 days; that is the failure mode everything is built
  against.
- **Persistence before display.** `append()` runs before any print. On
  2026-08-16 a `TypeError` in the waterfall header ran first and destroyed five
  samples. Display is decoration; the sample is the product.
- **One capture per UTC hour**, two fires. Duplicates are impossible by
  construction; do not "fix" a run that commits nothing.
- **Gaps stay gaps.** Failed pulls are written as rows with `source_ok=false` and
  the error string. Never interpolate, never backfill the live layer.
- **METHODOLOGY gates the site.** If a number is shown, METHODOLOGY says whether
  it is measured, assumed, or invisible. No hand-written copy on the site that
  can go stale against the data — compute it or condition it.
- **No Binance**, including P2P: 451 from US-hosted runners.
- **CriptoYa uses the median *bid*** — the broker ask carries retail markup
  (`fbac138`).
- **Every row carries its fee regime**, so history stays interpretable when a
  venue changes its schedule.

## Known-invisible (stated, never estimated)

Enterprise payout pricing (Nium/Thunes/Circle), OTC desks, local cash-out fees,
KYC/limits. Vietnam has no licensed spot USDT/VND book; Nigeria and India are
P2P-only — all out of scope by nature, not by omission.

## File map

```
collector.py            deep layer — SGD→PHP + USD→MXN decomposition + Wise panel
collector_basis.py      wide layer — 10-venue basis
tools/backfill_basis.py one-time daily history (not re-run)
tools/check_freshness.py rot guard for collect.yml
.github/workflows/collect.yml   the clock
index.html              basis & corridor board (site entry)
corridor.html           SGD→PHP detail
methodology.html        renders METHODOLOGY.md at runtime
support.js              the board's static runtime
data/samples.csv        corridor decomposition, hourly
data/basis.csv          10-venue basis, hourly
data/providers.csv      full incumbent panel, hourly (SGD→PHP)
data/providers_usdmxn.csv    full incumbent panel, hourly (USD→MXN)
data/basis_history.csv  daily backfill, 5 venues, 2024-03 →
data/offramp_snapshots.csv   v1 wreckage, kept as history
```
