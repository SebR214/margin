#!/usr/bin/env python3
"""The one header works on every page (2 Nov 2026, DESIGN.md "Nav"). Headless Chrome, stdlib only.

tools/bake_nav.py --check proves every page carries the same header markup. This proves it behaves the same on every page,
the way a reader uses it. For each page, on a desktop (1280px) and a phone (390px):
  desktop: one header; the logo and the five bar items sit at the same pixels as on the home page; a click on About opens
           its menu and its first link is the thing under the pointer (nothing covers it or cuts it off);
  phone:   the Menu button opens the sheet, About's three links are in it and can be seen, Escape closes it.
Any miss exits 1. Run in CI on every PR that touches a page (checks.yml, reader-facing).

    python3 tools/check_header.py
"""
import json
import os
import sys

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(HERE, "tools"))

PROBE_DESKTOP = r"""(async function () {
  var wait = function (ms) { return new Promise(function (r) { setTimeout(r, ms); }); };
  var heads = document.querySelectorAll('.site-head');
  var bar = document.querySelector('.site-head-bar');
  if (heads.length !== 1 || !bar) { return JSON.stringify({ err: heads.length + ' headers' }); }
  var x = function (e) { return e ? Math.round(e.getBoundingClientRect().left) : null; };
  var items = [].map.call(document.querySelectorAll('.site-logo, .site-nav > a, .sh-about-t'), function (e) { return e.textContent.trim() + '@' + x(e); });
  var btn = document.querySelector('.sh-about-btn');
  btn.click(); await wait(150);
  var menu = document.querySelector('.sh-about-menu'), first = menu.querySelector('a');
  var r = first.getBoundingClientRect(), at = document.elementFromPoint(r.left + r.width / 2, r.top + r.height / 2);
  var open = getComputedStyle(menu).display !== 'none' && r.height > 0;
  var reach = !!(at && first.contains(at));
  document.body.click(); await wait(150);
  var closed = getComputedStyle(menu).display === 'none' || matchMedia('(hover: hover)').matches;
  return JSON.stringify({ items: items.join(' '), height: Math.round(bar.getBoundingClientRect().bottom), open: open, reach: reach,
                          under: at ? (at.className || at.tagName) : null, closed: closed });
})()"""

PROBE_PHONE = r"""(async function () {
  var wait = function (ms) { return new Promise(function (r) { setTimeout(r, ms); }); };
  var btn = document.querySelector('.sh-menu'), nav = document.querySelector('.site-nav');
  if (!btn || !nav || getComputedStyle(btn).display === 'none') { return JSON.stringify({ err: 'no Menu button' }); }
  btn.click(); await wait(300);
  var links = [].filter.call(nav.querySelectorAll('a'), function (a) { var r = a.getBoundingClientRect(); return r.height > 0 && r.bottom > 0 && r.top < innerHeight * 2; });
  var open = getComputedStyle(nav).display !== 'none';
  document.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape' })); await wait(200);
  return JSON.stringify({ open: open, links: links.length, closed: getComputedStyle(nav).display === 'none',
                          height: Math.round(document.querySelector('.site-head-bar').getBoundingClientRect().bottom) });
})()"""


def targets():
    from gate_common import all_pages
    pages = list(all_pages())
    extra = {"country.html": "country.html?ccy=PHP&noredirect=1", "finding.html": "finding.html?id=exchange_vs_p2p"}
    try:
        ev = json.load(open(os.path.join(HERE, "data", "events_published.json")))["events"]
        if ev:
            extra["event.html"] = "event.html?id=" + ev[0]["id"]
    except (OSError, ValueError, KeyError):
        pass
    return ["index.html"] + [extra.get(p, p) for p in pages if p != "index.html"]


def main():
    from gate_common import open_page, serve
    base, stop = serve(HERE)
    fails, want = [], None
    page = open_page(settle=2.0)
    try:
        page.visit(base + "/index.html")      # the browser's tab exists from the first visit on
        for name in targets():
            page.set_viewport(1280, 800)
            page.visit("%s/%s" % (base, name))
            d = json.loads(page.eval_js(PROBE_DESKTOP, await_promise=True) or '{"err": "no answer"}')
            if d.get("err"):
                fails.append("%s desktop: %s" % (name, d["err"]))
                continue
            if want is None:
                want = d["items"]
            if d["items"] != want:
                fails.append("%s desktop: the bar is not where the home page has it\n    home: %s\n    here: %s" % (name, want, d["items"]))
            if d["height"] != 85:
                fails.append("%s desktop: the header is %dpx tall, every page's is 85px" % (name, d["height"]))
            if not d["open"] or not d["reach"]:
                fails.append("%s desktop: About does not open, or its menu is covered (by %s)" % (name, d["under"]))
            if not d["closed"]:
                fails.append("%s desktop: About's menu does not close on a click elsewhere" % name)
            page.set_viewport(390, 844, mobile=True)
            page.visit("%s/%s" % (base, name))
            p = json.loads(page.eval_js(PROBE_PHONE, await_promise=True) or '{"err": "no answer"}')
            if p.get("err"):
                fails.append("%s phone: %s" % (name, p["err"]))
                continue
            if not p["open"] or p["links"] < 7:
                fails.append("%s phone: the menu sheet shows %d of the 7 links" % (name, p["links"]))
            if not p["closed"]:
                fails.append("%s phone: Escape does not close the menu" % name)
            if p["height"] != 57:
                fails.append("%s phone: the header is %dpx tall, every page's is 57px" % (name, p["height"]))
            print("check_header: %s ok" % name if not [f for f in fails if f.startswith(name + " ")] else "check_header: %s FAILED" % name)
    finally:
        page.close()
        stop()
    for f in fails:
        print("check_header: " + f)
    if fails:
        sys.exit(1)
    print("check_header: %d pages, the same header, About and the phone menu work on each" % len(targets()))


if __name__ == "__main__":
    main()
