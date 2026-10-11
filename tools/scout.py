#!/usr/bin/env python3
"""The Scout (SEB-301). Once a week it picks ONE thing worth doing and writes
the spec into the standing issue SEB-300, where the builder (tools/one_call.py)
picks it up.

    python3 tools/scout.py              # a real run
    python3 tools/scout.py --dry-run    # one model call, prints the spec and the checks, writes nothing to Linear
    python3 tools/scout.py --self-test  # no network, no model

Inputs, and nothing else:
  - the output of `tools/analyst.py --dry-run --no-model` (numbers the analyst
    computed from the CSVs), and
  - the countries with no price this hour, from data/index_latest.json.
The prompt is built only from those two, plus a fixed instruction. No .md file
is ever sent to a model.

One Sonnet call (the newest anthropic/claude-sonnet on OpenRouter, resolved by
tools/llm.py; it fails loudly if there is none) picks one item and writes a
spec with a `## Files` section. The spec is posted only if every check passes:
  - every number in it traces to a number the analyst computed (the analyst's
    own number check, tools/analyst.py untraced_numbers);
  - every listed file exists and is a file the builder may change;
  - the files together stay under the size limit (80,000 characters).
If a check fails nothing is posted and the reason goes in data/scout_log.csv.
If SEB-300 is not Done, the week is skipped.

Env: OPENROUTER_API_KEY, LINEAR_API_KEY.
"""
import csv
import json
import os
import re
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "tools"))
sys.path.insert(0, os.path.join(ROOT, "agents"))
import analyst  # noqa: E402
import llm  # noqa: E402

JOB = "SEB-300"
LABEL = "one-call"
LOG = os.path.join(ROOT, "data", "scout_log.csv")
LOG_HEADER = ["ts_utc", "mode", "status", "detail", "item", "cost_usd"]
INDEX_LATEST = os.path.join(ROOT, "data", "index_latest.json")
MAX_FILES_CHARS = 80_000         # all listed files together; the builder sends them whole and its prompt limit is 100,000
MAX_TOKENS = 2500
# Files the builder may never be asked to change: agent code, checks, workflows,
# and the words (copy.json goes through the writer and Seb's approval).
FORBIDDEN = (".github/", "agents/", "tools/check_", "tools/llm.py", "tools/scout.py",
             "tools/one_call.py", "tools/analyst.py", "tools/audit_numbers.py", "copy.json",
             "METHODOLOGY.md", "CLAUDE.md")
# Where things live, so a spec can name real files. Checked against the repo in --self-test.
WHERE = {
    "collector_basis.py": "exchange order books and broker quotes, written to data/basis.csv",
    "collector_p2p.py": "Binance person-to-person boards, written to data/p2p_basis.csv",
    "collector_p2p_okx.py": "OKX person-to-person boards, written to data/p2p_okx.csv",
    "tools/emit_countries.py": "builds each country's price and the reason a country has none",
}

SYSTEM = """You write one job spec for a small static website that prices a dollar in about 60 countries.
You get numbers computed by code from the site's data files, and the list of countries with no price this hour.
Pick ONE item: a country with no price that needs a source, or a finding worth publishing. Write the spec for it.
Rules:
- Use no number except those in the data you were given. Do not estimate, round up or invent any.
- Write the spec in markdown: a title line starting with '# ', then '## Why' (two to four sentences), '## What to build', '## Files', '## Context' (optional), '## Done when'.
- '## Files' lists, one per line, each in backticks, the files the builder may change. '## Context' lists read-only files the same way.
- The builder is sent every listed file whole, and all of them together must stay under 80,000 characters. List only small files. Never list a data/*.csv or any large data file.
- Do not count, add, subtract or round anything yourself. Quote a number from the data exactly as given, or use none.
- Name only real files. Where things live:
%s
- Never list anything under .github/ or agents/, any tools/check_*.py, llm.py, scout.py, one_call.py, analyst.py, audit_numbers.py, copy.json, METHODOLOGY.md or CLAUDE.md.
- Write no words for the site. If the job needs reader-facing words, say they go through the writer.
- Say what is NOT to be done if it matters. Short sentences, plain words, no em-dashes.
""" % "\n".join("  - `%s`: %s" % kv for kv in WHERE.items())


def log_row(mode, status, detail, item="", cost=0.0):
    new = not os.path.exists(LOG)
    with open(LOG, "a", newline="") as f:
        w = csv.writer(f)
        if new:
            w.writerow(LOG_HEADER)
        w.writerow([llm.now().isoformat(), mode, status, detail[:500].replace("\n", " "), item, "%.6f" % cost])


# ---------- inputs ----------

def analyst_findings():
    """The analyst's new findings, from its own dry run. No model, no writes."""
    r = subprocess.run([sys.executable, os.path.join(ROOT, "tools", "analyst.py"), "--dry-run", "--no-model"],
                       cwd=ROOT, capture_output=True, text=True, timeout=600)
    if r.returncode != 0:
        raise SystemExit("analyst.py --dry-run failed: %s" % (r.stderr or r.stdout)[-400:])
    out = r.stdout
    i = out.find("\n[")
    return json.loads(out[i + 1:]) if i >= 0 else []


def no_price_countries(path=INDEX_LATEST):
    with open(path) as f:
        return json.load(f).get("withheld") or []


def numbers_for(findings, withheld):
    """Every number the prompt contains, as one dict, so the spec can be held to it."""
    nums = {"no_price_count": len(withheld)}
    for f in findings:
        for k, v in (f.get("numbers") or {}).items():
            nums["%s.%s" % (f["id"], k)] = v
    for w in withheld:
        for j, tok in enumerate(re.findall(r"\d[\d,]*(?:\.\d+)?", w.get("reason_raw") or "")):
            nums["%s.n%d" % (w["ccy"], j)] = float(tok.replace(",", ""))
    return nums


def build_prompt(findings, withheld):
    parts = ["FINDINGS FROM THE ANALYST (numbers computed by code):"]
    if findings:
        for f in findings:
            parts.append(json.dumps({"id": f["id"], "kind": f["kind"], "subject": f["subject"],
                                     "numbers": f["numbers"], "files": f["evidence"]["files"]}, sort_keys=True))
    else:
        parts.append("(none this week)")
    parts.append("COUNTRIES WITH NO PRICE THIS HOUR (%d):" % len(withheld))
    for w in withheld:
        parts.append("%s | %s | %s | %s" % (w["ccy"], w["country"], w.get("reason_raw") or w.get("reason"),
                                           w.get("source_file") or ""))
    return "\n".join(parts)


# ---------- the checks a spec must pass ----------

def listed(spec, heading):
    m = re.search(r"^##\s*%s\s*$(.*?)(?=^##\s|\Z)" % heading, spec, re.M | re.S | re.I)
    return re.findall(r"`([^`\s]+)`", m.group(1)) if m else []


def validate(spec, numbers, root=ROOT):
    """Reasons the spec may not be posted. Empty means it may."""
    reasons = []
    files, context = listed(spec, "Files"), listed(spec, "Context")
    if not files:
        reasons.append("no `## Files` section with backticked paths")
    total = 0
    for p in files + context:
        full = os.path.join(root, p)
        if p.startswith("/") or ".." in p.split("/"):
            reasons.append("path outside the repo: %s" % p)
        elif not os.path.isfile(full):
            reasons.append("file does not exist: %s" % p)
        elif os.path.isfile(full):
            total += os.path.getsize(full)
    for p in files:
        if any(p.startswith(x) or p == x for x in FORBIDDEN):
            reasons.append("the builder may not change %s" % p)
    if total > MAX_FILES_CHARS:
        reasons.append("listed files total %d bytes, over the %d limit" % (total, MAX_FILES_CHARS))
    text = re.sub(r"`[^`]*`", " ", spec)            # paths and code are labels, not statistics
    for tok in analyst.untraced_numbers(text, numbers):
        reasons.append("number %s does not trace to a number the analyst computed" % tok)
    return reasons


# ---------- Linear ----------

def post_spec(spec):
    import linear
    i = linear.find(JOB)
    st = linear.states()
    linear.call("""mutation($id: String!, $d: String!, $s: String!) {
      issueUpdate(id: $id, input: { description: $d, stateId: $s }) { success }
    }""", {"id": i["id"], "d": spec, "s": st["Todo"]["id"]})
    linear.call("""mutation($id: String!, $l: String!) {
      issueAddLabel(id: $id, labelId: $l) { success }
    }""", {"id": i["id"], "l": linear._label_id(LABEL)})


def job_state():
    import linear
    i = linear.find(JOB)
    return i["state"]["name"], i["state"]["type"]


# ---------- main ----------

def run(dry):
    mode = "dry-run" if dry else "run"
    name, typ = job_state()
    if typ != "completed":
        log_row(mode, "skipped", "%s is %s, not Done" % (JOB, name))
        print("skipped: %s is %s, not Done" % (JOB, name))
        return 0
    findings, withheld = analyst_findings(), no_price_countries()
    if not findings and not withheld:
        log_row(mode, "nothing", "no analyst findings and no country without a price")
        print("nothing to pick from")
        return 0
    prompt = build_prompt(findings, withheld)
    numbers = numbers_for(findings, withheld)
    model = llm.resolve_sonnet()
    before = len(llm.LOGGED)
    text, row = llm.complete([{"role": "system", "content": SYSTEM}, {"role": "user", "content": prompt}],
                             models_to_try=[model], issue=JOB + "/scout", max_tokens=MAX_TOKENS)
    cost = sum(float(r["cost_usd"]) for r in llm.LOGGED[before:])
    spec = text.strip()
    title = next((l[2:].strip() for l in spec.splitlines() if l.startswith("# ")), "")
    reasons = validate(spec, numbers)
    print("model: %s | prompt: %d characters | cost: $%.4f" % (model, len(prompt), cost))
    print("\n----- SPEC -----\n%s\n----- END -----" % spec)
    if reasons:
        log_row(mode, "rejected", "; ".join(reasons), title, cost)
        print("NOT POSTED. Checks failed:\n- " + "\n- ".join(reasons))
        return 0
    if dry:
        log_row(mode, "dry-run-pass", "all checks passed, nothing posted", title, cost)
        print("All checks passed. Dry run: nothing posted.")
        return 0
    post_spec(spec + "\n\n*Written by the Scout on %s. Every number traces to the analyst's output.*\n" % llm.now().date().isoformat())
    log_row(mode, "posted", "spec written into %s, set to Todo, labelled %s" % (JOB, LABEL), title, cost)
    print("posted into %s" % JOB)
    return 0


def self_test():
    import tempfile
    for rel in WHERE:
        assert os.path.isfile(os.path.join(ROOT, rel)), "WHERE names a file that is not in the repo: " + rel
    numbers = {"no_price_count": 13, "TRY.n0": 3.0}
    with tempfile.TemporaryDirectory() as d:
        os.makedirs(os.path.join(d, "tools"))
        open(os.path.join(d, "a.py"), "w").write("x = 1\n")
        open(os.path.join(d, "big.py"), "w").write("x" * (MAX_FILES_CHARS + 1))
        open(os.path.join(d, "ctx.csv"), "w").write("a\n")
        good = "# Add a source\n\n## Why\n13 countries have no price.\n\n## Files\n`a.py`\n\n## Context\n`ctx.csv`\n\n## Done when\nIt works.\n"
        assert validate(good, numbers, d) == [], validate(good, numbers, d)
        cases = {
            "invented number": good.replace("13 countries", "14 countries"),
            "no Files section": good.replace("## Files\n`a.py`", "## Files\nnone"),
            "missing file": good.replace("`a.py`", "`nope.py`"),
            "oversize file": good.replace("`a.py`", "`big.py`"),
            "forbidden file": good.replace("`a.py`", "`copy.json`"),
            "path escape": good.replace("`a.py`", "`../x.py`"),
            "missing context": good.replace("`ctx.csv`", "`gone.csv`"),
        }
        for name, spec in cases.items():
            r = validate(spec, numbers, d)
            assert r, "%s was not rejected" % name
        open(os.path.join(d, "copy.json"), "w").write("{}")
        assert any("may not change" in x for x in validate(cases["forbidden file"], numbers, d))
    p = build_prompt([], [{"ccy": "TRY", "country": "Turkey", "reason_raw": "3 ads, 10 required", "source_file": "data/p2p_basis.csv"}])
    assert "TRY | Turkey" in p and ".md" not in p
    assert numbers_for([], [{"ccy": "TRY", "reason_raw": "3 ads, 10 required"}]) == {"no_price_count": 1, "TRY.n0": 3.0, "TRY.n1": 10.0}
    print("scout self-test: ok")


if __name__ == "__main__":
    if "--self-test" in sys.argv:
        self_test()
        sys.exit(0)
    try:
        code = run("--dry-run" in sys.argv)
    except llm.LLMError as e:
        print("SCOUT FAILED: %s" % e, file=sys.stderr)
        log_row("dry-run" if "--dry-run" in sys.argv else "run", "failed", str(e))
        code = 1
    sys.exit(code)
