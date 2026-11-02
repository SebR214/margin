#!/usr/bin/env python3
"""The email alarm (SEB-301, 2 Nov). No model, stdlib only.

GitHub's own failure email never reached Seb: it goes to whoever triggered a run, and the watchdogs run themselves
(github-actions[bot] dispatches the next run), so a red run emailed nobody. Comments on SEB-301 are read by no one at night.

So each watchdog run pings a check on healthchecks.io: "up" when all is well, "down" (the /fail endpoint) with the reason when
not. healthchecks.io emails Seb when a check goes down, once, and again when it is back. It also emails when the pings stop
coming at all, so a dead chain, a stopped schedule or a GitHub Actions outage is caught too: the case no workflow can report.

    python3 tools/alert_ping.py HC_PING_WATCHDOG down "Audits: number country:SGD has not matched its raw rows for 3 runs."
    python3 tools/alert_ping.py HC_PING_COLLECTOR up
    python3 tools/alert_ping.py --self-test

The first argument names the environment variable that holds the check's ping URL (a repository secret). Loud failure: a
missing URL or a ping that fails three times exits 1, so an alarm that cannot ring turns its run red.
"""
import os
import sys
import time
import urllib.request

TRIES = 3


def target(url, state):
    url = url.strip().rstrip("/")
    return url + "/fail" if state == "down" else url


def ping(url, state, what, send=None, wait=5):
    """Send one ping, retrying a failed one. Returns None, or the last error after TRIES attempts."""
    send = send or _send
    body = (" ".join((what or "").split()) or ("all checks pass" if state == "up" else "see the run")).encode()[:10000]
    err = None
    for i in range(TRIES):
        try:
            send(target(url, state), body)
            return None
        except Exception as e:  # any failure to reach healthchecks.io is retried, then reported
            err = e
            if i < TRIES - 1:
                time.sleep(wait)
    return err


def _send(url, body):
    req = urllib.request.Request(url, data=body, method="POST", headers={"User-Agent": "margin-watchdog"})
    with urllib.request.urlopen(req, timeout=15) as r:
        if r.status != 200:
            raise RuntimeError("HTTP %d" % r.status)


def main(argv):
    if "--self-test" in argv:
        return self_test()
    if len(argv) < 3 or argv[2] not in ("up", "down"):
        sys.exit(__doc__)
    name, state, what = argv[1], argv[2], (argv[3] if len(argv) > 3 else "")
    url = os.environ.get(name, "").strip()
    if not url:
        print("::error::%s is not set, so no email can be sent. Add the healthchecks.io ping URL as the repository secret %s."
              % (name, name), file=sys.stderr)
        return 1
    err = ping(url, state, what)
    if err:
        print("::error::could not reach healthchecks.io after %d tries (%s), so no email was sent" % (TRIES, err), file=sys.stderr)
        return 1
    print("pinged %s: %s%s" % (name, state, (" (" + what + ")") if what else ""))
    return 0


def self_test():
    sent = []
    assert ping("https://hc-ping.com/abc/", "down", "Audits:  SGD\n off", lambda u, b: sent.append((u, b)), wait=0) is None
    assert sent == [("https://hc-ping.com/abc/fail", b"Audits: SGD off")], sent
    sent.clear()
    assert ping("https://hc-ping.com/abc", "up", "", lambda u, b: sent.append((u, b)), wait=0) is None
    assert sent == [("https://hc-ping.com/abc", b"all checks pass")], sent
    calls = []

    def flaky(u, b):
        calls.append(u)
        if len(calls) < 3:
            raise OSError("timed out")
    assert ping("https://hc-ping.com/abc", "down", "x", flaky, wait=0) is None and len(calls) == 3, "a ping is retried"

    def dead(u, b):
        raise OSError("refused")
    assert isinstance(ping("https://hc-ping.com/abc", "up", "", dead, wait=0), OSError), "three failures are reported"
    os.environ.pop("HC_PING_SELFTEST_UNSET", None)
    assert main(["x", "HC_PING_SELFTEST_UNSET", "down", "x"]) == 1, "a missing URL fails loudly"
    print("alert_ping self-test: ok")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
