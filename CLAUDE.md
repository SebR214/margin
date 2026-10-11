# margin.wiki

Seb's passion project. It prices a dollar in about 60 currencies every hour, against the official rate, and prices sending money on 7 routes with all fees in. Built for fun. Never suggest sharing it.

Read this file and the Linear issue you were given. Load nothing else unless the issue lists it.

## Where things run

- Site: margin.wiki, GitHub Pages, served from `main`.
- Collection: GitHub Actions, `collect.yml`, self-chaining about every 30 minutes. `collector_watchdog.yml` watches it.
- Hetzner box: the public API at api.margin.wiki (`margin-serve`), the P2P collector (`margin-p2p-box`) and the nightly analyst. None of these call a model. The analyst reads the CSVs, checks numbers and stores findings (SEB-301). Its number check feeds the Scout.
- Work queue: Linear, project `margin.wiki`, team `SEB`. Not GitHub issues.
- Agents (SEB-301), all on GitHub Actions, no loops, nothing on the box or on Seb's Mac:
  - Collector: `collect.yml`, no model.
  - Scout: `scout.yml`, Mondays 01:00 UTC, one Sonnet call through `tools/llm.py`. It writes one spec into SEB-300.
  - Builder: `one_call.yml` and `tools/one_call.py`, builds any `one-call` issue in one call, $1 a job.
  - Reviewer: the checks plus `automerge.yml`, no model. A PR that changes `collector*.py` or `collect.yml` is never merged by it.
- Money: $20 a month for all agents together, enforced by `tools/llm.py` from `data/agent_spend.csv`. Sonnet only for the Scout, cheap models for the builder, never Opus or Fable (`tools/check_models.py`).
- Daily status on SEB-301 comes from `tools/daily_status.py`, written from the logs. The watchdog fails if the Scout has not run in 8 days.
- The model loops on the box (`margin-builder`, `margin-reviewer`, `margin-product`) are off. Their rulebooks are in `docs/archive/`. No `.md` file other than a Linear issue's reference doc goes to a model.

Never say something is running, built or watching unless you checked it just now. Say where you checked.

## Data rules

- Real CSVs only. Every number is computed from a file in `data/`. Never type, guess or invent one.
- Any sentence with never, always, every, none or a count is re-derived from the CSVs before it is written, and is stated per route.
- Loud failure. Bad data exits non-zero. Nothing degrades quietly.
- Persistence before display. The sample is written before anything is printed.
- Gaps stay gaps. Failed pulls are rows with `source_ok=false`. The live layer is never backfilled or interpolated.
- History lives only in `data/history/`, labelled "reported, not observed", with its source on every row. It never feeds the index, a price or the unbroken-hours count.
- Existing CSV headers are frozen. New columns go in a sidecar file.
- Any change to how a number is computed goes through `METHODOLOGY.md` and bumps `index_version`. Read METHODOLOGY.md only when your job changes a method.
- Fees don't scale. Check fee tiers before claiming a cost at another amount.

## Words on the site

- The instrument is a dollar stablecoin (USDT). Say "stablecoin" or "a dollar", never "crypto".
- Money first, percent second. No jargon a smart outsider wouldn't know: no bps, basis, on-ramp, off-ramp, taker, maker, corridor, mid.
- Every reader-facing string lives in `copy.json`.
- Seb approves a page once, in its Linear spec. A PR whose title names its SEB issue merges by itself when every check passes (`automerge.yml`). Never wait on Seb for a PR, and never ask him to label one.
- `DESIGN.md` holds the page rules. Read it when your job touches a page.

## Working rules

- One Linear issue per job. Comment on the issue when you start and when you finish.
- If something needs Seb (root on the box, DNS, a decision), park it: say so in one line on the issue and move straight on to the next thing. Never list parked items as blockers, and don't ask about them again. Parked items don't count toward any gate.
- One Claude chat session at a time. Chat sessions never take `one-call` issues: the builder does.
- No new running cost without the monthly number stated to Seb first.
- Never add an agent, a loop or a machine to fix a problem with an existing one. Fix or remove the existing one.
- Writing: short sentences, plain words, no em-dashes.

Older docs are in `docs/archive/`. They record history, not current rules.
