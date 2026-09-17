#!/usr/bin/env python3
"""B3/M1: one SSE stream of what the machine is actually doing, unedited.

Binds 127.0.0.1:8903, GET /v1/events only. Every event is real -- built by
tailing logs and polling APIs the rest of the system already writes to, never
synthesized or resampled. Six kinds:

  collection_pass   one per source, each time data/agent_status.json records
                     a fresh last_ok_utc or a change in `broken` -- the same
                     file status.html already reads.
  call              the anonymised call tail: tool name and the country
                     parameter it was asked about, nothing else. From
                     serve_common.log_call_event and its callers.
  commission_step   one per step of a commission's source probe, keyed by the
                     Linear issue id so a visitor can follow one request's
                     thread. From tools/probe_source.py via
                     serve_common.log_commission_step.
  loop_health       one per completed pass of builder/reviewer/product, read
                     from their own jsonl records (agents/run.sh's `record()`)
                     -- role, whether it did real work, how long it took. Also
                     fires a `status: "stopped"` event the moment a role has
                     gone quiet for more than STALE_AFTER_SECONDS (the same
                     staleness window the homepage's own header uses), and a
                     `status: "ran"` event when it resumes. A stopped loop is
                     shown as stopped -- not merely absent from the feed.
  commit            a new commit landed on the checkout this process reads
                     from (/srv/margin, refreshed from origin/main every five
                     minutes by margin-pull.timer) -- short sha and subject.
  pr                a pull request on the repo changed state: opened, merged,
                     closed, reopened. Read from the GitHub REST API using an
                     installation token minted the same way the agent loops
                     do (agents/gh_token.sh), never `gh` itself, so this stays
                     dependency-free.
  linear_transition  an issue in the margin.wiki project changed state.
  linear_comment     a NEW comment stamped by an agent role -- builder,
                     reviewer or product. Comments with no stamp are
                     Sebastian's own words (see agents/RULES.md, "an unstamped
                     comment is his own"); those are never streamed. Linear is
                     documented elsewhere as private specifically because of
                     that convention, so this feed only ever carries what an
                     agent said, never what he did.

One background thread does all the polling, at cadences chosen per source
(cheap local file reads every 5-10s, external API calls every 60s so this
process makes at most ~1,440 GitHub calls/day and a similar count of Linear
GraphQL calls/day -- both well inside their free-tier rate limits, and neither
service bills per call for this org, so this adds no running cost). Every
connection just drains a shared, bounded event buffer -- so the API cost does
not grow with the number of people watching. New connections replay the last
50 events immediately, then stream whatever arrives after that.

No dollar figures anywhere: there is no spend metering on this project, so
none of these events carries a cost or a price -- only what happened.

Capped at MAX_CONNECTIONS concurrent streams -- a code-enforced ceiling, not
a load-tested one; see the SEB-42 PR for the arithmetic behind the number.
Past the cap, a new connection gets a plain 503 with a reason, never a silent
hang.

Stdlib only. Subprocess is used for two things only: minting a GitHub App
token (agents/gh_token.sh, which itself only shells out to openssl and curl)
and reading git log on the local checkout -- no `gh` CLI, no third-party
packages.
"""

import collections
import datetime
import http.server
import itertools
import json
import os
import socketserver
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
DATA = os.path.join(ROOT, "data")
AGENT_STATUS_PATH = os.path.join(DATA, "agent_status.json")
CALL_LOG_PATH = os.environ.get(
    "SERVE_EVENTS_LOG_PATH", "/var/log/margin/serve.systemd.log")
COMMISSION_LOG_PATH = os.environ.get(
    "COMMISSION_EVENTS_LOG_PATH", "/var/log/margin/commission.systemd.log")
LOOP_LOGDIR = os.environ.get("MARGIN_LOOP_LOGDIR", "/var/log/margin")
LOOP_JSONL = {role: os.path.join(LOOP_LOGDIR, "%s.jsonl" % role)
              for role in ("builder", "reviewer", "product")}
GH_TOKEN_SCRIPT = os.path.join(ROOT, "agents", "gh_token.sh")
GH_REPO = "SebR214/margin"
LINEAR_URL = "https://api.linear.app/graphql"
LINEAR_PROJECT_NAME = "margin.wiki"

HOST, PORT = "127.0.0.1", 8903

# A code-enforced ceiling, not a load-tested one -- see the SEB-42 PR for the
# arithmetic (20 held threads, worst case ~8MB stack each = 160MB, against a
# measured 2.4GB of available RAM on this box, alongside the four existing
# listeners).
MAX_CONNECTIONS = 20

POLL_LOCAL_SECONDS = 5      # file reads: agent_status.json, log tails, git log
POLL_LOOP_SECONDS = 10      # the three jsonl records
POLL_REMOTE_SECONDS = 60    # GitHub + Linear: the only calls that cost a quota

# Matches the staleness window index.html's own header uses for "collector ok"
# vs "no pass since <time>" -- one definition of "gone quiet" for the whole
# site, not a second one invented here.
STALE_AFTER_SECONDS = 90 * 60

REPLAY_COUNT = 50
BUFFER_SIZE = 500  # generous headroom over REPLAY_COUNT; bounds memory, not the replay

ROLE_STAMPS = (("\U0001f528", "builder"), ("\U0001f50d", "reviewer"),
               ("\U0001f4cb", "product"))

_slots = threading.Semaphore(MAX_CONNECTIONS)

# ---------------------------------------------------------------- the feed
#
# One background thread produces events; every connection just drains this.
# That is what keeps the external API calls (GitHub, Linear) at a fixed cost
# regardless of how many people are watching, and what makes "replay the last
# 50" a slice instead of a re-fetch.
_events_lock = threading.Lock()
_events = collections.deque(maxlen=BUFFER_SIZE)
_seq = itertools.count(1)


def _emit(kind, **fields):
    with _events_lock:
        n = next(_seq)
        event = {"seq": n, "kind": kind,
                 "at": datetime.datetime.now(datetime.timezone.utc)
                 .isoformat(timespec="seconds")}
        event.update(fields)
        _events.append(event)


def _replay(after_seq=0):
    with _events_lock:
        return [e for e in _events if e["seq"] > after_seq]


def _latest_seq():
    with _events_lock:
        return _events[-1]["seq"] if _events else 0


# --------------------------------------------------------- local, cheap: 5s

def _read_agent_status():
    try:
        with open(AGENT_STATUS_PATH) as f:
            return json.load(f)
    except (OSError, ValueError):
        return None


def _poll_collection_pass(seen):
    """Emit one event per source whose last_ok_utc or broken flag moved.

    `seen` is mutated in place, keyed by (file, name) -> (last_ok_utc, broken).
    The first call after the process starts has nothing seen, so it reports
    every source once -- which the replay buffer then carries to any client
    that connects afterwards, so this needs no separate bootstrap path.
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
        _emit("collection_pass", file=src.get("file"), name=src.get("name"),
              ok=not src.get("broken"), last_ok_utc=src.get("last_ok_utc"))


def _parse_call_event(line):
    if not line.startswith("call_event tool="):
        return None
    fields = {}
    for part in line.rstrip("\n")[len("call_event "):].split(" "):
        if "=" in part:
            k, v = part.split("=", 1)
            fields[k] = v
    return {"tool": fields.get("tool") or None,
            "country": fields.get("country") or None}


def _tail_new_lines(path, state):
    """Yield each line appended to `path` since the last call.

    `state` carries the file's inode and the byte offset already read, so a
    rotated log (Caddy and systemd both roll files) is noticed -- the offset
    resets to zero rather than seeking past the end of a now-smaller file.

    The FIRST time a given `state` dict sees this path, it primes to the
    CURRENT end of file rather than reading from the beginning. A log can
    carry days of pre-existing history -- commission tests, past passes --
    and replaying all of it as though it just happened is exactly the kind
    of thing "no synthetic events" rules out. Confirmed live: on 2026-09-17
    this bug (present before M1 touched the file) replayed the entire
    commission.systemd.log test history as fresh events on every restart.
    Only lines written after a process starts watching are real-time.
    """
    try:
        st = os.stat(path)
    except OSError:
        return
    if "inode" not in state:
        state["inode"] = st.st_ino
        state["offset"] = st.st_size
        return
    if state.get("inode") != st.st_ino or state.get("offset", 0) > st.st_size:
        state["inode"] = st.st_ino
        state["offset"] = 0
    with open(path) as f:
        f.seek(state.get("offset", 0))
        for line in f:
            yield line
        state["offset"] = f.tell()


def _poll_calls(state):
    for line in _tail_new_lines(CALL_LOG_PATH, state):
        event = _parse_call_event(line)
        if event is not None:
            _emit("call", **event)


def _parse_commission_step_event(line):
    if not line.startswith("commission_step "):
        return None
    try:
        record = json.loads(line[len("commission_step "):])
    except ValueError:
        return None
    if record.get("kind") != "commission_step" or not record.get("request_id"):
        return None
    record = dict(record)
    record.pop("kind", None)
    return record


def _poll_commission_steps(state):
    """One `commission_step` event per new line probe_source.py wrote.

    Unlike the call tail, this is one JSON object per line rather than
    space-separated `k=v` pairs -- a probe's `check` line and a rejection
    reason are free text that can contain spaces, which the `k=v` shape
    would silently truncate.
    """
    for line in _tail_new_lines(COMMISSION_LOG_PATH, state):
        event = _parse_commission_step_event(line)
        if event is not None:
            _emit("commission_step", **event)


def _poll_commits(state):
    """One `commit` event per new commit reaching the checkout this reads.

    /srv/margin is its own clone, refreshed from origin/main every five
    minutes by margin-pull.timer -- so "a commit landed here" means "a commit
    reached main", not a branch in progress on one of the agent checkouts.
    """
    try:
        out = subprocess.run(["git", "-C", ROOT, "rev-parse", "HEAD"],
                              capture_output=True, text=True, timeout=10)
        head = out.stdout.strip() if out.returncode == 0 else None
    except Exception:
        head = None
    if not head:
        return
    prev = state.get("head")
    state["head"] = head
    if prev is None or prev == head:
        return
    try:
        out = subprocess.run(
            ["git", "-C", ROOT, "log", "%s..%s" % (prev, head),
             "--reverse", "--format=%H\x1f%s"],
            capture_output=True, text=True, timeout=10)
    except Exception:
        return
    if out.returncode != 0:
        # prev is no longer an ancestor of head -- a force-push or a rebase
        # of the tracked branch. Say only that the tip moved; guessing at a
        # commit range that no longer exists would be inventing history.
        _emit("commit", sha=head[:8], message="(history rewritten upstream)")
        return
    for line in out.stdout.splitlines():
        if "\x1f" not in line:
            continue
        sha, msg = line.split("\x1f", 1)
        _emit("commit", sha=sha[:8], message=msg)


# ------------------------------------------------------ loop health: 10s

def _tail_jsonl_new(path, state):
    for line in _tail_new_lines(path, state):
        try:
            yield json.loads(line)
        except ValueError:
            continue


def _last_jsonl_timestamp(path):
    """The `finished_utc` of the last record already in `path`, read without
    loading the whole file -- so a loop that went quiet before this process
    even started is still correctly known to be quiet, without treating its
    entire history as fresh events."""
    try:
        with open(path, "rb") as f:
            f.seek(0, os.SEEK_END)
            size = f.tell()
            chunk = 4096
            pos = max(0, size - chunk)
            f.seek(pos)
            tail = f.read().decode("utf-8", "replace")
        line = tail.strip().splitlines()[-1] if tail.strip() else None
        if not line:
            return None
        fin = json.loads(line).get("finished_utc")
        return datetime.datetime.fromisoformat(fin).timestamp() if fin else None
    except (OSError, ValueError, IndexError):
        return None


def _poll_loop_health(states):
    now = time.time()
    for role, path in LOOP_JSONL.items():
        first_touch = role not in states
        st = states.setdefault(role, {"stopped": False, "last_ts": None})
        if first_touch:
            # _tail_jsonl_new (via _tail_new_lines) primes the read position
            # to end-of-file on its own first call below; this just seeds the
            # staleness baseline from the last record already on disk, so a
            # loop that was already quiet before this process started is
            # correctly known to be quiet from the first poll.
            st["last_ts"] = _last_jsonl_timestamp(path)
            if st["last_ts"] is not None and (now - st["last_ts"]) > STALE_AFTER_SECONDS:
                st["stopped"] = True
                _emit("loop_health", role=role, status="stopped",
                      minutes_silent=int((now - st["last_ts"]) / 60))
        for rec in _tail_jsonl_new(path, st):
            fin = rec.get("finished_utc")
            ts = None
            if fin:
                try:
                    ts = datetime.datetime.fromisoformat(fin).timestamp()
                except ValueError:
                    ts = None
            if ts is not None:
                st["last_ts"] = ts
            _emit("loop_health", role=role, status="ran",
                  ok=bool(rec.get("ok")), reason=rec.get("reason"),
                  seconds=rec.get("seconds"), finished_utc=fin)
            if st["stopped"]:
                st["stopped"] = False
                _emit("loop_health", role=role, status="resumed")

        last_ts = st.get("last_ts")
        is_stopped = last_ts is not None and (now - last_ts) > STALE_AFTER_SECONDS
        if is_stopped and not st["stopped"]:
            st["stopped"] = True
            _emit("loop_health", role=role, status="stopped",
                  minutes_silent=int((now - last_ts) / 60))


# ------------------------------------------------- external, rate-limited: 60s

def _mint_gh_token():
    try:
        out = subprocess.run([GH_TOKEN_SCRIPT], capture_output=True,
                              text=True, timeout=20)
    except Exception:
        return None
    if out.returncode != 0 or not out.stdout.strip():
        return None
    return out.stdout.strip()


def _gh_get(path, token):
    req = urllib.request.Request(
        "https://api.github.com" + path,
        headers={"Authorization": "token %s" % token,
                 "Accept": "application/vnd.github+json",
                 "User-Agent": "margin-wiki-serve-events"})
    with urllib.request.urlopen(req, timeout=20) as r:
        return json.loads(r.read().decode())


def _poll_prs(state):
    """Emit `pr` events for state changes only -- never for the PRs already
    in whatever state they were in the moment this process started. The first
    poll just records a baseline silently; only actual transitions after that
    are real-time events worth telling anyone about.
    """
    token = _mint_gh_token()
    if not token:
        return
    try:
        prs = _gh_get(
            "/repos/%s/pulls?state=all&per_page=30&sort=updated&direction=desc"
            % GH_REPO, token)
    except (urllib.error.URLError, urllib.error.HTTPError, ValueError):
        return
    first_poll = "seen" not in state
    seen = state.setdefault("seen", {})
    for pr in prs:
        n = pr.get("number")
        if n is None:
            continue
        st = "merged" if pr.get("merged_at") else pr.get("state")
        prev = seen.get(n)
        seen[n] = st
        if first_poll:
            continue
        if prev is None:
            if st == "open":
                _emit("pr", number=n, title=pr.get("title"),
                      action="opened", url=pr.get("html_url"))
            continue
        if prev != st:
            action = {"merged": "merged", "closed": "closed",
                      "open": "reopened"}.get(st, st)
            _emit("pr", number=n, title=pr.get("title"),
                  action=action, url=pr.get("html_url"))


def _linear_call(query, variables=None):
    key = os.environ.get("LINEAR_API_KEY")
    if not key:
        return None
    body = json.dumps({"query": query, "variables": variables or {}}).encode()
    req = urllib.request.Request(LINEAR_URL, data=body, headers={
        "Content-Type": "application/json", "Authorization": key})
    try:
        with urllib.request.urlopen(req, timeout=20) as r:
            d = json.loads(r.read().decode())
    except (urllib.error.URLError, urllib.error.HTTPError, ValueError):
        return None
    if not isinstance(d, dict) or "data" not in d or d.get("errors"):
        return None
    return d["data"]


def _linear_project_id(state):
    if "project_id" in state:
        return state["project_id"]
    d = _linear_call("{ projects(first: 50) { nodes { id name } } }")
    if not d:
        return None
    for p in d["projects"]["nodes"]:
        if p["name"] == LINEAR_PROJECT_NAME:
            state["project_id"] = p["id"]
            return p["id"]
    return None


def _parse_stamp(body):
    """Which role, if any, wrote this comment -- and the text after the stamp.

    An unstamped comment is Sebastian's own word (agents/RULES.md), and this
    feed is public, so those are never returned here; the caller drops them.
    """
    body = body or ""
    for emoji, role in ROLE_STAMPS:
        if body.startswith(emoji):
            rest = body.split("\n", 1)[1] if "\n" in body else ""
            return role, rest.strip()
    return None, None


def _poll_linear(state):
    """One poll, two things: issue-state transitions and new stamped
    comments. Combined into a single query so this stays one Linear call
    per cycle rather than two.
    """
    pid = _linear_project_id(state)
    if not pid:
        return
    d = _linear_call("""query($id: String!) {
      project(id: $id) { issues(first: 100) {
        nodes {
          identifier title
          state { name }
          comments(first: 5, orderBy: createdAt) { nodes { id body } }
        }
      } }
    }""", {"id": pid})
    if not d:
        return

    first_poll = "seen_state" not in state
    seen_state = state.setdefault("seen_state", {})
    seen_comments = state.setdefault("seen_comments", {})

    for iss in d["project"]["issues"]["nodes"]:
        key = iss["identifier"]

        st = iss["state"]["name"]
        prev = seen_state.get(key)
        seen_state[key] = st
        if not first_poll and prev is not None and prev != st:
            _emit("linear_transition", issue=key, title=iss["title"],
                  from_state=prev, to_state=st)

        cids = seen_comments.setdefault(key, set())
        for c in iss["comments"]["nodes"]:
            if c["id"] in cids:
                continue
            cids.add(c["id"])
            if first_poll:
                continue
            role, text = _parse_stamp(c.get("body"))
            if role is None:
                continue  # Sebastian's own word -- never streamed
            _emit("linear_comment", issue=key, role=role,
                  text=(text or "")[:160])


# --------------------------------------------------------------- the loop

def _background_poller():
    local_state = {"seen_sources": {}, "call": {}, "commission": {},
                   "commit": {}}
    loop_state = {}
    pr_state = {}
    linear_state = {}

    last_local = last_loop = last_remote = 0.0
    while True:
        now = time.monotonic()
        try:
            if now - last_local >= POLL_LOCAL_SECONDS:
                _poll_collection_pass(local_state["seen_sources"])
                _poll_calls(local_state["call"])
                _poll_commission_steps(local_state["commission"])
                _poll_commits(local_state["commit"])
                last_local = now
            if now - last_loop >= POLL_LOOP_SECONDS:
                _poll_loop_health(loop_state)
                last_loop = now
            if now - last_remote >= POLL_REMOTE_SECONDS:
                _poll_prs(pr_state)
                _poll_linear(linear_state)
                last_remote = now
        except Exception as e:
            # The poller must never die -- one bad cycle from a flaky API is
            # not a reason to stop telling the truth about everything else.
            sys.stderr.write("serve_events poller: %r\n" % (e,))
        time.sleep(1)


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

        # Replay, then follow. The background thread is the only thing that
        # ever calls GitHub or Linear, so this costs nothing per connection.
        backlog = _replay()[-REPLAY_COUNT:]
        last_seq = 0
        for event in backlog:
            self._send_event(event)
            last_seq = event["seq"]
        if not backlog:
            last_seq = _latest_seq()

        while True:
            for event in _replay(after_seq=last_seq):
                self._send_event(event)
                last_seq = event["seq"]
            time.sleep(1)

    def log_message(self, *a):
        pass


class ThreadingHTTPServer(socketserver.ThreadingMixIn, http.server.HTTPServer):
    daemon_threads = True


def main():
    threading.Thread(target=_background_poller, daemon=True).start()
    ThreadingHTTPServer.allow_reuse_address = True
    httpd = ThreadingHTTPServer((HOST, PORT), Handler)
    print("serve_events listening on http://%s:%d" % (HOST, PORT))
    httpd.serve_forever()


if __name__ == "__main__":
    main()
