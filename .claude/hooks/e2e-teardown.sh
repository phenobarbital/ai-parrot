#!/usr/bin/env bash
# SubagentStop / Stop hook — owner/worktree-scoped, defense-in-depth E2E
# teardown for FEAT-581's M8 exploration agents (`e2e-api-tester`,
# `e2e-ui-tester`).
#
# Registered in .claude/settings.json for both events:
#   * SubagentStop  fires when an exploration agent runs as a delegated
#                   subagent;
#   * Stop          fires when it was launched standalone
#                   (`claude --agent e2e-api-tester`/`e2e-ui-tester`), where
#                   it IS the main agent.
# Both payloads carry `agent_type`, so one script covers both and no-ops for
# every other agent (including a plain session with no `agent_type` at all).
#
# This is a SAFETY NET, not the primary cleanup path — spec §2 ("Hooks are
# defense in depth ... Portable correctness never depends on a
# host-specific hook, nesting limit, or promise that a shell process
# survives a sub-agent's return"). Both exploration agents' own
# instructions (`.claude/agents/e2e-api-tester.md`,
# `.claude/agents/e2e-ui-tester.md`) already call
# `parrot e2e down --all --owner-id explore-<agent-type>` themselves before
# finishing; this hook only catches the case where that did not happen
# (crash, denied capability, cut context, etc.).
#
# Owner identity is deliberately a FIXED per-role slug
# (`explore-e2e-api-tester` / `explore-e2e-ui-tester`), computed from
# `agent_type` alone — never a session ID this hook cannot independently
# reconstruct from its own payload without depending on undocumented,
# host-specific hook-input fields. The two exploration agents' own docs
# commit to this exact identity, so the hook can always find and stop
# whatever they started.
#
# Teardown is always `parrot e2e down --all --owner-id <id>` (spec §2:
# "owner-scoped teardown hooks"; "never a global stale kill") — scoped to
# ONE owner identity inside ONE resolved worktree, never every run on the
# machine and never `--stale` (that flag is the documented recovery path
# for an abandoned run from a *different*, earlier invocation, not this
# hook's own immediate cleanup). This script never writes to any
# machine-local settings file (e.g. `.claude/settings.json` itself) — it
# only ever shells out to the already-installed `parrot` CLI.
#
# Never blocks and never fails the agent/session lifecycle: always exits 0,
# whatever the teardown outcome was. Skip with PARROT_SKIP_E2E_TEARDOWN=1.
set -uo pipefail

INPUT=$(cat)
[[ "${PARROT_SKIP_E2E_TEARDOWN:-}" == "1" ]] && exit 0
command -v jq >/dev/null 2>&1 || exit 0

note() { echo "[e2e-teardown] $*" >&2; }

# --- Parse the (possibly malformed) hook payload ----------------------------
# A malformed payload (invalid JSON, missing fields) is never a hard
# failure: `jq -r '... // empty'` degrades to an empty string on a parse
# error too (stderr is discarded), and every empty/unexpected value below
# routes to a silent, successful no-op.
AGENT_TYPE=$(echo "$INPUT" | jq -r '.agent_type // empty' 2>/dev/null)
CWD=$(echo "$INPUT" | jq -r '.cwd // empty' 2>/dev/null)

# Only the two M8 exploration agents this task ships trigger a teardown;
# every other agent_type (including empty, from a malformed payload or a
# plain Stop event) is none of our business.
case "$AGENT_TYPE" in
    e2e-api-tester | e2e-ui-tester) ;;
    *)
        exit 0
        ;;
esac

[[ -n "$CWD" && -d "$CWD" ]] || {
    note "missing or invalid cwd in hook payload — nothing to tear down."
    exit 0
}

cd "$CWD" 2>/dev/null || exit 0
git rev-parse --git-dir >/dev/null 2>&1 || {
    note "cwd is not a git worktree — skipping."
    exit 0
}

# --- Resolve the worktree root ----------------------------------------------
# Same convention as parrot.e2e.cli._resolve_worktree(): walk up from cwd to
# the nearest ".git" entry (an ordinary repo's directory, or a linked
# worktree's ".git" file both count) — never an arbitrary path.
WORKTREE="$CWD"
CURRENT="$CWD"
while [[ "$CURRENT" != "/" ]]; do
    if [[ -e "$CURRENT/.git" ]]; then
        WORKTREE="$CURRENT"
        break
    fi
    CURRENT=$(dirname "$CURRENT")
done

# --- Fixed, per-role owner identity ------------------------------------------
# Matches exactly what .claude/agents/e2e-api-tester.md and
# .claude/agents/e2e-ui-tester.md instruct that agent to pass as its own
# --owner-id on every `parrot e2e up`/`down` call.
OWNER_ID="explore-${AGENT_TYPE}"

# --- Resolve the venv's `parrot` entry point --------------------------------
# The worktree has no .venv of its own (worktree-management.md); check the
# same candidate locations sdd-worker-format.sh uses for its own tools.
VENV_BIN=""
for candidate in "$CWD/.venv/bin" "${CLAUDE_PROJECT_DIR:-}/.venv/bin" \
    "$(git rev-parse --git-common-dir 2>/dev/null)/../.venv/bin"; do
    if [[ -n "$candidate" && -x "$candidate/parrot" ]]; then
        VENV_BIN=$(cd "$candidate" && pwd)
        break
    fi
done
PARROT="${VENV_BIN:+$VENV_BIN/}parrot"
command -v "$PARROT" >/dev/null 2>&1 || {
    note "parrot CLI not found — skipping (ai-parrot-server may not be installed)."
    exit 0
}

# --- Immediate, owner/worktree-scoped teardown ------------------------------
note "tearing down every run owned by '$OWNER_ID' in $WORKTREE ..."
OUTPUT=$(cd "$WORKTREE" && timeout 30 "$PARROT" e2e down --all --owner-id "$OWNER_ID" 2>&1)
RC=$?
note "parrot e2e down --all --owner-id $OWNER_ID exited $RC"
[[ -n "$OUTPUT" ]] && note "$OUTPUT"

# A failed, already-clean, or unavailable teardown is not a hook error —
# this hook is defense in depth, never a blocker.
exit 0
