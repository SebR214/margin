#!/usr/bin/env python3
"""data/sources_daily.json: every source the record has read from, with a status for every
day since the first reading and what exists of its history before that.

Schema
    {
      "as_of_utc":  newest stored reading timestamp,
      "first_day":  "2026-08-10", "last_day": day of as_of_utc,
      "days":       [every calendar day, first_day..last_day],
      "definition": the status rule in words,
      "sources": [
        {"id":          the name as stored (venue, source column, or the feed's endpoint),
         "kind":        "p2p" | "order_book" | "broker" | "fx" | "provider_quote" | "other",
         "live":        true if any reading is stored, false for a history-only series,
         "currencies":  currency codes the readings carry (empty where the file has none),
         "routes":      corridors the readings carry (empty where the file has none),
         "files":       the data files its readings are in,
         "first_utc":   first stored successful reading, null if none,
         "last_answered_utc": newest stored successful reading, null if none,
         "cadence_hours": its own expected cadence, from its stored rows (median gap between
                          the hours it answered, at least 1),
         "hours_answered", "hours_expected": over the whole record, same rule as the daily status,
         "status":      one status per entry of `days` (see definition),
         "history":     null, or [{"series", "ccy", "interval", "first", "last", "rows"}] from the
                        backfill manifest (reported, not observed),
         "history_reason": null, or the reason no history exists, copied from METHODOLOGY.md,
         "history_verdict": null, or the probe verdict beside it (METHODOLOGY.md probe table),
         "history_endpoint": null, or the endpoint that probe row names,
         "history_reason_kind": null | snapshot_only | needs_key | blocked | login_only | no_endpoint | other}
      ]
    }
Statuses: not_yet_a_source (the day is before the source's first successful reading, or it has
no stored reading), answered_every_hour, missed_some, missed_all.

The manifest is read for first dates, row counts and intervals only, so this tool is listed in
tools/check_history_isolation.py next to tools/emit_country_history.py. Stored files only; no
wall clock; stdlib only.

Usage: python3 tools/emit_sources_daily.py [--self-test]
"""

import json
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import record_common as rc  # noqa: E402

OUT = os.path.join(rc.DATA, "sources_daily.json")
MANIFEST = os.path.join(rc.DATA, "history", "manifest.json")
METHODOLOGY = os.path.join(rc.HERE, "METHODOLOGY.md")

DEFINITION = (
    "Each source's cadence is the median gap, in whole hours (at least 1), between the hours it "
    "answered in the stored rows; every source here is hourly. A day's expected hours are the hours "
    "of that day in which the collector stored any reading at all, from the source's first answer "
    "on, so a day the collector did not run does not count against a source. answered_every_hour: "
    "the source has a successful row in every expected hour (for a cadence above 1 hour, in at "
    "least one expected hour per cadence). missed_all: expected hours and none answered, or no hour "
    "collected that day. missed_some: anything between. not_yet_a_source: before its first "
    "successful reading, or no live reading stored."
)



def reason_kind(reason, verdict):
    """A small fixed set of kinds for the stored reason, so a page can say it in plain words
    without printing HTTP codes, endpoints or file names. None when no reason is stored."""
    if not reason:
        return None
    t = ((reason or "") + " " + (verdict or "")).lower()
    if "snapshot-only" in t:
        return "snapshot_only"
    if "api key" in t or "401" in t:
        return "needs_key"
    if "bot challenge" in t or "403" in t:
        return "blocked"
    if "login" in t or "sign-in" in t or "never scraped" in t:
        return "login_only"
    if "no history endpoint" in t or "no candle" in t or "candles 404" in t or "404" in t:
        return "no_endpoint"
    return "other"

def _manifest():
    return json.load(open(MANIFEST))["files"]


def _probe_rows():
    """METHODOLOGY.md probe verdict table -> [(candidate, result, verdict)]."""
    out, on = [], False
    for line in open(METHODOLOGY, encoding="utf-8"):
        if line.startswith("**Probe verdicts"):
            on = True
            continue
        if on and line.startswith("|"):
            cells = [c.strip().strip("`") for c in line.strip().strip("|").split("|")]
            if len(cells) == 4 and cells[0] not in ("Candidate",) and not set(cells[0]) <= {"-"}:
                out.append((cells[0], cells[2], cells[3], cells[1]))
        elif on and out and not line.startswith("|"):
            break
    return out


def _sentence(needle):
    text = re.sub(r"\s+", " ", open(METHODOLOGY, encoding="utf-8").read()).replace("**", "")
    for s in re.split(r"(?<=[.!?]) (?=[A-Z])", text):
        if needle in s:
            return s.strip()
    return None


def _norm(s):
    return re.sub(r"[^a-z0-9]", "", re.sub(r"\(.*?\)", "", s.lower()))


def build():
    rows = rc.readings()
    reg = rc.Registry(rows)
    ok_rows = [r for r in rows if r["ok"]]
    as_of = ok_rows[-1]["ts"]
    days = rc.day_range(rc.START_DAY, rc.day_of(as_of))
    hours_by_day = {}
    for h in sorted(reg.all_hours):
        hours_by_day.setdefault(h[:10], []).append(h)
    man = _manifest()
    probes = _probe_rows()
    criptoya_reason = _sentence("CriptoYa exposes no candle history")
    p2p_reason = _sentence("Binance P2P has no history endpoint")
    # manifest series by venue name ("BTC Markets_1d" -> "BTC Markets")
    series = {}
    for key, v in man.items():
        if "ccy" in v:
            name, _, interval = key.rpartition("_")
            series.setdefault(name, []).append({"series": key, "ccy": v["ccy"], "interval": interval,
                                                "first": v["first"], "last": v["last"], "rows": v["rows"]})
    out = []
    for sid in sorted(reg.sources, key=lambda s: (reg.sources[s]["kind"], s.lower())):
        s = reg.sources[sid]
        k = s["cadence_hours"]
        first_h, first_d = rc.hour_of(s["first_ts"]), rc.day_of(s["first_ts"])
        status, h_ans, h_exp = [], 0, 0
        for d in days:
            if d < first_d:
                status.append("not_yet_a_source")
                continue
            exp = [h for h in hours_by_day.get(d, []) if h >= first_h]
            ans = [h for h in exp if h in s["ok_hours"]]
            need = len(exp) if k == 1 else max(1, round(len(exp) / k))
            h_ans += len(ans)
            h_exp += len(exp)
            if not exp or not ans:
                status.append("missed_all")
            elif len(ans) >= need:
                status.append("answered_every_hour")
            else:
                status.append("missed_some")
        hist, reason, verdict, endpoint = None, None, None, None
        if sid in series:
            hist = sorted(series[sid], key=lambda x: x["interval"])
        else:
            base = _norm(sid)
            probe = next((p for p in probes if _norm(p[0]).startswith(base) and base), None)
            if probe:
                reason, verdict, endpoint = probe[1], probe[2], probe[3]
            elif sid.startswith(rc.CRIPTOYA_PREFIX):
                reason = criptoya_reason
            elif sid == "binance_p2p":
                reason = p2p_reason
        out.append({
            "history_reason_kind": reason_kind(reason, verdict),
            "id": sid, "kind": s["kind"], "live": True, "currencies": sorted(s["ccys"]),
            "routes": sorted(s["routes"]), "files": sorted(s["files"]),
            "first_utc": rc.iso_z(s["first_ts"]), "last_answered_utc": rc.iso_z(s["last_ts"]),
            "cadence_hours": k, "hours_answered": h_ans, "hours_expected": h_exp,
            "status": status, "history": hist, "history_reason": reason, "history_verdict": verdict,
            "history_endpoint": endpoint,
        })
    # history-only series: official rates and the Argentine parallel dollar are backfilled from
    # public endpoints that are not read by the hourly collector
    for key, v in sorted(man.items()):
        if "ccy" in v:
            continue
        sid = v["source"].split(" ")[0].split("/")[0]
        out.append({
            "id": sid, "kind": "fx", "live": False, "currencies": sorted(v["ccys"].split(",")) if v.get("ccys") else [],
            "routes": [], "files": [], "first_utc": None, "last_answered_utc": None, "cadence_hours": None,
            "hours_answered": 0, "hours_expected": 0, "status": ["not_yet_a_source"] * len(days),
            "history": [{"series": key, "ccy": v.get("ccys"), "interval": "1d", "first": v["first"],
                         "last": v["last"], "rows": v["rows"]}],
            "history_reason": None, "history_verdict": None, "history_endpoint": None,
        })
    return {"as_of_utc": rc.iso_z(as_of), "first_day": days[0], "last_day": days[-1], "days": days,
            "definition": DEFINITION, "sources": out}


def self_test(doc):
    rc.assert_no_nan(doc)
    n = len(doc["days"])
    assert doc["days"][0] == rc.START_DAY and doc["days"] == rc.day_range(doc["first_day"], doc["last_day"])
    ids = [s["id"] for s in doc["sources"]]
    assert len(ids) == len(set(ids)), "source ids unique"
    ok = {"not_yet_a_source", "answered_every_hour", "missed_some", "missed_all"}
    for s in doc["sources"]:
        assert len(s["status"]) == n and set(s["status"]) <= ok, s["id"]
        if s["live"]:
            # once a source exists it never goes back to not_yet_a_source
            seen = False
            for st in s["status"]:
                seen = seen or st != "not_yet_a_source"
                assert not (seen and st == "not_yet_a_source"), s["id"]
            assert s["first_utc"] <= s["last_answered_utc"]
            assert s["hours_answered"] <= s["hours_expected"]
        assert s["kind"] in ("p2p", "order_book", "broker", "fx", "provider_quote", "other")
        assert s["history"] is None or s["history"], s["id"]
        assert not (s["history"] and s["history_reason"]), "reason only where no series"
    assert {"Binance P2P".lower().replace(" ", "_")} <= {i for i in ids}, "binance_p2p present"
    print("sources_daily self-test ok: %d sources x %d days" % (len(ids), n))


def main():
    doc = build()
    self_test(doc)
    if "--self-test" in sys.argv:
        return
    rc.write_json(OUT, doc)


if __name__ == "__main__":
    main()
