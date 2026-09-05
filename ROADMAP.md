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
| Wide layer | `collector_basis.py` | 16 venues + per-exchange expansion of the ARS/VES feeds (~41 rows/hour), USDT vs official USD mid | 2026-08-10 | 3,669 |
| Panel | `collector.py` → `providers.csv` | every rail the Wise comparison API returns, per size (SGD→PHP) | 2026-08-11 | 3,427 |
| Panel | `collector.py` → `providers_usdmxn.csv` | same, USD→MXN | 2026-08-19 | 66 |
| Backfill | `tools/backfill_basis.py` | daily basis, 5 venues (TRY, KRW, IDR, THB, MXN) | 2024-03-02 → 2026-08-10 | 4,198 |

Venues live: Independent Reserve (SGD), Coins.ph (PHP), BTCTurk + Paribu (TRY),
Upbit + Bithumb + Coinone (KRW), Indodax + Pintu (IDR), Bitkub (THB), Bitso
(MXN), Foxbit + Mercado Bitcoin (BRL), CriptoYa (ARS, VES, BRL) with ARS and VES
also expanded to one row per listed exchange. **Five countries now have a median
across two or more exchanges; SGD, PHP, THB and MXN still have one each and the
site says so** — see METHODOLOGY, "More than one exchange per country".

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

1. **Cadence verification** — waiting on a week of `:17`/`:47` data to confirm
   the drop rate actually fell. No action until then (see P0-1).

## Robot

**Status 2026-09-02: `@claude` in CI is dead, and neither cause is fixable from
inside the repo.** Both need Sebastian.

Every `claude.yml` run since 2026-08-18 has failed the same way. Reference run
`33599792947`. Everything up to the model call succeeds — trigger detected, OIDC
and app token obtained, branch created, prompt assembled, Claude Code v2.1.258
installed — and then:

```
{"type":"system","subtype":"init","model":"claude-opus-5[1m]"}
{"type":"result","subtype":"success","is_error":true,"duration_ms":346,
 "num_turns":1,"total_cost_usd":0,"modelUsage":{}}
##[error]Claude result reported subtype success with is_error:true
```

No error text, because `anthropics/claude-code-action` runs the SDK with output
hidden. Running `claude -p` directly on a runner with the same secrets, with
`--output-format json`, prints the text the wrapper swallows:

**`ANTHROPIC_API_KEY`** — the key authenticates (`GET /v1/models` returns 200 and
lists twelve models, `claude-opus-5` and `claude-sonnet-5` among them) but has no
money behind it:

```
POST /v1/messages ->
{"type":"error","error":{"type":"invalid_request_error",
 "message":"Your credit balance is too low to access the Anthropic API.
            Please go to Plans & Billing to upgrade or purchase credits."}}

claude -p ... -> "api_error_status":400, "result":"Credit balance is too low",
                 "is_error":true, "num_turns":1, "total_cost_usd":0
```

**`CLAUDE_CODE_OAUTH_TOKEN`** — the alternate auth path, set 2026-08-18, is
malformed. The secret was pasted with a newline in the middle of it:

```
claude -p ... -> "result":"Invalid auth token · Fix external auth token ·
                  Invalid Authorization header value from CLAUDE_CODE_OAUTH_TOKEN:
                  it contains a line break at character 80
                  (110 characters on 2 lines)."
```

So all three escalation steps that were planned for this — pin a model, pin the
action to a release tag, bypass the Bun wrapper and call `claude -p` directly —
would have failed identically, because none of them touches the cause. The model
id was never the problem; `claude-opus-5` is on the key's list. The wrapper was
never the problem either, though bypassing it is what made the error legible,
which is the one thing worth keeping from the exercise.

**Two fixes, both Sebastian's, either one is sufficient:**

1. Add credit at console.anthropic.com → Plans & Billing. The existing key then
   works with no repo change.
2. Re-add `CLAUDE_CODE_OAUTH_TOKEN` as a single line with no trailing newline
   (`gh secret set CLAUDE_CODE_OAUTH_TOKEN --body "$(claude setup-token | tr -d '\n')"`),
   then swap `anthropic_api_key:` for `claude_code_oauth_token:` in both
   workflows. This bills the Claude subscription instead of API credits.

Until one of those happens, `@claude` on an issue does nothing, and the fallback
below is the path.

### Fallback: the `queue` label

Filing an issue is still enough. Label it `queue`. Then, on the Mac, in the repo:

```
claude "work every open issue labelled queue, one PR each"
```

Claude reads them with `gh issue list --label queue --state open` and
`gh issue view <n>`, and opens one PR per issue with `gh pr create`. Sebastian
never copies an issue body into a chat window; the label is the handoff. The
`queue` label exists on the repo as of 2026-09-02.

This is a worse robot than CI — it runs when he runs it, not when the issue is
filed — but it has no API-credit dependency and no wrapper between the issue and
the work.

---

## Recently shipped — 2026-09-02

Six merged the same day. Delivery of the whole 2026-09-02 brief except task 4,
which waits on approval, and task 6, which has not started by design.

1. **Robot post-mortem and the `queue` fallback** (PR #24, task 0). `@claude` in
   CI has been dead since 2026-08-18 for two reasons, neither fixable from
   inside the repo: the API key authenticates but has **no credit**, and the
   `CLAUDE_CODE_OAUTH_TOKEN` secret contains a **line break**. Both errors,
   verbatim, are under **Robot** above, along with the two fixes — both
   Sebastian's. The fallback ships either way: label an issue `queue`, and
   `claude "work every open issue labelled queue, one PR each"` works the lot.
2. **External trigger for `collect.yml`** (PR #25, issue #23, task 1).
   `repository_dispatch` `types: [collect]` is primary, GitHub's cron is the
   fallback, and `tools/check_delivery.py` measures what actually arrives.
   Verified live: a dispatch produced run `33613358354`, event
   `repository_dispatch`, green, `sample 2026-09-02T09:18Z`. **The external cron
   itself still needs Sebastian's token** — config in the PR.
3. **More than one exchange per country** (PR #26, task 2). Six new venues, each
   called from a US runner first; ARS and VES expanded to one row per exchange.
   Five countries now carry a median with the spread beside it. First production
   run with all of them: `41/41 venues ok`, and
   `markets: 10 currencies, 5 with 2+ venues this hour`.
4. **Implied crosses** (PR #27, task 3). `data/crosses_latest.json`, 45 pairs,
   both legs from the same hour or no pair at all, plus a plain-words table on
   the site. Market prices only — no fees — and the page says so.
5. **USDT vs USDC** (PR #29, task 5). `data/stable_spread.csv`, 12 of 13 venues
   quoting both, same run and same mid as the basis row. Nothing renders for
   seven days. First production run: `12/12 venues quote both`.
6. **`git add` on an unwritten file** (PR #30). Adding `stable_spread.csv` to
   the commit step turned a healthy no-op run red — exit 128, killing the step
   before the freshness guard. Files are staged behind `[ -f ]` now. Recorded
   because it is the invariant inverted: a layer that has not written its first
   row took down the guard that exists to make real rot loud.

**Open:** PR #28, plain language across the site (task 4), waiting on approval.

---

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

6. **Withdrawal-fee record** (route engine, data half). `data/withdrawal_fees.csv`
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

1. ~~**Confirm twice-hourly actually lifts delivery.**~~ **Escalated
   2026-09-02.** It did not. Twice-hourly held ~21 of 24 hours a day through
   Aug 25, then GitHub's scheduler collapsed: **Aug 26: 17. Aug 27: 2. Aug 28:
   3. Aug 29: 6. Aug 30: 6. Aug 31: 4. Sep 1: 7.** Holes of five to eight hours
   became routine, and nothing went red — the runs that *did* fire were green
   and landed data, and `check_freshness.py` cannot see a fire that never
   happened. Measured by the new `tools/check_delivery.py`, which counts
   distinct UTC hours per day in `data/basis.csv` and always exits 0; it is a
   measurement, not a guard.

   **The workflow now keeps itself running.** No cron, no personal access
   token, no external service, nothing outside GitHub. Every run of
   `collect.yml` ends by sleeping until the next :05 or :35 UTC and dispatching
   the next run with the built-in `GITHUB_TOKEN`. That is possible because of
   one documented exception — GitHub, *Triggering a workflow from a workflow*:

   > When you use the repository's `GITHUB_TOKEN` to perform tasks, events
   > triggered by the `GITHUB_TOKEN` will not create a new workflow run, with
   > the following exceptions: `workflow_dispatch` and `repository_dispatch`
   > events always create workflow runs.

   The `17,47` schedule stays, demoted from clock to **restarter**. A scheduled
   fire first asks "Am I needed": if any run of this workflow is already
   in progress or queued it prints `chain alive, run <id>` and stops before
   checkout; otherwise it prints `chain dead, restarting` and collects
   normally, forging a new first link. Dispatched runs — from the chain or from
   a person — always proceed. The concurrency group is gone, because it would
   queue a restarter behind a running link for up to half an hour, which is the
   opposite of what a restarter is for; overlap is free anyway, since the
   collectors are idempotent per UTC hour.

   The chain is self-healing in both directions: the dispatch step runs under
   `always()`, so one bad hour cannot end the chain, and a *failed* dispatch
   exits non-zero, so the run goes red and the next scheduled fire finds no
   link alive and restarts.

   **Incident, 2026-09-05: 41 concurrent runs.** Sebastian rebooted his Mac.
   macOS auto-loads `~/Library/LaunchAgents/*.plist` at login, so the launchd
   agent that had been unloaded on 2026-09-02 came back and resumed POSTing
   `repository_dispatch` twice an hour. Every one of those runs dispatched a
   successor, and **a chain never dies**, so each stray dispatch became a
   permanent second chain. They all sleep to the same :05/:35 slots, so they
   converged and fired in clumps: 20 in progress and 21 queued before it was
   caught. No data was harmed — the per-hour idempotency gate meant exactly one
   capture an hour throughout, and the extra runs staged nothing.

   Two fixes, and the second is the one that matters:

   1. The agent is now `launchctl disable`d for the user, which **survives a
      reboot**, rather than merely unloaded. The three files stay on disk as
      documented. Re-enable with
      `launchctl enable gui/$UID/wiki.margin.collect && launchctl bootstrap gui/$UID ~/Library/LaunchAgents/wiki.margin.collect.plist`.
   2. **Only a chain link forges the next link.** `workflow_dispatch` takes a
      `chain` input; the successor is dispatched with `-f chain=true`, and the
      dispatch step only runs for a scheduled fire or a run carrying that flag.
      Anything else — a `repository_dispatch`, a bare `gh workflow run` —
      collects its hour and stops. One-shot, useful, harmless. **The repo no
      longer depends on the state of a laptop to stay single-threaded.**

   A second, quieter bug came out of the same incident. The gate detected a
   live chain by listing the **newest 50 runs** and filtering them. A chain link
   sleeps for up to 30 minutes, so under any burst it falls out of that window
   and the gate concludes "chain dead" — then starts another chain. A scheduled
   fire at 2026-09-05 00:58 did exactly that with ~20 chains running, so the
   restarter was adding to the pile it existed to prevent. The gate now asks
   GitHub by **status** (`runs?status=in_progress`, `runs?status=queued`), which
   has no window and cannot drift.

   Not done by counting live runs and letting the oldest win: parent and
   successor overlap by seconds at handover, so that rule races and can kill
   the chain it is meant to protect.

   **One bug worth keeping on the record**, because it is the shape of failure
   this design is most exposed to. The gate calls `gh run list` before
   checkout, and `gh` infers the repository from the git remote — which does
   not exist yet at that point. Every scheduled fire failed with "failed to
   determine base repo" from the moment it merged until `GH_REPO` was added.
   Dispatched runs never reach that line, so **the chain kept running and only
   the restarter was broken**: collection looked perfectly healthy, and the
   safety net would only have been missed at the exact moment it was needed.
   A red scheduled run is now the signal to check that first. `timeout-minutes` is 45 to cover a 30-minute sleep
   either side of a full collection.

   Follow-up: re-measure hourly delivery after 7 days of self-chaining. Target
   23 of 24 or better. Every dropped hour is gone permanently.

   **Sebastian: retire the laptop stopgap.** The launchd agent from earlier
   today is now redundant and would double-trigger:

   ```
   launchctl unload ~/Library/LaunchAgents/wiki.margin.collect.plist
   ```
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

### P0.4 — P2P layer, collecting since 2026-09-02

1. **Ten capital-controlled currencies now have an hourly price**, from
   `collector_p2p.py` into `data/p2p_basis.csv`: NGN, EGP, PKR, BDT, VND, KES,
   GHS, BOB, LBP, ETB. These have no licensed spot USDT book to read, which is
   why they were "known-invisible" until now — an advertisement board is what
   these markets have instead.

   **Both sources were called from a US runner before anything was written.**

   - **Bybit P2P: blocked, not used.** `api.bybit.com` returns
     `403 "The Amazon CloudFront distribution is configured to block access
     from your country"`; `api2.bybit.com` and `www.bybit.com` time out behind
     the same block (curl exit 28). No workaround was attempted and none will
     be — proxying around a geo-block would make the source a lie.
   - **Binance P2P: answers.** `p2p.binance.com/bapi/c2c/v2/friendly/c2c/adv/search`
     returns 200 for all ten currencies. So the layer has one source, and every
     row says so in its `source` column.

   **Seven of ten currencies have a market.** NGN, GHS and ETB return an empty
   board — zero ads either side at any size. That is a finding about those
   markets, not a gap in the collector, and it is written as a row with
   `source_ok=False` and the reason, every hour, rather than omitted.

   First live reading, 2026-09-02 15:03Z, against the official rate:

   ```
   EGP  +132 bps    PKR  +276 bps    BDT  +366 bps    BOB  +322 bps
   KES   +11 bps    VND   -76 bps    LBP   -51 bps
   NGN / GHS / ETB  no ads
   ```

   **Method.** Top 10 ads each side, filtered to an amount worth about USD 500
   so the number is a price a person could actually transact at rather than the
   thin best ad on the board; the median of each side is stored, and the mid is
   their midpoint. A mid needs BOTH sides — one side alone is an asking price,
   not a market — so a currency with only one side is a failed row.

   **A P2P ad is not an order-book quote** and never gets merged into
   `basis.csv`. It is a price someone is asking, with counterparty risk, a
   payment-rail requirement and a settlement window, and nothing guarantees a
   fill. Own collector, own file, own key in `latest.json`.

   **No site work until seven days of rows exist.** Nothing renders before
   then. Re-read this section before building anything on it.

### P0.5 — consequence of the multi-venue change

1. **`data/basis.csv` now grows ~4x faster.** One row per venue per hour went
   from 10 to ~41, almost all of it the Argentine per-exchange expansion (24
   rows an hour on its own). At that rate the file adds roughly 1.5 MB a month,
   and `index.html` downloads the whole thing on every page load. This was
   accepted knowingly, not overlooked: Argentina has no direct venue at all, so
   the expansion is the only way it gets a median rather than one feed's
   average. Revisit when the file passes ~5 MB — the fix is a rolling window
   for the live layer with the tail rolled into `basis_history.csv`, not
   dropping venues.

### P1 — the demo

0. **USDT/USDC spread: wait for seven days of rows, then decide.** Collecting
   since 2026-09-02 into `data/stable_spread.csv`, 12 venues. Nothing renders
   until 7 days exist — a few bps between two stablecoins is inside one hour's
   noise, and a week is the minimum that tells a spread from a print. First
   live reading spanned −11.3 bps (Indodax) to +9.3 bps (Independent Reserve),
   which is wide enough to be worth the wait and too thin to publish off one
   sample.


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
4. ~~**A second corridor** — explicitly *not yet*.~~ **Done 2026-08-19**
   (`3127140`) — USD→MXN collects hourly and renders on the site. HANDOFF's
   "not before the demo is polished" is superseded: the demo shipped
   2026-08-18, and the second corridor is what makes the method read as a
   method rather than one lucky pair.

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
- **The front page speaks money and percent.** No bps, basis, on-ramp, off-ramp,
  notional, taker, maker, corridor, mid or USDT in anything a reader sees on
  `index.html` — those words live in `methodology.html` only. Country names, not
  exchange names, at the top level; exchange names belong in the hover. Every
  cost figure is shown as money first and the percentage second, because nobody
  sends "0.61%". The "nothing is filled in" reassurance appears once, in the
  small print, not five times.
- **METHODOLOGY gates the site.** If a number is shown, METHODOLOGY says whether
  it is measured, assumed, or invisible. No hand-written copy on the site that
  can go stale against the data — compute it or condition it.
- **No Binance SPOT**: `api.binance.com` returns 451 from US-hosted runners,
  "restricted location", re-confirmed 2026-09-02, as do `binance.th` for
  USDT/THB (no such book) and `trbinance.com`. **The P2P search endpoint is a
  different story and the old wording was wrong**: `p2p.binance.com` answers
  200 from the same runners for every currency asked, verified 2026-09-02. It
  is now the only source of the P2P layer, because Bybit's is geo-blocked. The
  invariant was never "avoid Binance"; it was "do not pretend a blocked
  endpoint answered", and that still holds.
- **CriptoYa uses the median *bid*** — the broker ask carries retail markup
  (`fbac138`).
- **Every row carries its fee regime**, so history stays interpretable when a
  venue changes its schedule.

## Known-invisible (stated, never estimated)

Enterprise payout pricing (Nium/Thunes/Circle), OTC desks, local cash-out fees,
KYC/limits — out of scope by nature, not by omission.

Vietnam, Nigeria and the other capital-controlled markets were listed here until
2026-09-02 because they have no licensed spot book. They are now collected off
P2P boards instead, in their own file, under their own rules — see P0.4. Nigeria
in particular is still effectively invisible: its board returns no ads at all,
which is recorded hourly rather than assumed.

## File map

```
collector.py            deep layer — SGD→PHP + USD→MXN decomposition + Wise panel
collector_basis.py      wide layer — 10-venue basis
tools/backfill_basis.py one-time daily history (not re-run)
tools/check_freshness.py rot guard, runs every fire of collect.yml
tools/check_delivery.py  hours captured per day, last 14 days (measurement, never red)
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
data/crosses_latest.json  every currency pair: crypto-route rate vs official, per run
data/stable_spread.csv  USDT vs USDC on the same venue, same hour (12 venues)
data/p2p_basis.csv      P2P layer -- 10 capital-controlled currencies, hourly
collector_p2p.py        P2P layer -- Binance P2P board, median of top 10 each side
data/withdrawal_fees.csv USDT withdrawal fee per venue/network, append-only
tools/seed_withdrawal_fees.py   one-time seed for withdrawal_fees.csv
tools/emit_latest.py    builds latest.json from the CSVs
```
