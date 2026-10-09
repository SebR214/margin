#!/usr/bin/env python3
"""data/findings.json: the findings the site publishes, each backed by stored files, with
a headline number computed here from those files, and data/findings_hours_<id>.csv, the
rows underneath it, for download.

NO PROSE. Every field is an id, a number, a date or a file name; the writer fills any text
later, keyed by finding id (the copy lock allows no new words from code).

Schema
    {
      "as_of_utc": newest last_recheck_utc of any finding,
      "findings": [
        {"id":              stable slug,
         "source_files":    stored data files the number is computed from,
         "method_files":    the tools that produce those files and this one,
         "headline":        {"value": number, "unit": identifier, "as_of_utc": ...},
         "evidence":        rows of numbers, one per route or country (keys differ by finding),
         "last_recheck_utc": newest stored timestamp among its inputs,
         "published_in":    html/js files that fetch a backing file (found by scanning the site),
         "published":       published_in is not empty,
         "hours_file":      "data/findings_hours_<id>.csv", or null when over 1 MB,
         "hours_rows":      rows in it (null when no file),
         "download_file":   the file to offer for download: hours_file, else the stored data file}
      ]
    }
Findings and what backs them:
    price_changes      data/price_changes.csv, data/price_changes_latest.json
                       value = days on which a provider's cost changed (kind "change")
    weekend_penalty    the same files; value = weekend increases (kind "weekend_up"),
                       evidence per route also has weekend_back and Saturdays judged
    volume_crossover   data/volume_crossover.json, data/samples.csv, data/crossover_receipts/
                       value = monthly SGD volume at which the stablecoin route's cost
                       crosses the cheapest provider's (taker)
    sgd_php_never_cheapest  data/routes_hourly.json, data/routes_summary.json
                       value = hours the stablecoin path was cheapest on SGD to PHP (0); evidence per amount
    stress_signal      data/stress_signal.csv, data/stress_signal_latest.json
                       value = triggers on record; evidence per country
    p2p_spread_signal  data/p2p_spread_signal.csv, data/p2p_spread_signal_latest.json
                       value = widest buy-sell spread against the currency's own average
Reads stored files only; idempotent; stdlib only; no wall clock.

Usage: python3 tools/emit_findings.py [--self-test]
"""

import csv
import datetime as dt
import glob
import json
import os
import re
import statistics
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import record_common as rc  # noqa: E402

DATA, HERE = rc.DATA, rc.HERE
OUT = os.path.join(DATA, "findings.json")
MAX_HOURS_BYTES = 1_000_000


def _json(name):
    return json.load(open(os.path.join(DATA, name), encoding="utf-8"))


def _num(v):
    try:
        x = float(v)
    except (TypeError, ValueError):
        return None
    return x if x == x else None


def _z(ts):
    return rc.iso_z(ts) if "T" in ts else ts + "T00:00:00Z"


def _published_in(source_files):
    """Site files (root html, js/ and root js) that name a backing file. Directories match on prefix."""
    names = [s.rstrip("/").split("/")[-1] for s in source_files]
    hits = []
    for p in sorted(glob.glob(os.path.join(HERE, "*.html")) + glob.glob(os.path.join(HERE, "js", "*.js"))
                    + glob.glob(os.path.join(HERE, "*.js"))):
        text = open(p, encoding="utf-8", errors="replace").read()
        if any(n in text for n in names):
            hits.append(os.path.relpath(p, HERE))
    return hits


PENDING = {}  # path -> text to write, or None to remove; applied by main() only, never by --self-test


def _hours_csv(fid, header, rows):
    """Queue data/findings_hours_<id>.csv unless it would be over 1 MB. Returns (path or None, row count or None)."""
    path = os.path.join(DATA, "findings_hours_%s.csv" % fid)
    rel = "data/findings_hours_%s.csv" % fid
    lines = [",".join(header)]
    for r in rows:
        lines.append(",".join("" if v is None else str(v) for v in r))
    body = "\n".join(lines) + "\n"
    if len(body.encode()) > MAX_HOURS_BYTES:
        PENDING[path] = None
        return None, None
    PENDING[path] = body
    return rel, len(rows)


def _finding(fid, source_files, method_files, headline, evidence, last, hours, fallback_download, shown=None):
    for m in method_files:
        assert os.path.exists(os.path.join(HERE, m)), "missing method file " + m
    for s in source_files:
        assert os.path.exists(os.path.join(HERE, s)), "missing source file " + s
    pub = _published_in(shown or source_files)
    hours_file, n = hours if hours else (None, None)
    return {"id": fid, "source_files": source_files, "method_files": method_files, "headline": headline,
            "evidence": evidence, "last_recheck_utc": last, "published_in": pub, "published": bool(pub),
            "hours_file": hours_file, "hours_rows": n, "download_file": hours_file or fallback_download}


def _panel_newest(files):
    """Newest ts_utc (as ...Z) in the hourly CSVs a daily judgment reads (the price panels, fx_rates.csv).
    Appended in time order, so the last row is the newest; stored files only, no wall clock."""
    best = ""
    for rel in files:
        with open(os.path.join(HERE, rel), encoding="utf-8") as f:
            last = ""
            for line in f:
                if line.strip():
                    last = line
        ts = last.split(",", 1)[0]
        if ts and ts != "ts_utc":
            best = max(best, rc.iso_z(ts))
    return best


def _pair_weekends(rows):
    """Work the weekend labels out from the stored rows, every time the findings are built.

    data/price_changes.csv is append-only: a Saturday rise is written as "change" because its Monday
    cut does not exist yet, and the cut is written later as "weekend_back". The rise row is never
    rewritten, so the stored labels leave most rises unpaired. Pairing here uses the same rule
    (tools/emit_price_changes.py label_weekends) on the stored rows and leaves the file as it is."""
    import emit_price_changes as epc
    ev = []
    for r in rows:
        e = dict(r)
        e["new_day"] = r["ts_utc"][:10]
        e["move_pct"] = float(r["move_pct"])
        ev.append(e)
    epc.label_weekends(ev)
    return [dict(r, kind=e["kind"]) for r, e in zip(rows, ev)]


def price_changes_findings():
    rows = _pair_weekends(rc.read_csv("price_changes.csv"))
    latest = _json("price_changes_latest.json")
    as_of = _z(latest["computed_at"])
    routes = sorted({r["corridor"] for r in rows})
    src = ["data/price_changes.csv", "data/price_changes_latest.json"]
    meth = ["tools/emit_price_changes.py", "tools/emit_pricechange_receipts.py", "tools/emit_findings.py"]
    # SEB-279: the recheck time is the newest hourly reading the judgment was made against, not
    # the newest change row or the judged day. Only complete days are judged and changes are rare,
    # so those stamps sit at midnight of a past day and made findings 01 and 02 look unchecked.
    last = max(_z(max(r["ts_utc"] for r in rows)), as_of, _panel_newest(latest.get("source_file") or []))
    hdr = ["ts_utc", "corridor", "size", "provider", "old_cost_pct", "new_cost_pct", "move_pct", "kind"]

    def sel(kinds):
        return [[r[c] for c in hdr] for r in rows if r["kind"] in kinds]

    ch = [r for r in rows if r["kind"] == "change"]
    ev_c = []
    for rt in routes:
        x = [r for r in ch if r["corridor"] == rt]
        days = sorted(r["ts_utc"][:10] for r in x)
        ev_c.append({"route": rt, "changes": len(x), "up": sum(1 for r in x if _num(r["move_pct"]) > 0),
                     "down": sum(1 for r in x if _num(r["move_pct"]) < 0),
                     "providers": len({r["provider"] for r in x}),
                     "first_day": days[0] if days else None, "last_day": days[-1] if days else None})
    f1 = _finding("price_changes", src, meth, {"value": len(ch), "unit": "price_changes", "as_of_utc": as_of},
                  ev_c, last, _hours_csv("price_changes", hdr, sel({"change"})), "data/price_changes.csv", src)
    sat = latest["saturdays_judged"]
    wk = [r for r in rows if r["kind"] in ("weekend_up", "weekend_back")]
    ev_w = []
    for rt in routes:
        ev_w.append({"route": rt, "weekend_up": sum(1 for r in wk if r["corridor"] == rt and r["kind"] == "weekend_up"),
                     "weekend_back": sum(1 for r in wk if r["corridor"] == rt and r["kind"] == "weekend_back"),
                     "saturdays_judged": sat.get(rt)})
    f2 = _finding("weekend_penalty", src, meth,
                  {"value": sum(e["weekend_up"] for e in ev_w), "unit": "weekend_increases", "as_of_utc": as_of},
                  ev_w, last, _hours_csv("weekend_penalty", hdr, sel({"weekend_up", "weekend_back"})),
                  "data/price_changes.csv", src)
    return [f1, f2]


def volume_crossover_finding():
    v = _json("volume_crossover.json")
    src = ["data/volume_crossover.json", "data/samples.csv", "data/fee_tier_schedule.csv", "data/fx_rates.csv"]
    stamps = [v["tier_schedule_as_of"]]
    for p in sorted(glob.glob(os.path.join(DATA, "crossover_receipts", "*.json"))):
        stamps.append(json.load(open(p))["evidence"]["last_ts"])
    last = max(rc.iso_z(s) if "T" in s else s for s in stamps)
    ev = []
    for side in ("taker", "maker"):
        s = v[side]
        ev.append({"route": v["corridor"], "side": side, "monthly_volume_sgd": s["monthly_volume_sgd"],
                   "monthly_volume_aud_on_ir": s["monthly_volume_aud_on_ir"],
                   "cost_bps_at_floor": s["cost_bps_at_floor"], "cost_bps_at_ceiling": s["cost_bps_at_ceiling"],
                   "fee_pct_at_crossover_ir": s["fee_pct_at_crossover_ir"],
                   "baseline_cost_bps_median": v["baseline_cost_bps_median"], "n_samples": v["n_samples"],
                   "rung_sgd": v["rung_sgd"]})
    hdr = ["ts", "corridor", "notional_src", "cost_bps_taker", "cost_bps_maker", "baseline_cost_bps"]
    hrs = [[r[c] for c in hdr] for r in rc.read_csv("samples.csv")
           if r["corridor"] == v["corridor"] and _num(r["notional_src"]) == v["rung_sgd"]
           and (r.get("source_ok") or "").strip().lower() != "false" and r["cost_bps_taker"] != ""]
    meth = ["tools/emit_volume_crossover.py", "tools/emit_crossover_receipts.py", "tools/emit_findings.py"]
    return _finding("volume_crossover", src + ["data/crossover_receipts/"], meth,
                    {"value": v["taker"]["monthly_volume_sgd"], "unit": "sgd_per_month", "as_of_utc": last},
                    ev, last, _hours_csv("volume_crossover", hdr, hrs), "data/samples.csv",
                    ["data/volume_crossover.json", "data/crossover_receipts/"])


def stress_finding():
    s = _json("stress_signal_latest.json")
    rows = rc.read_csv("stress_signal.csv")
    ev = []
    for ccy in sorted({r["ccy"] for r in rows}):
        x = [r for r in rows if r["ccy"] == ccy]
        ev.append({"ccy": ccy, "triggers": len(x),
                   "max_gap_widened_pt": max(_num(r["gap_widened_pt"]) for r in x),
                   "latest_index_pct": _num(sorted(x, key=lambda r: r["ts_utc"])[-1]["index_pct"]),
                   "last_triggered_on": max(r["triggered_on"] for r in x)})
    as_of = _z(s["as_of"])
    hdr = ["ts_utc", "ccy", "index_pct", "gap_widened_pt", "official_move_pct", "triggered_on"]
    return _finding("stress_signal", ["data/stress_signal.csv", "data/stress_signal_latest.json"],
                    ["tools/emit_stress_signal.py", "tools/emit_findings.py"],
                    {"value": len(rows), "unit": "triggers", "as_of_utc": as_of}, ev,
                    max(as_of, _panel_newest(["data/fx_rates.csv"])),  # SEB-279: newest reading judged against
                    _hours_csv("stress_signal", hdr, [[r[c] for c in hdr] for r in rows]),
                    "data/stress_signal.csv")


def spread_finding():
    s = _json("p2p_spread_signal_latest.json")
    ranked = [r for r in s["latest"] if r.get("spread_ratio") is not None]
    ranked.sort(key=lambda r: (-r["spread_ratio"], r["ccy"]))
    as_of = rc.iso_z(max(r["ts_utc"] for r in s["latest"]))
    ev = [{"ccy": r["ccy"], "spread_pct": r["spread_pct"], "ccy_mean_spread_pct": r["ccy_mean_spread_pct"],
           "spread_ratio": r["spread_ratio"], "n_prior_readings": r["n_prior_readings"]} for r in ranked]
    # the stored file is over 1 MB, so _hours_csv declines and the stored file is the download
    hdr = ["ts_utc", "ccy", "spread_pct", "ccy_mean_spread_pct", "spread_ratio", "n_prior_readings"]
    hours = _hours_csv("p2p_spread_signal", hdr, [[r[c] for c in hdr] for r in rc.read_csv("p2p_spread_signal.csv")])
    return _finding("p2p_spread_signal", ["data/p2p_spread_signal.csv", "data/p2p_spread_signal_latest.json"],
                    ["tools/emit_spread_signal.py", "tools/emit_findings.py"],
                    {"value": ranked[0]["spread_ratio"], "unit": "x_own_average_spread", "as_of_utc": as_of},
                    ev, as_of, hours, "data/p2p_spread_signal.csv")


def sgd_php_finding():
    """Singapore to the Philippines: the stablecoin path was cheaper than the cheapest app in 0 of the
    priced hours. The same figure the home page and the routes page print (data/routes_summary.json
    hours_priced_any_amount and total_hours_stable_cheapest), re-derived by tools/audit_claims.py."""
    summ = _json("routes_summary.json")
    r = next(x for x in summ["routes"] if x["id"] == "SGD->PHP")
    hourly = _json("routes_hourly.json")
    cols = hourly["hour_columns"]
    ci = {c: i for i, c in enumerate(cols)}
    route = next(x for x in hourly["routes"] if x["id"] == "SGD->PHP")
    ev, last = [], ""
    for a in route["amounts"]:
        hs = a["hours"]
        ev.append({"route": "SGD->PHP", "amount": a["amount"], "hours_priced": len(hs),
                   "hours_stablecoin_cheapest": sum(1 for h in hs if h[ci["stable_cheaper"]])})
        if hs:
            last = max(last, max(h[ci["hour_utc"]] for h in hs))
    amt = summ["routes"][0].get("default_amount") or 5000
    rows = next(a["hours"] for a in route["amounts"] if a["amount"] == amt)
    hdr = ["hour_utc", "amount_sgd", "stable_cost_pct", "app_cost_pct", "cheapest_app", "stable_path", "stable_cheaper"]
    hrs = [[h[ci["hour_utc"]], amt, h[ci["stable_cost_pct"]], h[ci["app_cost_pct"]], h[ci["cheapest_app"]],
            h[ci["stable_path"]], str(bool(h[ci["stable_cheaper"]])).lower()] for h in rows]
    meth = ["tools/emit_routes.py", "tools/audit_claims.py", "tools/emit_findings.py"]
    return _finding("sgd_php_never_cheapest",
                    ["data/routes_hourly.json", "data/routes_summary.json", "data/samples.csv", "data/provider_quotes.csv"],
                    meth,
                    {"value": r["total_hours_stable_cheapest"], "unit": "hours_stablecoin_cheapest", "as_of_utc": last},
                    ev, last, _hours_csv("sgd_php_never_cheapest", hdr, hrs), "data/routes_hourly.json",
                    ["data/routes_hourly.json", "data/routes_summary.json"])



EXCH_GAP_PTS = 2.0          # a gap of this many points or more counts as a disagreement
EXCH_PERSIST_DAYS = 7       # days with checked hours, in the last 30
EXCH_PERSIST_SHARE = 0.75   # share of checked hours with a disagreement
EXCH_WINDOW_DAYS = 30
EXCH_FAMILIES = ("order_book_median", "order_book_single", "broker_median", "broker_single")


def exchange_vs_p2p_hours():
    """One entry per country and hour in which the published number came from order books or brokers and at least one
    person-to-person board had 10 or more buy ads. gap = the board's premium over the official rate minus the number
    that hour published (data/index_hourly.csv, never recomputed). Two boards answering: the middle of the two prices."""
    import emit_countries as ec
    pub = {}
    for r in ec.rows(os.path.join(DATA, "index_hourly.csv")):
        if r["source_class"] in EXCH_FAMILIES:
            pub[(r["ccy"], r["hour_utc"][:13])] = (r["source_class"], float(r["index_pct"]))
    sides = ec.buy_side_counts()
    board = {}      # (ccy, hour) -> {"binance": (price, fx), "okx": (price, fx)}

    def hour_of(ts):
        t = ec.parse_ts(ts)
        return t.replace(minute=0, second=0, microsecond=0) if t else None
    for r in ec.rows(ec.P2P):
        t = hour_of(r.get("ts_utc"))
        price, fx = ec.num(r, "buy_median"), ec.num(r, "fx_mid_per_usd")
        if t is None or not r.get("ccy") or not ec.flag(r, "source_ok") or not price or not fx:
            continue
        n_buy = sides.get((r["ccy"], t))
        if n_buy is None:
            n_buy = ec.MIN_BUY_ADS if (ec.num(r, "n_ads") or 0) >= ec.MIN_BUY_ADS * 2 else 0
        if n_buy >= ec.MIN_BUY_ADS:
            board.setdefault((r["ccy"], t), {})["binance"] = (price, fx)
    for r in ec.rows(ec.P2P_OKX):
        t = hour_of(r.get("ts_utc"))
        price, fx = ec.num(r, "buy_median"), ec.num(r, "fx_mid_per_usd")
        if t is None or not r.get("ccy") or not ec.flag(r, "source_ok") or not price or not fx:
            continue
        if (ec.num(r, "n_ads") or 0) >= ec.MIN_BUY_ADS:
            board.setdefault((r["ccy"], t), {})["okx"] = (price, fx)
    out = []
    for (ccy, t), b in sorted(board.items(), key=lambda kv: (kv[0][1], kv[0][0])):
        key = (ccy, t.strftime("%Y-%m-%dT%H"))
        if key not in pub:
            continue
        prices = [v[0] for v in b.values()]
        fx = (b.get("binance") or b.get("okx"))[1]
        premium = (statistics.median(prices) / fx - 1) * 100
        out.append({"hour": t.strftime("%Y-%m-%dT%H:00:00Z"), "ccy": ccy, "published": pub[key][1], "board": premium,
                    "gap": premium - pub[key][1], "boards": sorted(b), "class": pub[key][0]})
    return out


def exchange_vs_p2p_finding():
    hrs = exchange_vs_p2p_hours()
    assert hrs, "no hour with both an exchange number and a person-to-person board"
    last = max(h["hour"] for h in hrs)
    cutoff = (dt.datetime.strptime(last, "%Y-%m-%dT%H:%M:%SZ") - dt.timedelta(days=EXCH_WINDOW_DAYS)).strftime("%Y-%m-%dT%H:%M:%SZ")
    names = {}
    for ccy in {h["ccy"] for h in hrs}:
        try:
            names[ccy] = [v["venue"] for v in json.load(open(os.path.join(DATA, "countries", ccy + ".json"))).get("venues", [])]
        except (OSError, ValueError):
            names[ccy] = []
    ev = []
    for ccy in sorted({h["ccy"] for h in hrs}):
        all_h = [h for h in hrs if h["ccy"] == ccy]
        recent = [h for h in all_h if h["hour"] > cutoff]
        days = {h["hour"][:10] for h in recent}
        share_recent = (sum(1 for h in recent if h["gap"] >= EXCH_GAP_PTS) / len(recent)) if recent else 0.0
        persists = len(days) >= EXCH_PERSIST_DAYS and share_recent >= EXCH_PERSIST_SHARE
        ev.append({"ccy": ccy, "country": re.sub(r"^the ", "", __import__("emit_countries").COUNTRY.get(ccy, ccy)), "median_gap_pts": round(statistics.median(h["gap"] for h in all_h), 2),
                   "share_gap_2pts": round(sum(1 for h in all_h if h["gap"] >= EXCH_GAP_PTS) / len(all_h), 3),
                   "hours_checked": len(all_h), "first_day": min(h["hour"] for h in all_h)[:10],
                   "exchanges": names.get(ccy, []), "boards": sorted({b for h in all_h for b in h["boards"]}),
                   "share_gap_2pts_30d": round(share_recent, 3), "days_30d": len(days), "persists": persists})
    ev.sort(key=lambda e: (not e["persists"], -e["median_gap_pts"]))
    hdr = ["hour_utc", "ccy", "published_pct", "board_pct", "gap_pts", "boards"]
    lines = [[h["hour"], h["ccy"], round(h["published"], 4), round(h["board"], 4), round(h["gap"], 4), "+".join(h["boards"])] for h in hrs]
    # the file stays under the size limit: oldest days drop first, never below the 30 days the rule reads
    while len(lines) > 1 and len((",".join(hdr) + "\n" + "\n".join(",".join(str(v) for v in r) for r in lines)).encode()) > MAX_HOURS_BYTES - 1000:
        day = lines[0][0][:10]
        if lines[0][0] <= cutoff:
            lines = [r for r in lines if r[0][:10] != day]
        else:
            break
    n = sum(1 for e in ev if e["persists"])
    meth = ["tools/emit_findings.py", "tools/emit_index_hourly.py", "tools/emit_countries.py"]
    return _finding("exchange_vs_p2p",
                    ["data/index_hourly.csv", "data/p2p_basis.csv", "data/p2p_okx.csv", "data/p2p_sides.csv"], meth,
                    {"value": n, "unit": "countries_exchange_vs_p2p", "as_of_utc": last},
                    ev, last, _hours_csv("exchange_vs_p2p", hdr, lines), "data/index_hourly.csv", ["data/findings.json"])


def build():
    fs = price_changes_findings() + [volume_crossover_finding(), sgd_php_finding(), exchange_vs_p2p_finding(), stress_finding(), spread_finding()]
    return {"as_of_utc": max(f["last_recheck_utc"] for f in fs), "findings": fs}


def self_test(doc):
    rc.assert_no_nan(doc)
    ids = [f["id"] for f in doc["findings"]]
    assert len(ids) == len(set(ids)) and ids
    for f in doc["findings"]:
        h = f["headline"]
        assert isinstance(h["value"], (int, float)) and h["unit"] and h["as_of_utc"]
        assert f["evidence"] and f["source_files"] and f["method_files"]
        assert f["last_recheck_utc"] >= h["as_of_utc"] or h["as_of_utc"] <= doc["as_of_utc"]
        full = os.path.join(HERE, f["download_file"])
        assert f["download_file"] and (os.path.exists(full) or PENDING.get(full)), f["id"]
        if f["hours_file"]:
            body = PENDING[os.path.join(HERE, f["hours_file"])]
            assert len(body.encode()) < MAX_HOURS_BYTES
            assert len(list(csv.reader(body.splitlines()))) - 1 == f["hours_rows"] > 0, f["id"]
        else:
            assert os.path.getsize(full) > MAX_HOURS_BYTES or f["id"] != "p2p_spread_signal"
    pc = {f["id"]: f for f in doc["findings"]}
    latest = _json("price_changes_latest.json")
    assert sum(e["changes"] for e in pc["price_changes"]["evidence"]) == pc["price_changes"]["headline"]["value"]
    assert pc["price_changes"]["headline"]["value"] + sum(
        e["weekend_up"] + e["weekend_back"] for e in pc["weekend_penalty"]["evidence"]) == latest["counts"]["total"]
    print("findings self-test ok: " + ", ".join("%s=%s" % (f["id"], f["headline"]["value"]) for f in doc["findings"]))


def main():
    doc = build()
    self_test(doc)
    if "--self-test" in sys.argv:
        return
    for path, body in sorted(PENDING.items()):
        if body is None:
            if os.path.exists(path):
                os.remove(path)
        else:
            with open(path, "w", encoding="utf-8", newline="") as f:
                f.write(body)
    rc.write_json(OUT, doc)


if __name__ == "__main__":
    main()
