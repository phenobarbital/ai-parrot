# TASK-3745: Register TOOL_REGISTRY['hooba'], add the `hooba` extra and package data for spec JSON + rules YAML

**Feature**: FEAT-602 — HoobaToolkit — OpenAPI-first Hooba automation with a private Playwright fallback and BBVA expense drafts
**Spec**: `sdd/specs/hooba-toolkit.spec.md`
**Status**: pending
**Priority**: medium
**Estimated effort**: S (< 2h)
**Depends-on**: TASK-3743
**Assigned-to**: unassigned

---

## Context

Spec §3 **Module 11** (packaging half), AC-15. Registers the toolkit for lazy discovery,
declares an optional `hooba` extra composing the extras its modules already import from,
and ships the non-Python data files (the pinned spec JSON and the rules YAML) in the wheel.

---

## Scope

- `parrot_tools/__init__.py`: `"hooba": "parrot_tools.hooba.toolkit.HoobaToolkit"` after the `business_automation` entry.
- `pyproject.toml`: `hooba = ["ai-parrot-tools[business_automation,excel,scraping]", "pyyaml>=6.0"]`; add `hooba` to `all`;
  package-data `"parrot_tools.hooba.spec" = ["*.json"]`, `"parrot_tools.hooba.rules" = ["*.yaml"]`.
- `tests/hooba/test_packaging.py`.

**NOT in scope**: running `uv lock` / `uv sync` inside the worktree (forbidden — see Notes).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot-tools/src/parrot_tools/__init__.py` | MODIFY | TOOL_REGISTRY entry |
| `packages/ai-parrot-tools/pyproject.toml` | MODIFY | hooba extra, all, package-data |
| `packages/ai-parrot-tools/tests/hooba/test_packaging.py` | CREATE | registry + pyproject assertions |

---

## Codebase Contract (Anti-Hallucination)

> **CRITICAL**: This section contains VERIFIED code references from the actual codebase
> (re-verified 2026-09-25 against `dev` at `ad42d9aff`).
> The implementing agent MUST use these exact imports, class names, and method signatures.
> **DO NOT** invent, guess, or assume any import, attribute, or method not listed here.

### Verified Imports
```python
from parrot_tools import TOOL_REGISTRY                                        # verified: parrot_tools/__init__.py:13
import tomllib                                                                # stdlib (py3.11+)
```

### Existing Signatures to Use
```python
# packages/ai-parrot-tools/src/parrot_tools/__init__.py
TOOL_REGISTRY: dict[str, str] = {                                             # line 13
    "business_automation": "parrot_tools.business_automation.toolkit.BusinessAutomationToolkit",   # line 36 (occurrences: 1)

# packages/ai-parrot-tools/pyproject.toml
business_automation = ["pandas>=2.0", "ai-parrot-loaders"]                   # line 107 (occurrences: 1)
all = [                                                                        # line 108
    "ai-parrot-tools[jira,pdf,...,research,business_automation]"              # line 109 (occurrences of '"ai-parrot-tools[jira,pdf,msword': 1)
"parrot_tools.aws.policies" = ["*.json"]                                      # line 132 (occurrences: 1) — last [tool.setuptools.package-data] entry
```

### Does NOT Exist
- ~~A `hooba` extra~~ / ~~`TOOL_REGISTRY["hooba"]`~~ — new here.
- ~~Running `scripts/generate_tool_registry.py`~~ — manual entries are preserved by it; add the line by hand.

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {
      "path": "packages/ai-parrot-tools/src/parrot_tools/__init__.py",
      "action": "MODIFY"
    },
    {
      "path": "packages/ai-parrot-tools/pyproject.toml",
      "action": "MODIFY"
    },
    {
      "path": "packages/ai-parrot-tools/tests/hooba/test_packaging.py",
      "action": "CREATE"
    }
  ],
  "contract_symbols": []
}
```

---

## Implementation Notes

- The shared `.venv` is editable-installed against the main checkout: `importlib.metadata` shows the MAIN checkout's
  extras, so the test reads `pyproject.toml` with `tomllib` instead.
- Do NOT run `uv lock` or `uv sync` in the worktree (repoints the shared venv). Record in the Completion Note that the
  main-checkout operator must run `uv lock` after merge.

### Key Constraints (all FEAT-602 tasks)
- async-first: no blocking I/O inside `async def` — wrap pandas/openpyxl/filesystem work in `asyncio.to_thread` (spec §7, S10).
- aiohttp only in new code: `httpx` and `requests` are banned by ruff TID251; the only httpx surface is inside the exempt `HTTPService` / `openapitoolkit.py`.
- Pydantic v2 models for every structured value; `self.logger` (or a module `logger = logging.getLogger(__name__)`), never `print`.
- Never log cookie values, passwords, IBANs or full bank rows at INFO or above.
- Google-style docstrings and strict type hints on every function and class; `black` line length 120; `ruff check` clean.
- Drafts only: no code path may call `:issue`, `:confirm`, `:cancel`, `:send*`, a DELETE, or any write outside `DRAFT_OPERATIONS` (spec G3, AC-5).
- Worktree testing: the shared `.venv` is editable-installed against the MAIN checkout. Run tests with
  `PYTHONPATH=packages/ai-parrot/src:packages/ai-parrot-tools/src:packages/ai-parrot-loaders/src pytest ...` so the worktree's code is imported. Never `uv sync` in a worktree.
- Fixtures are synthetic: never commit real Hooba selectors, credentials, bank exports or personal data (AC-17).

---

## Implementation Blueprint

> **CRITICAL — Executor-ready starting point.** Write each block below to its declared
> path nearly verbatim, then complete every `# FILL IN:` marker. Blocks were derived
> from the spec's Interface Skeletons (§3) and re-verified against the Codebase Contract
> above. Business-logic branches, edge cases and test bodies are `FILL IN` stubs by design.
> Never change a signature, class name, or file path the blueprint fixes.

### Steps (in order)
1. Registry line — *why*: lazy discovery by name.
2. pyproject extra, `all`, package-data — *why*: AC-15; without package-data the wheel lacks the spec JSON and YAML.
3. Test.

### `packages/ai-parrot-tools/src/parrot_tools/__init__.py` (MODIFY)
```python
# occurrences: 1 (verified: grep -c '"business_automation": "parrot_tools.business_automation.toolkit.BusinessAutomationToolkit",' __init__.py) — line 36
# AFTER — insert below that line:
    "hooba": "parrot_tools.hooba.toolkit.HoobaToolkit",
```

### `packages/ai-parrot-tools/pyproject.toml` (MODIFY)
```toml
# (a) occurrences: 1 (verified: grep -c 'business_automation = \["pandas>=2.0", "ai-parrot-loaders"\]') — line 107
# AFTER — insert below it:
# FEAT-602: HoobaToolkit — BBVA Excel parsing (excel, business_automation), Playwright fallback (scraping), rules YAML.
hooba = ["ai-parrot-tools[business_automation,excel,scraping]", "pyyaml>=6.0"]

# (b) line 109: append ",hooba" inside the brackets after "business_automation" in the `all` entry.

# (c) occurrences: 1 (verified: grep -c '"parrot_tools.aws.policies" = \["\*.json"\]') — line 132
# AFTER — insert below it:
"parrot_tools.hooba.spec" = ["*.json"]
"parrot_tools.hooba.rules" = ["*.yaml"]
```

### `packages/ai-parrot-tools/tests/hooba/test_packaging.py` (CREATE)
```python
"""FEAT-602 TASK-3745 — registry and packaging."""
import importlib
import tomllib
from pathlib import Path

from parrot_tools import TOOL_REGISTRY

PYPROJECT = Path(__file__).resolve().parents[2] / "pyproject.toml"


def test_registry_entry_resolves():
    # FILL IN: module, cls = TOOL_REGISTRY["hooba"].rsplit(".", 1); getattr(importlib.import_module(module), cls)


def test_hooba_extra_and_package_data_declared():
    # FILL IN: tomllib.loads(PYPROJECT.read_text()); "hooba" extra contents; "hooba" in all; package-data keys
```

### FILL IN checklist
- [ ] both test bodies
- [ ] Completion Note: "run `uv lock` in the main checkout after merge"

---

## Acceptance Criteria

- [ ] AC-15 (spec): `TOOL_REGISTRY['hooba']` resolves; the `hooba` extra composes business_automation, excel, scraping and pyyaml; `all` includes it; package-data ships the spec JSON and rules YAML.
- [ ] No `uv lock`/`uv sync` run inside the worktree.

---

## Validation Commands

> File-level pytest only — no directories, no package roots. In a worktree, prefix with the
> `PYTHONPATH=` shown in Key Constraints.

- `pytest packages/ai-parrot-tools/tests/hooba/test_packaging.py -q`

---

## Test Specification

| Test | Asserts |
|---|---|
| `test_registry_entry_resolves` | registry path importable |
| `test_hooba_extra_and_package_data_declared` | pyproject contents |

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at the path listed above for full context (§2, §3 module, §6, §7).
2. **Check dependencies** — verify every `Depends-on` task is done in `sdd/tasks/index/hooba-toolkit.json`.
3. **Verify the Codebase Contract** — before writing ANY code:
   - Confirm every import in "Verified Imports" still exists (`grep` or `read` the source)
   - Confirm every anchor in the blueprint still has the stated occurrence count (`grep -c`)
   - If anything has changed, update the contract FIRST, then implement
   - **NEVER** reference an import, attribute, or method not in the contract without verifying it exists
4. **Update status** in `sdd/tasks/index/hooba-toolkit.json` → `"in-progress"`.
5. **Implement** — start from the Implementation Blueprint blocks, complete every
   `# FILL IN:` marker, and never change a signature or path the blueprint fixes.
6. **Verify** all acceptance criteria and run every Validation Command.
7. **Move this file** to `sdd/tasks/completed/`.
8. **Update the index** → `"done"`.
9. **Fill in the Completion Note** below.

---

## Completion Note

**Completed by**: sdd-worker (seat=mistral, backend=nova, model=mistral.devstral-2-123b,
attempt_uid=c583d9474a97487b8a10b22d647af397, execution_id=85c083ec-56b6-42fe-8884-e686fbcf7a61)
**Date**: 2026-09-26
**Notes**: Registered `TOOL_REGISTRY['hooba'] = 'parrot_tools.hooba.toolkit.HoobaToolkit'`,
added the `hooba` extra (`ai-parrot-tools[business_automation,excel,scraping]` + `pyyaml>=6.0`)
and included it in `all`, and added `package-data` entries for
`parrot_tools.hooba.spec` (`*.json`) and `parrot_tools.hooba.rules` (`*.yaml`). Delivered
via `coder_run_chunk` (1 attempt, 0 retries, 0 failures), merged cleanly with 0 lint
residuals. Full `packages/ai-parrot-tools/tests/hooba/` suite: 55/55 passed post-merge
(includes new `test_packaging.py`). **`uv lock` was NOT run inside the worktree** (per
task instructions, to avoid repointing the shared venv) — **the main-checkout operator
must run `uv lock` after this branch merges** to pick up the new `hooba` extra.

**Deviations from spec**: none.
