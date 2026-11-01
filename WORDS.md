# WORDS.md: how the site writes

The site's one language guide. Pages, agents, Claude Code sessions and the writer model all follow it. `tools/check_copy.py`
reads the Words table below and fails any change that puts a "Never say" word in reader-facing text, and
`tools/writer_voice.py` gives the same table to the model. Change a word here and both follow. Layout and charts are in
`DESIGN.md`.

## How the site writes

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

## Naming

* Countries as a reader knows them. A currency shared by several countries is named by its region: "Central Africa" (Cameroon, the Central African Republic, Chad, the Republic of the Congo, Equatorial Guinea and Gabon share the CFA franc) and "West Africa" (Benin, Burkina Faso, Ivory Coast, Guinea-Bissau, Mali, Niger, Senegal and Togo). The country page says which countries share it.
* A central bank by its own English name the first time on a page ("the Central Bank of Egypt"), then "the central bank". A government as "{country}'s government". Never "the authorities", "officials", a capital city standing in for a government, or a person's name.
* A reason for a decision only as something the bank or government said, with a link. Never a reason of our own.
* Transfer apps by name are fine in body text and tables. "Apps like Remitly or Western Union" on first use. Never name Wise in a headline.

## Missing data

* A missed hour is a blank, never filled in. Say why when we know: "our collection was down", "we could not read the blockchain's fee".
* "Gap" means only the dollar gap. Missing data is "a blank" or "no price that hour".

## Written by a model

* Text an AI model wrote says so in one line under it, and that our code checked every number against our files before it went up.

## Words

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
