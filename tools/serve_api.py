#!/usr/bin/env python3
"""REST API over data/, plus one write: filing a request for new data.

Binds 127.0.0.1:8899 only -- agents/Caddyfile is the only thing meant to be
reachable from outside this box. Six endpoints:

  GET  /dollar_cost?country=
  GET  /compare_routes?from=&to=&amount=
  GET  /series?country=&days=
  GET  /query?sql=
  GET  /bundle/<file>
  POST /request_series   {"description": "..."}

The first four answer straight from a file this repo already writes.
/bundle serves the browser dataset bundle SEB-40 writes to data/bundle/ --
static files, but through this process rather than a Caddy file_server so the
cache headers live in one place with everything else this box serves. The
last endpoint doesn't touch data/ at all -- it files the request in Linear,
where the work is managed, and is rate-limited since this endpoint is public
and unauthenticated.

Stdlib only.
"""

import http.server
import json
import os
import socketserver
import sys
import urllib.parse

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import serve_common as sc  # noqa: E402

HOST, PORT = "127.0.0.1", 8899

BUNDLE_DIR = os.path.join(sc.DATA, "bundle")
BUNDLE_CONTENT_TYPES = {".parquet": "application/octet-stream", ".json": "application/json"}
# Regenerated hourly by the collect chain; a visitor who loads several pages
# inside this window gets the parquet files once and 304s after that, not a
# fresh download per page. See SEB-40's PR for the bandwidth arithmetic this
# window is based on.
BUNDLE_CACHE_CONTROL = "public, max-age=300"


class Handler(http.server.BaseHTTPRequestHandler):
    def _send(self, status, payload):
        body = json.dumps(payload, indent=2, sort_keys=True).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _send_bundle_file(self, name):
        # basename only -- name comes straight off the URL path, and this is
        # the only handler here that touches the filesystem by a caller-given
        # name rather than a fixed path, so it is the one place a "../" could
        # matter.
        if name != os.path.basename(name):
            self._send(404, {"error": "no such file"})
            return
        ext = os.path.splitext(name)[1]
        content_type = BUNDLE_CONTENT_TYPES.get(ext)
        path = os.path.join(BUNDLE_DIR, name)
        if content_type is None or not os.path.isfile(path):
            self._send(404, {"error": "no such file"})
            return

        st = os.stat(path)
        etag = f'"{st.st_size:x}-{int(st.st_mtime_ns):x}"'
        if self.headers.get("If-None-Match") == etag:
            self.send_response(304)
            self.send_header("ETag", etag)
            self.send_header("Cache-Control", BUNDLE_CACHE_CONTROL)
            self.end_headers()
            return

        with open(path, "rb") as f:
            body = f.read()
        self.send_response(200)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("ETag", etag)
        self.send_header("Cache-Control", BUNDLE_CACHE_CONTROL)
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        parsed = urllib.parse.urlsplit(self.path)
        params = {k: v[0] for k, v in urllib.parse.parse_qs(parsed.query).items()}
        try:
            if parsed.path == "/dollar_cost":
                sc.log_call_event(
                    "dollar_cost", sc.resolved_country_name(params.get("country")))
                self._send(200, sc.dollar_cost(params.get("country", "")))
            elif parsed.path == "/compare_routes":
                sc.log_call_event("compare_routes")
                self._send(200, sc.compare_routes(
                    params.get("from", ""), params.get("to", ""),
                    params.get("amount")))
            elif parsed.path == "/series":
                sc.log_call_event(
                    "series", sc.resolved_country_name(params.get("country")))
                self._send(200, sc.series(
                    params.get("country", ""), params.get("days")))
            elif parsed.path == "/query":
                sc.log_call_event("query")
                self._send(200, sc.run_query(params.get("sql", "")))
            elif parsed.path.startswith("/bundle/"):
                self._send_bundle_file(parsed.path[len("/bundle/"):])
            else:
                self._send(404, {"error": "no such endpoint"})
        except sc.ServeError as e:
            self._send(400, {"error": str(e)})

    def do_POST(self):
        parsed = urllib.parse.urlsplit(self.path)
        try:
            if parsed.path == "/request_series":
                sc.log_call_event("request_series")
                length = int(self.headers.get("Content-Length", 0))
                raw = self.rfile.read(length) if length else b""
                try:
                    payload = json.loads(raw) if raw else {}
                except ValueError:
                    raise sc.ServeError("body must be valid JSON")
                self._send(200, sc.request_series(payload.get("description", "")))
            else:
                self._send(404, {"error": "no such endpoint"})
        except sc.ServeError as e:
            self._send(400, {"error": str(e)})


def main():
    socketserver.TCPServer.allow_reuse_address = True
    httpd = socketserver.TCPServer((HOST, PORT), Handler)
    print("serve_api listening on http://%s:%d" % (HOST, PORT))
    httpd.serve_forever()


if __name__ == "__main__":
    main()
