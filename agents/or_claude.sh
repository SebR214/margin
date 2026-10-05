#!/usr/bin/env bash
# Run one coding task with Claude Code on a cheaper OpenRouter model (about 90% cheaper
# than the subscription models), from a desktop session or a terminal.
#
#   agents/or_claude.sh <model> <worktree-dir> <prompt-file>
#   agents/or_claude.sh deepseek/deepseek-v4-pro /path/to/worktree task.md
#
# Needs OPENROUTER_API_KEY in the environment (or exported by ~/.zshrc: it is read
# from there without being printed). Edits happen only inside the given directory.
set -euo pipefail
MODEL="${1:?model}"; DIR="${2:?worktree dir}"; PROMPT="${3:?prompt file}"
KEY="${OPENROUTER_API_KEY:-}"
[ -n "$KEY" ] || KEY=$(zsh -ic 'printf %s "$OPENROUTER_API_KEY"' 2>/dev/null | tail -c 73)
[ -n "$KEY" ] || { echo "OPENROUTER_API_KEY not set" >&2; exit 64; }
cd "$DIR"
ANTHROPIC_BASE_URL=https://openrouter.ai/api ANTHROPIC_AUTH_TOKEN="$KEY" ANTHROPIC_API_KEY= CLAUDE_CODE_OAUTH_TOKEN= \
  claude -p "$(cat "$PROMPT")" --model "$MODEL" \
    --allowedTools Bash,Read,Edit,Write,Glob,Grep --permission-mode acceptEdits \
    --max-turns "${OR_MAX_TURNS:-120}" --output-format text
