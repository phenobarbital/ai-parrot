---
type: Wiki Overview
title: 'TASK-1169: Add `jsonpath-ng` and `aioboto3` to `pyproject.toml`'
id: doc:sdd-tasks-completed-task-1169-pyproject-deps-md
tags:
- overview
timestamp: '2026-07-16T08:34:12+00:00'
summary: Two new runtime dependencies. Jinja2 ≥ 3.1 is already pinned.
---

# TASK-1169: Add `jsonpath-ng` and `aioboto3` to `pyproject.toml`

**Feature**: FEAT-170 — FormDesigner `FieldType.REST`
**Spec**: `sdd/specs/new-formdesigner-field-rest.spec.md` (Module 10)
**Status**: pending
**Priority**: medium
**Estimated effort**: S (< 2h)
**Depends-on**: none
**Assigned-to**: unassigned

---

## Context

Two new runtime dependencies. Jinja2 ≥ 3.1 is already pinned.

---

## Scope

- Edit `packages/parrot-formdesigner/pyproject.toml`:
  - Add `"jsonpath-ng>=1.6.1"` to `[project] dependencies`.
  - Add `"aioboto3>=12.0"` to `[project] dependencies`.
- Regenerate `uv.lock` (or local equivalent) — run
  `uv lock` from `packages/parrot-formdesigner/`.
- Smoke test: `uv pip install` succeeds and both modules import.

**NOT in scope**: lockfile policies for the umbrella `ai-parrot` repo
(if a separate top-level lock exists, it does not need to change).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/parrot-formdesigner/pyproject.toml` | MODIFY | +2 deps |
| `packages/parrot-formdesigner/uv.lock` (if tracked) | MODIFY | regenerated |

---

## Codebase Contract (Anti-Hallucination)

### Verified

Existing pinned deps in `packages/parrot-formdesigner/pyproject.toml`:
`pydantic`, `aiohttp`, `asyncdb`, `PyYAML`, `jinja2>=3.1`, `aiogram`,
`navigator-auth`, `lxml`, `reportlab`, `pycountry`.

### Does NOT Exist

- ~~`jsonpath-ng`~~ — not pinned today.
- ~~`aioboto3` / `boto3`~~ — not pinned today.

---

## Acceptance Criteria

- [ ] `pyproject.toml` contains both new dep lines with the minimum versions.
- [ ] `uv pip install .` inside the package succeeds.
- [ ] `python -c "import jsonpath_ng, aioboto3"` succeeds inside the venv.
- [ ] `test_pyproject_has_jsonpath_ng_aioboto3` passes (spec §4).

---

## Test Specification

```python
import tomllib
from pathlib import Path

def test_pyproject_has_jsonpath_ng_aioboto3():
    p = Path("packages/parrot-formdesigner/pyproject.toml")
    data = tomllib.loads(p.read_text())
    deps = data["project"]["dependencies"]
    assert any(d.startswith("jsonpath-ng") for d in deps)
    assert any(d.startswith("aioboto3") for d in deps)
```

---

## Completion Note

*(Agent fills this in when done)*
