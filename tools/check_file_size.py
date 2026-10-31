#!/usr/bin/env python3
"""Fail before the commit if a file is too big for GitHub (SEB-301, 31 Oct). No model.

GitHub refuses a push with a file over 100 MB. On 28 Oct data/p2p_ads_sellers.csv reached 99.6 MB, the next append broke
every "Commit samples" step, and nothing reached main for the hours after. This runs right before that step.

    python3 tools/check_file_size.py              # every tracked file and every new file git would add
    python3 tools/check_file_size.py --self-test

  - every file over WARN_BYTES (40 MB) is listed, with its size, so a table is split before it is a problem;
  - any file over FAIL_BYTES (80 MB) fails the run (exit 1), 20 MB before GitHub would refuse it;
  - FROZEN files are closed tables that were over the line or close to it when they were split into one file a day
    (tools/daily_csv.py). They are listed, not failed, but they must stay byte for byte the size they were closed at: a
    collector that appends to one again fails the run.
"""
import os
import subprocess
import sys

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
MB = 1_000_000
WARN_BYTES = 40 * MB
FAIL_BYTES = 80 * MB
# Closed tables, one file a day after them (tools/daily_csv.py). Never rewritten, so the size never changes. The two ads tables were
# closed on 28 Oct, the day the push failed; p2p_offers.csv on 31 Oct, at 46 MB.
FROZEN = {"data/p2p_ads_sellers.csv": 104_424_335, "data/p2p_ads.csv": 69_397_135, "data/p2p_offers.csv": 46_393_452}


def git_files(root=HERE):
    out = subprocess.run(["git", "ls-files", "-z", "--cached", "--others", "--exclude-standard"], cwd=root,
                         capture_output=True, check=True).stdout
    return sorted({p for p in out.decode("utf-8").split("\0") if p})


def judge(sizes, frozen=FROZEN):
    """sizes: {path: bytes}. Returns (listed, failures): listed = [(path, bytes)] over WARN_BYTES, biggest first."""
    listed = sorted(((p, n) for p, n in sizes.items() if n > WARN_BYTES), key=lambda x: -x[1])
    failures = []
    for p, n in listed:
        if p in frozen:
            if n != frozen[p]:
                failures.append("%s is a closed table (%d bytes) and now has %d: something appended to it" % (p, frozen[p], n))
        elif n > FAIL_BYTES:
            failures.append("%s is %.1f MB, over the %d MB limit (GitHub refuses a file over 100 MB)" % (p, n / MB, FAIL_BYTES // MB))
    for p, n in frozen.items():
        if p in sizes and sizes[p] != n and sizes[p] <= WARN_BYTES:
            failures.append("%s is a closed table (%d bytes) and now has %d: something rewrote it" % (p, n, sizes[p]))
    return listed, failures


def main(root=HERE):
    sizes = {}
    for p in git_files(root):
        fp = os.path.join(root, p)
        if os.path.isfile(fp):
            sizes[p] = os.path.getsize(fp)
    listed, failures = judge(sizes)
    for p, n in listed:
        print("  %6.1f MB  %s%s" % (n / MB, p, "  (closed)" if p in FROZEN else ""))
    if not listed:
        print("  no file over %d MB" % (WARN_BYTES // MB))
    for f in failures:
        print("  [error] " + f, file=sys.stderr)
    if failures:
        print("\n  [error] %d file(s) too big for the repository; split them into one file a day (tools/daily_csv.py) before "
              "the next commit" % len(failures), file=sys.stderr)
        return 1
    print("  file sizes ok (limit %d MB)" % (FAIL_BYTES // MB))
    return 0


def self_test():
    mb = lambda n: int(n * MB)
    fr = {"data/closed.csv": mb(104)}
    listed, bad = judge({"a.csv": mb(10), "b.csv": mb(41), "c.csv": mb(79.9)}, fr)
    assert [p for p, _ in listed] == ["c.csv", "b.csv"] and not bad, (listed, bad)
    listed, bad = judge({"a.csv": mb(10), "big.csv": mb(80.5), "ok.csv": mb(60)}, fr)
    assert len(bad) == 1 and "big.csv" in bad[0] and "80 MB" in bad[0], bad
    listed, bad = judge({"data/closed.csv": mb(104)}, fr)
    assert listed == [("data/closed.csv", mb(104))] and not bad, "a closed table at its closed size is listed, not failed"
    listed, bad = judge({"data/closed.csv": mb(104) + 1}, fr)
    assert len(bad) == 1 and "appended" in bad[0], bad
    listed, bad = judge({"data/closed.csv": mb(10)}, fr)
    assert len(bad) == 1 and "rewrote" in bad[0], bad
    listed, bad = judge({}, fr)
    assert listed == [] and not bad, "a closed table that is absent is not this check's business"
    assert FROZEN["data/p2p_ads_sellers.csv"] > FAIL_BYTES and FROZEN["data/p2p_ads.csv"] < FAIL_BYTES, "both kinds are covered"
    import tempfile
    with tempfile.TemporaryDirectory() as d:
        subprocess.run(["git", "init", "-q"], cwd=d, check=True)
        with open(os.path.join(d, "small.csv"), "w") as f:
            f.write("a\n")
        assert git_files(d) == ["small.csv"], git_files(d)
        assert main(d) == 0
    print("check_file_size self-test: ok")
    return 0


if __name__ == "__main__":
    sys.exit(self_test() if "--self-test" in sys.argv else main())
