#!/usr/bin/env bash
# launch_worker.sh — start an interactive `sdd-worker` session that never loads
# the `user` setting source.
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
#   scripts/sdd/launch_worker.sh [extra claude args...]
#
# Defaults: --model sonnet (unless the caller passes --model) and
# --setting-sources project,local (unless the caller passes its own, which must
# not include `user`).
#
# Exit codes:
#   2  the caller asked for the `user` setting source

set -euo pipefail

has_model=0
has_sources=0
expect_sources=0
for arg in "$@"; do
  if [[ $expect_sources -eq 1 ]]; then
    sources="$arg"
    expect_sources=0
  else
    case "$arg" in
      --model | --model=*) has_model=1; continue ;;
      --setting-sources) has_sources=1; expect_sources=1; continue ;;
      --setting-sources=*) has_sources=1; sources="${arg#--setting-sources=}" ;;
      *) continue ;;
    esac
  fi
  if [[ ",${sources}," == *",user,"* ]]; then
    echo "launch_worker.sh: refusing --setting-sources '${sources}': the 'user' source loads" \
      "~/.claude PreToolUse hooks that can bypass the Bubblewrap sandbox (issue:6756c929a450)" >&2
    exit 2
  fi
done

cmd=(claude --agent sdd-worker)
if [[ $has_sources -eq 0 ]]; then
  cmd+=(--setting-sources project,local)
fi
if [[ $has_model -eq 0 ]]; then
  cmd+=(--model sonnet)
fi

exec "${cmd[@]}" "$@"
