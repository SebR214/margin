#!/usr/bin/env python3
"""The daily status comment on SEB-301 (SEB-301). Written by this script from
the logs and GitHub's own records. No model call.

    python3 tools/daily_status.py            # build it and post it on SEB-301
    python3 tools/daily_status.py --print    # build it, print it, post nothing
    python3 tools/daily_status.py --self-test

Covers: collector health, the runner's and the researcher's last runs, PRs merged in
the last 24 hours, open PRs (a PR that changes collection code is left open on
purpose and is named), and this month's spend against the $20 ceiling.

Env: GH_TOKEN, GITHUB_REPOSITORY, LINEAR_API_KEY (to post).
"""
import csv
import datetime
import json
import os
import re
import subprocess
import sys
import urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "tools"))
sys.path.insert(0, os.path.join(ROOT, "agents"))
import llm  # noqa: E402
import check_additive  # noqa: E402

ISSUE = "SEB-301"
COLLECTION_CODE = re.compile(r"^collector[^/]*\.py$|^\.github/workflows/collect\.yml$")
RESEARCHER_LOG = os.path.join(ROOT, "data", "researcher_log.csv")
BUILDER_LOG = os.path.join(ROOT, "data", "builder_log.csv")   # ts_utc,status,job,pr,detail: one row per daily builder run (tools/one_call.py)


def gh(path):
    req = urllib.request.Request(
        "https://api.github.com/repos/%s/%s" % (os.environ["GITHUB_REPOSITORY"], path),
        headers={"Authorization": "Bearer " + os.environ["GH_TOKEN"],
                 "Accept": "application/vnd.github+json"})
    with urllib.request.urlopen(req, timeout=60) as r:
        return json.loads(r.read())


def ts(s):
    return datetime.datetime.fromisoformat(s.replace("Z", "+00:00"))


def ago(now, t):
    secs = int((now - t).total_seconds())
    if secs < 5400:
        return "%d min ago" % (secs // 60)
    if secs < 172800:
        return "%d h ago" % (secs // 3600)
    return "%d days ago" % (secs // 86400)


def last_run(now, workflow):
    runs = gh("actions/workflows/%s/runs?status=completed&per_page=1" % workflow)["workflow_runs"]
    if not runs:
        return "no completed run yet"
    r = runs[0]
    return "%s, %s ([run](%s))" % (r["conclusion"], ago(now, ts(r["updated_at"])), r["html_url"])


def touches_collection_code(files):
    return any(COLLECTION_CODE.match(f) for f in files)


def collector_health():
    r = subprocess.run([sys.executable, os.path.join(ROOT, "tools", "check_collector_health.py")],
                       cwd=ROOT, capture_output=True, text=True, timeout=300)
    line = (r.stdout.strip().splitlines() or [r.stderr.strip()[:200] or "no output"])[-1]
    return ("healthy" if r.returncode == 0 else "NOT HEALTHY") + ": " + line


def researcher_last():
    if not os.path.exists(RESEARCHER_LOG):
        return "no log yet"
    rows = list(csv.DictReader(open(RESEARCHER_LOG)))
    if not rows:
        return "no log yet"
    r = rows[-1]
    return "%s, %s jobs added at %s. %s" % (r["status"], r["added"], r["ts_utc"][:16].replace("T", " ") + " UTC", r["detail"][:160])


def built_today(now, path=BUILDER_LOG):
    """One line for the day: 'Built today: {job}, PR #{n}' or 'Built nothing today: {reason}'. Read from data/builder_log.csv, which
    the daily builder writes. The newest row of the UTC day wins; no row means the builder has not run yet today."""
    day = now.date().isoformat()
    rows = []
    if os.path.exists(path):
        with open(path, newline="") as f:
            rows = [r for r in csv.DictReader(f) if r["ts_utc"][:10] == day]
    if not rows:
        return "no builder run yet today"
    r = rows[-1]
    if r["status"] == "built":
        return "%s, PR #%s" % (r["job"], r["pr"])
    return "nothing: %s" % (r["detail"] or r["status"])


def build(now=None):
    now = now or datetime.datetime.now(datetime.timezone.utc)
    since = now - datetime.timedelta(hours=24)
    month = llm.month_spend(now)
    lines = ["**Daily status** (written by a script from the logs, %s UTC)" % now.strftime("%Y-%m-%d %H:%M"), ""]
    lines.append("- **Collector:** " + collector_health())
    lines.append("- **Collection run (collect.yml):** " + last_run(now, "collect.yml"))
    lines.append("- **Runner (one_call.yml):** " + last_run(now, "one_call.yml"))
    lines.append("- **Researcher (researcher.yml):** " + last_run(now, "researcher.yml"))
    lines.append("- **Researcher, last result:** " + researcher_last())
    lines.append("- **Built today:** " + built_today(now))
    closed = gh("pulls?state=closed&sort=updated&direction=desc&per_page=50")
    merged = [p for p in closed if p.get("merged_at") and ts(p["merged_at"]) >= since]
    lines.append("- **Merged in the last 24 hours:** %d" % len(merged))
    for p in merged[:15]:
        lines.append("  - [#%d](%s) %s" % (p["number"], p["html_url"], p["title"]))
    opened = gh("pulls?state=open&per_page=50")
    lines.append("- **Open PRs:** %d" % len(opened))
    for p in opened[:20]:
        files = gh("pulls/%d/files?per_page=100" % p["number"])
        touches, additive, why = check_additive.classify(files)
        note = ""
        if touches and not additive:
            note = " **(changes existing collection code, so it is not merged by itself: %s)**" % "; ".join(why)
        elif p.get("draft"):
            note = " (draft)"
        lines.append("  - [#%d](%s) %s%s" % (p["number"], p["html_url"], p["title"], note))
    import check_audit_health
    bad_numbers, bad_claims = check_audit_health.summary()
    lines.append("- **Audits:** %s" % ("all numbers matched, all claims true" if not (bad_numbers or bad_claims) else
                 "%d number(s) did not match their raw rows (%s); %d claim(s) false (%s)" % (
                     len(bad_numbers), ", ".join(bad_numbers) or "none", len(bad_claims), ", ".join(bad_claims) or "none")))
    import source_gate
    st = source_gate.status()
    lines.append("- **Sources:** %d approved; %s in quarantine; %s" % (
        len(st["approved"]), ", ".join(st["quarantine"]) or "none",
        ("NOT LISTED but collecting rows (ignored by the index): " + ", ".join(st["unlisted_with_rows"])) if st["unlisted_with_rows"] else "none unlisted"))
    ack = check_audit_health.acknowledged()
    if ack:
        lines.append("  - parked for Seb, not alarming until the date: " + "; ".join("%s (until %s)" % (k, v["until"]) for k, v in sorted(ack.items())))
    lines.append("- **Spend this month:** $%.2f of $%.2f (%d%%)" % (month, llm.MONTHLY_CAP_USD, round(month / llm.MONTHLY_CAP_USD * 100)))
    return "\n".join(lines)


def already_posted_today(comments, now):
    """True if a "Daily status" comment from the same UTC day is already there: one post a day, however often this runs."""
    day = now.date().isoformat()
    return any(c["body"].startswith("**Daily status**") and c["createdAt"][:10] == day for c in comments)


def post(body, now=None):
    import linear
    now = now or datetime.datetime.now(datetime.timezone.utc)
    i = linear.find(ISSUE)
    since = now.date().isoformat() + "T00:00:00.000Z"
    recent = linear.call("""query($id: String!) { issue(id: $id) { comments(first: 50, filter: { createdAt: { gte: "%s" } }) {
        nodes { body createdAt } } } }""" % since, {"id": i["id"]})
    if already_posted_today(recent["issue"]["comments"]["nodes"], now):
        print("a daily status was already posted today: not posting another")
        return False
    linear.call("""mutation($id: String!, $b: String!) {
      commentCreate(input: { issueId: $id, body: $b }) { success }
    }""", {"id": i["id"], "b": body})
    return True


def self_test():
    n = datetime.datetime(2026, 10, 20, 9, tzinfo=datetime.timezone.utc)
    mk = lambda body, at: {"body": body, "createdAt": at}
    assert already_posted_today([mk("**Daily status** (x)", "2026-10-20T07:47:33Z")], n)
    assert not already_posted_today([mk("**Daily status** (x)", "2026-10-19T08:00:00Z"), mk("Other", "2026-10-20T07:00:00Z")], n)
    import tempfile
    with tempfile.TemporaryDirectory() as d:
        p = os.path.join(d, "b.csv")
        assert built_today(n, p) == "no builder run yet today"
        open(p, "w").write("ts_utc,status,job,pr,detail\n2026-10-20T03:00:00+00:00,failed,1a,,probe failed\n2026-10-20T05:00:00+00:00,built,1b,561,\n")
        assert built_today(n, p) == "1b, PR #561"
        open(p, "a").write("2026-10-20T06:00:00+00:00,nothing,,,no job with files in BACKLOG.md\n")
        assert built_today(n, p) == "nothing: no job with files in BACKLOG.md"
        assert built_today(n.replace(day=21), p) == "no builder run yet today"
    assert touches_collection_code(["collector.py"])
    assert touches_collection_code(["collector_p2p_okx.py", "x.md"])
    assert touches_collection_code([".github/workflows/collect.yml"])
    assert not touches_collection_code(["tools/emit_countries.py", "collector/readme.md", ".github/workflows/researcher.yml"])
    now = datetime.datetime(2026, 10, 12, 12, tzinfo=datetime.timezone.utc)
    assert ago(now, now - datetime.timedelta(minutes=20)) == "20 min ago"
    assert ago(now, now - datetime.timedelta(days=3)) == "3 days ago"
    print("daily_status self-test: ok")


if __name__ == "__main__":
    if "--self-test" in sys.argv:
        self_test()
        sys.exit(0)
    text = build()
    print(text)
    if "--print" not in sys.argv:
        if post(text):
            print("\nposted on " + ISSUE)
