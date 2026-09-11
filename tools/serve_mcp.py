#!/usr/bin/env python3
"""MCP server over data/, the same engine serve_api.py exposes as REST.

Binds 127.0.0.1:8900 only. Hand-rolled JSON-RPC over http.server -- the same
kind of small, deterministic protocol handling tools/headless.py already
hand-rolls for DevTools, not a new dependency.

One route, POST /mcp, implementing initialize, tools/list and tools/call.

Stdlib only.
"""

import http.server
import json
import os
import socketserver
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import serve_common as sc  # noqa: E402

HOST, PORT = "127.0.0.1", 8900

TOOLS = [
    {
        "name": "dollar_cost",
        "description": (
            "Today's price to buy one US dollar in a country this project "
            "tracks, or the reason no price is available this hour."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {"country": {"type": "string"}},
            "required": ["country"],
        },
    },
    {
        "name": "compare_routes",
        "description": (
            "Compare the ways to send money on a corridor this project "
            "measures, ranked by cost, for a given amount."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "from": {"type": "string"},
                "to": {"type": "string"},
                "amount": {"type": "number"},
            },
            "required": ["from", "to", "amount"],
        },
    },
    {
        "name": "series",
        "description": "The day-by-day history of a country's dollar price.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "country": {"type": "string"},
                "days": {"type": "integer"},
            },
            "required": ["country"],
        },
    },
    {
        "name": "query",
        "description": (
            "Run one read-only SELECT statement over the raw data tables "
            "and get back up to 5,000 rows."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {"sql": {"type": "string"}},
            "required": ["sql"],
        },
    },
    {
        "name": "request_series",
        "description": (
            "Ask for a series this project does not collect yet. Opens a "
            "request for a person or agent to look into; it never adds data "
            "by itself."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {"description": {"type": "string"}},
            "required": ["description"],
        },
    },
]

DISPATCH = {
    "dollar_cost": lambda a: sc.dollar_cost(a.get("country", "")),
    "compare_routes": lambda a: sc.compare_routes(
        a.get("from", ""), a.get("to", ""), a.get("amount")),
    "series": lambda a: sc.series(a.get("country", ""), a.get("days")),
    "query": lambda a: sc.run_query(a.get("sql", "")),
    "request_series": lambda a: sc.request_series(a.get("description", "")),
}


def _handle(method, params):
    if method == "initialize":
        return {
            "protocolVersion": "2024-11-05",
            "capabilities": {"tools": {}},
            "serverInfo": {"name": "margin-wiki", "version": "1.0"},
        }
    if method == "tools/list":
        return {"tools": TOOLS}
    if method == "tools/call":
        name = (params or {}).get("name")
        arguments = (params or {}).get("arguments", {}) or {}
        fn = DISPATCH.get(name)
        if fn is None:
            return {
                "content": [{"type": "text", "text": "no such tool: %s" % name}],
                "isError": True,
            }
        try:
            result = fn(arguments)
        except sc.ServeError as e:
            return {"content": [{"type": "text", "text": str(e)}], "isError": True}
        return {"content": [{"type": "text", "text": json.dumps(result)}]}
    raise KeyError(method)


class Handler(http.server.BaseHTTPRequestHandler):
    def _send(self, payload):
        body = json.dumps(payload).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_POST(self):
        if self.path != "/mcp":
            self.send_response(404)
            self.end_headers()
            return
        length = int(self.headers.get("Content-Length", 0))
        raw = self.rfile.read(length) if length else b""
        req_id = None
        try:
            req = json.loads(raw or b"{}")
            req_id = req.get("id")
            result = _handle(req.get("method"), req.get("params"))
            self._send({"jsonrpc": "2.0", "id": req_id, "result": result})
        except KeyError as e:
            self._send({
                "jsonrpc": "2.0", "id": req_id,
                "error": {"code": -32601, "message": "method not found: %s" % e},
            })
        except (ValueError, TypeError) as e:
            self._send({
                "jsonrpc": "2.0", "id": req_id,
                "error": {"code": -32600, "message": str(e)},
            })


def main():
    socketserver.TCPServer.allow_reuse_address = True
    httpd = socketserver.TCPServer((HOST, PORT), Handler)
    print("serve_mcp listening on http://%s:%d" % (HOST, PORT))
    httpd.serve_forever()


if __name__ == "__main__":
    main()
