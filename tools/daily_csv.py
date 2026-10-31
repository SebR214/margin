#!/usr/bin/env python3
"""One file per UTC day for the append-only P2P tables (SEB-301, 31 Oct). No model.

    data/p2p_ads.csv, data/p2p_ads_sellers.csv   closed on 28 Oct, never rewritten (GitHub rejects a file over 100 MB)
    data/p2p_ads/YYYY-MM-DD.csv                  what the collector appends from then on, same header
    data/p2p_ads_sellers/YYYY-MM-DD.csv          same
    data/p2p_offers/YYYY-MM-DD.csv               same, for p2p_offers.csv (46 MB and growing)

Writers call append(); readers call paths() or iter_dicts(), which return the old file first (when there is one) and then
every day file in date order, so a reader sees one table. A day file is named for the UTC day it was written, a run that
crosses midnight lands whole in one file, and ts_utc inside each row is untouched. Header handling is the same as the
single files had: written when a file is new.

    python3 tools/daily_csv.py --self-test
"""
import csv
import datetime as dt
import glob
import os
import sys
import tempfile

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SITE_DATA = os.path.join(HERE, "data")


def raw_dir():
    """Where the raw append-only tables live (SEB-422, 31 Oct): data/ in this repo, or the margin-data checkout when the run
    set MARGIN_RAW_DIR (tools/raw_storage.py does that once the App can push there). A path that does not exist is an error,
    never a quiet fall back to data/."""
    d = os.environ.get("MARGIN_RAW_DIR")
    if not d:
        return SITE_DATA
    if not os.path.isdir(d):
        raise SystemExit("MARGIN_RAW_DIR=%s is not a directory" % d)
    return d


DATA = raw_dir()


def today():
    return dt.datetime.now(dt.timezone.utc).date()


def day_path(name, day=None, data=DATA):
    day = day or today()
    return os.path.join(data, name, "%s.csv" % day.isoformat())


def append(name, header, rows, day=None, data=DATA):
    """Append rows (lists) to today's file for `name`, with the header when the file is new. Returns the path."""
    path = day_path(name, day, data)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    new = not os.path.exists(path)
    with open(path, "a", newline="") as fh:
        w = csv.writer(fh)
        if new:
            w.writerow(header)
        w.writerows(rows)
    return path


def append_dicts(name, fields, rows, day=None, data=DATA):
    """Same, for dict rows (extra keys ignored, like csv.DictWriter(extrasaction='ignore'))."""
    path = day_path(name, day, data)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    new = not os.path.exists(path)
    with open(path, "a", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=fields, extrasaction="ignore")
        if new:
            w.writeheader()
        w.writerows(rows)
    return path


def paths(name, data=DATA):
    """The old single file (if it exists), then the day files in date order."""
    out = []
    old = os.path.join(data, name + ".csv")
    if os.path.exists(old):
        out.append(old)
    out.extend(sorted(glob.glob(os.path.join(data, name, "????-??-??.csv"))))
    return out


def iter_dicts(name, data=DATA, **open_kw):
    """Every row of the old file and the day files as dicts, oldest file first."""
    for p in paths(name, data):
        with open(p, newline="", **open_kw) as fh:
            for r in csv.DictReader(fh):
                yield r


def tail(name, nbytes=8192, data=DATA):
    """The last nbytes of the newest file, as text split into lines; [] when there is none."""
    ps = paths(name, data)
    while ps:
        p = ps.pop()
        size = os.path.getsize(p)
        if size == 0:
            continue
        with open(p, "rb") as fh:
            fh.seek(max(0, size - nbytes))
            return fh.read().decode("utf-8", "replace").splitlines()
    return []


def data_rows(name, data=DATA):
    """Data rows over all the files (newlines minus one header per file), counted in 1 MB chunks."""
    n = 0
    for p in paths(name, data):
        k = 0
        with open(p, "rb") as fh:
            for chunk in iter(lambda: fh.read(1 << 20), b""):
                k += chunk.count(b"\n")
        n += max(k - 1, 0)
    return n


def self_test():
    with tempfile.TemporaryDirectory() as d:
        header = ["ts_utc", "ccy", "price"]
        old = os.path.join(d, "p2p_ads.csv")
        with open(old, "w", newline="") as fh:
            csv.writer(fh).writerows([header, ["2026-10-28T20:00:00Z", "AED", "3.69"]])
        before = open(old, "rb").read()
        assert tail("p2p_ads", data=d)[-1].startswith("2026-10-28"), "tail falls back to the old file"
        d1, d2 = dt.date(2026, 10, 29), dt.date(2026, 10, 30)
        p1 = append("p2p_ads", header, [["2026-10-29T01:00:00Z", "AED", "3.70"]], d1, d)
        append("p2p_ads", header, [["2026-10-29T02:00:00Z", "AED", "3.71"]], d1, d)
        p2 = append("p2p_ads", header, [["2026-10-30T01:00:00Z", "INR", "88.1"]], d2, d)
        assert p1.endswith(os.path.join("p2p_ads", "2026-10-29.csv")) and p2.endswith("2026-10-30.csv")
        assert open(old, "rb").read() == before, "the closed file is never touched"
        assert open(p1).read().count("ts_utc") == 1, "one header per day file, not one per append"
        assert paths("p2p_ads", d) == [old, p1, p2], paths("p2p_ads", d)
        got = [(r["ts_utc"][:10], r["ccy"]) for r in iter_dicts("p2p_ads", d)]
        assert got == [("2026-10-28", "AED"), ("2026-10-29", "AED"), ("2026-10-29", "AED"), ("2026-10-30", "INR")], got
        assert data_rows("p2p_ads", d) == 4, data_rows("p2p_ads", d)
        assert tail("p2p_ads", data=d)[-1].startswith("2026-10-30"), "tail reads the newest day file"
        pd = append_dicts("p2p_offers", ["ts_utc", "price"], [{"ts_utc": "t", "price": 1, "extra": 2}], d1, d)
        assert open(pd).read().splitlines() == ["ts_utc,price", "t,1"], open(pd).read()
        assert paths("nothing", d) == [] and list(iter_dicts("nothing", d)) == [] and tail("nothing", data=d) == []
        assert data_rows("nothing", d) == 0
    print("daily_csv self-test ok")
    return 0


if __name__ == "__main__":
    if "--self-test" in sys.argv:
        sys.exit(self_test())
    print(__doc__)
