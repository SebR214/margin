# DESIGN.md: how pages look

Layout, phones, charts, colours and the nav. How the site writes is in `WORDS.md`. Sessions read both before touching a
page. When Seb decides something about a page in chat, it is written here in the same session or it does not exist.

## Palette (graphs and charts)

* `#817FCC` periwinkle — the primary data value (the dollar-route / stablecoin metric)
* `#D3D0CB` dust grey — comparison / secondary series
* `#3F3047` vintage grape — total / emphasis
* `#F0EBD8` eggshell — area fills

One mapping, every chart, no exceptions. Page chrome (text, background, borders) keeps the existing neutral greys; the palette above is for data. Indigo `#5A55E0` from UI-SPEC-2026-09-16 is retired.

The accent colors above are reserved for charts that compare two or more *named* things (a cost waterfall's legs, the multi-series history chart). A single-series trend chart (`js/chart.js`, used sitewide for "this one number over time") is not a comparison, so it renders in plain grey (`#6B6B6B` line, light grey fill, `#EDEDED` current-value badge) instead of periwinkle-on-eggshell — that combo read as an arbitrary mix of two accent colors with nothing to distinguish (SEB, 2026-09-25).

In a cost waterfall (`index.html`, `corridor.html`), the two "dollar-route" legs (buying the coin, selling it) do not share one color even though both are "cost" in kind — same color on two different bars reads as "these are the same number." First cost leg periwinkle, second cost leg eggshell with a thin periwinkle border (so it still shows against a white background); the rail/secondary leg stays dust grey, the total stays vintage grape (SEB, 2026-09-25).

## Nav (canonical, the only nav)

Countries, Routes, Sources, Findings, Research, Events, How it works, in that order. The logo links to the home page. The
nav is generated from `copy.json`'s `nav` array into every page by the bake step (`tools/bake_nav.py`); no page carries a
hand-written header. Pages not in the nav (how it was built, the machine room) are reached by links from other pages only. Fee tiers,
agent incidents, tape and corridor are redirects.

## Pages (layout, phones, charts)

Learned from Seb's reviews in the design chat, 27 Oct to 1 Nov. Every page change follows these, and is checked by reading
the page top to bottom at 375px and 1280px as a reader would, not only by the scripted checks. A page that renders without
errors can still make no sense.

### Every page

* One thing lives in one place. Every other page links to it and does not repeat it. Every link leads to something current: a moved page redirects, a retired page redirects to where its content went.
* One point per page, said in its headline. Every section serves that point. If a section has no reader who would care, cut it (the hourly price list on country pages went for this reason).
* A comparison is one chart or one table to read down, never the same sentence repeated per row. The reader should see the answer by scanning one column.
* Never show two versions of the same number on one page (this hour and the typical week) unless each says which it is.
* Reuse a chart the site already has before building a new one.
* A section built from a data step that stopped updating must not show old numbers as current. Check the data's own date when a page looks frozen.
* A line a reader would take as the whole market must be the whole market. Counts from a sample (the top 40 ads) say so or are not shown.

### Spacing, width, size (1 Nov 2026)

* Four gaps only. 8px between a heading and its own text, and between lines of one list (the money lines on a country page). 24px between separate points. 40px under the page headline (24px on a phone). 96px between sections (72px on a phone), with no rule line above them.
* Sizes: page headline 32px (26px on a phone), the lines under it 20px grey (17px on a phone), body text 17px, notes (time stamps, counts) 14px grey.
* A different gap must mean something you can name. If you cannot say why two gaps differ, make them the same.
* No width cap on text. Text runs the width of the page, so a short sentence stays on one line on a computer.
* One size for all body text on a page. A line that matters is never small or faint: if it is important, it is black, not 14px grey.
* Each page's spacing lives in one block in `css/site_page.css`. To change it, edit that block. Never add an override under an older rule.
* Home: the first screen is the headline and the lines under it. The grid starts when you scroll.

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
