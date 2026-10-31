#!/usr/bin/env python3
"""The outside check (SEB-425): what a crawler sees, over plain HTTP, against the live site. No model, stdlib only.

Runs in .github/workflows/outside_check.yml after GitHub Pages publishes. Exits 1 if any check fails, so a red run means the live
site is wrong. Checks:
  1. robots.txt, sitemap.xml, llms.txt, favicon.ico and favicon.svg exist (200).
  2. Every URL in the sitemap returns 200.
  3. Every page in the sitemap has a title and a description in its HTML, with no JavaScript run.
  4. Nothing the home page asks for returns 404: its scripts, styles and the data files they name.
  5. how-it-was-built, agent-incidents and the Iraq event page are one click from home: the footer links home draws are in
     copy.json siteHead.footerLinks, the home page loads the script that draws them, and each target returns 200.
A fetch that fails is retried a few times (Pages and its cache take a minute to catch up); the last answer counts.
"""
import json
import re
import sys
import time
import urllib.error
import urllib.request
import xml.etree.ElementTree as ET
from concurrent.futures import ThreadPoolExecutor
from urllib.parse import urljoin, urlparse

SITE = "https://margin.wiki"
MUST_BE_LINKED = ["how-it-was-built.html", "agent-incidents.html", "event.html"]
TRIES, PAUSE = 4, 30


def fetch(url, tries=None, pause=None):
    """(status, body). Retries a non-200 or a network error; the last answer is returned."""
    tries = TRIES if tries is None else tries
    pause = PAUSE if pause is None else pause
    last = (0, "")
    for i in range(tries):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "margin.wiki outside check"})
            with urllib.request.urlopen(req, timeout=30) as r:
                return r.status, r.read().decode("utf-8", "replace")
        except urllib.error.HTTPError as e:
            last = (e.code, "")
        except Exception as e:  # network error: status 0, the reason goes in the failure line
            last = (0, str(e))
        if i < tries - 1:
            time.sleep(pause)
    return last


def check(base):
    fails = []

    def bad(msg):
        fails.append(msg)

    for p in ["robots.txt", "sitemap.xml", "llms.txt", "favicon.ico", "favicon.svg"]:
        s, _ = fetch(base + "/" + p)
        if s != 200:
            bad("/%s returned %s" % (p, s))

    s, xml = fetch(base + "/sitemap.xml")
    locs = []
    if s == 200:
        try:
            locs = [e.text.strip() for e in ET.fromstring(xml).iter("{http://www.sitemaps.org/schemas/sitemap/0.9}loc") if e.text]
        except ET.ParseError as e:
            bad("sitemap.xml is not valid XML: %s" % e)
    if s == 200 and not locs:
        bad("sitemap.xml lists no URLs")
    # the sitemap names margin.wiki; when checking another base (a test server) the same paths are asked of that base
    paths = [urlparse(u).path.lstrip("/") + ("?" + urlparse(u).query if urlparse(u).query else "") for u in locs]
    with ThreadPoolExecutor(8) as ex:
        got = list(ex.map(lambda p: (p, fetch(base + "/" + p)), paths))
    seen_html = {}
    for p, (st, body) in got:
        if st != 200:
            bad("sitemap URL /%s returned %s" % (p, st))
            continue
        page = p.split("?")[0] or "index.html"
        if page.endswith((".html", "")) and page not in seen_html:
            seen_html[page] = body
    for page, body in seen_html.items():
        t = re.search(r"<title>(.*?)</title>", body, re.S)
        d = re.search(r'<meta name="description" content="([^"]*)"', body)
        if not t or not t.group(1).strip():
            bad("/%s has no title in its HTML" % page)
        if not d or not d.group(1).strip():
            bad("/%s has no description in its HTML" % page)

    # 4. the home page's own requests
    s, home = fetch(base + "/")
    if s != 200:
        bad("home page returned %s" % s)
        return fails
    refs = set(re.findall(r'(?:src|href)="(\./[^"#?]+|/[^"#?/][^"#?]*)', home))
    refs |= {m for m in re.findall(r'(?:src|href)="(\./[^"#]+)"', home)}
    scripts = [r for r in refs if r.endswith(".js")]
    for sc in scripts:
        _, js = fetch(urljoin(base + "/", sc), tries=2)
        refs |= set("./" + m for m in re.findall(r"['\"](data/[A-Za-z0-9_./-]+\.json)['\"]", js))
        refs |= set("./" + m for m in re.findall(r"['\"](copy\.json)['\"]", js))
    for r in sorted(refs):
        if r.startswith("//") or r.startswith("http") or r.endswith(".md"):
            continue
        st, _ = fetch(urljoin(base + "/", r), tries=2)
        if st == 404:
            bad("home page asks for %s and gets 404" % r)

    # 5. one click from home
    s, cj = fetch(base + "/copy.json")
    links = []
    if s == 200:
        try:
            links = [l["href"].lstrip("./") for l in json.loads(cj)["siteHead"]["footerLinks"]]
        except (ValueError, KeyError, TypeError):
            bad("copy.json has no siteHead.footerLinks")
    if "footer.js" not in home:
        bad("the home page does not load js/footer.js, which draws the footer links")
    for want in MUST_BE_LINKED:
        if not any(l.split("?")[0] == want for l in links):
            bad("%s is not in the footer links drawn on the home page" % want)
    for l in links:
        st, _ = fetch(base + "/" + l)
        if st != 200:
            bad("footer link /%s returned %s" % (l, st))
    return fails


def self_test():
    import http.server
    import os
    import tempfile
    import threading

    global TRIES, PAUSE
    TRIES, PAUSE = 1, 0
    d = tempfile.mkdtemp()

    def w(name, text):
        os.makedirs(os.path.dirname(os.path.join(d, name)) or d, exist_ok=True)
        open(os.path.join(d, name), "w").write(text)

    page = '<html><head><title>T</title><meta name="description" content="D"/></head><body><script src="./js/footer.js"></script></body></html>'
    for n in ["index.html", "how-it-was-built.html", "agent-incidents.html", "event.html"]:
        w(n, page)
    w("js/footer.js", "fetch('./copy.json'); fetch('data/x.json');")
    w("data/x.json", "{}")
    w("robots.txt", "x")
    w("llms.txt", "x")
    w("favicon.ico", "x")
    w("favicon.svg", "x")
    w("copy.json", json.dumps({"siteHead": {"footerLinks": [{"href": "./how-it-was-built.html"}, {"href": "./agent-incidents.html"}, {"href": "./event.html"}]}}))
    ns = "http://www.sitemaps.org/schemas/sitemap/0.9"
    w("sitemap.xml", '<urlset xmlns="%s"><url><loc>https://margin.wiki/</loc></url><url><loc>https://margin.wiki/event.html</loc></url></urlset>' % ns)
    handler = lambda *a, **k: http.server.SimpleHTTPRequestHandler(*a, directory=d, **k)
    srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), handler)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    base = "http://127.0.0.1:%d" % srv.server_address[1]
    import io
    import contextlib
    with contextlib.redirect_stderr(io.StringIO()):
        assert check(base) == [], check(base)
        os.remove(os.path.join(d, "data/x.json"))
        assert any("404" in f for f in check(base)), "a missing data file must fail"
        w("data/x.json", "{}")
        w("event.html", '<html><head><title></title></head></html>')
        f = check(base)
        assert any("no title" in x for x in f) and any("no description" in x for x in f), f
        w("event.html", page)
        os.remove(os.path.join(d, "robots.txt"))
        assert any("robots.txt" in x for x in check(base))
    srv.shutdown()
    print("check_outside self-test ok")


if __name__ == "__main__":
    if "--self-test" in sys.argv:
        self_test()
        sys.exit(0)
    base = SITE
    if "--base" in sys.argv:
        base = sys.argv[sys.argv.index("--base") + 1].rstrip("/")
    problems = check(base)
    for p in problems:
        print("FAIL: " + p, file=sys.stderr)
    if problems:
        print("outside check: %d problem(s) on %s" % (len(problems), base), file=sys.stderr)
        sys.exit(1)
    print("outside check: %s is findable, every sitemap URL answers, the home page requests no 404" % base)
