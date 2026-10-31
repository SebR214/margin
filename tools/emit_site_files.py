#!/usr/bin/env python3
"""Findable (SEB-425): the head of every page, robots.txt and sitemap.xml. No model, stdlib only.

Words come from copy.json "siteHead". Two jobs:
  head     rewrite the block between <!-- head:begin --> and <!-- head:end --> in every static page: title, description,
           canonical, Open Graph and Twitter tags, the favicon links and the markdown twin. Run by hand when a title changes.
  files    write robots.txt and sitemap.xml from the page list the machine view already builds (tools/emit_markdown.py all_pages).
           lastmod is the build hour. emit_markdown.build() calls this, so it runs with every collection.
Loud failure: a title over 60 characters, a description over 160, a page without an entry, exits non-zero.
"""
import html
import json
import os
import re
import sys

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SITE = "https://margin.wiki"
TITLE_MAX, DESC_MAX = 60, 160
# moved pages: noindex redirects, never in the sitemap
REDIRECTS = {"corridor.html", "tape.html", "fee-tiers.html"}
# pages with a markdown twin
TWINS = {"index.html": "index.md", "countries.html": "countries.md", "sending-money.html": "sending-money.md",
         "sources.html": "sources.md", "findings.html": "findings.md", "how-it-works.html": "how-it-works.md",
         "how-it-was-built.html": "how-it-was-built.md"}
# country.html and finding.html are templates: the page sets its own canonical, so the static head has none
TEMPLATES = {"country.html", "finding.html"}
BEGIN, END = "<!-- head:begin -->", "<!-- head:end -->"


def load_copy():
    with open(os.path.join(HERE, "copy.json")) as f:
        return json.load(f)["siteHead"]


def static_pages():
    return sorted(f for f in os.listdir(HERE) if f.endswith(".html") and f not in REDIRECTS)


def url_for(page):
    return SITE + "/" if page == "index.html" else SITE + "/" + page


def head_block(page, entry):
    title, desc = entry
    if len(title) > TITLE_MAX:
        sys.exit("%s: title is %d characters, the limit is %d" % (page, len(title), TITLE_MAX))
    if len(desc) > DESC_MAX:
        sys.exit("%s: description is %d characters, the limit is %d" % (page, len(desc), DESC_MAX))
    t, d = html.escape(title, quote=True), html.escape(desc, quote=True)
    url = url_for(page)
    lines = [BEGIN, "<title>%s</title>" % t, '<meta name="description" content="%s"/>' % d]
    if page not in TEMPLATES:
        lines.append('<link rel="canonical" href="%s"/>' % url)
    lines += ['<meta property="og:site_name" content="margin.wiki"/>', '<meta property="og:type" content="website"/>',
              '<meta property="og:title" content="%s"/>' % t, '<meta property="og:description" content="%s"/>' % d]
    if page not in TEMPLATES:
        lines.append('<meta property="og:url" content="%s"/>' % url)
    lines += ['<meta name="twitter:card" content="summary"/>', '<meta name="twitter:title" content="%s"/>' % t,
              '<meta name="twitter:description" content="%s"/>' % d,
              '<link rel="icon" href="/favicon.svg" type="image/svg+xml"/>', '<link rel="icon" href="/favicon.ico" sizes="48x48"/>']
    if page in TWINS:
        lines.append('<link rel="alternate" type="text/markdown" href="/%s"/>' % TWINS[page])
    lines.append(END)
    return "\n".join(lines)


def country_head(ccy, country, copy):
    """The head of one country's own page (SEB-426): its title, description, canonical URL and markdown copy."""
    page = "country/%s/" % ccy.lower()
    title = copy["countryTitle"].replace("{country}", country)
    desc = copy["countryDescription"].replace("{country}", country)
    if len(title) > TITLE_MAX or len(desc) > DESC_MAX:
        sys.exit("%s: title is %d characters (limit %d), description %d (limit %d)" % (page, len(title), TITLE_MAX, len(desc), DESC_MAX))
    t, d, url = html.escape(title, quote=True), html.escape(desc, quote=True), SITE + "/" + page
    return "\n".join([BEGIN, "<title>%s</title>" % t, '<meta name="description" content="%s"/>' % d,
                      '<link rel="canonical" href="%s"/>' % url, '<meta property="og:site_name" content="margin.wiki"/>',
                      '<meta property="og:type" content="website"/>', '<meta property="og:title" content="%s"/>' % t,
                      '<meta property="og:description" content="%s"/>' % d, '<meta property="og:url" content="%s"/>' % url,
                      '<meta name="twitter:card" content="summary"/>', '<meta name="twitter:title" content="%s"/>' % t,
                      '<meta name="twitter:description" content="%s"/>' % d,
                      '<link rel="icon" href="/favicon.svg" type="image/svg+xml"/>', '<link rel="icon" href="/favicon.ico" sizes="48x48"/>',
                      '<link rel="alternate" type="text/markdown" href="/country/%s.md"/>' % ccy.upper(), END])


OLD = [re.compile(r"[ \t]*<title>.*?</title>[ \t]*\n", re.S),
       re.compile(r'[ \t]*<meta name="description"[^>]*>[ \t]*\n'),
       re.compile(r'[ \t]*<link rel="alternate" type="text/markdown"[^>]*>[ \t]*\n')]
BLOCK = re.compile(re.escape(BEGIN) + r".*?" + re.escape(END), re.S)


def rewrite_heads():
    pages = load_copy()["pages"]
    changed = []
    for page in static_pages():
        if page not in pages:
            sys.exit("%s has no entry in copy.json siteHead.pages" % page)
        path = os.path.join(HERE, page)
        text = open(path).read()
        block = head_block(page, pages[page])
        if BEGIN in text:
            new = BLOCK.sub(lambda m: block, text, count=1)
        else:
            for rx in OLD:
                text = rx.sub("", text, count=1)
            m = re.search(r'<meta name="viewport"[^>]*>[ \t]*\n', text)
            if not m:
                sys.exit("%s has no viewport meta to anchor the head block on" % page)
            new = text[:m.end()] + block + "\n" + text[m.end():]
        if new != text or new != open(path).read():
            open(path, "w").write(new)
            changed.append(page)
    print("head: %s" % (", ".join(changed) if changed else "already current on every page"))


def write_robots():
    open(os.path.join(HERE, "robots.txt"), "w").write("User-agent: *\nAllow: /\n\nSitemap: %s/sitemap.xml\n" % SITE)


def write_sitemap(urls, lastmod):
    """urls: absolute paths like 'countries.html' or 'country.html?ccy=ARS'. One entry each, in the order given."""
    seen, out = set(), ['<?xml version="1.0" encoding="UTF-8"?>',
                        '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">']
    for u in urls:
        loc = url_for(u) if "?" not in u else SITE + "/" + u
        if loc in seen:
            continue
        seen.add(loc)
        out.append("<url><loc>%s</loc><lastmod>%s</lastmod></url>" % (html.escape(loc), lastmod))
    out.append("</urlset>")
    open(os.path.join(HERE, "sitemap.xml"), "w").write("\n".join(out) + "\n")
    return len(seen)


def write_files(lastmod=None):
    """robots.txt and sitemap.xml from emit_markdown's page list. lastmod is a UTC date-time like 2026-10-31T07:00:00Z."""
    sys.path.insert(0, os.path.join(HERE, "tools"))
    import emit_markdown
    from datetime import datetime, timezone
    lastmod = lastmod or datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:00:00Z")
    # each country has its own page, country/<ccy>/ (SEB-426); country.html is the template and stays out
    pages = [("country/%s/" % url.split("=")[1].lower()) if url.startswith("country.html?ccy=") else url for url, md in emit_markdown.all_pages()]
    extra = [f for f in static_pages() if f not in TEMPLATES and f not in pages]
    n = write_sitemap(pages + extra, lastmod)
    write_robots()
    print("site files: robots.txt and sitemap.xml with %d urls, lastmod %s" % (n, lastmod))
    return n


def self_test():
    b = head_block("countries.html", ["T & t", "a \"d\""])
    assert "<title>T &amp; t</title>" in b and 'content="a &quot;d&quot;"' in b
    assert 'rel="canonical" href="https://margin.wiki/countries.html"' in b and "/countries.md" in b
    assert "canonical" not in head_block("country.html", ["T", "d"])
    assert url_for("index.html") == SITE + "/"
    ch = country_head("ARS", "Argentina", {"countryTitle": "{country}: a dollar", "countryDescription": "In {country}."})
    assert '<link rel="canonical" href="https://margin.wiki/country/ars/"/>' in ch and "/country/ARS.md" in ch
    try:
        head_block("x.html", ["t" * 61, "d"])
    except SystemExit:
        pass
    else:
        raise AssertionError("long title accepted")
    print("emit_site_files self-test ok")


if __name__ == "__main__":
    if "--self-test" in sys.argv:
        self_test()
    elif "head" in sys.argv:
        rewrite_heads()
    else:
        write_files()
