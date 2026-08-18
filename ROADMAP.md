# ROADMAP — margin.wiki

Written 2026-08-18. **This is the working source of truth.** Start every session
by reading it, and update it when something ships. It supersedes the build-order
section of `HANDOFF-v2.md` (items 1–7 are all done); HANDOFF is still worth
reading once for the *why* — the architecture split, the venue survey, and the
geo-block warnings, which have not changed.

## The sentence this is building toward

> "I built a live map of stablecoin capital-flow pressure across ~10 countries,
> with a fully audited cost decomposition of one corridor showing the
> 'stablecoins are cheap' narrative is a fee-tier story, running unattended
> since August."

Every session should make that sentence more true. Note the tension flagged in
**P1-1** below: the word "map" is currently not honest.

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

1. **Site upgrade (A/B/C)** — built and verified locally, **not pushed**,
   awaiting approval. `index.html` only, +263/−13.
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
2. **Cadence verification** — a watcher reports the natural `:17`/`:47` pair for
   hour 08 on 2026-08-18. Expect one capture, two green runs.

---

## Next, prioritised

### P0 — history is the only thing that cannot be rebuilt

1. **Confirm twice-hourly actually lifts delivery.** Measure over a full week.
   Baseline was 125 of 168 expected hours (~74%) with a single fire. If GitHub
   still drops *both* fires in an hour often enough to matter, escalate to an
   external trigger (`repository_dispatch` from a cheap always-on cron) rather
   than accepting the loss — a missing hour is gone permanently.
2. **Put fee verification on a clock.** Fees are the largest single term in the
   taker decomposition and the easiest thing to get silently wrong. They were
   verified once, on 2026-08-10, and nothing re-checks them. Needs a scheduled
   re-verification and a "verified N days ago" staleness indicator on the site,
   so a stale fee schedule is visible the way a stale sample already is.

### P1 — the demo

1. **Resolve the map.** HANDOFF calls the world map the centerpiece and "the
   wow". It shipped (`b7b50c3`) and was then replaced by the 2026-08-12 redesign
   (`5cfb6fc`). Today `data/world.geo.json` is an orphan — nothing in the repo
   references it — and METHODOLOGY still has a section titled "Historical basis
   (the map's history line)". Decide explicitly: bring the map back as a section
   or page, or cut it and fix the METHODOLOGY heading and the north-star sentence
   above. The in-flight small-multiples grid covers some of the same ground and
   may make the map redundant; what is not acceptable is the current state, where
   the docs promise something the site does not have.
2. **The two write-ups** still open from the README:
   the taker/maker crossover, and why stablecoins are worst at remittance sizes
   (~156 bps at S$200). Both are now answerable from collected data rather than
   asserted — that was the point of waiting.

### P2 — debt and polish

1. **`README.md` Status is stale** — "One week of history" and "Front end" are
   both done; the run order still says the schedule is `:17`.
2. **`START_THE_CLOCK.md` is v1-era fiction** — it references
   `corridor_monitor.py`, a `collect-offramp-depth` workflow, and
   `data/offramp_snapshots.csv` as the live target. None of that is current.
   Delete it or rewrite it as a short "how to run locally".
3. **Dead v1 code**: `corridor_monitor.py` and `corridor_monitor_v1_spec.md` are
   superseded by `collector.py`. Keep `data/offramp_snapshots.csv` — the 34-day
   silent-failure record is deliberate history.
4. **Intraday FX mids.** `open.er-api.com` is daily. Fine for TRY/ARS/VES at
   100+ bps, genuinely sloppy for SGD/THB/PHP, which are exactly the markets the
   corridor depends on. HANDOFF flagged this as a later upgrade; it is now the
   main precision ceiling on the corridor number.
5. **A second corridor** — explicitly *not yet*. HANDOFF: do not add one before
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
collector.py            deep layer — SGD→PHP decomposition + Wise panel
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
data/providers.csv      full incumbent panel, hourly
data/basis_history.csv  daily backfill, 5 venues, 2024-03 →
data/offramp_snapshots.csv   v1 wreckage, kept as history
data/world.geo.json     ORPHAN — see P1-1
```
