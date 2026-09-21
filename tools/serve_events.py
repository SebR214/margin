#!/usr/bin/env python3
"""SEB-58/M1: the machine room's event feed -- SEB-42's SSE endpoint (B3),
extended to stream three more kinds of real event, all still built by
tailing or diffing files something else already writes. No new collector
instrumentation, no new credentials: everything below reads a file already
on disk, or shells out to the local `git log` (no network, no token).

New kinds, alongside the three B3 already streams (`collection_pass`,
`call`, `commission_step`):

  collector_pass    one `phase: start` and one `phase: complete` bracketing
                     a batch of `collector_source` events, keyed to
                     data/index_latest.json's own `computed_at` -- the only
                     timestamp this process can see for an index rebuild, so
                     both ends of the bracket carry it rather than guessing
                     when the process actually began.
  collector_source   one per country whose priced/withheld state moved in
                     data/index_latest.json's `countries` (priced) or
                     `withheld` (unpriced) lists: ccy, source kind, evidence
                     count, priced or withheld with its plain-language
                     reason.
  linear             one per line agents/linear.py's `_log_activity()`
                     appends when a builder/reviewer/product pass changes an
                     issue's state or posts a comment -- the only local
                     record that a Linear mutation happened, since that
                     script talks straight to the API and keeps nothing
                     else.
  commit             one per new commit `git log` finds on this checkout's
                     current branch -- sha, author, message, and the PR
                     number when the message ends `(#123)`, which is how a
                     squash-merge names it. This is also how a merged pull
                     request appears in the feed; nothing here shows a pull
                     request the moment it is OPENED, because that needs the
                     GitHub API, and handing this publicly-reachable process
                     a GitHub credential is a bigger hole than the gap it
                     would close -- see SEB-73, which is actively asking
                     whether a GitHub credential on this box has already
                     been used to post as Sebastian. Left for M2 to source
                     another way (a periodic sidecar, not this stream).
  loop_health        one per new line appended to a role's own
                     /var/log/margin/<role>.jsonl (agents/run.sh's
                     `record()`), carrying that role's pass count for today;
                     plus one whenever a role crosses agents/watchdog.sh's
                     own silence threshold (SILENT_AFTER, 7200s) in either
                     direction, so a stopped loop is shown stopped rather
                     than just going quiet.

Replay: the events this SERVER PROCESS has actually published, sent to a
client the moment it connects, before it starts receiving live events.
Nothing older than server start is replayed -- backfilling from the
beginning of a log file that predates this process would dump old lines
under today's timestamp, which is exactly the resampled event the issue
rules out.

Held per KIND, not in one shared deque (KIND_HISTORY_MAX below) -- one
hourly collector_pass alone emits ~60 collector_source events, one per
tracked country, and a single shared "last 50" bound meant that one pass
silently evicted every commit, review and Linear event a visitor was
supposed to see. Each kind now keeps its own bounded history (generous for
the low-volume kinds that matter most, just enough for collector_source to
hold one full pass), merged back into true chronological order at replay
time by a monotonic sequence number stamped at publish.

One background thread polls everything and publishes to those per-kind
deques and to every connected client's own queue; each HTTP connection is
otherwise just a subscriber, under the same MAX_CONNECTIONS cap as before.

Stdlib only.
"""

import collections
import datetime
import http.server
import itertools
import json
import os
import queue
import re
import socketserver
import subprocess
import sys
import threading
import time

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
DATA = os.path.join(ROOT, "data")
AGENT_STATUS_PATH = os.path.join(DATA, "agent_status.json")
INDEX_LATEST_PATH = os.path.join(DATA, "index_latest.json")
CALL_LOG_PATH = os.environ.get(
    "SERVE_EVENTS_LOG_PATH", "/var/log/margin/serve.systemd.log")
COMMISSION_LOG_PATH = os.environ.get(
    "COMMISSION_EVENTS_LOG_PATH", "/var/log/margin/commission.systemd.log")
LINEAR_ACTIVITY_LOG_PATH = os.environ.get(
    "LINEAR_ACTIVITY_LOG_PATH", "/var/log/margin/linear_activity.jsonl")
LOOP_LOG_DIR = os.environ.get("LOOP_LOG_DIR", "/var/log/margin")

LOOP_ROLES = ("builder", "reviewer", "product")
# Same number agents/watchdog.sh pages on -- "stopped" here has to mean the
# same thing it means there, or the two disagree about the same loop.
SILENT_AFTER = 7200

HOST, PORT = "127.0.0.1", 8903

# A code-enforced ceiling, not a load-tested one -- see the SEB-42 PR for the
# arithmetic (20 held threads, worst case ~8MB stack each = 160MB, against a
# measured 2.4GB of available RAM on this box, alongside the four existing
# listeners).
MAX_CONNECTIONS = 20

POLL_SECONDS = 5

# SEB-58 means "replay the last 50 events" as "a new visitor should see
# what just happened" -- one shared deque across every kind broke that
# promise the first time it was actually load-bearing: one hourly
# collector_pass alone emits ~60 collector_source events (one per tracked
# country), so a single pass evicted EVERY commit, review, and Linear event
# this whole page exists to show -- hours of real work vanished from a new
# visitor's replay the moment the clock ticked over, not because nothing
# happened, but because the loud, frequent kind drowned out the sparse,
# important ones in one shared bound. A page whose whole point is proving
# the work happened cannot let its own busiest event type erase the record
# of that work.
#
# Fix: one bounded deque per kind, sized to what that kind actually needs --
# generous for the low-volume kinds that matter most (commit, linear),
# just enough for collector_source to hold one full pass. A monotonic
# sequence number stamped at publish time lets replay merge every kind's
# buffer back into one true chronological order.
KIND_HISTORY_MAX = {
    "collector_source": 70,   # one hourly pass, ~60 countries, with slack
    "collection_pass":  20,
    "collector_pass":   10,
    "loop_health":      25,
    "linear":           30,
    "commit":           30,
    "call":             20,
    "commission_step":  20,
}
DEFAULT_KIND_HISTORY_MAX = 20

_slots = threading.Semaphore(MAX_CONNECTIONS)
_seq = itertools.count()
_history_by_kind = {}
_history_lock = threading.Lock()
_subscribers = set()
_subscribers_lock = threading.Lock()


def _publish(event):
    kind = event.get("kind", "")
    seq = next(_seq)
    with _history_lock:
        buf = _history_by_kind.get(kind)
        if buf is None:
            buf = collections.deque(maxlen=KIND_HISTORY_MAX.get(kind, DEFAULT_KIND_HISTORY_MAX))
            _history_by_kind[kind] = buf
        buf.append((seq, event))
    with _subscribers_lock:
        subs = list(_subscribers)
    for q in subs:
        try:
            q.put_nowait(event)
        except queue.Full:
            # A subscriber too slow to keep up misses a live event, but the
            # replay buffer still catches it up on its next poll -- dropping
            # here beats blocking the one shared poller on one slow reader.
            pass


def _replay_backlog():
    """Every kind's retained history, merged back into one chronological
    order by the sequence number each event was published with.
    """
    with _history_lock:
        items = [pair for buf in _history_by_kind.values() for pair in buf]
    items.sort(key=lambda pair: pair[0])
    return [event for _, event in items]


def _iso_now():
    return datetime.datetime.now(datetime.timezone.utc) \
                             .replace(microsecond=0).isoformat()


def _read_json(path):
    try:
        with open(path) as f:
            return json.load(f)
    except (OSError, ValueError):
        return None


def _read_agent_status():
    return _read_json(AGENT_STATUS_PATH)


def _collection_pass_events(seen):
    """Yield one event per source whose last_ok_utc or broken flag moved.

    `seen` is a dict this call mutates in place, keyed by (file, name) ->
    (last_ok_utc, broken) last reported on this connection. A freshly opened
    stream starts with nothing seen, so its first poll reports the state of
    every source as a change -- "here is what you missed", which for a
    stream that just opened is everything there is.
    """
    status = _read_agent_status()
    if status is None:
        return
    for src in status.get("sources", []):
        key = (src.get("file"), src.get("name"))
        marker = (src.get("last_ok_utc"), src.get("broken"))
        if seen.get(key) == marker:
            continue
        seen[key] = marker
        yield {
            "kind": "collection_pass",
            "file": src.get("file"),
            "name": src.get("name"),
            "ok": not src.get("broken"),
            "last_ok_utc": src.get("last_ok_utc"),
        }


def _collector_pass_events(state):
    """Diff data/index_latest.json against the last snapshot this process
    saw, bracketing any change with a `collector_pass` start/complete pair.

    `state` carries `computed_at` (the top-level timestamp last seen) and
    `countries` (ccy -> the marker last reported for that country). The
    first call ever seeds both from the file's CURRENT contents without
    yielding anything -- a restart shouldn't replay the whole index as if it
    had just happened, the same reasoning `_seed_tail_state` applies to log
    files below.
    """
    doc = _read_json(INDEX_LATEST_PATH)
    if doc is None:
        return
    computed_at = doc.get("computed_at")
    if computed_at == state.get("computed_at"):
        return
    seeding = "computed_at" not in state
    state["computed_at"] = computed_at

    rows = []
    for c in doc.get("countries", []):
        rows.append((c.get("ccy"), {
            "ccy": c.get("ccy"), "country": c.get("country"),
            "source_kind": c.get("source_class"),
            "evidence_count": c.get("n_sources"), "priced": True,
        }))
    for w in doc.get("withheld", []):
        rows.append((w.get("ccy"), {
            "ccy": w.get("ccy"), "country": w.get("country"),
            "source_kind": None, "evidence_count": w.get("n_sources"),
            "priced": False, "reason": w.get("reason"),
        }))

    changed = []
    seen_now = {}
    for ccy, payload in rows:
        marker = json.dumps(payload, sort_keys=True)
        seen_now[ccy] = marker
        if state.get("countries", {}).get(ccy) != marker:
            changed.append(payload)
    state["countries"] = seen_now

    if seeding or not changed:
        return

    yield {"kind": "collector_pass", "phase": "start", "ts": computed_at}
    for payload in changed:
        yield dict(payload, kind="collector_source", ts=computed_at)
    yield {"kind": "collector_pass", "phase": "complete", "ts": computed_at}


def _parse_call_event(line):
    if not line.startswith("call_event tool="):
        return None
    fields = {}
    for part in line.rstrip("\n")[len("call_event "):].split(" "):
        if "=" in part:
            k, v = part.split("=", 1)
            fields[k] = v
    return {
        "kind": "call",
        "tool": fields.get("tool") or None,
        "country": fields.get("country") or None,
    }


def _seed_tail_state(path):
    """A tail cursor pre-set to end-of-file, so the first poll after this
    process starts reports only what happens from here on -- not the whole
    history of a log file that predates it.
    """
    try:
        st = os.stat(path)
        return {"inode": st.st_ino, "offset": st.st_size}
    except OSError:
        return {}


def _tail_new_lines(path, state):
    """Yield each line appended to `path` since the last call.

    `state` carries the file's inode and the byte offset already read, so a
    rotated log (Caddy and systemd both roll files) is noticed -- the offset
    resets to zero rather than seeking past the end of a now-smaller file.
    Shared by every event kind that comes from tailing a log file.
    """
    try:
        st = os.stat(path)
    except OSError:
        return
    if state.get("inode") != st.st_ino or state.get("offset", 0) > st.st_size:
        state["inode"] = st.st_ino
        state["offset"] = 0
    with open(path) as f:
        f.seek(state.get("offset", 0))
        for line in f:
            yield line
        state["offset"] = f.tell()


def _call_events(state):
    """Yield one `call` event per new `call_event tool=... country=...` line."""
    for line in _tail_new_lines(CALL_LOG_PATH, state):
        event = _parse_call_event(line)
        if event is not None:
            yield event


def _parse_commission_step_event(line):
    if not line.startswith("commission_step "):
        return None
    try:
        record = json.loads(line[len("commission_step "):])
    except ValueError:
        return None
    if record.get("kind") != "commission_step" or not record.get("request_id"):
        return None
    return record


def _commission_step_events(state):
    """Yield one `commission_step` event per new line probe_source.py wrote.

    Unlike the call tail, this is one JSON object per line rather than
    space-separated `k=v` pairs -- a probe's `check` line and a rejection
    reason are free text that can contain spaces, which the `k=v` shape
    would silently truncate.
    """
    for line in _tail_new_lines(COMMISSION_LOG_PATH, state):
        event = _parse_commission_step_event(line)
        if event is not None:
            yield event


def _parse_linear_activity_event(line):
    if not line.startswith("linear_activity "):
        return None
    try:
        record = json.loads(line[len("linear_activity "):])
    except ValueError:
        return None
    if record.get("kind") not in ("transition", "comment") or not record.get("ident"):
        return None
    event = dict(record)
    event["event"] = event.pop("kind")
    event["kind"] = "linear"
    return event


def _linear_activity_events(state):
    """Yield one `linear` event per line agents/linear.py's `_log_activity()`
    appended -- a builder/reviewer/product transition or comment, written by
    the loop that made it, at the moment it made it.
    """
    for line in _tail_new_lines(LINEAR_ACTIVITY_LOG_PATH, state):
        event = _parse_linear_activity_event(line)
        if event is not None:
            yield event


def _commit_events(state):
    """Yield one `commit` event per new commit on this checkout's current
    branch, oldest first -- sha, author, message, and the PR number a
    squash-merge leaves at the end of its message in parens, e.g.
    "SEB-57 R2: the receipt replay (#113)".

    Local `git log` only: no GitHub API, no credential. This checkout is
    kept in sync with origin/main by margin-pull.timer, the same mechanism
    the REST API already trusts for "today's numbers".
    """
    args = ["git", "-C", ROOT, "log", "--format=%H%x1f%aI%x1f%an%x1f%s"]
    args.append("%s..HEAD" % state["head"] if "head" in state else "-1")
    try:
        out = subprocess.run(args, capture_output=True, text=True, timeout=10)
    except OSError:
        return
    if out.returncode != 0 or not out.stdout.strip():
        return
    lines = out.stdout.strip("\n").split("\n")
    seeding = "head" not in state
    state["head"] = lines[0].split("\x1f", 1)[0]
    if seeding:
        return
    for line in reversed(lines):
        sha, iso, author, subject = line.split("\x1f", 3)
        m = re.search(r"\(#(\d+)\)\s*$", subject)
        yield {
            "kind": "commit", "sha": sha[:9], "author": author,
            "message": subject, "ts": iso,
            "pr_number": int(m.group(1)) if m else None,
        }


def _is_stopped(last_finished_utc, now_ts):
    if not last_finished_utc:
        return True  # a role that has never recorded a pass reads as stopped
    try:
        last_s = datetime.datetime.fromisoformat(last_finished_utc).timestamp()
    except ValueError:
        return True
    return (now_ts - last_s) > SILENT_AFTER


def _seed_loop_role(path, st):
    """Read a role's whole jsonl once at startup so `passes_today` is right
    from the first live event, then seed the tail cursor to end-of-file so
    future polls only see genuinely new passes.
    """
    st.update(_seed_tail_state(path))
    today = datetime.datetime.now(datetime.timezone.utc).date().isoformat()
    count, last = 0, None
    try:
        with open(path) as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    rec = json.loads(line)
                except ValueError:
                    continue
                last = rec
                if (rec.get("finished_utc") or "")[:10] == today:
                    count += 1
    except OSError:
        pass
    st["today"] = today
    st["passes_today"] = count
    st["last_finished_utc"] = last.get("finished_utc") if last else None


def _loop_health_events(states):
    now_ts = time.time()
    for role in LOOP_ROLES:
        path = os.path.join(LOOP_LOG_DIR, role + ".jsonl")
        st = states.get(role)
        if st is None:
            st = {}
            _seed_loop_role(path, st)
            st["stopped"] = _is_stopped(st.get("last_finished_utc"), now_ts)
            states[role] = st
            continue  # seeding pass: report nothing, same as every other source

        for line in _tail_new_lines(path, st):
            try:
                rec = json.loads(line)
            except ValueError:
                continue
            day = (rec.get("finished_utc") or "")[:10]
            if day and day != st.get("today"):
                st["today"] = day
                st["passes_today"] = 0
            st["passes_today"] = st.get("passes_today", 0) + 1
            st["last_finished_utc"] = rec.get("finished_utc")
            yield {
                "kind": "loop_health", "event": "pass", "role": role,
                "ok": rec.get("ok"), "reason": rec.get("reason"),
                "seconds": rec.get("seconds"),
                "passes_today": st["passes_today"],
                "ts": rec.get("finished_utc"),
            }

        is_stopped = _is_stopped(st.get("last_finished_utc"), now_ts)
        if is_stopped != st.get("stopped", False):
            st["stopped"] = is_stopped
            yield {
                "kind": "loop_health",
                "event": "stopped" if is_stopped else "recovered",
                "role": role, "last_finished_utc": st.get("last_finished_utc"),
                "ts": _iso_now(),
            }


def _poll_forever():
    """The one background thread that watches every source and publishes
    what it finds. Every HTTP connection is a subscriber to this, not a
    poller of its own -- which is what makes "replay the last 50" possible:
    there is exactly one shared history to replay from.
    """
    seen_sources = {}
    collector_state = {}
    call_state = _seed_tail_state(CALL_LOG_PATH)
    commission_state = _seed_tail_state(COMMISSION_LOG_PATH)
    linear_state = _seed_tail_state(LINEAR_ACTIVITY_LOG_PATH)
    commit_state = {}
    loop_states = {}
    while True:
        for event in _collection_pass_events(seen_sources):
            _publish(event)
        for event in _collector_pass_events(collector_state):
            _publish(event)
        for event in _call_events(call_state):
            _publish(event)
        for event in _commission_step_events(commission_state):
            _publish(event)
        for event in _linear_activity_events(linear_state):
            _publish(event)
        for event in _commit_events(commit_state):
            _publish(event)
        for event in _loop_health_events(loop_states):
            _publish(event)
        time.sleep(POLL_SECONDS)


class Handler(http.server.BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path != "/v1/events":
            self.send_response(404)
            self.end_headers()
            return
        if not _slots.acquire(blocking=False):
            self._send_503()
            return
        try:
            self._stream()
        except (BrokenPipeError, ConnectionResetError):
            pass
        finally:
            _slots.release()

    def _send_503(self):
        body = json.dumps({
            "error": "too many people are watching the machine right now "
                     "-- try again shortly",
        }).encode()
        self.send_response(503)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _send_event(self, payload):
        self.wfile.write(("data: %s\n\n" % json.dumps(payload)).encode())
        self.wfile.flush()

    def _stream(self):
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.send_header("Cache-Control", "no-cache")
        self.send_header("Connection", "keep-alive")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        q = queue.Queue(maxsize=200)
        with _subscribers_lock:
            _subscribers.add(q)
        try:
            for event in _replay_backlog():
                self._send_event(event)
            while True:
                self._send_event(q.get())
        finally:
            with _subscribers_lock:
                _subscribers.discard(q)

    def log_message(self, *a):
        pass


class ThreadingHTTPServer(socketserver.ThreadingMixIn, http.server.HTTPServer):
    daemon_threads = True


def main():
    ThreadingHTTPServer.allow_reuse_address = True
    httpd = ThreadingHTTPServer((HOST, PORT), Handler)
    threading.Thread(target=_poll_forever, daemon=True).start()
    print("serve_events listening on http://%s:%d" % (HOST, PORT))
    httpd.serve_forever()


if __name__ == "__main__":
    main()
