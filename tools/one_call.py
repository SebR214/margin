#!/usr/bin/env python3
"""One-call runner (SEB-274). One cheap model call per job, not an agent loop.

    python3 tools/one_call.py            # take the next ready issue, if any
    python3 tools/one_call.py SEB-273    # run one issue by hand

A ready issue is in Todo, carries the label `one-call`, and does not carry
`needs-claude`. Its description lists the files the model may change under a
`## Files` heading, and optional read-only files under `## Context`, one
backticked path per line. Linear documents attached to the issue (the
reference page) are sent too. Nothing else is loaded.

Flow: one call to qwen (kimi if qwen errors). The returned files are written,
then the offline checks run. Pass: open a PR and comment on the issue. Fail:
one retry with the check output. Fail again: label `needs-claude`, put the
issue back in Todo, and stop.

Caps: 2 calls and $1 per job, DAILY_CAP_USD (default $3) per UTC day, summed
from data/agent_spend.csv. Every call is logged there with the cost OpenRouter
reports in the response.

Exit codes: 0 for a clean pass, including "nothing to do" and "daily cap
reached". 1 when something is broken that a person must see (no credit, no
key, Linear unreachable). A non-zero exit fails the workflow run, and GitHub
emails the failure.

Env: OPENROUTER_API_KEY, LINEAR_API_KEY, GH_PUSH_TOKEN (to open PRs that run
CI), GITHUB_REPOSITORY.
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
sys.path.insert(0, os.path.join(ROOT, "agents"))
import linear  # noqa: E402

LABEL = "one-call"
STUCK_LABEL = "needs-claude"
MODELS = ["qwen/qwen3-coder", "moonshotai/kimi-k2"]
MAX_CALLS = 2
JOB_CAP_USD = 1.00
DAILY_CAP_USD = float(os.environ.get("DAILY_CAP_USD", "3.00"))
MAX_TOKENS = 32000
SPEND_PATH = os.path.join(ROOT, "data", "agent_spend.csv")
SPEND_HEADER = ["ts_utc", "issue", "model", "tokens_in", "tokens_out",
                "cost_usd", "result"]
CHECKS = [
    ["python3", "tools/check_inventory.py"],
    ["python3", "tools/check_copy.py"],
    ["python3", "tools/check_design.py"],
]

SYSTEM = """You change files in a small static website repo.
You get one task, the files you may change, read-only context files, and
sometimes a reference page to match.
Rules:
- Change only the files listed under FILES YOU MAY CHANGE.
- Keep every reader-facing word as it is unless the task says otherwise.
- Never type a number into a page. Numbers come from the data files the
  code already reads.
- Return each changed file in full, exactly in this form, and nothing else:
<<<FILE path/to/file>>>
full file contents
<<<END>>>
"""


ROWS = []  # every call this process made, logged even if the run breaks


class Broken(Exception):
    """Something a person must see. Fails the run."""


def now():
    return datetime.datetime.now(datetime.timezone.utc).replace(microsecond=0)


def sh(cmd, check=True, **kw):
    r = subprocess.run(cmd, cwd=ROOT, capture_output=True, text=True, **kw)
    if check and r.returncode != 0:
        raise Broken("%s failed: %s" % (" ".join(cmd), (r.stderr or r.stdout)[-800:]))
    return r


# ---------- spend log ----------

def spent_today():
    if not os.path.exists(SPEND_PATH):
        return 0.0
    today = now().date().isoformat()
    total = 0.0
    with open(SPEND_PATH, newline="") as f:
        for row in csv.DictReader(f):
            if row["ts_utc"].startswith(today):
                try:
                    total += float(row["cost_usd"] or 0)
                except ValueError:
                    pass
    return total


def write_spend(rows):
    if not rows:
        return
    new = not os.path.exists(SPEND_PATH)
    with open(SPEND_PATH, "a", newline="") as f:
        w = csv.writer(f)
        if new:
            w.writerow(SPEND_HEADER)
        for r in rows:
            w.writerow([r[k] for k in SPEND_HEADER])


def commit_spend(rows):
    """Append the rows on main and push. Retries a rebase, like collect.yml."""
    if not rows or os.environ.get("ONE_CALL_DRY_RUN"):
        write_spend(rows)
        return
    for attempt in range(3):
        sh(["git", "fetch", "-q", "origin", "main"])
        sh(["git", "checkout", "-q", "-B", "main", "origin/main"])
        write_spend(rows)
        sh(["git", "add", "data/agent_spend.csv"])
        sh(["git", "commit", "-q", "-m", "one-call spend %s" % now().isoformat()])
        if sh(["git", "push", "-q", "origin", "main"], check=False).returncode == 0:
            return
    raise Broken("could not push data/agent_spend.csv after 3 tries")


# ---------- Linear ----------

def issue_with_docs(ident):
    i = linear.find(ident)
    d = linear.call("""query($id: String!) {
      issue(id: $id) { documents { nodes { title content } } }
    }""", {"id": i["id"]})
    i["docs"] = d["issue"]["documents"]["nodes"]
    return i


def labels(i):
    return {l["name"].lower() for l in i["labels"]["nodes"]}


def next_ready():
    ready = [i for i in linear.issues_in_project()
             if i["state"]["type"] == "unstarted"
             and LABEL in labels(i) and STUCK_LABEL not in labels(i)]
    ready.sort(key=lambda x: (x["priority"] or 99, x["sortOrder"]))
    return ready[0]["identifier"] if ready else None


def comment(i, text):
    linear.call("""mutation($id: String!, $b: String!) {
      commentCreate(input: { issueId: $id, body: $b }) { success }
    }""", {"id": i["id"], "b": "⚙️ **One-call runner**\n\n" + text})


def set_state(i, name):
    st = linear.states()
    if name in st:
        linear.call("""mutation($id: String!, $s: String!) {
          issueUpdate(id: $id, input: { stateId: $s }) { success }
        }""", {"id": i["id"], "s": st[name]["id"]})


def add_label(i, name):
    linear.call("""mutation($id: String!, $l: String!) {
      issueAddLabel(id: $id, labelId: $l) { success }
    }""", {"id": i["id"], "l": linear._label_id(name)})


# ---------- the job ----------

def paths_under(desc, heading):
    m = re.search(r"^##\s*%s\s*$(.*?)(?=^##\s|\Z)" % heading, desc or "",
                  re.M | re.S | re.I)
    if not m:
        return []
    return re.findall(r"`([^`\s]+)`", m.group(1))


def build_prompt(i, files, context):
    parts = ["TASK %s: %s\n\n%s" % (i["identifier"], i["title"], i["description"])]
    for d in i["docs"]:
        parts.append("REFERENCE (Linear document: %s)\n%s" % (d["title"], d["content"]))
    for p in context:
        parts.append("CONTEXT, READ ONLY: %s\n%s" % (p, open(os.path.join(ROOT, p)).read()))
    parts.append("FILES YOU MAY CHANGE: %s" % ", ".join(files))
    for p in files:
        full = os.path.join(ROOT, p)
        body = open(full).read() if os.path.exists(full) else "(new file)"
        parts.append("FILE %s\n%s" % (p, body))
    return "\n\n=====\n\n".join(parts)


def call_model(messages, ident):
    key = os.environ.get("OPENROUTER_API_KEY")
    if not key:
        raise Broken("OPENROUTER_API_KEY is not set")
    last_err = None
    for model in MODELS:
        body = json.dumps({"model": model, "messages": messages,
                           "max_tokens": MAX_TOKENS, "temperature": 0.2,
                           "usage": {"include": True}}).encode()
        req = urllib.request.Request(
            "https://openrouter.ai/api/v1/chat/completions", data=body,
            headers={"Authorization": "Bearer " + key,
                     "Content-Type": "application/json"})
        try:
            with urllib.request.urlopen(req, timeout=600) as r:
                out = json.loads(r.read())
        except urllib.error.HTTPError as e:
            if e.code == 402:
                raise Broken("OpenRouter says the key is out of credit (402)")
            last_err = "%s %s: %s" % (model, e.code, e.read().decode()[:300])
            continue
        except (urllib.error.URLError, TimeoutError) as e:
            last_err = "%s: %s" % (model, e)
            continue
        u = out.get("usage") or {}
        text = (out.get("choices") or [{}])[0].get("message", {}).get("content") or ""
        row = {"ts_utc": now().isoformat(), "issue": ident, "model": model,
               "tokens_in": u.get("prompt_tokens", ""),
               "tokens_out": u.get("completion_tokens", ""),
               "cost_usd": "%.6f" % float(u.get("cost") or 0), "result": ""}
        return text, row
    raise Broken("both models failed: %s" % last_err)


def apply(text, allowed):
    blocks = re.findall(r"<<<FILE ([^>\s]+)>>>\n(.*?)\n<<<END>>>", text, re.S)
    written = []
    for path, body in blocks:
        if path not in allowed:
            continue
        with open(os.path.join(ROOT, path), "w") as f:
            f.write(body if body.endswith("\n") else body + "\n")
        written.append(path)
    return written


def run_checks(written):
    out = []
    cmds = list(CHECKS) + [["node", "--check", p] for p in written if p.endswith(".js")]
    for c in cmds:
        r = subprocess.run(c, cwd=ROOT, capture_output=True, text=True)
        if r.returncode != 0:
            out.append("$ %s\n%s" % (" ".join(c), (r.stdout + r.stderr)[-1500:]))
    return out


def open_pr(i, written, rows):
    branch = "one-call/%s" % i["identifier"].lower()
    sh(["git", "checkout", "-q", "-B", branch])
    sh(["git", "add", "--"] + written)
    sh(["git", "commit", "-q", "-m", "%s: %s\n\nOne-call runner, %s." % (
        i["identifier"], i["title"], ", ".join(r["model"] for r in rows))])
    sh(["git", "push", "-q", "-f", "origin", branch])
    repo = os.environ["GITHUB_REPOSITORY"]
    cost = sum(float(r["cost_usd"]) for r in rows)
    body = ("%s\n\nOne-call runner. %d call(s), $%.4f. Offline checks passed. "
            "The rendered check and screenshots run in CI.\n\n%s" % (
                i["url"], len(rows), cost, "\n".join("- `%s`" % p for p in written)))
    req = urllib.request.Request(
        "https://api.github.com/repos/%s/pulls" % repo,
        data=json.dumps({"title": "%s: %s" % (i["identifier"], i["title"]),
                         "head": branch, "base": "main", "body": body}).encode(),
        headers={"Authorization": "Bearer " + os.environ["GH_PUSH_TOKEN"],
                 "Accept": "application/vnd.github+json"})
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            return json.loads(r.read())["html_url"]
    except urllib.error.HTTPError as e:
        if e.code == 422:  # a PR for this branch is already open
            return "https://github.com/%s/pulls?q=head:%s" % (repo, branch)
        raise Broken("could not open PR: %s" % e.read().decode()[:300])


def run(ident):
    i = issue_with_docs(ident)
    files = paths_under(i["description"], "Files")
    context = paths_under(i["description"], "Context")
    if not files:
        add_label(i, STUCK_LABEL)
        comment(i, "No `## Files` section with backticked paths, so there is nothing "
                   "I may change. Labelled `needs-claude`.")
        return []
    missing = [p for p in context if not os.path.exists(os.path.join(ROOT, p))]
    if missing:
        add_label(i, STUCK_LABEL)
        comment(i, "Context files not in the repo: %s. Labelled `needs-claude`." % ", ".join(missing))
        return []

    set_state(i, "In Progress")
    comment(i, "Starting. Files: %s." % ", ".join(files))
    messages = [{"role": "system", "content": SYSTEM},
                {"role": "user", "content": build_prompt(i, files, context)}]
    rows, failures, written = ROWS, [], []
    for attempt in range(MAX_CALLS):
        if spent_today() + sum(float(r["cost_usd"]) for r in rows) >= DAILY_CAP_USD:
            failures = ["daily cap of $%.2f reached" % DAILY_CAP_USD]
            break
        if sum(float(r["cost_usd"]) for r in rows) >= JOB_CAP_USD:
            failures = ["job cap of $%.2f reached" % JOB_CAP_USD]
            break
        text, row = call_model(messages, i["identifier"])
        rows.append(row)
        sh(["git", "checkout", "-q", "--"] + [p for p in files if os.path.exists(os.path.join(ROOT, p))], check=False)
        written = apply(text, set(files))
        failures = run_checks(written) if written else ["the model returned no files in the agreed form"]
        row["result"] = "pass" if not failures else "fail"
        if not failures:
            break
        messages += [{"role": "assistant", "content": text},
                     {"role": "user", "content": "The checks failed. Fix this and return "
                      "every changed file in full again:\n\n" + "\n\n".join(failures)}]

    cost = sum(float(r["cost_usd"]) for r in rows)
    if not failures:
        url = open_pr(i, written, rows)
        comment(i, "PR open: %s\n%d call(s), $%.4f." % (url, len(rows), cost))
    else:
        sh(["git", "checkout", "-q", "--", "."], check=False)
        add_label(i, STUCK_LABEL)
        set_state(i, "Todo")
        comment(i, "Stopped after %d call(s), $%.4f. Labelled `needs-claude`.\n\n```\n%s\n```"
                % (len(rows), cost, "\n\n".join(failures)[-2500:]))
    return rows


def main():
    if spent_today() >= DAILY_CAP_USD:
        print("daily cap of $%.2f reached, nothing run" % DAILY_CAP_USD)
        return 0
    ident = sys.argv[1] if len(sys.argv) > 1 else next_ready()
    if not ident:
        print("nothing to do")
        return 0
    print("running %s" % ident)
    try:
        run(ident)
    except Broken as e:
        print("BROKEN: %s" % e, file=sys.stderr)
        try:
            i = linear.find(ident)
            set_state(i, "Todo")
            comment(i, "Runner stopped: %s. Put back in Todo." % e)
        except SystemExit:
            pass
        commit_spend(ROWS)
        return 1
    commit_spend(ROWS)
    print("done: %d call(s), $%.4f" % (len(ROWS), sum(float(r["cost_usd"]) for r in ROWS)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
