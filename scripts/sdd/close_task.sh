#!/usr/bin/env bash
#
# close_task.sh — Deterministically close a single SDD task.
#
# Compatibility wrapper (FEAT-633): the logic lives in parrot.sdd.scripts.close_task.
# Usage and exit codes are unchanged:
#   scripts/sdd/close_task.sh <TASK-ID> <feature-slug> [verified|partial|forced]
#   0 closed (idempotent) · 1 usage · 2 nothing to close · 3 post-condition failed
set -euo pipefail

_src="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../packages/ai-parrot/src" 2>/dev/null && pwd || true)"
if [[ -n "$_src" ]]; then
  export PYTHONPATH="${_src}${PYTHONPATH:+:${PYTHONPATH}}"
fi

# Interpreter that can import `parrot` (the task.closed ledger emission is best-effort and a failed import
# would silently drop the event). PATH's python3 is that interpreter only in a shell that ran
# `source .venv/bin/activate` — not in dev-loop coder seats, sandboxed worktree agents or CI. First executable
# candidate wins (checked for existence only, never probed). `$SDD_LEDGER_PYTHON` is honoured by close_task.py itself,
# for the ledger emission only:
#   1. $PYTHON                       (operator override; ignored when not -x)
#   2. <this script's main checkout>/.venv/bin/python
#   3. $VIRTUAL_ENV/bin/python
#   4. python3
# Candidate 2 comes from ${BASH_SOURCE[0]}, never $PWD: this script runs with a cwd in other repos (ledger test
# fixtures) or from a linked worktree, neither of which holds a .venv.
_script_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
_common_dir="$(git -C "$_script_dir" rev-parse --path-format=absolute --git-common-dir 2>/dev/null || true)"
_checkout=""
if [[ -n "$_common_dir" ]]; then
  _checkout="$(dirname "$_common_dir")"
fi
PY_BIN="python3"
for candidate in \
  "${PYTHON:-}" \
  "${_checkout:+$_checkout/.venv/bin/python}" \
  "${VIRTUAL_ENV:+$VIRTUAL_ENV/bin/python}"; do
  if [[ -n "$candidate" && -x "$candidate" ]]; then
    PY_BIN="$candidate"
    break
  fi
done
exec "$PY_BIN" -m parrot.sdd.scripts.close_task "$@"
