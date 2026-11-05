#!/usr/bin/env python3
"""SEB-437: no event page is built for an event outside our hourly record. No model, stdlib only.

Our hourly record starts on the first day of data/heatmap_daily.json. An event before that day was found later, in a backtest of
history: it is a row in the history table (research-breaks.html) and has no page. This check runs tools/publish_events.py's own
selection over the stored candidates and fails if an event dated before the first day would still get a page, or if the event
page and the events list could open one (their scripts must send such an id to the table).

    python3 tools/check_event_pages.py [--self-test]
"""
import os
import sys

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(HERE, "tools"))
import publish_events as pe  # noqa: E402


def problems(events, start, event_js, list_js):
    out = ["%s (%s) is before our hourly record (%s) and would get a page" % (e["id"], e["date"], start) for e in events if e["date"] < start]
    if "research-breaks.html" not in event_js or "own_start" not in event_js:
        out.append("js/event.js does not send an event before our hourly record to research-breaks.html")
    if "own_start" not in list_js and "ownStart" not in list_js:
        out.append("js/events_page.js does not drop events before our hourly record")
    return out


def main():
    srcs = [(pe.read(f), d, label) for f, d, label in pe.SOURCES]
    start = pe.own_start()
    inside, _ = pe.split_record(pe.select(srcs), start)
    rd = lambda p: open(os.path.join(HERE, p), encoding="utf-8").read()
    got = problems(inside, start, rd("js/event.js"), rd("js/events_page.js"))
    for g in got:
        print("FAIL:", g)
    if not got:
        print("event pages ok: %d event(s), all inside our hourly record (from %s)" % (len(inside), start))
    return 1 if got else 0


def self_test():
    ok_js = "x own_start research-breaks.html", "x ownStart"
    assert not problems([{"id": "A", "date": "2026-08-10"}], "2026-08-10", *ok_js)
    assert problems([{"id": "B", "date": "2026-08-09"}], "2026-08-10", *ok_js)
    assert problems([], "2026-08-10", "nothing", ok_js[1]) and problems([], "2026-08-10", ok_js[0], "nothing")
    print("self-test ok")
    return 0


if __name__ == "__main__":
    sys.exit(self_test() if "--self-test" in sys.argv else main())
