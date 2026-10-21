#!/usr/bin/env python3
"""A route added to collector.CORRIDORS reaches the Routes page with no other edit (SEB-301).

Adds a dummy route, SGD->TST, to a copy of collector.CORRIDORS before any emitter
is imported. Its rows are SGD->PHP's stored rows with the route id changed, in a
temporary data folder: samples.csv carries them under the new id and its own
panel file, providers_sgdtst.csv, is a copy of providers.csv. Then:

  - every emitter's route list and panel map holds the new route;
  - tools/emit_routes.py, run on that folder, writes it to data/routes_summary.json
    and data/routes_hourly.json, named by its id until the writer fills its
    copy.json "routeNames" slot.

Nothing under the real data/ is written.

    python3 tests/check_new_route.py
"""

import csv
import json
import os
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "tools"))

import collector  # noqa: E402

NEW, LIKE, PANEL = "SGD->TST", "SGD->PHP", "providers_sgdtst.csv"
corridors = dict(collector.CORRIDORS)
corridors[NEW] = dict(corridors[LIKE], dst="TST", providers_file=PANEL)
collector.CORRIDORS = corridors  # the copy every emitter below now reads

import audit_numbers  # noqa: E402
import emit_corridor_summary  # noqa: E402
import emit_latest  # noqa: E402
import emit_price_changes  # noqa: E402
import emit_provider_receipts  # noqa: E402
import emit_providers  # noqa: E402
import emit_routes  # noqa: E402
import record_common  # noqa: E402


def main():
    fails = []

    def check(cond, what):
        if not cond:
            fails.append(what)

    check(emit_routes.ROUTES[-1] == NEW, "emit_routes.ROUTES")
    check(emit_corridor_summary.CORRIDORS[-1] == NEW, "emit_corridor_summary.CORRIDORS")
    for name, panels in [("emit_routes", emit_routes.PANELS), ("emit_providers", emit_providers.PANELS),
                         ("emit_latest", emit_latest.PANELS), ("emit_price_changes", emit_price_changes.PANELS),
                         ("emit_provider_receipts", emit_provider_receipts.PANELS),
                         ("audit_numbers", audit_numbers.PROVIDER_PANELS)]:
        check(panels.get(NEW) == PANEL, name + " panel map")
    check(PANEL in record_common.READING_FILES, "record_common.READING_FILES")

    src = os.path.join(ROOT, "data")
    with tempfile.TemporaryDirectory() as tmp:
        data = os.path.join(tmp, "data")
        os.mkdir(data)
        with open(os.path.join(src, emit_routes.SAMPLES), newline="") as f:
            rd = csv.DictReader(f)
            fields, rows = rd.fieldnames, [r for r in rd if r["corridor"] == LIKE]
        with open(os.path.join(data, emit_routes.SAMPLES), "w", newline="") as f:
            w = csv.DictWriter(f, fieldnames=fields)
            w.writeheader()
            w.writerows(rows)
            w.writerows(dict(r, corridor=NEW) for r in rows)
        os.symlink(os.path.join(src, emit_routes.PANELS[LIKE]), os.path.join(data, emit_routes.PANELS[LIKE]))
        os.symlink(os.path.join(src, emit_routes.PANELS[LIKE]), os.path.join(data, PANEL))

        emit_routes.DATA = data
        emit_routes.OUT = {k: os.path.join(data, os.path.basename(p)) for k, p in emit_routes.OUT.items()}
        emit_routes.main()

        summary = json.load(open(os.path.join(data, "routes_summary.json")))
        hourly = json.load(open(os.path.join(data, "routes_hourly.json")))
        ids = [r["id"] for r in summary["routes"]]
        check(ids == [LIKE, NEW], "routes_summary.json routes are %s" % ids)
        new = next((r for r in hourly["routes"] if r["id"] == NEW), None)
        check(new is not None, "routes_hourly.json has the new route")
        if new:
            check(new["route_words"] == NEW and new["dest"] is None, "an unnamed route shows its id")
            check(sum(len(a["hours"]) for a in new["amounts"]) > 0, "the new route has priced hours")
        check("data/" + PANEL in hourly["source_files"], "routes_hourly.json names the new panel file")

    if fails:
        print("new route FAILED (%d)" % len(fails))
        for f in fails:
            print("  - " + f)
        return 1
    print("new route ok: %s reaches routes_summary.json with no other edit" % NEW)
    return 0


if __name__ == "__main__":
    sys.exit(main())
