#!/usr/bin/env bash
# Rebase the current branch onto origin/main and auto-resolve conflicts in
# known GENERATED files instead of making a human hand-diagnose them.
#
# WHY THIS EXISTS: main gets real commits every ~30 minutes from the hourly
# collector bot, plus occasional direct pushes from other sessions. Any
# branch that sits open more than a few minutes collides with that -- not bad
# luck, guaranteed by the architecture, because several files under version
# control here (index.html, data/providers_latest.json, data/*.csv, ...) are
# BUILD OUTPUT, not source. A conflict in one of those is never a real
# content conflict: it means both sides regenerated the same derived file
# from different inputs, and the fix is always "take one side, then
# regenerate" -- never a hand line-by-line merge. This script encodes that
# so resolving it is one command, not a fresh investigation every time.
#
# It does NOT auto-resolve conflicts in anything else. A real conflict in
# actual source (copy.json, a .py file, hand-written HTML structure) still
# stops here and asks a human, same as a normal rebase.
#
# Usage: tools/rebase_onto_main.sh
# Run from the branch you want rebased, in its own worktree/checkout.

set -euo pipefail
cd "$(git rev-parse --show-toplevel)"

# path -> regeneration command. Order matters: run in this order after
# resolving all of them via `checkout --theirs` (main's freshest copy), so
# each generator sees the newest inputs before writing its own output.
declare -A REGEN=(
  ["index.html"]="python3 tools/bake_homepage.py"
  ["data/providers_latest.json"]="python3 tools/emit_providers.py"
  ["data/index_latest.json"]="python3 tools/emit_countries.py"
  ["data/corridor_summary.json"]="python3 tools/emit_corridor_summary.py"
  ["data/corridor_window.json"]="python3 tools/bake_homepage.py"
)
# Append-only history files: never hand-merged, never regenerated from
# scratch either (that would fabricate history). On conflict, main's copy is
# the real, live, growing record -- always take it as-is.
APPEND_ONLY=(
  "data/provider_quotes.csv"
  "data/samples.csv"
  "data/basis.csv"
  "data/p2p_basis.csv"
  "data/fx_rates.csv"
)

echo "== fetching origin/main =="
git fetch origin main

echo "== rebasing onto origin/main =="
if git rebase origin/main; then
  echo "== clean rebase, nothing to resolve =="
  exit 0
fi

resolved_any=false
while true; do
  conflicts=$(git diff --name-only --diff-filter=U || true)
  if [ -z "$conflicts" ]; then
    break
  fi

  unhandled=()
  while IFS= read -r path; do
    [ -z "$path" ] && continue
    if [ -n "${REGEN[$path]:-}" ]; then
      echo "  [auto] $path is generated -> take main's copy, will regenerate"
      git checkout --theirs -- "$path"
      git add -- "$path"
      resolved_any=true
    elif printf '%s\n' "${APPEND_ONLY[@]}" | grep -qx "$path"; then
      echo "  [auto] $path is append-only history -> take main's copy as-is"
      git checkout --theirs -- "$path"
      git add -- "$path"
      resolved_any=true
    else
      unhandled+=("$path")
    fi
  done <<< "$conflicts"

  if [ ${#unhandled[@]} -gt 0 ]; then
    echo
    echo "  [stop] real conflict(s), not auto-resolvable:"
    printf '    %s\n' "${unhandled[@]}"
    echo
    echo "  Resolve these by hand, then: git add <file> && git rebase --continue"
    echo "  (Generated/append-only files above were already auto-resolved and staged.)"
    exit 1
  fi

  if ! git rebase --continue; then
    # --continue can re-surface the SAME files as conflicts again on the
    # next commit in the series; loop back and handle them again rather
    # than assuming one pass is enough.
    continue
  fi
  break
done

if [ "$resolved_any" = true ]; then
  echo "== regenerating build output from resolved inputs =="
  for path in "${!REGEN[@]}"; do
    cmd="${REGEN[$path]}"
    echo "  running: $cmd"
    eval "$cmd" || { echo "  [error] regeneration failed: $cmd"; exit 1; }
  done

  if ! git diff --quiet; then
    echo "== committing regenerated output =="
    git add -A
    git commit -m "Regenerate baked output after rebasing onto latest main

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>"
  else
    echo "== regeneration produced no changes, nothing to commit =="
  fi
fi

echo "== done. Verify with tools/check_copy.py and tools/check_index_consistency.py, then push. =="
