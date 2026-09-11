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
"""

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

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

BANNED = ["bps", "basis point", "basis", "on-ramp", "off-ramp", "notional",
          "taker", "maker", "usdt", "fiat rail"]
BARE_MID = re.compile(r"\bmid\b(?!-market)", re.I)
BROKEN = ["placeholder", "[object object]", "lorem ipsum", "todo:", "fixme"]
EXEMPT = {"methodology.html"}

EMPTY_STATES = ("could not be read", "no comparison available",
                "no price history available", "no data available")

# Every page a reader can reach. A new page must be listed here to be covered.
PAGES = ["index.html", "providers.html", "pricing-history.html",
         "corridor.html", "methodology.html", "status.html", "findings.html"]

# The site ships no favicon, so every page logs one 404 that means nothing.
IGNORED_ERRORS = ("favicon.ico",)


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
    """
    src = open(os.path.join(HERE, page)).read()
    src = re.sub(r"(?is)<(script|style)\b.*?</\1>", " ", src)
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


def check(page, port, browser, base):
    fails = []
    known = base.get(page, {})
    r = browser.visit(f"http://127.0.0.1:{port}/{page}")
    text, low = r.text, r.text.lower()

    if not text.strip():
        return [f"{page}: rendered no text at all"]

    if page not in EXEMPT:
        for w in BANNED:
            if re.search(r"\b" + re.escape(w) + r"\b", low):
                fails.append(f"{page}: banned word on a reader-facing page: {w!r}")
        if BARE_MID.search(text):
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
    try:
        with Page() as browser:
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
