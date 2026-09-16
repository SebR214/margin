# margin.wiki — start here

Paste this into a new chat. It is deliberately short; the repo holds the detail.

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
| Server | `78.47.61.109` — Hetzner, Falkenstein, `ssh -i ~/.ssh/margin_agent root@…` |
| Site | margin.wiki (GitHub Pages, from `main`) |
| API | api.margin.wiki → Caddy → `127.0.0.1:8899` REST, `:8900` MCP, `:8901` ask |
| Repo | `SebR214/margin` (public) — code and PRs only |
| Work | Linear — [linear.app/sebastian-roervig](https://linear.app/sebastian-roervig), project `margin.wiki`, team `SEB`. An issue is `https://linear.app/sebastian-roervig/issue/SEB-<n>` |

Three loops on the server — `margin-builder`, `margin-reviewer`,
`margin-product` — take work from Linear and open PRs. `margin-serve` runs the
API. Collection runs on GitHub Actions (`collect.yml`), self-chaining every 30
minutes.

Credentials live in `/etc/margin/env` (loops) and `/etc/margin/ask.env` (the
metered Anthropic key, read by `margin-serve` **only** — putting it in the
shared file silently moves every loop onto metered billing and drained $10 in
twenty minutes once already).

## How to talk to the work

```bash
export LINEAR_API_KEY=...            # in /etc/margin/env on the server
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

## State, 15 September 2026

**Shipped:** the index (59 currencies), REST + MCP API, `/ask`, commission
(`request_series` → Linear, sources probed and verified), standing asks over
RSS, findings, weekly snapshot, stress-signal record, data page, calculator,
provenance on every emitted file, a browser bundle, an SSE event stream.

**In flight:** a nine-issue plan, `SEB-38`–`SEB-47`. Backend track (B1–B4) is
merged. UI track (U1, U2, U5, U3, U4) is building — **U1 is awaiting
Sebastian's screenshot approval as PR #94** and everything else is behind it.

**Waiting on Sebastian:**

1. Approve or reject **U1** (PR #94). Everything UI is blocked behind it.
2. **SEB-49** — Algeria moved 14.3 index points in an hour with the official
   rate flat. Full evidence, no parallel rate on file. Needs an outside check or
   a decision to add a source.
3. **B5** (`SEB-45`) — needs a capped Anthropic key, $25/month, to go live.

## Things that have bitten, twice each

- **A stale line in `ROADMAP.md` outranks a fresh issue** and will silently stop
  the builder. When a decision changes, change the ROADMAP, not just a comment.
- **An emitted file left out of `collect.yml`'s staging list kills collection.**
  It commits, then refuses to rebase, and 21 hours of unbackfillable readings
  were lost this way. There is now a fallback that stages tracked changes and
  warns.
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

They run **Sonnet**, not the default. `MARGIN_MODEL` in `/etc/margin/env`
overrides it.

**Do not restate the poll intervals here.** They live in `agents/run.sh` and
have already changed twice; a number copied into this file goes stale and then
seeds every new session with it. Read the script.

The one principle worth keeping in your head: **polling is cheap, so it should
be frequent.** If you ever find yourself slowing the loops down to save money,
check first whether the thing you are slowing down actually costs anything — it
probably does not, and you would be buying latency for nothing.
