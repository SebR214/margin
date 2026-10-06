"""Shared by the two reader-facing merge gates (check_rendered.py and
check_cold_reader.py): which pages a PR touches, and a throwaway local server
to render them from. Stdlib only."""

import functools
import glob
import http.server
import os
import re
import socket
import subprocess
import threading

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# A page with a required query string to render anything meaningful.
PAGE_QUERY = {"country.html": "?ccy=DZD", "finding.html": "?id=price_changes"}

# Not reader pages: mockups, tests, scratch.
SKIP_PREFIXES = ("docs/", "tests/", ".claude/", ".debate/")


def all_pages():
    pages = []
    for f in sorted(glob.glob(os.path.join(HERE, "*.html"))):
        rel = os.path.basename(f)
        if re.search(r" \d\.", rel):  # duplicate scratch copies ("home 2.html")
            continue
        pages.append(rel)
    return pages


def changed_files(base):
    """Files changed on this branch against `base` (a ref such as origin/main)."""
    for spec in (base + "...HEAD", base):
        r = subprocess.run(["git", "diff", "--name-only", spec], cwd=HERE,
                           capture_output=True, text=True)
        if r.returncode == 0:
            return [l.strip() for l in r.stdout.splitlines() if l.strip()]
    return []


def pages_for_change(files):
    """The pages a change can alter. A page's own html maps to itself; the
    shared stylesheet, scripts or copy deck can alter every page."""
    files = [f for f in files if not f.startswith(SKIP_PREFIXES)]
    pages = set()
    shared = False
    for f in files:
        if "/" not in f and f.endswith(".html"):
            if not re.search(r" \d\.", f):
                pages.add(f)
        elif f == "style.css" or f == "copy.json" or (f.startswith("copy/") and f.endswith(".json")) or (f.startswith("js/") and f.endswith(".js")) \
                or (f.endswith(".css") or f.endswith(".js")) and "/" not in f:
            shared = True
    if shared:
        return all_pages()
    return sorted(p for p in pages if os.path.exists(os.path.join(HERE, p)))


class _Quiet(http.server.SimpleHTTPRequestHandler):
    def log_message(self, *a):
        pass


def serve(root=HERE):
    """Start a local static server on a free port; returns (base_url, stop)."""
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    handler = functools.partial(_Quiet, directory=root)
    httpd = http.server.ThreadingHTTPServer(("127.0.0.1", port), handler)
    t = threading.Thread(target=httpd.serve_forever, daemon=True)
    t.start()
    return "http://127.0.0.1:%d" % port, httpd.shutdown


def open_page(settle=4.0, tries=3):
    """A headless Page that survives the CI runner occasionally failing to open
    Chrome's debug port ("browser never opened a debug port"): retry the launch."""
    import time
    from headless import Page
    last = None
    for i in range(tries):
        try:
            return Page(settle=settle)
        except Exception as e:  # noqa: BLE001
            last = e
            time.sleep(2 + 3 * i)
    raise last
