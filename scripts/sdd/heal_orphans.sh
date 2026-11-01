#!/usr/bin/env bash
#
# heal_orphans.sh — Self-healing sweep for stalled SDD task files.
#
# Compatibility wrapper (FEAT-633): the logic lives in parrot.sdd.scripts.heal_orphans.
# Usage and exit codes are unchanged:
#   scripts/sdd/heal_orphans.sh [--dry-run] [feature-slug]
set -euo pipefail

_src="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../packages/ai-parrot/src" 2>/dev/null && pwd || true)"
if [[ -n "$_src" ]]; then
  export PYTHONPATH="${_src}${PYTHONPATH:+:${PYTHONPATH}}"
fi
exec "${PYTHON:-python3}" -m parrot.sdd.scripts.heal_orphans "$@"
