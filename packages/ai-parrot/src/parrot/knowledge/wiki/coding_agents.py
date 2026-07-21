"""Native Codex, Claude Code and Gemini CLI wiring for the LLM Wiki.

The installer is intentionally stdlib-only: it can run in a repository before
the optional wiki indexing dependencies are available.  Existing settings are
merged, managed instruction blocks are marker-delimited, and hooks are
advisory (they never deny or rewrite a tool call).
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any, TextIO

NUDGE = (
    "This repository has an ai-parrot LLM-wiki. Before scanning source files, "
    "run `wikitoolkit query \"<focused question>\"`, then inspect a result "
    "with `wikitoolkit page <id>` or `wikitoolkit related <id>`."
)
SKILL = """---
name: parrot-wiki
description: Query the repository LLM-wiki before raw source scans.
---

# Parrot Wiki

Start codebase investigations with `wikitoolkit query \"<focused question>\"`,
then use `wikitoolkit page <id>` and `wikitoolkit related <id>`. Fall back to
raw search only after those paths are empty.
"""

_AGENTS = {
    "codex": ("AGENTS.md", ".codex/hooks.json", "PreToolUse", "Bash|Grep|Glob|Read"),
    "claude": ("CLAUDE.md", ".claude/settings.json", "PreToolUse", "Bash|Grep|Glob|Read"),
    "gemini": (
        "GEMINI.md", ".gemini/settings.json", "AfterTool",
        "run_shell_command|read_file|read_many_files|grep_search|search_file_content|glob|list_directory",
    ),
}


def _markers(agent: str) -> tuple[str, str]:
    return f"<!-- parrot:wiki:{agent}:begin -->", f"<!-- parrot:wiki:{agent}:end -->"


def _block(agent: str) -> str:
    begin, end = _markers(agent)
    return f"{begin}\n## Codebase Knowledge Graph (LLM Wiki)\n\n{NUDGE}\n\n{end}\n"


def _upsert(text: str, block: str, begin: str, end: str) -> str:
    if begin in text:
        head, _, rest = text.partition(begin)
        tail = rest.partition(end)[2] if end in rest else "\n"
        return f"{head}{block.rstrip()}\n{tail.lstrip(chr(10))}"
    return f"{text.rstrip(chr(10)) + chr(10) if text else ''}\n{block}"


def _json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"{path} must contain a JSON object")
    return value


def _hook_entry(agent: str) -> dict[str, Any]:
    _, _, event, matcher = _AGENTS[agent]
    command = f"parrot wiki {agent} hook"
    return {"matcher": f"^({matcher})$", "hooks": [{"type": "command", "command": command, "timeout": 10_000}]}


def install(agent: str, root: Path = Path.cwd()) -> list[str]:
    """Install one agent integration and return changed asset descriptions."""
    if agent not in _AGENTS:
        raise ValueError(f"unsupported agent: {agent}")
    root = root.resolve()
    instruction, settings_name, event, _ = _AGENTS[agent]
    changes: list[str] = []
    instruction_path = root / instruction
    before = instruction_path.read_text(encoding="utf-8") if instruction_path.exists() else ""
    begin, end = _markers(agent)
    after = _upsert(before, _block(agent), begin, end)
    if after != before:
        instruction_path.write_text(after, encoding="utf-8")
    changes.append(instruction)
    skill = root / f".{agent}/skills/parrot-wiki/SKILL.md"
    skill.parent.mkdir(parents=True, exist_ok=True)
    skill.write_text(SKILL, encoding="utf-8")
    changes.append(str(skill.relative_to(root)))
    settings_path = root / settings_name
    data = _json(settings_path)
    hooks = data.setdefault("hooks", {})
    if not isinstance(hooks, dict):
        raise ValueError(f"{settings_path}: hooks must be an object")
    entries = hooks.setdefault(event, [])
    if not isinstance(entries, list):
        raise ValueError(f"{settings_path}: hooks.{event} must be a list")
    desired = _hook_entry(agent)
    command = desired["hooks"][0]["command"]
    entries[:] = [entry for entry in entries if command not in json.dumps(entry)]
    entries.append(desired)
    settings_path.parent.mkdir(parents=True, exist_ok=True)
    settings_path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
    changes.append(settings_name)
    return changes


def hook(agent: str, stdin: TextIO | None = None, stdout: TextIO | None = None) -> int:
    """Emit an advisory hook response; malformed input is always fail-silent."""
    stdin, stdout = stdin or sys.stdin, stdout or sys.stdout
    try:
        payload = json.load(stdin)
        if isinstance(payload, dict) and payload.get("hook_event_name") in (None, _AGENTS[agent][2]):
            json.dump({"systemMessage": NUDGE}, stdout)
            stdout.write("\n")
    except Exception:  # pragma: no cover - hook safety boundary
        return 0
    return 0
