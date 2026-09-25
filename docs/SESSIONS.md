SESSIONS.md — remaining work, so no future session has to ask Sebastian for context

Session 1 (DESIGN.md, the canonical nav, the real chart palette) shipped in
PR #153, merged 2026-09-25. What follows is what's left.

## Session 2

Scope: the ten dead pages, corridor.html's title/h1, a hard waterfall-
reconciliation check, and the last "ordinary" register strays. Nothing
else — anything found outside this list goes to the post-v1 backlog label,
untouched.

1. **Ten dead pages get redirects, not deletion**: calculator.html,
   providers.html, pricing-history.html, requests.html, status.html,
   stress.html, watch.html, weekly.html, data.html, methodology.html.
   Each redirects to its nearest live replacement rather than 404ing on
   anyone with an old link.

2. **methodology.html first**: diff it against how-it-works.html, fold
   anything methodology.html has that how-it-works.html lacks into
   how-it-works.html, *then* redirect methodology.html. Content has to
   land before the page that held it goes away, not after.

3. **corridor.html's title and h1**: still "Is it a real dollar?", the
   pre-DESIGN.md framing. Give it the real job -- one route's receipt --
   in both `<title>` and `<h1>`. This also means updating
   `tools/check_page.py`'s `PAGE_TITLE["corridor.html"]` entry in the same
   change (PR #153 hardcoded the old string as correct; leaving it stale
   makes the title check fail on the very fix it should be enforcing).

4. **A real reconciliation check**: read the rendered waterfall bars and
   the rendered total off the live page (not the underlying CSV/bps
   fields -- the rendered numbers, what a reader actually sees) and fail
   unless they sum to the cent. `data/corridor_waterfall.csv` (added
   2026-09-24) already backs this exactly; the check should prove the page
   renders what the sidecar says, not re-derive the math itself.

5. **Register strays**: "ordinary provider" (or similar pre-DESIGN.md
   phrasing) wherever it still appears in ask.html, findings.html,
   sending-money.html -- DESIGN.md says "best fiat provider," no
   exceptions. Grep the whole of copy.json and each page's own markup, not
   just the obvious spots; SEB-53 was exactly this kind of stray missed
   once already.

Merge this one yourself once your own `check_page.py` gate passes clean
(the two known, pre-existing, environment-only failures --
`watch.html`'s `/watch` backend and `machine-room.html`'s `:8903` API,
neither reachable outside the production server -- don't block a merge;
everything else does).

## Session 3

Scope: settle who actually did what on `main`, then make the answer
mechanical instead of re-derived by hand every time.

1. **The commit audit.** Every commit on `main` since the loops started
   that has no PR or no recorded reviewer verdict. For each: read its git
   author email, its commit timestamp's timezone offset, and its
   `Co-Authored-By` line -- that's what actually identifies who committed
   it. **Never conclude "the agent did this" from an absence in
   `linear_activity.jsonl` or any other log** -- a log that only sees
   Linear activity cannot see a commit made from Sebastian's own laptop,
   and treating silence there as proof produced a false accusation once
   already (SEB-101, corrected 2026-09-23: six commits blamed on the
   builder were `+0800`, Sebastian's own timezone, while the server runs
   `+0000`). Classify each commit as collector, index, or reader-facing,
   since that's what determines how much it actually mattered.

2. **Branch protection on `main`**, only after the audit's done: pull
   requests required, one approval required, from `SebR214` specifically.
   This is the mechanical fix for the thing the audit will surface by
   hand -- PRs merged over a rejected review, merges nobody can attribute
   with certainty, because GitHub's own record can't currently
   distinguish Sebastian from an agent.

3. **Agent commits move to their own identity** (GitHub App or machine
   user, not `SebR214`) so that distinction is real going forward, not
   just asserted in a commit message.

**Once branch protection is live, the human-merge rule is back and
permanent** -- the waiver that let a session merge #153 and Session 2's
PR directly was scoped to before this existed, not a standing exception.

## Standing rules (DESIGN.md, in full once Session 1 landed)

- Every reader-facing string lives in `copy.json`.
- Numbers are computed from `data/`, never typed. Gaps stay gaps.
- Work happens on a branch; Sebastian merges (see the waiver note above
  for the one exception, and its expiry condition).
- Done means Sebastian has seen it on live margin.wiki -- not on a
  branch, not in a screenshot of a local render, on the actual domain.
