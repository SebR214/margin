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
5. Research → `research.html` (Seb asked for it in chat, 25 Oct 2026; it sits in each page's nav array after Findings, with the word set in `copy.json`)
6. Events → `events.html` (SEB-423, agreed in chat 31 Oct 2026; it sits after Research, word set in `copy.json`). Lists the currency events that have a page, newest first, each linking to its page and to the home map on that day.

Logo links to `index.html`. Findings, how it works, fee tiers and agent
incidents stay live but are reachable by deep links only (from
`machine-room.html`'s "Read more" block and from each other), never in
the nav. Ask is hidden until its rebuild — nothing links to it. The nav
is generated from `copy.json`'s `nav` array into every page by the bake
step (`tools/bake_nav.py`); no page carries a hand-written header.

## Pages (layout, phones, charts)

Learned from Seb's reviews in the design chat, 27 Oct to 1 Nov. Every page change follows these, and is checked by reading
the page top to bottom at 375px and 1280px as a reader would, not only by the scripted checks. A page that renders without
errors can still make no sense.

### Every page

* One point per page, said in its headline. Every section serves that point. If a section has no reader who would care, cut it (the hourly price list on country pages went for this reason).
* A comparison is one chart or one table to read down, never the same sentence repeated per row. The reader should see the answer by scanning one column.
* Never show two versions of the same number on one page (this hour and the typical week) unless each says which it is.
* Reuse a chart the site already has before building a new one.
* A section built from a data step that stopped updating must not show old numbers as current. Check the data's own date when a page looks frozen.
* A line a reader would take as the whole market must be the whole market. Counts from a sample (the top 40 ads) say so or are not shown.

### Phones

* Nothing scrolls sideways. A wide table becomes stacked rows or a grid that fits the screen.
* The menu is a full screen sheet with big links and a Close button. The phone header is the logo and Menu only.
* No hover colour that sticks after a tap: hover styles sit inside `@media (hover:hover)`. No tinted "selected" row on a phone when the tap already scrolls to the detail.
* Text fills its column. Headings and notes wrap with `text-wrap: pretty`, never into a box narrower than the text around them. One width per section.
* No text under 13px.

### Charts

* A line, not an area fill, where the line can sit below zero. A fill that floats above the line reads upside down.
* Say which side is which in words against the zero line ("Stablecoin cheaper", "App cheaper"). No minus signs for the reader to decode.
* Missing data is a thin light grey dotted line joining the two ends, with one sentence under the heading saying what it means. No grey blocks, no words written on the chart.
* Axis labels are spaced by position so they never overlap. A chart starts at its first point, not on an empty stretch.
* Range buttons in words (Week, Month, Year, All), offered only when they show more than the shorter one.
* A popup says the number in words ("Stablecoin S$10.78 more expensive than the cheapest app"), not "+S$10.78 (1.08%)".

## Register (the language guide)

This section is the site's one language guide. Pages, agents and the writer model all follow it. `tools/check_copy.py`
reads the Words table below and fails any change that puts a "Never say" word in reader-facing text, and
`tools/writer_voice.py` gives the same table to the model. Change a word here and both follow.

### How the site writes

* Write for someone who has never worked in payments. Read a sentence aloud to a friend outside finance. If they would ask "what does that mean?", rewrite it.
* One idea per sentence. Sentences under 20 words, headings under 12.
* Every heading says what a reader would want to know: what a dollar costs them, or what changed for them. A number without its meaning is not a heading.
* Say why it matters in the same breath as the number. "A dollar costs 4.7% more than the official rate, up from 1.4% yesterday" beats "the gap grew 3.3%".
* Lead with a change only when it is unusual. A move back to a country's normal level is not news, so it does not lead the page.
* Money beats percent where there is an amount: "About S$56 on S$5,000" beats "1.12%". Round numbers in headings, exact figures in tables. One number per sentence at most where possible.
* Lead with the thing, not the source: "In Argentina a dollar costs..." not "According to our data...".
* No metaphors, no wordplay, no drama, no judgment, no guesses about the future, no punchy closing lines.
* No dashes and no semicolons in visible copy. No exclamation marks.
* "We" is the site: "our daily source", "our code spotted the change".
* The same word for the same thing on every page. The table below is the list.

### Naming

* Countries as a reader knows them. A currency shared by several countries is named by its region: "Central Africa" (Cameroon, the Central African Republic, Chad, the Republic of the Congo, Equatorial Guinea and Gabon share the CFA franc) and "West Africa" (Benin, Burkina Faso, Ivory Coast, Guinea-Bissau, Mali, Niger, Senegal and Togo). The country page says which countries share it.
* A central bank by its own English name the first time on a page ("the Central Bank of Egypt"), then "the central bank". A government as "{country}'s government". Never "the authorities", "officials", a capital city standing in for a government, or a person's name.
* A reason for a decision only as something the bank or government said, with a link. Never a reason of our own.
* Transfer apps by name are fine in body text and tables. "Apps like Remitly or Western Union" on first use. Never name Wise in a headline.

### Missing data

* A missed hour is a blank, never filled in. Say why when we know: "our collection was down", "we could not read the blockchain's fee".
* "Gap" means only the dollar gap. Missing data is "a blank" or "no price that hour".

### Written by a model

* Text an AI model wrote says so in one line under it, and that our code checked every number against our files before it went up.

### Words

| Say | Never say |
|---|---|
| the official rate | mid-market, mid rate, interbank rate, real exchange rate |
| the gap (how much more than the official rate a dollar costs, in %) | premium, spread, basis points, bps |
| a move in the gap, in % ("up 3.3%") | points, percentage points |
| cheaper, more expensive | dearer, pricier |
| the cheapest app (first use: transfer apps like Remitly or Western Union) | best app, fiat provider |
| the stablecoin way | stablecoin path, stablecoin route, dollar route |
| a stablecoin, a coin that stays worth one US dollar | crypto, cryptocurrency |
| people selling to each other | person to person, person-to-person, peer-to-peer, P2P, between people |
| exchanges, brokers | order book, order books, venue, venues, broker quote, broker quotes |
| a route (a sending pair: Singapore to the Philippines) | corridor |
| from exchange history, not our own checks | not seen by us, reported, not observed |
| usually, the typical value | median |
| buying at the asking price, setting your price and waiting | taker, maker |
| Central Africa, West Africa | Central African CFA, West African CFA |

* Numbers are computed from `data/`, never typed. Gaps stay gaps.
* Every reader-facing string lives in `copy.json`.

**Also banned in headings, subheadings, captions, labels and nav** (fine only in methodology and how-it-works deep sections):
fiat, rail, basis, bps, venue, on-ramp, off-ramp, P2P, parallel rate, median, decomposition, spread, liquidity, maker,
taker, VIP tier, measured hours, pass, collector, withheld, Wise. `tools/check_copy.py` enforces both lists.
