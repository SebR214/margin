# Track A: the Aider builder (SEB-301, pilot from 22 Oct 2026)

Not read by any model. This is the record of how track A is set up and what the weekly Claude task is told.

## Parts

- `aider_builder.yml` and `tools/aider_builder.py`: once a day, one job, Aider in architect mode through OpenRouter. Sonnet plans,
  qwen3-coder writes the edits. Test command: `tools/aider_checks.py` (the offline commands of the `checks` job in checks.yml).
  At most 30 model turns and 25 minutes a job. Cost per job is the OpenRouter key's own `usage` before and after the run, written to
  `data/agent_spend.csv` as `SEB-301/aider/<job>`. Result and cost per job also go to `data/aider_log.csv` and one line on SEB-301.
- A job is taken only if it carries a `track: aider` line in BACKLOG.md. The one-call builder skips those jobs. Pilot: items 1 to 3.
  After the pilot, Seb decides whether the line goes on every job or the one-call builder goes.
- A job that fails twice gets `blocked: needs-claude: ...` in BACKLOG.md. The builder then takes the next job.
- Since 25 Oct: the Scout, `weekly_planner.yml` and the weekly Claude Code task are gone. `researcher.yml` writes 3 jobs a week,
  `scorecard.yml` posts the weekly result, and `needs-claude` jobs go to Seb's own sessions (track B). See CLAUDE.md.
  The prompt below is kept as history only.

## Weekly Claude task prompt

Work in the margin-wiki repo (SebR214/margin), from a fresh checkout of main. Read CLAUDE.md. Run
`grep -n "needs-claude" BACKLOG.md` and take at most 2 jobs whose `blocked:` line starts with `needs-claude`, in file order. For each:
read only the job's `files:`, `context:` and `done when:` lines and the files it lists (never a data file or a file over 20 KB whole),
build it, run `python3 tools/aider_checks.py`, open a PR titled `SEB-301: <job title> (backlog <id>)`, remove the job's `blocked:` line and add
`built: PR #N (date)` for a collection job or tick it for any other. Post one line on SEB-301 with the PR and the result. If a job
cannot be done, replace its `blocked:` text with the reason in one line (without the word needs-claude) and go on. Do not take a
third job. Never put a collect.yml or collector change in the same PR as a visual change. No em-dashes.

## Cost

See the SEB-301 comment of 22 Oct for the monthly estimate from the pilot's real numbers.
