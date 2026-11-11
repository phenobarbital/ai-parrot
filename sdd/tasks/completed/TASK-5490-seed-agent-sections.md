# TASK-5490: Seed agent sections into .parrot/mcp-toolkits.yaml

**Feature**: FEAT-877 — Agent as a local stdio MCP server
**Spec**: `sdd/specs/agent-local-mcp.spec.md`
**Status**: done
**Priority**: medium
**Estimated effort**: S (< 2h)
**Depends-on**: TASK-5486
**Assigned-to**: unassigned

---

## Context

Packaged toolkits are seeded from `_toolkit_templates/`; agent sections have no template —
they are generated (spec Non-Goals). This task adds `seed_agent_sections()` to
`toolkit_seed.py` (spec §3 **Module 4**, seed half): it writes one `AgentToolkit` section
per requested agent with the same guarantees as `seed_toolkit_sections` — the whole text is
assembled in memory, written once atomically, re-loaded and verified, and an error before
the write leaves the file byte-identical. TASK-5491 calls it from `install_agent_toolkits`.

---

## Scope

- Add `seed_agent_sections(root: Path, agents: Mapping[str, str]) -> SeedResult`
  (`section_name → agent_name`) right after `seed_toolkit_sections`.
- Each section is rendered with `yaml.safe_dump` as
  `{<section>: {"class": AGENT_TOOLKIT_CLASS_PATH, "kwargs": {"agent": <name>}, "env": {}}}`
  and indented two spaces under `toolkits:` (the layout `remove_section` /
  `set_section_enabled` parse).
- An existing section of that name: skipped (`result.skipped`) when it already serves the
  same agent through `AgentToolkit`; otherwise `ValueError` BEFORE any write.
- Create `packages/ai-parrot/tests/mcp/test_agent_toolkit_install.py` with the seed tests.

**NOT in scope**: agent resolution, host reconciliation, reports (TASK-5491); changing
`seed_toolkit_sections` / `preflight_seed` (template-only, untouched).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/mcp/toolkit_seed.py` | MODIFY | `seed_agent_sections` |
| `packages/ai-parrot/tests/mcp/test_agent_toolkit_install.py` | CREATE | Seed tests (TASK-5491 appends install tests) |

---

## Codebase Contract (Anti-Hallucination)

> Verified against `origin/dev` at `41df674d50` (2026-11-11).

### Verified Imports
```python
from parrot.mcp.toolkit_seed import SeedResult, seed_toolkit_sections, remove_section, set_section_enabled  # verified: toolkit_seed.py:41,335 (+ remove_section / set_section_enabled defined above it)
from parrot.mcp.toolkit_config import AGENT_TOOLKIT_CLASS_PATH, load_toolkits_config   # constant: TASK-5486; loader: toolkit_config.py:90
# toolkit_seed.py module imports (lines 3-15): from __future__ import annotations; logging; os; re; shlex; tempfile;
#   from importlib.resources import files; from pathlib import Path; from typing import Any, Sequence (line 12);
#   import yaml; from pydantic import BaseModel, Field
```

### Existing Signatures to Use
```python
# packages/ai-parrot/src/parrot/mcp/toolkit_seed.py
logger = logging.getLogger(__name__)
class SeedResult(BaseModel):                              # line 41
    created_file: bool = False
    added: list[str]; skipped: list[str]; unknown: list[str]; drift: dict[str, list[str]]
def _config_path(root: Path) -> Path                      # line 193 → <root>/.parrot/mcp-toolkits.yaml
def _atomic_write(path: Path, text: str) -> None          # line 198 (temp file in same dir + fsync + os.replace)
def seed_toolkit_sections(root: Path, names: Sequence[str]) -> SeedResult   # line 335 — the pattern to mirror:
    #   local import of load_toolkits_config (line 356); content = path.read_text() + load_toolkits_config(root)
    #   for existing sections; `needs_toolkits_root = not path.exists() or "toolkits:" not in content`;
    #   `needs_leading_newline = bool(content) and not content.endswith("\n")`; one _atomic_write;
    #   post-write re-load → ValueError(f"Failed to re-load seeded config from {path}: {e}") (lines 421-429)
def remove_section(root: Path, name: str) -> bool          # text-based, any section name
def set_section_enabled(root: Path, name: str, enabled: bool) -> bool   # text-based, any section name

# packages/ai-parrot/src/parrot/mcp/toolkit_config.py
class ToolkitSection(BaseModel):                           # line 20 — class_path (alias "class"), kwargs: dict, env: dict
```

### Does NOT Exist
- ~~a template for agents under `parrot/mcp/_toolkit_templates/`~~ — sections are generated.
- ~~`preflight_seed` accepting agent sections~~ — it validates template names only; do not call it here.
- ~~`ruamel.yaml`~~ — use `yaml.safe_dump` (PyYAML) only.

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {"path": "packages/ai-parrot/src/parrot/mcp/toolkit_seed.py", "action": "MODIFY"},
    {"path": "packages/ai-parrot/tests/mcp/test_agent_toolkit_install.py", "action": "CREATE"}
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot/src/parrot/mcp/toolkit_seed.py#SeedResult",
    "sym:packages/ai-parrot/src/parrot/mcp/toolkit_seed.py#seed_toolkit_sections",
    "sym:packages/ai-parrot/src/parrot/mcp/toolkit_seed.py#_atomic_write",
    "sym:packages/ai-parrot/src/parrot/mcp/toolkit_seed.py#_config_path",
    "sym:packages/ai-parrot/src/parrot/mcp/toolkit_config.py#load_toolkits_config"
  ]
}
```

---

## Implementation Notes

### Key Constraints
- `toolkit_seed` must not import `parrot.registry` or `parrot.mcp.agent_toolkit`.
- Import `AGENT_TOOLKIT_CLASS_PATH` and `load_toolkits_config` LOCALLY inside the function,
  as `seed_toolkit_sections` does (keeps module import cost flat).
- Validate everything (malformed file, conflicting sections) before `_atomic_write`.

---

## Implementation Blueprint

### Steps (in order)
1. Add `Mapping` to the typing import — *why*: the spec signature takes a `Mapping[str, str]`.
2. Insert `seed_agent_sections` right after `seed_toolkit_sections` returns — *why*: spec §3 M4 fixes the location.
3. Write the seed tests; run the Validation Commands.

### `packages/ai-parrot/src/parrot/mcp/toolkit_seed.py` (MODIFY) — import
```python
# occurrences: 1 (verified: grep -cx 'from typing import Any, Sequence' toolkit_seed.py → line 12)
# REPLACE with:
from typing import Any, Mapping, Sequence
```

### `toolkit_seed.py` (MODIFY) — new function
```python
# occurrences: 1 (verified: grep -c 'def seed_toolkit_sections(root: Path, names: Sequence\[str\]) -> SeedResult:' toolkit_seed.py)
# AFTER — insert below the END of `seed_toolkit_sections` (its last line is `    return result`, after the
#   `logger.info("seeded %s: ...` call; verified: toolkit_seed.py:335-433), two blank lines before


def seed_agent_sections(root: Path, agents: Mapping[str, str]) -> SeedResult:
    """Create/extend `<root>/.parrot/mcp-toolkits.yaml` with one AgentToolkit section per item (FEAT-877).

    Args:
        root: Project root.
        agents: Section name (``agent-<slug>``) → registry agent name.

    Returns:
        SeedResult naming the added and skipped (already installed) sections.

    Raises:
        ValueError: an existing section of that name serves another agent or class, the
            existing file is malformed, or the written file fails to re-load.
    """
    from parrot.mcp.toolkit_config import AGENT_TOOLKIT_CLASS_PATH, load_toolkits_config  # noqa: PLC0415

    root_path = Path(root)
    path = _config_path(root_path)
    result = SeedResult(created_file=not path.exists())
    content = ""
    existing: dict = {}
    if path.exists():
        content = path.read_text(encoding="utf-8")
        existing = load_toolkits_config(root_path).toolkits  # malformed → ValueError before any write

    pending: list[tuple[str, str]] = []
    for section_name, agent_name in agents.items():
        section = existing.get(section_name)
        # FILL IN: None → pending; same class (AGENT_TOOLKIT_CLASS_PATH) and section.kwargs.get("agent") == agent_name
        #   → result.skipped; anything else → ValueError naming the section, its class and its agent (no write yet)
        ...

    if pending:
        pieces = [content]
        if not path.exists() or "toolkits:" not in content:
            pieces.append("toolkits:\n")
        elif content and not content.endswith("\n"):
            pieces.append("\n")
        for section_name, agent_name in pending:
            body = {"class": AGENT_TOOLKIT_CLASS_PATH, "kwargs": {"agent": agent_name}, "env": {}}
            rendered = yaml.safe_dump({section_name: body}, sort_keys=False, default_flow_style=False)
            pieces.append("".join(f"  {line}\n" for line in rendered.splitlines()))
            result.added.append(section_name)
        _atomic_write(path, "".join(pieces))

    # FILL IN: when result.added, re-load with load_toolkits_config(root_path) and raise
    #   ValueError(f"Failed to re-load seeded config from {path}: {e}") if a seeded name is missing or parsing fails
    #   — mirror seed_toolkit_sections lines 421-429; then logger.info as it does; return result
    ...
```
**Why**: the two-space layout keeps `remove_section` / `set_section_enabled` (text-based)
working on agent sections unchanged — that is what makes AC-7 free.

### `packages/ai-parrot/tests/mcp/test_agent_toolkit_install.py` (CREATE)
```python
"""FEAT-877 Module 4 — seeding and installing agent sections."""
from __future__ import annotations

from pathlib import Path

import pytest

from parrot.mcp.toolkit_config import AGENT_TOOLKIT_CLASS_PATH, load_toolkits_config
from parrot.mcp.toolkit_seed import seed_agent_sections, seed_toolkit_sections


def _config(root: Path) -> Path:
    return root / ".parrot" / "mcp-toolkits.yaml"


def test_seed_agent_section_written(tmp_path: Path) -> None:
    result = seed_agent_sections(tmp_path, {"agent-finance": "finance"})
    assert result.created_file and result.added == ["agent-finance"]
    section = load_toolkits_config(tmp_path).toolkits["agent-finance"]
    assert section.class_path == AGENT_TOOLKIT_CLASS_PATH
    assert section.kwargs == {"agent": "finance"}
    # FILL IN: seeding again → skipped == ["agent-finance"], file byte-identical; seeding into a file that
    #   already has a template section (seed_toolkit_sections(tmp_path, ["memory"])) keeps it and appends


def test_seed_agent_section_conflict(tmp_path: Path) -> None:
    # FILL IN: seed {"agent-finance": "finance"}; seeding {"agent-finance": "other"} raises ValueError and the
    #   file is byte-identical; a hand-written "agent-x" section with another class also raises
    ...


def test_seed_agent_section_malformed_file(tmp_path: Path) -> None:
    # FILL IN: write invalid YAML to the config → ValueError and the file is byte-identical
    ...
```

### FILL IN checklist
- [ ] the skip/conflict branch — spec §3 M4.
- [ ] the post-write re-load — mirror `seed_toolkit_sections`.
- [ ] every `...` test body.

---

## Acceptance Criteria

- [ ] A new section has class `parrot.mcp.agent_toolkit.AgentToolkit`, `kwargs: {agent: <name>}`, `env: {}`.
- [ ] Re-seeding the same agent is a skip; a conflicting existing section raises before any write (file byte-identical).
- [ ] Existing template sections and comments are preserved.
- [ ] `toolkit_seed` still imports nothing from `parrot.registry`.
- [ ] `ruff check` clean on both files.

---

## Validation Commands

- `pytest packages/ai-parrot/tests/mcp/test_agent_toolkit_install.py -q`
- `pytest packages/ai-parrot/tests/mcp/test_toolkit_install.py -q`

---

## Test Specification

See the CREATE block above: spec §4 Module 4 rows `test_seed_agent_section_written`,
`test_seed_agent_section_conflict`, plus `test_seed_agent_section_malformed_file`.

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
9. **Close the task** with `parrot sdd task close TASK-5490 agent-local-mcp verified`
10. **Fill in the Completion Note** below, then commit the staged SDD state

---

## Completion Note


- Task: TASK-5490
- Feature: agent-local-mcp
- Implementation SHA: 6be06f17097bdd4d54da566b87995e438c6a7ca2
- Closed at (UTC): 2026-11-11T00:21:02+00:00
- Fix commits: none

| Metric | Value |
|---|---|
| validation_refs | 1 |
| fix_commits | 0 |
| seat_summary | Seat: gpt-5.6-sol · Backend: codex · Model: gpt-5.6-sol · Attempts: 1 · Duration: 135s · Tokens: n/a |
