#!/usr/bin/env python3
"""Write copy.json's nav array into every live page's header.

DESIGN.md is explicit: "The nav is generated from copy.json's nav array
into every page by the bake step; no page carries a hand-written header."
Before this existed, each page below hand-typed its own <nav> block, and
they drifted -- some had five links (a stale "The machine room" entry),
some had four, `class="active"` landed on the wrong link, and copy.json's
own nav array still pointed at retired pages (calculator.html,
methodology.html). One source of truth, written everywhere, is the fix.

Only the <nav>...</nav> element is touched. The rest of each page's
<header> (logo, MCP/live status, the mobile nav-toggle button) is
page-specific chrome, not copy, so it stays hand-written.

Idempotent: replaces whatever <nav>...</nav> currently holds, so running
this twice in a row (or after copy.json changes) always converges on the
same markup.

Stdlib only.
"""

import json
import os
import re
import sys

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
COPY = os.path.join(HERE, "copy.json")

# Every page that carries the shared site nav. A page reachable only by
# deep link (ask.html, machine-room.html, corridor.html) still gets the
# same generated nav in its header -- DESIGN.md just keeps it out of the
# nav's own link list.
NAV_PAGES = [
    "index.html", "agent-incidents.html", "ask.html", "corridor.html",
    "country.html", "fee-tiers.html", "how-it-works.html",
    "machine-room.html", "sending-money.html", "the-index.html",
]
# findings.html is NOT in this list -- D3 retired it to a redirect stub
# (tools/write_redirects.py), same shape as the ten pages from Session 2,
# and a stub carries no <nav> for this script to bake into.

NAV_RE = re.compile(r"<nav>.*?</nav>", re.S)


def nav_html(items, current):
    lines = ["<nav>"]
    for item in items:
        href = item["href"]
        # Compare basenames: pages live at the repo root, hrefs are
        # "./name.html", so a plain string match already works, but this
        # stays correct if a href ever gains a query string or a deeper
        # relative path.
        active = os.path.basename(href) == current
        cls = ' class="active"' if active else ""
        lines.append(f'        <a href="{href}"{cls}>{item["label"]}</a>')
    lines.append("      </nav>")
    return "\n".join(lines)


def main():
    with open(COPY) as f:
        nav_items = json.load(f)["nav"]

    changed = []
    for page in NAV_PAGES:
        path = os.path.join(HERE, page)
        if not os.path.exists(path):
            print(f"  WARNING: {page} is in NAV_PAGES but does not exist", file=sys.stderr)
            continue
        with open(path) as f:
            html = f.read()
        if not NAV_RE.search(html):
            print(f"  WARNING: {page} has no <nav>...</nav> to replace -- "
                  f"header structure moved, this script needs updating", file=sys.stderr)
            sys.exit(1)
        new_html, n = NAV_RE.subn(lambda m: nav_html(nav_items, page), html, count=1)
        if new_html != html:
            with open(path, "w") as f:
                f.write(new_html)
            changed.append(page)

    if changed:
        print("  baked nav from copy.json into: " + ", ".join(changed))
    else:
        print("  nav already matches copy.json on every page")


if __name__ == "__main__":
    main()
