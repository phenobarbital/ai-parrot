#!/bin/sh
# Brief agy-permission-hook — launcher for the agy PreToolUse permission policy (tracked .agents/hooks.json).
# Runs the policy from THIS checkout's source with the shared .venv of the main checkout, so a linked worktree
# evaluates its own branch (like scripts/sdd/codex_hook.sh). agy blocks a command whose hook fails, and a silent
# pass would drop the narrowing while the broad agy rules stay active, so every failure answers force_ask:
# agy then asks before each command until the hook works again.
unavailable() {
    printf '%s\n' "{\"decision\": \"force_ask\", \"reason\": \"agy permission hook unavailable ($1); confirm each command\"}"
    exit 0
}
top=$(git rev-parse --show-toplevel 2>/dev/null) || unavailable "not a git checkout"
common_dir=$(git rev-parse --path-format=absolute --git-common-dir 2>/dev/null) || unavailable "no git common dir"
python_bin="$(dirname "$common_dir")/.venv/bin/python"
[ -x "$python_bin" ] || unavailable "no .venv in the main checkout"
src="$top/packages/ai-parrot/src"
[ -f "$src/parrot/sdd/scripts/agy_permissions.py" ] || unavailable "policy module missing"
out=$(PYTHONPATH="$src${PYTHONPATH:+:$PYTHONPATH}" "$python_bin" -m parrot.sdd.scripts.agy_permissions --hook 2>/dev/null) ||
    unavailable "policy failed to run"
[ -n "$out" ] || unavailable "empty answer"
printf '%s\n' "$out"
