#!/usr/bin/env python3
"""The data-gap report the researcher reads (SEB-301, 25 Oct). Plain code, no model, no network.

Computed from files already on main, so the researcher never has to guess where the data is thin:

- no_price: countries the index lists with no price this hour, and why (data/index_latest.json)
- one_source: markets priced from one source (data/source_pairs.json)
- disagree: source pairs in one market whose median gap is at or over the lasting-gap line (data/source_pairs.json)
- stale_findings: findings with no retest row in the last 8 days, or none at all (data/findings.json, data/finding_tests.csv)
- quarantine_due: sources still in quarantine past their 7 days (data/source_registry.json)

    python3 tools/gap_report.py              # write data/gap_report.json and print a summary
    python3 tools/gap_report.py --print      # print only
    python3 tools/gap_report.py --self-test
"""
import csv
import datetime
import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(ROOT, "data", "gap_report.json")
STALE = datetime.timedelta(days=8)


def load(rel):
    with open(os.path.join(ROOT, rel)) as f:
        return json.load(f)


def no_price(index):
    by = {w.get("ccy"): w for w in index.get("withheld") or []}
    return [{"ccy": c, "country": (by.get(c) or {}).get("country", ""), "reason": (by.get(c) or {}).get("reason", "")}
            for c in index.get("without_value") or []]


def one_source(pairs):
    out = []
    for ccy, m in sorted((pairs.get("markets") or {}).items()):
        if m.get("one_source"):
            out.append({"ccy": ccy, "sources_behind_price": m.get("sources_behind_price"), "sources_seen": m.get("sources_seen")})
    return out


def disagree(pairs):
    line = float(pairs.get("gap_pct") or 2.0)
    out = []
    for ccy, m in sorted((pairs.get("markets") or {}).items()):
        for p in m.get("pairs") or []:
            g = p.get("median_gap_pct")
            if g is not None and (p.get("flag") or float(g) >= line):
                out.append({"ccy": ccy, "a": p["a"], "b": p["b"], "median_gap_pct": g, "hours": p.get("hours"),
                            "share_over_gap": p.get("share_over_gap"), "flag": bool(p.get("flag"))})
    out.sort(key=lambda r: -float(r["median_gap_pct"]))
    return out


def ts(s):
    return datetime.datetime.fromisoformat(s.replace("Z", "+00:00"))


def stale_findings(findings, test_rows, now):
    last = {}
    for r in test_rows:
        last[r["finding_id"]] = max(last.get(r["finding_id"], ""), r["ts_utc"])
    out = []
    for f in findings.get("findings") or []:
        fid = f.get("id")
        t = last.get(fid)
        if not t:
            out.append({"id": fid, "last_retest": None})
        elif now - ts(t) > STALE:
            out.append({"id": fid, "last_retest": t[:10]})
    return out


def quarantine_due(reg, today):
    days = int(reg.get("quarantine_days") or 7)
    out = []
    for name, s in sorted((reg.get("sources") or {}).items()):
        if s.get("status") == "quarantine" and s.get("first_row"):
            age = (today - datetime.date.fromisoformat(s["first_row"])).days
            if age > days:
                out.append({"source": name, "first_row": s["first_row"], "days": age})
    return out


def build(now=None):
    now = now or datetime.datetime.now(datetime.timezone.utc)
    pairs = load("data/source_pairs.json")
    with open(os.path.join(ROOT, "data", "finding_tests.csv"), newline="") as f:
        tests = list(csv.DictReader(f))
    return {
        "computed_at": now.isoformat(timespec="seconds"),
        "source_files": ["data/index_latest.json", "data/source_pairs.json", "data/findings.json", "data/finding_tests.csv",
                         "data/source_registry.json"],
        "no_price": no_price(load("data/index_latest.json")),
        "one_source": one_source(pairs),
        "disagree": disagree(pairs),
        "stale_findings": stale_findings(load("data/findings.json"), tests, now),
        "quarantine_due": quarantine_due(load("data/source_registry.json"), now.date()),
    }


def summary(r):
    return "gap report: %d without a price, %d one source, %d disagreeing pairs, %d stale findings, %d past quarantine" % (
        len(r["no_price"]), len(r["one_source"]), len(r["disagree"]), len(r["stale_findings"]), len(r["quarantine_due"]))


def self_test():
    idx = {"without_value": ["AFN", "ZAR"], "withheld": [{"ccy": "AFN", "country": "Afghanistan", "reason": "too few"}]}
    assert no_price(idx) == [{"ccy": "AFN", "country": "Afghanistan", "reason": "too few"}, {"ccy": "ZAR", "country": "", "reason": ""}]
    sp = {"gap_pct": 2.0, "markets": {
        "NGN": {"one_source": False, "pairs": [{"a": "x", "b": "y", "median_gap_pct": 4.1, "flag": True, "hours": 90}]},
        "THB": {"one_source": True, "sources_seen": ["z"], "pairs": [{"a": "z", "b": "w", "median_gap_pct": 0.3, "flag": False}]},
        "INR": {"one_source": False, "pairs": [{"a": "p", "b": "q", "median_gap_pct": 2.0, "flag": False}]}}}
    assert [m["ccy"] for m in one_source(sp)] == ["THB"]
    assert [(d["ccy"], d["median_gap_pct"]) for d in disagree(sp)] == [("NGN", 4.1), ("INR", 2.0)], "a gap on the line counts"
    now = datetime.datetime(2026, 10, 25, tzinfo=datetime.timezone.utc)
    fs = {"findings": [{"id": "a"}, {"id": "b"}, {"id": "c"}]}
    rows = [{"finding_id": "a", "ts_utc": "2026-10-24T00:00:00+00:00"}, {"finding_id": "b", "ts_utc": "2026-10-10T00:00:00+00:00"}]
    assert stale_findings(fs, rows, now) == [{"id": "b", "last_retest": "2026-10-10"}, {"id": "c", "last_retest": None}]
    reg = {"quarantine_days": 7, "sources": {"old": {"status": "quarantine", "first_row": "2026-10-10"},
                                             "new": {"status": "quarantine", "first_row": "2026-10-23"},
                                             "ok": {"status": "approved", "first_row": "2026-08-01"}}}
    assert [q["source"] for q in quarantine_due(reg, now.date())] == ["old"]
    r = build(now)
    assert set(r) >= {"no_price", "one_source", "disagree", "stale_findings", "quarantine_due"}, "the real files did not read"
    print("gap_report self-test: ok (%s)" % summary(r))


def main(argv):
    if "--self-test" in argv:
        self_test()
        return 0
    r = build()
    print(summary(r))
    if "--print" in argv:
        print(json.dumps(r, indent=1)[:4000])
        return 0
    with open(OUT, "w") as f:
        json.dump(r, f, indent=1)
        f.write("\n")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
