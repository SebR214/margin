# margin.wiki

Seb's passion project. It prices a dollar in about 60 currencies every hour, against the official rate, and prices sending money on 7 routes with all fees in. Built for fun. Never suggest sharing it.

Read this file and the Linear issue you were given. Load nothing else unless the issue lists it.

## Where things run

- Site: margin.wiki, GitHub Pages, served from `main`.
- Collection: GitHub Actions, `collect.yml`, self-chaining about every 30 minutes. `collector_watchdog.yml` watches it.
- Hetzner box: the public API at api.margin.wiki (`margin-serve`), the P2P collector (`margin-p2p-box`) and the nightly analyst. None of these call a model. The analyst reads the CSVs, checks numbers and stores findings (SEB-301).
- Work queue: `BACKLOG.md` for track A, Linear project `margin.wiki`, team `SEB`, for the rest. Not GitHub issues.
- Agents (SEB-301, Seb's plan of 25 Oct), all on GitHub Actions, no loops, nothing on the box or on Seb's Mac:
  - Collector: `collect.yml`, no model.
  - Researcher: `researcher.yml` and `tools/researcher.py`, Mondays 00:17 UTC, the only scheduled model that proposes work. It reads the data-gap report `tools/gap_report.py` computes from the CSVs (countries with no price, one-source markets, sources that disagree, stale finding retests, sources past quarantine), ROADMAP.md and the backlog titles, makes one Sonnet call through OpenRouter (two if the first answer breaks a rule), and writes 3 jobs to the end of `BACKLOG.md` with `proposed: researcher`. About $0.30 a run.
  - Who writes the backlog: the researcher, and Seb or a chat by hand in the same job form. Nothing else. The Scout and the weekly planner were removed on 25 Oct. The weekly review and build never adds backlog items. It only ticks the one it built.
  - Track A job rules (`tools/job_shape.py`): new files only (a new collector file, a new sidecar CSV, a new finding test, a new history file, a new script), plus collect.yml growing by one step and a new row in `data/source_registry.json`. Each job lists one new test `tests/agent_<name>.py` and its `done when:` names it. `tools/run_agent_tests.py` runs every such test in CI and as the builder's test. A job that changes an existing collector (collector.py and the rest), a page (html, js, css, copy.json) or a method (METHODOLOGY.md, DESIGN.md) is track B: the builder skips it, the researcher can't write it.
  - Builder: the Aider builder, `aider_builder.yml` and `tools/aider_builder.py`, up to 3 jobs a day (one per daily slot). It takes the top ready job in `BACKLOG.md` (not done, blocked or built, with its files listed, no track or `track: aider`, and not track B), builds it with Aider through OpenRouter (Sonnet as architect only, qwen3-coder writes the code), runs `tools/aider_checks.py` as its test, 30 turns and $2 a job at most, logs real cost to `data/agent_spend.csv`, opens the PR, and automerge merges it on green. A job that fails twice is blocked with `needs-claude:` and the reason, and goes to Seb's own sessions (track B). A job that adds or changes collection is ticked only once its first rows are on main (`watchdog.yml`). Details in `docs/aider_track.md`.
  - The one-call builder (`one_call.yml`) has no schedule since 24 Oct. It runs only by hand.
  - Reviewer: the checks plus `automerge.yml`, no model. A PR that changes `collector*.py` or `collect.yml` is merged by it only if it is additive (new collector files or new sidecar CSVs, or new entries in a route table a collector already has; collect.yml only grows; no existing CSV touched and no other collector line changed: `tools/check_additive.py`) and one full collection run on the branch passes (`collector-gate` in `checks.yml`). Anything else stays open and goes in the daily status.
  - Scorecard: `scorecard.yml` and `tools/scorecard.py`, Sundays 12:17 UTC, no model. Bot PRs merged that week, the job each came from, who proposed it, builder runs, spend, and the count toward the kill date. Posted on the GitHub issue "Agent scorecard", which emails Seb. It is the only evidence about track A. No chat says track A is "fixed" or "working". It quotes the card.
  - Kill date: if fewer than 4 bot PRs from researcher jobs have merged by 8 Nov 2026, track A is switched off and the researcher's list becomes a to-do for Seb's own sessions.
- Money: $20 a month for all agents together, enforced by `tools/llm.py` from `data/agent_spend.csv`. Sonnet for the researcher, and for the Aider builder as architect only (qwen or DeepSeek write the code); cheap models for the one-call builder; never Opus or Fable (`tools/check_models.py`). One scheduled Claude session a week and no other: the weekly review and build (a claude.ai scheduled task, Opus on Seb's plan, Mondays 09:50 SGT, about an hour). Part 1 reads the repo and the CSVs and emails Seb a memo: 3 things the data says that nobody has published, 2 flaws, 1 big bet. Part 2 builds one step and opens one PR: what Seb asked for in a reply to the memo, else the next unbuilt ROADMAP.md step, else the next track B backlog item. Never a job the Aider builder has. Trial to 23 Nov: kept only if the memo gives at least one idea a month Seb builds. Seb can also start one-off Claude Code sessions for track B jobs.
- Daily status on SEB-301 comes from `tools/daily_status.py`, written from the logs. One post a day, with a "Built today" line. The watchdog fails if the researcher has not run in 8 days.
- The model loops on the box (`margin-builder`, `margin-reviewer`, `margin-product`) are off. Their rulebooks are in `docs/archive/`. No `.md` file other than a Linear issue's reference doc, `BACKLOG.md` and `ROADMAP.md` (for the researcher) goes to a model.

Never say something is running, built or watching unless you checked it just now. Say where you checked.

## Two tracks

- **Track A** is `BACKLOG.md` building itself without Seb: the researcher and the chats write jobs, the Aider builder builds them, the checks and `automerge.yml` merge, the Sunday scorecard reports. Only jobs that pass `tools/job_shape.py`.
- **Track B** is Seb's own Claude Code sessions: work he asks for in chat, live the same day, plus any `needs-claude` or track B job.
- A job is on one track at a time. Track A takes only what is in `BACKLOG.md`; a chat session never takes a job the builder has.

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
- A `writer/` PR whose title names its SEB issue passes `copy-lock` with no label. Never ask Seb to add `copy-approved` or any other label. If the words were agreed in chat or the spec, merge on green.
- How it was built's description of the agents is closed. It says four agents and stays that way. Never raise it, never flag it in a review or audit, never list it as waiting on Seb, never change it.

## Working rules

- Nothing waits for a green run. A PR whose title names its SEB issue is merged by `automerge.yml` when every check passes, and the rendered gates in `checks.yml` (1280px and 390px) are the page check, so a session never ends a turn on "I'll merge on green" or "I'll check it live after". Open the PR with everything it needs, then take the next job. A failed check wakes the session through Auto-fix. Work that needs a clock (24 hours of rows) is one line on the Linear issue with the time it is due, and the next session picks it up. Never hand Seb a step a session or a check can do.
- One Linear issue per job. Comment on the issue when you start and when you finish.
- Nothing waits for Seb. If a job needs him (root on the box, DNS, a decision), park it: one line on the issue, then take the next job. Parked never stops work. Never list parked items as blockers, and don't ask about them again. Parked items don't count toward any gate. If anything has waited on Seb for more than 24 hours, one email goes to the address on his GitHub account ("Waiting on you: {n}", one line each with a link), then nothing more until the list changes.
- One Claude chat session at a time. Chat sessions never take `one-call` issues: the builder does.
- No new running cost without the monthly number stated to Seb first.
- Never add an agent, a loop or a machine to fix a problem with an existing one. Fix or remove the existing one.
- Never read a data file or a file over 20 KB whole. Use grep, head or a line range. Read BACKLOG.md for the queue, not the whole of SEB-301. One session per task. Start a new one when the task is done.
- Writing: short sentences, plain words, no em-dashes.

Older docs are in `docs/archive/`. They record history, not current rules.
