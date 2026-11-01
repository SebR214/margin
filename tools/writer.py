#!/usr/bin/env python3
"""The writer (SEB-423 step 4): one Sonnet call through OpenRouter, two jobs.

  event  for each published event with no passing file: the event record plus up to 5 web search results, two paragraphs.
         Stored in data/event_prose/{id}.json.
  daily  once a day: data/home_facts.json, at most 3 sentences. Stored in data/home_prose.json.

The words (instructions and the voice check) live in tools/writer_voice.py. This file owns the pipeline: the call, the number
audit, the source check and the stored files. A text that fails any check is not written, and the page keeps its own sentences.
Every number in the text must appear, digit for digit, in the input the model was given. Every source must be a page the
search returned. The call goes through tools/llm.py, so the $20 monthly cap and data/agent_spend.csv apply.

    python3 tools/writer.py event [--id ID]      write the events that have no passing file
    python3 tools/writer.py daily                write today's home sentences (skips if already written today)
    python3 tools/writer.py --self-test

Exit 1 if any text was refused or any call failed. Texts that passed are written first.
"""
import datetime
import json
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import llm
from writer_voice import EVENT_INSTRUCTIONS, DAILY_INSTRUCTIONS, check_event_output, check_daily_output

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
EVENTS = os.path.join(ROOT, "data", "events_published.json")
FACTS = os.path.join(ROOT, "data", "home_facts.json")
PROSE_DIR = os.path.join(ROOT, "data", "event_prose")
HOME_PROSE = os.path.join(ROOT, "data", "home_prose.json")
SEARCH_RESULTS = 5
ISSUE = "SEB-423"

_NUM = re.compile(r"\d[\d,]*(?:\.\d+)?")
_MARK = re.compile(r"\[\d{1,2}\]")
_JSON = re.compile(r"\{.*\}", re.S)


def numbers(text):
    """Every number in a text as a canonical string: no commas, no leading zeros, no trailing zeros after a point."""
    out = set()
    for m in _NUM.findall(text):
        m = m.replace(",", "").rstrip(".")
        if "." in m:
            a, b = m.split(".", 1)
            m = (a.lstrip("0") or "0") + ("." + b.rstrip("0") if b.rstrip("0") else "")
        else:
            m = m.lstrip("0") or "0"
        out.add(m)
    return out


def split_numbers(text):
    """The numbers of a JSON input, with dates split into year, month and day so "7 Oct 2026" can be checked."""
    return numbers(re.sub(r"(\d)-(\d)", r"\1 \2", text))


def audit_numbers(paragraphs, input_text, extra_ok=()):
    """Failures: every number in the written text that the input does not hold. Empty list means it passes."""
    allowed = split_numbers(input_text) | set(extra_ok)
    fails = []
    for i, p in enumerate(paragraphs):
        for n in sorted(numbers(_MARK.sub("", p)) - allowed):
            fails.append("text %d: %s is not in the input" % (i + 1, n))
    return fails


def audit_sources(sources, citations):
    """Failures: a source link the search did not return. The model may not invent a link."""
    seen = {c["url"].rstrip("/") for c in citations}
    return ["source not returned by the search: %s" % s.get("url") for s in sources if str(s.get("url", "")).rstrip("/") not in seen]


def parse_json(text):
    m = _JSON.search(text or "")
    if not m:
        raise ValueError("no JSON in the reply, which began: %r" % (text or "")[:200])
    return json.loads(m.group(0))


def _now():
    return llm.now().strftime("%Y-%m-%dT%H:%M:%SZ")


def _write(path, obj):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w") as f:
        json.dump(obj, f, indent=1, ensure_ascii=False)
        f.write("\n")
    os.replace(tmp, path)


def _model():
    return llm.resolve_sonnet()


def country_name(ccy):
    try:
        return json.load(open(os.path.join(ROOT, "data", "countries", ccy + ".json")))["country"]
    except (OSError, KeyError, ValueError):
        return ccy


def write_event(ev, record_text, country, complete=None):
    """One event. Returns (stored object or None, failures)."""
    complete = complete or llm.complete
    model = _model()
    system = EVENT_INSTRUCTIONS.replace("{country}", country) + "\n\nEvent record:\n" + record_text
    query = "%s %s official exchange rate announcement %s" % (country, ev["ccy"], ev["date"])
    text, _row = complete([{"role": "system", "content": system}, {"role": "user", "content": query}],
                          models_to_try=[model], issue=ISSUE, max_tokens=8000,
                          extra={"plugins": [{"id": "web", "max_results": SEARCH_RESULTS}]})
    print("%s: %d search results, reply %d characters, finish %s" % (ev["id"], len(llm.CITATIONS), len(text or ""), llm.LAST_FINISH[0]))
    obj = parse_json(text)
    fails = check_event_output(obj)
    if not fails:
        fails += audit_numbers(obj["paragraphs"], record_text)
        fails += audit_sources(obj["sources"], llm.CITATIONS)
    if fails:
        return None, fails
    return {"id": ev["id"], "written_utc": _now(), "model": model, "paragraphs": obj["paragraphs"], "sources": obj["sources"],
            "audit": {"passed": True, "checked_utc": _now(), "failures": []},
            "voice": {"passed": True, "problems": []}}, []


def write_daily(facts_text, facts_as_of, about_ccy, complete=None):
    complete = complete or llm.complete
    model = _model()
    system = DAILY_INSTRUCTIONS + "\n\nFacts file:\n" + facts_text
    text, _row = complete([{"role": "system", "content": system}, {"role": "user", "content": "Write today's sentences."}],
                          models_to_try=[model], issue=ISSUE, max_tokens=4000)
    obj = parse_json(text)
    fails = check_daily_output(obj)
    if not fails:
        fails += audit_numbers(obj["sentences"], facts_text, extra_ok=("5",))   # "5%": the line the facts file counts crossings of
    if fails:
        return None, fails
    return {"written_utc": _now(), "facts_as_of": facts_as_of, "model": model, "about_ccy": about_ccy,
            "sentences": obj["sentences"],
            "audit": {"passed": True, "checked_utc": _now(), "failures": []},
            "voice": {"passed": True, "problems": []}}, []


def passed(path):
    try:
        return json.load(open(path))["audit"]["passed"] is True
    except (OSError, KeyError, ValueError):
        return False


def run_events(only=None):
    bad = 0
    for ev in json.load(open(EVENTS))["events"]:
        if only and ev["id"] != only:
            continue
        path = os.path.join(PROSE_DIR, ev["id"] + ".json")
        if passed(path):
            continue
        record = os.path.join(ROOT, ev["record"])
        if os.path.getsize(record) > 40000:
            print("%s: record is over 40 KB, not sent" % ev["id"])
            bad += 1
            continue
        try:
            obj, fails = write_event(ev, open(record).read(), country_name(ev["ccy"]))
        except (llm.LLMError, ValueError) as e:
            obj, fails = None, [str(e)]
        if obj:
            _write(path, obj)
            print("%s: written, %d sources" % (ev["id"], len(obj["sources"])))
        else:
            bad += 1
            print("%s: REFUSED: %s" % (ev["id"], "; ".join(fails)))
    return bad


def run_daily():
    facts_text = open(FACTS).read()
    facts = json.loads(facts_text)
    today = _now()[:10]
    try:
        if passed(HOME_PROSE) and json.load(open(HOME_PROSE))["written_utc"][:10] == today:
            print("home: already written today")
            return 0
    except (OSError, KeyError, ValueError):
        pass
    about = (facts.get("largest_move") or {}).get("ccy") or ""
    try:
        obj, fails = write_daily(facts_text, facts.get("as_of_utc", ""), about)
    except (llm.LLMError, ValueError) as e:
        obj, fails = None, [str(e)]
    if obj:
        _write(HOME_PROSE, obj)
        print("home: written, %d sentences" % len(obj["sentences"]))
        return 0
    print("home: REFUSED: %s" % "; ".join(fails))
    return 1


def self_test():
    assert numbers("rose 60.4% on 07 Mar 2024, 1,200.50 and 3.0") == {"60.4", "7", "2024", "1200.5", "3"}
    rec = '{"date": "2024-03-07", "change_pct": 60.4, "before": 30.9}'
    assert audit_numbers(["Egypt's rate rose 60.4% on 7 Mar 2024 [1]."], rec) == []
    assert audit_numbers(["It rose 60% on 7 Mar 2024."], rec) == ["text 1: 60 is not in the input"]
    assert audit_numbers(["From 30.9 to 49.5."], rec) == ["text 1: 49.5 is not in the input"]
    assert audit_sources([{"url": "https://a.org/x/"}, {"url": "https://b.org"}], [{"url": "https://a.org/x"}]) == \
        ["source not returned by the search: https://b.org"]
    assert parse_json('Here:\n{"sentences": ["a."]}\n') == {"sentences": ["a."]}
    # the whole path with a fake model: a good reply is stored, an invented number and an invented link are refused
    llm.resolve_sonnet = lambda: "anthropic/claude-sonnet-test"
    ev = {"id": "EGP-official_break-2024-03-07", "ccy": "EGP", "date": "2024-03-07"}
    good = {"paragraphs": ["Egypt's official rate rose 60.4% on 7 Mar 2024. It stood at 30.9 before.",
                           "The Central Bank of Egypt said it would let the market set the rate [1]."],
            "sources": [{"title": "t", "url": "https://example.org/a", "site": "example.org"}]}

    def fake(reply, cites):
        def c(messages, **kw):
            assert kw["extra"]["plugins"][0]["max_results"] == 5 and kw["issue"] == ISSUE
            llm.CITATIONS[:] = cites
            return json.dumps(reply), {}
        return c
    ok, f = write_event(ev, rec, "Egypt", fake(good, [{"url": "https://example.org/a", "title": "t"}]))
    assert f == [] and ok["audit"]["passed"] and ok["sources"][0]["url"] == "https://example.org/a", f
    bad = dict(good, paragraphs=[good["paragraphs"][0].replace("60.4", "60"), good["paragraphs"][1]])
    assert write_event(ev, rec, "Egypt", fake(bad, [{"url": "https://example.org/a", "title": "t"}]))[0] is None
    assert write_event(ev, rec, "Egypt", fake(good, []))[0] is None
    facts = '{"as_of_utc": "2026-11-01T08:00:00+00:00", "largest_move": {"ccy": "XAF", "now_pct": 5.9}}'
    d, f = write_daily(facts, "2026-11-01T08:00:00+00:00", "XAF",
                       lambda m, **kw: (json.dumps({"sentences": ["The gap in Central Africa stood at 5.9% on 1 Nov."]}), {}))
    assert f == [] and d["about_ccy"] == "XAF" and d["sentences"], f
    d, f = write_daily(facts, "x", "XAF", lambda m, **kw: (json.dumps({"sentences": ["The gap stood at 6.1%."]}), {}))
    assert d is None and "6.1" in f[0], f
    print("writer self-test: ok")


def main(argv):
    if "--self-test" in argv:
        return self_test()
    if argv[:1] == ["event"]:
        return 1 if run_events(argv[argv.index("--id") + 1] if "--id" in argv else None) else 0
    if argv[:1] == ["daily"]:
        return run_daily()
    print(__doc__)
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
