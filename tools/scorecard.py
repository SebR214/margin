#!/usr/bin/env python3
"""The weekly agent scorecard (SEB-301, Seb's plan of 25 Oct). Plain code, no model.

The only evidence that track A works. Bot PRs merged in the last 7 days, which backlog job each came from, who proposed that job
(the researcher, or a chat/Seb), what the builder tried, and what the agents spent. If the agents merged nothing, that is line one.
It also counts toward the kill date: at least 4 bot PRs from researcher jobs merged by 8 Nov 2026, or track A is switched off.

Sent as a comment on the GitHub issue "Agent scorecard", mentioning the repo owner, so GitHub emails it to him. Once per week
(a marker in the comment), unless --force.

    python3 tools/scorecard.py             # build it and post it
    python3 tools/scorecard.py --print     # build it, print it, post nothing
    python3 tools/scorecard.py --self-test

Env: GH_TOKEN (issues: write), GITHUB_REPOSITORY.
"""
import csv
import datetime
import json
import os
import re
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "tools"))
import backlog  # noqa: E402
import job_shape  # noqa: E402

TITLE = "Agent scorecard"
START = datetime.date(2026, 10, 25)
KILL = datetime.date(2026, 11, 8)
NEED = 4
BRANCH = re.compile(r"^(aider|one-call)/backlog-([0-9]+[a-z]+)$")
MARK = re.compile(r"<!-- scorecard:(\d{4}-W\d{2}) -->")


def ts(s):
    return datetime.datetime.fromisoformat(s.replace("Z", "+00:00"))


def read_csv(rel):
    p = os.path.join(ROOT, rel)
    if not os.path.exists(p):
        return []
    with open(p, newline="") as f:
        return list(csv.DictReader(f))


def proposers(text):
    """job id -> 'researcher' or 'chat'. A job is the researcher's only if it carries a `proposed: researcher` line."""
    out, cur = {}, None
    for line in text.split("\n"):
        m = backlog.JOB.match(line)
        if m:
            cur = m.group(2)
            out[cur] = "chat"
            continue
        if cur and line.startswith("    ") and line.strip().startswith("proposed: researcher"):
            out[cur] = "researcher"
        elif line.strip() and not line.startswith("    "):
            cur = None
    return out


PROPOSED = re.compile(r"^proposed: researcher (\d{4}-\d{2}-\d{2})\b")


def researcher_jobs(text, since, until):
    """(job id, title) of every job with a `proposed: researcher <date>` line dated since..until, in BACKLOG.md order."""
    out, cur = [], None
    for line in text.split("\n"):
        m = backlog.JOB.match(line)
        if m:
            cur = (m.group(2), m.group(3).strip())
            continue
        d = PROPOSED.match(line.strip()) if cur and line.startswith("    ") else None
        if d and since <= datetime.date.fromisoformat(d.group(1)) <= until:
            out.append(cur)
        elif line.strip() and not line.startswith("    "):
            cur = None
    return out


def bot_merged(prs, since, until=None):
    out = []
    for p in prs:
        if not p.get("merged_at") or not (p.get("user") or {}).get("login", "").endswith("[bot]"):
            continue
        t = ts(p["merged_at"])
        if t < since or (until and t >= until):
            continue
        m = BRANCH.match((p.get("head") or {}).get("ref", ""))
        out.append({"number": p["number"], "title": p["title"], "url": p.get("html_url", ""), "merged_at": p["merged_at"],
                    "job": m.group(2) if m else ""})
    return sorted(out, key=lambda r: r["merged_at"])


def agent_of(issue):
    if "researcher" in issue:
        return "researcher"
    if "scout" in issue:
        return "scout (removed 25 Oct)"
    if "/aider/" in issue:
        return "Aider builder"
    return "one-call builder" if issue.startswith("SEB-301/") else "other"


def spend(rows, since):
    out = {}
    for r in rows:
        if r.get("ts_utc") and ts(r["ts_utc"]) >= since:
            a = agent_of(r.get("issue", ""))
            out[a] = out.get(a, 0.0) + float(r.get("cost_usd") or 0)
    return out


def attempts(rows, since):
    out = {}
    for r in rows:
        if r.get("ts_utc") and ts(r["ts_utc"]) >= since:
            out[r["status"]] = out.get(r["status"], 0) + 1
    return out


def ready(text):
    out = []
    for it in backlog.parse(text):
        if it["done"]:
            continue
        for j in it["jobs"]:
            if not j["done"] and not j["blocked"] and not j["built"] and j["files"] and j["track"] in ("", "aider") \
                    and not job_shape.forbidden(j["files"]):
                out.append(j["id"])
    return out


def missed_hours(seen, since, now):
    """(missed, slots, longest gap in hours) over the whole UTC hours between `since` and `now`. `seen` holds hour-truncated
    datetimes with a collection row (data/basis.csv). The current hour is left out, since it may not have run yet."""
    start = since.replace(minute=0, second=0, microsecond=0) + datetime.timedelta(hours=1)
    end = now.replace(minute=0, second=0, microsecond=0)
    slots, missed, run, longest = 0, 0, 0, 0
    t = start
    while t < end:
        slots += 1
        if t in seen:
            run = 0
        else:
            missed += 1
            run += 1
            longest = max(longest, run)
        t += datetime.timedelta(hours=1)
    return missed, slots, longest


def build(now, prs, text, spend_rows, aider_rows, researcher_rows, hours_seen=None):
    since = now - datetime.timedelta(days=7)
    month0 = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    who = proposers(text)
    week = bot_merged(prs, since)
    for p in week:
        p["by"] = who.get(p["job"], "chat") if p["job"] else "unknown"
    all_since = bot_merged(prs, datetime.datetime.combine(START, datetime.time(), datetime.timezone.utc))
    kill_count = sum(1 for p in all_since if p["job"] and who.get(p["job"]) == "researcher")
    lines = []
    if not week:
        lines.append("**Agents merged nothing this week.**")
    else:
        lines.append("**Agents merged %d PR%s this week.**" % (len(week), "" if len(week) == 1 else "s"))
    lines.append("")
    lines.append("Week: %s to %s UTC." % (since.strftime("%d %b %H:%M"), now.strftime("%d %b %H:%M")))
    for p in week:
        lines.append("- [#%d](%s) job %s, proposed by %s: %s" % (p["number"], p["url"], p["job"] or "?", p["by"], p["title"][:90]))
    if hours_seen is not None:
        mh, slots, longest = missed_hours(hours_seen, since, now)
        lines.append("")
        lines.append(("**Collection missed %d of %d hours this week** (longest gap %d hours). Missed hours can't be filled later."
                      % (mh, slots, longest)) if mh else "Collection ran every hour this week (%d of %d)." % (slots, slots))
    a = attempts(aider_rows, since)
    lines.append("")
    lines.append("Builder runs this week: " + (", ".join("%s %d" % (k, v) for k, v in sorted(a.items())) if a else "none") + ".")
    r = [x for x in researcher_rows if x.get("ts_utc") and ts(x["ts_utc"]) >= since]
    lines.append("Researcher this week: " + ("; ".join("%s, %s jobs added" % (x["status"], x["added"]) for x in r) if r else "did not run") + ".")
    for jid, title in researcher_jobs(text, since.date(), now.date()):
        lines.append("- %s: %s" % (jid, title))
    q = ready(text)
    lines.append("Ready jobs in BACKLOG.md now: %d%s." % (len(q), (" (" + ", ".join(q[:10]) + ")") if q else ""))
    w, m = spend(spend_rows, since), spend(spend_rows, month0)
    lines.append("Spend this week: $%.2f%s. This month: $%.2f of $20." % (
        sum(w.values()), (" (" + ", ".join("%s $%.2f" % (k, v) for k, v in sorted(w.items())) + ")") if w else "", sum(m.values())))
    lines.append("")
    if now.date() > KILL:
        verdict = "Passed, keep track A" if kill_count >= NEED else "Missed, switch track A off"
        lines.append("Kill date %s: %d of %d researcher-job PRs merged. %s." % (KILL.strftime("%d %b"), kill_count, NEED, verdict))
    else:
        lines.append("Kill date %s: %d of %d researcher-job PRs merged so far." % (KILL.strftime("%d %b"), kill_count, NEED))
    return "\n".join(lines), {"week": len(week), "kill_count": kill_count}


def gh(path, method="GET", data=None):
    cmd = ["gh", "api", "-X", method, "repos/%s/%s" % (os.environ["GITHUB_REPOSITORY"], path)]
    for k, v in (data or {}).items():
        cmd += ["-f", "%s=%s" % (k, v)]
    r = subprocess.run(cmd, capture_output=True, text=True)
    if r.returncode != 0:
        raise SystemExit("gh api %s failed: %s" % (path, r.stderr[-300:]))
    return json.loads(r.stdout) if r.stdout.strip() else None


def week_key(now):
    y, w, _ = now.isocalendar()
    return "%d-W%02d" % (y, w)


def main(argv):
    if "--self-test" in argv:
        return self_test()
    now = datetime.datetime.now(datetime.timezone.utc)
    prs = gh("pulls?state=closed&sort=updated&direction=desc&per_page=100")
    import check_delivery
    seen = set()
    for day, hours in check_delivery.hours_by_day(os.path.join(ROOT, "data", "basis.csv")).items():
        for h in hours:
            seen.add(datetime.datetime(day.year, day.month, day.day, h, tzinfo=datetime.timezone.utc))
    body, _ = build(now, prs, open(backlog.PATH).read(), read_csv("data/agent_spend.csv"), read_csv("data/aider_log.csv"),
                    read_csv("data/researcher_log.csv"), seen)
    print(body)
    if "--print" in argv:
        return 0
    owner = os.environ["GITHUB_REPOSITORY"].split("/")[0]
    issues = [x for x in gh("issues?state=open&per_page=100") if x["title"] == TITLE and "pull_request" not in x]
    key = week_key(now)
    if issues and "--force" not in argv:
        cs = gh("issues/%d/comments?per_page=100" % issues[0]["number"]) or []
        if any((MARK.search(c["body"]) or [None, None])[1] == key for c in cs):
            print("this week's scorecard is already posted (%s)" % key)
            return 0
    number = issues[0]["number"] if issues else gh("issues", "POST", {"title": TITLE, "body": "One comment a week from tools/scorecard.py: what the agents merged, who proposed it, what it cost."})["number"]
    gh("issues/%d/comments" % number, "POST", {"body": "@%s %s\n\n<!-- scorecard:%s -->" % (owner, body, key)})
    print("posted on issue #%d" % number)
    return 0


def self_test():
    text = ("- [ ] 7. X\n  - [ ] 7b. List\n    files: `tools/l.py`\n- [ ] 20. Y\n  - [ ] 20a. Bitkub\n    track: aider\n"
            "    proposed: researcher 2026-10-26 (gap: one_source: THB)\n    files: `collector_bitkub.py` `tests/agent_bitkub.py`\n")
    assert proposers(text) == {"7b": "chat", "20a": "researcher"}
    now = datetime.datetime(2026, 11, 1, 12, tzinfo=datetime.timezone.utc)
    bot = {"login": "margin-agents[bot]"}
    prs = [{"number": 700, "title": "SEB-301: List", "merged_at": "2026-10-30T05:00:00Z", "user": bot, "head": {"ref": "aider/backlog-7b"}},
           {"number": 701, "title": "SEB-301: Bitkub", "merged_at": "2026-10-31T05:00:00Z", "user": bot, "head": {"ref": "aider/backlog-20a"}},
           {"number": 702, "title": "Seb's own", "merged_at": "2026-10-31T06:00:00Z", "user": {"login": "SebR214"}, "head": {"ref": "x"}},
           {"number": 640, "title": "old", "merged_at": "2026-10-22T08:54:54Z", "user": bot, "head": {"ref": "aider/backlog-1a"}},
           {"number": 703, "title": "closed", "merged_at": None, "user": bot, "head": {"ref": "aider/backlog-18a"}}]
    spend_rows = [{"ts_utc": "2026-10-30T05:00:00+00:00", "issue": "SEB-301/aider/7b", "cost_usd": "0.40"},
                  {"ts_utc": "2026-10-26T02:00:00+00:00", "issue": "SEB-301/researcher", "cost_usd": "0.30"},
                  {"ts_utc": "2026-10-20T02:00:00+00:00", "issue": "SEB-300/scout", "cost_usd": "0.02"}]
    body, n = build(now, prs, text, spend_rows, [{"ts_utc": "2026-10-30T05:00:00+00:00", "status": "built"}],
                    [{"ts_utc": "2026-10-26T02:00:00+00:00", "status": "ok", "added": "3"}])
    assert body.startswith("**Agents merged 2 PRs this week.**"), body
    assert "job 7b, proposed by chat" in body and "job 20a, proposed by researcher" in body and "#702" not in body and "#640" not in body
    assert "Spend this week: $0.70" in body and "researcher $0.30" in body, body
    assert "Kill date 08 Nov: 1 of 4 researcher-job PRs merged so far." in body, body
    assert "Ready jobs in BACKLOG.md now: 2 (7b, 20a)" in body, body
    assert researcher_jobs(text, datetime.date(2026, 10, 25), datetime.date(2026, 11, 1)) == [("20a", "Bitkub")]
    assert researcher_jobs(text, datetime.date(2026, 10, 27), datetime.date(2026, 11, 3)) == [], "proposed before the window"
    assert researcher_jobs(text, datetime.date(2026, 10, 20), datetime.date(2026, 10, 25)) == [], "proposed after the window"
    assert "Researcher this week: ok, 3 jobs added.\n- 20a: Bitkub\nReady jobs" in body, body
    body0, _ = build(now, [], text, [], [], [])
    assert body0.startswith("**Agents merged nothing this week.**") and "Researcher this week: did not run" in body0
    late, _ = build(datetime.datetime(2026, 11, 9, tzinfo=datetime.timezone.utc), prs, text, [], [], [])
    assert "Missed, switch track A off" in late, late
    assert week_key(now) == "2026-W44"
    h = lambda d, hh: datetime.datetime(2026, 10, d, hh, tzinfo=datetime.timezone.utc)  # noqa: E731
    full = {h(25, 13) + datetime.timedelta(hours=i) for i in range(168)}
    assert missed_hours(full, now - datetime.timedelta(days=7), now) == (0, 167, 0)
    holes = full - {h(30, 1), h(30, 2), h(30, 3), h(31, 9)}
    assert missed_hours(holes, now - datetime.timedelta(days=7), now) == (4, 167, 3)
    b2, _ = build(now, [], text, [], [], [], holes)
    assert "**Collection missed 4 of 167 hours this week** (longest gap 3 hours)" in b2, b2
    print("scorecard self-test: ok")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
