#!/usr/bin/env python3
"""The weekly planner (SEB-301). No model. One line on SEB-301 each Monday: items shipped per track and cost per track.

    python3 tools/weekly_planner.py            # build the line and post it on SEB-301
    python3 tools/weekly_planner.py --print    # build it, print it, post nothing
    python3 tools/weekly_planner.py --self-test

Track A is the Aider builder (data/aider_log.csv, spend rows `SEB-301/aider/<job>`). Track B is the one-call builder
(data/builder_log.csv, the other `SEB-301/<job>` spend rows). The Scout's rows (issue contains `scout`) are named apart. Every
number is counted from those three files for the 7 days before the run. It also names the jobs waiting for Claude.

Env: LINEAR_API_KEY (to post).
"""
import csv
import datetime
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "tools"))
sys.path.insert(0, os.path.join(ROOT, "agents"))
import backlog  # noqa: E402

DAYS = 7


def read(path):
    if not os.path.exists(path):
        return []
    with open(path, newline="") as f:
        return list(csv.DictReader(f))


def since(rows, now, days=DAYS):
    cut = (now - datetime.timedelta(days=days)).strftime("%Y-%m-%dT%H:%M:%S")
    return [r for r in rows if (r.get("ts_utc") or "") >= cut]


def track_of(issue):
    if "scout" in issue:
        return "scout"
    return "A" if "/aider/" in issue else "B"


def numbers(spend, aider, builder, now):
    cost = {"A": 0.0, "B": 0.0, "scout": 0.0}
    for r in since(spend, now):
        try:
            cost[track_of(r.get("issue") or "")] += float(r.get("cost_usd") or 0)
        except ValueError:
            pass
    shipped = {"A": sum(1 for r in since(aider, now) if r["status"] == "built"),
               "B": sum(1 for r in since(builder, now) if r["status"] == "built")}
    failed = {"A": sum(1 for r in since(aider, now) if r["status"] == "failed"),
              "B": sum(1 for r in since(builder, now) if r["status"] == "failed")}
    return shipped, failed, cost


def waiting(text):
    out = []
    for it in backlog.parse(text):
        for j in it["jobs"]:
            if not j["done"] and "needs-claude" in j["blocked"]:
                out.append(j["id"])
    return out


def line(shipped, failed, cost, wait):
    def per(t):
        return "$%.2f" % (cost[t] / shipped[t]) if shipped[t] else "n/a"
    return ("Week: track A (Aider) shipped %d, failed %d, cost $%.2f (%s an item). Track B (one-call) shipped %d, failed %d, cost $%.2f (%s an item). "
            "Scout $%.2f. Waiting for Claude: %s." % (
                shipped["A"], failed["A"], cost["A"], per("A"), shipped["B"], failed["B"], cost["B"], per("B"), cost["scout"],
                ", ".join(wait) if wait else "none"))


def post(text):
    import linear
    i = linear.find("SEB-301")
    linear.call("""mutation($id: String!, $b: String!) {
      commentCreate(input: { issueId: $id, body: $b }) { success }
    }""", {"id": i["id"], "b": "🗓️ **Weekly planner:** " + text})


def self_test():
    now = datetime.datetime(2026, 10, 26, 7, 0)
    spend = [{"ts_utc": "2026-10-25T06:00:00+00:00", "issue": "SEB-301/aider/1a", "cost_usd": "0.50"},
             {"ts_utc": "2026-10-24T06:00:00+00:00", "issue": "SEB-301/3a", "cost_usd": "0.004"},
             {"ts_utc": "2026-10-24T06:00:00+00:00", "issue": "SEB-300/scout", "cost_usd": "0.03"},
             {"ts_utc": "2026-10-10T06:00:00+00:00", "issue": "SEB-301/aider/9z", "cost_usd": "9"}]
    aider = [{"ts_utc": "2026-10-25T06:00:00+00:00", "status": "built"}, {"ts_utc": "2026-10-23T06:00:00+00:00", "status": "failed"}]
    builder = [{"ts_utc": "2026-10-24T06:00:00+00:00", "status": "built"}, {"ts_utc": "2026-10-24T06:00:00+00:00", "status": "nothing"}]
    s, f, c = numbers(spend, aider, builder, now)
    assert s == {"A": 1, "B": 1} and f == {"A": 1, "B": 0}, (s, f)
    assert abs(c["A"] - 0.5) < 1e-9 and abs(c["B"] - 0.004) < 1e-9 and abs(c["scout"] - 0.03) < 1e-9, c
    t = "- [ ] 1. R\n  - [ ] 1a. Add\n    files: `a.py`\n    blocked: needs-claude: failed 2 times (2026-10-22)\n"
    assert waiting(t) == ["1a"]
    out = line(s, f, c, ["1a"])
    assert "shipped 1, failed 1, cost $0.50 ($0.50 an item)" in out and "Waiting for Claude: 1a." in out and "\u2014" not in out
    assert "n/a" in line({"A": 0, "B": 0}, f, c, [])
    print("weekly_planner self-test: ok")


def main(argv):
    if "--self-test" in argv:
        self_test()
        return 0
    now = datetime.datetime.now(datetime.timezone.utc).replace(tzinfo=None)
    s, f, c = numbers(read(os.path.join(ROOT, "data", "agent_spend.csv")), read(os.path.join(ROOT, "data", "aider_log.csv")),
                      read(os.path.join(ROOT, "data", "builder_log.csv")), now)
    out = line(s, f, c, waiting(open(backlog.PATH).read()))
    print(out)
    if "--print" not in argv:
        post(out)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
