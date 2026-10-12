#!/usr/bin/env python3
"""The daily status comment on SEB-301 (SEB-301). Written by this script from
the logs and GitHub's own records. No model call.

    python3 tools/daily_status.py            # build it and post it on SEB-301
    python3 tools/daily_status.py --print    # build it, print it, post nothing
    python3 tools/daily_status.py --self-test

Covers: collector health, the runner's and the Scout's last runs, PRs merged in
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

ISSUE = "SEB-301"
COLLECTION_CODE = re.compile(r"^collector[^/]*\.py$|^\.github/workflows/collect\.yml$")
SCOUT_LOG = os.path.join(ROOT, "data", "scout_log.csv")


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


def scout_last():
    if not os.path.exists(SCOUT_LOG):
        return "no log yet"
    rows = list(csv.DictReader(open(SCOUT_LOG)))
    if not rows:
        return "no log yet"
    r = rows[-1]
    return "%s (%s) at %s. %s" % (r["status"], r["mode"], r["ts_utc"][:16].replace("T", " ") + " UTC", r["detail"][:160])


def build(now=None):
    now = now or datetime.datetime.now(datetime.timezone.utc)
    since = now - datetime.timedelta(hours=24)
    month = llm.month_spend(now)
    lines = ["**Daily status** (written by a script from the logs, %s UTC)" % now.strftime("%Y-%m-%d %H:%M"), ""]
    lines.append("- **Collector:** " + collector_health())
    lines.append("- **Collection run (collect.yml):** " + last_run(now, "collect.yml"))
    lines.append("- **Runner (one_call.yml):** " + last_run(now, "one_call.yml"))
    lines.append("- **Scout (scout.yml):** " + last_run(now, "scout.yml"))
    lines.append("- **Scout, last result:** " + scout_last())
    closed = gh("pulls?state=closed&sort=updated&direction=desc&per_page=50")
    merged = [p for p in closed if p.get("merged_at") and ts(p["merged_at"]) >= since]
    lines.append("- **Merged in the last 24 hours:** %d" % len(merged))
    for p in merged[:15]:
        lines.append("  - [#%d](%s) %s" % (p["number"], p["html_url"], p["title"]))
    opened = gh("pulls?state=open&per_page=50")
    lines.append("- **Open PRs:** %d" % len(opened))
    for p in opened[:20]:
        files = [f["filename"] for f in gh("pulls/%d/files?per_page=100" % p["number"])]
        note = ""
        if touches_collection_code(files):
            note = " **(changes collection code: left open, needs a person)**"
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


def post(body):
    import linear
    i = linear.find(ISSUE)
    linear.call("""mutation($id: String!, $b: String!) {
      commentCreate(input: { issueId: $id, body: $b }) { success }
    }""", {"id": i["id"], "b": body})


def self_test():
    assert touches_collection_code(["collector.py"])
    assert touches_collection_code(["collector_p2p_okx.py", "x.md"])
    assert touches_collection_code([".github/workflows/collect.yml"])
    assert not touches_collection_code(["tools/emit_countries.py", "collector/readme.md", ".github/workflows/scout.yml"])
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
        post(text)
        print("\nposted on " + ISSUE)
