# margin.wiki — start here

Paste this into a new chat. It is deliberately short; the repo holds the detail.

**Ops details (server, ssh, credential locations) live in a private Linear
document, "Start Here" — ask Sebastian for the link if you don't have it.
This public file carries everything else.**

## What it is

> margin.wiki prices a dollar in 59 currencies, every hour, using the only
> dollar a person can actually buy — and says which ones have no price today,
> and why.

The instrument is a **dollar stablecoin** priced in local currency. Never say
"crypto" on a reader-facing page — that is a locked invariant, not a preference.
It is an FX story. Absence is published: ~46 currencies carry a price in a given
hour, the rest are withheld with a stated reason.

`ROADMAP.md` is the contract. Its `## Invariants` outrank any issue.

## Where it runs

| | |
|---|---|
| Site | margin.wiki (GitHub Pages, from `main`) |
| API | api.margin.wiki → Caddy → REST, MCP, and the ask endpoint, each on its own local port |
| Repo | `SebR214/margin` (public) — code and PRs only |
| Work | Linear — [linear.app/sebastian-roervig](https://linear.app/sebastian-roervig), project `margin.wiki`, team `SEB`. An issue is `https://linear.app/sebastian-roervig/issue/SEB-<n>` |

Three loops on the server — `margin-builder`, `margin-reviewer`,
`margin-product` — take work from Linear and open PRs. `margin-serve` runs the
API. Collection runs on GitHub Actions (`collect.yml`), self-chaining every 30
minutes.

Credential locations are in the private Start Here document, not here — see
above.

## How to talk to the work

```bash
export LINEAR_API_KEY=...            # location: the private Start Here doc
python3 agents/linear.py issues      # everything in the project
python3 agents/linear.py next        # what the builder takes next
python3 agents/linear.py show SEB-39
python3 agents/linear.py say SEB-39 product "..."
python3 agents/linear.py respec SEB-39 --body-file spec.md --role product
```

## Standing rules

- Real files only. Every number computed from something in `data/`, never typed.
- Loud failure. A thing that cannot run says so; it never degrades quietly.
- Existing CSV headers are frozen. New columns go in a sidecar.
- Every reader-facing string lives in `copy.json`.
- **Nothing reader-facing merges without Sebastian's screenshot approval.**
- No new running cost without the monthly figure and its arithmetic stated first.
- Never backfill. Gaps stay gaps.

## State

See the most recent "margin.wiki — v1 freeze and ship brief" in Linear (or
pasted into the working session) for the current plan and what's frozen.
Everything before it is superseded where the two disagree.

## Things that have bitten, twice each

- **A stale line in `ROADMAP.md` outranks a fresh issue** and will silently stop
  the builder. When a decision changes, change the ROADMAP, not just a comment.
- **An emitted file left out of a workflow's staging list kills collection.**
  It commits, then refuses to rebase, and 21 hours of unbackfillable readings
  were lost this way once. There is now a fallback that stages tracked changes
  and warns — and the same failure mode has repeated since on a different
  workflow (`fees.yml`) for a different emitted file, so re-check any new
  `git add <explicit files>` step against what the script it runs actually
  writes.
- **A check wired downstream of the fault never fires.** The freshness guard ran
  last and reported rot correctly on every failing run — after the step that had
  already failed.

## Cost

The loops are the largest consumer of the subscription, so they are built to
cost nothing when there is nothing to do.

**A plain guard runs before the model, every pass.** It asks Linear and GitHub
whether there is work, over ordinary HTTP with no model involved, and only wakes
a session if the answer is yes. An empty queue therefore costs one request, not
a session. Before this existed, 88% of roughly 3,900 daily passes were full
model sessions that discovered the queue was empty.

They run **Sonnet**, not the default. The model override lives in the private
Start Here doc's environment file.

**Do not restate the poll intervals here.** They live in `agents/run.sh` and
have already changed twice; a number copied into this file goes stale and then
seeds every new session with it. Read the script.

The one principle worth keeping in your head: **polling is cheap, so it should
be frequent.** If you ever find yourself slowing the loops down to save money,
check first whether the thing you are slowing down actually costs anything — it
probably does not, and you would be buying latency for nothing.
