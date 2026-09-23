DESIGN.md — single source of truth

Every reader-facing decision lives here. If a rule is not in this file, it is not a rule. Sessions read this before touching any page. When Seb decides something in chat, it gets written here in the same session or it does not exist.

## Palette (graphs and charts)

* `#817FCC` periwinkle — the primary data value (the dollar-route / stablecoin metric)
* `#D3D0CB` dust grey — comparison / secondary series
* `#3F3047` vintage grape — total / emphasis
* `#F0EBD8` eggshell — area fills

One mapping, every chart, no exceptions. Page chrome (text, background, borders) keeps the existing neutral greys; the palette above is for data. Indigo `#5A55E0` from UI-SPEC-2026-09-16 is retired.

## Nav (canonical, the only nav)

1. The index → `the-index.html`
2. Sending money → `sending-money.html` (drop this entry if the page was killed)
3. Findings → `findings.html`
4. How it works → `how-it-works.html`

Logo links to `index.html`. Ask, machine room and corridor pages are reachable by deep links only, never in the nav. The nav is generated from `copy.json`'s `nav` array into every page by the bake step; no page carries a hand-written header. As of today `copy.json`'s nav still points at `calculator.html` and `methodology.html` — that is the bug, fix it there once.

## Register

* "best fiat provider", never "best ordinary way to send money"
* "stablecoin route", never "buying crypto" or "the crypto way"
* "buying it now" = taker, "waiting for your price" = maker; use the plain form in reader-facing text, the technical term in methodology
* Numbers are computed from `data/`, never typed. Gaps stay gaps.
* Every reader-facing string lives in `copy.json`.
