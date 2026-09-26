#!/usr/bin/env python3
"""Q2 -- the critic (SPEC-AGENT-2026-09-21).

Once a day, opens the LIVE site in a real browser as a stranger and judges
it, not as a code check: clicks every chip, asks five fresh questions of its
own invention, opens a couple of receipts, walks the nav at desktop and
phone widths. Files real Linear issues, with real screenshots attached,
judged on one rubric -- would this embarrass the site in front of a senior
payments person. Not "did it error". "Is it bad".

Deliberately NOT an agentic `claude -p` loop with Bash/Edit access. This is
"no code access" by construction, not by prompt instruction that could be
argued around: a plain script that can only browse, screenshot, make two
narrowly-scoped model calls, and file a Linear issue. It cannot open a file
in this repo, let alone change one.

    python3 tools/critic.py                 # real run against margin.wiki
    python3 tools/critic.py --dry-run        # everything except filing issues
    python3 tools/critic.py --base-url http://127.0.0.1:8000   # test locally

Stdlib only, plus the same headless CDP client check_page.py/shot.py use.
"""

import argparse
import base64
import json
import os
import random
import subprocess
import sys
import tempfile
import urllib.error
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from headless import Page  # noqa: E402

ANTHROPIC_URL = "https://api.anthropic.com/v1/messages"
ANTHROPIC_VERSION = "2023-06-01"
MODEL = "claude-sonnet-5"
LIVE_BASE = "https://margin.wiki"
SCREENSHOT_DIR = os.environ.get("CRITIC_SHOT_DIR", tempfile.mkdtemp(prefix="critic-"))

RUBRIC = (
    "Would this embarrass the site in front of a senior payments person -- "
    "someone who has run a remittance or FX desk and would recognise a "
    "wrong number, a broken promise, or amateurish copy in one glance? Judge "
    "\"is it bad\", not \"did it technically error\". A page that loads with "
    "no console error can still be a bad answer, a confusing layout, or a "
    "claim the data doesn't support."
)


def log(msg):
    print("[critic] %s" % msg, file=sys.stderr, flush=True)


def anthropic_call(system, user_content, max_tokens=1200, timeout=60):
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        sys.exit("ANTHROPIC_API_KEY is not set -- the critic has nothing to judge with")
    body = json.dumps({
        "model": MODEL, "max_tokens": max_tokens, "system": system,
        "messages": [{"role": "user", "content": user_content}],
    }).encode()
    req = urllib.request.Request(
        ANTHROPIC_URL, data=body, method="POST",
        headers={"x-api-key": api_key, "anthropic-version": ANTHROPIC_VERSION,
                 "content-type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            payload = json.loads(r.read())
    except urllib.error.HTTPError as e:
        sys.exit("Anthropic call failed: HTTP %s %s" % (e.code, e.read().decode()[:300]))
    return "".join(b.get("text", "") for b in payload.get("content", []) if b.get("type") == "text")


def image_block(path):
    with open(path, "rb") as f:
        data = base64.b64encode(f.read()).decode()
    return {"type": "image", "source": {"type": "base64", "media_type": "image/png", "data": data}}


def click_chip(p, index, input_id="askInput", btn_id="askBtn", answer_id="answerBox"):
    expr = """
    (function(){
      var chips = document.querySelectorAll('.chip');
      if (!chips[%d]) return null;
      var label = chips[%d].textContent;
      chips[%d].click();
      var box = document.getElementById(%s);
      return JSON.stringify({label: label, answer: box.textContent});
    })()
    """ % (index, index, index, json.dumps(answer_id))
    raw = p.eval_js(expr)
    return json.loads(raw) if raw else None


def ask_freetext(p, question, input_id="askInput", btn_id="askBtn", answer_id="answerBox", wait_ms=6000):
    expr = """
    (async function(){
      document.getElementById(%s).value = %s;
      document.getElementById(%s).click();
      await new Promise(function(r){ setTimeout(r, %d); });
      var box = document.getElementById(%s);
      return JSON.stringify({question: %s, answer: box.textContent});
    })()
    """ % (json.dumps(input_id), json.dumps(question), json.dumps(btn_id), wait_ms,
           json.dumps(answer_id), json.dumps(question))
    raw = p.eval_js(expr, await_promise=True)
    return json.loads(raw) if raw else None


def gen_fresh_questions(coverage_line):
    system = ("You write five short, natural questions a genuinely curious first-time "
              "visitor might type into a site's ask box, given only its stated capability "
              "line below. Mix it up: one plainly answerable, one about an untracked "
              "country, one with a typo, one about how something works, one adversarial "
              "or odd. Output exactly five, one per line, no numbering, no quotes.")
    text = anthropic_call(system, coverage_line, max_tokens=300)
    qs = [l.strip() for l in text.strip().split("\n") if l.strip()]
    return qs[:5]


def judge_transcript(observations, screenshot_paths):
    system = (
        "You are a strict but fair critic of a live public website, margin.wiki, which "
        "measures what a dollar really costs in dozens of countries and answers questions "
        "about it live. Rubric: " + RUBRIC + "\n\n"
        "You are given a transcript of real interactions (chips clicked, questions asked, "
        "answers received) and real screenshots of the site at different pages and widths. "
        "Find genuine problems only -- a wrong or confusing answer, a broken layout, a "
        "claim not backed by what's shown, jargon a normal reader wouldn't parse, anything "
        "that would make a payments professional roll their eyes. Do not invent problems to "
        "have something to say; if everything you saw was genuinely fine, say so.\n\n"
        "Output strict JSON: {\"issues\": [{\"title\": \"...\", \"body\": \"what you saw, "
        "plainly, and why it's bad\", \"screenshot_index\": <int or null>}]}. "
        "Empty issues array if nothing embarrassing was found."
    )
    content = [{"type": "text", "text": observations}]
    for sp in screenshot_paths:
        content.append(image_block(sp))
    text = anthropic_call(system, content, max_tokens=8000, timeout=180)
    try:
        start = text.index("{")
        return json.loads(text[start:])
    except (ValueError, json.JSONDecodeError):
        log("judge response was not parseable JSON, treating as no issues found: %r" % text[:300])
        return {"issues": []}


def run(base_url, dry_run):
    shots = []
    transcript = []

    with Page() as p:
        # ---- Home: the corridor-finding front page. No ask box here since
        # the v1-freeze rebuild split it out to ask.html -- just judge the
        # page itself loads clean. ----
        p.visit(base_url + "/index.html")
        home_shot = os.path.join(SCREENSHOT_DIR, "home.png")
        p.screenshot(home_shot)
        shots.append(home_shot)
        headline = p.eval_js("(document.getElementById('heroHeadline')||{}).textContent || ''")
        transcript.append("HOME PAGE loaded. Headline: %s" % headline)
        if p.errors:
            transcript.append("Console errors on home page: %r" % p.errors[:5])

        # ---- Ask page: chips, real answers ----
        p.visit(base_url + "/ask.html")
        ask_shot = os.path.join(SCREENSHOT_DIR, "ask.png")
        p.screenshot(ask_shot)
        shots.append(ask_shot)
        coverage = p.eval_js("(document.getElementById('coverage')||{}).textContent || ''")
        transcript.append("ASK PAGE loaded. Coverage line: %s" % coverage)

        chip_count = int(p.eval_js("document.querySelectorAll('.chip').length") or 0)
        for i in range(chip_count):
            res = click_chip(p, i)
            if res:
                transcript.append("CHIP %r -> %r" % (res["label"], res["answer"][:300]))
        chip_shot = os.path.join(SCREENSHOT_DIR, "ask-after-chip.png")
        p.screenshot(chip_shot)
        shots.append(chip_shot)

        # ---- Five fresh questions, of the critic's own invention ----
        try:
            fresh = gen_fresh_questions(coverage or "prices in dozens of countries, sending money, how it works")
        except SystemExit:
            raise
        for q in fresh:
            res = ask_freetext(p, q)
            if res:
                transcript.append("FREE TEXT (critic's own) %r -> %r" % (q, res["answer"][:400]))
        freetext_shot = os.path.join(SCREENSHOT_DIR, "ask-after-freetext.png")
        p.screenshot(freetext_shot)
        shots.append(freetext_shot)
        if p.errors:
            transcript.append("Console errors on ask page: %r" % p.errors[:5])

        # ---- Open a receipt: whichever country the widest-gap chip named ----
        widest_ccy = p.eval_js("""
          (function(){
            var links = document.querySelectorAll('a[href*="country.html"]');
            for (var i=0;i<links.length;i++){
              var m = links[i].href.match(/ccy=([A-Z]{3})/);
              if (m) return m[1];
            }
            return null;
          })()
        """)
        if widest_ccy:
            p.visit(base_url + "/country.html?ccy=" + widest_ccy)
            receipt_shot = os.path.join(SCREENSHOT_DIR, "receipt.png")
            p.screenshot(receipt_shot)
            shots.append(receipt_shot)
            receipt_text = p.eval_js("document.body.innerText.slice(0, 800)")
            transcript.append("RECEIPT page for %s: %s" % (widest_ccy, receipt_text))
            if p.errors:
                transcript.append("Console errors on receipt page: %r" % p.errors[:5])

        # ---- How it works: its own ask box ----
        p.visit(base_url + "/how-it-works.html")
        placeholder = p.eval_js("(document.getElementById('hiwAskInput')||{}).placeholder || ''")
        res = ask_freetext(p, "how any number was made", "hiwAskInput", "hiwAskBtn", "hiwAnswer")
        if res:
            transcript.append("HOW-IT-WORKS placeholder question (%r) -> %r" % (placeholder, res["answer"][:400]))
        hiw_shot = os.path.join(SCREENSHOT_DIR, "how-it-works.png")
        p.screenshot(hiw_shot)
        shots.append(hiw_shot)

        # ---- Walk the nav, desktop width, each page loads clean ----
        nav_pages = ["the-index.html", "sending-money.html", "findings.html", "machine-room.html"]
        for np in nav_pages:
            p.visit(base_url + "/" + np)
            if p.errors:
                transcript.append("Console errors on %s (desktop): %r" % (np, p.errors[:5]))

        # ---- Phone width: home page only, to keep this fast and cheap ----
        p.visit(base_url + "/index.html")
        p.set_viewport(390, 844, mobile=True)
        mobile_shot = os.path.join(SCREENSHOT_DIR, "home-mobile.png")
        p.screenshot(mobile_shot, full=False)
        p.clear_viewport()
        shots.append(mobile_shot)
        transcript.append("Walked nav_pages=%r at desktop width; captured home at 390x844 (phone)." % nav_pages)

    observations = "\n\n".join(transcript)
    log("collected %d observations, %d screenshots" % (len(transcript), len(shots)))

    verdict = judge_transcript(observations, shots)
    issues = verdict.get("issues", [])
    log("judge found %d issue(s)" % len(issues))

    if dry_run:
        print(json.dumps(verdict, indent=2))
        return

    for issue in issues:
        title = issue.get("title", "Critic finding")
        body = issue.get("body", "")
        si = issue.get("screenshot_index")
        shot_path = shots[si] if isinstance(si, int) and 0 <= si < len(shots) else None
        asset_line = ""
        if shot_path:
            try:
                url = subprocess.check_output(
                    ["python3", os.path.join(HERE, "..", "agents", "linear.py"), "attach", shot_path],
                    text=True).strip()
                asset_line = "\n\n![screenshot](%s)" % url
            except subprocess.CalledProcessError as e:
                log("could not attach screenshot: %s" % e)
        full_body = body + asset_line
        out = subprocess.check_output(
            ["python3", os.path.join(HERE, "..", "agents", "linear.py"), "new", title,
             "--body", full_body, "--role", "critic", "--label", "critic-finding"],
            text=True).strip()
        log("filed: %s -- %s" % (out, title))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--base-url", default=LIVE_BASE)
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args()
    run(a.base_url.rstrip("/"), a.dry_run)


if __name__ == "__main__":
    main()
