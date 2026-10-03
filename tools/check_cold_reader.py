#!/usr/bin/env python3
"""Gate 2 for reader-facing PRs: the cold reader check.

For each changed page: render it headless, take the visible text in reading
order, and send ONLY that text to a model that knows nothing about this site
(no repo, no diff, no ticket -- it runs in an empty temp directory). The model
says, per section, what the text tells a reader and why they would care. Any
section where it cannot do both, any unexplained jargon, any number with no
stated consequence is a failure, quoted exactly. Any failure blocks the merge
and the list is printed (and posted to the PR by the workflow).

The model runs through the `claude` CLI on the agents' flat-rate subscription
token (CLAUDE_CODE_OAUTH_TOKEN). ANTHROPIC_API_KEY and friends are stripped
from the child's environment, so this can never fall onto the metered key.

A failure is only counted if the text the model quotes really appears on the
page, so a hallucinated quote cannot block a PR.

Usage:
  python3 tools/check_cold_reader.py                      # pages changed vs origin/main
  python3 tools/check_cold_reader.py --changed-only      # CI: block only on text the PR adds
  python3 tools/check_cold_reader.py --self-test         # tests/jargon_page.html must be flagged
  python3 tools/check_cold_reader.py --pages index.html
  python3 tools/check_cold_reader.py --base-url https://margin.wiki --all --json-out out.json
"""

import argparse
import json
import os
import re
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(HERE, "tools"))
from gate_common import PAGE_QUERY, all_pages, changed_files, pages_for_change, serve  # noqa: E402
from headless import Page  # noqa: E402

MODEL = os.environ.get("COLD_READER_MODEL", "claude-sonnet-5-5")

INSTRUCTION = (
    "You are a smart reader with no background on this site. For each section: (1) say in one "
    "sentence what it tells you, (2) say why a reader would care. If you cannot do both, or a term "
    "is unexplained jargon, or a number has no stated consequence, list it as a failure with the "
    "exact text."
)

FORMAT = (
    "\n\nReply with JSON only, no prose, in exactly this shape:\n"
    '{"sections":[{"heading":"...","tells":"one sentence","why":"one sentence or empty if you cannot say"}],'
    '"failures":[{"section":"...","reason":"...","exact_text":"text copied exactly from the page"}]}\n'
    "Use an empty failures list if there are none.\n\nThe page text follows.\n\n-----\n"
)


def page_text(page, url):
    if page.ws is None:
        page.visit("about:blank")  # opens the protocol connection
    page.set_viewport(1280, 900, mobile=False)
    r = page.visit(url)
    page.clear_viewport()
    return re.sub(r"\n{3,}", "\n\n", r.text or "").strip()


def ask(text):
    env = {k: v for k, v in os.environ.items()
           if k not in ("ANTHROPIC_API_KEY", "ANTHROPIC_AUTH_TOKEN", "ANTHROPIC_BASE_URL")}
    with tempfile.TemporaryDirectory(prefix="cold-reader-") as empty:
        p = subprocess.run(
            ["claude", "-p", INSTRUCTION + FORMAT + text, "--model", MODEL,
             "--output-format", "text", "--max-turns", "1"],
            cwd=empty, env=env, capture_output=True, text=True, timeout=300, stdin=subprocess.DEVNULL)
    if p.returncode != 0:
        raise RuntimeError("claude CLI failed (%d): %s" % (p.returncode, (p.stderr or p.stdout)[-400:]))
    return p.stdout


def parse(raw):
    m = re.search(r"\{.*\}", raw, re.S)
    if not m:
        raise RuntimeError("model did not return JSON: " + raw[:300])
    return json.loads(m.group(0))


def norm(s):
    return re.sub(r"\s+", " ", s or "").strip().lower()


def added_text(base):
    """Text this PR adds to pages, scripts and the copy deck, tags stripped."""
    r = subprocess.run(["git", "diff", "-U0", base + "...HEAD", "--", "*.html", "copy.json", "js/*.js"],
                       cwd=HERE, capture_output=True, text=True)
    lines = [l[1:] for l in r.stdout.splitlines() if l.startswith("+") and not l.startswith("+++")]
    return norm(re.sub(r"<[^>]+>", " ", " ".join(lines)).replace("\\u2192", "").replace("\\\"", '"'))


def existed_in(base, name):
    return subprocess.run(["git", "cat-file", "-e", "%s:%s" % (base, name)], cwd=HERE,
                          capture_output=True).returncode == 0


def judge(text, name):
    """Send one page's text to the model; keep only failures whose quote is really on the page."""
    if len(text) < 80:
        return {"page": name, "failures": [{"section": "(whole page)", "reason": "the page rendered almost no visible text",
                                            "exact_text": text}], "sections": []}
    out = parse(ask(text))
    hay = norm(text)
    real = []
    for f in out.get("failures") or []:
        quote = norm(f.get("exact_text"))
        if quote and quote in hay:
            real.append(f)
    return {"page": name, "failures": real, "sections": out.get("sections") or [],
            "dropped_unquotable": len(out.get("failures") or []) - len(real)}


def review(page, base_url, name):
    q = PAGE_QUERY.get(name, "")
    return judge(page_text(page, "%s/%s%s" % (base_url, name, q)), name)


def added_fragments(base):
    """Literal text this PR adds to copy.json (string values), split at template
    placeholders into fragments long enough to recognise on a rendered page."""
    r = subprocess.run(["git", "diff", "-U0", base + "...HEAD", "--", "copy.json"],
                       cwd=HERE, capture_output=True, text=True)
    frags = set()
    for line in r.stdout.splitlines():
        if not line.startswith("+") or line.startswith("+++"):
            continue
        body = line[1:]
        m = re.match(r'\s*"[^"]+"\s*:\s*"(.*)",?\s*$', body) or re.match(r'\s*"(.*)",?\s*$', body)
        if not m:
            continue
        val = m.group(1).replace('\\"', '"')
        for part in re.split(r"\{[^}]*\}", re.sub(r"<[^>]+>", " ", val)):
            part = norm(part)
            if len(part) >= 28:
                frags.add(part)
    return frags


def page_is_affected(name, text, base, frags, html_changed):
    """A page needs reading only if its own html changed or it shows text this PR added."""
    if not existed_in(base, name) or name in html_changed:
        return True
    hay = norm(text)
    return any(f in hay for f in frags)


def self_test():
    """Render tests/jargon_page.html and require the model to flag it."""
    base, stop = serve(HERE)
    try:
        with Page(settle=2.0) as page:
            rep = review(page, base, "tests/jargon_page.html")
    finally:
        stop()
    for f in rep["failures"]:
        print('- [%s] %s\n    exact text: "%s"' % (f.get("section", ""), f.get("reason", ""), f.get("exact_text", "")))
    if not rep["failures"]:
        print("SELF-TEST FAILED: the cold reader found nothing wrong with tests/jargon_page.html")
        return 1
    print("self-test ok: the cold reader flags tests/jargon_page.html (%d failure(s))" % len(rep["failures"]))
    return 0


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", default=os.environ.get("GATE_BASE", "origin/main"))
    ap.add_argument("--all", action="store_true")
    ap.add_argument("--pages", nargs="*")
    ap.add_argument("--base-url")
    ap.add_argument("--json-out")
    ap.add_argument("--self-test", action="store_true")
    ap.add_argument("--list-affected", action="store_true", help="print which pages a PR would have read; no model call")
    ap.add_argument("--changed-only", action="store_true",
                    help="only failures on text this PR adds block; failures on pre-existing text are listed, not blocking")
    a = ap.parse_args()

    if a.self_test:
        try:
            return self_test()
        except Exception as e:
            print("COLD READER COULD NOT RUN: %s" % e)
            return 2

    if a.pages:
        names = a.pages
    elif a.all:
        names = all_pages()
    else:
        names = pages_for_change(changed_files(a.base))
    if not names:
        print("cold reader: no reader-facing page changed, nothing to read")
        return 0

    stop = None
    base_url = a.base_url
    if not base_url:
        base_url, stop = serve(HERE)
    reports = []
    try:
        html_changed = {f for f in changed_files(a.base) if "/" not in f and f.endswith(".html")} if a.changed_only else set()
        frags = added_fragments(a.base) if a.changed_only else set()
        with Page(settle=4.0) as page:
            for name in names:
                try:
                    text = page_text(page, "%s/%s%s" % (base_url, name, PAGE_QUERY.get(name, "")))
                    if a.changed_only and not page_is_affected(name, text, a.base, frags, html_changed):
                        sys.stderr.write("  skip %s: shows none of the text this PR added\n" % name)
                        continue
                    if a.list_affected:
                        print("would read: " + name)
                        continue
                    rep = judge(text, name)
                except Exception as e:  # a gate that cannot run must say so, not pass
                    print("COLD READER COULD NOT RUN on %s: %s" % (name, e))
                    return 2
                reports.append(rep)
                sys.stderr.write("  read %s: %d failure(s)\n" % (name, len(rep["failures"])))
    finally:
        if stop:
            stop()

    if a.json_out:
        json.dump(reports, open(a.json_out, "w"), indent=1)

    if a.changed_only:
        added = added_text(a.base)
        frags = added_fragments(a.base)
        for r in reports:
            if not existed_in(a.base, r["page"]):
                continue  # a new page is read in full
            keep, old = [], []
            for f in r["failures"]:
                q = norm(f.get("exact_text"))
                hit = bool(q) and (q[:50] in added or any(fr in q for fr in frags) or (len(q) >= 14 and any(q in fr for fr in frags)))
                (keep if hit else old).append(f)
            r["failures"], r["preexisting"] = keep, old
        for r in reports:
            if r.get("preexisting"):
                print("note: %s has %d older cold-reader finding(s) on text this PR did not add (not blocking; see SEB-220)"
                      % (r["page"], len(r["preexisting"])))

    bad = [r for r in reports if r["failures"]]
    for r in bad:
        print("\n== %s ==" % r["page"])
        for f in r["failures"]:
            print('- [%s] %s\n    exact text: "%s"' % (f.get("section", ""), f.get("reason", ""), f.get("exact_text", "")))
    if bad:
        print("\nCOLD READER CHECK FAILED: %d failure(s) on %d page(s)" % (sum(len(r["failures"]) for r in bad), len(bad)))
        return 1
    print("cold reader check ok: %d page(s) read cold, no failures" % len(reports))
    return 0


if __name__ == "__main__":
    sys.exit(main())
