#!/usr/bin/env python3
"""The plain-language gate: no payments jargon in anything a reader skims.

Rule 0 of the Day-1 plain-language pass: headings, subheadings, captions,
table headers/labels and the nav may never carry the words below. They are
fine in a methodology / how-it-works deep section, where a technical reader
is already asking for the technical term -- that's why how-it-works.html and
methodology's own copy are exempt below, and nothing else is.

Two things are checked:

  1. copy.json -- every string value reachable under a key whose own name
     looks like a heading/caption/label/nav/column (see HEADING_KEY_RE),
     scanned recursively so nav items, table columns and byline maps are all
     covered without listing every path by hand.

  2. The baked HTML pages themselves -- every <h1>/<h2>/<h3>, every <nav>,
     and every element whose class suggests a caption/label/kicker/column
     header (cap, label, lbl, kicker, col-title, legend, and <th>).

Exit 0 = clean. Exit 1 = every violation listed, file, locator and word.
"""

import html
import json
import os
import re
import sys

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
COPY = os.path.join(HERE, "copy.json")

# The banned list, task 0 of the Day-1 spec, verbatim. Word-boundary matched,
# case-insensitive, so "spread" catches "spreadsheet" too -- acceptable
# false-positive rate for a gate that's meant to be strict, and none of
# these words legitimately appear in a heading for an unrelated reason.
BANNED = [
    "fiat", "rail", "corridor", "route", "basis", "bps", "venue",
    "on-ramp", "off-ramp", "onramp", "offramp", "p2p", "parallel rate",
    "median", "decomposition", "spread", "liquidity", "maker", "taker",
    "vip tier", "measured hours", "pass", "collector", "withheld",
    # Phase 1 (FINAL spec): naming a specific transfer app in a heading,
    # card or caption reads as an endorsement -- "apps like Wise" is fine
    # in body prose (see BODY_KEY_EXCEPTIONS / EXEMPT_FILES) but not here.
    "wise",
]

BANNED_RE = re.compile(
    r"\b(" + "|".join(re.escape(w) for w in BANNED) + r")\b", re.I
)

# Exact-string exemptions: a restored or otherwise pre-existing heading/
# caption/label whose text is kept verbatim (per the FINAL spec, restored
# content is never rewritten to satisfy this check) but trips BANNED_RE.
# Keyed by the exact snippet the check would otherwise report, matched
# case-sensitively and in full -- deliberately narrow, never a whole-file
# or whole-word carve-out, so a NEW violation of the same word elsewhere
# still fails.
ALLOWLIST = set()

# A template placeholder like {corridor} or {rung} is never reader-visible on
# its own -- it is substituted with a real, already-plain value (a route's
# route_words, a formatted amount) before anyone sees it. Its NAME can share
# a banned word without the rendered sentence ever doing so, so placeholders
# are stripped before either scan below.
PLACEHOLDER_RE = re.compile(r"\{[^{}]*\}")


def strip_placeholders(s):
    return PLACEHOLDER_RE.sub(" ", s)

# Files where the technical register is the whole point -- METHODOLOGY's own
# home. Everything else on the live site is reader-facing.
EXEMPT_FILES = {"how-it-works.html", "methodology.html"}

# copy.json keys that name a heading, subheading, caption, table header,
# stat label or nav entry -- matched by substring on the key's own name
# (case-insensitive), not a fixed path list, so a new heading-shaped key
# added later is covered automatically instead of silently skipped.
HEADING_KEY_RE = re.compile(
    r"(title|headline|heading|caption|^cap$|cap$|label|kicker|legend|"
    r"col$|columns?|byline|lede|sub$|nav|withheldtitle|gapstitle|pricedtitle|"
    r"corridortabletitle|verdict|worsttag|provider$|dollarroute)",
    re.I,
)

# Keys that are explicitly body prose, not a heading/caption/label, even
# though their parent object also holds heading-shaped keys (e.g. a card's
# "cap" is a caption, but methodology-style prose keys are not this check's
# job -- rule 0 scopes the ban to "headings, subheadings, captions, table
# headers, stat labels and nav" specifically, not full paragraphs).
BODY_KEY_EXCEPTIONS = {
    "body", "footnote", "note", "hint", "intro", "footertemplate",
    "capnote", "evidencesentencetemplate", "ratesentencetemplate",
    "mathsentencetemplate", "verdictnoteorderbook", "verdictnoteaggregate",
    "verdict1", "verdict2", "lede1", "lede2",
}


def walk_copy(node, path, key_is_heading, out):
    if isinstance(node, dict):
        for k, v in node.items():
            # A heading-shaped parent (legend, columns, byline, meters...)
            # makes its own children heading-shaped too -- those children
            # ARE the labels, the parent key is just the grouping name. An
            # explicit body-prose key always overrides back to False, even
            # under a heading-shaped parent.
            own_match = bool(HEADING_KEY_RE.search(k))
            heading = (key_is_heading or own_match) and k.lower() not in BODY_KEY_EXCEPTIONS
            walk_copy(v, path + "." + k, heading, out)
    elif isinstance(node, list):
        for i, v in enumerate(node):
            walk_copy(v, path + f"[{i}]", key_is_heading, out)
    elif isinstance(node, str) and key_is_heading:
        for m in BANNED_RE.finditer(strip_placeholders(node)):
            out.append((path, m.group(1), node))


def check_copy_json():
    with open(COPY) as f:
        doc = json.load(f)
    out = []
    walk_copy(doc, "copy.json", False, out)
    return out


TAG_RE = re.compile(
    r"<(h1|h2|h3|nav)\b[^>]*>(.*?)</\1>", re.S | re.I
)
CLASS_ELEMENT_RE = re.compile(
    r'<(\w+)\s+[^>]*class="([^"]*)"[^>]*>(.*?)</\1>', re.S | re.I
)
CAPTIONISH_CLASS_RE = re.compile(
    r"\b(cap|label|lbl|kicker|col-title|legend)\b", re.I
)
TH_RE = re.compile(r"<th\b[^>]*>(.*?)</th>", re.S | re.I)
TAG_STRIP_RE = re.compile(r"<[^>]+>")
SCRIPT_STYLE_RE = re.compile(r"<(script|style)\b.*?</\1>", re.S | re.I)


def text_of(fragment):
    return html.unescape(TAG_STRIP_RE.sub(" ", fragment))


def check_html_file(path, out):
    name = os.path.basename(path)
    if name in EXEMPT_FILES:
        return
    with open(path, encoding="utf-8") as f:
        raw = f.read()
    # Script/style blocks build headings from copy.json strings at runtime
    # (already checked directly against copy.json above) or hold JS source
    # whose variable names can accidentally contain a banned word as a
    # substring -- neither is reader-facing markup, so both are stripped
    # before the tag scan below.
    content = SCRIPT_STYLE_RE.sub("", raw)

    for m in TAG_RE.finditer(content):
        tag, inner = m.group(1), m.group(2)
        # A nav's own inner HTML is nested <a> tags -- fine, still text.
        txt = text_of(inner)
        for bm in BANNED_RE.finditer(txt):
            out.append((f"{name}:<{tag}>", bm.group(1), txt.strip()[:120]))

    for m in CLASS_ELEMENT_RE.finditer(content):
        tag, cls, inner = m.group(1), m.group(2), m.group(3)
        if tag.lower() in ("script", "style"):
            continue
        if not CAPTIONISH_CLASS_RE.search(cls):
            continue
        txt = text_of(inner)
        for bm in BANNED_RE.finditer(txt):
            out.append((f"{name}:.{cls.split()[0]}", bm.group(1), txt.strip()[:120]))

    for m in TH_RE.finditer(content):
        txt = text_of(m.group(1))
        for bm in BANNED_RE.finditer(txt):
            out.append((f"{name}:<th>", bm.group(1), txt.strip()[:120]))


def check_all_html():
    out = []
    for name in sorted(os.listdir(HERE)):
        if name.endswith(".html"):
            check_html_file(os.path.join(HERE, name), out)
    return out


def main():
    violations = []
    violations += [("copy.json:" + p, w, s) for p, w, s in check_copy_json()]
    violations += check_all_html()

    violations = [v for v in violations if v[2] not in ALLOWLIST]

    if not violations:
        print("  check_copy.py: clean -- no banned word in any heading, "
              "caption, label, nav or table header")
        return

    print(f"  [error] {len(violations)} banned-word violation(s):", file=sys.stderr)
    for loc, word, snippet in violations:
        print(f"    {loc}: {word!r} in {snippet!r}", file=sys.stderr)
    sys.exit(1)


if __name__ == "__main__":
    main()
