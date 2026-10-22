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
  - Scout: `scout.yml`, Mondays 01:00 UTC, Sonnet through OpenRouter (`tools/llm.py`). Its main job is splitting the next 7 unchecked items of `BACKLOG.md` into jobs that fit one builder call, with the exact files listed. If a pick fails the probe or a check it tries the next item, up to 3 a run. Its own suggestions come second, into SEB-300.
  - Builder: `one_call.yml` and `tools/one_call.py`, once a day. It takes the top unchecked job in `BACKLOG.md` (the queue; `tools/backlog.py` copies new "Queued by Claude" items from SEB-301 comments into it first), builds it in one call (qwen, kimi as fallback, $1 a job), opens the PR, ticks the item with the PR number, posts one line on SEB-301. A job that changes a published number lists METHODOLOGY.md in its files. A job that fails twice gets `needs-claude` and the builder takes the next one. A job that adds or changes collection is ticked only once its first rows are on main; none within 2 hours of the merge and it is blocked with why (`watchdog.yml`, BACKLOG.md item 0). A file too big to send whole is sent in parts and changed by edits. Issues labelled `one-call` are still taken.
  - Aider builder (track A, pilot from 22 Oct, SEB-301): `aider_builder.yml`, once a day, Aider through OpenRouter with Sonnet as architect and qwen3-coder as editor, on jobs of BACKLOG.md that carry `track: aider` (the one-call builder skips them). Test command `tools/aider_checks.py`, 30 turns a job, real cost from OpenRouter's key usage into `data/agent_spend.csv`. Two failures mark a job `needs-claude`; a weekly Claude Code task takes at most 2. `weekly_planner.yml` posts items shipped and cost per track on SEB-301. Details in `docs/aider_track.md`. Sonnet is allowed here as architect only.
  - Reviewer: the checks plus `automerge.yml`, no model. A PR that changes `collector*.py` or `collect.yml` is merged by it only if it is additive (new collector files or new sidecar CSVs, or new entries in a route table a collector already has; collect.yml only grows; no existing CSV touched and no other collector line changed: `tools/check_additive.py`) and one full collection run on the branch passes (`collector-gate` in `checks.yml`). Anything else stays open and goes in the daily status.
- Money: $20 a month for all agents together, enforced by `tools/llm.py` from `data/agent_spend.csv`. Sonnet only for the Scout, cheap models for the builder, never Opus or Fable (`tools/check_models.py`).
- Daily status on SEB-301 comes from `tools/daily_status.py`, written from the logs. One post a day, with a "Built today" line. The watchdog fails if the Scout has not run in 8 days.
- The model loops on the box (`margin-builder`, `margin-reviewer`, `margin-product`) are off. Their rulebooks are in `docs/archive/`. No `.md` file other than a Linear issue's reference doc and `BACKLOG.md` (for the Scout to split) goes to a model.

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
- Seb approves a page once, in its Linear spec. A PR built from a spec he approved, whose title names its SEB issue, merges by itself when every check passes (`automerge.yml`), including method changes (METHODOLOGY.md and the `index_version` bump are checked by `method-change`) and additive collector changes. Post any before and after table on the issue. Never wait on Seb for a PR, and never ask him to label one.
- `DESIGN.md` holds the page rules. Read it when your job touches a page.

## Working rules

- One Linear issue per job. Comment on the issue when you start and when you finish.
- Nothing waits for Seb. If a job needs him (root on the box, DNS, a decision), park it: one line on the issue, then take the next job. Parked never stops work. Never list parked items as blockers, and don't ask about them again. Parked items don't count toward any gate. If anything has waited on Seb for more than 24 hours, one email goes to the address on his GitHub account ("Waiting on you: {n}", one line each with a link), then nothing more until the list changes.
- One Claude chat session at a time. Chat sessions never take `one-call` issues: the builder does.
- No new running cost without the monthly number stated to Seb first.
- Never add an agent, a loop or a machine to fix a problem with an existing one. Fix or remove the existing one.
- Never read a data file or a file over 20 KB whole. Use grep, head or a line range. Read BACKLOG.md for the queue, not the whole of SEB-301. One session per task. Start a new one when the task is done.
- Writing: short sentences, plain words, no em-dashes.

Older docs are in `docs/archive/`. They record history, not current rules.
