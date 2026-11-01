#!/usr/bin/env python3
"""Pages that show their content without JavaScript (SEB-431). No model, stdlib only.

Most pages are an empty shell that a script fills in, so a crawler, a reader's text browser or a visitor with scripts off saw a
title and nothing else. This renders each page the way a reader gets it (served from this checkout, in headless Chrome, the same
way tools/emit_markdown.py does) and writes what it drew into the page's own HTML, inside a <noscript> block between
<!-- bake:begin --> and <!-- bake:end --> just before </body>. A reader with scripts never sees the block, so the page behaves
exactly as before. Without scripts the block is the page, and a rule inside it hides the empty shell above it.

Idempotent: each run replaces exactly what the last run wrote. The words and numbers are the page's own, as drawn from copy.json
and data/ this hour, so nothing is typed here. Pages that are one template for many things (country.html, finding.html,
event.html) are left alone: country pages are baked one by one by tools/emit_country_pages.py.

    python3 tools/bake_pages.py --self-test
    python3 tools/bake_pages.py            # render every page now and write the blocks (needs Chrome, like emit_markdown)

Loud failure: a page that rendered almost no text, or no heading, is not written, and the run exits 1 after the others are done.
"""
import json
import os
import re
import sys
import time

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(HERE, "tools"))

BEGIN, END = "<!-- bake:begin -->", "<!-- bake:end -->"
BLOCK = re.compile(r"[ \t]*" + re.escape(BEGIN) + r".*?" + re.escape(END) + r"[ \t]*\n?", re.S)
TEMPLATES = {"country.html", "finding.html", "event.html", "404.html"}
MIN_TEXT = 400          # characters of text a drawn page must have, or the render did not finish
HIDE_SHELL = "<style>body > *:not(noscript){display:none !important}</style>"

# what a page's body holds once it is drawn, without the things that only work with scripts (the Human/Machine switch included)
CAPTURE_JS = """(function(){var b=document.body.cloneNode(true);
 [].forEach.call(b.querySelectorAll('script,noscript,template,.mv-switch,.mv-panel'),function(e){e.remove()});
 return JSON.stringify({html:b.innerHTML,text:(document.body.innerText||'').length,h1:!!document.querySelector('h1')})})()"""


def pages():
    from gate_common import all_pages
    return [p for p in all_pages() if p not in TEMPLATES]


def inject(text, captured):
    """The page's HTML with its bake block replaced (or added before </body>)."""
    if "</noscript" in captured.lower():
        raise ValueError("the drawn page holds a </noscript>, it cannot be wrapped")
    block = "%s\n<noscript>%s<div>%s</div></noscript>\n%s\n" % (BEGIN, HIDE_SHELL, captured, END)
    if BEGIN in text:
        return BLOCK.sub(lambda m: block, text, count=1)
    i = text.rfind("</body>")
    if i < 0:
        raise ValueError("no </body> to put the block before")
    return text[:i] + block + text[i:]


def render(names, settle=2.5):
    from gate_common import open_page, serve
    base, stop = serve(HERE)
    out = {}
    try:
        with open_page(settle=settle) as page:
            page.visit("about:blank")
            page.set_viewport(1300, 900)
            for name in names:
                page.visit(base + "/" + name)
                got, last = {}, -1
                for _ in range(12):                 # a page fills in after its data loads: wait until its text stops growing
                    got = json.loads(page.eval_js(CAPTURE_JS) or "{}")
                    if got.get("h1") and got.get("text", 0) >= MIN_TEXT and got["text"] == last:
                        break
                    last = got.get("text", 0)
                    time.sleep(1.0)
                out[name] = got
            page.clear_viewport()
    finally:
        stop()
    return out


def run():
    names = pages()
    got = render(names)
    bad, made = [], 0
    for name in names:
        g = got.get(name) or {}
        if not g.get("h1") or g.get("text", 0) < MIN_TEXT:
            bad.append("%s: drew %s characters of text%s" % (name, g.get("text", 0), "" if g.get("h1") else " and no heading"))
            continue
        path = os.path.join(HERE, name)
        old = open(path, encoding="utf-8").read()
        new = inject(old, g["html"])
        if new != old:
            open(path, "w", encoding="utf-8").write(new)
        made += 1
    print("bake pages: %d of %d pages carry what they draw" % (made, len(names)))
    if bad:
        print("bake pages FAILED, these pages were left as they were:\n  " + "\n  ".join(bad), file=sys.stderr)
        return 1
    return 0


def self_test():
    page = "<html><body><div id=\"app\"></div>\n<script src=\"a.js\"></script>\n</body></html>\n"
    a = inject(page, "<h1>One</h1>")
    assert a.count(BEGIN) == 1 and "<noscript>" in a and "<h1>One</h1>" in a and a.index(BEGIN) < a.index("</body>"), a
    b = inject(a, "<h1>Two</h1>")                      # a second run replaces the first, never adds to it
    assert b.count(BEGIN) == 1 and "<h1>Two</h1>" in b and "<h1>One</h1>" not in b, b
    assert inject(b, "<h1>Two</h1>") == b              # and a run with nothing new changes nothing
    assert b.replace(BLOCK.search(b).group(0), "") == page, "the page outside the block moved"
    try:
        inject(page, "<p></noscript></p>")
    except ValueError:
        pass
    else:
        raise AssertionError("a </noscript> in the capture was accepted")
    assert "country.html" not in [p for p in ["country.html", "index.html"] if p not in TEMPLATES]
    print("bake_pages self-test ok")


if __name__ == "__main__":
    if "--self-test" in sys.argv:
        self_test()
    else:
        sys.exit(run())
