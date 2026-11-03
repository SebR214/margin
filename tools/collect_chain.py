#!/usr/bin/env python3
"""The collection chain's one rule book (SEB-436). No model, stdlib only.

collect.yml is a chain: each run starts the next. Until 2 Nov the run collected first and slept at the END of the job, so a run
that was slow or cancelled never started its successor, and the chain stayed dead until a GitHub cron fire (4 of 48 landed that
day). Now a run does this, in this order, before it collects anything:

  1. sleep until its own slot (the :05 or :35 UTC it was sent to),
  2. check that no other run is further ahead (so two chains never run side by side),
  3. start the next run, which goes to sleep until the slot after this one.

Whatever happens later in the run (a slow push, a cancel, a crash) the next link already exists.

A run's place in the chain is its slot, written in its run title ("collect slot=2026-11-03T10:35Z"). Runs are ordered by slot,
then by run id (the lower id wins a tie). A run stands down when any other live run comes after it in that order. A run that is
still finishing an earlier slot comes before it, so a slow predecessor never makes the next link stand down. A run started by
hand or by a restarter has no slot: its slot is the minute it started, and it waits a few seconds first so a sibling started in
the same moment is visible to both.

    python3 tools/collect_chain.py wake          # used by collect.yml, reads its inputs from the environment
    python3 tools/collect_chain.py next          # prints the slot after now
    python3 tools/collect_chain.py --self-test

Loud failure: a successor that could not be started after three tries writes dispatch_failed=true (proceed=true is written first,
so the run still collects its hour: the data is never held back by a dead dispatch) and the last step of collect.yml fails the run.
"""
import datetime as dt
import json
import os
import re
import subprocess
import sys
import time

STAMP = "%Y-%m-%dT%H:%MZ"
SLOT_MINUTES = (5, 35)
MIN_AHEAD = 5          # seconds: never send a successor into the slot we are standing in
SETTLE = 20            # seconds a run with no slot waits before it looks for siblings
ONE_SHOT = "collect one-shot"
TITLE = re.compile(r"slot=(\d{4}-\d\d-\d\dT\d\d:\d\dZ)")


def utc(s):
    return dt.datetime.strptime(s, STAMP).replace(tzinfo=dt.timezone.utc)


def next_slot(now):
    """The first :05 or :35 UTC that is more than MIN_AHEAD seconds after `now`."""
    base = now.replace(minute=0, second=0, microsecond=0)
    for h in (0, 1):
        for m in SLOT_MINUTES:
            t = base + dt.timedelta(hours=h, minutes=m)
            if (t - now).total_seconds() > MIN_AHEAD:
                return t
    raise AssertionError("unreachable")


def slot_text(t):
    return t.strftime(STAMP)


def slot_of(run):
    """The slot in a run's title, else the minute the run started."""
    m = TITLE.search(run.get("display_title") or "")
    if m:
        return m.group(1)
    started = run.get("run_started_at") or run.get("created_at") or ""
    return started[:16] + "Z" if len(started) >= 16 else ""


def key(run):
    """Order of runs in the chain: later slot first, then lower id."""
    return (slot_of(run), -int(run["id"]))


def stand_down(me, others):
    """True when a live run other than `me` comes after it. One-shot runs are not part of the chain."""
    mine = key(me)
    for r in others:
        if r["id"] == me["id"] or (r.get("display_title") or "") == ONE_SHOT:
            continue
        if key(r) > mine:
            return r
    return None


def seconds_to(slot, now):
    return max(0.0, (utc(slot) - now).total_seconds())


def gh(*args):
    r = subprocess.run(["gh"] + list(args), capture_output=True, text=True)
    if r.returncode:
        raise RuntimeError("gh %s: %s" % (" ".join(args[:3]), (r.stderr or r.stdout).strip()[:300]))
    return r.stdout


def live_runs(repo):
    out = []
    for status in ("in_progress", "queued"):
        doc = json.loads(gh("api", "repos/%s/actions/workflows/collect.yml/runs?status=%s&branch=main&per_page=100" % (repo, status)))
        out += doc.get("workflow_runs", [])
    return out


def output(name, value):
    path = os.environ.get("GITHUB_OUTPUT")
    if path:
        with open(path, "a") as f:
            f.write("%s=%s\n" % (name, value))


def start_next(slot, run=None, tries=3):
    """Start the next link, asking it to sleep to `slot`. Returns None, or the last error after `tries` attempts."""
    run = run or (lambda: gh("workflow", "run", "collect.yml", "--ref", "main", "-f", "chain=true", "-f", "slot=" + slot))
    err = None
    for i in range(tries):
        try:
            run()
            return None
        except Exception as e:
            err = e
            print("dispatch attempt %d failed: %s" % (i + 1, e))
            if i < tries - 1:
                time.sleep(10)
    return err


def wake():
    repo = os.environ["GH_REPO"]
    run_id = int(os.environ["RUN_ID"])
    event, chain, given = os.environ.get("EVENT_NAME", ""), os.environ.get("CHAIN", ""), os.environ.get("SLOT", "").strip()
    if event != "schedule" and chain != "true":
        print("one-shot (%s): collects its hour and stops, no chain" % event)
        output("proceed", "true")
        return 0
    now = dt.datetime.now(dt.timezone.utc)
    if given:
        mine = given
        wait = seconds_to(given, now)
        print("link for slot %s: sleeping %ds" % (given, wait))
        time.sleep(wait)
    else:
        mine = slot_text(now.replace(second=0, microsecond=0))
        print("no slot given (%s): starting a chain at %s, settling %ds" % (event, mine, SETTLE))
        time.sleep(SETTLE)
    me = {"id": run_id, "display_title": "collect slot=" + mine}
    ahead = stand_down(me, live_runs(repo))
    if ahead:
        print("chain alive: run %s (%s) is ahead of this one, standing down" % (ahead["id"], slot_of(ahead)))
        output("proceed", "false")
        return 0
    output("proceed", "true")
    nxt = slot_text(next_slot(dt.datetime.now(dt.timezone.utc)))
    err = start_next(nxt)
    if err:
        # this run still collects its hour; the last step of the job turns the run red on this output
        print("::error::could not start the next link after 3 tries (%s). This run collects its hour, the box and the cron restart the chain." % err)
        output("dispatch_failed", "true")
        return 0
    print("next link started for slot %s" % nxt)
    return 0


def self_test():
    def t(s):
        return utc(s)

    # the next slot
    assert slot_text(next_slot(t("2026-11-03T10:00Z"))) == "2026-11-03T10:05Z"
    assert slot_text(next_slot(t("2026-11-03T10:05Z") + dt.timedelta(seconds=8))) == "2026-11-03T10:35Z"   # woke at its slot
    assert slot_text(next_slot(t("2026-11-03T10:05Z"))) == "2026-11-03T10:35Z"                              # never into the slot just left
    assert slot_text(next_slot(t("2026-11-03T10:34Z") + dt.timedelta(seconds=57))) == "2026-11-03T11:05Z"   # 3s ahead is too close
    assert slot_text(next_slot(t("2026-11-03T10:36Z"))) == "2026-11-03T11:05Z"
    assert slot_text(next_slot(t("2026-11-03T23:50Z"))) == "2026-11-04T00:05Z"
    assert seconds_to("2026-11-03T10:35Z", t("2026-11-03T10:05Z")) == 1800 and seconds_to("2026-11-03T10:35Z", t("2026-11-03T10:40Z")) == 0

    # who stands down
    def run(i, slot=None, started="2026-11-03T10:05:12Z", title=None):
        return {"id": i, "display_title": title or ("collect slot=" + slot if slot else "collect"), "run_started_at": started}
    me = run(200, "2026-11-03T10:35Z")
    assert stand_down(me, [me]) is None, "a run never stands down for itself"
    assert stand_down(me, [me, run(190, "2026-11-03T10:05Z")]) is None, "a slow predecessor is behind this run"
    assert stand_down(me, [me, run(190, "2026-11-03T10:05Z"), run(210, "2026-11-03T11:05Z")]), "a successor is ahead"
    assert stand_down(me, [me, run(199, "2026-11-03T10:35Z")]), "the same slot: the lower id wins"
    assert stand_down(me, [me, run(201, "2026-11-03T10:35Z")]) is None
    assert stand_down(me, [me, run(300, title=ONE_SHOT, started="2026-11-03T11:30:00Z")]) is None, "a one-shot is not the chain"
    # a run with no slot sorts by the minute it started
    assert slot_of(run(5, started="2026-11-03T10:17:40Z")) == "2026-11-03T10:17Z"
    assert stand_down(run(6, "2026-11-03T10:47Z"), [run(5, started="2026-11-03T10:17:40Z")]) is None
    # a restarter that finds the sleeping successor of a live chain stands down
    restarter = run(400, "2026-11-03T10:47Z")
    assert stand_down(restarter, [restarter, run(390, "2026-11-03T10:35Z"), run(391, "2026-11-03T11:05Z")])
    # a chain whose link died after starting its successor is not a dead chain
    assert stand_down(restarter, [restarter, run(391, "2026-11-03T11:05Z")])
    # and one whose last link is old and still running (no successor) is restarted
    assert stand_down(restarter, [restarter, run(390, "2026-11-03T10:35Z")]) is None

    # two restarters in the same moment: exactly one goes on, whatever order they look in
    for slots in (("2026-11-03T10:47Z", "2026-11-03T10:47Z"), ("2026-11-03T10:47Z", "2026-11-03T10:48Z")):
        a, b = run(500, slots[0]), run(501, slots[1])
        alive = [a, b]
        goes = [r for r in (a, b) if stand_down(r, alive) is None]
        assert len(goes) == 1, (slots, goes)

    # a long simulated day: every link wakes, starts the next, then maybe dies. Never a gap, never two chains.
    live, nid, slot, ever = [], 1, "2026-11-03T00:05Z", 0
    live.append(run(nid, slot))
    for _ in range(48):
        cur = [r for r in live if slot_of(r) == slot][0]
        assert stand_down(cur, live) is None, "the live link must not stand down"
        slot = slot_text(next_slot(utc(slot) + dt.timedelta(seconds=8)))
        nid += 1
        live.append(run(nid, slot))
        live = [r for r in live if slot_of(r) >= slot_text(utc(slot) - dt.timedelta(minutes=30))]   # old links finish or die
        ever = max(ever, len([r for r in live if slot_of(r) >= slot]))
    assert ever == 1 and slot == "2026-11-04T00:05Z", (ever, slot)

    # a dispatch that fails twice and then works is retried; one that never works is reported
    calls = []

    def flaky():
        calls.append(1)
        if len(calls) < 3:
            raise RuntimeError("HTTP 504")
    real_sleep, time.sleep = time.sleep, lambda s: None
    try:
        assert start_next("x", flaky) is None and len(calls) == 3

        def dead():
            raise RuntimeError("HTTP 502")
        assert isinstance(start_next("x", dead), RuntimeError)
    finally:
        time.sleep = real_sleep

    # wake(), end to end with a stubbed gh: the normal path, standing down, a dead dispatch, a one-shot
    import tempfile
    global gh
    real_gh, real_sleep = gh, time.sleep
    time.sleep = lambda s: None
    try:
        for case in ("normal", "ahead", "dead", "oneshot"):
            sent, out = [], tempfile.NamedTemporaryFile("r+", delete=False)
            now = dt.datetime.now(dt.timezone.utc)
            slot = slot_text(now - dt.timedelta(minutes=1))      # a slot already reached: no sleep
            ahead = {"id": 9, "display_title": "collect slot=" + slot_text(now + dt.timedelta(minutes=30)), "run_started_at": ""}
            old = {"id": 3, "display_title": "collect slot=" + slot_text(now - dt.timedelta(minutes=31)), "run_started_at": ""}

            def fake_gh(*args, _case=case):
                if args[0] == "api":
                    runs = [old] if "status=in_progress" in args[1] else []
                    if _case == "ahead" and "status=queued" in args[1]:
                        runs = [ahead]
                    return json.dumps({"workflow_runs": runs})
                sent.append(args)
                if _case == "dead":
                    raise RuntimeError("HTTP 502")
                return ""
            gh = fake_gh
            os.environ.update({"GH_REPO": "o/r", "RUN_ID": "5", "SLOT": slot, "GITHUB_OUTPUT": out.name,
                               "EVENT_NAME": "workflow_dispatch", "CHAIN": "false" if case == "oneshot" else "true"})
            assert wake() == 0
            got = open(out.name).read()
            os.unlink(out.name)
            if case == "normal":
                assert "proceed=true" in got and len(sent) == 1 and sent[0][-1].startswith("slot=20") and "chain=true" in sent[0], (got, sent)
                assert sent[0][-1] == "slot=" + slot_text(next_slot(dt.datetime.now(dt.timezone.utc))), sent
            elif case == "ahead":
                assert "proceed=false" in got and not sent, (got, sent)
            elif case == "dead":
                assert "proceed=true" in got and "dispatch_failed=true" in got and len(sent) == 3, (got, sent)
            else:
                assert "proceed=true" in got and not sent, (got, sent)
    finally:
        gh, time.sleep = real_gh, real_sleep
    print("collect_chain self-test: ok")
    return 0


def main(argv):
    if "--self-test" in argv:
        return self_test()
    if len(argv) > 1 and argv[1] == "wake":
        return wake()
    if len(argv) > 1 and argv[1] == "next":
        print(slot_text(next_slot(dt.datetime.now(dt.timezone.utc))))
        return 0
    sys.exit(__doc__)


if __name__ == "__main__":
    sys.exit(main(sys.argv))
