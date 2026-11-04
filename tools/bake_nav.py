#!/usr/bin/env python3
"""The one site header (2 Nov 2026, DESIGN.md "Nav"). Every page has the same header, written by this tool and nothing else.

The header is plain HTML between <!-- site-head:begin --> and <!-- site-head:end -->, right after <body>, on every page. The
words come from copy.json ("brand", "siteNav", homeData "menuLabel" and "menuClose"). The page you are on gets
aria-current="page", and when it is one of the About pages, About is marked too. How it looks is css/site_head.css, how it
behaves (About, the phone menu, the clock) is js/site_head.js. No page script draws or redraws a header.

    python3 tools/bake_nav.py            # write the header into every page
    python3 tools/bake_nav.py --check    # exit 1 if any page's header is not the one copy, or anything else draws a header

--check also fails, loudly, on the things that broke the header seven times in one day (1 to 2 Nov):
  a page with no header block, or two, or a block that differs from what this tool writes;
  any other header markup in a page (the old hp-head, ci-head, sm-head, fp-head and mwh headers);
  a page script that builds a nav or a header;
  CSS for the header anywhere but css/site_head.css;
  more than seven items in the bar.
"""
import glob
import html
import json
import os
import re
import sys

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
COPY = os.path.join(HERE, "copy.json")
BEGIN, END = "<!-- site-head:begin -->", "<!-- site-head:end -->"
BLOCK = re.compile(re.escape(BEGIN) + r".*?" + re.escape(END), re.S)
BAKE = re.compile(r"<!-- bake:begin -->.*?<!-- bake:end -->", re.S)      # the no-script copy of a page (tools/bake_pages.py)
# pages that are one item of a list: the bar marks the list
HOME_OF = {"country.html": "countries.html", "finding.html": "research.html", "event.html": "events.html",
           "research-capital-controls.html": "research.html", "research-source-pairs.html": "research.html"}
OLD = re.compile(r"""class=["'][^"']*\b(hp-head|hp-headleft|hp-nav|hp-logo|ci-head|ci-nav|ci-logo|sm-head|sm-nav|sm-logo|"""
                 r"""fp-head|fp-brand|fp-nav|fp-logo|c-head|c-nav|c-logo|s-head|s-nav|s-logo|mwh|mwh-logo)\b""")
OLD_CSS = re.compile(r"\.(hp-head|hp-headleft|hp-nav|hp-logo|ci-head|ci-nav|ci-logo|sm-head|sm-nav|sm-logo|fp-head|fp-brand|"
                     r"fp-nav|fp-logo|c-head|c-nav|c-logo|s-head|s-nav|s-logo|mwh|mwh-logo|hp-clock|hp-dot)\b")
OWN_CSS = re.compile(r"\.(site-head|site-head-bar|site-logo|site-nav|sh-[a-z-]+)\b")
# a stylesheet rule whose selector names the header or nav element: it styles the site header from outside
ELEMENT = re.compile(r"(?:^|[\s,>+~(])(header|nav)(?![\w-])")
# a script that makes a nav or a header element, or writes one as markup
JS_BUILDS = re.compile(r"""createElement\(\s*['"](nav|header)['"]|el\(\s*['"](nav|header)['"]|<nav\b|<header\b""")


def words():
    c = json.load(open(COPY, encoding="utf-8"))
    nav, hd = c["siteNav"], c["homeData"]
    if len(nav["main"]) + 1 > 7:
        sys.exit("bake_nav: more than seven items in the bar (DESIGN.md Nav)")
    return c["brand"], nav, hd["menuLabel"], hd["menuClose"]


def page_file(href):
    return href.split("?")[0].split("#")[0].split("/")[-1].lower()


def header_html(page, w=None):
    """The header for one page, as one line of HTML."""
    brand, nav, menu, close = w or words()
    here = HOME_OF.get(page, page)
    e = lambda s: html.escape(s, quote=True)

    def link(it):
        cur = ' aria-current="page"' if page_file(it["href"]) == here else ""
        return '<a href="%s"%s data-text="%s">%s</a>' % (e(it["href"]), cur, e(it["label"]), e(it["label"]))
    in_about = any(page_file(it["href"]) == here for it in nav["aboutItems"])
    about = ('<span class="sh-about%s"><button type="button" class="sh-about-btn" aria-expanded="false" aria-haspopup="true">'
             '<span class="sh-about-t" data-text="%s">%s</span></button><span class="sh-about-menu">%s</span></span>') % (
        " sh-here" if in_about else "", e(nav["about"]), e(nav["about"]), "".join(link(it) for it in nav["aboutItems"]))
    return (BEGIN + '<header class="site-head"><div class="site-head-bar">'
            '<a class="site-logo" href="./index.html">%s</a>'
            '<nav class="site-nav" id="sh-nav" aria-label="Main">%s%s</nav>'
            '<button type="button" class="sh-menu" aria-expanded="false" aria-controls="sh-nav" data-open="%s" data-close="%s">%s</button>'
            '</div></header>' + END) % (e(brand), "".join(link(it) for it in nav["main"]), about, e(menu), e(close), e(menu))


def put(text, page, w=None):
    """The page with its header block written. A page with no block, or more than one, is an error."""
    n = len(BLOCK.findall(BAKE.sub("", text)))
    if n != 1:
        raise ValueError("%s has %d header blocks, it needs exactly one, right after <body>" % (page, n))
    return BLOCK.sub(lambda m: header_html(page, w), text, count=1)


def pages():
    sys.path.insert(0, os.path.join(HERE, "tools"))
    from gate_common import all_pages
    return all_pages()


def problems(w):
    out = []
    for p in pages():
        text = open(os.path.join(HERE, p), encoding="utf-8").read()
        live = BAKE.sub("", text)
        try:
            if put(text, p, w) != text:
                out.append("%s: its header is not the one copy; run python3 tools/bake_nav.py" % p)
        except ValueError as err:
            out.append(str(err))
            continue
        body = re.search(r"<body[^>]*>\s*", live)
        if not body or not live[body.end():].startswith(BEGIN):
            out.append("%s: the header block must come right after <body>" % p)
        m = OLD.search(BLOCK.sub("", live))
        if m:
            out.append("%s: an old header (%s) is still in the page; the header is the site-head block only" % (p, m.group(1)))
        for m in re.finditer(r"<style[^>]*>(.*?)</style>", live, re.S):
            hit = OLD_CSS.search(m.group(1)) or OWN_CSS.search(m.group(1))
            if hit:
                out.append("%s: header styles in the page's <style> (%s); they live in css/site_head.css only" % (p, hit.group(0)))
    for f in sorted(glob.glob(os.path.join(HERE, "js", "*.js"))):
        if os.path.basename(f) == "site_head.js":
            continue
        src = open(f, encoding="utf-8").read()
        m = JS_BUILDS.search(src) or OLD.search(src)
        if m:
            out.append("js/%s: builds a nav or a header (%s); the header is written into the HTML by tools/bake_nav.py"
                       % (os.path.basename(f), m.group(0)))
    for f in sorted(glob.glob(os.path.join(HERE, "css", "*.css")) + [os.path.join(HERE, "style.css")]):
        if not os.path.exists(f) or os.path.basename(f) == "site_head.css":
            continue
        src = re.sub(r"/\*.*?\*/", "", open(f, encoding="utf-8").read(), flags=re.S)
        m = OLD_CSS.search(src) or OWN_CSS.search(src)
        if not m:
            for sel in re.findall(r"([^{}]+)\{", src):
                if not sel.strip().startswith("@") and ELEMENT.search(sel):
                    m = ELEMENT.search(sel)
                    break
        if m:
            out.append("%s: styles the header (%s); header styles live in css/site_head.css only"
                       % (os.path.relpath(f, HERE), m.group(0).strip()))
    return out


def self_test(w):
    page = "<html><body>\n" + BEGIN + "old" + END + "\n<div id=app></div></body></html>"
    got = put(page, "research-source-pairs.html", w)
    assert 'href="./research.html" aria-current="page"' in got, "a research page marks Research"
    assert got.count('aria-current') == 1
    got = put(page, "sources.html", w)
    assert 'class="sh-about sh-here"' in got and 'href="./sources.html" aria-current="page"' in got, "an About page marks About"
    for bad in ("<html><body><div id=app></div></body></html>", "<html><body>" + (BEGIN + END) * 2 + "</body></html>"):
        try:
            put(bad, "x.html", w)
            raise AssertionError("a page with no block or two blocks must fail")
        except ValueError:
            pass
    assert JS_BUILDS.search("var n = el('nav', 'x');") and JS_BUILDS.search("'<header class=\"x\">'")
    assert ELEMENT.search("nav a") and ELEMENT.search(".x, header") and not ELEMENT.search(".nav-x") and not ELEMENT.search(".fp-navy")
    assert OLD_CSS.search(".fp-head { padding: 0 }") and not OLD_CSS.search(".fp-sec-head { gap: 8px }")
    print("bake_nav: self-test passed")


def main():
    w = words()
    if "--self-test" in sys.argv:
        self_test(w)
        return
    if "--check" in sys.argv:
        bad = problems(w)
        for b in bad:
            print("bake_nav: " + b)
        if bad:
            sys.exit(1)
        print("bake_nav: %d pages, one header, nothing else draws one" % len(pages()))
        return
    for p in pages():
        path = os.path.join(HERE, p)
        text = open(path, encoding="utf-8").read()
        new = put(text, p, w)
        if new != text:
            open(path, "w", encoding="utf-8").write(new)
            print("bake_nav: wrote the header into %s" % p)


if __name__ == "__main__":
    main()
