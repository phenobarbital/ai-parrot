# TASK-2069: Charter model, YAML loader & fingerprint

**Feature**: FEAT-402 — Supervised Wiki Ingestion (charter-driven triage + HITL manifest review)
**Spec**: `sdd/specs/supervised-wiki-ingestion.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: none
**Assigned-to**: unassigned

---

## Context

Implements **Module 1** of the spec (§3). The editorial charter is the
versioned policy artifact that drives every triage decision: scope rules,
scoring-dimension weights, admit/reject thresholds, routing destinations,
calibration policy, and the few-shot examples loop. Everything downstream
(manifest, triage router, CLI) consumes these models.

Design reference (adapt, do NOT import):
`sdd/state/FEAT-402-supervised-wiki-ingestion/references/charter.example.yaml`
and `references/schemas.py`.

---

## Scope

- Implement `packages/ai-parrot/src/parrot/knowledge/wiki/charter.py`:
  - Pydantic models: `Charter`, `CharterScope` (include/exclude rules),
    `Thresholds` (with `route(composite: float) -> Literal["admit", "gray", "reject"]`),
    `CalibrationPolicy` (audit fractions: `near_fraction=0.6`,
    `uniform_fraction=0.4`; gray-zone widening; propose-only),
    `TriageExample`, `Amendment`.
  - Validators: `weights` keys must match the dimension names
    (`density`, `novelty`, `durability`), each in [0,1], sum ≈ 1.0 ±0.01
    (mirror `WikiConfig.validate_search_weights`); `reject < admit`.
  - `load_charter(path: Path) -> Charter`: YAML load + validation +
    sha256 fingerprint of the canonical file bytes exposed as
    `Charter.fingerprint` (computed at load, not a stored YAML field).
  - `append_example(charter, example, ...)` helper that appends a human
    decision to `examples_file` (JSONL or YAML list — pick one, document it).
- Ship a documented example charter as a test fixture (adapt
  `charter.example.yaml`; admit 0.75 / reject 0.35 as EXAMPLE values only —
  never hardcoded defaults in code).
- Write `tests/knowledge/wiki/test_charter.py`.

**NOT in scope**: manifest models (TASK-2070), triage logic (TASK-2071),
CLI (TASK-2075), any change to `WikiConfig` (TASK-2072 adds `charter_path`).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/knowledge/wiki/charter.py` | CREATE | Charter models + loader + fingerprint + examples append |
| `tests/knowledge/wiki/test_charter.py` | CREATE | Unit tests + example-charter fixture |

---

## Codebase Contract (Anti-Hallucination)

> Verified against `dev` @ `ad6365242` (2026-08-02). Re-verify per Agent
> Instructions before implementing.

### Verified Imports
```python
import yaml                    # PyYAML>=6.0.2, core dep (packages/ai-parrot/pyproject.toml:52)
from pydantic import BaseModel, Field, field_validator, model_validator
```

### Existing Signatures to Use
```python
# packages/ai-parrot/src/parrot/knowledge/wiki/models.py:114-140
# PATTERN to mirror for the weights validator (do not import it):
# @field_validator("search_weights") — each weight in [0,1], sum ≈ 1.0 ±0.01
```

### Does NOT Exist
- ~~`parrot/knowledge/wiki/charter.py`~~ — you are creating it; zero hits under `packages/` today.
- ~~`Charter`~~, ~~`Thresholds`~~, ~~`TriageExample`~~ — no such symbols anywhere in shipped code.
- ~~importing `sdd/state/FEAT-402-supervised-wiki-ingestion/references/schemas.py`~~ — design sketch only, NOT on the import path; re-implement per spec §2 Data Models.

---

## Implementation Notes

### Key Constraints
- Pure models + sync file I/O (loader is called from CLI setup before the
  async pipeline; no async needed here — document that).
- Google-style docstrings, strict type hints, module-level
  `logging.getLogger(__name__)`.
- Fingerprint = `hashlib.sha256(<raw file bytes>).hexdigest()` — over the
  bytes as read, so any edit (even whitespace) versions the policy.
- `Thresholds.route`: `composite >= admit → "admit"`; `composite < reject → "reject"`; else `"gray"`.

### References in Codebase
- `packages/ai-parrot/src/parrot/knowledge/wiki/models.py` — validator style, Field descriptions.
- Spec §2 "Data Models" — authoritative field lists.

---

## Acceptance Criteria

- [ ] `load_charter` accepts the example charter YAML and returns a validated `Charter` with a stable sha256 fingerprint across repeated loads.
- [ ] Weights not summing to ~1.0 → `ValidationError`; `reject >= admit` → `ValidationError`.
- [ ] `Thresholds.route` bands correct at the boundaries (composite == admit → admit; == reject → gray).
- [ ] `append_example` appends and round-trips through `examples_file`.
- [ ] All tests pass: `pytest tests/knowledge/wiki/test_charter.py -v`
- [ ] No linting errors: `ruff check packages/ai-parrot/src/parrot/knowledge/wiki/charter.py`
- [ ] Import works: `from parrot.knowledge.wiki.charter import Charter, load_charter`

---

## Test Specification

```python
# tests/knowledge/wiki/test_charter.py
import pytest
from parrot.knowledge.wiki.charter import Charter, Thresholds, load_charter

@pytest.fixture
def sample_charter(tmp_path):
    ...  # write minimal valid charter YAML, return Path

def test_charter_load_valid(sample_charter): ...          # fingerprint stable
def test_charter_weights_must_sum(tmp_path): ...          # sum != 1.0 rejected
def test_charter_thresholds_order(tmp_path): ...          # reject >= admit rejected
def test_thresholds_route_bands(): ...                    # admit/gray/reject boundaries
def test_examples_file_append(tmp_path): ...              # append + round-trip
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at the path listed above for full context
2. **Check dependencies** — none for this task
3. **Verify the Codebase Contract** — before writing ANY code, confirm the
   references above still hold; if anything changed, update the contract
   FIRST, then implement
4. **Update status** in `sdd/tasks/index/supervised-wiki-ingestion.json` → `"in-progress"`
5. **Implement** following the scope, codebase contract, and notes above
6. **Verify** all acceptance criteria are met
7. **Move this file** to `sdd/tasks/completed/TASK-2069-charter-model-loader.md`
8. **Update index** → `"done"`
9. **Fill in the Completion Note** below

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**:
**Date**:
**Notes**:

**Deviations from spec**: none
