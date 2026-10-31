"""Research page 2, "Markets inside one country disagree" (SEB-423 step 3), from data/source_pairs.json (tools/emit_source_pairs.py).

For each country with two or more sources compared on at least the file's min_common_hours hours, the pair that sat furthest apart
(its median gap over the window) and how many hours it covers. Countries are then counted in three bands: within 0.5%, 0.5% to 3%,
3% or more. Every number is read off the file; the words are copy.json's researchData.
"""
import json
import os

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
DATA = os.path.join(ROOT, "data")
TIGHT = 0.5
WIDE = 3.0


def countries(doc, names=None):
    out = []
    for ccy, m in doc["markets"].items():
        ps = [p for p in m.get("pairs", []) if p["hours"] >= doc["min_common_hours"] and p.get("median_gap_pct") is not None]
        if not ps:
            continue
        w = max(ps, key=lambda p: (p["median_gap_pct"], p["hours"]))
        out.append({"ccy": ccy, "country": (names or {}).get(ccy, ccy), "gap_pct": w["median_gap_pct"], "a": w["a"], "b": w["b"], "hours": w["hours"],
                    "pairs": len(ps)})
    out.sort(key=lambda r: (-r["gap_pct"], r["ccy"]))
    return out


def bands(rows):
    return {"tight": sum(1 for r in rows if r["gap_pct"] <= TIGHT), "middle": sum(1 for r in rows if TIGHT < r["gap_pct"] < WIDE),
            "wide": sum(1 for r in rows if r["gap_pct"] >= WIDE)}


def build():
    doc = json.load(open(os.path.join(DATA, "source_pairs.json")))
    names = {c["ccy"]: c.get("country") or c["ccy"] for c in json.load(open(os.path.join(DATA, "heatmap_daily.json"))).get("currencies", [])}
    rows = countries(doc, names)
    if not rows:
        raise SystemExit("source_pairs: no country had two sources with enough common hours")
    return {"as_of_utc": doc["as_of_utc"], "window_days": doc["window_days"], "min_common_hours": doc["min_common_hours"], "tight_pct": TIGHT, "wide_pct": WIDE,
            "label": "observed", "source": "data/source_pairs.json, tools/research/source_pairs.py", "compared": len(rows), "bands": bands(rows), "countries": rows}


def self_test():
    doc = {"min_common_hours": 24, "markets": {
        "AAA": {"pairs": [{"a": "x", "b": "y", "hours": 100, "median_gap_pct": 0.2}, {"a": "x", "b": "z", "hours": 100, "median_gap_pct": 4.0}]},
        "BBB": {"pairs": [{"a": "x", "b": "y", "hours": 10, "median_gap_pct": 9.0}]},
        "CCC": {"pairs": [{"a": "x", "b": "y", "hours": 50, "median_gap_pct": 0.5}]}}}
    rows = countries(doc)
    assert [r["ccy"] for r in rows] == ["AAA", "CCC"] and rows[0]["b"] == "z", rows           # BBB has too few hours, the widest pair counts
    assert bands(rows) == {"tight": 1, "middle": 0, "wide": 1}, bands(rows)
    print("source_pairs self-test ok")
