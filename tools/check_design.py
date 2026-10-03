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

Usage: python3 tools/check_design.py [--update]
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


def main():
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
