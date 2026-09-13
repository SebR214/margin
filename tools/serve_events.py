#!/usr/bin/env python3
"""B3: one SSE stream the homepage (and anyone else) can watch live.

Binds 127.0.0.1:8903, GET /v1/events only. Three kinds of event, all built by
tailing logs the other four listeners already write -- no new instrumentation
of the collectors, per SEB-42:

  collection_pass   one per source, each time data/agent_status.json records
                     a fresh last_ok_utc or a change in `broken` -- the same
                     file status.html already reads, tailed here instead of
                     rebuilt.
  call              the anonymised call tail: tool name and the country
                     parameter it was asked about, nothing else. Produced by
                     serve_common.log_call_event and its callers in
                     serve_api.py, serve_mcp.py, ask_backend.py and
                     watch_backend.py -- one `call_event tool=... country=...`
                     line per request, and this is the ONLY log-line shape
                     this file turns into a `call` event. Every other line
                     already written to serve.systemd.log (queries, SQL,
                     model token counts, watch conditions) is read and
                     discarded without being parsed for fields.
  commission_step   B4 (SEB-43) is what will produce these; it has not
                     shipped, so this kind is wired into the protocol and
                     never fires. That is a stated gap, not a fabricated one
                     -- see the SEB-42 PR.

Capped at MAX_CONNECTIONS concurrent streams -- a code-enforced ceiling, not
a load-tested one; see the PR for the arithmetic behind the number. Past the
cap, a new connection gets a plain 503 with a reason, never a silent hang.

Stdlib only.
"""

import http.server
import json
import os
import socketserver
import sys
import threading
import time

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
DATA = os.path.join(ROOT, "data")
AGENT_STATUS_PATH = os.path.join(DATA, "agent_status.json")
CALL_LOG_PATH = os.environ.get(
    "SERVE_EVENTS_LOG_PATH", "/var/log/margin/serve.systemd.log")

HOST, PORT = "127.0.0.1", 8903

# A code-enforced ceiling, not a load-tested one -- see the SEB-42 PR for the
# arithmetic (20 held threads, worst case ~8MB stack each = 160MB, against a
# measured 2.4GB of available RAM on this box, alongside the four existing
# listeners).
MAX_CONNECTIONS = 20

POLL_SECONDS = 5

_slots = threading.Semaphore(MAX_CONNECTIONS)


def _read_agent_status():
    try:
        with open(AGENT_STATUS_PATH) as f:
            return json.load(f)
    except (OSError, ValueError):
        return None


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


def _call_events(state):
    """Yield one `call` event per new `call_event tool=... country=...` line.

    `state` carries the file's inode and the byte offset already read, so a
    rotated log (Caddy and systemd both roll files) is noticed -- the offset
    resets to zero rather than seeking past the end of a now-smaller file.
    """
    try:
        st = os.stat(CALL_LOG_PATH)
    except OSError:
        return
    if state.get("inode") != st.st_ino or state.get("offset", 0) > st.st_size:
        state["inode"] = st.st_ino
        state["offset"] = 0
    with open(CALL_LOG_PATH) as f:
        f.seek(state.get("offset", 0))
        for line in f:
            event = _parse_call_event(line)
            if event is not None:
                yield event
        state["offset"] = f.tell()


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
        seen_sources = {}
        call_state = {}
        while True:
            for event in _collection_pass_events(seen_sources):
                self._send_event(event)
            for event in _call_events(call_state):
                self._send_event(event)
            time.sleep(POLL_SECONDS)

    def log_message(self, *a):
        pass


class ThreadingHTTPServer(socketserver.ThreadingMixIn, http.server.HTTPServer):
    daemon_threads = True


def main():
    ThreadingHTTPServer.allow_reuse_address = True
    httpd = ThreadingHTTPServer((HOST, PORT), Handler)
    print("serve_events listening on http://%s:%d" % (HOST, PORT))
    httpd.serve_forever()


if __name__ == "__main__":
    main()
