# margin.wiki

Seb's passion project. It prices a dollar in over 50 countries every hour, against the official rate, and prices sending money on 11 routes with all fees in. Built for fun. Never suggest sharing it.

Read this file and the Linear issue you were given. Load nothing else unless the issue lists it.

## Where things run

- Site: margin.wiki, GitHub Pages. `main` holds the data and the page templates, not the finished pages. The generated pages (the baked `<noscript>` blocks, the `.md` twins, `llms.txt`, `sitemap.xml`, `robots.txt`, `404.html`, the country pages) are built on the runner after each collection run by `tools/build_site.py` and published with `actions/deploy-pages` (`collect.yml`; `pages.yml` for a merged page, script, style or word change). Never commit a generated page: they are in `.gitignore` and `checks.yml` fails a PR that adds one.
- Collection: GitHub Actions, `collect.yml`, self-chaining about every 30 minutes: each run sleeps to its slot, starts the next run, then collects (`tools/collect_chain.py`), so a slow run cannot end the chain. The Hetzner box restarts a dead chain within 10 minutes (`agents/collect_restarter.sh`, timer `margin-collect-restarter`, installed once with `agents/install_restarter.sh`); the GitHub cron is the second line. `collector_watchdog.yml` watches it and emails through healthchecks.io when no sample has landed, or the site has not been deployed, in 90 minutes.
- Raw tables (SEB-422): the ad tables and order-book depth (`data/p2p_ads/`, `data/p2p_ads_sellers/`, `data/p2p_offers/`, `data/depth/`) move to the public repo `SebR214/margin-data`, one folder per table, one file a day. `collect.yml` checks it out, sets `MARGIN_RAW_DIR` (read by `tools/daily_csv.py`), and pushes it in its own commit step. It switches on by itself once the margin-agents App can push there (`tools/raw_storage.py probe`); until then the tables stay in `data/`. Nothing in either repo passes 80 MB.
- Hetzner box: the public API at api.margin.wiki (`margin-serve`), the P2P collector (`margin-p2p-box`), the nightly analyst and the collection restarter (`margin-collect-restarter`). None of these call a model. The analyst reads the CSVs, checks numbers and stores findings (SEB-301).
- Work queue: `BACKLOG.md` for track A, Linear project `margin.wiki`, team `SEB`, for the rest. Not GitHub issues.
- Agents (SEB-301, Seb's plan of 25 Oct), all on GitHub Actions, no loops, nothing on the box or on Seb's Mac:
  - Collector: `collect.yml`, no model.
  - Who writes the backlog: the research chat and Seb, by hand, in the job form, plus the Opus planner for `build` issues in Linear (5 Nov). Nothing else. The researcher (retired 31 Oct, SEB-422), the Scout and the weekly planner are gone. The research chat reads `python3 tools/gap_report.py --boards` and the other gap lists and writes jobs with `tools/new_board_job.py`.
  - Track A job rules (`tools/job_shape.py`): new files only (a new collector file, a new sidecar CSV, a new finding test, a new history file, a new script), plus collect.yml growing by one step and a new row in `data/source_registry.json`. Each job lists one new test `tests/agent_<name>.py` and its `done when:` names it. `tools/run_agent_tests.py` runs every such test in CI and as the builder's test. A job that changes an existing collector (collector.py and the rest), a page (html, js, css, copy.json) or a method (METHODOLOGY.md, DESIGN.md) is track B: the builder skips it.
  - Builder (5 Nov): the Claude builder, `claude_builder.yml` and `tools/next_build.py` (no model), replaces the Aider builder. An Opus planner (a claude.ai scheduled task, set up in the research chat) writes up to 3 Linear issues a day in project margin.wiki with the label `build` and emails Seb. Every 30 minutes `next_build.py` picks the next job: a `build` issue In Review with a comment from Seb newer than the builder's last comment, else the top `build` issue in Todo; nothing once 3 "Started" comments exist for today. The job goes to `anthropics/claude-code-action` (Sonnet, 60 turns, 45 minutes) on branch `claude/<SEB id>` with the app token, so its PR runs the checks. The workflow comments "Started" and moves the issue to In Progress, then comments the PR link and moves it to In Review. `automerge.yml` merges the PR on green and comments the live page link on the issue and moves it to Done. A run that ends with no PR labels the issue `needs-claude` (track B). Track A job rules still describe what the planner may ask for cheaply, but the builder is not limited to them.
  - The Aider builder (`aider_builder.yml`) has no schedule since 5 Nov. It runs only by hand. Details in `docs/aider_track.md`.
  - The one-call builder (`one_call.yml`) has no schedule since 24 Oct. It runs only by hand.
  - Reviewer: the checks plus `automerge.yml`, no model. A PR that changes `collector*.py` or `collect.yml` is merged by it only if it is additive (new collector files or new sidecar CSVs, or new entries in a route table a collector already has; collect.yml only grows; no existing CSV touched and no other collector line changed: `tools/check_additive.py`) and one full collection run on the branch passes (`collector-gate` in `checks.yml`). Anything else stays open and goes in the daily status.
- Money: $20 a month for the OpenRouter agents together, enforced by `tools/llm.py` from `data/agent_spend.csv` (never Opus or Fable there: `tools/check_models.py`). The Claude builder is the one scheduled Claude use and costs nothing extra a month: it runs on Seb's Claude subscription through the OAuth token `CLAUDE_CODE_OAUTH_TOKEN` (`claude setup-token`, valid one year, renew by 5 Nov 2027), capped at 3 builds a day. GitHub Actions minutes are free (public repo). No other scheduled Claude sessions.
- The model loops on the box (`margin-builder`, `margin-reviewer`, `margin-product`) are off. Their rulebooks are in `docs/archive/`. No `.md` file other than a Linear issue's reference doc, `BACKLOG.md` and `ROADMAP.md` (for the research chat) goes to a model.

Never say something is running, built or watching unless you checked it just now. Say where you checked.

## Two tracks

- **Track A** is `BACKLOG.md` building itself without Seb: the research chat and Seb write jobs, the Aider builder (by hand only since 5 Nov) builds them, the checks and `automerge.yml` merge. Only jobs that pass `tools/job_shape.py`.
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
- How it was built (`how-it-was-built.html`, SEB-427, the machine room merged into it 1 Nov) says what the builder, the checks and the collector are now. Its numbers come from `tools/emit_machine_room.py`; its words live in `copy.json` under `machineRoom` and `machineRoomPage`. A merge counts only if the files it added are not empty on main.

## Page work (1 Nov 2026, after a rough design session)

- Before you show Seb a mock, look at it as a reader, list what is wrong, and fix it. If he can find a fault in a minute, you should have found it first.
- A mock is the real page, with real data and the real CSS. No stand-in text, no separate mock CSS.
- "Quick mock" means that page only and one screenshot. No other pages and no checks until he says ship.
- A layout job changes layout. Do not hide, move or reword text unless he asked.
- If an instruction can be read two ways, say how you read it in one line, then act.
- Follow the spacing rules in DESIGN.md. Every gap has a reason you can name.
- The header is one block on every page, written by `tools/bake_nav.py`, styled only in `css/site_head.css`. Never fix the header on one page. Change the one source, and `bake_nav.py --check` and `check_header.py` must pass.
- A job is done only when the page the reader lands on has been read top to bottom, every link on it clicked, and nothing on it contradicts what the job built.

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
