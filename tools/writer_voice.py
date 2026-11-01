#!/usr/bin/env python3
"""The writer's voice (SEB-423 step 4): what tools/writer.py tells the model, and the check its words must pass.

tools/writer.py owns the pipeline (the model call, the number audit, the stored files, the collect.yml step). This file owns
only the words: the instructions sent to the model, and check_voice(), which rejects text that does not sound like the site.
Keep the pipeline in writer.py and import from here:

    from writer_voice import EVENT_INSTRUCTIONS, DAILY_INSTRUCTIONS, check_voice, check_event_output

The voice is the site's own, as it reads on margin.wiki today (WORDS.md, the 27 Oct words pass): short plain
sentences, one idea each, the same word for the same thing on every page.

What the pages read (js/event.js, js/home.js). A file shows only when audit.passed is true and, if present, voice.passed is true.

    data/event_prose/{event id}.json
        {"id": "IQD-official_break-2026-10-09", "written_utc": "...", "model": "...",
         "paragraphs": ["...", "..."],                      two paragraphs, plain text, "[1]" marks a source
         "sources": [{"title": "...", "url": "https://...", "site": "reuters.com"}],
         "audit": {"passed": true, "checked_utc": "...", "failures": []},
         "voice": {"passed": true, "problems": []}}

    data/home_prose.json
        {"written_utc": "...", "facts_as_of": "...", "about_ccy": "MAD", "model": "...",   about_ccy: the headline's country
         "sentences": ["...", "..."],                       two at most, no links
         "audit": {"passed": true, ...}, "voice": {"passed": true, "problems": []}}

    python3 tools/writer_voice.py --self-test
"""
import os
import re
import sys

# --------------------------------------------------------------------------------------------- the words every page uses
# One word per idea, the list agreed on 27 Oct. The model gets the left side as the word to use and the right side as words
# it must never write. check_voice() enforces the right side.
# The Words table in WORDS.md is the one list (1 Nov). check_copy.py enforces it on the pages, and the model gets the same rows.
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from check_copy import words_table  # noqa: E402

WORDS = words_table()

# Words that make the site sound like a news wire or a sales page. The pages never use them.
BANNED = sorted({w for _, ws in WORDS for w in ws if w.lower() not in ("reported",)} | {
    "USDT", "Tether", "black market", "parallel rate", "parallel market",
    "plunge", "plunged", "plummet", "plummeted", "soar", "soared", "skyrocket", "skyrocketed", "crash", "crashed", "tumble",
    "tumbled", "slump", "slumped", "spike", "spiked", "surge", "surged", "collapse", "collapsed", "freefall", "meltdown",
    "regime", "authorities", "officials", "amid", "amidst", "notably", "significantly", "dramatic", "dramatically",
    "unprecedented", "historic", "crisis", "shock", "brave", "bold", "desperate", "finally", "it is worth", "importantly",
    "in a move", "sent shockwaves", "devalue", "devalued", "devaluation", "fiat", "rail", "corridor", "we believe", "likely",
    "expected to", "analysts",
})

MAX_WORDS = 24          # WORDS.md asks for under 20; a few words of room for a country or bank name

_WORDS_LINES = "\n".join("  %s. Never: %s." % (say, ", ".join(nv)) for say, nv in WORDS)

# --------------------------------------------------------------------------------------------- shared rules
_RULES = """How the site writes. Follow every line.

- Short sentences, one idea each, under 20 words. Plain words a person outside finance knows.
- No dashes of any kind, no semicolons, no exclamation marks, no questions. No headings, no lists, no bold.
- Past tense for what happened. Dates as "7 Oct 2026", or "7 Oct" when the year is clear.
- Every number says what it means for someone buying a dollar there, in the same sentence. A number alone is not enough.
- The same word for the same thing, always. Say, and never say:
{words}
- Money and dates first, percent second. Write a number exactly as it appears in the input, with the same rounding.
- No metaphors, no drama, no judgment, no guesses about the future. Do not end on a punchy line.
- "We" is the site: "our daily source", "our code spotted the change".
- Never use these words either: {banned}.
"""

EVENT_INSTRUCTIONS = (_RULES + """
Your job: write two short paragraphs for one event page on margin.wiki. The page already shows a chart and a table with
every number, so you explain, you do not repeat the table.

Input: the event record (JSON, the only source of numbers) and up to 5 search results about the announcement.

Paragraph 1, what it meant for someone buying a dollar, from the record only. Do not repeat the table. Say which rate moved,
by how much and when, then what that meant: if the record has a street price, how much more people already paid on the
street before the official rate moved, and how much of that gap the official rate closed. If the record has no street
price, say what a dollar cost at the official rate before and after. 2 to 4 sentences.

Paragraph 2, what the government or central bank did, from the search results only: what was announced, by whom, on what
date. 2 to 4 sentences. Every sentence that comes from a search result ends with its marker, like [1] or [2], numbered in
the order of your sources list. If no search result clearly describes this announcement, write one sentence saying we found
no announcement for that date, with no marker, and return an empty sources list.

Naming:
- The central bank by its own English name the first time, as the source gives it ("the Central Bank of Egypt"), then
  "the central bank". The government as "{{country}}'s government". Never "the authorities", "officials", a capital city
  standing in for a government, or a person's name.
- A reason for the decision only as something the bank or government said, with its marker: "The central bank said it
  wanted to close the gap with the street price [1]." Never give a reason of your own.

Never:
- a number that is not in the event record, even if a search result has it. Leave the number out instead.
- the IMF, loans, inflation, elections or other countries, unless a cited result ties them to this announcement.
- words like devalue, crisis, collapse, plunge or surge. Say the rate "rose" or "fell" and by how much.

Style example, from the Iraq page (do not reuse its numbers or dates):
  "Iraq's government raised the official rate on 7 Oct. Our daily source for the official rate took until 15 Oct to show
  the full rise."
  "The street price rose 3.0% in the five days before 7 Oct, then jumped on the day the new rate was announced."

Return JSON only, no other text:
{{"paragraphs": ["...", "..."], "sources": [{{"title": "...", "url": "https://...", "site": "..."}}]}}
""").format(banned=", ".join(BANNED), words=_WORDS_LINES)

DAILY_INSTRUCTIONS = (_RULES + """
Your job: write the lines under the margin.wiki home page headline. The headline already says, for the country whose gap
moved most since yesterday, what a dollar costs there now against the official rate and what it cost yesterday. Your first
sentence says what that means: how it compares with the usual level there, from the facts file. Do not repeat the headline's
numbers. Add a second sentence only if another item in the facts file is as big for a reader, and link it to the first by
place or by kind (another country crossing the same line, an event in the same country). Never list unrelated items.

Input: the facts file (JSON), the only source. It holds the largest move of the last 24 hours and what changed in the last
7 days: countries that crossed 5% over the official rate, events, sources added, findings whose retest changed, routes
where the stablecoin became cheaper or more expensive than the cheapest app.

Write at most 2 sentences. No links, no markers. If the facts file has no largest move, return an empty list: the page then
keeps its fixed headline and needs nothing under it.

Never write a number that is not in the facts file. Never say why something moved.

Style example, under a headline about Morocco (do not reuse its numbers or names):
  "That is about twice the usual level there over the last 30 days. Morocco crossed 5% over the official rate on 30 Oct."

Return JSON only, no other text:
{{"sentences": ["...", "..."]}}
""").format(banned=", ".join(BANNED), words=_WORDS_LINES)


# --------------------------------------------------------------------------------------------- the check
_DASH = re.compile(r"[‒–—―]|\s-\s|--")
_MARK = re.compile(r"\[(\d{1,2})\]")


def _sentences(text):
    t = _MARK.sub("", text)
    return [s.strip() for s in re.split(r"(?<=[.!?])\s+", t) if s.strip()]


def check_voice(text):
    """Problems with one paragraph or sentence block, as a list of short strings. Empty means it sounds like the site."""
    out = []
    if _DASH.search(text):
        out.append("dash")
    if ";" in text:
        out.append("semicolon")
    if "!" in text:
        out.append("exclamation mark")
    if "?" in text:
        out.append("question")
    low = " " + re.sub(r"\s+", " ", text.lower()) + " "
    for w in BANNED:
        if re.search(r"(?<![a-z])" + re.escape(w.lower()) + r"(?![a-z])", low):
            out.append("word: " + w)
    for s in _sentences(text):
        n = len(s.split())
        if n > MAX_WORDS:
            out.append("long sentence (%d words): %s" % (n, s[:60]))
    return out


def check_event_output(obj):
    """Problems with the model's event JSON: shape, voice and source markers. Empty means it can go to the number audit."""
    out = []
    paras, srcs = obj.get("paragraphs"), obj.get("sources")
    if not isinstance(paras, list) or len(paras) != 2 or not all(isinstance(p, str) and p.strip() for p in paras):
        return ["needs exactly two paragraphs"]
    if not isinstance(srcs, list):
        return ["sources must be a list"]
    for i, s in enumerate(srcs):
        if not isinstance(s, dict) or not re.match(r"^https?://", str(s.get("url", ""))):
            out.append("source %d has no http link" % (i + 1))
    for i, p in enumerate(paras):
        out += ["paragraph %d: %s" % (i + 1, x) for x in check_voice(p)]
        for m in _MARK.findall(p):
            if not 1 <= int(m) <= len(srcs):
                out.append("paragraph %d: marker [%s] has no source" % (i + 1, m))
    if _MARK.search(paras[0]):
        out.append("paragraph 1 comes from the record only, it takes no source markers")
    if srcs and not _MARK.search(paras[1]):
        out.append("paragraph 2 cites none of its sources")
    used = {int(m) for m in _MARK.findall(paras[1])}
    if srcs and used != set(range(1, len(srcs) + 1)):
        out.append("every source must be cited, and only those")
    return out


def check_daily_output(obj):
    """Problems with the model's daily JSON. Empty means it can go to the number audit."""
    ss = obj.get("sentences")
    if not isinstance(ss, list) or len(ss) > 2 or not all(isinstance(s, str) and s.strip() for s in ss):
        return ["needs a list of at most 2 sentences"]
    out = []
    for i, s in enumerate(ss):
        out += ["sentence %d: %s" % (i + 1, x) for x in check_voice(s)]
        if _MARK.search(s) or "http" in s:
            out.append("sentence %d: no links or markers on home" % (i + 1))
    return out


def self_test():
    good = ("Egypt's official rate for a dollar rose 60% between 4 Mar and 7 Mar 2024. A week later it was still "
            "57% above where it started.")
    assert check_voice(good) == [], check_voice(good)
    bad = "The pound plunged — a historic devaluation; the premium soared!"
    probs = check_voice(bad)
    for want in ("dash", "semicolon", "exclamation mark", "word: plunged", "word: historic", "word: devaluation", "word: premium",
                 "word: soared"):
        assert want in probs, (want, probs)
    long = " ".join(["word"] * 30) + "."
    assert any(p.startswith("long sentence") for p in check_voice(long))
    assert check_voice("Tether") == ["word: tether"] or "word: Tether" in check_voice("Tether")
    ev = {"paragraphs": [good, "The Central Bank of Egypt said it would let the market set the rate [1]. It raised interest rates "
                               "on the same day [2]."],
          "sources": [{"title": "a", "url": "https://example.org/a"}, {"title": "b", "url": "https://example.org/b"}]}
    assert check_event_output(ev) == [], check_event_output(ev)
    assert "paragraph 2 cites none of its sources" in check_event_output(dict(ev, paragraphs=[good, "The central bank spoke."]))
    assert any("has no source" in p for p in check_event_output(dict(ev, paragraphs=[good, "It said so [3]. And [1] [2]."])))
    assert any("record only" in p for p in check_event_output(dict(ev, paragraphs=[good + " [1]", ev["paragraphs"][1]])))
    assert check_event_output({"paragraphs": ["one"], "sources": []}) == ["needs exactly two paragraphs"]
    none = {"paragraphs": [good, "We found no announcement for 7 Mar 2024."], "sources": []}
    assert check_event_output(none) == [], check_event_output(none)
    assert check_daily_output({"sentences": ["Morocco went above 5% over the official rate on 30 Oct."]}) == []
    assert check_daily_output({"sentences": ["a.", "b.", "c."]}) == ["needs a list of at most 2 sentences"]
    assert WORDS and any("dearer" in nv for _, nv in WORDS), "the Words table in WORDS.md is the list"
    assert any("no links" in p for p in check_daily_output({"sentences": ["See https://x.org for more."]}))
    # the instructions themselves follow the site's word list (outside the "never use" list they quote)
    for name, txt in (("event", EVENT_INSTRUCTIONS), ("daily", DAILY_INSTRUCTIONS)):
        body = txt.split("- Never use these words")[0]
        assert "{" not in body.replace("{{", "").replace("{country}", ""), name
    print("writer_voice self-test: ok (%d banned words)" % len(BANNED))


if __name__ == "__main__":
    if "--self-test" in sys.argv:
        self_test()
    elif "--print" in sys.argv:
        print(EVENT_INSTRUCTIONS if "event" in sys.argv else DAILY_INSTRUCTIONS)
    else:
        print(__doc__)
