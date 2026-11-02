#!/usr/bin/env bash
# PreToolUse hook (agent frontmatter) — confines the file-writing tools of the
# FEAT-581 M8 exploration agents (`e2e-api-tester`, `e2e-ui-tester`) to
# `<project>/sdd/state/FEAT-*/e2e/exploration/`.
#
# Reads the PreToolUse JSON on stdin, takes `tool_input.file_path` (or
# `notebook_path`), resolves it against $CLAUDE_PROJECT_DIR (realpath: `..` and
# symlinks normalized) and exits 2 with a reason on stderr for anything outside
# the allowed tree. Missing / unparseable input fails CLOSED.
#
# Scope: Write|Edit|MultiEdit|NotebookEdit only. Bash is NOT confined — shell
# redirections cannot be parsed reliably, so Bash writes remain prompt discipline.
exec python3 -c '
import json, os, sys

def deny(reason):
    sys.stderr.write("e2e-exploration-write-guard: BLOCKED - " + reason + "\n")
    sys.exit(2)

try:
    payload = json.loads(sys.stdin.read())
    tool_input = payload["tool_input"]
    raw = tool_input.get("file_path") or tool_input.get("notebook_path")
except Exception:
    deny("unparseable hook payload (fail closed)")
if not isinstance(raw, str) or not raw.strip():
    deny("no file_path in tool_input (fail closed)")

root = os.path.realpath(os.environ.get("CLAUDE_PROJECT_DIR") or os.getcwd())
target = os.path.realpath(raw if os.path.isabs(raw) else os.path.join(root, raw))
try:
    rel = os.path.relpath(target, root)
except ValueError:
    deny("path is outside the project: " + raw)
parts = rel.split(os.sep)
ok = (
    len(parts) >= 6
    and parts[:2] == ["sdd", "state"]
    and parts[2].startswith("FEAT-")
    and parts[3:5] == ["e2e", "exploration"]
)
if not ok:
    deny("exploration agents may only write under sdd/state/FEAT-*/e2e/exploration/ (got " + raw + ")")
sys.exit(0)
'
