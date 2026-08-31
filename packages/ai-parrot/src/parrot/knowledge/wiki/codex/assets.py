"""Managed assets for the Codex WikiToolkit integration."""

from __future__ import annotations

import json
import shutil
from pathlib import Path

AGENTS_BEGIN = "<!-- parrot:wiki:codex:begin -->"
AGENTS_END = "<!-- parrot:wiki:codex:end -->"
MCP_BEGIN = "# >>> parrot-wiki Codex MCP >>>"
MCP_END = "# <<< parrot-wiki Codex MCP <<<"
RULES_BEGIN = "# >>> parrot-wiki Codex permissions >>>"
RULES_END = "# <<< parrot-wiki Codex permissions <<<"
MCP_TABLE = "mcp_servers.wikitoolkit"
SKILL_PATH = Path(".codex/skills/parrot-wiki/SKILL.md")
RULES_PATH = Path(".codex/rules/parrot-wiki.rules")

AGENTS_SECTION = f"""{AGENTS_BEGIN}
## Codebase Knowledge Graph (LLM Wiki)

This repository has an ai-parrot LLM-wiki. Before scanning source files, run `wikitoolkit query "<focused question>"`, then inspect a result with `wikitoolkit page <id>` or `wikitoolkit related <id>`. When you learn a durable fact or decision, save it: `wikitoolkit remember "<fact>" --category decision`.

{AGENTS_END}
"""

SKILL = """---
name: parrot-wiki
description: Query the repository LLM-wiki before raw source scans, and save durable knowledge into it.
---

# Parrot Wiki

Start codebase investigations with `wikitoolkit query "<focused question>"`,
then use `wikitoolkit page <id>` and `wikitoolkit related <id>`. Fall back to
raw search only after those paths are empty.

The wiki is also persistent memory. Save durable facts, decisions, and lessons
with `wikitoolkit remember "<fact>" --category <note|decision|lesson|concept>`.
Use `wikitoolkit note`, `wikitoolkit link`, `wikitoolkit memories`, and
`wikitoolkit audit` to maintain and review that knowledge.
"""


def resolve_binary(root: Path, name: str) -> str:
    """Resolve a project-venv binary, then PATH, then its bare name."""
    venv_binary = root / ".venv" / "bin" / name
    if venv_binary.exists():
        return str(venv_binary)
    return shutil.which(name) or name


def mcp_block(root: Path) -> str:
    """Return the managed project-scoped Codex MCP configuration."""
    command = json.dumps(resolve_binary(root, "wikitoolkit"))
    return (
        f"{MCP_BEGIN}\n"
        f"[{MCP_TABLE}]\n"
        f"command = {command}\n"
        'args = ["mcp"]\n'
        'default_tools_approval_mode = "approve"\n'
        f"{MCP_END}\n"
    )


def rules_block(root: Path) -> str:
    """Return allow rules for every supported WikiToolkit CLI surface."""
    patterns = [["wikitoolkit"], ["parrot", "wiki"]]
    resolved_wiki = resolve_binary(root, "wikitoolkit")
    resolved_parrot = resolve_binary(root, "parrot")
    for pattern in ([resolved_wiki], [resolved_parrot, "wiki"]):
        if pattern not in patterns:
            patterns.append(pattern)
    rules = [RULES_BEGIN]
    for pattern in patterns:
        rules.append(
            "prefix_rule("
            f"pattern={json.dumps(pattern)}, "
            'decision="allow", '
            'justification="Allow repository WikiToolkit commands installed by parrot codex install"'
            ")"
        )
    rules.append(RULES_END)
    return "\n".join(rules) + "\n"
