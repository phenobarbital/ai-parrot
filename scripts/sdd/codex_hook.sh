#!/bin/sh
# FEAT-563 — portable launcher for the codex PreToolUse hook.
# Resolves the MAIN checkout (the one owning the shared .venv) from any linked
# worktree and runs the parrot_tools guard with the hook payload on stdin.
# Never breaks codex: any missing piece exits 0 silently (no decision).
common_dir=$(git rev-parse --path-format=absolute --git-common-dir 2>/dev/null) || exit 0
main_checkout=$(dirname "$common_dir")
python_bin="$main_checkout/.venv/bin/python"
[ -x "$python_bin" ] || exit 0
exec "$python_bin" -m parrot_tools.tool_optimizations.hooks --host codex
