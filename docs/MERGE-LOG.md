# Merge log

Every PR self-merged by the orchestrating session (not a human, not the repo's own
Linear-driven agent loop) under the standing authorization Sebastian gave directly in
that session's chat, plus its verification evidence. This exists because SEB-77's core
problem was an agent citing an approval nobody else could check — this file is the
record that should have existed then. Entries are append-only, oldest first.

Scope: this log covers self-merges by the *orchestrating chat session* only. The
repo's own separate Linear-driven agent loop (agents/PRODUCT.md, BUILDER.md,
REVIEWER.md, COMMISSION.md) keeps its own record via Linear issues/PR review comments,
not this file.

---

## #161 — Hotfix: backfill payout_type column, unbreak the hourly collector
**Merged:** 2026-09-26T07:18:36Z
**Why self-merged:** live production outage (collector chain down ~3.5h), narrowly-scoped
infra fix, not a product/design decision.
**Evidence:** root cause diagnosed and reproduced locally (11-vs-12 column mismatch
breaking DuckDB's CSV sniffer in tools/emit_bundle.py); fix verified against a real
`read_csv_auto` call matching emit_bundle.py's own invocation; `collector_providers.py
--selftest` passed; confirmed the *next live* collect.yml run (36226399062) went green,
not just local tests.

## #162 — Add an outside watchdog for the collector chain
**Merged:** 2026-09-26T07:55:10Z
**Why self-merged:** monitoring/alerting addition, zero runtime risk to the live site or
collector (reads git/gh history only, writes nothing to data/ or any page).
**Evidence:** `tools/check_collector_health.py` run against the live repo (reported
healthy, correct output); new `collector_watchdog.yml` triggered manually post-merge and
confirmed a real, successful Actions run (36228240423, 17s) — not just merged and hoped.

## #163 — Add tools/rebase_onto_main.sh
**Merged:** 2026-09-26T08:24:04Z
**Why self-merged:** dev-only tooling, not referenced by collect.yml or any page, zero
runtime impact on the live site.
**Evidence:** live end-to-end test on a throwaway branch (forced real conflicts against
current main, confirmed auto-resolution + regeneration + both check_copy.py and
check_index_consistency.py passing afterward), plus a separate live repro of the
"real conflict, not auto-resolvable" exit-1 path. A real bug was found in testing
(associative arrays silently broke under macOS's default bash 3.2) and fixed with an
explicit version guard before merge, verified under both bash 3.2 (fails loud, as
intended) and bash 5 (works).

## #166 — Phase 0: add tools/check_inventory.py
**Merged:** 2026-09-26T08:50:42Z
**Why self-merged:** FINAL spec amendment 1 explicit self-merge authorization once the
gate's own CI passes; this phase has nothing to gate itself against yet (it's the first
gate), so "passes" means it correctly flagged the real, expected #160 regression.
**Evidence:** gate correctly identified index.html's real chart/table loss vs the
7078efd09 baseline; confirmed the new checks.yml workflow is genuinely wired to GitHub
pull_request/push events (two real Actions runs observed, not just runnable by hand).

## #165 — Phase 1: mechanical restore
**Merged:** 2026-09-26T08:52:47Z (orchestrator; originally left unmerged by the building
subagent under an earlier, since-amended "never merge yourself" instruction)
**Why self-merged:** FINAL spec amendment 1, all three gates (inventory, copy,
consistency) passed clean after rebase.
**Evidence:** independently re-ran all three checks myself after rebasing onto main a
second time (main advanced twice mid-review, once from the collector bot, once from
another session's direct chart-color commits); confirmed no drift after regenerating
index.html; confirmed the next live collect.yml run (36231121344) went green.

## #167 — Phase 2: add VISION.md
**Merged:** 2026-09-26T08:57:24Z (self-merged by the building subagent)
**Why self-merged:** FINAL spec amendment 1, root-file addition + doc edits only, no
page content touched.
**Evidence:** the harness itself flagged this subagent's report for extra scrutiny
("Merge Without Review"). Orchestrator independently re-verified against origin/main
directly (not the subagent's self-report): confirmed VISION.md's text is byte-verbatim
what the amendment specified, and confirmed all four agents/*.md files actually carry
the "Read VISION.md before anything below" instruction (the orchestrator's first check
was against a stale local git checkout and produced a false negative — corrected after
re-checking origin/main directly; noted here for the record, not hidden).

## #168 — Phase 3: home page "Where the line runs" country-premium strip
**Merged:** 2026-09-26T09:28:19Z (self-merged by the building subagent)
**Why self-merged:** FINAL spec amendment 1, additive-only new section, all three gates
passed.
**Evidence:** orchestrator independently verified the merged origin/main content
directly — markers present, linked to country.html?ccy=X, footer sentence matches the
spec's template with real computed values (Algeria +90.4%, consistent with VISION.md's
illustrative ~90%). Re-ran check_inventory.py/check_copy.py/check_index_consistency.py
and check_collector_health.py myself after syncing a stale local checkout.

## #164 — SEB-124: undo the frozen-header widening and backfill on provider_quotes.csv
**Merged:** 2026-09-26T10:30:30Z (orchestrator)
**Why self-merged:** FINAL spec amendment 2 (any pipeline PR, any filer, gets the same
gates: no VISION.md rule touched, inventory+copy+CI pass, data change verified against
real git history, next collector run green). Filed by the repo's own separate
Linear-driven agent loop as a correction to the orchestrator's own #161 hotfix — the
orchestrator deliberately did NOT self-merge on the first pass specifically because the
PR's substance was "skipping review was the violation," and recommended Sebastian post
a human approval comment instead; amendment 2 then explicitly authorized self-merging
data-schema fixes like this one once verified against git history, which is what
happened.
**Evidence:** independently verified, against raw git history (not the PR's own
description) that the pre-#161 parent commit really did have exactly 10,680 rows at
11 fields and 200 at 12 — matching the PR's claimed split exactly; confirmed the
reverted CSV's legacy portion is byte-identical to that parent commit's file, header
included; confirmed collector_providers.py's own selftest exercises a real sidecar
write/read round-trip, not just an assertion. Branch needed rebasing twice (main moved
under it twice during review, from ongoing collector commits and Phase 4 landing);
resolved by manually re-splitting each newly-landed batch of main-side rows into the
same 11-column-CSV-plus-sidecar shape, then regenerating data/bundle/* and
manifest_latest.json from scratch rather than hand-merging binary parquet conflicts.
Triggered a fresh live collect.yml run after merge to confirm the new schema writes
correctly in production, not assumed from local tests.

## #169 — Phase 4: fold findings into sending-money, add crossover sentences
**Merged:** 2026-09-26T~10:1x:xxZ (self-merged by the building subagent)
**Why self-merged:** FINAL spec amendment 1/2, all three gates passed; findings.html's
inventory count was already 0/0/0 in the committed baseline (its content was always
plain divs with no detected chart/table/interactive element), so retiring it to a
redirect stub caused no inventory shrinkage by construction — no exemption, no baseline
edit.
**Evidence:** orchestrator independently verified against origin/main directly: confirmed
findings.html is a genuine redirect stub, confirmed the crossover sentence templates
(`crossoverWinTemplate`/`crossoverNeverTemplate`) exist in copy.json exactly as
specified and are rendered client-side with real computed `pct`/`sending_words` values,
not hardcoded strings.

## #171 — Phase 5: push collect.yml/fees.yml under the GitHub App identity
**Merged:** 2026-09-27T03:28:47Z
**Why self-merged:** FINAL spec amendment 1/2, highest-stakes phase (production push
credentials) but explicitly gated on live proof, not a guess.
**Evidence:** found and fixed two real bugs via live `workflow_dispatch` test runs before
touching main — a duplicate `Authorization` header (actions/checkout's persisted credential
collided with the App token's, both writing to `http.https://github.com/.extraheader`,
GitHub 400'd with "Duplicate header") fixed via `persist-credentials: false`; and a wrong
numeric id in the bot's noreply email (used the App's own ID instead of the bot user
account's id, confirmed via `gh api users/margin-agents%5Bbot%5D --jq .id` -> 329969015),
which meant the first "successful" test commit LOOKED right but GitHub never linked it to
the bot account (`author.login: null`). After both fixes, confirmed on a genuinely fresh
test commit AND on a real production commit on main post-merge:
`gh api repos/SebR214/margin/commits/<sha> --jq '.author.login'` returned
`"margin-agents[bot]"` with `author_type: "Bot"` both times — the real link, not just a
matching name. One of the live test dispatches (on a feature branch, before merge)
incidentally confused the live chain's un-scoped alive-check and caused a real ~1h+ gap in
production collection, caught by the watchdog and fixed separately in #173 (that repo-side
fix is outside this log's scope — see its own PR).

## #172 — SOURCES 1-2: second comparison feed, direct quotes round 2
**Merged:** 2026-09-27T05:29:16Z
**Why self-merged:** additive tooling/docstring change only (one file:
collector_providers.py), zero runtime risk, all gates passed clean; left open initially per
the parent spec's explicit "runs after FINAL" ordering, merged once Phase 5 + branch
protection were confirmed done.
**Evidence:** a documented, live-verified NEGATIVE result, not a shortcut -- probed Monito,
RemitFinder, iCompareFX, CompareRemit (all blocked: CloudFront/Cloudflare walls, robots.txt
disallow, or no real per-provider rate data) and re-probed Remitly, Western Union,
MoneyGram, WorldRemit, Xe, Ria, Xoom plus closed out the DBS Singapore redirect chase (all
still blocked per the same HARD RULES standard: no login, no headless browser, no CAPTCHA
bypass). `collector_providers.py --verify` and `--selftest` both passed (including new
synthetic fixtures for the not-yet-live second-feed precedence logic), plus
check_inventory.py/check_copy.py/check_index_consistency.py all clean.
