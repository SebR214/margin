#!/usr/bin/env python3
"""REST API over data/, plus one write: filing a request for new data.

Binds 127.0.0.1:8899 only -- agents/Caddyfile is the only thing meant to be
reachable from outside this box. Five endpoints:

  GET  /dollar_cost?country=
  GET  /compare_routes?from=&to=&amount=
  GET  /series?country=&days=
  GET  /query?sql=
  POST /request_series   {"description": "..."}

The first four answer straight from a file this repo already writes. The
last one doesn't touch data/ at all -- it files the request in Linear, where
the work is managed, and is rate-limited since this endpoint is public and
unauthenticated.

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


class Handler(http.server.BaseHTTPRequestHandler):
    def _send(self, status, payload):
        body = json.dumps(payload, indent=2, sort_keys=True).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        parsed = urllib.parse.urlsplit(self.path)
        params = {k: v[0] for k, v in urllib.parse.parse_qs(parsed.query).items()}
        try:
            if parsed.path == "/dollar_cost":
                self._send(200, sc.dollar_cost(params.get("country", "")))
            elif parsed.path == "/compare_routes":
                self._send(200, sc.compare_routes(
                    params.get("from", ""), params.get("to", ""),
                    params.get("amount")))
            elif parsed.path == "/series":
                self._send(200, sc.series(
                    params.get("country", ""), params.get("days")))
            elif parsed.path == "/query":
                self._send(200, sc.run_query(params.get("sql", "")))
            else:
                self._send(404, {"error": "no such endpoint"})
        except sc.ServeError as e:
            self._send(400, {"error": str(e)})

    def do_POST(self):
        parsed = urllib.parse.urlsplit(self.path)
        try:
            if parsed.path == "/request_series":
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
