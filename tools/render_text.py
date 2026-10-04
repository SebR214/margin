#!/usr/bin/env python3
"""The rendered text of a page, as a reader sees it, for a writer PR's description.

The writer agent puts this output in its PR body under "## Rendered text" so the
owner reads the words in context, with live numbers filled in, before approving.

  python3 tools/render_text.py how-it-works.html            # one page
  python3 tools/render_text.py index.html country.html     # several, one section each
"""

import os
import sys

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(HERE, "tools"))
from gate_common import PAGE_QUERY, open_page, serve  # noqa: E402
from check_cold_reader import page_text  # noqa: E402


def main():
    pages = sys.argv[1:]
    if not pages:
        print(__doc__)
        return 64
    base, stop = serve(HERE)
    try:
        with open_page(settle=4.0) as page:
            for name in pages:
                text = page_text(page, "%s/%s%s" % (base, name, PAGE_QUERY.get(name, "")))
                print("### %s\n\n%s\n" % (name, text))
    finally:
        stop()
    return 0


if __name__ == "__main__":
    sys.exit(main())
