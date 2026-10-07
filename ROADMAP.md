# Roadmap

Rewritten 2026-10-07 to one page. The full old version is `docs/archive/ROADMAP-to-2026-10-07.md`. The work queue is Linear, not this file.

## What the site is

margin.wiki prices a dollar in about 60 currencies every hour, using the dollar a person can actually buy there: a dollar stablecoin, on person-to-person boards and order books, against the official rate. Currencies with no price this hour say why, in plain words. It also prices sending money on 7 routes, all fees in.

Sending money with a stablecoin was tested against apps and banks. It is published as evidence that the stablecoin is a real dollar, not as a cheaper way to send money.

## Three surfaces, one set of files

- The site, built from the CSVs and JSON in `data/`.
- The API at api.margin.wiki: `/dollar_cost`, `/compare_routes`, `/series`, `/query`, `/request_series`, plus `/ask` and `/mcp`.
- Ask: a question in, the SQL, the answer and the source file out.

## Invariants

Collection integrity comes first. History can't be rebuilt, so collection breadth and reliability beat new features.

Data:
- Every number is computed from `data/`. Deterministic code owns numbers. A model never writes a number.
- Loud failure. Persistence before display. One capture per UTC hour.
- Gaps stay gaps. The live layer is never backfilled or interpolated.
- History is its own layer in `data/history/`, "reported, not observed", source on every row, never feeding the index, a price or unbroken hours (`tools/check_history_isolation.py`).
- Every row carries its fee regime.
- The stablecoin is checked against a dollar. Where a venue lists both, the USDT to USDC spread is measured and published.
- METHODOLOGY.md says whether each shown number is measured, assumed or invisible. Method changes bump `index_version`.

API and Ask:
- SQL is read-only, capped at 5,000 rows, with a 10-second timeout.
- Every query is logged. No personal data is stored.
- Every answer cites the file it came from.
- A new series starts at zero history and says so.
- A rejected source is shown as rejected, with what was probed and why.

Pages:
- Money first, percent second. No jargon on the front page. "Stablecoin", never "crypto".
- Every chart hovers to the nearest real point. `js/chart.js` is the reference.
- No hand-written copy that can go stale against the data.

Agents:
- No agent weakens a test, check or gate to make its own work pass.
- Insufficient evidence is a valid answer.
- Agents propose changes to this file by PR and say what changed.

## Out of scope

Enterprise payout pricing, OTC desks, local cash-out fees and KYC limits. Stated, never estimated.
