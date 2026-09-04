# TASK-2804: Satellite Package — ai-parrot-client-local

**Feature**: FEAT-523 — PEP 420 LLM Client Extraction
**Spec**: `sdd/specs/pep-420-llm-clients.spec.md`
**Status**: pending
**Priority**: medium
**Estimated effort**: S (< 2h)
**Depends-on**: TASK-2795
**Assigned-to**: unassigned

---

## Context

Extract `LocalLLMClient` and `vLLMClient` from core into the
`ai-parrot-client-local` satellite package. Part of spec Module 6
(standalone providers). Two-file satellite with no new SDK dependency
(both use OpenAI-compatible API via `OpenAIBaseClient`).

---

## Scope

- Create `packages/ai-parrot-client-local/` with PEP 420 structure:
  ```
  packages/ai-parrot-client-local/
  ├── pyproject.toml
  └── src/
      └── parrot/          # .gitkeep only (NO __init__.py)
          └── clients/     # .gitkeep only (NO __init__.py)
              ├── localllm.py
              └── vllm.py
  ```
- Move `packages/ai-parrot/src/parrot/clients/localllm.py` → satellite
- Move `packages/ai-parrot/src/parrot/clients/vllm.py` → satellite
- Create `pyproject.toml` with entry points and dependencies
- Delete the original files from core

**NOT in scope**: factory.py changes (TASK-2795), pyproject.toml extras (TASK-2806), tests (TASK-2807).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot-client-local/pyproject.toml` | CREATE | Package metadata |
| `packages/ai-parrot-client-local/src/parrot/.gitkeep` | CREATE | PEP 420 |
| `packages/ai-parrot-client-local/src/parrot/clients/.gitkeep` | CREATE | PEP 420 |
| `packages/ai-parrot-client-local/src/parrot/clients/localllm.py` | CREATE (move) | LocalLLMClient |
| `packages/ai-parrot-client-local/src/parrot/clients/vllm.py` | CREATE (move) | vLLMClient |
| `packages/ai-parrot/src/parrot/clients/localllm.py` | DELETE | Moved to satellite |
| `packages/ai-parrot/src/parrot/clients/vllm.py` | DELETE | Moved to satellite |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from parrot.clients.openai_base import OpenAIBaseClient  # clients/openai_base.py:59
```

### Does NOT Exist
- ~~`parrot.clients.ollama`~~ — there is no `ollama.py` module; Ollama support is handled by `LocalLLMClient` in `localllm.py` via OpenAI-compatible API

---

## Implementation Notes

### pyproject.toml
```toml
[build-system]
requires = ["setuptools>=77.0.0", "wheel>=0.44.0"]
build-backend = "setuptools.build_meta"

[project]
name = "ai-parrot-client-local"
version = "0.1.0"
dependencies = ["ai-parrot"]

[project.entry-points."parrot.clients"]
localllm = "parrot.clients.localllm:LocalLLMClient"
vllm = "parrot.clients.vllm:vLLMClient"

[tool.setuptools.packages.find]
where = ["src"]
include = ["parrot*"]
namespaces = true
```

### Key Constraints
- No extra SDK dependency — both clients use OpenAI-compatible endpoints
  through `OpenAIBaseClient` which stays in core

---

## Acceptance Criteria

- [ ] `packages/ai-parrot-client-local/` exists with correct PEP 420 structure
- [ ] `pyproject.toml` declares `localllm` and `vllm` entry points
- [ ] Both files moved from core to satellite
- [ ] `from parrot.clients.localllm import LocalLLMClient` works when satellite installed
- [ ] `from parrot.clients.vllm import vLLMClient` works when satellite installed
- [ ] `uv pip install -e packages/ai-parrot-client-local` succeeds

---

## Completion Note

*(Agent fills this in when done)*
