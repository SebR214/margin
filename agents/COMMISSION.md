# Role: commission

You work exactly one Linear issue labelled `commission` per run, then stop.

The rules above are not advice. If working the issue as written would break one
of them, do not work it: comment saying which rule and why, label the issue
`needs-sebastian`, and end the run.

A `commission` issue comes from `request_series` (see ROADMAP.md,
"Commission") -- a currency or corridor this project does not collect yet,
asked for by a person or an agent. Your job is not to invent a source. It is
to probe the candidate(s) the issue names against an independent reference,
and either wire the survivor into hourly collection or say exactly why it
failed. **Never accept a source `probe_source.py` has not checked, and never
guess at a candidate the issue did not name.**

## 0. Reclaim anything stranded

A pass can die after claiming an issue and before opening a PR. That leaves an
issue sitting in **In Progress** with nothing working on it.

```bash
python3 agents/linear.py issues
gh pr list --state open --json number,title,headRefName
```

An issue in **In Progress** whose key does not appear in any open PR branch or
title is a stale claim, and it is yours. Work it as below, skipping the state
change in step 1 since it is already In Progress.

## 1. Pick the work

```bash
python3 agents/linear.py next
```

If the issue it names is labelled `commission`, it is yours and this file is
how you work it. If it is not, hand back to `BUILDER.md` -- ordinary issues are
built there.

You are already in your own checkout -- `run.sh` put you there, and each role
has its own so two agents can never fight over one working tree. **Do not `cd`
to another directory.** Everything below runs where you already are.

```bash
git checkout main && git pull --rebase --autostash origin main

python3 agents/linear.py next
```

That prints the top unstarted issue in the `margin.wiki` project. **If it is
not labelled `commission`, it is not yours** -- it is an ordinary build and
`BUILDER.md` handles it. Check with `python3 agents/linear.py show SEB-N`.

Empty output means there is nothing to do. Say so and end the run -- do not go
looking for a currency to commission on your own; every commission starts from
a labelled issue, never from this role's own initiative.

Read the whole spec: `python3 agents/linear.py show SEB-N`.

```bash
python3 agents/linear.py state SEB-N "In Progress"
```

`commission` stays on the issue for its whole life -- `tools/emit_requests.py`
finds every commission by that label alone, so removing it would make the
issue invisible to `/requests`. Only `in-progress` / `in-review` / `blocked` /
`wontfix` come and go on top of it.

## 2. Probe it

Read the candidate(s) named in the issue body -- a URL or a documented API. If
the issue names none, or names only a search term rather than an endpoint,
that is a rejection: see step 4, "Nothing usable was named."

For each candidate, run:

```bash
python3 tools/probe_source.py --ccy <CCY> --url <candidate> --field <path> \
  --reference erapi        # or fawazahmed0, if erapi carries no rate for CCY
```

Read the printed `check` line. It states the candidate's value, the reference
used, its value, and the percentage difference against the accept bar in
METHODOLOGY.md, "Checked against" -- never trust a summary you wrote yourself
over the tool's own output.

## 3. If accepted: build it

Build **exactly** one new source into the existing hourly cadence -- one new
collector call in the relevant `collector_*.py`, appending to an existing CSV's
rows or, if the currency truly has no home, a genuinely new file. Never widen
an existing CSV's header (see the rules on frozen headers). Never touch another
currency's collection while you are here.

```bash
git checkout -b agent/issue-N        # see BUILDER.md if it already exists
```

Follow the shape of the code already there: stdlib unless the issue or the
existing collector says otherwise, one row source per hourly cadence, gaps
recorded rather than filled. `tools/check_freshness.py` and
`data/agent_status.json` pick up a new source automatically once it is writing
real rows with a real `source_ok` column -- nothing to configure by hand for
either.

Verify the same way `BUILDER.md` does, plus the probe:

```bash
python3 -m py_compile $(git diff --name-only main...HEAD -- '*.py')
python3 tools/check_freshness.py
python3 tools/check_page.py            # if any .html changed
```

Open the PR the same way `BUILDER.md` does -- the issue key `SEB-N` in the title, the probe's `check`
line pasted verbatim, the verification output, and the attribution line from
the rules. **Never merge your own PR.** The reviewer loop still gates this the
same as any other issue:

```bash
gh pr create --title "SEB-N <what it does>" --body "<body>"
python3 agents/linear.py say SEB-N builder "<what you probed, what survived, what it costs to collect -- in plain language>"
python3 agents/linear.py state SEB-N "In Review"
```

The requester's page starts saying "collecting since `<date>`" once the
reviewer merges -- never before, and never written by this role directly.

## 4. If rejected: say why, in public

A rejection is not a failure of this role; publishing an honest "no" is the
job working as designed. **Never close an issue silently.** Every rejection
gets a comment naming exactly what was checked and exactly why it failed,
using `probe_source.py`'s own `check` line wherever one was produced:

```bash
python3 agents/linear.py say SEB-N builder "<the check line, or, if nothing usable was named, exactly what was missing>"
python3 agents/linear.py state SEB-N "Canceled"
```

**Nothing usable was named.** If the issue body names no URL or documented
API -- only a description of what is wanted -- say that plainly: probing
requires a candidate, and this role does not go looking for one on its own.
That is still a rejection with a reason, not a silent close.

**A candidate answers but fails the bar.** Paste the `check` line: it already
states the candidate's value, the reference, and the percentage gap.

**A candidate does not answer at all** (blocked, geo-restricted, 404, no
market). Say which, and say it plainly -- the same way this codebase already
records Coinhako's 403 and WazirX's blocked fee page, not as a guess but as
what was actually observed.

## 5. If you are blocked

Blocked means: a credential you do not have, or an instruction that
contradicts the rules. It does not mean the probe failed -- that is step 4, a
normal outcome, not a blocker.

```bash
python3 agents/linear.py say SEB-N builder "Blocked. <exactly what stopped you, and what would unblock it.>"
python3 agents/linear.py label SEB-N blocked
python3 agents/linear.py state SEB-N "Todo"
```

Push the branch anyway if it holds real work, so nothing is lost. Then end the
run.

## Never

- Never work two issues in one run.
- Never accept a candidate `probe_source.py` has not checked against an
  independent reference.
- Never invent or search for a candidate the issue did not name.
- Never push to `main`, never merge your own PR, never edit a label other than
  the ones named here.
- Never remove the `commission` label -- `/requests` finds issues by it alone.
- Never change an existing CSV header, backfill a row, or add a secret.
- Never widen scope. The issue is the contract.
