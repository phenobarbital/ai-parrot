# TASK-2799: Satellite Package — ai-parrot-client-amazon

**Feature**: FEAT-523 — PEP 420 LLM Client Extraction
**Spec**: `sdd/specs/pep-420-llm-clients.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-2795
**Assigned-to**: unassigned

---

## Context

Extract the Amazon/AWS client family from core into the
`ai-parrot-client-amazon` satellite package. Implements spec Module 5. After
TASK-2795 lands the factory refactor, this task moves the Bedrock and Nova
client files and sets up the PEP 420 package structure with entry-point
declarations.

---

## Scope

- Create package directory structure at `packages/ai-parrot-client-amazon/`:
  ```
  packages/ai-parrot-client-amazon/
  ├── pyproject.toml
  └── src/
      └── parrot/             # NO __init__.py (PEP 420)
          └── clients/        # NO __init__.py (PEP 420)
              ├── bedrock.py
              └── nova/
                  ├── __init__.py   (351B — keeps its own __init__)
                  ├── audio.py      (61.6K)
                  ├── client.py     (8.5K)
                  ├── generation.py (15.4K)
                  └── mantle.py     (5.6K — BedrockMantleClient)
  ```
- Move `packages/ai-parrot/src/parrot/clients/bedrock.py` → satellite
- Move `packages/ai-parrot/src/parrot/clients/nova/` (entire subpackage) → satellite
- Create `pyproject.toml` with:
  - `name = "ai-parrot-client-amazon"`, `version = "0.1.0"`
  - `dependencies = ["ai-parrot", "aioboto3>=13.2.0", "anthropic[aiohttp,aws]"]`
  - Entry points: `bedrock-converse`, `nova`, `bedrock-mantle`, `mantle`
  - `namespaces = true` in setuptools config
- Place `.gitkeep` files at `src/parrot/` and `src/parrot/clients/` (no `__init__.py`)
- The `nova/` subpackage KEEPS its own `__init__.py` — it is a concrete package, not a namespace level
- Verify imports still work via namespace merging

**NOT in scope**: modifying `factory.py` (done in TASK-2795), updating core
`pyproject.toml` extras (TASK-2806), tests (TASK-2807).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot-client-amazon/pyproject.toml` | CREATE | Package metadata, deps, entry points |
| `packages/ai-parrot-client-amazon/src/parrot/.gitkeep` | CREATE | PEP 420 namespace marker |
| `packages/ai-parrot-client-amazon/src/parrot/clients/.gitkeep` | CREATE | PEP 420 namespace marker |
| `packages/ai-parrot-client-amazon/src/parrot/clients/bedrock.py` | CREATE (move) | BedrockConverseClient |
| `packages/ai-parrot-client-amazon/src/parrot/clients/nova/__init__.py` | CREATE (move) | Nova package init |
| `packages/ai-parrot-client-amazon/src/parrot/clients/nova/audio.py` | CREATE (move) | Nova audio client |
| `packages/ai-parrot-client-amazon/src/parrot/clients/nova/client.py` | CREATE (move) | Nova client |
| `packages/ai-parrot-client-amazon/src/parrot/clients/nova/generation.py` | CREATE (move) | Nova generation |
| `packages/ai-parrot-client-amazon/src/parrot/clients/nova/mantle.py` | CREATE (move) | BedrockMantleClient |
| `packages/ai-parrot/src/parrot/clients/bedrock.py` | DELETE | Moved to satellite |
| `packages/ai-parrot/src/parrot/clients/nova/` | DELETE | Entire subpackage moved to satellite |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
# These imports come FROM the files being moved:
from parrot.clients.base import AbstractClient          # clients/base.py:230
from parrot.clients.openai_base import OpenAIBaseClient  # clients/openai_base.py:59

# Classes being moved:
from parrot.clients.bedrock import BedrockConverseClient  # clients/bedrock.py:1647
from parrot.clients.nova.mantle import BedrockMantleClient  # clients/nova/mantle.py
```

### Existing Signatures to Use
```python
# parrot/clients/bedrock.py:1647 — being moved
class BedrockConverseClient(AbstractClient):
    # Uses aioboto3 for AWS API calls
    # Uses anthropic[aws] transport for Bedrock Anthropic models

# parrot/clients/nova/mantle.py — being moved
class BedrockMantleClient(OpenAIBaseClient):
    # Inherits from OpenAIBaseClient which stays in core

# parrot/clients/openai_base.py:59 — stays in core
class OpenAIBaseClient(AbstractClient):
    # Shared base for OpenAI-compatible clients (including BedrockMantleClient)
```

### Does NOT Exist
- ~~`parrot.clients.aws`~~ — no `aws.py` module; AWS/Bedrock is in `bedrock.py`
- ~~`parrot.clients.nova.nova_client`~~ — the Nova client file is `client.py`, not `nova_client.py`
- ~~`BedrockClient`~~ — the class is `BedrockConverseClient`, not `BedrockClient`

---

## Implementation Notes

### Pattern to Follow
```toml
# pyproject.toml — follow ai-parrot-embeddings pattern
[build-system]
requires = ["setuptools>=77.0.0", "wheel>=0.44.0"]
build-backend = "setuptools.build_meta"

[project]
name = "ai-parrot-client-amazon"
version = "0.1.0"
dependencies = [
    "ai-parrot",
    "aioboto3>=13.2.0",
    "anthropic[aiohttp,aws]",
]

[project.entry-points."parrot.clients"]
bedrock-converse = "parrot.clients.bedrock:BedrockConverseClient"
nova = "parrot.clients.nova:NovaClient"
bedrock-mantle = "parrot.clients.nova.mantle:BedrockMantleClient"
mantle = "parrot.clients.nova.mantle:BedrockMantleClient"

[tool.setuptools.packages.find]
where = ["src"]
include = ["parrot*"]
namespaces = true
```

### Key Constraints
- NO `__init__.py` at `src/parrot/` or `src/parrot/clients/` — PEP 420 namespace merging
- The `nova/` subpackage KEEPS its existing `__init__.py` — it is a concrete sub-package within the namespace
- **CRITICAL**: `anthropic[aiohttp,aws]` MUST be declared in this package's own dependencies. `BedrockConverseClient` uses the Anthropic SDK's AWS transport internally (for Bedrock-hosted Anthropic models). This dependency is independent of `ai-parrot-client-anthropic` — both packages need it separately.
- All imports from `AbstractClient` and `OpenAIBaseClient` must reference core (these stay in core)
- The moved files must not change their internal import paths for core dependencies
- Entry-point keys must match what was in `SUPPORTED_CLIENTS`

### References in Codebase
- `packages/ai-parrot-embeddings/pyproject.toml` — reference satellite pyproject.toml
- `packages/ai-parrot-embeddings/src/parrot/` — reference PEP 420 directory structure

---

## Acceptance Criteria

- [ ] `packages/ai-parrot-client-amazon/` exists with correct structure
- [ ] `pyproject.toml` declares entry points for `bedrock-converse`, `nova`, `bedrock-mantle`, `mantle`
- [ ] `pyproject.toml` declares `anthropic[aiohttp,aws]` in its own dependencies
- [ ] Source files moved from core to satellite (bedrock.py + nova/ subpackage)
- [ ] `from parrot.clients.bedrock import BedrockConverseClient` works when satellite installed
- [ ] `from parrot.clients.nova.mantle import BedrockMantleClient` works when satellite installed
- [ ] No `__init__.py` at namespace levels (`src/parrot/`, `src/parrot/clients/`)
- [ ] `nova/` retains its own `__init__.py`
- [ ] `uv pip install -e packages/ai-parrot-client-amazon` succeeds

---

## Test Specification

```python
# Verified manually:
# uv pip install -e packages/ai-parrot-client-amazon
# python -c "from parrot.clients.bedrock import BedrockConverseClient; print(BedrockConverseClient)"
# python -c "from parrot.clients.nova.mantle import BedrockMantleClient; print(BedrockMantleClient)"
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
7. **Move this file** to `sdd/tasks/completed/TASK-2799-satellite-amazon.md`
8. **Update index** → `"done"`
9. **Fill in the Completion Note** below

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**: <session or agent ID>
**Date**: YYYY-MM-DD
**Notes**: What was implemented, any deviations from scope, issues encountered.

**Deviations from spec**: none | describe if any
