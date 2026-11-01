# margin.wiki

Seb's passion project. It prices a dollar in about 60 currencies every hour, against the official rate, and prices sending money on 11 routes with all fees in. Built for fun. Never suggest sharing it.

Read this file and the Linear issue you were given. Load nothing else unless the issue lists it.

## Where things run

- Site: margin.wiki, GitHub Pages, served from `main`.
- Collection: GitHub Actions, `collect.yml`, self-chaining about every 30 minutes. `collector_watchdog.yml` watches it.
- Raw tables (SEB-422): the ad tables and order-book depth (`data/p2p_ads/`, `data/p2p_ads_sellers/`, `data/p2p_offers/`, `data/depth/`) move to the public repo `SebR214/margin-data`, one folder per table, one file a day. `collect.yml` checks it out, sets `MARGIN_RAW_DIR` (read by `tools/daily_csv.py`), and pushes it in its own commit step. It switches on by itself once the margin-agents App can push there (`tools/raw_storage.py probe`); until then the tables stay in `data/`. Nothing in either repo passes 80 MB.
- Hetzner box: the public API at api.margin.wiki (`margin-serve`), the P2P collector (`margin-p2p-box`) and the nightly analyst. None of these call a model. The analyst reads the CSVs, checks numbers and stores findings (SEB-301).
- Work queue: `BACKLOG.md` for track A, Linear project `margin.wiki`, team `SEB`, for the rest. Not GitHub issues.
- Agents (SEB-301, Seb's plan of 25 Oct), all on GitHub Actions, no loops, nothing on the box or on Seb's Mac:
  - Collector: `collect.yml`, no model.
  - Who writes the backlog: the research chat and Seb, by hand, in the job form. Nothing else. The researcher (retired 31 Oct, SEB-422), the Scout and the weekly planner are gone. The research chat reads `python3 tools/gap_report.py --boards` and the other gap lists and writes jobs with `tools/new_board_job.py`.
  - Track A job rules (`tools/job_shape.py`): new files only (a new collector file, a new sidecar CSV, a new finding test, a new history file, a new script), plus collect.yml growing by one step and a new row in `data/source_registry.json`. Each job lists one new test `tests/agent_<name>.py` and its `done when:` names it. `tools/run_agent_tests.py` runs every such test in CI and as the builder's test. A job that changes an existing collector (collector.py and the rest), a page (html, js, css, copy.json) or a method (METHODOLOGY.md, DESIGN.md) is track B: the builder skips it.
  - Builder: the Aider builder, `aider_builder.yml` and `tools/aider_builder.py`, up to 3 jobs a day (one per daily slot). It takes the top ready job in `BACKLOG.md` (not done, blocked or built, with its files listed, no track or `track: aider`, and not track B), builds it with Aider through OpenRouter (Sonnet as architect only, qwen3-coder writes the code), runs `tools/aider_checks.py` as its test, 30 turns and $2 a job at most, logs real cost to `data/agent_spend.csv`, opens the PR, and automerge merges it on green. A job whose `tests/agent_*.py` is already on main was built by someone else: the builder blocks it as "already built?" and takes the next one, without spending a run. A job that fails twice is blocked with `needs-claude:` and the reason, and goes to Seb's own sessions (track B). A job that adds or changes collection is ticked only once its first rows are on main (`watchdog.yml`). Details in `docs/aider_track.md`.
  - The one-call builder (`one_call.yml`) has no schedule since 24 Oct. It runs only by hand.
  - Reviewer: the checks plus `automerge.yml`, no model. A PR that changes `collector*.py` or `collect.yml` is merged by it only if it is additive (new collector files or new sidecar CSVs, or new entries in a route table a collector already has; collect.yml only grows; no existing CSV touched and no other collector line changed: `tools/check_additive.py`) and one full collection run on the branch passes (`collector-gate` in `checks.yml`). Anything else stays open and goes in the daily status.
- Money: $20 a month for all agents together, enforced by `tools/llm.py` from `data/agent_spend.csv`. Sonnet for the Aider builder as architect only (qwen or DeepSeek write the code); cheap models for the one-call builder; never Opus or Fable (`tools/check_models.py`). No scheduled Claude sessions at all. The weekly Opus build was dropped on 27 Oct: the cheap track must work on its own.
- The model loops on the box (`margin-builder`, `margin-reviewer`, `margin-product`) are off. Their rulebooks are in `docs/archive/`. No `.md` file other than a Linear issue's reference doc, `BACKLOG.md` and `ROADMAP.md` (for the research chat) goes to a model.

Never say something is running, built or watching unless you checked it just now. Say where you checked.

## Two tracks

- **Track A** is `BACKLOG.md` building itself without Seb: the research chat and Seb write jobs, the Aider builder builds them, the checks and `automerge.yml` merge. Only jobs that pass `tools/job_shape.py`.
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
- No tracked file may pass 80 MB (GitHub refuses 100 MB; `tools/check_file_size.py` fails the run before the commit). The ad tables are one file a day: `data/p2p_ads/`, `data/p2p_ads_sellers/`, `data/p2p_offers/` (`tools/daily_csv.py`). `data/p2p_ads.csv`, `data/p2p_ads_sellers.csv` and `data/p2p_offers.csv` are closed, never written again. A reader takes the closed file plus the day files.
- Any change to how a number is computed goes through `METHODOLOGY.md` and bumps `index_version`. Read METHODOLOGY.md only when your job changes a method.
- Fees don't scale. Check fee tiers before claiming a cost at another amount.

## Words on the site

- The instrument is a dollar stablecoin (USDT). Say "stablecoin" or "a dollar", never "crypto".
- Money first, percent second. No jargon a smart outsider wouldn't know: no bps, basis, on-ramp, off-ramp, taker, maker, corridor, mid.
- Every reader-facing string lives in `copy.json`.
- Seb approves a page once, in its Linear spec. A PR built from a spec he approved, whose title names its SEB issue, merges by itself when every check passes (`automerge.yml`), including method changes (METHODOLOGY.md and the `index_version` bump are checked by `method-change`) and additive collector changes. Post any before and after table on the issue. Never wait on Seb for a PR, and never ask him to label one.
- `DESIGN.md` holds the page rules (layout, phones, charts) and `WORDS.md` holds how the site writes (voice, naming, the Words table that `tools/check_copy.py` enforces). Read both when your job touches a page or any reader-facing words.
- A `writer/` PR whose title names its SEB issue passes `copy-lock` with no label. Never ask Seb to add `copy-approved` or any other label. If the words were agreed in chat or the spec, merge on green.
- How it was built and the machine room (`machine-room.html`, SEB-427) say what the builder, the checks and the collector are now. The machine room's numbers come from `tools/emit_machine_room.py`; its words live in `copy.json` under `machineRoomPage`. A merge counts only if the files it added are not empty on main.

## Page work (1 Nov 2026, after a rough design session)

- Before you show Seb a mock, look at it as a reader, list what is wrong, and fix it. If he can find a fault in a minute, you should have found it first.
- A mock is the real page, with real data and the real CSS. No stand-in text, no separate mock CSS.
- "Quick mock" means that page only and one screenshot. No other pages and no checks until he says ship.
- A layout job changes layout. Do not hide, move or reword text unless he asked.
- If an instruction can be read two ways, say how you read it in one line, then act.
- Follow the spacing rules in DESIGN.md. Every gap has a reason you can name.

## Working rules

- You watch your PR's checks, fix every failure, check the live site after it merges, and only then post done on the Linear issue. A session builds every part of its issue itself, page parts included; nothing waits on the Aider builder and nothing is parked as design chat work. Work that needs a clock (24 hours of rows) is one line on the issue with the time it is due. Never hand Seb a step a session or a check can do.
- One Linear issue per job. Comment on the issue when you start and when you finish.
- Nothing waits for Seb. If a job needs him (root on the box, DNS, a decision), park it: one line on the issue, then take the next job. Parked never stops work. Never list parked items as blockers, and don't ask about them again. Parked items don't count toward any gate. If anything has waited on Seb for more than 24 hours, one email goes to the address on his GitHub account ("Waiting on you: {n}", one line each with a link), then nothing more until the list changes.
- One Claude chat session at a time. Chat sessions never take `one-call` issues: the builder does.
- No new running cost without the monthly number stated to Seb first.
- Never add an agent, a loop or a machine to fix a problem with an existing one. Fix or remove the existing one.
- Never read a data file or a file over 20 KB whole. Use grep, head or a line range. Read BACKLOG.md for the queue, not the whole of SEB-301. One session per task. Start a new one when the task is done.
- Tests never assert on live data that collection changes. Tests use their own fixed hours or fixture files. (31 Oct: two tests that matched the real files turned main's checks red as the hours moved on.)
- Writing: short sentences, plain words, no em-dashes.

Older docs are in `docs/archive/`. They record history, not current rules.
