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
python3 - "$TASK_ID" "$FEATURE_SLUG" "$VERIFICATION" <<'PYEOF' || true
import sys
from pathlib import Path

task_id, feature_slug, verification = sys.argv[1:4]

try:
    from parrot.knowledge.wiki.ledger.events import LedgerEvent
    from parrot.knowledge.wiki.ledger.log import LedgerLog
    from parrot.knowledge.wiki.project import find_shared_root

    shared_root = find_shared_root(Path.cwd()) or Path.cwd()
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
    print(f"⚠️  task.closed ledger emission skipped: {exc}", file=sys.stderr)
PYEOF
