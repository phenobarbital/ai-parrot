#!/usr/bin/env bash
# launch_worker.sh — start an interactive `sdd-worker` session in the strict
# native Claude sandbox (FEAT-768), without loading the `user` setting source.
#
# Why (issue:6756c929a450): the sdd-worker agent file installs a PreToolUse hook
# that wraps every Bash call in Bubblewrap by returning `updatedInput`. A
# user-level hook in ~/.claude (e.g. RTK's global `rtk hook claude`, or a
# plugin's catch-all PreToolUse hook) can return its own `updatedInput` for the
# same call, and Claude Code does not define which rewrite wins — so a command
# can run outside the sandbox. Loading only the `project` and `local` setting
# sources keeps those hooks out. Cost: user-level permissions, plugins and
# ~/.claude/CLAUDE.md are not loaded in this session.
#
# Usage (from inside the feature worktree):
#   scripts/sdd/launch_worker.sh [--sandbox-allow-domain HOST] [extra claude args...]
#
# Defaults: --model sonnet (unless the caller passes --model) and
# --setting-sources project,local (unless the caller passes its own, which must
# not include `user`).
#
# Exit codes:
#   1  a host prerequisite is missing
#   2  caller input violates the native sandbox policy

set -euo pipefail

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
python_bin="$(command -v python3 || true)"
if [[ -z "$python_bin" ]]; then
  echo "launch_worker.sh: python3 is required (activate the repository venv)" >&2
  exit 1
fi
exec "$python_bin" "$repo_root/packages/ai-parrot/src/parrot/flows/dev_loop/native_claude_sandbox.py" \
  launch-worker "$@"
