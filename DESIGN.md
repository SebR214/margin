DESIGN.md — single source of truth

Every reader-facing decision lives here. If a rule is not in this file, it is not a rule. Sessions read this before touching any page. When Seb decides something in chat, it gets written here in the same session or it does not exist.

## Palette (graphs and charts)

* `#817FCC` periwinkle — the primary data value (the dollar-route / stablecoin metric)
* `#D3D0CB` dust grey — comparison / secondary series
* `#3F3047` vintage grape — total / emphasis
* `#F0EBD8` eggshell — area fills

One mapping, every chart, no exceptions. Page chrome (text, background, borders) keeps the existing neutral greys; the palette above is for data. Indigo `#5A55E0` from UI-SPEC-2026-09-16 is retired.

The accent colors above are reserved for charts that compare two or more *named* things (a cost waterfall's legs, the multi-series history chart). A single-series trend chart (`js/chart.js`, used sitewide for "this one number over time") is not a comparison, so it renders in plain grey (`#6B6B6B` line, light grey fill, `#EDEDED` current-value badge) instead of periwinkle-on-eggshell — that combo read as an arbitrary mix of two accent colors with nothing to distinguish (SEB, 2026-09-25).

In a cost waterfall (`index.html`, `corridor.html`), the two "dollar-route" legs (buying the coin, selling it) do not share one color even though both are "cost" in kind — same color on two different bars reads as "these are the same number." First cost leg periwinkle, second cost leg eggshell with a thin periwinkle border (so it still shows against a white background); the rail/secondary leg stays dust grey, the total stays vintage grape (SEB, 2026-09-25).

## Nav (canonical, the only nav)

1. Home → `index.html`
2. Sending money → `sending-money.html`
3. Countries → `the-index.html`
4. How it was built → `machine-room.html`

Logo links to `index.html`. Findings, how it works, fee tiers and agent
incidents stay live but are reachable by deep links only (from
`machine-room.html`'s "Read more" block and from each other), never in
the nav. Ask is hidden until its rebuild — nothing links to it. The nav
is generated from `copy.json`'s `nav` array into every page by the bake
step (`tools/bake_nav.py`); no page carries a hand-written header.

## Register

Write for someone who has never worked in payments. Read a sentence aloud
to a friend outside finance — if they'd ask "what does that mean?",
rewrite it. One idea per sentence. Headings under 12 words, sentences
under 20 words. No metaphors, no wordplay, no dramatic short closing
lines. No dashes and no semicolons in visible copy. Name real things
("Sending money from Singapore to the Philippines," "Apps like Wise")
instead of jargon. Money beats percentages: "About S$56 on S$5,000" beats
"+1.12%." Round numbers ("99%," not "99.3%") in headings; exact figures
can live in tables. One number per sentence at most.

* "apps like Wise" (or "transfer apps like Wise"), never "fiat provider" or "best ordinary way to send money"
* "stablecoins (digital dollars)" on first use per page, then "stablecoins" or "the stablecoin route" — never "buying crypto" or "the crypto way"
* "buying it now" (not "taker"), "waiting for your price" (not "maker") in reader-facing text; the technical term is fine in methodology / how-it-works deep sections only
* "sending X to Y" instead of "corridor" or "route" in headings, captions and labels
* "the typical value" or "usually" instead of "median"; "not enough data" instead of "withheld"
* Numbers are computed from `data/`, never typed. Gaps stay gaps.
* Every reader-facing string lives in `copy.json`.

**Banned in headings, subheadings, captions, labels and nav** (fine only in
methodology / how-it-works deep sections): fiat, rail, corridor, route,
basis, bps, venue, on-ramp, off-ramp, P2P, parallel rate, median,
decomposition, spread, liquidity, maker, taker, VIP tier, measured hours,
pass, collector, withheld. `tools/check_copy.py` enforces this list
against copy.json and the baked pages — run it before any reader-facing
change ships.
