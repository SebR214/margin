#!/usr/bin/env python3
"""The one site menu (2 Nov 2026, DESIGN.md "Nav"). Writes copy.json "siteNav" into js/site_nav.js, between the
// DATA:begin and // DATA:end lines, so the menu's words live in copy.json and every page draws the same menu.

    python3 tools/bake_nav.py            # write it
    python3 tools/bake_nav.py --check    # exit 1 if js/site_nav.js does not match copy.json

Loud failure: a missing block, or more than seven items in the bar.
"""
import json
import os
import re
import sys

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
COPY = os.path.join(HERE, "copy.json")
JS = os.path.join(HERE, "js", "site_nav.js")
BLOCK = re.compile(r"(  // DATA:begin\n  var N = ).*?(;\n  // DATA:end)", re.S)


def main():
    nav = json.load(open(COPY, encoding="utf-8"))["siteNav"]
    if len(nav["main"]) + 1 > 7:
        sys.exit("bake_nav: more than seven items in the bar (DESIGN.md Nav)")
    src = open(JS, encoding="utf-8").read()
    if not BLOCK.search(src):
        sys.exit("bake_nav: js/site_nav.js has no DATA block")
    new = BLOCK.sub(lambda m: m.group(1) + json.dumps(nav, ensure_ascii=False) + m.group(2), src, count=1)
    if "--check" in sys.argv:
        if new != src:
            sys.exit("bake_nav: js/site_nav.js does not match copy.json siteNav; run python3 tools/bake_nav.py")
        print("bake_nav: js/site_nav.js matches copy.json")
        return
    if new != src:
        open(JS, "w", encoding="utf-8").write(new)
        print("bake_nav: wrote js/site_nav.js from copy.json")
    else:
        print("bake_nav: js/site_nav.js already matches copy.json")


if __name__ == "__main__":
    main()
