#!/usr/bin/env python3
"""Country pages in the HTML (SEB-426): one page per country at country/<ccy lowercase>/, written with this hour's numbers in it. No model.

country.html is a template that fills itself in with JavaScript from ?ccy=, so a crawler that does not run scripts saw no price
on it, and one URL for all countries. The machine-view step (tools/emit_markdown.py) already renders every country page in
headless Chrome to write its .md copy. The same render hands this module the markup the page built (nav, hero, depth, chart,
sources); it is written into a copy of the template, so the HTML and the .md copy show the same numbers from the same render.
The page's own script still loads the data and replaces all of it with the freshest hour, so a reader with JavaScript sees no
difference. Without JavaScript a last-30-days table of the gap sits under the chart (a <noscript> block, so it never shows
otherwise). Words come from copy.json (countryData, siteHead); every number from data/countries/<CCY>.json or the render.

    python3 tools/emit_country_pages.py --self-test
    python3 tools/emit_country_pages.py          # render the country pages now and write them (needs Chrome, like emit_markdown)

Loud failure: a country with no price in its render, a head over the limits, a template that moved its anchors, exits non-zero.
"""
import html
import json
import os
import re
import sys

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(HERE, "tools"))
import emit_site_files

MON = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]
MINUS = "−"
DAYS = 30
BEGIN, END = emit_site_files.BEGIN, emit_site_files.END
BLOCK = re.compile(re.escape(BEGIN) + r".*?" + re.escape(END), re.S)
# the redirect script in the template that adds the markdown link for ?ccy=: the static head carries its own
ALT_SCRIPT = re.compile(r'<script>\(function\(\)\{var v=new URLSearchParams\(location\.search\)\.get\("ccy"\).*?</script>\n', re.S)
# the empty holders in the template, each filled from the render
HOLDERS = [("nav", '<nav class="hp-nav" aria-label="Main" id="nav"></nav>', '<nav class="hp-nav" aria-label="Main" id="nav">%s</nav>'),
           ("cnav", '<div class="cnav" id="cnav"></div>', '<div class="cnav" id="cnav">%s</div>'),
           ("hero", '<div class="hero" id="hero"></div>', '<div class="hero" id="hero" style="display: flex; flex-direction: column;">%s</div>'),
           ("depth", '<div id="depth"></div>', '<div id="depth">%s</div>'),
           ("chart", '<section id="chart"></section>', '<section id="chart">%s</section>'),
           ("src", '<section id="src"></section>', '<section id="src">%s</section>')]


def pct1(v):
    a = abs(v)
    return (format(round(a), ",") if a >= 100 else "%.1f" % a) + "%"


def sgn(v):
    return ("" if abs(v) < 0.05 else "+" if v > 0 else MINUS) + pct1(v)


def day(s):
    return "%d %s" % (int(s[8:10]), MON[int(s[5:7]) - 1])


def noscript_table(c, words):
    """The last DAYS days of our own record, as a table. Only the days the page's chart draws as our own (no reported history)."""
    rows = [h for h in c.get("history", []) if "backfill" not in h.get("source", "")][-DAYS:]
    if not rows:
        return ""
    body = "".join("<tr><td>%s</td><td>%s</td></tr>" % (html.escape(day(h["date"])), html.escape(sgn(h["index_pct"]))) for h in rows)
    return ('<noscript><table class="nsx" aria-label="%s"><thead><tr><th scope="col">%s</th><th scope="col">%s</th></tr></thead>'
            "<tbody>%s</tbody></table></noscript>") % (html.escape(words["chartAria"], quote=True), html.escape(words["rcolTime"]),
                                                      html.escape(words["rcolGap"]), body)


def page_html(template, ccy, country, frag, c, copy):
    """One country's page: the template with its head, base, holders and noscript table filled."""
    if not re.search(r"\d", re.sub(r"<[^>]+>", " ", frag.get("hero", ""))):
        sys.exit("%s: the render shows no number in the hero, no page written" % ccy)
    if BEGIN not in template or ALT_SCRIPT.search(template) is None:
        sys.exit("country.html moved its head block or its markdown-link script, fix tools/emit_country_pages.py")
    out = BLOCK.sub(lambda m: emit_site_files.country_head(ccy, country, copy["siteHead"]), template, count=1)
    out = ALT_SCRIPT.sub("", out, count=1)
    # the template's relative links (./style.css, ./js/..., ./countries.html) resolve from the site root, one folder up from here
    out = out.replace('<meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover"/>',
                      '<meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover"/>\n<base href="/">', 1)
    out = out.replace("<body>", '<body data-ccy="%s">' % ccy, 1)
    for key, empty, full in HOLDERS:
        if empty not in out:
            sys.exit("country.html has no %s holder, fix tools/emit_country_pages.py" % key)
        inner = frag.get(key, "")
        if key == "chart":
            inner += noscript_table(c, copy["countryData"])
        out = out.replace(empty, full % inner, 1)
    return out


def write_all(frags, hour):
    """frags: {'country/ARS.md': {nav, cnav, hero, depth, chart, src}} from emit_markdown.render. Writes country/<ccy>/index.html."""
    template = open(os.path.join(HERE, "country.html")).read()
    copy = json.load(open(os.path.join(HERE, "copy.json")))
    made = 0
    for path, frag in sorted(frags.items()):
        ccy = os.path.basename(path)[:-3]
        c = json.load(open(os.path.join(HERE, "data", "countries", ccy + ".json")))
        text = page_html(template, ccy, c["country"], frag, c, copy)
        d = os.path.join(HERE, "country", ccy.lower())
        os.makedirs(d, exist_ok=True)
        open(os.path.join(d, "index.html"), "w").write(text)
        made += 1
    print("country pages: %d pages in country/<ccy>/ for the %s hour" % (made, hour))
    return made


def self_test():
    assert sgn(8.5969) == "+8.6%" and sgn(-0.01) == "0.0%" and sgn(-12.34) == MINUS + "12.3%" and sgn(150.2) == "+150%"
    assert day("2026-10-31") == "31 Oct"
    c = {"history": [{"date": "2026-10-%02d" % d, "index_pct": d / 2.0, "source": "hourly_buy"} for d in range(1, 29)]
         + [{"date": "2020-01-01", "index_pct": 1.0, "source": "daily_backfill"}]}
    t = noscript_table(c, {"chartAria": "A", "rcolTime": "Time", "rcolGap": "Gap"})
    assert t.count("<tr>") == 29 and "2020" not in t and "<noscript>" in t, t.count("<tr>")
    tpl = open(os.path.join(HERE, "country.html")).read()
    copy = json.load(open(os.path.join(HERE, "copy.json")))
    frag = {k: "<p>%s 1,666 ARS</p>" % k for k in ["nav", "cnav", "hero", "depth", "chart", "src"]}
    h = page_html(tpl, "ARS", "Argentina", frag, c, copy)
    assert '<base href="/">' in h and 'data-ccy="ARS"' in h and "https://margin.wiki/country/ars/" in h and "1,666 ARS" in h
    assert "new URLSearchParams(location.search).get(\"ccy\")" not in h.split("<body")[0]
    try:
        page_html(tpl, "ARS", "Argentina", dict(frag, hero="<p>nothing</p>"), c, copy)
    except SystemExit:
        pass
    else:
        raise AssertionError("a hero with no number was accepted")
    print("emit_country_pages self-test ok")


if __name__ == "__main__":
    if "--self-test" in sys.argv:
        self_test()
    else:
        import emit_markdown
        pages = [(u, p) for u, p in emit_markdown.all_pages() if p.startswith("country/")]
        emit_markdown.render(pages)
        write_all({p: f for p, f in emit_markdown.render.fragments.items()}, emit_markdown.hour())
