# TASK-5486: Agent-section helpers in toolkit_config

**Feature**: FEAT-877 — Agent as a local stdio MCP server
**Spec**: `sdd/specs/agent-local-mcp.spec.md`
**Status**: done
**Priority**: high
**Estimated effort**: S (< 2h)
**Depends-on**: none
**Assigned-to**: unassigned

---

## Context

An installed agent becomes a `.parrot/mcp-toolkits.yaml` section named `agent-<slug>`
whose class is `parrot.mcp.agent_toolkit.AgentToolkit`. Seed, install, stale detection
and the toolkit itself all need that naming rule and that class path, and three of them
(`toolkit_seed`, `toolkit_stale`, `toolkit_config`'s own loader) must stay free of
registry/agent imports. This task implements spec §3 **Module 2**: two constants and two
pure functions in the light `toolkit_config` module.

---

## Scope

- Add `AGENT_TOOLKIT_CLASS_PATH: str = "parrot.mcp.agent_toolkit.AgentToolkit"` and
  `AGENT_SECTION_PREFIX: str = "agent-"`.
- Add `agent_section_name(agent_name: str) -> str`: lower-case; every run of characters
  outside `[a-z0-9]` → one `-`; strip leading/trailing `-`; prefix `agent-`; an empty slug
  raises `ValueError`.
- Add `is_agent_section(section: ToolkitSection) -> bool`:
  `section.class_path == AGENT_TOOLKIT_CLASS_PATH`.
- Write `packages/ai-parrot/tests/mcp/test_agent_section_config.py`.

**NOT in scope**: importing `parrot.mcp.agent_toolkit` (it does not exist yet and must
never be imported from here); seeding sections (TASK-5490); stale rules (TASK-5492).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/mcp/toolkit_config.py` | MODIFY | Constants + `agent_section_name` + `is_agent_section` |
| `packages/ai-parrot/tests/mcp/test_agent_section_config.py` | CREATE | Unit tests |

---

## Codebase Contract (Anti-Hallucination)

> Verified against `origin/dev` at `41df674d50` (2026-11-11).

### Verified Imports
```python
from parrot.mcp.toolkit_config import ToolkitSection, MCPToolkitsConfig, load_toolkits_config  # verified: toolkit_config.py:20,80,90
# toolkit_config.py module imports today (lines 11-16): from pathlib import Path / from typing import Any /
#   import yaml / from pydantic import BaseModel, ConfigDict, Field, model_validator   — `re` is NOT imported yet
```

### Existing Signatures to Use
```python
# packages/ai-parrot/src/parrot/mcp/toolkit_config.py
class ToolkitSection(BaseModel):            # line 20 — class_path is aliased "class" in YAML
    class_path: str                          # (alias "class")
    enabled: bool = True
    kwargs: dict[str, Any]
class MCPToolkitsConfig(BaseModel):          # line 80
    toolkits: dict[str, ToolkitSection] = Field(default_factory=dict)
```

### Does NOT Exist
- ~~`parrot.mcp.agent_toolkit`~~ — created by TASK-5487; the class path here is a plain string.
- ~~`ToolkitSection.agent`~~ / ~~`ToolkitSection.kind`~~ — a section is recognised by its `class_path` only.
- ~~`slugify` helper in `parrot.mcp`~~ — write the regex inline.

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {"path": "packages/ai-parrot/src/parrot/mcp/toolkit_config.py", "action": "MODIFY"},
    {"path": "packages/ai-parrot/tests/mcp/test_agent_section_config.py", "action": "CREATE"}
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot/src/parrot/mcp/toolkit_config.py#ToolkitSection",
    "sym:packages/ai-parrot/src/parrot/mcp/toolkit_config.py#MCPToolkitsConfig"
  ]
}
```

---

## Implementation Notes

### Key Constraints
- `toolkit_config` is imported by `toolkit_server` on every `mcp-local` start: keep it
  dependency-free (no registry, no agent, no `parrot.bots`).
- `ToolkitSection` is constructed with the alias: `ToolkitSection(**{"class": "...", "kwargs": {}})`
  or `ToolkitSection.model_validate({"class": ...})` — check `model_config` for
  `populate_by_name` before using `class_path=` in tests.

---

## Implementation Blueprint

### Steps (in order)
1. Add `import re` to the module imports — *why*: the slug rule is a regex.
2. Insert the constants and both functions above `class MCPToolkitsConfig` — *why*: spec §3 M2 fixes their location and `ToolkitSection` is defined above it.
3. Write the tests, run the Validation Commands.

### `packages/ai-parrot/src/parrot/mcp/toolkit_config.py` (MODIFY) — import
```python
# occurrences: 1 (verified: grep -cx 'from typing import Any' toolkit_config.py → line 14)
# BEFORE — insert above `from pathlib import Path` (line 11), keeping stdlib imports together
import re
```

### `toolkit_config.py` (MODIFY) — helpers
```python
# occurrences: 1 (verified: grep -c 'class MCPToolkitsConfig(BaseModel):' toolkit_config.py)
# BEFORE — insert above `class MCPToolkitsConfig(BaseModel):` (verified: toolkit_config.py:80)
#: FEAT-877 — class path of the toolkit that serves one registered agent.
AGENT_TOOLKIT_CLASS_PATH: str = "parrot.mcp.agent_toolkit.AgentToolkit"
#: FEAT-877 — prefix of every generated agent section name.
AGENT_SECTION_PREFIX: str = "agent-"

_SLUG_SEPARATORS = re.compile(r"[^a-z0-9]+")


def agent_section_name(agent_name: str) -> str:
    """Return the `.parrot/mcp-toolkits.yaml` section name for an agent ("agent-<slug>").

    Lower-cases the name, collapses every run of characters outside ``[a-z0-9]``
    into one ``-`` and strips leading/trailing ``-``.

    Args:
        agent_name: Registered agent name.

    Returns:
        ``"agent-<slug>"``.

    Raises:
        ValueError: the name has no ``[a-z0-9]`` character.
    """
    # FILL IN: slug = _SLUG_SEPARATORS.sub("-", agent_name.lower()).strip("-");
    #   empty slug → ValueError naming the agent; return f"{AGENT_SECTION_PREFIX}{slug}" — bounded by spec §3 M2


def is_agent_section(section: ToolkitSection) -> bool:
    """True when the section serves an agent through AgentToolkit (FEAT-877)."""
    return section.class_path == AGENT_TOOLKIT_CLASS_PATH
```
**Why**: a section is an agent section because of its class, never because of its name —
so a hand-written section named `agent-x` with another class is not treated as one.

### `packages/ai-parrot/tests/mcp/test_agent_section_config.py` (CREATE)
```python
"""FEAT-877 Module 2 — agent-section naming and recognition."""
from __future__ import annotations

import pytest

from parrot.mcp.toolkit_config import (
    AGENT_SECTION_PREFIX,
    AGENT_TOOLKIT_CLASS_PATH,
    ToolkitSection,
    agent_section_name,
    is_agent_section,
)


@pytest.mark.parametrize(
    ("name", "expected"),
    [
        ("Finance Bot", "agent-finance-bot"),
        ("finance", "agent-finance"),
        ("  __Finance__Bot!!  ", "agent-finance-bot"),
        ("HR.Assistant-v2", "agent-hr-assistant-v2"),
    ],
)
def test_agent_section_name_slug(name: str, expected: str) -> None:
    assert agent_section_name(name) == expected
    assert agent_section_name(name).startswith(AGENT_SECTION_PREFIX)


@pytest.mark.parametrize("name", ["", "   ", "!!!", "ñ"])
def test_agent_section_name_empty_slug_raises(name: str) -> None:
    # FILL IN: pytest.raises(ValueError) — bounded by spec §3 M2
    ...


def test_is_agent_section() -> None:
    # FILL IN: True for a section whose class is AGENT_TOOLKIT_CLASS_PATH; False for a
    #   packaged-toolkit class and for a section NAMED "agent-x" with another class
    ...
```

### FILL IN checklist
- [ ] `agent_section_name` body — bounded by spec §3 M2 (slug rule, `ValueError`).
- [ ] the two `...` test bodies.

---

## Acceptance Criteria

- [ ] `agent_section_name("Finance Bot") == "agent-finance-bot"`; an unsluggable name raises `ValueError`.
- [ ] `is_agent_section` is true only for the `AgentToolkit` class path.
- [ ] `toolkit_config` still imports nothing from `parrot.registry` / `parrot.bots`.
- [ ] `ruff check packages/ai-parrot/src/parrot/mcp/toolkit_config.py packages/ai-parrot/tests/mcp/test_agent_section_config.py` is clean.

---

## Validation Commands

- `pytest packages/ai-parrot/tests/mcp/test_agent_section_config.py -q`

---

## Test Specification

See the CREATE block above (`test_agent_section_name_slug`,
`test_agent_section_name_empty_slug_raises`, `test_is_agent_section`).

---

## Agent Instructions

When you pick up this task:

1. **Work in the feature worktree** — never on `base_branch`
   (`parrot sdd worktree ensure --slug agent-local-mcp --feature-id FEAT-877`)
2. **Read the spec** at the path listed above for full context
3. **Check dependencies** — every `Depends-on` task must be `"done"` in
   `sdd/tasks/index/agent-local-mcp.json`
4. **Verify the Codebase Contract** before writing code; if anything changed, update the contract first
5. **Update status** in the per-spec index → `"in-progress"` (set `started_at`) and commit only that file
6. **Implement** from the Implementation Blueprint; complete every `# FILL IN:` marker
7. **Verify** the acceptance criteria — run the Validation Commands with `PYTHONPATH=packages/ai-parrot/src`
8. **Commit the code** — stage only the files this task lists
9. **Close the task** with `parrot sdd task close TASK-5486 agent-local-mcp verified`
10. **Fill in the Completion Note** below, then commit the staged SDD state

---

## Completion Note


- Task: TASK-5486
- Feature: agent-local-mcp
- Implementation SHA: 371e2855073c6c37cc921371c86fe253ea5ef438
- Closed at (UTC): 2026-11-11T00:14:26+00:00
- Fix commits: none

| Metric | Value |
|---|---|
| validation_refs | 1 |
| fix_commits | 0 |
| seat_summary | Seat: gpt-5.6-sol · Backend: codex · Model: gpt-5.6-sol · Attempts: 1 · Duration: 95s · Tokens: n/a |
