#!/usr/bin/env python3
"""Process entry point: starts the REST API, the MCP server and /ask.

  python3 tools/serve.py

All three listeners bind 127.0.0.1 and read data/ read-only -- see
serve_api.py, serve_mcp.py, ask_backend.py and serve_common.py.
agents/Caddyfile is what makes any of them reachable from outside the box.

This is the one process that runs as the margin-serve systemd unit, the only
place ANTHROPIC_API_KEY (in /etc/margin/ask.env) is read -- see
ask_backend.py's docstring and margin-serve.service.
"""

import os
import sys
import threading

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import ask_backend  # noqa: E402
import serve_api  # noqa: E402
import serve_mcp  # noqa: E402


def main():
    threading.Thread(target=serve_api.main, daemon=True).start()
    threading.Thread(target=ask_backend.main, daemon=True).start()
    serve_mcp.main()


if __name__ == "__main__":
    main()
