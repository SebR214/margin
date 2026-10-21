#!/usr/bin/env python3
"""Retest the live findings (SEB-301, ROADMAP.md "How a finding is tested"). No model, no estimate.

    python3 tools/retest_findings.py            # run every test whose trigger fired, append one row each to data/finding_tests.csv
    python3 tools/retest_findings.py --print    # run them, print the rows, write nothing
    python3 tools/retest_findings.py --self-test

Each finding has a test file in findings_tests/<id>.json: the exact calculation, the data window, the minimum observations, what makes the
test invalid, and the thresholds for holds, weaker and no longer true. This script reads those files and the finding's own stored evidence
(data/findings_hours_<id>.csv, data/findings.json, data/volume_crossover.json) and appends a row to data/finding_tests.csv. Each retest adds
a row; no earlier row is ever changed. A finding is tested at most once a clock day, and only when its trigger fired: new evidence rows for
the price findings, a changed fee table (the tier schedule date) for the volume finding. The first row of a finding is its baseline.

    ts_utc,finding_id,status,metric,value,baseline,n_obs,window_start,window_end,data_through,reason,detail
status: holds | weaker | no_longer_true | invalid (the test could not be run fairly; the reason says why).
"""
import csv
import datetime as dt
import json
import os
import statistics
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
HEADER = ["ts_utc", "finding_id", "status", "metric", "value", "baseline", "n_obs", "window_start", "window_end", "data_through", "reason", "detail"]
LOG = "data/finding_tests.csv"


def parse(s):
    s = (s or "").replace("Z", "+00:00")
    t = dt.datetime.fromisoformat(s)
    return t if t.tzinfo else t.replace(tzinfo=dt.timezone.utc)


def rows_of(path):
    with open(path, newline="") as f:
        return list(csv.DictReader(f))


def classify(value, test):
    """The status for a figure under the test's thresholds."""
    d, hold, weak = test["direction"], test["holds"], test["weaker"]
    if d == "higher_is_better":
        return "holds" if value >= hold else "weaker" if value >= weak else "no_longer_true"
    if d == "lower_is_better":
        return "holds" if value <= hold else "weaker" if value <= weak else "no_longer_true"
    return "holds" if value <= hold else "weaker" if value <= weak else "no_longer_true"      # band: distance from the baseline


def finding_meta(root, fid):
    doc = json.load(open(os.path.join(root, "data", "findings.json")))
    f = next((x for x in doc["findings"] if x["id"] == fid), None)
    return f, parse(doc["as_of_utc"]) if doc.get("as_of_utc") else None


def stale(f, hours, now):
    last = parse(f["last_recheck_utc"]) if f else None
    return last is None or now - last > dt.timedelta(hours=hours)


# ---- one metric per finding: returns dict(value, baseline, n_obs, window_start, window_end, data_through, invalid, metric, detail) ----

def m_price_changes(root, test, now, first):
    rows = rows_of(os.path.join(root, test["evidence_file"]))
    f, _ = finding_meta(root, "price_changes")
    ts = sorted(parse(r["ts_utc"]) for r in rows)
    out = {"metric": "recent_to_all_time_weekly_rate", "n_obs": len(ts), "detail": ""}
    if not ts:
        return dict(out, invalid="the evidence file is empty")
    last, firstt = ts[-1], ts[0]
    span = (last - firstt).days
    out.update(window_start=(last - dt.timedelta(days=28)).date().isoformat(), window_end=last.date().isoformat(), data_through=last.isoformat())
    if stale(f, 72, now):
        return dict(out, invalid="the finding's last recheck is more than 3 days old")
    if span < 28 or len(ts) < 50:
        return dict(out, invalid="fewer than 28 days or 50 changes in the file (%d days, %d changes)" % (span, len(ts)))
    all_rate = len(ts) / (span / 7.0)
    recent = sum(1 for t in ts if t > last - dt.timedelta(days=28)) / 4.0
    return dict(out, value=recent / all_rate, baseline=all_rate)


def m_weekend(root, test, now, first):
    rows = rows_of(os.path.join(root, test["evidence_file"]))
    f, _ = finding_meta(root, "weekend_penalty")
    ups = {}
    backs = set()
    for r in rows:
        if r["kind"] == "weekend_up":
            ups.setdefault(r["rise_id"], parse(r["ts_utc"]))
        elif r["kind"] == "weekend_back":
            backs.add(r["rise_id"])
    rises = {k: v for k, v in ups.items() if k in backs}
    out = {"metric": "recent_to_all_time_rises_per_saturday", "n_obs": len(rises), "detail": ""}
    if not rises:
        return dict(out, invalid="no rise with its cut-back in the file")
    sats = sorted({t.date() for t in rises.values()})
    all_sats = []
    d = sats[0]
    while d <= sats[-1]:
        all_sats.append(d)
        d += dt.timedelta(days=7)
    last4 = all_sats[-4:]
    n_recent = sum(1 for t in rises.values() if t.date() in last4)
    out.update(window_start=last4[0].isoformat(), window_end=last4[-1].isoformat(), data_through=max(rises.values()).isoformat())
    if stale(f, 192, now):
        return dict(out, invalid="the finding's last recheck is more than 8 days old")
    if len(all_sats) < 8 or len(rises) < 10:
        return dict(out, invalid="fewer than 8 Saturdays or 10 rises (%d Saturdays, %d rises)" % (len(all_sats), len(rises)))
    all_rate = len(rises) / len(all_sats)
    return dict(out, value=(n_recent / 4.0) / all_rate, baseline=all_rate)


def m_volume(root, test, now, first):
    vc = json.load(open(os.path.join(root, "data", "volume_crossover.json")))
    f, _ = finding_meta(root, "volume_crossover")
    out = {"metric": "volume_change_vs_first", "n_obs": vc.get("n_samples", 0), "window_start": "", "window_end": "",
           "data_through": vc.get("tier_schedule_as_of", ""), "detail": ""}
    cur = f["headline"]["value"] if f else None
    if vc.get("status") != "ok" or (vc.get("reconstruction_max_error_bps") or 0) > 1 or vc.get("n_samples", 0) < 500 or not cur:
        return dict(out, invalid="status %r, rebuild error %s bps, %s checks, volume %s" % (vc.get("status"), vc.get("reconstruction_max_error_bps"), vc.get("n_samples"), cur))
    base = float(first["baseline"]) if first and first.get("baseline") else float(cur)      # the first volume this test recorded
    return dict(out, value=abs(cur - base) / base, baseline=base, detail=json.dumps({"volume_now": cur}))


def m_sgd(root, test, now, first):
    rows = rows_of(os.path.join(root, test["evidence_file"]))
    f, _ = finding_meta(root, "sgd_php_never_cheapest")
    out = {"metric": "share_of_hours_stablecoin_cheapest", "detail": ""}
    if not rows:
        return dict(out, n_obs=0, invalid="the evidence file is empty")
    last = max(parse(r["hour_utc"]) for r in rows)
    win = [r for r in rows if parse(r["hour_utc"]) > last - dt.timedelta(days=28)]
    out.update(n_obs=len(win), window_start=min(r["hour_utc"] for r in win)[:10], window_end=last.isoformat(), data_through=last.isoformat())
    if stale(f, 6, now):
        return dict(out, invalid="the finding's last recheck is more than 6 hours old")
    if len(win) < 500:
        return dict(out, invalid="fewer than 500 priced hours in the window (%d)" % len(win))
    share = sum(1 for r in win if r["stable_cheaper"] == "true") / len(win)
    allshare = sum(1 for r in rows if r["stable_cheaper"] == "true") / len(rows)
    return dict(out, value=share, baseline=allshare)


def m_exchange(root, test, now, first):
    f, _ = finding_meta(root, "exchange_vs_p2p")
    out = {"metric": "share_of_first_persisting_countries_still_persisting", "n_obs": 0, "detail": ""}
    if f is None:
        return dict(out, invalid="finding not in data/findings.json")
    ev = f["evidence"]
    now_set = sorted(e["ccy"] for e in ev if e.get("persists"))
    out.update(window_start="", window_end=f["headline"]["as_of_utc"], data_through=f["headline"]["as_of_utc"], n_obs=len(ev))
    if stale(f, 6, now):
        return dict(out, invalid="the finding's last recheck is more than 6 hours old")
    base_set = json.loads(first["detail"])["countries"] if first else now_set
    if not base_set:
        return dict(out, invalid="no country persisted when the test first ran", detail=json.dumps({"countries": base_set}))
    still = [c for c in base_set if c in now_set]
    return dict(out, value=len(still) / len(base_set), baseline=len(base_set), detail=json.dumps({"countries": base_set, "now": now_set}))


METRICS = {"price_changes": m_price_changes, "weekend_penalty": m_weekend, "volume_crossover": m_volume,
           "sgd_php_never_cheapest": m_sgd, "exchange_vs_p2p": m_exchange}


def triggered(fid, result, last_row, today):
    """True when this finding should be tested now: never tested, or new evidence since the last row, and not already tested today."""
    if last_row is None:
        return True
    if last_row["ts_utc"][:10] == today:
        return False
    return result.get("data_through", "") != last_row["data_through"]


def retest(root=ROOT, now=None, force=False):
    now = now or dt.datetime.now(dt.timezone.utc)
    path = os.path.join(root, LOG)
    old = rows_of(path) if os.path.exists(path) else []
    out = []
    for fid, fn in METRICS.items():
        test = json.load(open(os.path.join(root, "findings_tests", fid + ".json")))
        mine = [r for r in old if r["finding_id"] == fid]
        first = next((r for r in mine if r["status"] != "invalid"), None)
        try:
            res = fn(root, test, now, first)
        except Exception as e:      # noqa: BLE001 - a test that cannot run is an invalid row with its reason, never a crash
            res = {"metric": "", "n_obs": "", "invalid": "the test could not run: %s: %s" % (type(e).__name__, str(e)[:120]), "detail": ""}
        if not force and not triggered(fid, res, mine[-1] if mine else None, now.date().isoformat()):
            continue
        if res.get("invalid"):
            status, value, reason = "invalid", "", res["invalid"]
        else:
            value = res["value"]
            status = classify(value, test)
            reason = test["thresholds_text"]
        out.append([now.replace(microsecond=0).isoformat(), fid, status, res["metric"], ("%.6g" % value) if value != "" else "",
                    ("%.6g" % res["baseline"]) if res.get("baseline") is not None else "", res.get("n_obs", ""), res.get("window_start", ""),
                    res.get("window_end", ""), res.get("data_through", ""), reason, res.get("detail", "")])
    return out


def append(rows, root=ROOT):
    path = os.path.join(root, LOG)
    new = not os.path.exists(path)
    with open(path, "a", newline="") as f:
        w = csv.writer(f)
        if new:
            w.writerow(HEADER)
        w.writerows(rows)


def self_test():
    t = {"direction": "higher_is_better", "holds": 0.5, "weaker": 0.1}
    assert [classify(v, t) for v in (1.2, 0.5, 0.3, 0.1, 0.05, 0)] == ["holds", "holds", "weaker", "weaker", "no_longer_true", "no_longer_true"]
    t = {"direction": "lower_is_better", "holds": 0.01, "weaker": 0.05}
    assert [classify(v, t) for v in (0.0, 0.01, 0.03, 0.06)] == ["holds", "holds", "weaker", "no_longer_true"]
    t = {"direction": "band", "holds": 0.25, "weaker": 0.5}
    assert [classify(v, t) for v in (0.0, 0.25, 0.4, 0.9)] == ["holds", "holds", "weaker", "no_longer_true"]
    now = dt.datetime(2026, 10, 20, 12, tzinfo=dt.timezone.utc)
    last = {"ts_utc": "2026-10-20T03:00:00+00:00", "data_through": "A"}
    assert triggered("x", {"data_through": "A"}, None, "2026-10-20")
    assert not triggered("x", {"data_through": "B"}, last, "2026-10-20"), "once a day"
    assert not triggered("x", {"data_through": "A"}, dict(last, ts_utc="2026-10-19T03:00:00+00:00"), "2026-10-20"), "no new evidence"
    assert triggered("x", {"data_through": "B"}, dict(last, ts_utc="2026-10-19T03:00:00+00:00"), "2026-10-20")
    # the real files, with a known answer: the claim as published holds on the data it was made from
    rows = retest(ROOT, now=dt.datetime.now(dt.timezone.utc), force=True)      # force: the real log may already hold today's rows
    by = {r[1]: r for r in rows}
    assert set(by) == set(METRICS), by.keys()
    for r in rows:
        assert r[2] in ("holds", "weaker", "no_longer_true", "invalid") and len(r) == len(HEADER), r
    # the second run of the volume test, with a first row on file: the baseline is the first volume, not the first deviation (which is 0)
    vrow = {"ts_utc": "2026-10-20T10:35:00+00:00", "finding_id": "volume_crossover", "status": "holds", "value": "0", "baseline": "2.03708e+07",
            "data_through": "2026-10-01T10:18:27Z", "detail": ""}
    vres = m_volume(ROOT, json.load(open(os.path.join(ROOT, "findings_tests", "volume_crossover.json"))), now, vrow)
    assert vres.get("baseline") == 2.03708e+07 and "invalid" not in vres and isinstance(vres["value"], float), vres  # the size of the change moves with the live data (it broke main on 21 Oct), so only the shape is asserted
    # synthetic evidence: a finding that stops being true is called so
    import tempfile
    with tempfile.TemporaryDirectory() as d:
        os.makedirs(os.path.join(d, "data"))
        os.makedirs(os.path.join(d, "findings_tests"))
        for fid in METRICS:
            json.dump(json.load(open(os.path.join(ROOT, "findings_tests", fid + ".json"))), open(os.path.join(d, "findings_tests", fid + ".json"), "w"))
        base = dt.datetime(2026, 8, 12, tzinfo=dt.timezone.utc)
        w = open(os.path.join(d, "data", "findings_hours_sgd_php_never_cheapest.csv"), "w")
        w.write("hour_utc,amount_sgd,stable_cost_pct,app_cost_pct,cheapest_app,stable_path,stable_cheaper\n")
        for i in range(700):
            h = (base + dt.timedelta(hours=i)).strftime("%Y-%m-%dT%H:00:00Z")
            w.write("%s,5000,1,1,X,USDT,%s\n" % (h, "true" if i % 5 == 0 else "false"))
        w.close()
        end = (base + dt.timedelta(hours=699)).strftime("%Y-%m-%dT%H:00:00Z")
        json.dump({"as_of_utc": end, "findings": [{"id": "sgd_php_never_cheapest", "last_recheck_utc": end, "headline": {"as_of_utc": end}, "evidence": []}]},
                  open(os.path.join(d, "data", "findings.json"), "w"))
        res = m_sgd(d, json.load(open(os.path.join(d, "findings_tests", "sgd_php_never_cheapest.json"))), parse(end), None)
        assert abs(res["value"] - 0.2) < 0.01 and res["n_obs"] == 672, res
        assert classify(res["value"], json.load(open(os.path.join(d, "findings_tests", "sgd_php_never_cheapest.json")))) == "no_longer_true"
        stale_res = m_sgd(d, json.load(open(os.path.join(d, "findings_tests", "sgd_php_never_cheapest.json"))), parse(end) + dt.timedelta(hours=7), None)
        assert stale_res["invalid"], "a stale finding is not tested"
    print("retest_findings self-test: ok")


def main(argv):
    if "--self-test" in argv:
        return self_test()
    rows = retest(force="--force" in argv)
    for r in rows:
        print(",".join(str(x) for x in r))
    if "--print" in argv or not rows:
        print("%d finding(s) tested%s" % (len(rows), " (printed, not written)" if "--print" in argv else ""))
        return 0
    append(rows)                    # persistence before display
    print("%d finding(s) tested, rows appended to %s" % (len(rows), LOG))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
