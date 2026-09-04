# TASK-2805: Satellite Package — ai-parrot-client-hf

**Feature**: FEAT-523 — PEP 420 LLM Client Extraction
**Spec**: `sdd/specs/pep-420-llm-clients.spec.md`
**Status**: pending
**Priority**: medium
**Estimated effort**: S (< 2h)
**Depends-on**: TASK-2795
**Assigned-to**: unassigned

---

## Context

Extract `TransformersClient` from core into the `ai-parrot-client-hf`
satellite package. Part of spec Module 6 (standalone providers).
Single-file satellite.

---

## Scope

- Create `packages/ai-parrot-client-hf/` with PEP 420 structure:
  ```
  packages/ai-parrot-client-hf/
  ├── pyproject.toml
  └── src/
      └── parrot/          # .gitkeep only (NO __init__.py)
          └── clients/     # .gitkeep only (NO __init__.py)
              └── hf.py
  ```
- Move `packages/ai-parrot/src/parrot/clients/hf.py` → satellite
- Create `pyproject.toml` with entry points and dependencies
- Delete the original file from core

**NOT in scope**: factory.py changes (TASK-2795), pyproject.toml extras (TASK-2806), tests (TASK-2807).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot-client-hf/pyproject.toml` | CREATE | Package metadata |
| `packages/ai-parrot-client-hf/src/parrot/.gitkeep` | CREATE | PEP 420 |
| `packages/ai-parrot-client-hf/src/parrot/clients/.gitkeep` | CREATE | PEP 420 |
| `packages/ai-parrot-client-hf/src/parrot/clients/hf.py` | CREATE (move) | TransformersClient |
| `packages/ai-parrot/src/parrot/clients/hf.py` | DELETE | Moved to satellite |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from parrot.clients.base import AbstractClient  # clients/base.py:230
```

### Does NOT Exist
- ~~`parrot.clients.huggingface`~~ — the file is named `hf.py`, not `huggingface.py`

---

## Implementation Notes

### pyproject.toml
```toml
[build-system]
requires = ["setuptools>=77.0.0", "wheel>=0.44.0"]
build-backend = "setuptools.build_meta"

[project]
name = "ai-parrot-client-hf"
version = "0.1.0"
dependencies = ["ai-parrot", "transformers>=4.48.0,<5.0", "sentence-transformers"]

[project.entry-points."parrot.clients"]
hf = "parrot.clients.hf:TransformersClient"
huggingface = "parrot.clients.hf:TransformersClient"
transformers = "parrot.clients.hf:TransformersClient"

[tool.setuptools.packages.find]
where = ["src"]
include = ["parrot*"]
namespaces = true
```

---

## Acceptance Criteria

- [ ] `packages/ai-parrot-client-hf/` exists with correct PEP 420 structure
- [ ] `pyproject.toml` declares `hf`, `huggingface`, `transformers` entry points
- [ ] `hf.py` moved from core to satellite
- [ ] `from parrot.clients.hf import TransformersClient` works when satellite installed
- [ ] `uv pip install -e packages/ai-parrot-client-hf` succeeds

---

## Completion Note

*(Agent fills this in when done)*
