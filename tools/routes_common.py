#!/usr/bin/env python3
"""The one list of routes every emitter reads (SEB-301).

A route is an entry in collector.py CORRIDORS. Its comparison panel is that
entry's providers_file (providers.csv has no corridor column and a frozen
header, so each route has its own file with the same header). Its names are in
copy.json block "routeNames", keyed by the same id, because every
reader-facing word lives in copy.json:

  fromTo   "Singapore to the Philippines"
  dest     "the Philippines", the destination-only phrase
  sending  "Singapore dollars to the Philippines", money and destination

A new route therefore needs no edit here or in any emitter. Until the writer
fills its names the slot is empty and each emitter falls back the way it
always has (the route id, or null).

The pages do not import this: they read the route list from
data/routes_summary.json (js/route.js) and data/corridor_summary.json
(corridor.html), which the emitters write from it.

Stdlib only. collector.py imports only the standard library at module level.
"""

import json
import os
import sys

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if HERE not in sys.path:
    sys.path.insert(0, HERE)
from collector import CORRIDORS  # noqa: E402

COPY = os.path.join(HERE, "copy.json")

# collector.py order, the order every page lists routes in.
ROUTES = list(CORRIDORS)
PANELS = {c: cfg.get("providers_file", "providers.csv") for c, cfg in CORRIDORS.items()}


def _names(field):
    with open(COPY, encoding="utf-8") as f:
        block = json.load(f).get("routeNames") or {}
    return {c: v[field] for c, v in block.items() if isinstance(v, dict) and v.get(field)}


ROUTE_WORDS = _names("fromTo")
ROUTE_DEST = _names("dest")
SENDING_WORDS = _names("sending")
