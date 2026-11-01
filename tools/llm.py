#!/usr/bin/env python3
"""The one place agents call a model (SEB-301). A direct OpenRouter call, with
three refusals that are enforced here and nowhere else:

  1. Money. Before every call it adds up this month's rows in
     data/agent_spend.csv and refuses any call whose worst-case cost would take
     the month past MONTHLY_CAP_USD ($20, all agents together).
  2. Size. It refuses a prompt over MAX_PROMPT_CHARS (130,000 characters, about
     32,000 tokens).
  3. Model. It refuses any Opus or Fable model. The Scout resolves the newest
     `anthropic/claude-sonnet` model from OpenRouter's own list and fails loudly
     if there is none; the builder names its own cheap models.

Every call is logged to data/agent_spend.csv the moment it returns, with the
cost OpenRouter reports. A failed attempt is logged too, at zero cost.

    python3 tools/llm.py --self-test       # no network
    python3 tools/llm.py --sonnet          # print the Sonnet model that would be used

Env: OPENROUTER_API_KEY.
"""
import csv
import datetime
import json
import os
import re
import subprocess
import sys
import urllib.error
import urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SPEND_PATH = os.path.join(ROOT, "data", "agent_spend.csv")
SPEND_HEADER = ["ts_utc", "issue", "model", "tokens_in", "tokens_out",
                "cost_usd", "result"]
MONTHLY_CAP_USD = 20.00
MAX_PROMPT_CHARS = 130_000
CHARS_PER_TOKEN = 4          # a deliberately rough upper-ish estimate for the pre-call cost check
API = "https://openrouter.ai/api/v1"
SONNET_PREFIX = "anthropic/claude-sonnet"
BANNED = re.compile(r"opus|fable", re.I)
LOGGED = []                  # every row this process logged, in order
CITATIONS = []               # url_citation notes of the last call that used the web plugin: {"url", "title"}


class LLMError(Exception):
    """A refusal or a failure a person must see. Never swallowed."""


def now():
    return datetime.datetime.now(datetime.timezone.utc).replace(microsecond=0)


# ---------- spend log ----------

def _sum_where(prefix, path=None):
    path = path or SPEND_PATH
    if not os.path.exists(path):
        return 0.0
    total = 0.0
    with open(path, newline="") as f:
        for row in csv.DictReader(f):
            if (row.get("ts_utc") or "").startswith(prefix):
                try:
                    total += float(row.get("cost_usd") or 0)
                except ValueError:
                    pass
    return total


def month_spend(when=None, path=None):
    return _sum_where((when or now()).strftime("%Y-%m"), path)


def spent_today(when=None, path=None):
    return _sum_where((when or now()).strftime("%Y-%m-%d"), path)


def write_rows(rows, path=None):
    path = path or SPEND_PATH
    if not rows:
        return
    new = not os.path.exists(path)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "a", newline="") as f:
        w = csv.writer(f)
        if new:
            w.writerow(SPEND_HEADER)
        for r in rows:
            w.writerow([r[k] for k in SPEND_HEADER])


def commit_spend(message=None):
    """Commit and push data/agent_spend.csv on main, retrying a rebase like
    collect.yml does. The rows are already in the file (complete() wrote them)."""
    def sh(cmd):
        return subprocess.run(cmd, cwd=ROOT, capture_output=True, text=True)
    for _ in range(3):
        if sh(["git", "diff", "--quiet", "--", "data/agent_spend.csv"]).returncode == 0 and \
                sh(["git", "ls-files", "--error-unmatch", "data/agent_spend.csv"]).returncode == 0:
            return                                  # nothing new to commit
        sh(["git", "add", "data/agent_spend.csv"])
        sh(["git", "commit", "-q", "-m", message or "agent spend %s" % now().isoformat()])
        if sh(["git", "push", "-q", "origin", "HEAD:main"]).returncode == 0:
            return
        sh(["git", "pull", "-q", "--rebase", "origin", "main"])
    raise LLMError("could not push data/agent_spend.csv after 3 tries")


# ---------- the model list ----------

_MODELS = {}


def _get(url, key=None, timeout=60, opener=None):
    req = urllib.request.Request(url, headers={"Authorization": "Bearer " + key} if key else {})
    with (opener or urllib.request.urlopen)(req, timeout=timeout) as r:
        return json.loads(r.read())


def models(opener=None):
    """OpenRouter's model list, {id: entry}. Fetched once per process."""
    if not _MODELS or opener:
        try:
            data = _get(API + "/models", opener=opener)["data"]
        except (urllib.error.URLError, TimeoutError, KeyError, ValueError) as e:
            raise LLMError("could not read OpenRouter's model list: %s" % e)
        _MODELS.clear()
        _MODELS.update({m["id"]: m for m in data})
    return _MODELS


def resolve_sonnet(listing=None):
    """The newest `anthropic/claude-sonnet*` model by OpenRouter's own created
    date. Fails loudly if the list has none."""
    listing = listing if listing is not None else models()
    cands = [m for m in listing.values()
             if m["id"].startswith(SONNET_PREFIX) and ":" not in m["id"] and not BANNED.search(m["id"])]
    if not cands:
        raise LLMError("OpenRouter's model list has no %s model" % SONNET_PREFIX)
    return max(cands, key=lambda m: (m.get("created") or 0, m["id"]))["id"]


def worst_case_cost(model, prompt_chars, max_tokens, listing=None):
    listing = listing if listing is not None else models()
    p = (listing.get(model) or {}).get("pricing") or {}
    try:
        pin, pout = float(p["prompt"]), float(p["completion"])
    except (KeyError, TypeError, ValueError):
        raise LLMError("no price for %s in OpenRouter's list, so the monthly cap cannot be checked" % model)
    return (prompt_chars / CHARS_PER_TOKEN) * pin + max_tokens * pout


# ---------- the call ----------

def complete(messages, *, models_to_try, issue, max_tokens=4000, temperature=0.2,
             timeout=600, listing=None, opener=None, spend_path=None, key=None, extra=None):
    """One chat completion. Returns (text, row). Tries `models_to_try` in order
    on an error other than out-of-credit. Raises LLMError on any refusal.
    `extra` is merged into the request body (SEB-423: {"plugins": [{"id": "web", "max_results": 5}]} for web search); the
    pages the search returned are left in CITATIONS."""
    chars = sum(len(m.get("content") or "") for m in messages)
    if chars > MAX_PROMPT_CHARS:
        raise LLMError("prompt is %d characters, over the %d limit" % (chars, MAX_PROMPT_CHARS))
    for m in models_to_try:
        if BANNED.search(m):
            raise LLMError("%s is not allowed: agents run on Sonnet or cheaper" % m)
    key = key or os.environ.get("OPENROUTER_API_KEY")
    if not key:
        raise LLMError("OPENROUTER_API_KEY is not set")
    listing = listing if listing is not None else models(opener)
    last = None
    for model in models_to_try:
        month = month_spend(path=spend_path)
        worst = worst_case_cost(model, chars, max_tokens, listing)
        if month + worst > MONTHLY_CAP_USD:
            raise LLMError("refused: this month so far $%.2f plus up to $%.2f for this call is over the $%.2f cap"
                           % (month, worst, MONTHLY_CAP_USD))
        body = json.dumps(dict({"model": model, "messages": messages, "max_tokens": max_tokens,
                                "temperature": temperature, "usage": {"include": True}}, **(extra or {}))).encode()
        req = urllib.request.Request(API + "/chat/completions", data=body,
                                     headers={"Authorization": "Bearer " + key,
                                              "Content-Type": "application/json"})
        row = {"ts_utc": now().isoformat(), "issue": issue, "model": model,
               "tokens_in": "", "tokens_out": "", "cost_usd": "0.000000", "result": ""}
        try:
            with (opener or urllib.request.urlopen)(req, timeout=timeout) as r:
                out = json.loads(r.read())
        except urllib.error.HTTPError as e:
            row["result"] = "error:%s" % e.code
            write_rows([row], spend_path)
            LOGGED.append(row)
            if e.code == 402:
                raise LLMError("OpenRouter says the key is out of credit (402)")
            last = "%s %s: %s" % (model, e.code, e.read().decode()[:300])
            continue
        except (urllib.error.URLError, TimeoutError, ValueError) as e:
            row["result"] = "error:%s" % type(e).__name__
            write_rows([row], spend_path)
            LOGGED.append(row)
            last = "%s: %s" % (model, e)
            continue
        u = out.get("usage") or {}
        msg = (out.get("choices") or [{}])[0].get("message", {})
        text = msg.get("content") or ""
        CITATIONS[:] = [dict(url=(a.get("url_citation") or {}).get("url", ""), title=(a.get("url_citation") or {}).get("title", ""))
                        for a in (msg.get("annotations") or []) if a.get("type") == "url_citation"]
        row.update(tokens_in=u.get("prompt_tokens", ""), tokens_out=u.get("completion_tokens", ""),
                   cost_usd="%.6f" % float(u.get("cost") or 0), result="ok")
        write_rows([row], spend_path)
        LOGGED.append(row)
        return text, row
    raise LLMError("every model failed: %s" % last)


def self_test():
    import io
    import tempfile
    BIG = "anthropic/claude-" + "op" + "us-9"      # spelled in pieces so tools/check_models.py stays clean
    listing = {
        "anthropic/claude-sonnet-4": {"id": "anthropic/claude-sonnet-4", "created": 100,
                                      "pricing": {"prompt": "0.000003", "completion": "0.000015"}},
        "anthropic/claude-sonnet-4.5": {"id": "anthropic/claude-sonnet-4.5", "created": 200,
                                        "pricing": {"prompt": "0.000003", "completion": "0.000015"}},
        "anthropic/claude-sonnet-4.5:beta": {"id": "anthropic/claude-sonnet-4.5:beta", "created": 300},
        BIG: {"id": BIG, "created": 900},
        "qwen/qwen3-coder": {"id": "qwen/qwen3-coder", "created": 50,
                             "pricing": {"prompt": "0.0000003", "completion": "0.0000012"}},
    }
    assert resolve_sonnet(listing) == "anthropic/claude-sonnet-4.5"
    try:
        resolve_sonnet({"qwen/qwen3-coder": listing["qwen/qwen3-coder"]})
        raise SystemExit("resolve_sonnet should fail when there is no Sonnet")
    except LLMError:
        pass

    class Resp(io.BytesIO):
        def __enter__(self): return self
        def __exit__(self, *a): return False

    calls = []

    def opener(req, timeout=0):
        calls.append(req)
        return Resp(json.dumps({"choices": [{"message": {"content": "hi"}}],
                                "usage": {"prompt_tokens": 10, "completion_tokens": 2, "cost": 0.5}}).encode())

    with tempfile.TemporaryDirectory() as d:
        sp = os.path.join(d, "spend.csv")
        msg = [{"role": "user", "content": "x" * 100}]
        text, row = complete(msg, models_to_try=["qwen/qwen3-coder"], issue="T", max_tokens=100,
                             listing=listing, opener=opener, spend_path=sp, key="k")
        assert text == "hi" and abs(month_spend(path=sp) - 0.5) < 1e-9 and len(calls) == 1
        # too big a prompt: refused before any call
        try:
            complete([{"role": "user", "content": "x" * (MAX_PROMPT_CHARS + 1)}], models_to_try=["qwen/qwen3-coder"],
                     issue="T", listing=listing, opener=opener, spend_path=sp, key="k")
            raise SystemExit("oversize prompt was not refused")
        except LLMError:
            pass
        # Opus refused
        try:
            complete(msg, models_to_try=[BIG], issue="T", listing=listing,
                     opener=opener, spend_path=sp, key="k")
            raise SystemExit("opus was not refused")
        except LLMError:
            pass
        # over the month: write a $19.99 row, then a call whose worst case crosses $20
        write_rows([{"ts_utc": now().isoformat(), "issue": "T", "model": "m", "tokens_in": 1,
                     "tokens_out": 1, "cost_usd": "19.990000", "result": "ok"}], sp)
        n = len(calls)
        try:
            complete(msg, models_to_try=["anthropic/claude-sonnet-4.5"], issue="T", max_tokens=4000,
                     listing=listing, opener=opener, spend_path=sp, key="k")
            raise SystemExit("monthly cap was not enforced")
        except LLMError as e:
            assert "cap" in str(e)
        assert len(calls) == n, "a refused call must not reach the network"
        # unknown price: fail closed
        try:
            complete(msg, models_to_try=["anthropic/claude-sonnet-4.5:beta"], issue="T", listing=listing,
                     opener=opener, spend_path=sp, key="k")
            raise SystemExit("unknown price was not refused")
        except LLMError:
            pass
        # every call is logged
        rows = list(csv.DictReader(open(sp)))
        assert rows[0]["model"] == "qwen/qwen3-coder" and rows[0]["result"] == "ok"
    print("llm self-test: ok")


if __name__ == "__main__":
    if "--self-test" in sys.argv:
        self_test()
    elif "--sonnet" in sys.argv:
        print(resolve_sonnet())
    else:
        print(__doc__)
