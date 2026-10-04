#!/usr/bin/env python3
"""Gate 1 for reader-facing PRs: the rendered style check.

Opens each page a PR can change, headless, at 390px and 1280px, and checks the
COMPUTED styles of every visible element -- what a reader sees, not what the
CSS says:

  size       at most one text element above 24px per page
  caps       no text-transform: uppercase; no word of 3+ ALL-CAPS letters
             (currency codes and a short acronym list are ignored)
  colour     text, background and border colours must be style.css tokens
             (the ink tints included); anything else, reds and purples
             above all, fails
  weights    only 400 and 600
  scroll     no horizontal scroll at 390px

One line per violation: page, selector, property, value. Any violation fails.

Legacy: pages that predate the gate already break some of these. Those known
violations are listed in tools/rendered_baseline.json as "property=value"
kinds per page and are tolerated until fixed; a NEW kind on any page, or any
violation on a page not in the baseline, fails. `--update-baseline` rewrites
the baseline from the current pages (it must never be run to hide a new
violation in a PR).

Usage:
  python3 tools/check_rendered.py                       # pages changed vs origin/main
  python3 tools/check_rendered.py --base origin/main
  python3 tools/check_rendered.py --all                 # every page
  python3 tools/check_rendered.py --pages index.html tape.html
  python3 tools/check_rendered.py --base-url https://margin.wiki --all   # live site
  python3 tools/check_rendered.py --self-test           # tests/bad_page.html must FAIL
  python3 tools/check_rendered.py --all --update-baseline
"""

import argparse
import glob
import json
import os
import re
import sys

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(HERE, "tools"))
from gate_common import PAGE_QUERY, all_pages, changed_files, open_page, pages_for_change, serve  # noqa: E402
from headless import Page  # noqa: E402

BASELINE = os.path.join(HERE, "tools", "rendered_baseline.json")
VIEWPORTS = ((390, 844, True), (1280, 900, False))
ALLOWED_WEIGHTS = ("400", "600")
MAX_BIG_TEXT_PX = 24
ACRONYMS = {"UTC", "USD", "USDT", "USDC", "API", "MCP", "SQL", "CSV", "JSON", "ECB", "ISO", "URL",
            "HTML", "AI", "FAQ", "SGD", "AUD", "NZD", "PHP", "MXN", "INR", "NGN", "THB", "KRW",
            # provider and venue names, and unit names, that are written in capitals by their owners
            "BNZ", "ANZ", "HSBC", "OFX", "ACH", "BCRA", "BTC", "CFA", "SPEI", "ETH", "OKX", "HTX", "MAX", "NAB",
            "ASB", "WBC", "BOQ", "CBA", "DBS", "OCBC", "UOB", "WISE", "XAF", "XOF", "XDR", "IMF", "ECB", "SEB"}


def token_colors():
    """Opaque RGB triples from style.css's :root custom properties."""
    css = open(os.path.join(HERE, "style.css"), encoding="utf-8").read()
    root = re.search(r":root\s*\{(.*?)\n\}", css, re.S)
    out = set()
    for h in re.findall(r"#([0-9a-fA-F]{6})\b", root.group(1) if root else css):
        out.add((int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)))
    return sorted(out)


def currency_codes():
    return sorted(os.path.splitext(os.path.basename(p))[0]
                  for p in glob.glob(os.path.join(HERE, "data", "countries", "*.json")))


# Runs inside the page. Returns a list of {prop, value, selector, extra?}.
PROBE = r"""
(function(TOKENS, CAPS_OK, ALLOWED_WEIGHTS, MAX_BIG, INK){
  var out = [];
  function sel(el){
    var s = el.tagName.toLowerCase();
    if (el.id) s += '#' + el.id;
    else if (el.classList && el.classList.length) s += '.' + [].slice.call(el.classList, 0, 2).join('.');
    var p = el.parentElement;
    if (p && p !== document.body) {
      var ps = p.tagName.toLowerCase();
      if (p.id) ps += '#' + p.id; else if (p.classList && p.classList.length) ps += '.' + p.classList[0];
      s = ps + ' > ' + s;
    }
    return s;
  }
  function visible(el){
    if (!el.getClientRects().length) return false;
    var cs = getComputedStyle(el);
    if (cs.visibility === 'hidden' || cs.display === 'none' || parseFloat(cs.opacity) === 0) return false;
    for (var a = el; a; a = a.parentElement) { if (a.hidden) return false; }
    return true;
  }
  function rgb(c){
    var m = c.match(/rgba?\(\s*([\d.]+)[ ,]+([\d.]+)[ ,]+([\d.]+)(?:\s*[,/]\s*([\d.%]+))?\s*\)/);
    if (m) { var a = m[4] === undefined ? 1 : (m[4].indexOf('%') > -1 ? parseFloat(m[4]) / 100 : parseFloat(m[4]));
             return [Math.round(m[1]), Math.round(m[2]), Math.round(m[3]), a]; }
    m = c.match(/color\(srgb\s+([\d.]+)\s+([\d.]+)\s+([\d.]+)(?:\s*\/\s*([\d.%]+))?\)/);
    if (m) { var a2 = m[4] === undefined ? 1 : (m[4].indexOf('%') > -1 ? parseFloat(m[4]) / 100 : parseFloat(m[4]));
             return [Math.round(m[1] * 255), Math.round(m[2] * 255), Math.round(m[3] * 255), a2]; }
    return null;
  }
  function colourOk(c){
    var v = rgb(c);
    if (!v) return true;
    if (v[3] === 0) return true;
    var same = function(t){ return t[0] === v[0] && t[1] === v[1] && t[2] === v[2]; };
    if (TOKENS.some(same)) return true;
    return same(INK);
  }
  var seen = {};
  function add(prop, value, el){
    var k = prop + '|' + value + '|' + sel(el);
    if (seen[k]) return; seen[k] = 1;
    out.push({prop: prop, value: value, selector: sel(el)});
  }
  var skipTag = {SCRIPT:1, STYLE:1, NOSCRIPT:1, HEAD:1, TITLE:1, META:1, LINK:1, SVG:1, PATH:1};
  var big = [];
  var all = document.body.querySelectorAll('*');
  for (var i = 0; i < all.length; i++) {
    var el = all[i];
    if (skipTag[el.tagName.toUpperCase()] || !visible(el)) continue;
    var cs = getComputedStyle(el);
    var own = '';
    for (var n = el.firstChild; n; n = n.nextSibling) { if (n.nodeType === 3 && n.nodeValue.trim()) own += n.nodeValue + ' '; }
    var hasText = own.trim().length > 0;
    if (hasText) {
      var fs = parseFloat(cs.fontSize);
      if (fs > MAX_BIG) big.push([fs, el]);
      if (cs.textTransform === 'uppercase') add('text-transform', 'uppercase', el);
      var w = String(cs.fontWeight);
      if (ALLOWED_WEIGHTS.indexOf(w) < 0) add('font-weight', w, el);
      if (!colourOk(cs.color)) add('color', cs.color, el);
      var inCode = !!el.closest('code, pre, .ccy, .cc, .code, [data-ccy]');
      if (!inCode) {
        var words = own.match(/\b[A-Z]{3,}\b/g) || [];
        for (var j = 0; j < words.length; j++) {
          if (CAPS_OK.indexOf(words[j]) < 0) { add('all-caps-text', words[j], el); break; }
        }
      }
    }
    var bg = rgb(cs.backgroundColor);
    if (bg && bg[3] > 0 && !colourOk(cs.backgroundColor)) add('background-color', cs.backgroundColor, el);
    ['Top', 'Right', 'Bottom', 'Left'].forEach(function(side){
      if (parseFloat(cs['border' + side + 'Width']) > 0 && cs['border' + side + 'Style'] !== 'none') {
        var bc = cs['border' + side + 'Color'];
        if (!colourOk(bc)) add('border-color', bc, el);
      }
    });
  }
  if (big.length > 1) {
    for (var b = 1; b < big.length; b++) add('font-size>' + MAX_BIG + 'px', big[b][0] + 'px (not the only large text)', big[b][1]);
  }
  var de = document.documentElement;
  if (de.scrollWidth > de.clientWidth + 1) {
    out.push({prop: 'horizontal-scroll', value: de.scrollWidth + 'px wide in a ' + de.clientWidth + 'px viewport', selector: 'html'});
  }
  return JSON.stringify(out);
})(__T__, __C__, __W__, __M__, __I__)
"""


def check_page(page, url, name):
    """All violations for one page across both viewports."""
    found = []
    toks = token_colors()
    caps_ok = sorted(set(currency_codes()) | ACRONYMS)
    if page.ws is None:
        page.visit("about:blank")  # opens the protocol connection
    for width, height, mobile in VIEWPORTS:
        page.set_viewport(width, height, mobile=mobile)
        page.visit(url)
        js = (PROBE.replace("__T__", json.dumps([list(t) for t in toks]))
              .replace("__C__", json.dumps(caps_ok))
              .replace("__W__", json.dumps(list(ALLOWED_WEIGHTS)))
              .replace("__M__", str(MAX_BIG_TEXT_PX))
              .replace("__I__", json.dumps([32, 30, 29])))
        data = json.loads(page.eval_js(js) or "[]")
        for v in data:
            if width == 390 and v["prop"] != "horizontal-scroll" and any(
                    x["prop"] == v["prop"] and x["value"] == v["value"] and x["selector"] == v["selector"]
                    for x in found):
                continue
            if v["prop"] == "horizontal-scroll" and width != 390:
                continue
            v["page"], v["width"] = name, width
            if not any(x["page"] == name and x["prop"] == v["prop"] and x["value"] == v["value"]
                       and x["selector"] == v["selector"] for x in found):
                found.append(v)
    page.clear_viewport()
    return found


def kind(v):
    return "%s=%s" % (v["prop"], v["value"])


def load_baseline():
    return json.load(open(BASELINE)) if os.path.exists(BASELINE) else {}


def run(base_url, names, quiet=False):
    results = {}
    with open_page(settle=4.0) as page:
        for name in names:
            url = base_url + "/" + name.split("?")[0] + (PAGE_QUERY.get(name, "") if "?" not in name else "?" + name.split("?", 1)[1])
            results[name] = check_page(page, url, name)
            if not quiet:
                sys.stderr.write("  rendered %s: %d violation(s)\n" % (name, len(results[name])))
    return results


def self_test():
    base, stop = serve(HERE)
    try:
        res = run(base, ["tests/bad_page.html"], quiet=True)["tests/bad_page.html"]
    finally:
        stop()
    props = {v["prop"] for v in res}
    need = {"text-transform", "font-weight", "color", "all-caps-text", "horizontal-scroll"}
    missing = need - props
    for v in res:
        print("%s | %s | %s | %s" % (v["page"], v["selector"], v["prop"], v["value"]))
    if missing or not res:
        print("SELF-TEST FAILED: the gate did not catch %s on tests/bad_page.html" % sorted(missing or need))
        return 1
    print("self-test ok: the gate fails tests/bad_page.html on %d rule(s)" % len(props))
    return 0


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", default=os.environ.get("GATE_BASE", "origin/main"))
    ap.add_argument("--all", action="store_true")
    ap.add_argument("--pages", nargs="*")
    ap.add_argument("--base-url")
    ap.add_argument("--self-test", action="store_true")
    ap.add_argument("--update-baseline", action="store_true")
    ap.add_argument("--json-out")
    a = ap.parse_args()

    if a.self_test:
        return self_test()

    if a.pages:
        names = a.pages
    elif a.all:
        names = all_pages()
    else:
        names = pages_for_change(changed_files(a.base))
    if not names:
        print("rendered check: no reader-facing page changed, nothing to render")
        return 0

    stop = None
    base_url = a.base_url
    if not base_url:
        base_url, stop = serve(HERE)
    try:
        results = run(base_url, names)
    finally:
        if stop:
            stop()

    if a.json_out:
        json.dump(results, open(a.json_out, "w"), indent=1)

    if a.update_baseline:
        base = load_baseline()
        for name, vs in results.items():
            base[name] = sorted({kind(v) for v in vs})
        json.dump(base, open(BASELINE, "w"), indent=1, sort_keys=True)
        open(BASELINE, "a").write("\n")
        print("rendered baseline updated for %d page(s)" % len(results))
        return 0

    baseline = load_baseline()
    bad = []
    tolerated = 0
    for name, vs in results.items():
        known = set(baseline.get(name, []))
        for v in vs:
            if kind(v) in known:
                tolerated += 1
            else:
                bad.append(v)
    for v in bad:
        print("%s | %s | %s | %s" % (v["page"], v["selector"], v["prop"], v["value"]))
    if bad:
        print("RENDERED CHECK FAILED: %d new violation(s) on %d page(s) (%d known legacy violation(s) tolerated)"
              % (len(bad), len({v["page"] for v in bad}), tolerated))
        return 1
    print("rendered check ok: %d page(s), no new violations (%d known legacy violation(s) tolerated)"
          % (len(results), tolerated))
    return 0


if __name__ == "__main__":
    sys.exit(main())
