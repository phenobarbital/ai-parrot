# TASK-3728: Lazy CLI registration + manuals extra in pyproject (M13)

**Feature**: FEAT-601 — Procedure Graph (training agent)
**Spec**: `sdd/specs/training-agent.spec.md`
**Status**: pending
**Priority**: medium
**Estimated effort**: S (< 2h)
**Depends-on**: TASK-3727
**Assigned-to**: unassigned

---

## Context

Spec §3 Module 13 (packaging half) and AC16. `parrot manuals …` must resolve lazily through core's
`LazyGroup` (`cli._lazy_commands`) to the click group `manuals` in `parrot_tools.procedures.cli`
(created by TASK-3727), and give an install hint (`cli._lazy_extras`) when the tools satellite is missing.
A `manuals` optional extra self-references `ai-parrot[graphindex,bookstore]` so rapidfuzz stays declared
only in `graphindex` (`test_dependency_boundary.py` asserts `holders == ["graphindex"]`).

**Exclusive task** (`parallel: false`): it edits `packages/ai-parrot/pyproject.toml`, a dependency manifest.
Adding a self-referencing extra introduces no new package; if the lock check complains, the operator runs
`uv lock` from the main checkout — `uv.lock` is **not** part of this task's files and must not be
regenerated inside the worktree (worktree rule: never `uv sync` in a worktree).

---

## Scope

- Add `"manuals": "parrot_tools.procedures.cli",` to `cli._lazy_commands`.
- Add `"manuals": "ai-parrot-tools: pip install ai-parrot-tools ai-parrot[manuals]",` to `cli._lazy_extras`.
- Add the extra `manuals = ["ai-parrot[graphindex,bookstore]"]` right after the `bookstore` extra.
- Tests: `test_cli_group_registered_lazily`, `test_manuals_extra_self_reference`.

**NOT in scope**: the click group itself (TASK-3727); docs (TASK-3729); any other extra; `uv.lock`.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/cli/__init__.py` | MODIFY | Register `manuals` lazily + install hint |
| `packages/ai-parrot/pyproject.toml` | MODIFY | Add `manuals` optional extra after `bookstore` |
| `packages/ai-parrot/tests/knowledge/manuals/test_packaging.py` | CREATE | Registration + extra tests |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from parrot.cli import cli                          # verified: packages/ai-parrot/src/parrot/cli/__init__.py:103-105 (@click.group(cls=LazyGroup) def cli())
from click.testing import CliRunner                 # verified: packages/ai-parrot/tests/cli/test_devloop_feature_brief.py:14
import tomllib                                      # verified: packages/ai-parrot/tests/knowledge/contracts/test_dependency_boundary.py:12
```

### Existing Signatures to Use
```python
# packages/ai-parrot/src/parrot/cli/__init__.py
class LazyGroup(click.Group):
    def get_command(self, ctx, cmd_name): ...       # lines 71-100 — imports _lazy_commands[cmd_name]; on ImportError of the
                                                    # target module raises click.ClickException("'parrot <cmd>' requires <hint>");
                                                    # returns getattr(mod, cmd_name.replace("-", "_"))
cli._lazy_commands = {                              # line 109; last entries: "devloop": "parrot.cli.devloop", (125) … "mcp-serve" (132); closes at 133
cli._lazy_extras = {                                # line 139; "e2e": _E2E_INSTALL_HINT, at 146; closes at 147

# packages/ai-parrot/pyproject.toml
[project.optional-dependencies]                     # line 209
wiki = ["ai-parrot[graphindex,wiki-languages,wiki-structural,leiden]", ...]   # lines 333-336 — self-reference precedent
bookstore = [ "bm25s>=0.2", "pymupdf>=1.27", "pymupdf4llm>=0.0.27", ]         # lines 341-345

# packages/ai-parrot/tests/knowledge/contracts/test_dependency_boundary.py
REPO_ROOT = Path(__file__).resolve().parents[5]     # line 17 — same depth applies to tests/knowledge/manuals/
def test_rapidfuzz_is_added_to_exactly_one_core_extra(core_project): ... holders == ["graphindex"]   # lines 49-52
```

### Does NOT Exist
- ~~`cli._lazy_commands["manuals"]` / a `manuals` extra~~ — added here.
- ~~A `parrot contracts` subcommand~~ — contracts CLI is argparse behind `python -m parrot_tools.contracts` (F018); do not register it.
- ~~`rapidfuzz` in any extra other than `graphindex`~~ — must stay that way.

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {"path": "packages/ai-parrot/src/parrot/cli/__init__.py", "action": "MODIFY"},
    {"path": "packages/ai-parrot/pyproject.toml", "action": "MODIFY"},
    {"path": "packages/ai-parrot/tests/knowledge/manuals/test_packaging.py", "action": "CREATE"}
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot/src/parrot/cli/__init__.py#LazyGroup.get_command",
    "sym:packages/ai-parrot/src/parrot/cli/__init__.py#cli"
  ]
}
```

---

## Implementation Notes

### Pattern to Follow
`packages/ai-parrot-server/tests/unit/e2e/test_cli.py:103-110` (`test_lazygroup_resolves_e2e`) — asserts the
registry entry and the hint substring.

### Key Constraints
- Worktree tests: the shared `.venv` is editable-installed against the main checkout, so run tests with
  `PYTHONPATH=packages/ai-parrot/src:packages/ai-parrot-tools/src:packages/ai-parrot-integrations/src pytest <file> -q`.
- No new third-party dependency (spec G8, AC18).
- Google-style docstrings and strict type hints on every function/class; Pydantic v2; `self.logger` / module
  `logging.getLogger(__name__)` — never `print`.
- HTTP is `aiohttp` only — never `requests` / `httpx` (ruff TID251 fails the merge gate).
- Existing `Path` attachment behaviour (`images` / `media` / `files` / `documents`) must stay byte-for-byte
  unchanged (AC14) — URL handling is strictly additive.
- The missing-satellite test simulates absence by monkeypatching `importlib.import_module` (or
  `sys.modules["parrot_tools.procedures.cli"] = None`) and asserting `click.ClickException` whose message
  contains `ai-parrot[manuals]`.
- Do not reorder existing dict entries or extras (minimal diff).

---

## Implementation Blueprint

### Steps (in order)
1. Add the `manuals` registry line after `devloop` — *why*: lazy registration is the only wiring core needs (AC16).
2. Add the install hint after `e2e` — *why*: `LazyGroup.get_command` reports it when `parrot_tools` is absent.
3. Add the extra after the `bookstore` block — *why*: spec §3 M13 fixes the composition; placing it after `bookstore` keeps it next to its dependencies.
4. Write `test_packaging.py` — *why*: AC16 + rapidfuzz boundary.

### `packages/ai-parrot/src/parrot/cli/__init__.py` (MODIFY)
```python
# occurrences: 1 (verified: grep -cF '    "devloop": "parrot.cli.devloop",' packages/ai-parrot/src/parrot/cli/__init__.py)
# AFTER — insert below `    "devloop": "parrot.cli.devloop",` (verified: cli/__init__.py:125; inside `cli._lazy_commands = {` at :109)
    # FEAT-601 — Procedure Graph manuals CLI, ships in ai-parrot-tools.
    "manuals": "parrot_tools.procedures.cli",
```
```python
# occurrences: 1 (verified: grep -cF '    "e2e": _E2E_INSTALL_HINT,' .../cli/__init__.py)
# AFTER — insert below `    "e2e": _E2E_INSTALL_HINT,` (verified: cli/__init__.py:146; inside `cli._lazy_extras = {` at :139)
    "manuals": "ai-parrot-tools: pip install ai-parrot-tools ai-parrot[manuals]",
```
**Why**: exact strings fixed by spec §3 M13 skeleton; `get_command` reads attr `manuals` from the module.

### `packages/ai-parrot/pyproject.toml` (MODIFY)
```toml
# occurrences: 1 (verified: grep -cF '    "pymupdf4llm>=0.0.27",' packages/ai-parrot/pyproject.toml)
# AFTER — insert below the `]` that closes `bookstore = [` (anchor `bookstore = [` verified: pyproject.toml:341, occurrences: 1;
#          its last item `    "pymupdf4llm>=0.0.27",` at :344, closing `]` at :345)

# Procedure Graph — field-training agent over assembly manuals (FEAT-601).
# Self-reference so rapidfuzz stays declared only in `graphindex` (test_dependency_boundary.py).
manuals = ["ai-parrot[graphindex,bookstore]"]
```
**Why**: the self-reference adds no third-party package (AC18) and keeps the rapidfuzz holder list unchanged.

### `packages/ai-parrot/tests/knowledge/manuals/test_packaging.py` (CREATE)
```python
"""FEAT-601 M13 — lazy CLI registration and the `manuals` extra (TASK-3728)."""
from __future__ import annotations

import tomllib
from pathlib import Path

import click
import pytest

from parrot.cli import cli

REPO_ROOT = Path(__file__).resolve().parents[5]
CORE_PYPROJECT = REPO_ROOT / "packages" / "ai-parrot" / "pyproject.toml"


def test_cli_group_registered_lazily() -> None:
    """`manuals` maps to parrot_tools.procedures.cli and carries an install hint."""
    assert cli._lazy_commands["manuals"] == "parrot_tools.procedures.cli"
    assert "ai-parrot[manuals]" in cli._lazy_extras["manuals"]
    # FILL IN: when parrot_tools is importable, cli.get_command(ctx, "manuals") returns a click.Group whose
    #          commands include add, add-video, refresh, verify, queue, relink-tips, export, spike (AC16)


def test_cli_missing_satellite_gives_install_hint(monkeypatch: pytest.MonkeyPatch) -> None:
    # FILL IN: make importing parrot_tools.procedures.cli raise ImportError(name="parrot_tools");
    #          assert click.ClickException message contains "ai-parrot[manuals]"
    pass


def test_manuals_extra_self_reference() -> None:
    extras = tomllib.loads(CORE_PYPROJECT.read_text())["project"]["optional-dependencies"]
    assert extras["manuals"] == ["ai-parrot[graphindex,bookstore]"]
    holders = [name for name, items in extras.items() if any("rapidfuzz" in item for item in items)]
    assert holders == ["graphindex"], holders
```

### FILL IN checklist
- [ ] `test_cli_group_registered_lazily` — subcommand listing assertion (skip if `parrot_tools` not importable)
- [ ] `test_cli_missing_satellite_gives_install_hint` — ImportError simulation

---

## Acceptance Criteria

- [ ] `cli._lazy_commands["manuals"] == "parrot_tools.procedures.cli"`; `parrot manuals --help` lists the commands (AC16)
- [ ] Missing satellite ⇒ `ClickException` mentioning `ai-parrot[manuals]`
- [ ] `manuals` extra equals `["ai-parrot[graphindex,bookstore]"]`; rapidfuzz holders still `["graphindex"]`
- [ ] `packages/ai-parrot/tests/knowledge/contracts/test_dependency_boundary.py` still passes
- [ ] All tests pass (see Validation Commands)

---

## Validation Commands

- `pytest packages/ai-parrot/tests/knowledge/manuals/test_packaging.py -q`
- `pytest packages/ai-parrot/tests/knowledge/contracts/test_dependency_boundary.py -q`

---

## Test Specification

| Test | Description |
|---|---|
| `test_cli_group_registered_lazily` | spec §4 M13: `cli._lazy_commands["manuals"]` resolves; subcommands listed |
| `test_cli_missing_satellite_gives_install_hint` | missing satellite ⇒ install hint |
| `test_manuals_extra_self_reference` | spec §4 M13: extra equals `["ai-parrot[graphindex,bookstore]"]`; rapidfuzz holders `["graphindex"]` |

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at the path listed above for full context
2. **Check dependencies** — verify `Depends-on` tasks are in `sdd/tasks/completed/`
3. **Verify the Codebase Contract** — before writing ANY code:
   - Confirm every import in "Verified Imports" still exists (`grep` or `read` the source)
   - Confirm every class/method in "Existing Signatures" still has the listed attributes
   - If anything has changed, update the contract FIRST, then implement
   - **NEVER** reference an import, attribute, or method not in the contract without verifying it exists
4. **Update status** in `sdd/tasks/index/training-agent.json` → `"in-progress"` with your session ID
5. **Implement** — start from the Implementation Blueprint blocks, complete every
   `# FILL IN:` marker, and never change a signature or path the blueprint fixes
6. **Verify** all acceptance criteria are met
7. **Move this file** to `sdd/tasks/completed/`
8. **Update index** → `"done"`
9. **Fill in the Completion Note** below

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**: <session or agent ID>
**Date**: YYYY-MM-DD
**Notes**: What was implemented, any deviations from scope, issues encountered.

**Deviations from spec**: none | describe if any
