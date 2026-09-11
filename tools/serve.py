#!/usr/bin/env python3
"""Process entry point: starts the REST API and the MCP server, nothing else.

  python3 tools/serve.py

Both listeners bind 127.0.0.1 and read data/ read-only -- see serve_api.py,
serve_mcp.py and serve_common.py. agents/Caddyfile is what makes either one
reachable from outside the box.
"""

import os
import sys
import threading

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import serve_api  # noqa: E402
import serve_mcp  # noqa: E402


def main():
    threading.Thread(target=serve_api.main, daemon=True).start()
    serve_mcp.main()


if __name__ == "__main__":
    main()
