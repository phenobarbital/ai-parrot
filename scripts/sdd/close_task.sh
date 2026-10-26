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
exec "${PYTHON:-python3}" -m parrot.sdd.scripts.close_task "$@"
