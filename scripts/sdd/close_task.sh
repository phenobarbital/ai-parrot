#!/usr/bin/env bash
#
# close_task.sh — Deterministically close a single SDD task.
#
# Moves a task file from sdd/tasks/active/ to sdd/tasks/completed/, marks it
# "done" in its per-spec index (status, completed_at, file path), and stages
# the change — then HARD-VERIFIES that no active/ copy survives.
#
# This exists because agents executing /sdd-start or /sdd-done tend to
# paraphrase the `mv` step as a Write/copy, leaving the active/ file behind.
# When the feature branch merges into the base branch, BOTH copies land →
# "stalled" orphan task files. A script removes that execution drift: there is
# nothing to paraphrase.
#
# Usage:
#   scripts/sdd/close_task.sh <TASK-ID> <feature-slug> [verification]
#
# Example:
#   scripts/sdd/close_task.sh TASK-1429 structured-table verified
#
# Arguments:
#   TASK-ID        e.g. TASK-1429 (the active file is matched by this prefix)
#   feature-slug   per-spec index basename under sdd/tasks/index/<slug>.json
#   verification   optional: verified|partial|forced (default: verified)
#
# Exit codes:
#   0  task closed (or already closed — idempotent)
#   1  usage error
#   2  active file not found AND no completed twin (nothing to close)
#   3  post-condition failed (active copy still present) — must never happen
#
# Ledger emission interpreter:
#   The task.closed emission below needs an interpreter that can import
#   `parrot`. PATH's python3 is that interpreter only in a shell that ran
#   `source .venv/bin/activate` — not in dev-loop coder seats, sandboxed
#   worktree agents or CI — and a failed import is swallowed (the emission is
#   best-effort), silently dropping the event. So the interpreter is resolved
#   explicitly; the first executable candidate wins:
#     1. $SDD_LEDGER_PYTHON          (operator override; ignored when not -x)
#     2. <this script's main checkout>/.venv/bin/python   (cf. codex_hook.sh)
#     3. $VIRTUAL_ENV/bin/python     (an activated venv)
#     4. python3                     (last resort)
#   Candidate 2 is derived from ${BASH_SOURCE[0]}, never from $PWD: this script
#   is routinely run with a cwd in a different repo (the ledger test fixtures)
#   or from a linked worktree, neither of which holds a .venv.
set -euo pipefail

TASK_ID="${1:-}"
FEATURE_SLUG="${2:-}"
VERIFICATION="${3:-verified}"

if [[ -z "$TASK_ID" || -z "$FEATURE_SLUG" ]]; then
  echo "usage: $0 <TASK-ID> <feature-slug> [verified|partial|forced]" >&2
  exit 1
fi

REPO_ROOT="$(git rev-parse --show-toplevel)"
cd "$REPO_ROOT"

ACTIVE_DIR="sdd/tasks/active"
COMPLETED_DIR="sdd/tasks/completed"
INDEX="sdd/tasks/index/${FEATURE_SLUG}.json"
NOW="$(date -u +%Y-%m-%dT%H:%M:%S+00:00)"

mkdir -p "$COMPLETED_DIR"

# Resolve the active file by TASK-ID prefix (slug may vary).
shopt -s nullglob
active_matches=("$ACTIVE_DIR/${TASK_ID}-"*.md)
completed_matches=("$COMPLETED_DIR/${TASK_ID}-"*.md)
shopt -u nullglob

if [[ ${#active_matches[@]} -eq 0 && ${#completed_matches[@]} -gt 0 ]]; then
  echo "ℹ️  ${TASK_ID}: already in completed/ (no active copy) — nothing to move."
  # Still ensure the index reflects done + correct path below.
elif [[ ${#active_matches[@]} -eq 0 ]]; then
  echo "✗ ${TASK_ID}: no file in active/ and no twin in completed/." >&2
  exit 2
fi

basename_md=""
for src in "${active_matches[@]}"; do
  basename_md="$(basename "$src")"
  dest="$COMPLETED_DIR/$basename_md"
  if [[ -e "$dest" ]]; then
    # Twin already exists in completed/ → the active copy is a pure orphan.
    # git rm --ignore-unmatch exits 0 for untracked files without touching the
    # working tree, so rm -f afterwards to guarantee removal either way.
    git rm -q --ignore-unmatch "$src" >/dev/null 2>&1 || true
    rm -f "$src"
    echo "✓ ${TASK_ID}: removed orphan active copy (twin already in completed/)."
  else
    git mv "$src" "$dest" 2>/dev/null || { mv "$src" "$dest"; }
    echo "✓ ${TASK_ID}: moved active → completed/$basename_md"
  fi
done

# Fall back to the completed twin's basename if there was no active match.
if [[ -z "$basename_md" && ${#completed_matches[@]} -gt 0 ]]; then
  basename_md="$(basename "${completed_matches[0]}")"
fi

# Update the per-spec index for this task: status, completed_at, verification, file.
if [[ -f "$INDEX" && -n "$basename_md" ]]; then
  tmp="$(mktemp)"
  jq --arg id "$TASK_ID" --arg now "$NOW" --arg ver "$VERIFICATION" \
     --arg file "$COMPLETED_DIR/$basename_md" '
    (.tasks[] | select(.id == $id) | .status) = "done" |
    (.tasks[] | select(.id == $id) | .completed_at) = $now |
    (.tasks[] | select(.id == $id) | .verification) = $ver |
    (.tasks[] | select(.id == $id) | .file) = $file |
    (if all(.tasks[]; .status == "done") then .completed_at = $now else . end)
  ' "$INDEX" > "$tmp" && mv "$tmp" "$INDEX"
  git add "$INDEX"
fi

# Stage the moves explicitly (never `git add .`).
git add "$COMPLETED_DIR/$basename_md" 2>/dev/null || true
git add -u "$ACTIVE_DIR" 2>/dev/null || true

# HARD POST-CONDITION: no active copy of this task may survive.
shopt -s nullglob
survivors=("$ACTIVE_DIR/${TASK_ID}-"*.md)
shopt -u nullglob
if [[ ${#survivors[@]} -gt 0 ]]; then
  echo "✗ ${TASK_ID}: active copy STILL present after close: ${survivors[*]}" >&2
  exit 3
fi

echo "✅ ${TASK_ID} closed (verification=${VERIFICATION}). active/ is clean."

# FEAT-566 Module 12: emit task.closed to the shared work ledger, AFTER the
# hard post-condition above has already passed. This only ever appends to
# the durable, lock-free events.jsonl log (never touches ledger.db/SQLite),
# so there is no writer contention to handle here — a ledger index sync
# later applies the event. Emission is best-effort: any failure (missing
# parrot.knowledge.wiki package, unwritable shared root, ...) is logged and
# swallowed, never turning an otherwise-successful closure into a failure.
#
# Resolve an interpreter that can import parrot (see the header). Candidates are
# checked for existence only — never probed by running them.
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SCRIPT_COMMON_DIR="$(git -C "$SCRIPT_DIR" rev-parse --path-format=absolute --git-common-dir 2>/dev/null || true)"
SCRIPT_CHECKOUT=""
if [[ -n "$SCRIPT_COMMON_DIR" ]]; then
  SCRIPT_CHECKOUT="$(dirname "$SCRIPT_COMMON_DIR")"
fi
PY_BIN="python3"
for candidate in \
  "${SDD_LEDGER_PYTHON:-}" \
  "${SCRIPT_CHECKOUT:+$SCRIPT_CHECKOUT/.venv/bin/python}" \
  "${VIRTUAL_ENV:+$VIRTUAL_ENV/bin/python}"; do
  if [[ -n "$candidate" && -x "$candidate" ]]; then
    PY_BIN="$candidate"
    break
  fi
done
# The `if !` wrapper (rather than a bare `|| true`): when the interpreter
# itself cannot run, the Python-level handler below never executes, so this is
# the only place the operator would ever hear about it. Closure succeeds
# either way — a ledger failure never undoes a completed closure.
if ! "$PY_BIN" - "$TASK_ID" "$FEATURE_SLUG" "$VERIFICATION" "$PY_BIN" <<'PYEOF'
import sys
from pathlib import Path

task_id, feature_slug, verification, py_bin = sys.argv[1:5]
# Resolve the cwd BEFORE importing parrot: parrot.knowledge.wiki.project pulls
# in parrot.bots -> navigator, and navconfig os.chdir()s to its own project
# root on import, which would redirect the event to the wrong ledger.
start_dir = Path.cwd()

try:
    from parrot.knowledge.wiki.ledger.events import LedgerEvent
    from parrot.knowledge.wiki.ledger.log import LedgerLog
    from parrot.knowledge.wiki.project import find_shared_root

    shared_root = find_shared_root(start_dir) or start_dir
    ledger_dir = shared_root / ".parrot" / "ledger"
    ledger_dir.mkdir(parents=True, exist_ok=True)

    event = LedgerEvent(
        kind="task.closed",
        subject=f"task:{task_id}",
        actor="agent:close_task.sh",
        payload={"feature": feature_slug, "verification": verification},
    )
    LedgerLog(str(ledger_dir / "events.jsonl")).append(event)
except Exception as exc:  # noqa: BLE001 — ledger emission never blocks closure
    print(f"⚠️  task.closed ledger emission skipped ({py_bin}): {exc}", file=sys.stderr)
PYEOF
then
  echo "⚠️  task.closed ledger emission skipped (${PY_BIN} exited non-zero)" >&2
fi
