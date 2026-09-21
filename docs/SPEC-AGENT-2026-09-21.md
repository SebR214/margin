# margin.wiki — the autonomous researcher, 21 Sep 2026

Direction agreed with Sebastian 21 Sep: the site is an autonomous researcher
you can watch working. It answers by visibly working, it notices things on
its own, it grows on commission, and it repairs itself in public. This spec
supersedes the ask-box and QA sections of SPEC-UI-2026-09-16. D1 (spark vs
index_pct disagreement), U6 (chart component), U7 layout items, R1/R2
(receipts), M1/M2 (machine room) stand as written there.

Context that forced this spec: on 21 Sep the deployed ask box failed its own
suggested questions. "Which country has the widest gap this hour?" — a chip
— returned "that couldn't be turned into a query", while the homepage rail
displayed the widest gap. "Why is South Africa not priced?" — a chip —
returned a refusal while the withheld reason sits in index_latest.json. The
How-it-works ask box, under a placeholder reading "Ask the agent how any
number was made", refused that exact question. The Singapore answer
returned a bare FX rate with no gap — a Google answer on a site whose whole
thesis is the gap.

Rules that apply to every issue below, in addition to the standing ones
(real CSVs only, no invented numbers, screenshot approval before
reader-facing merges, design system unchanged):

* A suggested question can never fail. Anything the site itself proposes —
  a chip, a placeholder, a "try asking" hint — must resolve through a
  tested path. If its data is missing this hour, the suggestion is not
  shown.
* No bare refusals, ever. Every failed answer names what was understood,
  gives the nearest real number or link, and says concretely what can be
  asked. "That couldn't be turned into a query" never ships again in any
  wording.
* Every country answer carries the site's frame: street price, official
  rate, the gap, the evidence count. If an answer could have come from
  Google, it is wrong even when it is correct.
* The agent's visible work is real. Streamed queries actually ran,
  streamed reasoning is the actual trace, and nothing is replayed as if
  live. Faking the theater is worse than having none.
* Every published claim traces to a query over stored files. No forecasts,
  no models — the agent may compare the present against its own recorded
  history and nothing else.

Order: A0 → A1–A4 + Q1–Q3 → V1 → (M1/M2 from prior spec) → N1 → C1.

## A0 — Audit: what is actually deployed

Before any code: post a state-of-the-world report. The public repo's
README and visible tree still describe the old SGD→PHP corridor product
(samples.csv, no ask feature, no API code), while margin.wiki serves the
new homepage with a live ask box, and api.margin.wiki's root 404s.
Establish and write down: what repo/branch/workflow actually deploys
margin.wiki and api.margin.wiki; where the ask implementation lives and
what it actually does (template matcher, NL→SQL, LLM — which model, which
key, what budget); why chips route through the same brittle path; whether
the README is stale or the repo split. Post the findings as a Linear
comment before changing anything. Everything below assumes this map
exists.

## A1 — Suggested questions answer from published aggregates

Every chip and every placeholder-suggested phrasing gets a fixed, tested
answer path reading from the published outputs (index_latest.json and
friends), not the query translator. "Widest gap this hour" reads the same
field the homepage rail reads. "Why is X not priced" reads the withheld
reason. Chips are generated from what the data can answer this hour; a
chip whose data is missing is not rendered. Answer templates carry the
frame rule above.

## A2 — The failure floor

Free-text questions that can't be answered resolve to the Denmark pattern,
which is the one good answer currently deployed: name the entity that was
understood, state plainly what is and isn't collected, give the nearest
real figure or link, list what can be asked. This is the floor under
everything, including V1 when its budget runs out.

## A3 — The ask box is an answer machine, not a chat log

The answer renders directly under the question box. Chips move below the
answer after asking. No scrolling to find your answer. The timestamp
labels the data, not the asking: "answered from the 02:00 UTC pass", not
"ASKED · this hour". The capability line stops saying "ask about anything
in there" and names the classes: what a dollar costs in any of the tracked
countries, why one isn't priced, the cheapest way to send money on the
tracked corridors, how a price moved over time, how any published number
was made, how the site works. One chip demonstrates each class.

## A4 — Route by question kind

"How are the numbers made", "how was this number made", and everything
methodology-shaped routes to prose or to the R1 receipt for the number in
question — never to SQL. The How-it-works ask box must be able to answer
the exact question its placeholder invites.

## Q1 — The golden set

~50 questions in CI: every chip, every placeholder phrasing, close
variants, untracked countries (the Denmark case), entity typos, one
adversarial handful. Runs against a built site on every ask-touching PR.
Any suggested-question failure or bare refusal blocks the merge. Every new
chip or placeholder enters the set in the same PR that adds it.

## Q2 — The critic

A new loop with no code access. Once a day it opens the live site in a
real browser as a stranger: clicks every chip, asks five fresh questions
of its own invention, opens receipts, walks the nav on desktop and phone
widths. It files Linear issues with screenshots, judged on one rubric:
would this embarrass the site in front of a senior payments person. Not
"did it error" — "is it bad". Its issues route to product for triage like
any other.

## Q3 — Review on the deployed preview

Reader-facing PRs are approved from the deployed preview in a browser, not
from the diff. The reviewer types the chips, asks one free-text question,
and attaches what it saw to the review. Sebastian's screenshot approval
stays on top of this, unchanged.

## V1 — The visible agent (B5 done properly)

Free-text ask becomes an agentic loop with a real LLM: inspect the schema,
write a query, run it against the browser dataset (B2 bundle where
possible, API otherwise), look at the result, decide whether it answers
the question, revise up to 3 attempts, then compose the answer in the
site's frame. The whole loop streams visibly — the query appears, runs,
rows land, the chart assembles (U6 component) from real rows. On failure
the visitor watched three real attempts and gets the A2 floor with what
the data couldn't support.

Budget: hard monthly cap on the Anthropic key, per-IP rate limiting,
cheapest model that holds up. When the budget is spent, the box says so
plainly and falls back to A1+A2 paths. Never a canned answer pretending to
be live.

## N1 — It notices: auto-published investigations

Every pass, after publication, the agent scans what moved against its own
recorded history: gap deltas over 24h/7d, corridor flips, sources going
quiet, withheld countries returning. Notability thresholds are derived
from the recorded distribution of past moves, written down in the repo,
and cited in every finding — not vibes, not hardcoded per country.

On trigger, it investigates: queries over stored history, cross-source
checks within the pass, then publishes a finding — a few sentences in the
house voice, the U6 chart, the receipts, and its full reasoning trace
behind a "how I found this" link. The homepage top story is the latest
machine finding, timestamped, next revision on the hour.

Findings become living objects: each carries its supporting query, re-run
on schedule. When the evidence fades, the finding archives itself,
visibly, with the date and the re-run that killed it — archived, never
silently deleted. This replaces hand-curated findings and retires the
OFX-card class of problem: no card ships on a pattern the current data
doesn't show, and no card outlives its evidence.

Wife test applies to every generated sentence. WRITING-RULES.md applies.
If the pass has nothing notable, nothing is published — an empty day is an
honest day.

## C1 — It grows: commissions

A free-text ask naming an untracked country stops being a dead end: "Not
tracked — want me to try?" On yes, a probe run queues: the agent hunts
candidate sources for that currency, tests each against the evidence rule,
and streams every step into the machine room feed (B4 events): source
found, source tested, offers seen, verdict. Success: the country goes live
on the next pass with a plaque on its country page — "commissioned by a
visitor, {date}" — and the probe log linked. Failure: a public page of
what was tried and why each source failed, linked from the ask answer, in
the same pattern as the existing Ethiopia story. The evidence rule does
not bend for commissioned countries: commissioning lowers nothing, it only
aims the machine.

Rate-limit commissions (a handful in flight; a queue with honest position
numbers). Every probe step must originate from a real attempt log — no
synthetic progress.

## Sequencing and dependencies

A0 first, alone, findings posted. A1–A4 and Q1–Q3 land together next —
they stop the bleeding and nothing reader-facing merges without them. V1
needs the key wired and D1 fixed (no charts before D1). M1/M2 from the
prior spec land with or before N1 and C1, which publish into them. N1
before C1: it makes the site alive daily with zero visitors; C1 is the
bigger lift and the bigger wow, and it needs B4's event stream anyway.
