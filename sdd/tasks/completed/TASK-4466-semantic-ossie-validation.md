# TASK-4466: Apache Ossie 0.1.1 document validation (M4 — ossie)

**Feature**: FEAT-704 — Semantic Layer — governed metric queries for agents (`ai-parrot-semantic`)
**Spec**: `sdd/specs/semantic-layer.spec.md`
**Status**: pending
**Priority**: medium
**Estimated effort**: S (< 2h)
**Depends-on**: TASK-4464
**Assigned-to**: unassigned

---

## Context

Spec §3 Module 4 (ossie part) + AC15: Apache Ossie 0.1.1 documents are validated against a vendored JSON Schema before sidemantic's importer sees them; a 0.2 document is rejected, not coerced (§7).

---

## Scope

- Vendor the Apache Ossie 0.1.1 JSON Schema at `packages/ai-parrot-semantic/src/parrot/semantic/schemas/ossie-0.1.1.schema.json`.
- Implement `packages/ai-parrot-semantic/src/parrot/semantic/ossie.py`: `OSSIE_SPEC_VERSION`, `is_ossie_document`, `validate_ossie_document`.
- Add a valid fixture `packages/ai-parrot-semantic/tests/fixtures/ossie/orders.ossie.json` (the `orders` model of spec §4 Test Data) and test it.

**NOT in scope**: loading the document into sidemantic (TASK-4467).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot-semantic/src/parrot/semantic/schemas/ossie-0.1.1.schema.json` | CREATE | vendored Ossie 0.1.1 JSON Schema |
| `packages/ai-parrot-semantic/src/parrot/semantic/ossie.py` | CREATE | detection + validation |
| `packages/ai-parrot-semantic/tests/fixtures/ossie/orders.ossie.json` | CREATE | valid 0.1.1 fixture |
| `packages/ai-parrot-semantic/tests/test_ossie.py` | CREATE | schema tests |

---

## Codebase Contract (Anti-Hallucination)

> **CRITICAL**: This section contains VERIFIED code references from the actual codebase
> (re-verified on `dev` @ 754878f67, 2026-10-19). Use these exact imports, class names and
> method signatures. **DO NOT** invent, guess or assume anything not listed here — verify first.
> `grep` in this repo is aliased to `ugrep` by RTK: use `grep -F` for anchors with `(`, `[`, `{`.

### Verified Imports
```python
import jsonschema                                  # declared by TASK-4463 (jsonschema>=4.20)
from importlib.resources import files              # stdlib — load the vendored schema from package data
from parrot.semantic.errors import SemanticPolicyError   # TASK-4464
```

### Existing Signatures to Use
```python
# no existing core signature is used by this task
```

### Does NOT Exist
- ~~An Apache Ossie Python SDK on PyPI~~ — `ossie` / `apache-ossie` / `osi-spec` do not exist; the schema is vendored.
- ~~Network access at test time~~ — the schema is read from package data only.

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {
      "path": "packages/ai-parrot-semantic/src/parrot/semantic/schemas/ossie-0.1.1.schema.json",
      "action": "CREATE"
    },
    {
      "path": "packages/ai-parrot-semantic/src/parrot/semantic/ossie.py",
      "action": "CREATE"
    },
    {
      "path": "packages/ai-parrot-semantic/tests/fixtures/ossie/orders.ossie.json",
      "action": "CREATE"
    },
    {
      "path": "packages/ai-parrot-semantic/tests/test_ossie.py",
      "action": "CREATE"
    }
  ],
  "contract_symbols": []
}
```

---

## Implementation Notes

- Obtain the official 0.1.1 schema file from the Apache Ossie repository (tagged 0.1.1) and record its source URL + commit in the Completion Note. If it cannot be obtained, STOP and mark the task `done-with-issues` — do not hand-write a schema.
- `is_ossie_document` keys off the document's declared spec-version field as named by the schema (read it from the schema, do not guess).

### Key Constraints
- Async-first; sync CPU-only work (sqlglot, sidemantic compile) runs under `asyncio.to_thread` at the call site.
- Pydantic v2 models; `logging.getLogger(__name__)` / `self.logger`, never `print`.
- Google-style docstrings, strict type hints, 120-column lines; `ruff check` clean (TID251 bans apply).
- Fail closed wherever governance is involved (spec §7 "Patterns to Follow").
- Worktree testing: prefix pytest with `PYTHONPATH=packages/ai-parrot-semantic/src:packages/ai-parrot/src` (add `:packages/ai-parrot-server/src` for server tests); never `uv sync` inside a worktree.

---

## Implementation Blueprint

> **Executor-ready starting point.** Write each block to its declared path nearly verbatim,
> then complete every `# FILL IN:` marker. Never change a signature, class name or path the
> blueprint fixes (they come from the spec §3 Interface Skeletons).

### Steps (in order)
1. Vendor the schema file — *why*: no SDK exists (spec §6 Does NOT Exist).
2. Write `ossie.py` — *why*: the loader (TASK-4467) calls it before sidemantic.
3. Write the fixture + tests.

### `packages/ai-parrot-semantic/src/parrot/semantic/ossie.py` (CREATE)
```python
"""Apache Ossie 0.1.1 detection and validation against the vendored JSON Schema."""
from __future__ import annotations

import json
from functools import lru_cache
from importlib.resources import files
from typing import Any

import jsonschema

from .errors import SemanticPolicyError

OSSIE_SPEC_VERSION = "0.1.1"


@lru_cache(maxsize=1)
def _schema() -> dict[str, Any]:
    return json.loads(files("parrot.semantic").joinpath("schemas/ossie-0.1.1.schema.json").read_text())


def is_ossie_document(doc: dict) -> bool:
    """True when `doc` declares itself an Apache Ossie document (any version)."""
    # FILL IN: check the version/kind marker field the schema requires — bounded by the vendored schema
    raise NotImplementedError


def validate_ossie_document(doc: dict) -> None:
    """Validate against the vendored 0.1.1 schema.

    Raises:
        SemanticPolicyError: code "ossie_version" for a version other than 0.1.1 (never coerced);
            code "ossie_invalid" with details["path"] = the first error's JSON path otherwise.
    """
    # FILL IN: version check first; then jsonschema.Draft202012Validator (or the draft the schema's
    #          "$schema" names) -> sorted(iter_errors) by path; raise on the first
    raise NotImplementedError
```
**Why**: spec §3 M4 skeleton; `files()` reads package data shipped via `[tool.setuptools.package-data]` (TASK-4463).

### FILL IN checklist
- [ ] `is_ossie_document` marker — bounded by the vendored schema.
- [ ] `validate_ossie_document` error codes — `ossie_version` / `ossie_invalid`.
- [ ] Schema provenance in the Completion Note.

---

## Acceptance Criteria

- [ ] `test_ossie_schema_validation` passes: fixture validates; a doc missing a required field fails with its path; a `0.2.0` doc fails with `ossie_version` (AC15).

---

## Validation Commands

> File-level pytest only — no directories, no package roots. Run with `PYTHONPATH=packages/ai-parrot-semantic/src:packages/ai-parrot/src` in a worktree.

- `pytest packages/ai-parrot-semantic/tests/test_ossie.py -q`

---

## Test Specification

```python
# packages/ai-parrot-semantic/tests/test_ossie.py
import json
from pathlib import Path
import pytest
from parrot.semantic.ossie import validate_ossie_document, is_ossie_document
from parrot.semantic.errors import SemanticPolicyError

FIX = Path(__file__).parent / "fixtures/ossie/orders.ossie.json"


def test_ossie_schema_validation():
    doc = json.loads(FIX.read_text())
    assert is_ossie_document(doc)
    validate_ossie_document(doc)
    # FILL IN: drop a required key -> SemanticPolicyError with details["path"]; bump version -> code "ossie_version"
```

---

## Agent Instructions

When you pick up this task:

1. **Work in the feature worktree** — never on `dev`
   (`python -m scripts.sdd.ensure_worktree --slug semantic-layer --feature-id FEAT-704 --spec sdd/specs/semantic-layer.spec.md --index sdd/tasks/index/semantic-layer.json`).
2. **Read the spec** (`sdd/specs/semantic-layer.spec.md`), especially the sections named in Context.
3. **Check dependencies** — every `Depends-on` task is `done` in `sdd/tasks/index/semantic-layer.json`.
4. **Verify the Codebase Contract** before writing code; fix a stale entry in this file first.
5. **Implement** exactly the files above, following the blueprint; touch nothing else.
6. **Validate**: `ruff check --fix <files>`, then the Validation Commands.
7. **Commit** only the listed files: `feat(semantic-layer): TASK-4466 — Apache Ossie 0.1.1 document validation (M4 — ossie)`.
8. **Close** with `scripts/sdd/close_task.sh TASK-4466 semantic-layer verified` and fill in the Completion Note.

---

## Completion Note

- Task: TASK-4466
- Feature: semantic-layer
- Closed at (UTC): 2026-10-19
- Fix commits: none
- Seat: gpt-5.6-sol · Backend: codex · Model: gpt-5.6-sol · Attempts: 1 · Duration: 277.7s · Tokens: n/a
- Validation: merge-tier ad0839b5:wave3:merge completed exit 0 (12 passed).
- Review: coder-review:4da8264f37092f416cc7f1fb — no corrections.
