#!/usr/bin/env python3
"""Design ratchet: a PR may not make a reader-facing page louder.

DESIGN.md and VISION.md say the pages keep one quiet register: sentence-case
labels, one or two weights, ink plus greys, accent colours only for data. No
script could enforce taste, but it can enforce "no more than before". This
counts four things per reader page and fails if any count goes UP against
tools/design_baseline.json:

  allcaps_copy   copy.json strings that are ALL CAPS (labels, statuses)
  css_uppercase  `text-transform:uppercase` in a page's own CSS
  heavy_weight   font-weight 800/900 in a page's own CSS
  off_palette    hex colours in a page's own CSS outside the allowed set

Counts going down is fine (and `--update` lowers the baseline). Stdlib only.

A second mode, --style, renders the seven reader pages (home, countries, sending money, sources, findings,
how it works, country) at 1300px and 390px and measures the page title, the text under it, the section
headings, the filter pills, the running-text link underline and the gap between the header and the title.
It fails if any page differs from the home page (css/site_page.css is where those values live).
--perturb adds a deliberate change first, to prove the check can fail.

Usage: python3 tools/check_design.py [--update] [--style [--perturb]]
"""
import glob
import json
import os
import re
import sys

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BASELINE = os.path.join(HERE, "tools", "design_baseline.json")

# ink, greys, rules, white, the DESIGN.md data palette and its neutrals.
ALLOWED = {
    "#0B0B0B", "#000", "#000000", "#FFF", "#FFFFFF", "#333", "#333333", "#6B6B6B", "#7D7979", "#9A9A9A",
    "#D3D0CB", "#EDEDED", "#F0F0F0", "#F6F6F6", "#F5F5F5", "#FAFAFA", "#EEE", "#EEEEEE", "#DDD", "#DDDDDD",
    "#817FCC", "#3F3047", "#F0EBD8", "#201E1D",
}
HEX = re.compile(r"#[0-9A-Fa-f]{3}(?:[0-9A-Fa-f]{3})?\b")


def reader_pages():
    out = []
    for f in sorted(glob.glob(os.path.join(HERE, "*.html"))):
        out.append(f)
    return out


def own_css(src):
    return "\n".join(re.findall(r"<style[^>]*>(.*?)</style>", src, re.S | re.I))


def count_allcaps(node):
    n = 0
    if isinstance(node, dict):
        for v in node.values():
            n += count_allcaps(v)
    elif isinstance(node, list):
        for v in node:
            n += count_allcaps(v)
    elif isinstance(node, str):
        letters = re.sub(r"[^A-Za-z]", "", re.sub(r"\{[^}]*\}|<[^>]*>", "", node))
        if len(letters) >= 4 and letters.isupper():
            n += 1
    return n


def measure():
    counts = {"copy.json": {"allcaps_copy": count_allcaps(json.load(open(os.path.join(HERE, "copy.json"))))}}
    for f in reader_pages():
        css = own_css(open(f, encoding="utf-8").read())
        bad = {h.upper() for h in HEX.findall(css) if h.upper() not in {a.upper() for a in ALLOWED}}
        counts[os.path.basename(f)] = {
            "css_uppercase": len(re.findall(r"text-transform\s*:\s*uppercase", css, re.I)),
            "heavy_weight": len(re.findall(r"font-weight\s*:\s*(?:800|900)\b", css)),
            "off_palette": len(bad),
        }
    return counts


STYLE_PAGES = ["index.html", "countries.html", "country.html?ccy=PHP", "sending-money.html?route=SGD-PHP&amount=5000",
               "sources.html", "findings.html", "how-it-works.html"]
STYLE_PROBE = r"""
(function () {
  var cs = function (e) { return getComputedStyle(e); };
  var h1 = document.querySelector('h1');
  var head = document.querySelector('.hp-head,.ci-head,.c-head,.sm-head,.s-head,.fp-head,.mwh');
  var lead = h1 && h1.nextElementSibling && h1.nextElementSibling.tagName === 'P' ? h1.nextElementSibling : null;   // a page with no text under its title has none to measure
  var h2 = document.querySelector('h2');
  var pill = [].filter.call(document.querySelectorAll('button.hp-btn,button.c-chip,button.ci-pill,button.sm-pill,button.pill'), function (x) { return x.getAttribute('aria-pressed') !== 'true' && !x.classList.contains('on'); })[0];
  var lk = [].filter.call(document.querySelectorAll('p a, li a'), function (x) { return !x.closest('header,nav,.hp-head,footer') && x.innerText.trim().length > 3; })[0];
  var o = {};
  o.title = h1 ? cs(h1).fontSize + ' ' + cs(h1).fontWeight : 'none';
  o.lead = lead ? cs(lead).fontSize + ' ' + cs(lead).color : 'none';
  o.h2 = h2 ? cs(h2).fontSize + ' ' + cs(h2).fontWeight : 'none';
  o.leadgap = h1 && lead ? Math.round(lead.getBoundingClientRect().top - h1.getBoundingClientRect().bottom) + 'px' : 'none';
  var first = document.querySelector('.cnav,.fnav') || h1;   // a page with a back link above its title keeps the 40px above that row
  o.gap = first && head ? Math.round(first.getBoundingClientRect().top - head.getBoundingClientRect().bottom) + 'px' : 'none';
  if (pill) { o.pill = [cs(pill).borderTopLeftRadius, cs(pill).minHeight, cs(pill).fontWeight, cs(pill).fontSize, cs(pill).borderTopWidth, cs(pill).borderTopColor].join(' '); }
  if (lk) { o.link = cs(lk).textDecorationLine + ' ' + cs(lk).textDecorationThickness + ' ' + cs(lk).textDecorationColor; }
  return JSON.stringify(o);
})()
"""


def style_check(perturb=False):
    sys.path.insert(0, os.path.join(HERE, "tools"))
    from gate_common import open_page, serve  # noqa: E402
    base, stop = serve(HERE)
    seen = {}
    try:
        with open_page(settle=4.0) as page:
            page.visit("about:blank")
            for width, height, mobile in ((1300, 900, False), (390, 844, True)):
                page.set_viewport(width, height, mobile=mobile)
                for name in STYLE_PAGES:
                    page.visit(base + "/" + name)
                    if perturb and name.startswith("sources"):
                        page.eval_js("document.querySelector('h1').style.setProperty('font-size','30px','important');'ok'")
                    seen[(width, name)] = json.loads(page.eval_js(STYLE_PROBE) or "{}")
            page.clear_viewport()
    finally:
        stop()
    bad = []
    for width in (1300, 390):
        std = seen[(width, STYLE_PAGES[0])]
        for name in STYLE_PAGES[1:]:
            got = seen[(width, name)]
            for k, v in std.items():
                if k in ('lead', 'leadgap') and got.get(k) == 'none':
                    continue    # a page may have no text under its title (how it works, after its subtitle was removed)
                if k in got and got[k] != v:
                    bad.append("%dpx %s: %s is %r, home has %r" % (width, name.split("?")[0], k, got[k], v))
    if bad:
        print("style check FAILED (a page differs from the home page):")
        for line in bad:
            print("  " + line)
        return 1
    print("style check ok (%d pages at 1300px and 390px match the home page)" % len(STYLE_PAGES))
    return 0


def main():
    if "--style" in sys.argv:
        return style_check("--perturb" in sys.argv)
    now = measure()
    if "--update" in sys.argv:
        json.dump(now, open(BASELINE, "w"), indent=1, sort_keys=True)
        open(BASELINE, "a").write("\n")
        print("design baseline updated")
        return 0
    base = json.load(open(BASELINE)) if os.path.exists(BASELINE) else {}
    bad = []
    for page, metrics in now.items():
        for k, v in metrics.items():
            b = base.get(page, {}).get(k)
            if b is None:
                b = 0 if page not in base else v  # a brand-new page starts at zero
            if v > b:
                bad.append("%s: %s went from %d to %d" % (page, k, b, v))
    if bad:
        print("design check FAILED (the page got louder than the baseline):")
        for line in bad:
            print("  " + line)
        print("Fix the styling, or if a count is truly warranted, run --update in the same PR and say why.")
        return 1
    print("design check ok (%d pages, nothing louder than baseline)" % (len(now) - 1))
    return 0


if __name__ == "__main__":
    sys.exit(main())
