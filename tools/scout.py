#!/usr/bin/env python3
"""The Scout (SEB-301). Once a week it picks ONE thing worth doing and writes
the spec into the standing issue SEB-300, where the builder (tools/one_call.py)
picks it up.

    python3 tools/scout.py              # a real run
    python3 tools/scout.py --dry-run    # one model call and the probes, prints the spec, writes nothing to Linear
    python3 tools/scout.py --self-test  # no network, no model

Inputs come only from code, computed from the CSVs:
  1. the coverage list: markets priced from a single source (one exchange order
     book, one broker, or one person-to-person board);
  2. source pairs that disagree: the analyst's board disagreements, and the
     countries where exchange prices and person-to-person prices sit apart;
  3. findings whose recheck says they no longer hold: claims that
     tools/audit_claims.py (data/claims_status.json) marks ok:false.
No .md file is ever sent to a model, and the prompt is built from these three only.

One Sonnet call (the newest anthropic/claude-sonnet on OpenRouter, resolved by
tools/llm.py; it fails loudly if there is none) picks the top item and writes a
build spec with a `## Files` section. It never writes reader-facing words: a
spec may not list a page, a stylesheet, a script or copy.json. For a new source
it only suggests venues, in a `## Venues` section, and each one must pass the
existing source probe (tools/probe_source.py) before the spec is posted.

The spec is posted only if every check passes:
  - every number in it traces to a number the analyst's number check allows;
  - every listed file exists and is a file the builder may change;
  - the files together stay under the size limit (120,000 characters);
  - every suggested venue is for a single-source market and passes the probe.
If a check fails nothing is posted and the reason goes in data/scout_log.csv.
The Scout never hands the builder a job that changes how a published number is
computed (a spec that lists an emitter in tools/check_method_change.py or a
collector, or says "Method change: yes"). That spec goes into SEB-300 labelled
`needs-claude` instead of `one-call`, for a chat session to do with METHODOLOGY.md.
The week is skipped only if SEB-300 is still open and not labelled `needs-claude`.

Env: OPENROUTER_API_KEY, LINEAR_API_KEY.
"""
import csv
import json
import os
import re
import glob
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "tools"))
sys.path.insert(0, os.path.join(ROOT, "agents"))
import analyst  # noqa: E402
import llm  # noqa: E402

JOB = "SEB-300"
READY_TARGET = 3


def ready_jobs():
    """Jobs the Aider builder can take now: not done, blocked or built, with files, no track or `track: aider`."""
    import backlog
    items = backlog.parse(open(backlog.PATH).read())
    return sum(1 for it in items if not it["done"] for j in it["jobs"]
               if not j["done"] and not j["blocked"] and not j["built"] and j["files"] and j["track"] in ("", "aider"))
LABEL = "one-call"
STUCK_LABEL = "needs-claude"
LOG = os.path.join(ROOT, "data", "scout_log.csv")
LOG_HEADER = ["ts_utc", "mode", "status", "detail", "item", "cost_usd"]
DATA = os.path.join(ROOT, "data")
INDEX_LATEST = os.path.join(DATA, "index_latest.json")
CLAIMS_STATUS = os.path.join(DATA, "claims_status.json")
EMITTERS_FILE = os.path.join(ROOT, "tools", "check_method_change.py")
EMITTER_FILE = os.path.join(ROOT, "tools", "emit_countries.py")
EXCHANGE_P2P_GAP_PTS = 2.0      # an exchange price and a person-to-person price this far apart (points) count as a disagreement
MAX_FILES_CHARS = 120_000        # all listed files together (120 KB); the builder sends them whole, and its prompt limit (tools/llm.py) is 130,000 so the spec and instructions fit beside them
MAX_TOKENS = 2500
# Files the builder may never be asked to change: agent code, checks, workflows,
# and the words (copy.json goes through the writer and Seb's approval).
FORBIDDEN = (".github/", "agents/", "tools/check_", "tools/llm.py", "tools/scout.py",
             "tools/one_call.py", "tools/analyst.py", "tools/audit_numbers.py", "tools/audit_claims.py",
             "copy.json", "claims.json", "METHODOLOGY.md", "CLAUDE.md", "js/", "css/")
FORBIDDEN_SUFFIX = (".html", ".css")      # reader-facing pages: the Scout never touches them
# Where things live, so a spec can name real files. Checked against the repo in --self-test.
WHERE = {
    "collector_basis.py": "exchange order books and broker quotes, written to data/basis.csv",
    "collector_p2p.py": "Binance person-to-person boards, written to data/p2p_basis.csv",
    "collector_p2p_okx.py": "OKX person-to-person boards, written to data/p2p_okx.csv",
    "tools/emit_countries.py": "builds each country's price and the reason a country has none",
}

SYSTEM = """You write one build spec for a small static website that prices a dollar in about 60 countries.
You get three lists computed by code from the site's data files: markets priced from a single source, source pairs that disagree, and claims that no longer hold.
Pick the ONE item most worth building this week and write the spec for it.
Rules:
- Use no number except those in the data you were given. Do not count, add, subtract or round anything yourself. Quote a number exactly as given, or use none. Write any other quantity in words ("two decimals", "one file", "the five amounts"), never in digits: every digit in the spec is checked against the data. That includes digits inside words: write person-to-person, never "P2P".
- Binance and OKX person-to-person prices are combined only where they are within 3 percent of each other (METHODOLOGY.md, v1.2). Where they differ by more, they are kept apart on purpose. A pair that disagrees by more than that is NOT a missing second source: never propose combining them, averaging them or lowering that bar. Propose a venue to probe, a check, or a fix to a claim instead.
- Never pick a job that changes how a published number is computed (how a country's price, a route's cost or a finding's number is built, or which sources feed it). If the best item is one, still write the spec, and put the line `Method change: yes` under '## Why'. It then goes to a person, not the builder.
- You never write reader-facing words. Never list a page, a stylesheet, a script or copy.json. If the job needs words, say they go through the writer.
- Write the spec in markdown: a title line starting with '# ', then '## Why' (two to four sentences), '## What to build', '## Files', '## Context' (optional), '## Done when', and '## Venues' only if the job is a new source.
- '## Files' lists, one per line, each in backticks, the files the builder may change. '## Context' lists read-only files the same way.
- The builder is sent every listed file whole, and all of them together must stay under 120,000 characters. List only small files. Never list a data/*.csv or any large data file.
- For a new source, only suggest venues. In '## Venues', one per line: `CCY` | `https://full-api-url` | `dotted.path.to.the.price.field`. The URL must return JSON with the price of one US dollar (or one dollar stablecoin) in that currency. The CCY must be one of the single-source markets you were given. Each venue is checked by a probe against an independent rate, and the spec is dropped if any fails. Suggest only venues you are sure exist.
- Name only real files. Where things live:
%s
- Never list anything under .github/, agents/, js/ or css/, any tools/check_*.py, llm.py, scout.py, one_call.py, analyst.py, audit_numbers.py, audit_claims.py, claims.json, METHODOLOGY.md or CLAUDE.md.
- Say what is NOT to be done if it matters. Short sentences, plain words, no em-dashes.
""" % "\n".join("  - `%s`: %s" % kv for kv in WHERE.items())


def log_row(mode, status, detail, item="", cost=0.0):
    new = not os.path.exists(LOG)
    with open(LOG, "a", newline="") as f:
        w = csv.writer(f)
        if new:
            w.writerow(LOG_HEADER)
        w.writerow([llm.now().isoformat(), mode, status, detail[:500].replace("\n", " "), item, "%.6f" % cost])


# ---------- inputs: all computed by code from the CSVs ----------

def _load(path):
    with open(path) as f:
        return json.load(f)


def single_source_markets(data=DATA):
    """Markets that have a price now, from one source only."""
    out = []
    idx = _load(os.path.join(data, "index_latest.json"))["countries"]
    for c in idx:
        cls = c.get("source_class")
        n = c.get("n_sources")
        if cls == "p2p_buy_median":
            doc_path = os.path.join(data, "countries", "%s.json" % c["ccy"])
            n = (_load(doc_path).get("n_boards") if os.path.exists(doc_path) else None) or 1
            if n != 1:
                continue
        elif cls == "p2p_fallback":
            n = 1
        elif cls in ("order_book_single", "broker_single"):
            n = 1
        else:
            continue
        out.append({"ccy": c["ccy"], "country": c["country"], "source_class": cls,
                    "sources": n, "source_file": c.get("source_file")})
    return sorted(out, key=lambda x: x["ccy"])


def disagreeing_pairs(data=DATA):
    """Source pairs that disagree: the analyst's two-board gaps, and countries where
    exchange prices and person-to-person prices sit apart by EXCHANGE_P2P_GAP_PTS or more."""
    out = []
    country_files = sorted(f for f in glob.glob(os.path.join(data, "countries", "*.json")) if " " not in os.path.basename(f))
    as_of = max(_load(f)["history"][-1]["date"] for f in country_files if _load(f).get("history"))
    for f in analyst.investigate_boards_disagree(as_of, 1.0):
        out.append({"pair": "binance_vs_okx", "ccy": f["subject"], **f["numbers"]})
    for f in country_files:
        d = _load(f)
        b = d.get("p2p_beside")
        if b and d.get("index_pct") is not None and b.get("index_pct") is not None:
            gap = round(abs(b["index_pct"] - d["index_pct"]), 2)
            if gap >= EXCHANGE_P2P_GAP_PTS:
                out.append({"pair": "exchange_vs_p2p", "ccy": d["ccy"], "exchange_pct": round(d["index_pct"], 2),
                            "p2p_pct": round(b["index_pct"], 2), "gap_points": gap})
    return out


def failing_claims(data=DATA):
    """Claims the hourly recheck (tools/audit_claims.py) says no longer hold."""
    doc = _load(os.path.join(data, "claims_status.json"))
    return [{"claim": k, "value": v.get("value")} for k, v in sorted(doc["claims"].items()) if not v.get("ok")]


def standing_rules(path=EMITTER_FILE):
    """The rules the method already has, read from the code that applies them, so the Scout can quote them."""
    m = re.search(r"^SECOND_BOARD_MAX_GAP\s*=\s*([0-9.]+)", open(path).read(), re.M)
    assert m, "SECOND_BOARD_MAX_GAP not found in " + path
    return [{"rule": "binance_and_okx_boards_are_combined_only_within_this_many_percent", "percent": round(float(m.group(1)) * 100, 6)}]


def gather():
    return {"single_source_markets": single_source_markets(),
            "disagreeing_pairs": disagreeing_pairs(),
            "failing_claims": failing_claims(),
            "standing_rules": standing_rules()}


def numeric_leaves(x, prefix="n"):
    """Every number in the inputs, as a flat dict, so the spec can be held to it. Counts included."""
    out = {}
    if isinstance(x, bool) or x is None:
        return out
    if isinstance(x, (int, float)):
        out[prefix] = x
    elif isinstance(x, dict):
        for k, v in x.items():
            out.update(numeric_leaves(v, "%s.%s" % (prefix, k)))
    elif isinstance(x, list):
        out["%s.count" % prefix] = len(x)
        for i, v in enumerate(x):
            out.update(numeric_leaves(v, "%s[%d]" % (prefix, i)))
    return out


def build_prompt(inputs):
    parts = []
    for name, items in inputs.items():
        parts.append("%s (%d):" % (name.upper(), len(items)))
        parts.extend(json.dumps(i, sort_keys=True) for i in items) if items else parts.append("(none)")
    return "\n".join(parts)


# ---------- the checks a spec must pass ----------

def listed(spec, heading):
    m = re.search(r"^##\s*%s\s*$(.*?)(?=^##\s|\Z)" % heading, spec, re.M | re.S | re.I)
    return re.findall(r"`([^`\s]+)`", m.group(1)) if m else []


def validate(spec, numbers, root=ROOT, markets=None, probe_fn=None):
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
        if p.endswith(FORBIDDEN_SUFFIX):
            reasons.append("the Scout never touches reader-facing pages: %s" % p)
        elif any(p.startswith(x) or p == x for x in FORBIDDEN):
            reasons.append("the builder may not change %s" % p)
    if total > MAX_FILES_CHARS:
        reasons.append("listed files total %d bytes, over the %d limit" % (total, MAX_FILES_CHARS))
    text = re.sub(r"`[^`]*`", " ", spec)            # paths and code are labels, not statistics
    for tok in analyst.untraced_numbers(text, numbers):
        reasons.append("number %s does not trace to a number the analyst computed" % tok)
    reasons += check_venues(spec, markets, probe_fn)
    return reasons


def venues(spec):
    """(ccy, url, field) from the `## Venues` section: CCY | URL | field, each in backticks."""
    m = re.search(r"^##\s*Venues\s*$(.*?)(?=^##\s|\Z)", spec, re.M | re.S | re.I)
    out = []
    for line in (m.group(1).splitlines() if m else []):
        parts = re.findall(r"`([^`]+)`", line)
        if len(parts) == 3:
            out.append(tuple(p.strip() for p in parts))
        elif line.strip(" -*"):
            out.append((line.strip(),))       # malformed: rejected below
    return out


def check_venues(spec, markets, probe_fn=None):
    """Every suggested venue is for a single-source market and passes tools/probe_source.py."""
    reasons = []
    vs = venues(spec)
    if not vs:
        return reasons
    ccys = {m["ccy"] for m in (markets or [])}
    if probe_fn is None:
        import probe_source   # needs `requests`; scout.yml installs it
        probe_fn = probe_source.probe
    for v in vs:
        if len(v) != 3:
            reasons.append("venue line is not `CCY` | `url` | `field`: %s" % v[0][:80])
            continue
        ccy, url, field = v
        if ccy not in ccys:
            reasons.append("venue for %s, which is not a single-source market" % ccy)
            continue
        if not url.startswith("https://"):
            reasons.append("venue url for %s is not https: %s" % (ccy, url[:80]))
            continue
        r = probe_fn(ccy, url, field)
        if not r.get("accepted"):
            reasons.append("probe rejected %s %s: %s" % (ccy, url, (r.get("check") or "")[:200]))
    return reasons


def method_emitters(path=EMITTERS_FILE):
    """The files whose output is a published number, read from the method-change check."""
    block = re.search(r"^EMITTERS\s*=\s*\{(.*?)^\}", open(path).read(), re.M | re.S)
    return set(re.findall(r'^\s*"([^"]+)"\s*:', block.group(1), re.M)) if block else set()


def changes_method(spec, emitters=None):
    """True if the job changes how a published number is computed: it lists an emitter or a collector, or says so."""
    emitters = method_emitters() if emitters is None else emitters
    files = listed(spec, "Files")
    return (any(p in emitters or re.match(r"collector[^/]*\.py$", p) for p in files)
            or bool(re.search(r"^\W*method change:\s*yes", spec, re.M | re.I)))


# ---------- Linear ----------

def post_spec(spec, method=False):
    """Write the spec into SEB-300. A method job gets `needs-claude`, never `one-call`; any other gets `one-call`."""
    import linear
    i = linear.find(JOB)
    st = linear.states()
    linear.call("""mutation($id: String!, $d: String!, $s: String!) {
      issueUpdate(id: $id, input: { description: $d, stateId: $s }) { success }
    }""", {"id": i["id"], "d": spec, "s": st["Todo"]["id"]})
    have = {l["name"].lower() for l in i["labels"]["nodes"]}
    want, drop = (STUCK_LABEL, LABEL) if method else (LABEL, STUCK_LABEL)
    if drop in have:
        linear.call("""mutation($id: String!, $l: String!) {
          issueRemoveLabel(id: $id, labelId: $l) { success }
        }""", {"id": i["id"], "l": linear._label_id(drop)})
    if want not in have:
        linear.call("""mutation($id: String!, $l: String!) {
          issueAddLabel(id: $id, labelId: $l) { success }
        }""", {"id": i["id"], "l": linear._label_id(want)})


def may_write(state_type, label_names):
    """The Scout writes a new spec when SEB-300 is Done, or when it is stuck and labelled needs-claude (so it never stalls on it)."""
    return state_type == "completed" or STUCK_LABEL in {l.lower() for l in label_names}


def job_state():
    import linear
    i = linear.find(JOB)
    return i["state"]["name"], may_write(i["state"]["type"], [l["name"] for l in i["labels"]["nodes"]])


# ---------- main ----------

def ran_this_week(path=LOG, now=None):
    """True if a real (not dry) run already finished this ISO week: a log row with mode 'run' and a status other than
    'failed'. The schedule has several slots because GitHub drops cron runs; only the first one that works does anything."""
    if not os.path.exists(path):
        return False
    now = now or llm.now()
    monday = (now - __import__("datetime").timedelta(days=now.weekday())).date().isoformat()
    with open(path, newline="") as f:
        return any(r["mode"] == "run" and r["status"] != "failed" and r["ts_utc"][:10] >= monday for r in csv.DictReader(f))


BACKLOG = os.path.join(ROOT, "BACKLOG.md")


def split_backlog(dry, mode):
    """The Scout's main job (Seb, 20 Oct): split the next unchecked BACKLOG.md items into jobs one builder call can do. Returns True
    if there was anything to split (so the suggestion flow below is skipped this week)."""
    import scout_split
    text = open(BACKLOG).read() if os.path.exists(BACKLOG) else ""
    if not scout_split.next_candidates(text):
        return False
    model = llm.resolve_sonnet()
    before = len(llm.LOGGED)

    def ask(system, user):
        out, _row = llm.complete([{"role": "system", "content": system}, {"role": "user", "content": user}],
                                 models_to_try=[model], issue=JOB + "/scout", max_tokens=1800)
        return out

    markets = {m["ccy"] for m in single_source_markets()}
    new, notes, done = scout_split.run_split(text, ask, markets)
    cost = sum(float(r["cost_usd"]) for r in llm.LOGGED[before:])
    print("model: %s | cost: $%.4f" % (model, cost))
    print("\n".join(notes) or "nothing to split")
    changed = new != text
    if changed and not dry:
        open(BACKLOG, "w").write(new)
    log_row(mode, "split" if done else "blocked", "; ".join(notes)[:480], "%d item(s) split" % done, cost)
    if dry and changed:
        print("\n----- BACKLOG.md after (dry run: not written) -----\n" + new)
    return True


def run(dry, force=False):
    mode = "dry-run" if dry else "run"
    # 25 Oct (Seb): the builder must never sit idle with work in the queue. The Scout runs daily, and makes a model call only
    # when the builder has fewer than READY_TARGET ready jobs. Its own suggestions into SEB-300 stay once a week.
    if not dry and not force and ready_jobs() >= READY_TARGET:
        print("the builder has %d ready jobs, nothing to split" % ready_jobs())
        return 0
    if split_backlog(dry, mode):
        return 0
    if not dry and not force and ran_this_week():
        print("already made suggestions this week, nothing to do")
        return 0
    name, free = job_state()
    if not free:
        log_row(mode, "skipped", "%s is %s, not Done and not labelled %s" % (JOB, name, STUCK_LABEL))
        print("skipped: %s is %s, not Done and not labelled %s" % (JOB, name, STUCK_LABEL))
        return 0
    inputs = gather()
    if not any(v for k, v in inputs.items() if k != "standing_rules"):
        log_row(mode, "nothing", "no single-source market, no disagreement, no failing claim")
        print("nothing to pick from")
        return 0
    prompt = build_prompt(inputs)
    numbers = numeric_leaves(inputs)
    model = llm.resolve_sonnet()
    before = len(llm.LOGGED)
    text, row = llm.complete([{"role": "system", "content": SYSTEM}, {"role": "user", "content": prompt}],
                             models_to_try=[model], issue=JOB + "/scout", max_tokens=MAX_TOKENS)
    cost = sum(float(r["cost_usd"]) for r in llm.LOGGED[before:])
    spec = text.strip()
    title = next((l[2:].strip() for l in spec.splitlines() if l.startswith("# ")), "")
    reasons = validate(spec, numbers, markets=inputs["single_source_markets"])
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
    method = changes_method(spec)
    post_spec(spec + "\n\n*Written by the Scout on %s. Every number traces to the code-computed inputs; every venue passed the source probe.*\n" % llm.now().date().isoformat(), method)
    label = STUCK_LABEL if method else LABEL
    log_row(mode, "posted", "spec written into %s, set to Todo, labelled %s%s" % (JOB, label, " (it changes how a published number is computed)" if method else ""), title, cost)
    print("posted into %s, labelled %s" % (JOB, label))
    return 0


def untraced_ok(text, numbers):
    return not analyst.untraced_numbers(text, numbers)


def self_test():
    import tempfile
    for rel in WHERE:
        assert os.path.isfile(os.path.join(ROOT, rel)), "WHERE names a file that is not in the repo: " + rel
    numbers = numeric_leaves({"single_source_markets": [{"ccy": "TRY", "sources": 1}], "x": [3]})
    markets = [{"ccy": "TRY"}]
    accepted = lambda ccy, url, field: {"accepted": True}
    rejected = lambda ccy, url, field: {"accepted": False, "check": "off by 4%"}
    with tempfile.TemporaryDirectory() as d:
        open(os.path.join(d, "a.py"), "w").write("x = 1\n")
        open(os.path.join(d, "big.py"), "w").write("x" * (MAX_FILES_CHARS + 1))
        open(os.path.join(d, "ctx.csv"), "w").write("a\n")
        good = ("# Add a source\n\n## Why\n1 market has one source.\n\n## Files\n`a.py`\n\n## Context\n`ctx.csv`\n\n"
                "## Venues\n`TRY` | `https://example.com/api` | `ticker.last`\n\n## Done when\nIt works.\n")
        ok = lambda spec, probe=accepted: validate(spec, numbers, d, markets, probe)
        assert ok(good) == [], ok(good)
        cases = {
            "invented number": good.replace("1 market", "7 markets"),
            "no Files section": good.replace("## Files\n`a.py`", "## Files\nnone"),
            "missing file": good.replace("`a.py`", "`nope.py`"),
            "oversize files": good.replace("`a.py`", "`big.py`"),
            "forbidden file": good.replace("`a.py`", "`copy.json`"),
            "a page": good.replace("`a.py`", "`index.html`"),
            "a script folder": good.replace("`a.py`", "`js/route.js`"),
            "path escape": good.replace("`a.py`", "`../x.py`"),
            "missing context": good.replace("`ctx.csv`", "`gone.csv`"),
            "venue for a market with two sources": good.replace("`TRY` |", "`EUR` |"),
            "venue not https": good.replace("https://example.com", "http://example.com"),
            "malformed venue": good.replace("`TRY` | `https://example.com/api` | `ticker.last`", "somewhere on the web"),
        }
        for name, spec in cases.items():
            for f in ("copy.json", "index.html", "js/route.js"):
                os.makedirs(os.path.dirname(os.path.join(d, f)) or d, exist_ok=True)
                open(os.path.join(d, f), "a").close()
            assert ok(spec), "%s was not rejected" % name
        assert any("probe rejected" in r for r in ok(good, rejected)), "a failing probe must stop the spec"
        assert any("may not change" in r for r in ok(cases["forbidden file"]))
    # the inputs, built from the repo's own data
    ins = gather()
    assert set(ins) == {"single_source_markets", "disagreeing_pairs", "failing_claims", "standing_rules"}
    assert ins["standing_rules"][0]["percent"] == 3.0, "the 3% rule must come from emit_countries.py"
    assert untraced_ok("a 3 percent gap", numeric_leaves(ins))
    # a job that changes how a number is computed never goes to the builder
    em = method_emitters()
    assert "tools/emit_countries.py" in em and "tools/emit_routes.py" in em and "tools/emit_findings.py" in em, em
    plain = "# x\n\n## Why\nA venue.\n\n## Files\n`tools/probe_source.py`\n"
    assert not changes_method(plain, em)
    assert changes_method(plain.replace("tools/probe_source.py", "tools/emit_countries.py"), em)
    assert changes_method(plain.replace("tools/probe_source.py", "collector_p2p.py"), em)
    assert changes_method(plain.replace("A venue.", "Method change: yes\nA venue."), em)
    # the Scout waits on SEB-300 only while it is open and not labelled needs-claude
    assert may_write("completed", []) and may_write("started", ["Needs-Claude"]) and may_write("unstarted", ["needs-claude", "one-call"])
    assert not may_write("started", ["one-call"]) and not may_write("unstarted", [])
    p = build_prompt(ins)
    assert ".md" not in p.replace("\n", " ").split("SINGLE_SOURCE_MARKETS")[0]
    assert all(m["ccy"] and m["sources"] == 1 for m in ins["single_source_markets"])
    assert all(not c["claim"].endswith(".md") for c in ins["failing_claims"])
    assert len(p) < llm.MAX_PROMPT_CHARS // 2, "the prompt must stay far below the limit"
    # one real run a week: a 'run' row this ISO week stops later slots; a dry run, a failure, or last week's row does not
    import datetime as _dt
    with tempfile.TemporaryDirectory() as d:
        lg = os.path.join(d, "scout_log.csv")
        now = _dt.datetime(2026, 10, 13, 1, 17, tzinfo=_dt.timezone.utc)      # a Tuesday; the week began Mon 12 Oct
        assert not ran_this_week(lg, now)
        for mode, status, ts, want in (("dry-run", "rejected", "2026-10-12T01:00:00", False), ("run", "failed", "2026-10-12T01:00:00", False),
                                       ("run", "posted", "2026-10-05T01:00:00", False), ("run", "rejected", "2026-10-12T01:00:00", True)):
            with open(lg, "w", newline="") as f:
                w = csv.writer(f); w.writerow(LOG_HEADER); w.writerow([ts, mode, status, "", "", "0"])
            assert ran_this_week(lg, now) is want, (mode, status, ts)
    import scout_split
    scout_split.self_test()
    print("scout self-test: ok")


if __name__ == "__main__":
    if "--self-test" in sys.argv:
        self_test()
        sys.exit(0)
    try:
        code = run("--dry-run" in sys.argv, "--force" in sys.argv)
    except llm.LLMError as e:
        print("SCOUT FAILED: %s" % e, file=sys.stderr)
        log_row("dry-run" if "--dry-run" in sys.argv else "run", "failed", str(e))
        code = 1
    sys.exit(code)
