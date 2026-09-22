#!/usr/bin/env python3
"""D1 (v1 freeze and ship brief): bake the real headline and corridor table
into index.html's own markup at collection time, so a crawler or a visitor
with JS off sees the actual measurement -- not "Loading this hour's
measurement...", which is what ships otherwise.

Runs AFTER tools/emit_corridor_summary.py, every pass. Idempotent: each run
replaces exactly what the LAST run wrote, using the same id="..." anchors
the client-side JS already targets, so baking twice in a row (or baking
then letting JS re-render on load) never duplicates or drifts. The waterfall
CHART stays client-rendered -- an SVG bar chart is worth building in one
place (the browser, where MarginChart-style code already exists), not
twice.

If data/corridor_summary.json is missing or unmeasurable, this leaves
index.html's existing baked content alone rather than blanking it back to
a loading state -- a real number from an earlier pass outlives a single
failed one, same as every other "gaps stay gaps" rule on this site never
means "erase what was already known."

Stdlib only.
"""

import json
import os
import re
import sys

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SUMMARY = os.path.join(HERE, "data", "corridor_summary.json")
INDEX_HTML = os.path.join(HERE, "index.html")


def esc(s):
    return (str(s).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
            .replace('"', "&quot;").replace("'", "&#39;"))


def pct(bps):
    v = bps / 100.0
    return ("+" if v >= 0 else "") + ("%.2f" % v) + "%"


def sub_html(home_copy):
    index_pointer = home_copy.get("indexPointer", "Every tracked currency’s own parallel-rate gap moved to")
    index_pointer_link = home_copy.get("indexPointerLink", "the index →")
    return (esc(home_copy.get("headlineSub", "")) + " " + esc(index_pointer) +
            ' <a href="./the-index.html" style="font-weight:600;color:#0B0B0B">' + esc(index_pointer_link) + "</a>")


def corridor_row_html(c, home_copy):
    wins = c["win_rate_taker_pct"] >= 10 or c["win_rate_maker_pct"] >= 10
    note = ""
    if c["corridor"] == "USD->MXN":
        note = '<div class="corridor-note">' + esc(home_copy.get("corridorMxnNote", "")) + "</div>"
    return (
        "<tr>"
        "<td><b>" + esc(c.get("route_words", c["corridor"])) + "</b></td>"
        '<td class="num">' + pct(c["taker_cost_bps_median"]) + "</td>"
        '<td class="num">' + pct(c["baseline_cost_bps_median"]) + "</td>"
        '<td class="' + ("win-yes" if wins else "win-no") + '">'
        + ("%.1f" % c["win_rate_taker_pct"]) + "% of hours" + note + "</td>"
        '<td><a href="./corridor.html?corridor=' + esc(c["corridor"]) + '" style="font-weight:600;color:#0B0B0B">'
        + esc(home_copy.get("seeCorridor", "see the receipt →")) + "</a></td>"
        "</tr>"
    )


def corridor_table_html(corridors, home_copy):
    cols = home_copy.get("corridorTableCols", {})
    rows = "".join(corridor_row_html(c, home_copy) for c in corridors)
    return (
        '<div class="waterfall-title">' + esc(home_copy.get("corridorTableTitle", "Every route, measured the same way")) + "</div>"
        '<table class="corridor-table"><thead><tr>'
        "<th>" + esc(cols.get("corridor", "ROUTE")) + "</th>"
        "<th>" + esc(cols.get("stablecoin", "BUYING IT NOW")) + "</th>"
        "<th>" + esc(cols.get("fiat", "BEST ORDINARY WAY")) + "</th>"
        "<th>" + esc(cols.get("winRate", "STABLECOIN WINS")) + "</th>"
        "<th></th></tr></thead><tbody>" + rows + "</tbody></table>"
    )


def replace_by_marker(html, name, new_inner):
    """Replace whatever sits between <!--BAKE:START:name--> and
    <!--BAKE:END:name--> with new_inner, keeping the markers themselves in
    place for the next run.

    Not tag-matching: the content baked in here (the corridor table, in
    particular) contains its own nested <div>s, and an earlier version of
    this function matched up to the first closing tag of the SAME kind
    rather than the one that actually closed the target element -- fine on
    a first bake into an empty placeholder, silently truncating everything
    after the injected content's own first nested </div> on every bake
    after that. Comment markers can't nest or get confused with real
    markup, so they don't have that failure mode regardless of what HTML
    is injected between them.
    """
    pattern = re.compile(
        r'(<!--BAKE:START:' + re.escape(name) + r'-->)(.*?)(<!--BAKE:END:' + re.escape(name) + r'-->)',
        re.S)
    if not pattern.search(html):
        return html, False
    return pattern.sub(lambda m: m.group(1) + new_inner + m.group(3), html, count=1), True


def main():
    if not os.path.exists(SUMMARY):
        print("  no data/corridor_summary.json yet -- leaving index.html's baked content as-is")
        return
    with open(SUMMARY) as f:
        doc = json.load(f)
    if doc.get("status") != "ok" or not doc.get("headline", {}).get("text"):
        print("  corridor_summary.json has no measurable headline this pass -- leaving prior bake in place")
        return

    with open(os.path.join(HERE, "copy.json")) as f:
        copy_doc = json.load(f)
    home_copy = copy_doc.get("home", {})

    with open(INDEX_HTML) as f:
        html = f.read()

    changed = False
    html, ok1 = replace_by_marker(html, "heroHeadline", esc(doc["headline"]["text"]))
    changed = changed or ok1

    html, ok2 = replace_by_marker(html, "heroSub", sub_html(home_copy))
    changed = changed or ok2

    if doc.get("corridors"):
        table = corridor_table_html(doc["corridors"], home_copy)
        html, ok3 = replace_by_marker(html, "corridorTableSection", table)
        changed = changed or ok3

    if not changed:
        print("  WARNING: none of the expected id= anchors were found in index.html -- "
              "the page structure moved and this script needs updating, not silently skipped")
        sys.exit(1)

    with open(INDEX_HTML, "w") as f:
        f.write(html)
    print("  baked headline + corridor table into index.html from data/corridor_summary.json")


if __name__ == "__main__":
    main()
