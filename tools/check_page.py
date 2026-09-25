#!/usr/bin/env python3
"""Render every reader-facing page in a real browser and fail loudly.

The review loop needs a gate that is decided by a machine, not argued about.
This renders each page the way a reader gets it -- fetching its JSON over HTTP,
running its JavaScript -- and then reads what actually appeared on screen.

It fails on:
  * a jargon word on a page that is not methodology.html
  * "placeholder", "NaN", "undefined", "[object Object]" in the rendered text
  * a console error or an uncaught exception
  * the page falling back to its own empty state, which means its data did not
    load -- a page that renders nothing must not pass review
  * a number written into the markup instead of computed from a file in data/

`mid-market` is allowed on purpose: it is the phrase a sender recognises, and
it is already the house phrase on providers.html. Bare `mid` is not.

Stdlib only. Exit status 0 only if every page passed.

Usage:
  python3 tools/check_page.py                 # every reader-facing page
  python3 tools/check_page.py providers.html  # only these

ask.html's static shell is always checked. Its live answer -- a real question
asked of the real backend -- only runs under CHECK_PAGE_LIVE_ASK=1, since a
live model call makes the result depend on what the model returns today, not
on the code under review (SEB-110):
  CHECK_PAGE_LIVE_ASK=1 python3 tools/check_page.py ask.html
"""

import glob
import html.parser
import http.server
import json
import os
import re
import socketserver
import sys
import threading

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from headless import Page                                    # noqa: E402
from bake_nav import NAV_PAGES, nav_html                     # noqa: E402

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

BANNED = ["bps", "basis point", "basis", "on-ramp", "off-ramp", "notional",
          "taker", "maker", "usdt", "fiat rail", "crypto"]

# ROADMAP names "corridor" for index.html specifically. A global ban would fail
# corridor.html on its own filename, so it is scoped rather than widened.
PAGE_BANNED = {"index.html": ["corridor"]}
BARE_MID = re.compile(r"\bmid\b(?!-market)", re.I)
BROKEN = ["placeholder", "[object object]", "lorem ipsum", "todo:", "fixme"]
EXEMPT = {"methodology.html"}

EMPTY_STATES = ("could not be read", "no comparison available",
                "no price history available", "no data available")

# Every page a reader can reach. A new page must be listed here to be covered.
PAGES = ["index.html", "providers.html", "pricing-history.html",
         "corridor.html", "methodology.html", "status.html", "findings.html",
         "requests.html", "calculator.html", "weekly.html", "data.html",
         "ask.html", "watch.html", "stress.html", "machine-room.html",
         "the-index.html", "sending-money.html", "how-it-works.html",
         "country.html", "fee-tiers.html", "agent-incidents.html"]

# ask.html and watch.html both call a live backend rather than reading a
# static file, so a check of the static shell alone would never touch the
# code that actually answers a question or sets up a watch. This visits each
# with a query string its own script reads to fire one fixed action
# automatically, headlessly -- see the comment above `verifyIdx` in ask.html
# and watch.html. country.html reads ?ccy= client-side and renders nothing
# but a loading state without one -- DZD is a real, currently-priced code so
# the check exercises the actual receipt-steps render path, not just the
# not-found branch.
#
# ask.html's live path is two sequential model calls (SQL, then a sentence),
# so its pass/fail depends on what a live model happens to return at test
# time -- a rate limit, a truncated response, or a sentence that leaks a
# banned word on the one run in ten that needs the retry ask_backend.py
# already does. That makes it fail PRs that never touched ask.html and pass
# ones that broke it (SEB-110). The merge gate this script runs for every
# .html-touching PR (agents/REVIEWER.md row 5) has to be decided by the code,
# not by today's model, so by default ask.html gets only the static-shell
# suffixless visit here -- chips render, nothing crashes, no stray jargon in
# the template. The live smoke test -- an actual question answered end to
# end -- still exists, opt-in, behind CHECK_PAGE_LIVE_ASK=1; a reviewer
# looking specifically at an ask.html change already does this real check by
# hand (agents/REVIEWER.md "Review from the rendered page").
LIVE_ASK = os.environ.get("CHECK_PAGE_LIVE_ASK") == "1"
PAGE_VISIT_SUFFIX = {"country.html": "?ccy=DZD"}
# watch.html used to need "?verify=0" here to headlessly trigger its live
# backend condition-setting flow -- it's a redirect stub now (SESSIONS.md
# Session 2), that flow doesn't exist on this page anymore.
if LIVE_ASK:
    PAGE_VISIT_SUFFIX["ask.html"] = "?verify=0"

# The site ships no favicon, so every page logs one 404 that means nothing.
IGNORED_ERRORS = ("favicon.ico",)


def real_filenames():
    """Basenames of files actually on disk under data/ -- 'basis.csv' etc.

    A page that lists what data/ holds has to quote those names verbatim, the
    same way it quotes a column name like `cost_bps`: citing an identifier
    is not the same as using the word in prose. This scrubs only names that
    are literally present on disk, so it cannot be used to smuggle jargon --
    it has no effect on any word that is not also a real file.
    """
    names = set()
    for pattern in ("data/*.csv", "data/*.json"):
        names.update(os.path.basename(p) for p in glob.glob(os.path.join(HERE, pattern)))
    return names


def scrub_filenames(text):
    for name in real_filenames():
        text = re.sub(re.escape(name), " ", text, flags=re.I)
    return text


class Quiet(http.server.SimpleHTTPRequestHandler):
    def __init__(self, *a, **k):
        super().__init__(*a, directory=HERE, **k)

    def log_message(self, *a):
        pass


def serve():
    socketserver.TCPServer.allow_reuse_address = True
    httpd = socketserver.TCPServer(("127.0.0.1", 0), Quiet)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    return httpd, httpd.server_address[1]


class _Text(html.parser.HTMLParser):
    """Collect text nodes with the tag stack that contains them."""

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.stack, self.out = [], []

    def handle_starttag(self, tag, attrs):
        if tag not in ("br", "img", "input", "meta", "link", "hr", "source"):
            self.stack.append(tag)

    def handle_endtag(self, tag):
        if tag in self.stack:
            while self.stack and self.stack.pop() != tag:
                pass

    def handle_data(self, data):
        self.out.append((list(self.stack), data))


MONEY = re.compile(r"(?<![\w.-])\d[\d,]*\.?\d*\s*%"
                   r"|(?:US\$|S\$|A\$|NZ\$|€|£|\$)\s?\d[\d,]*\.?\d*")

# Prose explains; it does not report a measurement. A number inside a paragraph
# or a list item is describing the method ("a country sitting 0.06% away"),
# which is writing, not a claim about today's data. A number in a heading, a
# table cell or a bare span IS in a reporting position, and must be computed.
PROSE = {"p", "li", "blockquote", "figcaption", "title", "label"}


def literal_numbers(page):
    """Numbers typed into the markup rather than computed from a file in data/.

    Attributes are ignored -- `width: 100%` and `offset="0%"` are layout, not
    claims -- so only text a reader actually sees is scanned.

    A number inside <!--BAKE:START:x-->...<!--BAKE:END:x--> is exempt, not
    stripped-and-scanned like an ordinary comment: those markers are how
    tools/bake_homepage.py (SPEC "v1 freeze and ship brief", D1's
    server-rendered headline) writes a real, freshly computed number
    straight into the page at collection time, for a crawler or a reader
    with JS off. The marker itself is the proof the number came from a
    script every pass, not a hand edit once -- stripped along with its
    contents, same as script/style, rather than scanned as if it were
    ordinary prose a person typed.
    """
    src = open(os.path.join(HERE, page)).read()
    src = re.sub(r"(?is)<(script|style)\b.*?</\1>", " ", src)
    src = re.sub(r"(?s)<!--BAKE:START:[^-]+-->.*?<!--BAKE:END:[^-]+-->", " ", src)
    src = re.sub(r"(?s)<!--.*?-->", " ", src)
    parser = _Text()
    parser.feed(src)
    hits = []
    for stack, data in parser.out:
        if PROSE & set(stack):
            continue
        for m in MONEY.finditer(data):
            token = m.group(0).strip()
            if re.fullmatch(r"(100|0)\s*%", token):
                continue
            hits.append(token)
    return hits


BASELINE = os.path.join(HERE, "tools", "page_baseline.json")


def baseline():
    if not os.path.exists(BASELINE):
        return {}
    with open(BASELINE) as f:
        return json.load(f)


def nav_items():
    with open(os.path.join(HERE, "copy.json")) as f:
        return json.load(f)["nav"]


RENDERED_NAV = re.compile(r"<nav>.*?</nav>", re.S)
RENDERED_TITLE = re.compile(r"<title>(.*?)</title>", re.S)


def normalize_markup(s):
    return re.sub(r"\s+", " ", s).strip()


# Each reader-facing page has one job; its <title> says what it is. This is
# a regression guard, not a style rule -- a page whose title stops matching
# this map has either been repurposed without updating the title, or had
# its title edited without anyone checking it still describes the page.
# tools/check_page.py compares with startswith(), not ==, because
# corridor.html appends the corridor's own currencies to this base title
# client-side (see its `document.title=...` line).
#
# The ten retired pages (providers.html, pricing-history.html,
# methodology.html, status.html, requests.html, calculator.html,
# weekly.html, data.html, watch.html, stress.html -- SESSIONS.md Session 2)
# are `<meta http-equiv="refresh" content="0; ...">` stubs now: this check
# visits the URL the same way a reader would, and a 0-second refresh has
# already fired by the time it reads the title, so what it actually
# observes is the DESTINATION page's title, never the stub's own. That
# is the stronger test -- it proves the redirect really lands somewhere,
# not just that the stub's markup looks right -- so each entry below names
# its destination's title, not its own.
PAGE_TITLE = {
    "index.html": "margin.wiki",
    "providers.html": "margin.wiki — sending money",
    "pricing-history.html": "margin.wiki — findings",
    "corridor.html": "margin.wiki — one route, the receipt in full",
    "methodology.html": "margin.wiki — how it works",
    "status.html": "margin.wiki — the machine room",
    "findings.html": "margin.wiki — findings",
    "requests.html": "margin.wiki — the index",
    "calculator.html": "margin.wiki — sending money",
    "weekly.html": "margin.wiki — findings",
    "data.html": "margin.wiki — the machine room",
    "ask.html": "margin.wiki — ask it a question",
    "watch.html": "margin.wiki — ask it a question",
    "stress.html": "margin.wiki — findings",
    "machine-room.html": "margin.wiki — the machine room",
    "the-index.html": "margin.wiki — the index",
    "sending-money.html": "margin.wiki — sending money",
    "how-it-works.html": "margin.wiki — how it works",
    "country.html": "margin.wiki — a country's price in full",
    "fee-tiers.html": "margin.wiki — Stablecoins are cheap, kind of",
    "agent-incidents.html": "margin.wiki — Running a site on agents I don't fully trust",
}


def check(page, port, browser, base):
    fails = []
    known = base.get(page, {})
    r = browser.visit(f"http://127.0.0.1:{port}/{page}{PAGE_VISIT_SUFFIX.get(page, '')}")
    text, low = r.text, r.text.lower()

    if not text.strip():
        return [f"{page}: rendered no text at all"]

    if page in NAV_PAGES:
        m = RENDERED_NAV.search(r.html)
        expected = nav_html(nav_items(), page)
        if not m:
            fails.append(f"{page}: no <nav>...</nav> found in the rendered page")
        elif normalize_markup(m.group(0)) != normalize_markup(expected):
            fails.append(f"{page}: rendered nav does not match copy.json's nav "
                         f"array -- run tools/bake_nav.py")

    expected_title = PAGE_TITLE.get(page)
    if expected_title:
        tm = RENDERED_TITLE.search(r.html)
        rendered_title = html.unescape(tm.group(1)) if tm else ""
        if not rendered_title.startswith(expected_title):
            fails.append(f"{page}: title {rendered_title!r} does not match its "
                         f"job ({expected_title!r} expected) -- update PAGE_TITLE "
                         f"in tools/check_page.py if the page's job genuinely "
                         f"changed, otherwise fix the <title>")

    # The waterfall's three bars must sum to the rendered total, to the cent
    # -- read off the page a reader actually sees (data-wf-leg/data-wf-total
    # text content), not re-derived from data/ here. That was the point of
    # SEB's waterfall fix (three bars used to be reconstructed independently
    # and drifted off the total by real cents on a live row); this check
    # exists so a future edit to drawWaterfall() can't silently reintroduce
    # the same drift. Skipped, not failed, when the page shows its own
    # honest "not available yet" state (no bars rendered at all).
    if page == "corridor.html":
        wf_vals = browser.eval_js("""
          (function(){
            var legs = Array.from(document.querySelectorAll('[data-wf-leg]')).map(function(el){ return el.textContent; });
            var totalEl = document.querySelector('[data-wf-total]');
            return {legs: legs, total: totalEl ? totalEl.textContent : null};
          })()
        """)
        if wf_vals and wf_vals.get("total") is not None:
            def parse_cash(s):
                m = re.search(r"([\d,]+\.\d{2})$", s or "")
                if not m:
                    return None
                v = float(m.group(1).replace(",", ""))
                return -v if "−" in s else v
            leg_vals = [parse_cash(s) for s in wf_vals["legs"]]
            total_val = parse_cash(wf_vals["total"])
            if total_val is not None and all(v is not None for v in leg_vals) and leg_vals:
                drift = round(sum(leg_vals) - total_val, 2)
                if abs(drift) > 0.005:
                    fails.append(f"{page}: waterfall bars ({leg_vals}) sum to "
                                 f"{round(sum(leg_vals), 2)}, rendered total is "
                                 f"{total_val} -- drift {drift}, does not "
                                 f"reconcile to the cent")

    if page not in EXEMPT:
        scrubbed = scrub_filenames(text)
        scrubbed_low = scrubbed.lower()
        for w in BANNED + PAGE_BANNED.get(page, []):
            if re.search(r"\b" + re.escape(w) + r"\b", scrubbed_low):
                fails.append(f"{page}: banned word on a reader-facing page: {w!r}")
        if BARE_MID.search(scrubbed):
            fails.append(f"{page}: banned word 'mid' on a reader-facing page "
                         f"(use 'mid-market' or plain language)")

    for w in BROKEN:
        if w in low:
            fails.append(f"{page}: {w!r} appears in the rendered page")
    for w in ("nan", "undefined"):
        if re.search(r"\b" + w + r"\b", low):
            fails.append(f"{page}: {w!r} appears in the rendered page")

    allowed = tuple(known.get("errors", []))
    for e in r.errors:
        if any(s in e for s in IGNORED_ERRORS) or \
           (allowed and any(s in e for s in allowed)):
            continue
        fails.append(f"{page}: console error: {e[:160]}")

    for phrase in EMPTY_STATES:
        if phrase in low:
            fails.append(f"{page}: fell back to its empty state ({phrase!r}) -- "
                         f"its data file did not load")

    if page not in EXEMPT:
        accepted = list(known.get("literals", []))
        new = []
        for lit in literal_numbers(page):
            if lit in accepted:
                accepted.remove(lit)      # each accepted item covers one hit
            else:
                new.append(lit)
        if new:
            fails.append(f"{page}: number written into the markup, not computed "
                         f"from data/: {new[:6]} -- compute it, or add it to "
                         f"tools/page_baseline.json with a reason")
    return fails


def main():
    pages = [p for p in (sys.argv[1:] or PAGES)
             if os.path.exists(os.path.join(HERE, p))]
    if not pages:
        print("no such page in this repo")
        return 1
    httpd, port = serve()
    base = baseline()
    bad = set()
    # ask.html's live answer is two sequential model calls plus a query, and
    # watch.html's is one model call plus a query -- slower than any static
    # page's fetch, so both get a longer settle. ask.html only fires its live
    # call under CHECK_PAGE_LIVE_ASK=1 (see PAGE_VISIT_SUFFIX above).
    settle = 8 if (("ask.html" in pages and LIVE_ASK) or "watch.html" in pages) else 2.5
    try:
        with Page(settle=settle) as browser:
            for p in pages:
                f = check(p, port, browser, base)
                print(("  FAIL  " if f else "  ok    ") + p)
                for line in f:
                    print("          " + line)
                if f:
                    bad.add(p)
    finally:
        httpd.shutdown()
    print(f"\n{len(pages) - len(bad)}/{len(pages)} pages clean")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
