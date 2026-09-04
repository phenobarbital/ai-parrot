# TASK-2798: Satellite Package — ai-parrot-client-google

**Feature**: FEAT-523 — PEP 420 LLM Client Extraction
**Spec**: `sdd/specs/pep-420-llm-clients.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: L (4-8h)
**Depends-on**: TASK-2795
**Assigned-to**: unassigned

---

## Context

Extract the Google client family from core into the `ai-parrot-client-google`
satellite package. This is the largest satellite (~16,000 lines, 466 KB of
source). Implements spec Module 4. Includes the `google/` subpackage,
`Gemma4Client`, and `GeminiLiveClient` (WebSocket-based voice — ships with
Google family since it depends on `google-genai`).

---

## Scope

- Create package directory structure at `packages/ai-parrot-client-google/`:
  ```
  packages/ai-parrot-client-google/
  ├── pyproject.toml
  └── src/
      └── parrot/              # NO __init__.py (PEP 420)
          └── clients/         # NO __init__.py (PEP 420)
              ├── google/      # HAS __init__.py (real subpackage)
              │   ├── __init__.py
              │   ├── client.py
              │   ├── analysis.py
              │   └── generation.py
              ├── gemma4.py
              └── live.py
  ```
- Move the following from `packages/ai-parrot/src/parrot/clients/` → satellite:
  - `google/` subpackage (entire directory: `__init__.py`, `client.py`,
    `analysis.py`, `generation.py`)
  - `gemma4.py` (`Gemma4Client`)
  - `live.py` (`GeminiLiveClient`)
- Create `pyproject.toml` with:
  - `name = "ai-parrot-client-google"`, `version = "0.1.0"`
  - `dependencies = ["ai-parrot", "google-genai>=2.18.1", "google-api-python-client", "google-cloud-texttospeech"]`
  - Entry points: `google`, `gemma4`, `gemini-live`
  - `namespaces = true` in setuptools config
- Place `.gitkeep` files at `src/parrot/` and `src/parrot/clients/` (no `__init__.py`)
- The `google/` subpackage retains its own `__init__.py` — it is a real
  package, not a namespace level
- Verify imports still work via namespace merging

**NOT in scope**: modifying `factory.py` (done in TASK-2795), updating core
`pyproject.toml` extras (TASK-2806), tests (TASK-2807).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot-client-google/pyproject.toml` | CREATE | Package metadata, deps, entry points |
| `packages/ai-parrot-client-google/src/parrot/.gitkeep` | CREATE | PEP 420 namespace marker |
| `packages/ai-parrot-client-google/src/parrot/clients/.gitkeep` | CREATE | PEP 420 namespace marker |
| `packages/ai-parrot-client-google/src/parrot/clients/google/__init__.py` | CREATE (move) | GoogleGenAIClient re-export |
| `packages/ai-parrot-client-google/src/parrot/clients/google/client.py` | CREATE (move) | GoogleGenAIClient implementation |
| `packages/ai-parrot-client-google/src/parrot/clients/google/analysis.py` | CREATE (move) | GoogleAnalysis mixin |
| `packages/ai-parrot-client-google/src/parrot/clients/google/generation.py` | CREATE (move) | GoogleGeneration mixin |
| `packages/ai-parrot-client-google/src/parrot/clients/gemma4.py` | CREATE (move) | Gemma4Client |
| `packages/ai-parrot-client-google/src/parrot/clients/live.py` | CREATE (move) | GeminiLiveClient |
| `packages/ai-parrot/src/parrot/clients/google/` | DELETE | Entire directory moved to satellite |
| `packages/ai-parrot/src/parrot/clients/gemma4.py` | DELETE | Moved to satellite |
| `packages/ai-parrot/src/parrot/clients/live.py` | DELETE | Moved to satellite |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
# These imports come FROM the files being moved:
from parrot.clients.base import AbstractClient          # clients/base.py:230
from parrot.clients.openai_base import OpenAIBaseClient  # clients/openai_base.py:59

# This is the main class being moved:
from parrot.clients.google import GoogleGenAIClient  # clients/google/__init__.py
# Which re-exports from:
from parrot.clients.google.client import GoogleGenAIClient  # clients/google/client.py:95
```

### Existing Signatures to Use
```python
# parrot/clients/google/client.py:95 — being moved
class GoogleGenAIClient(AbstractClient):
    # Large client (~278 KB source): analysis mixin + generation mixin

# parrot/clients/google/__init__.py (177B) — being moved
# Exports GoogleGenAIClient

# parrot/clients/base.py:230 — stays in core
class AbstractClient(EventEmitterMixin, ABC):
    client_type: str = "generic"      # line 237
    client_name: str = "generic"      # line 238
```

### Does NOT Exist
- ~~`parrot.clients.vertex`~~ — no standalone Vertex AI client; Vertex support is handled through `GoogleGenAIClient` (the `google-genai` SDK supports both AI Studio and Vertex natively)
- ~~`parrot.clients.gemini`~~ — the directory is named `google/`, not `gemini/`
- ~~`parrot/clients/google/vertex.py`~~ — Vertex routing is internal to `GoogleGenAIClient`

---

## Implementation Notes

### Pattern to Follow
```toml
# pyproject.toml — follow ai-parrot-embeddings pattern
[build-system]
requires = ["setuptools>=77.0.0", "wheel>=0.44.0"]
build-backend = "setuptools.build_meta"

[project]
name = "ai-parrot-client-google"
version = "0.1.0"
dependencies = [
    "ai-parrot",
    "google-genai>=2.18.1",
    "google-api-python-client",
    "google-cloud-texttospeech",
]

[project.entry-points."parrot.clients"]
google = "parrot.clients.google:GoogleGenAIClient"
gemma4 = "parrot.clients.gemma4:Gemma4Client"
gemini-live = "parrot.clients.live:GeminiLiveClient"

[tool.setuptools.packages.find]
where = ["src"]
include = ["parrot*"]
namespaces = true
```

### Key Constraints
- NO `__init__.py` at `src/parrot/` or `src/parrot/clients/` — PEP 420 namespace merging
- The `google/` directory itself IS a real subpackage with its own `__init__.py` — only the
  namespace junction levels lack `__init__.py`
- All imports from `AbstractClient` must reference core (stays in core)
- The moved files must not change their internal import paths for core dependencies
- Entry-point keys must match what was in `SUPPORTED_CLIENTS`
- This is the largest satellite — verify the full `google/` subpackage moves cleanly
  including all internal cross-imports between `client.py`, `analysis.py`, and `generation.py`

### References in Codebase
- `packages/ai-parrot-embeddings/pyproject.toml` — reference satellite pyproject.toml
- `packages/ai-parrot-embeddings/src/parrot/` — reference PEP 420 directory structure
- `packages/ai-parrot/src/parrot/clients/google/` — source directory to move

---

## Acceptance Criteria

- [ ] `packages/ai-parrot-client-google/` exists with correct structure
- [ ] `pyproject.toml` declares entry points for `google`, `gemma4`, `gemini-live`
- [ ] Source files moved from core to satellite (entire `google/` dir, `gemma4.py`, `live.py`)
- [ ] Original files deleted from core
- [ ] `from parrot.clients.google import GoogleGenAIClient` works when satellite installed
- [ ] `from parrot.clients.gemma4 import Gemma4Client` works when satellite installed
- [ ] `from parrot.clients.live import GeminiLiveClient` works when satellite installed
- [ ] No `__init__.py` at namespace levels (PEP 420)
- [ ] `google/` subpackage retains its `__init__.py`
- [ ] `uv pip install -e packages/ai-parrot-client-google` succeeds
- [ ] Internal cross-imports within `google/` subpackage still work

---

## Test Specification

```python
# Verified manually:
# uv pip install -e packages/ai-parrot-client-google
# python -c "from parrot.clients.google import GoogleGenAIClient; print(GoogleGenAIClient)"
# python -c "from parrot.clients.gemma4 import Gemma4Client; print(Gemma4Client)"
# python -c "from parrot.clients.live import GeminiLiveClient; print(GeminiLiveClient)"
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at `sdd/specs/pep-420-llm-clients.spec.md` for full context
2. **Check dependencies** — verify TASK-2795 is completed
3. **Verify the Codebase Contract** — confirm source files still exist at listed paths
4. **Update status** in `sdd/tasks/index/pep-420-llm-clients.json` → `"in-progress"`
5. **Implement** following the scope and notes above
6. **Verify** all acceptance criteria are met
7. **Move this file** to `sdd/tasks/completed/TASK-2798-satellite-google.md`
8. **Update index** → `"done"`
9. **Fill in the Completion Note** below

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**: <session or agent ID>
**Date**: YYYY-MM-DD
**Notes**: What was implemented, any deviations from scope, issues encountered.

**Deviations from spec**: none | describe if any
