#!/usr/bin/env bash
# Run the writer agent once, on one page's copy: agents/run_writer.sh how-it-works.html
#
# The writer is a model with NO code access. It runs in a scratch directory that holds
# copy.json and a brief and nothing else, with only Read and Edit allowed. This script,
# not the model, then checks the result, branches, commits, renders the page text and
# opens the pull request. The model cannot merge, push or run a command.
#
# Needs: claude CLI (flat-rate token), gh (signed in), git, python3, Chrome for the render.

set -euo pipefail
PAGE="${1:?usage: run_writer.sh <page.html>}"
REPO="$(cd "$(dirname "$0")/.." && pwd)"
MODEL="${WRITER_MODEL:-claude-opus-5-5}"
STAMP="$(date -u +%Y%m%d-%H%M)"
BRANCH="writer/${PAGE%.html}-$STAMP"
WORK="$(mktemp -d)"; SCRATCH="$(mktemp -d)"
trap 'rm -rf "$SCRATCH"' EXIT

cd "$REPO"
git fetch -q origin main
git worktree add -q "$WORK" -B "$BRANCH" origin/main

# The brief: what to beat (this page live), the voice (home, a country), the blocks it reads.
cp "$WORK/copy.json" "$SCRATCH/copy.json"
{
  echo "# Brief for $PAGE"; echo
  echo "## What to beat: the live text of $PAGE"; echo
  (cd "$WORK" && python3 tools/render_text.py "$PAGE")
  echo; echo "## The voice to match"; echo
  (cd "$WORK" && python3 tools/render_text.py index.html country.html)
} > "$SCRATCH/BRIEF.md"
cp "$WORK/agents/WRITER.md" "$SCRATCH/WRITER.md"

(cd "$SCRATCH" && env -u ANTHROPIC_API_KEY -u ANTHROPIC_AUTH_TOKEN claude -p \
  "Follow WRITER.md. Rewrite the copy for $PAGE in copy.json, using BRIEF.md. Edit copy.json only, then reply with a short PR note: what changed, what you cut and why, and any figure you needed but no field provides." \
  --model "$MODEL" --allowedTools "Read" "Edit" --permission-mode acceptEdits --max-turns 40 \
  --output-format text > "$SCRATCH/note.md")

# Checks the model cannot skip: valid JSON, no key removed, no invented number or placeholder.
python3 - "$WORK/copy.json" "$SCRATCH/copy.json" <<'PY'
import json, re, sys
old, new = (json.load(open(p)) for p in sys.argv[1:3])
def flat(o, p=""):
    if isinstance(o, dict):
        for k, v in o.items(): yield from flat(v, p + "/" + k)
    elif isinstance(o, list):
        for i, v in enumerate(o): yield from flat(v, p + "[%d]" % i)
    else: yield p, o
a, b = dict(flat(old)), dict(flat(new))
known = set(re.findall(r"\{(\w+)\}", json.dumps(old)))
bad = []
for k in a:
    if k not in b: bad.append("removed " + k)
for k, v in b.items():
    if a.get(k) == v or not isinstance(v, str): continue
    if re.search(r"\d", re.sub(r"\{\w+\}", "", v)): bad.append("digit outside a placeholder in " + k)
    for ph in re.findall(r"\{(\w+)\}", v):
        if ph not in known: bad.append("unknown placeholder {%s} in %s" % (ph, k))
    if re.search(r"[;—–]| - ", v): bad.append("dash or semicolon in " + k)
if bad:
    print("WRITER OUTPUT REJECTED:\n  " + "\n  ".join(bad)); sys.exit(1)
PY
cp "$SCRATCH/copy.json" "$WORK/copy.json"
cd "$WORK"
git diff --quiet -- copy.json && { echo "writer changed nothing"; exit 0; }
git add copy.json
git commit -q -m "writer: copy for $PAGE

Co-Authored-By: Claude Sonnet 5.5 <noreply@anthropic.com>"
git push -q -u origin "$BRANCH"
{
  cat "$SCRATCH/note.md"; echo; echo "## Rendered text"; echo
  python3 tools/render_text.py "$PAGE"
  echo; echo "Needs the owner's approval: the label \`copy-approved\`, added by their own account."
  echo; echo "🤖 Generated with [Claude Code](https://claude.com/claude-code)"
} > "$SCRATCH/body.md"
gh pr create --base main --head "$BRANCH" --title "writer: $PAGE copy" --body-file "$SCRATCH/body.md"
