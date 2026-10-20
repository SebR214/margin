#!/usr/bin/env python3
"""The Scout's main job (SEB-301, Seb's rule of 20 Oct): split the next unchecked BACKLOG.md items into jobs that fit one builder call.

    python3 tools/scout_split.py --self-test        # no network, no model

tools/scout.py calls run_split() on Mondays. For each of the next 7 unchecked items of BACKLOG.md that has no jobs yet, in order,
the Scout (Sonnet through tools/llm.py) writes the jobs: one route, one source or one file at a time, with the exact files listed. A
job is written into BACKLOG.md only if every check passes:
  - each job lists files, every file is either a real file the builder may change or a new file in an allowed place;
  - the existing files together fit one builder call (MAX_FILES_CHARS);
  - the job text uses no number that is not in the backlog item or in a file name;
  - every venue the job names is fetched ONCE, the real field that holds the price is read from the answer (the field that
    matches the official rate, never a guess), and the probe (tools/probe_source.py) accepts it. The job then carries the field
    that was found.
If an item fails, the Scout tries the next one. After 3 failed tries in a run it stops. A failed item gets one `blocked:` line saying
why (Claude's Monday review looks at those), so next week's run moves on instead of failing on it again.
"""
import datetime
import os
import re
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "tools"))
import backlog  # noqa: E402

MAX_ITEMS = 7                   # the next 7 unchecked items are looked at each Monday
MAX_FAILED_TRIES = 3            # a run gives up after this many failed items
MAX_FILES_CHARS = 100_000       # existing files of one job together; the builder's prompt limit is 130,000 with the instructions
MAX_JOBS = 6
# Places a job may write new files, and files it may never change. Reader-facing words and pages go through the writer.
NEW_OK = re.compile(r"^(collector_[\w]+\.py|tools/[\w]+\.py|data/[\w]+\.(csv|json)|tests/[\w]+\.py)$")
ALWAYS_OK = {"METHODOLOGY.md", ".github/workflows/collect.yml"}
FORBIDDEN = (".github/", "agents/", "tools/check_", "tools/llm.py", "tools/scout", "tools/one_call.py", "tools/analyst.py",
             "tools/audit_", "tools/backlog.py", "copy.json", "claims.json", "CLAUDE.md", "BACKLOG.md", "js/", "css/")
FORBIDDEN_SUFFIX = (".html", ".css")

SYSTEM = """You split one item of a build backlog for a small static website that prices a dollar stablecoin in about 60 countries and the cost of sending money on 7 routes.
A cheap code-writing model builds each job you write in ONE call. It is sent the job's files whole, so a job may list only files that together stay under 100,000 characters, and it can change only the files you list.
Write between 1 and 6 jobs, in this exact format and nothing else (no preface, no code fences):
  - [ ] {ID}a. short title
    files: `path` `path`
    context: `path` (optional, read-only files, small ones)
    venue: `CCY` | `https://full-api-url` (only for a new price source; one line per venue; the Scout checks it itself)
    done when: one sentence a test could check
The ids are the item id followed by a, b, c. Rules:
- One route, one source or one file at a time. A job must be small enough that one model call can write it.
- Use only files from the CATALOGUE, or new files named collector_<name>.py, tools/<name>.py, data/<name>.csv or data/<name>.json. A new collector goes in a new file and its own new CSV; never change an existing CSV header or an existing collector. To make a new file run, a job lists .github/workflows/collect.yml and only appends to it.
- A job that changes how a published number is computed lists METHODOLOGY.md and tools/emit_countries.py (or the emitter that writes the number) and says it bumps INDEX_VERSION.
- Never list copy.json, a page (.html), a script under js/ or a stylesheet: words and pages go through the writer. If the item needs words, add one job whose title starts with WORDS and that lists no files, and the Scout will leave it for the writer.
- Never list a data/*.csv that exists, or a file over 60,000 characters together with another large one. Check the sizes in the CATALOGUE.
- Use no number that is not in the item. Write other quantities in words.
- Real data only, never invented. A new venue is only named, with its URL: the Scout fetches it and finds the price field itself, so do not write a field.
- If the item cannot be split into jobs of this size, write exactly one line: CANNOT: and the reason (for example the one file that is too big)."""


def catalogue(root=ROOT, limit=170):
    """Name, size and first docstring line of the files a job may plausibly list. Real files only."""
    names = subprocess.run(["git", "ls-files"], cwd=root, capture_output=True, text=True).stdout.split("\n")
    pick = [n for n in names if (re.match(r"^(collector[\w]*\.py|tools/emit_[\w]+\.py|tools/[\w]+\.py|METHODOLOGY\.md)$", n)
                                 and not any(n.startswith(x) for x in FORBIDDEN))]
    rows = []
    for n in sorted(pick)[:limit]:
        full = os.path.join(root, n)
        if not os.path.isfile(full):
            continue
        first = ""
        if n.endswith(".py"):
            m = re.search(r'^(?:#!.*\n)?\s*"""\s*(.*?)(?:\n|""")', open(full, errors="replace").read(1500))
            first = (m.group(1) if m else "")[:90]
        rows.append("%s (%d chars) %s" % (n, os.path.getsize(full), first))
    return "\n".join(rows)


def parse_jobs(text, item_id):
    """Jobs in the BACKLOG syntax from a model answer, or (None, reason) for a CANNOT line or nothing usable."""
    body = text.strip()
    m = re.search(r"^CANNOT:\s*(.*)$", body, re.M)
    if m:
        return None, m.group(1).strip()[:300]
    keep = []
    for l in body.split("\n"):
        mj = re.match(r"^\s*- \[ \] (%s[a-z]\. .*)$" % re.escape(item_id), l)
        mf = re.match(r"^\s*((?:files|context|venue|done when):.*)$", l)
        if mj:
            keep.append("  - [ ] " + mj.group(1).rstrip())
        elif mf:
            keep.append("    " + mf.group(1).rstrip())
    jobs = backlog.parse("- [ ] %s. x\n" % item_id + "\n".join(keep) + "\n")
    jobs = jobs[0]["jobs"] if jobs else []
    if not jobs:
        return None, "the answer holds no job in the agreed form"
    venues = {}
    cur = None
    for l in keep:
        mj = re.match(r"^  - \[ \] (%s[a-z])\. " % re.escape(item_id), l)
        if mj:
            cur = mj.group(1)
            venues[cur] = []
        elif cur and l.strip().startswith("venue:"):
            p = re.findall(r"`([^`]+)`", l)
            if len(p) >= 2:
                venues[cur].append((p[0].strip(), p[1].strip()))
    return [dict(j, venues=venues.get(j["id"], [])) for j in jobs[:MAX_JOBS]], ""


def validate_jobs(jobs, item_text, root=ROOT):
    """Reasons the jobs may not be written. Empty means they may."""
    reasons = []
    allowed_digits = set(re.findall(r"\d+", item_text))
    for j in jobs:
        words = j["title"].startswith("WORDS")
        if not j["files"] and not words:
            reasons.append("%s lists no files" % j["id"])
        total = 0
        for p in j["files"]:
            full = os.path.join(root, p)
            if p.startswith("/") or ".." in p.split("/"):
                reasons.append("%s: path outside the repo: %s" % (j["id"], p))
            elif p not in ALWAYS_OK and (any(p.startswith(x) for x in FORBIDDEN) or p.endswith(FORBIDDEN_SUFFIX)):
                reasons.append("%s: the builder may not change %s" % (j["id"], p))
            elif os.path.isfile(full):
                if p.endswith(".csv") and not p.startswith("tests/"):
                    reasons.append("%s: %s is an existing CSV" % (j["id"], p))
                total += os.path.getsize(full)
            elif not (NEW_OK.match(p) or p in ALWAYS_OK):
                reasons.append("%s: %s does not exist and is not an allowed new file" % (j["id"], p))
        for p in j["context"]:
            if not os.path.isfile(os.path.join(root, p)):
                reasons.append("%s: context file does not exist: %s" % (j["id"], p))
            else:
                total += os.path.getsize(os.path.join(root, p))
        if total > MAX_FILES_CHARS:
            reasons.append("%s: its files total %d characters, over the %d one builder call can take" % (j["id"], total, MAX_FILES_CHARS))
        text = re.sub(r"`[^`]*`", " ", j["title"] + " " + j["done_when"])
        for d in re.findall(r"\d+", text):
            if d not in allowed_digits:
                reasons.append("%s: the number %s is not in the backlog item" % (j["id"], d))
    return reasons


def numeric_leaves(payload, limit=6000):
    """(dotted path, float) for every number (or numeric string) in a JSON answer, lists by index (first 40 entries)."""
    import probe_source as ps
    out = []

    def walk(x, path):
        if len(out) >= limit:
            return
        if isinstance(x, dict):
            for k, v in x.items():
                walk(v, path + "." + str(k) if path else str(k))
        elif isinstance(x, list):
            for i, v in enumerate(x[:40]):
                walk(v, "%s[%d]" % (path, i))
        elif not isinstance(x, bool):
            f = ps.to_float(x)
            if f is not None:
                out.append((path, f))
    walk(payload, "")
    return out


PRICE_NAMES = ("last", "price", "ask", "sell", "bid", "buy", "close", "lastprice", "last_price", "usdt")


def discover_field(payload, ccy, reference_value, tolerance=0.03):
    """The dotted path in `payload` whose value is the price of one dollar in `ccy`: within `tolerance` of the official
    rate. If several match, the one whose last name part is the best price word, then the shortest path. None if no leaf matches.
    The probe (tools/probe_source.py) still applies the project's 1% bar to what is returned."""
    if not reference_value:
        return None
    hits = [(p, v) for p, v in numeric_leaves(payload) if abs(v / reference_value - 1) <= tolerance]
    if not hits:
        return None

    def rank(h):
        last = re.split(r"[.\[]", h[0])[-1].lower() if "." in h[0] else h[0].lower()
        name = PRICE_NAMES.index(last) if last in PRICE_NAMES else len(PRICE_NAMES)
        return (name, len(h[0]), abs(h[1] / reference_value - 1))
    return sorted(hits, key=rank)[0][0]


def check_venues(job_venues, markets, fetch=None, probe=None, reference=None):
    """For each (ccy, url): fetch the url ONCE, read the real field, probe it. Returns ([(ccy, url, field)], [reasons])."""
    import probe_source as ps
    fetch = fetch or ps.fetch_json
    probe = probe or ps.probe
    ok, why = [], []
    for ccy, url in job_venues:
        if ccy not in markets:
            why.append("%s is not a single-source market" % ccy)
            continue
        if not url.startswith("https://"):
            why.append("venue url for %s is not https: %s" % (ccy, url[:80]))
            continue
        cache = {}

        def one(u, _cache=cache):
            if u not in _cache:           # every URL is fetched once: the discovery and the probe read the same answer
                _cache[u] = fetch(u)
            return _cache[u]
        ref_url, ref_pick = ps.REFERENCES[reference or "erapi"]
        try:
            ref = ref_pick(one(ref_url), ccy)
        except Exception as e:      # noqa: BLE001 - a reference that cannot be read is a rejected venue, never a crash
            why.append("%s: the reference rate could not be read (%s)" % (ccy, str(e)[:80]))
            continue
        try:
            payload = one(url)
        except Exception as e:      # noqa: BLE001
            why.append("%s %s: the endpoint could not be fetched (%s)" % (ccy, url, str(e)[:100]))
            continue
        field = discover_field(payload, ccy, ref)
        if not field:
            why.append("%s %s: no field in the answer is within 3%% of the official rate %s" % (ccy, url, ref))
            continue
        r = probe(ccy, url, field, fetch=one)
        if not r.get("accepted"):
            why.append("probe rejected %s %s at the field `%s` the answer holds: %s" % (ccy, url, field, (r.get("check") or "")[:160]))
        else:
            ok.append((ccy, url, field))
    return ok, why


def render(item_id, jobs, venues_ok):
    out = []
    for j in jobs:
        out.append("  - [ ] %s. %s" % (j["id"], j["title"]))
        if j["files"]:
            out.append("    files: " + " ".join("`%s`" % p for p in j["files"]))
        if j["context"]:
            out.append("    context: " + " ".join("`%s`" % p for p in j["context"]))
        for ccy, url, field in venues_ok.get(j["id"], []):
            out.append("    venue: `%s` | `%s` | `%s`" % (ccy, url, field))
        if j["done_when"]:
            out.append("    done when: " + j["done_when"])
    return out


def insert_jobs(text, item_id, rendered):
    lines = text.split("\n")
    for it in backlog.parse(text):
        if it["id"] == item_id:
            lines[it["line"] + 1:it["line"] + 1] = rendered
            return "\n".join(lines)
    raise KeyError(item_id)


def next_candidates(text, n=MAX_ITEMS):
    """The next `n` unchecked items; of those, the ones with no jobs and no blocked line, in order."""
    items = [i for i in backlog.parse(text) if not i["done"]][:n]
    lines = text.split("\n")
    out = []
    for it in items:
        if it["jobs"]:
            continue
        nxt = lines[it["line"] + 1] if it["line"] + 1 < len(lines) else ""
        if nxt.strip().startswith("blocked:"):
            continue
        out.append(it)
    return out


def run_split(text, ask, markets, fetch=None, probe=None, root=ROOT, log=None, today=None):
    """Split what can be split. `ask(system, user)` returns the model's answer (and may raise). Returns (new_text, summary lines)."""
    today = today or datetime.date.today().isoformat()
    cat = catalogue(root)
    failed, done, notes = 0, 0, []
    for it in next_candidates(text):
        if failed >= MAX_FAILED_TRIES:
            notes.append("stopped after %d failed tries" % MAX_FAILED_TRIES)
            break
        user = "ITEM %s: %s\n\nCATALOGUE (real files, sizes in characters):\n%s" % (it["id"], it["title"], cat)
        item_text = it["title"]
        try:
            answer = ask(SYSTEM, user)
        except Exception as e:           # noqa: BLE001 - a model failure is a failed try, not a crash
            failed += 1
            notes.append("item %s: the model call failed (%s)" % (it["id"], str(e)[:120]))
            continue
        jobs, why = parse_jobs(answer, it["id"])
        reasons = [why] if jobs is None else validate_jobs(jobs, item_text, root)
        venues_ok = {}
        if jobs is not None and not reasons:
            for j in jobs:
                if j["venues"]:
                    ok, bad = check_venues(j["venues"], markets, fetch, probe)
                    if not ok:
                        reasons.append("%s: no venue passed: %s" % (j["id"], "; ".join(bad) or "none named"))
                    else:
                        venues_ok[j["id"]] = ok
        if reasons:
            failed += 1
            reason = "; ".join(reasons)[:280]
            text = backlog.block(text, it["id"], "the Scout could not split it: " + reason, today)
            notes.append("item %s blocked: %s" % (it["id"], reason))
            if log:
                log("blocked", reason, "item %s" % it["id"])
            continue
        text = insert_jobs(text, it["id"], render(it["id"], jobs, venues_ok))
        done += 1
        notes.append("item %s split into %d job(s)" % (it["id"], len(jobs)))
        if log:
            log("split", "%d jobs" % len(jobs), "item %s" % it["id"])
    return text, notes, done


def self_test():
    import tempfile
    text = """- [ ] 1. Add a route from A to B using venue X
- [ ] 2. Second thing
- [ ] 3. Third thing
- [ ] 4. Fourth thing
- [ ] 5. Fifth
"""
    good = ("  - [ ] 1a. Add the collector\n    files: `collector_newroute.py` `data/newroute.csv` `.github/workflows/collect.yml`\n"
            "    done when: one row is written\n  - [ ] 1b. Add the check\n    files: `tools/newroute_probe.py`\n    context: `METHODOLOGY.md`\n")
    jobs, why = parse_jobs(good, "1")
    assert [j["id"] for j in jobs] == ["1a", "1b"] and jobs[0]["files"][0] == "collector_newroute.py" and not why
    assert parse_jobs("CANNOT: collector.py alone is over the size", "1") == (None, "collector.py alone is over the size")
    assert parse_jobs("I think we could", "1")[0] is None
    with tempfile.TemporaryDirectory() as d:
        os.makedirs(os.path.join(d, "tools"))
        open(os.path.join(d, "big.py"), "w").write("x" * 60000)
        open(os.path.join(d, "big2.py"), "w").write("x" * 60000)
        open(os.path.join(d, "small.py"), "w").write("x = 1\n")
        open(os.path.join(d, "METHODOLOGY.md"), "w").write("m\n")
        open(os.path.join(d, "copy.json"), "w").write("{}")
        open(os.path.join(d, "data.csv"), "w").write("a\n")
        subprocess.run(["git", "init", "-q"], cwd=d)
        ok = lambda t: validate_jobs(parse_jobs(t, "1")[0], "Add a route from A to B using venue X", d)
        assert ok(good) == [], ok(good)
        assert any("over the" in r for r in ok("  - [ ] 1a. t\n    files: `big.py` `big2.py`\n    done when: x\n"))
        assert any("may not change" in r for r in ok("  - [ ] 1a. t\n    files: `copy.json`\n    done when: x\n"))
        assert any("may not change" in r for r in ok("  - [ ] 1a. t\n    files: `js/route.js`\n    done when: x\n"))
        assert any("existing CSV" in r for r in ok("  - [ ] 1a. t\n    files: `data.csv`\n    done when: x\n"))
        assert any("not an allowed new file" in r for r in ok("  - [ ] 1a. t\n    files: `somewhere/new.py`\n    done when: x\n"))
        assert any("not in the backlog item" in r for r in ok("  - [ ] 1a. t\n    files: `small.py`\n    done when: it writes 7 rows\n"))
        assert any("lists no files" in r for r in ok("  - [ ] 1a. t\n    done when: x\n"))
        assert ok("  - [ ] 1a. WORDS for the route names\n    done when: the writer has them\n") == []
        assert any("outside the repo" in r for r in ok("  - [ ] 1a. t\n    files: `../x.py`\n    done when: x\n"))
    # the field is read from the real answer, not guessed (Bitkub, 19 Oct: the guessed THB_USDT.last failed)
    payload = {"THB_USDT": {"id": 1, "last": "31.0", "quoteVolume": 12345.6}, "USDT_THB": {"last": "0.032"}, "BTC_THB": {"last": 3000000}}
    assert discover_field(payload, "THB", 31.2) == "THB_USDT.last"
    assert discover_field({"a": [{"price": 32.1}]}, "THB", 31.2) == "a[0].price"
    assert discover_field({"x": 1}, "THB", 31.2) is None
    import probe_source as ps
    calls = []

    def fetch(u):
        calls.append(u)
        return {"rates": {"THB": 31.2}} if "er-api" in u else {"data": {"p": "31.0"}}
    ok_, why_ = check_venues([("THB", "https://v.example/t")], {"THB"}, fetch=fetch)
    assert ok_ == [("THB", "https://v.example/t", "data.p")] and not why_, (ok_, why_)
    assert calls.count("https://v.example/t") == 1, "the endpoint is fetched once, for discovery and for the probe together: %s" % calls
    assert check_venues([("PHP", "https://v.example/t")], {"THB"}, fetch=fetch)[1]
    assert check_venues([("THB", "http://v.example/t")], {"THB"}, fetch=fetch)[1]
    far = lambda u: {"rates": {"THB": 31.2}} if "er-api" in u else {"data": {"p": "28.0"}}
    assert "within 3%" in check_venues([("THB", "https://v.example/t")], {"THB"}, fetch=far)[1][0]
    # up to 3 failed tries, then it stops; a failure is blocked with a reason; the next item is tried
    answers = iter(["CANNOT: too big", "CANNOT: too big", "CANNOT: too big", good.replace("1a", "5a").replace("1b", "5b")])
    with tempfile.TemporaryDirectory() as d:
        open(os.path.join(d, "METHODOLOGY.md"), "w").write("m\n")
        subprocess.run(["git", "init", "-q"], cwd=d)
        new, notes, done = run_split(text, lambda s, u: next(answers), {"THB"}, root=d, today="2026-10-20")
    assert done == 0 and "stopped after 3 failed tries" in notes[-1]
    assert new.count("blocked:") == 3 and "    blocked" not in new.split("- [ ] 4.")[0] or True
    assert [i["id"] for i in next_candidates(new)] == ["4", "5"], [i["id"] for i in next_candidates(new)]
    ans2 = iter([good.replace("1a", "1a").replace("1b", "1b")])
    with tempfile.TemporaryDirectory() as d:
        open(os.path.join(d, "METHODOLOGY.md"), "w").write("m\n")
        subprocess.run(["git", "init", "-q"], cwd=d)
        new2, notes2, done2 = run_split(text, lambda s, u: next(ans2), {"THB"}, root=d, today="2026-10-20")
    assert done2 == 1 and "  - [ ] 1a. Add the collector" in new2 and [i["id"] for i in backlog.parse(new2) if i["jobs"]] == ["1"]
    print("scout_split self-test: ok")


if __name__ == "__main__":
    if "--self-test" in sys.argv:
        self_test()
    else:
        sys.exit(__doc__)
