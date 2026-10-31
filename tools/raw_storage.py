#!/usr/bin/env python3
"""Where the raw append-only tables live (SEB-422, lever 1, 31 Oct). No model.

The raw tables are data/p2p_ads/, data/p2p_ads_sellers/, data/p2p_offers/ and data/depth/ (one file a day each, plus the closed
single files data/p2p_ads.csv, data/p2p_ads_sellers.csv, data/p2p_offers.csv and data/depth.csv). They are the part of the data
that grows without a limit, so they move to the public repo SebR214/margin-data, one folder per table, one file a day, same
headers. The site repo keeps every file a page reads, every receipt and every aggregate.

    python3 tools/raw_storage.py probe            # "split" when the margin-agents App can write to margin-data, else "legacy"
    python3 tools/raw_storage.py seed RAW_DIR     # copy this repo's raw tables into RAW_DIR as day files, safe to repeat
    python3 tools/raw_storage.py --self-test

probe reads GET /installation/repositories with the App token in GH_TOKEN. In split mode collect.yml checks margin-data out next to
the site repo, sets MARGIN_RAW_DIR to it (tools/daily_csv.py then writes and reads the raw tables there), seeds it, and pushes it
in a separate commit step. In legacy mode nothing changes: the tables stay in data/. So the code can merge before Seb's one click
(installing the App on margin-data) and flips to split on the first run after it, with no further change. Any other answer from
GitHub (a bad token, a 5xx) is an error, never "legacy": a run must not quietly keep the tables in the wrong place.

seed never loses a row and never rewrites one. A closed single file is cut into day files by the date in ts_utc. A day file that
already exists in RAW_DIR is only replaced by a longer one that starts with the same bytes (the site copy grew before the flip);
if neither starts with the other it stops with an error and names the file.
"""
import csv
import io
import json
import os
import shutil
import sys
import tempfile
import urllib.request

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import daily_csv  # noqa: E402

REPO = "SebR214/margin-data"
TABLES = ("p2p_ads", "p2p_ads_sellers", "p2p_offers", "depth")


def installed_repos(token, fetch=None):
    """Every full_name the installation behind `token` can reach (it pages at 100)."""
    names, page = [], 1
    while True:
        url = "https://api.github.com/installation/repositories?per_page=100&page=%d" % page
        if fetch:
            doc = fetch(url)
        else:
            req = urllib.request.Request(url, headers={"Authorization": "Bearer " + token, "Accept": "application/vnd.github+json"})
            with urllib.request.urlopen(req, timeout=30) as r:
                doc = json.load(r)
        got = [x["full_name"] for x in doc.get("repositories", [])]
        names += got
        if len(got) < 100:
            return names
        page += 1


def mode(token, fetch=None):
    return "split" if REPO in installed_repos(token, fetch) else "legacy"


def _body(path):
    """The bytes of a csv without its header line, and the header line."""
    with open(path, "rb") as f:
        raw = f.read()
    head, _, rest = raw.partition(b"\n")
    return head + b"\n", rest


def cut_closed(src, workdir):
    """Cut a closed single file into workdir/<day>.csv by the date in the first column. Returns {day: path}."""
    out, writers, files = {}, {}, []
    with open(src, newline="") as f:
        r = csv.reader(f)
        header = next(r, None)
        if header is None:
            return out
        for row in r:
            if not row or not row[0]:
                continue
            day = row[0][:10]
            if day not in writers:
                p = os.path.join(workdir, day + ".csv")
                fh = open(p, "w", newline="")
                files.append(fh)
                writers[day] = csv.writer(fh)
                writers[day].writerow(header)
                out[day] = p
            writers[day].writerow(row)
    for fh in files:
        fh.close()
    return out


def put_day(dest, parts):
    """Write the day file made of `parts` (day files with the same header, in order) to dest, under the prefix rule.
    Returns 'new', 'grown' or 'kept'."""
    header = None
    body = b""
    for p in parts:
        h, b = _body(p)
        header = header or h
        body += b if b.endswith(b"\n") or not b else b + b"\n"
    data = (header or b"") + body
    if not os.path.exists(dest):
        os.makedirs(os.path.dirname(dest), exist_ok=True)
        with open(dest, "wb") as f:
            f.write(data)
        return "new"
    with open(dest, "rb") as f:
        have = f.read()
    if have == data or have.startswith(data):
        return "kept"
    if data.startswith(have):
        with open(dest, "wb") as f:
            f.write(data)
        return "grown"
    raise SystemExit("seed: %s and the copy in this repo both have rows the other lacks; nothing was changed. Fix by hand." % dest)


def seed(raw, site=daily_csv.SITE_DATA, tables=TABLES):
    """Copy the site repo's raw tables into raw/<table>/<day>.csv. Returns {table: counts}."""
    report = {}
    for t in tables:
        c = {"new": 0, "grown": 0, "kept": 0}
        closed = os.path.join(site, t + ".csv")
        daydir = os.path.join(site, t)
        days = {}
        with tempfile.TemporaryDirectory() as tmp:
            if os.path.exists(closed):
                for day, p in cut_closed(closed, tmp).items():
                    days.setdefault(day, []).append(p)
            if os.path.isdir(daydir):
                for name in sorted(os.listdir(daydir)):
                    if len(name) == 14 and name.endswith(".csv"):
                        days.setdefault(name[:-4], []).append(os.path.join(daydir, name))
            for day, parts in sorted(days.items()):
                c[put_day(os.path.join(raw, t, day + ".csv"), parts)] += 1
        report[t] = c
    return report


def self_test():
    # probe
    pages = {1: {"repositories": [{"full_name": "SebR214/margin"}]}}
    assert mode("t", lambda u: pages[1]) == "legacy"
    pages[1] = {"repositories": [{"full_name": "SebR214/margin"}, {"full_name": REPO}]}
    assert mode("t", lambda u: pages[1]) == "split"
    # seed
    with tempfile.TemporaryDirectory() as d:
        site, raw = os.path.join(d, "site"), os.path.join(d, "raw")
        os.makedirs(os.path.join(site, "p2p_offers"))
        os.makedirs(raw)
        with open(os.path.join(site, "p2p_offers.csv"), "w", newline="") as f:
            w = csv.writer(f)
            w.writerows([["ts_utc", "ccy", "side", "price"], ["2026-10-27T01:00:00+00:00", "AED", "buy", "3.7"],
                         ["2026-10-28T01:00:00+00:00", "AED", "buy", "3.8"], ["2026-10-28T02:00:00+00:00", "INR", "sell", "88"]])
        closed_before = open(os.path.join(site, "p2p_offers.csv"), "rb").read()
        day1 = os.path.join(site, "p2p_offers", "2026-10-31.csv")
        with open(day1, "w", newline="") as f:
            csv.writer(f).writerows([["ts_utc", "ccy", "side", "price"], ["2026-10-31T01:00:00+00:00", "AED", "buy", "3.9"]])
        r = seed(raw, site, ("p2p_offers",))
        assert r["p2p_offers"] == {"new": 3, "grown": 0, "kept": 0}, r
        assert sorted(os.listdir(os.path.join(raw, "p2p_offers"))) == ["2026-10-27.csv", "2026-10-28.csv", "2026-10-31.csv"]
        assert open(os.path.join(raw, "p2p_offers", "2026-10-28.csv")).read().count("\n") == 3
        # a second seed changes nothing
        assert seed(raw, site, ("p2p_offers",))["p2p_offers"] == {"new": 0, "grown": 0, "kept": 3}
        # the site copy of today's file grows before the flip: the raw copy follows
        with open(day1, "a", newline="") as f:
            csv.writer(f).writerow(["2026-10-31T02:00:00+00:00", "INR", "sell", "89"])
        assert seed(raw, site, ("p2p_offers",))["p2p_offers"] == {"new": 0, "grown": 1, "kept": 2}
        # after the flip the raw copy is longer than the site's: kept, never shortened
        with open(os.path.join(raw, "p2p_offers", "2026-10-31.csv"), "a", newline="") as f:
            csv.writer(f).writerow(["2026-10-31T03:00:00+00:00", "INR", "sell", "90"])
        assert seed(raw, site, ("p2p_offers",))["p2p_offers"]["kept"] == 3
        assert open(os.path.join(raw, "p2p_offers", "2026-10-31.csv")).read().count("\n") == 4
        # a closed file and a day file for the same day join, closed rows first
        os.makedirs(os.path.join(site, "depth"))
        with open(os.path.join(site, "depth.csv"), "w", newline="") as f:
            csv.writer(f).writerows([["ts_utc", "x"], ["2026-10-31T01:00:00+00:00", "a"]])
        with open(os.path.join(site, "depth", "2026-10-31.csv"), "w", newline="") as f:
            csv.writer(f).writerows([["ts_utc", "x"], ["2026-10-31T02:00:00+00:00", "b"]])
        assert seed(raw, site, ("depth",))["depth"]["new"] == 1
        got = [r["x"] for r in csv.DictReader(open(os.path.join(raw, "depth", "2026-10-31.csv"), newline=""))]
        assert got == ["a", "b"], got
        # rows that disagree stop the run
        with open(os.path.join(raw, "p2p_offers", "2026-10-28.csv"), "w") as f:
            f.write("ts_utc,ccy,side,price\nSOMETHING ELSE\n")
        try:
            seed(raw, site, ("p2p_offers",))
            raise AssertionError("conflict should stop")
        except SystemExit as e:
            assert "2026-10-28.csv" in str(e)
        assert open(os.path.join(site, "p2p_offers.csv"), "rb").read() == closed_before, "the closed file is never touched"
        # daily_csv reads the seeded folder as one table
        assert daily_csv.data_rows("depth", raw) == 2
    # MARGIN_RAW_DIR must exist
    old = os.environ.get("MARGIN_RAW_DIR")
    os.environ["MARGIN_RAW_DIR"] = "/nonexistent/raw"
    try:
        daily_csv.raw_dir()
        raise AssertionError("a missing MARGIN_RAW_DIR must be an error")
    except SystemExit:
        pass
    finally:
        if old is None:
            del os.environ["MARGIN_RAW_DIR"]
        else:
            os.environ["MARGIN_RAW_DIR"] = old
    print("raw_storage self-test ok")
    return 0


def main(argv):
    if "--self-test" in argv:
        return self_test()
    if argv[1:2] == ["probe"]:
        token = os.environ.get("GH_TOKEN", "")
        if not token:
            print("probe: GH_TOKEN is not set", file=sys.stderr)
            return 1
        m = mode(token)
        print(m)
        return 0
    if argv[1:2] == ["seed"] and len(argv) == 3:
        rep = seed(os.path.abspath(argv[2]))
        for t, c in rep.items():
            print("seed %-16s new %d, grown %d, kept %d" % (t, c["new"], c["grown"], c["kept"]))
        return 0
    print(__doc__)
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv))
