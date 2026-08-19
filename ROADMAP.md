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
| Deep layer | `collector.py` | SGD→PHP, ladder S$200 / 1k / 5k / 25k / 50k, full fee-verified decomposition | 2026-08-10 | 875 |
| Deep layer | `collector.py` | USD→MXN, same ladder in USD, same method | 2026-08-19 | 10 |
| Wide layer | `collector_basis.py` | 10 venues, USDT vs official USD mid | 2026-08-10 | 1,729 |
| Panel | `collector.py` → `providers.csv` | every rail the Wise comparison API returns, per size (SGD→PHP) | 2026-08-11 | 3,427 |
| Panel | `collector.py` → `providers_usdmxn.csv` | same, USD→MXN | 2026-08-19 | 66 |
| Backfill | `tools/backfill_basis.py` | daily basis, 5 venues (TRY, KRW, IDR, THB, MXN) | 2024-03-02 → 2026-08-10 | 4,198 |

Venues live: Independent Reserve (SGD), Coins.ph (PHP), BTCTurk (TRY), Upbit
(KRW), Indodax (IDR), Bitkub (THB), Bitso (MXN), CriptoYa (ARS, VES, BRL).

**Scheduling.** `collect.yml` fires `17,47 * * * *`. Both collectors are
idempotent per UTC hour — the second fire is a no-op when the first landed and a
rescue when it didn't. Rot is caught by `tools/check_freshness.py` (3h limit),
not by "this run staged nothing", which is now a healthy outcome.

**Site.** Live at margin.wiki via GitHub Pages (`CNAME`, `.nojekyll`, React
vendored to `vendor/`, no external runtime deps). `index.html` is the basis &
corridor board, `corridor.html` the per-corridor detail (both corridors),
`methodology.html` renders
`METHODOLOGY.md` at runtime so it cannot drift.

**Fee verification.** Corridor 1: IR 0.50% flat (no maker discount), Coins.ph
Pro 0.15/0.10 VIP0, both verified 2026-08-10. Corridor 2: Bitso `usdt_mxn`
0.78/0.60 and Coinbase stable-pair 1.0/0.5 bps, both 2026-08-19. The correction
that killed the original "maker beats Wise 3×" headline is documented in
METHODOLOGY rather than quietly removed.

`tools/check_fees.py` re-checks all four monthly. Three are read from a
published source; **Coinbase is login-gated and is never scraped** — its manual
verification is on a 90-day clock instead, and goes `stale` (red) past it.

---

## In flight

Nothing is being built right now. All four standing-plan items are gated and
none of the gates has cleared:

| # | Item | Waiting on |
|---|---|---|
| 1 | Crossover toggle | sourced IR + Coins.ph tier tables, and its spec issue |
| 2 | Front-end rebuild | design final pass + design source on the issue |
| 3 | EU corridor | venue verification (product agent, via the browser) |
| 4 | Time layer | ~60 days of hourly data — October |

Also open: **#16** route-engine render half, held until a corridor has ≥2 real
paths (needs a public Coins.ph free-USDT-deposit statement, or Coinbase's
per-network withdrawal fees entered by hand).

## Recently shipped — 2026-08-19

All five merged the same day. SHAs are the squashed merge commits on `main`.

1. **Corridor 2 collection — USD→MXN** (`3127140`, PR #9, issue #7). Coinbase
   on-ramp → Bitso off-ramp, same method and same fields as SGD→PHP, sampled
   hourly by `collect.yml`. Panel rows go to `data/providers_usdmxn.csv`
   (`providers.csv` has no corridor column and a frozen schema); the hourly
   idempotency gate is now per-corridor, so the two corridors never contend for
   an hour. Fees verified 2026-08-19: Coinbase stable-pair 1.0/0.5 bps (manual,
   login-gated), Bitso `usdt_mxn` 78/60 bps from Bitso's own API.
2. **Machine-readable snapshot** (`0f817d7`, PR #10, issue #8).
   `tools/emit_latest.py` (stdlib only) regenerates `data/latest.json` every
   collector run: latest basis per venue, latest ladder per corridor, best/worst
   panel provider per size, source CSV paths. Derived, never authoritative — a
   missing or empty CSV yields an absent key, never a placeholder, and bad rows
   are skipped rather than fatal. `as_of_utc` is the newest **source** row, not
   the wall clock, so an unchanged dataset regenerates a byte-identical file —
   which is what keeps the commit step's "nothing staged" branch reachable and
   `check_freshness.py` running. That guard now runs on every fire, last, so a
   stale-data failure is loud without costing an already-written sample.
3. **Mexico on the site** (`2a808e2`, PR #11). Both corridors render, grouped by
   the `corridor` column, with corridor pills on `index.html` and
   `corridor.html` defaulting to SGD→PHP; corridor 2's panel reads
   `providers_usdmxn.csv`, corridor 1 keeps `providers.csv`. Fixed a live bug:
   both pages read `samples.csv` unfiltered, so from #9 landing until this
   merged, USD→MXN rows were spliced into the SGD→PHP cost series and the
   heading followed whichever row was written last. Also stopped clamping the
   y-scale at zero — four real SGD→PHP readings (min −1.59 bps) and Xoom's
   −114 bps were being drawn off-canvas. **Drawing a real measurement off
   canvas is the same failure as filling a gap**; see Invariants.
4. **Bitso in the fee watcher** (`3c2d823`, PR #12). `tools/check_fees.py` diffs
   `usdt_mxn` against `fees.flat_rate` from Bitso's `available_books` API — a
   published number, so no parser to rot. Coinbase's stable-pair schedule is
   login-gated and is **not** scraped: its *manual* verification runs on a
   90-day clock (`status=stale` and a non-zero exit past it), with
   `published_bps` left empty rather than echoing the config back as if
   confirmed. First run 2026-08-19: 8 checks, all ok.
5. **Promotional-pricing honesty** (`03414e1`, PR #15). METHODOLOGY gains a
   *Promotional pricing* section: comparison-API quotes can carry promo pricing,
   the panel records them exactly as received, and the baseline is therefore the
   best *advertised* price, not necessarily the best *recurring* one. Prompted by
   Xoom quoting −114.0 bps at USD 200 and −114.7 at USD 1,000 on USD→MXN while
   quoting +48.1 at USD 5,000. Both corridor pages' small print now names promo
   rates. No data changes, no flag columns, no filtering.

6. **Withdrawal-fee record** (`0df09d1`, PR #18 — route engine, data half). `data/withdrawal_fees.csv`
   is an append-only log of USDT withdrawal fees per venue per network, from
   primary sources only: Bitso and Independent Reserve read from their published
   pages, Coinbase `source_ok=False` because the schedule is login-gated —
   **pending manual entry**. `tools/check_fees.py` re-reads both pages monthly
   and appends what it observed, in its OWN file with honest columns (a flat
   chain fee in USDT is not a rate in bps). It goes red when a published fee
   EXCEEDS every value recorded before it — Bitso's Ethereum fee is gas-linked
   and moves between reads, so the record is a ceiling rather than a point.
   The render half is held on `route-engine-v1` until a corridor has ≥2 real
   paths: SGD→PHP needs a public Coins.ph free-USDT-deposit statement, USD→MXN
   needs Coinbase's per-network withdrawal fees.

7. **Network-fee corrections, both corridors** (`bdef58a` PR #17, `d8a718e`
   PR #19). Two live wrong numbers on the same line. SGD→PHP carried an
   unsourced flat 1.0 USDT: IR publishes **4.0** on Tron, so the corridor was
   understated by ~191 bps at S$200. USD→MXN carried the same 1.0 copied
   across — on **Tron, which Coinbase does not support for USDT at all**. It
   now models **Polygon** and Coinbase's published **0.01% of amount, capped
   20 USDT**; being proportional that is 1 bp at every size, where the old
   constant read 50 bps at USD 200. `decompose()` models both fee shapes and
   writes the effective per-size cost to the existing `network_fee_stable`
   column, so samples.csv keeps its schema. Also: the fee stamp read
   `Date.now()` and printed "fees verified today"; both pages now print the
   date from the fee config, taking the **oldest leg**. Confirmed in the data
   at 2026-08-19T10:47Z.
   *Not modelled:* Coinbase's separate gas fee, never published — left at zero
   rather than invented, and the one term on the site that understates.

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

**The standing plan, committed 2026-08-19.** Four items, in this order. Each
carries its gate; an item does not start until its gate clears, and the gate is
part of the item rather than a caveat on it.

### 1. Crossover toggle — NOW, gated on sourced tier tables

Show at which size and fee tier the USDT route overtakes the best fiat rail.

- **New** `data/fee_tiers.csv`, one row per venue per published tier, header:
  `ts_utc,venue,tier_name,maker_bps,taker_bps,min_volume_usd,source_url,source_ok`
- **Compute** reuses the existing corridor decomposition with the fee legs
  swapped per tier. It does not fork the math.
- **Crossover** = the smallest ladder size where USDT all-in beats the best fiat
  rail *at that size*. Where it never does, the honest answer is
  "no crossover on the ladder" — **no interpolation between ladder points**, and
  no invented tiers.
- **GATE:** the IR and Coins.ph tier tables, read from their live pages. Do not
  start until the sourced numbers arrive. **No tier figure from memory, and none
  from any third-party summary.** The full spec arrives as its own issue.

### 2. Front-end rebuild — parallel, gated on the design source

Full spec exists. Rule one: **no hardcoded number anywhere** — every figure
computes from the CSVs and carries its as-of date, or it does not appear.

- **GATE:** ships once the design's final pass lands *and* the design source
  (exported markup or screenshots) is attached to the issue.
- Merge is gated on Sebastian's screenshot approval. The red `review` check
  stays ignored per the standing rule (known upstream crash in
  `anthropics/claude-code-action`; it has failed on every branch since
  2026-08-12 and kills both auth methods — do not spend time on it and do not
  touch a credential over it).

### 3. EU corridor — next, BLOCKED ON VENUE VERIFICATION

A EUR on-ramp venue with a readable book and hand-verified fees, verified
**through the browser before any spec exists**.

- **Verification is the product agent's job.** Do not research venues and do not
  draft a collector. This item is blocked until verified venue facts arrive.

### 4. Time layer — October, calendar-gated

Basis by hour of day; weekend versus weekday on hourly data; the cheapest hour
to move the corridor. Each lands as its own **dated Findings entry**.

- **GATE:** the hourly layer reaching ~60 days. Hourly collection began
  2026-08-10, so this is an October item. **Nothing to build now** — this is a
  ROADMAP note, not a backlog ticket.

---

## Carried over, not in the standing plan

Still true, still unscheduled. These do not compete with the four above.

1. **Confirm twice-hourly actually lifts delivery.** Measure over a full week.
   Baseline was 125 of 168 expected hours (~74%) with a single fire. If GitHub
   still drops *both* fires in an hour often enough to matter, escalate to an
   external trigger (`repository_dispatch` from a cheap always-on cron) rather
   than accepting the loss — a missing hour is gone permanently. Live evidence:
   the 2026-08-19 10:17Z fire dropped and 10:47Z landed, which is the redundancy
   working as designed.
2. **The remittance-size write-up.** Why the stablecoin route is worst at small
   sizes. Now materially better evidenced — see the held finding below.
3. **`README.md` Status is stale** — "One week of history" and "Front end" are
   both done; the run order still says the schedule is `:17`.
4. **Dead v1 code**: `corridor_monitor.py` and `corridor_monitor_v1_spec.md` are
   superseded by `collector.py`. Keep `data/offramp_snapshots.csv` — the 34-day
   silent-failure record is deliberate history.
5. **Intraday FX mids.** `open.er-api.com` is daily. Fine for TRY/ARS/VES at
   100+ bps, genuinely sloppy for SGD/THB/PHP, which are exactly the markets the
   corridor depends on. It is now the main precision ceiling on the corridor
   number.

## Held findings — evidenced, deliberately unpublished

1. **Flat versus proportional network fees.** The stablecoin route is worst at
   remittance size on SGD→PHP because Independent Reserve's withdrawal fee is
   **flat per send** (4.0 USDT — 255 bps at S$200, 1 bp at S$50,000), while
   USD→MXN stays even across the whole ladder because Coinbase's is
   **proportional** (0.01% of amount, capped 20 USDT — exactly 1 bp at every
   size). First run under both corrected fees: **2026-08-19T10:47Z**
   (`ad57f4d`), where SGD→PHP falls 314 → 71 bps across the ladder while
   USD→MXN sits flat at ~103.5 throughout.
   **Do not write this up yet** — it needs a few days of clean rows collected
   under the corrected fees. Every row before 2026-08-19T10:47Z carries a fee
   regime that was never charged.

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
tools/check_freshness.py rot guard, runs every fire of collect.yml
.github/workflows/collect.yml   the clock
index.html              basis & corridor board (site entry)
corridor.html           corridor detail, both corridors (switcher)
methodology.html        renders METHODOLOGY.md at runtime
support.js              the board's static runtime
data/samples.csv        corridor decomposition, hourly
data/basis.csv          10-venue basis, hourly
data/providers.csv      full incumbent panel, hourly (SGD→PHP)
data/providers_usdmxn.csv    full incumbent panel, hourly (USD→MXN)
data/basis_history.csv  daily backfill, 5 venues, 2024-03 →
data/offramp_snapshots.csv   v1 wreckage, kept as history
data/latest.json        machine-readable snapshot, regenerated each run
data/withdrawal_fees.csv USDT withdrawal fee per venue/network, append-only
tools/seed_withdrawal_fees.py   one-time seed for withdrawal_fees.csv
tools/emit_latest.py    builds latest.json from the CSVs
```
