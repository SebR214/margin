#!/usr/bin/env python3
"""Render pages to PNG so a review can show what it saw, not describe it.

Serves the repository over HTTP the way a reader gets it, so the page's own
fetch() calls resolve, then captures the full height of each page.

Usage:
  python3 tools/shot.py                      # every reader-facing page
  python3 tools/shot.py providers.html       # only these
  python3 tools/shot.py --out /tmp/shots index.html
"""

import http.server
import os
import socketserver
import sys
import threading

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from headless import Page                                    # noqa: E402
from check_page import PAGES                                 # noqa: E402

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


class Quiet(http.server.SimpleHTTPRequestHandler):
    def __init__(self, *a, **k):
        super().__init__(*a, directory=HERE, **k)

    def log_message(self, *a):
        pass


def main():
    args = sys.argv[1:]
    out = "/tmp/shots"
    if "--out" in args:
        i = args.index("--out")
        out = args[i + 1]
        del args[i:i + 2]
    pages = [p for p in (args or PAGES) if os.path.exists(os.path.join(HERE, p))]
    if not pages:
        print("no such page in this repo")
        return 1
    os.makedirs(out, exist_ok=True)

    socketserver.TCPServer.allow_reuse_address = True
    httpd = socketserver.TCPServer(("127.0.0.1", 0), Quiet)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    port = httpd.server_address[1]
    try:
        with Page() as b:
            for p in pages:
                b.visit(f"http://127.0.0.1:{port}/{p}")
                dest = os.path.join(out, p.replace(".html", "") + ".png")
                b.screenshot(dest)
                print(f"  {dest}  ({os.path.getsize(dest) // 1024} KB)")
    finally:
        httpd.shutdown()
    return 0


if __name__ == "__main__":
    sys.exit(main())
