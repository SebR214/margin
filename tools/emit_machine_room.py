#!/usr/bin/env python3
"""The machine room (SEB-427): what builds the site, from files. Plain code, no model, stdlib only.

    python3 tools/emit_machine_room.py              # sync the merged PR list, write data/machine_room.json
    python3 tools/emit_machine_room.py --self-test

Reads data/aider_log.csv (every attempt of the Aider builder, with OpenRouter's own cost), data/agent_spend.csv (every model call),
the merged PRs on main (git log, kept in data/machine_room_prs.csv so a shallow checkout loses nothing), .github/workflows/*.yml
(name and schedule) and data/machine_room_meters.json (the newest run of each workflow, written by a step that has a token).
Writes data/machine_room.json, which machine-room.html draws. The incident texts and the workflow descriptions are words, so they
live in copy.json; only the numbers an incident quotes (the length of the outage) are worked out here.

A merge counts only if every file it added or changed (BACKLOG.md aside) is not empty on main. Builds PR 696 and 701 merged with
empty files and counted as done; this is the rule that would have caught them.
Loud failure: a row that cannot be read exits non-zero. A number it cannot work out is null, never a guess.
"""
import csv
import datetime as dt
import glob
import json
import os
import re
import subprocess
import sys

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA = os.path.join(HERE, "data")
OUT = os.path.join(DATA, "machine_room.json")
PRS = os.path.join(DATA, "machine_room_prs.csv")
PR_COLS = ["pr", "merged_utc", "files", "empty_files", "title"]
ATTEMPT = ("built", "failed", "harness", "rejected")
PR_RE = re.compile(r"\(#(\d+)\)\s*$")
SGT = 8


def parse_ts(s):
    t = dt.datetime.fromisoformat(s.strip().replace("Z", "+00:00"))
    return t.astimezone(dt.timezone.utc) if t.tzinfo else t.replace(tzinfo=dt.timezone.utc)


def read_csv(path):
    with open(path, newline="") as f:
        return list(csv.DictReader(f))


# ---- merged PRs, kept across runs -------------------------------------------------------------------------------------

def git(repo, *args, stdin=None):
    return subprocess.run(["git", "-C", repo] + list(args), input=stdin, capture_output=True, text=True, check=True).stdout


def pr_row(repo, sha, when, title, num):
    """files and empty files of one squash-merged PR, read from the commit itself. None when the commit cannot be judged:
    a merge commit, or the oldest commit of a shallow checkout (its parent is missing, so its diff would be the whole tree)."""
    parents = git(repo, "rev-list", "--parents", "-n", "1", sha).split()[1:]
    if len(parents) != 1:
        return None
    raw = git(repo, "diff-tree", "-r", "--no-commit-id", "--no-renames", "--raw", sha).splitlines()
    touched = []
    for line in raw:
        meta, path = line.split("\t", 1)
        f = meta.split()
        status, new = f[4], f[3]
        if status == "D" or path == "BACKLOG.md" or f[1] == "160000":
            continue
        touched.append(new)
    sizes = git(repo, "cat-file", "--batch-check=%(objectsize)", stdin="".join(h + "\n" for h in touched)).split() if touched else []
    empty = sum(1 for z in sizes if z == "0")
    return {"pr": num, "merged_utc": when, "files": len(touched), "empty_files": empty, "title": title}


def sync_prs(repo=HERE, path=PRS, ref="HEAD"):
    """Add every merged PR on `ref` that the list does not have yet. Rows are never rewritten."""
    have = {}
    if os.path.exists(path):
        for r in read_csv(path):
            have[int(r["pr"])] = r
    out = git(repo, "log", "--format=%H%x1f%cI%x1f%s", ref)
    new = []
    for line in out.splitlines():
        sha, iso, subj = line.split("\x1f", 2)
        m = PR_RE.search(subj)
        if not m or int(m.group(1)) in have:
            continue
        r = pr_row(repo, sha, parse_ts(iso).isoformat(), subj[:m.start()].strip(), int(m.group(1)))
        if r:
            new.append(r)
    if new:
        rows = sorted(list(have.values()) + new, key=lambda r: int(r["pr"]))
        with open(path, "w", newline="") as f:
            w = csv.DictWriter(f, fieldnames=PR_COLS)
            w.writeheader()
            w.writerows(rows)
        have = {int(r["pr"]): r for r in rows}
    return have


def real_merge(r):
    return int(r["files"]) > 0 and int(r["empty_files"]) == 0


# ---- the scorecard ----------------------------------------------------------------------------------------------------

def week_start(t):
    d = t.date()
    return d - dt.timedelta(days=d.weekday())


def scorecard(log, prs, now):
    """One row per week (Monday to Sunday, UTC), newest first, from the first attempt to the week of `now`.
    A PR is merged when it is on main and real_merge() holds; a PR number the list does not have counts as not merged."""
    rows = [r for r in log if r["status"] in ATTEMPT]
    if not rows:
        return [], {}
    by = {}
    for r in rows:
        ws = week_start(parse_ts(r["ts_utc"]))
        w = by.setdefault(ws, {"attempts": 0, "opened": set(), "cost": 0.0})
        w["attempts"] += 1
        w["cost"] += float(r["cost_usd"] or 0)
        if r["pr"].strip():
            w["opened"].add(int(r["pr"]))
    first, last = min(by), week_start(now)
    weeks, merged_all = [], set()
    d = first
    while d <= last:
        w = by.get(d, {"attempts": 0, "opened": set(), "cost": 0.0})
        merged = {p for p in w["opened"] if p in prs and real_merge(prs[p])}
        merged_all |= merged
        weeks.append({"week_start": d.isoformat(), "attempts": w["attempts"], "opened": len(w["opened"]), "merged": len(merged),
                      "merged_share_pct": round(100.0 * len(merged) / w["attempts"]) if w["attempts"] else None,
                      "cost_usd": round(w["cost"], 2)})
        d += dt.timedelta(days=7)
    weeks.reverse()
    return weeks, merged_all


def totals(log, prs, merged_all, now, spend):
    spent = sum(float(r["cost_usd"] or 0) for r in log if r["status"] in ATTEMPT)
    last = max((parse_ts(prs[p]["merged_utc"]) for p in merged_all), default=None)
    every = [float(r["cost_usd"] or 0) for r in spend]
    return {
        "spent_usd": round(spent, 2),
        "attempts": sum(1 for r in log if r["status"] in ATTEMPT),
        "merged": len(merged_all),
        "cost_per_merged_usd": round(spent / len(merged_all), 2) if merged_all else None,
        "days_since_last_merge": (now.date() - last.date()).days if last else None,
        "last_merge_utc": last.isoformat() if last else None,
        "all_models_usd": round(sum(every), 2),
        "all_models_since": min((parse_ts(r["ts_utc"]).date().isoformat() for r in spend), default=None),
    }


# ---- what runs where --------------------------------------------------------------------------------------------------

def shift(h):
    """UTC hour to Singapore time; the second value is how many days the local date moves on."""
    return (h + SGT) % 24, (h + SGT) // 24


def schedule_of(crons):
    """Structured, so copy.json owns the sentence: {kind: every|hourly|daily|weekly|monthly|none, ...} in Singapore time."""
    if not crons:
        return {"kind": "none"}
    parsed = [c.split() for c in crons]
    mins = sorted({m for p in parsed for m in p[0].replace("*/", "").split(",")}, key=int)
    p = parsed[0]
    if p[0].startswith("*/") and p[1] == "*":
        return {"kind": "every", "minutes": int(p[0][2:])}
    if p[1] == "*":
        return {"kind": "hourly", "minutes": [int(m) for m in mins]}
    times, day_shift = [], 0
    for q in parsed:
        for h in q[1].split(","):
            lh, ds = shift(int(h))
            times.append("%02d:%02d" % (lh, int(q[0])))
            day_shift = ds
    times = sorted(set(times))
    if p[4] != "*":
        return {"kind": "weekly", "day": (int(p[4]) + day_shift) % 7, "times": times}
    if p[2] != "*":
        return {"kind": "monthly", "day": int(p[2]) + day_shift, "times": times}
    return {"kind": "daily", "times": times}


def workflows(wf_dir, runs):
    out = []
    for path in sorted(glob.glob(os.path.join(wf_dir, "*.yml"))):
        text = open(path).read()
        name = re.search(r"^name:\s*(.+?)\s*$", text, re.M)
        crons = re.findall(r"^\s*-\s*cron:\s*[\"']([^\"']+)[\"']", text, re.M)
        file = os.path.basename(path)
        run = (runs or {}).get(file)
        out.append({"file": file, "name": name.group(1).strip("\"'") if name else file, "schedule": schedule_of(crons),
                    "last_run": ({"status": run.get("status"), "conclusion": run.get("conclusion"), "run_utc": run.get("run_utc")}
                                 if run else None)})
    return out


# ---- the incident that quotes a number ---------------------------------------------------------------------------------

def stored_hours(path):
    seen = set()
    with open(path, newline="") as f:
        for r in csv.DictReader(f):
            seen.add(parse_ts(r["hour_utc"]))
    return sorted(seen)


def gap_after(hours, start):
    """The stored hour at or before `start`, the next stored hour, and the hours between them. None if `start` is past the data."""
    before = [h for h in hours if h <= start]
    after = [h for h in hours if h > start]
    if not before or not after:
        return None
    a, b = before[-1], after[0]
    return {"last_before_utc": a.isoformat(), "next_after_utc": b.isoformat(), "hours": int((b - a).total_seconds() // 3600)}


def build(now=None):
    now = now or dt.datetime.now(dt.timezone.utc).replace(microsecond=0)
    prs = sync_prs()
    log = read_csv(os.path.join(DATA, "aider_log.csv"))
    for r in log:
        if r["pr"].strip() and int(r["pr"]) not in prs:
            print("emit_machine_room: PR %s is in aider_log.csv but not in the merged list (open, closed, or merged outside this clone)"
                  % r["pr"], file=sys.stderr)
    weeks, merged_all = scorecard(log, prs, now)
    meters = {}
    try:
        meters = json.load(open(os.path.join(DATA, "machine_room_meters.json")))
    except (OSError, ValueError):
        pass
    with open(os.path.join(HERE, "copy.json")) as f:
        incidents = json.load(f).get("machineRoomPage", {}).get("incidents", {}).get("items", [])
    gaps = {}
    hours = stored_hours(os.path.join(DATA, "index_hourly.csv"))
    for it in incidents:
        if it.get("gapFromUtc"):
            gaps[it["id"]] = gap_after(hours, parse_ts(it["gapFromUtc"]))
    doc = {
        "computed_at": now.isoformat(),
        "totals": totals(log, prs, merged_all, now, read_csv(os.path.join(DATA, "agent_spend.csv"))),
        "weeks": weeks,
        "workflows": workflows(os.path.join(HERE, ".github", "workflows"), meters.get("workflow_runs")),
        "gaps": gaps,
        "files": ["data/aider_log.csv", "data/agent_spend.csv", "data/machine_room_prs.csv", "data/index_hourly.csv",
                  "data/machine_room_meters.json"],
    }
    with open(OUT, "w") as f:
        json.dump(doc, f, indent=1)
        f.write("\n")
    return doc


# ---- self-test: its own fixtures, nothing from the live files -----------------------------------------------------------

def self_test():
    import tempfile
    assert week_start(parse_ts("2026-10-25T23:00:00+00:00")) == dt.date(2026, 10, 19)  # a Sunday belongs to the week before
    assert week_start(parse_ts("2026-10-26T00:00:00+00:00")) == dt.date(2026, 10, 26)
    assert schedule_of(["7 5 * * *", "37 8 * * *"]) == {"kind": "daily", "times": ["13:07", "16:37"]}
    assert schedule_of(["11 3 * * 0"]) == {"kind": "weekly", "day": 0, "times": ["11:11"]}
    assert schedule_of(["23 3 1 * *"]) == {"kind": "monthly", "day": 1, "times": ["11:23"]}
    assert schedule_of(["11 18 * * 0"]) == {"kind": "weekly", "day": 1, "times": ["02:11"]}  # past midnight in Singapore: Monday
    assert schedule_of(["*/30 * * * *"]) == {"kind": "every", "minutes": 30}
    assert schedule_of(["17,47 * * * *"]) == {"kind": "hourly", "minutes": [17, 47]}
    assert schedule_of([]) == {"kind": "none"}
    prs = {1: {"merged_utc": "2026-10-27T10:00:00+00:00", "files": "3", "empty_files": "0"},
           2: {"merged_utc": "2026-10-28T10:00:00+00:00", "files": "3", "empty_files": "3"},  # merged, all empty: does not count
           3: {"merged_utc": "2026-10-20T10:00:00+00:00", "files": "1", "empty_files": "0"}}
    log = [{"ts_utc": "2026-10-20T09:00:00+00:00", "status": "built", "pr": "3", "cost_usd": "0.10"},
           {"ts_utc": "2026-10-27T09:00:00+00:00", "status": "built", "pr": "1", "cost_usd": "0.20"},
           {"ts_utc": "2026-10-28T09:00:00+00:00", "status": "built", "pr": "2", "cost_usd": "0.30"},
           {"ts_utc": "2026-10-28T11:00:00+00:00", "status": "failed", "pr": "", "cost_usd": "0.00"},
           {"ts_utc": "2026-10-28T12:00:00+00:00", "status": "nothing", "pr": "", "cost_usd": "0.00"}]
    now = parse_ts("2026-10-31T12:00:00+00:00")
    weeks, merged = scorecard(log, {int(k): {**v, "pr": k} for k, v in prs.items()}, now)
    assert [w["week_start"] for w in weeks] == ["2026-10-26", "2026-10-19"], weeks
    assert weeks[0] == {"week_start": "2026-10-26", "attempts": 3, "opened": 2, "merged": 1, "merged_share_pct": 33, "cost_usd": 0.5}, weeks[0]
    assert merged == {1, 3}
    t = totals(log, prs, merged, now, [{"ts_utc": "2026-10-07T00:00:00+00:00", "cost_usd": "1.5"}])
    assert t["spent_usd"] == 0.6 and t["merged"] == 2 and t["cost_per_merged_usd"] == 0.3 and t["days_since_last_merge"] == 4, t
    assert t["all_models_usd"] == 1.5 and t["all_models_since"] == "2026-10-07"
    hs = [parse_ts("2026-10-28T19:00:00+00:00"), parse_ts("2026-10-28T20:00:00+00:00"), parse_ts("2026-10-31T04:00:00+00:00")]
    assert gap_after(hs, parse_ts("2026-10-28T20:00:00+00:00"))["hours"] == 56
    assert gap_after(hs, parse_ts("2026-11-05T00:00:00+00:00")) is None
    # a real repo: a build that merged with empty files is not a real merge, and a deleted file is not "empty"
    with tempfile.TemporaryDirectory() as d:
        def g(*a):
            subprocess.run(["git", "-C", d, "-c", "user.email=t@t", "-c", "user.name=t"] + list(a), check=True, capture_output=True)
        g("init", "-q", "-b", "main")
        open(os.path.join(d, "base.txt"), "w").write("x\n"); open(os.path.join(d, "gone.txt"), "w").write("x\n")
        g("add", "."); g("commit", "-qm", "start")
        open(os.path.join(d, "a.py"), "w").write("")  # empty
        open(os.path.join(d, "b.csv"), "w").write("h\n")
        open(os.path.join(d, "BACKLOG.md"), "w").write("tick\n")
        g("add", "."); g("commit", "-qm", "build one (#10)")
        open(os.path.join(d, "c.py"), "w").write("print(1)\n"); os.remove(os.path.join(d, "gone.txt"))
        g("add", "-A"); g("commit", "-qm", "build two (#11)")
        csvp = os.path.join(d, "prs.csv")
        got = sync_prs(d, csvp)
        assert not real_merge(got[10]) and got[10]["files"] == 2 and got[10]["empty_files"] == 1, got[10]
        assert real_merge(got[11]) and got[11]["files"] == 1, got[11]
        assert sync_prs(d, csvp).keys() == got.keys()  # second run adds nothing
    print("emit_machine_room self-test ok")


def main():
    if "--self-test" in sys.argv:
        return self_test()
    doc = build()
    t = doc["totals"]
    print("emit_machine_room: %d weeks, %d merged builds, $%.2f spent, %d workflows" % (len(doc["weeks"]), t["merged"], t["spent_usd"], len(doc["workflows"])))
    return 0


if __name__ == "__main__":
    sys.exit(main())
