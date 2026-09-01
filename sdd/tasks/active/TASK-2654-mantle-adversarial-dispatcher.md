# TASK-2654: MantleAdversarialReviewDispatcher + additive catalog entries

**Feature**: FEAT-486 — Refactor Dev-Flow — Per-Seat LLM Configuration, Multi-Agent Development Pool, Configurable Review
**Spec**: `sdd/specs/refactor-dev-flow.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: none
**Assigned-to**: unassigned

---

## Context

Spec §3 Module 4 (goal G5). `gpt-5.6-sol` cannot run over the Codex CLI —
the counter-review seat needs a Bedrock Mantle transport, read-only by
construction, mirroring `NovaAdversarialReviewDispatcher`. Catalog gains
additive rows so the console picker can offer the new defaults.

---

## Scope

- Implement `MantleAdversarialReviewDispatcher` (mirror
  `NovaAdversarialReviewDispatcher`, `dev_loop/dispatchers/nova.py:239-240`):
  `advisory = True`, no tools bound, forces `files_modified=[]` (see
  `CodexAdversarialReviewDispatcher` doing this at `code_review.py:337`),
  model defaults to `"gpt-5.6-sol"` (configurable via constructor arg with
  a `DEV_LOOP_ADVERSARIAL_MODEL`-style conf fallback — new key, do not
  repoint the existing codex one), client = `BedrockMantleClient`. Set a
  sensible `max_tokens` (see per-model ceilings pattern,
  `dev_loop/models/nova.py:51-56`).
- Register it in `CodeReviewDispatcherFactory` (`code_review.py:164-188`)
  and add `"mantle"` to the adversarial backend choices triad
  (`catalog.py:54,:60,:63-91`) — ADDITIVE ONLY (existing `codex`/`nova`
  entries unchanged; `ADVERSARIAL_BACKEND` default stays `"codex"`).
- Additive `catalog.py` model-list entries: `gpt-5.6-sol` reachable via the
  Mantle/adversarial role; `qwen.qwen3-coder-480b-a35b-v1:0` added to the
  `nova` backend's `models` tuple (`catalog.py:235-244`).
- Unit tests: advisory/read-only invariants, factory registration, triad
  resolution, catalog additivity (existing rows byte-identical).

**NOT in scope**: assembling the pair into `ParallelPerspectiveReviewDispatcher`
from the plan (TASK-2655), console picker UI (TASK-2658), judge panel or
`JudgeSpec` (explicitly untouched per spec).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/flows/dev_loop/dispatchers/mantle.py` (or extend `code_review.py` — follow where `NovaAdversarialReviewDispatcher` lives) | CREATE/MODIFY | The dispatcher |
| `packages/ai-parrot/src/parrot/flows/dev_loop/code_review.py` | MODIFY | Factory registration |
| `packages/ai-parrot/src/parrot/flows/dev_loop/catalog.py` | MODIFY | Additive triad + model rows |
| `packages/ai-parrot/src/parrot/conf.py` | MODIFY | New adversarial-model conf key |
| `packages/ai-parrot/tests/flows/dev_loop/test_mantle_adversarial.py` | CREATE | Unit tests |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from parrot.clients.nova import BedrockMantleClient  # clients/nova/__init__.py:9-11
# NOT exported from parrot.clients top-level __init__ — import from parrot.clients.nova
```

### Existing Signatures to Use
```python
# packages/ai-parrot/src/parrot/flows/dev_loop/code_review.py (verified 2026-09-01)
class AbstractCodeReviewDispatcher:      # :85
    advisory: bool = False               # :100
    async def review(...)                # :106
class CodeReviewDispatcherFactory:       # :164 — register (:170), create (:180)
class CodexAdversarialReviewDispatcher:  # :267 — advisory=True (:278), __init__ (:280-294),
                                         #   model default conf.DEV_LOOP_ADVERSARIAL_MODEL (:290),
                                         #   forces files_modified=[] (:337)
# NovaAdversarialReviewDispatcher — dev_loop/dispatchers/nova.py:239-240 (read-only by
#   construction: no tools). THE pattern to mirror.

# packages/ai-parrot/src/parrot/flows/dev_loop/catalog.py
# :54 ADVERSARIAL_BACKEND = "codex"; :60 choices ("codex","nova"); :63-91 resolve_adversarial_backend()
# :98-127 BackendInfo frozen dataclass; :131-253 BACKENDS tuple; :229-244 nova entry (models :235-244)
# :22-24 model lists are advisory free-text, never a whitelist

# packages/ai-parrot/src/parrot/clients/nova/mantle.py
class BedrockMantleClient(OpenAIBaseClient):  # :32
    _default_model = "openai.gpt-oss-120b"    # :86
    def __init__(self, api_key=None, base_url=None, region=None, **kwargs): ...  # :89-95
    # key resolution: api_key → BEDROCK_MANTLE_API_KEY → AWS_NOVA_API_KEY (:96)

# conf.py:947 DEV_LOOP_ADVERSARIAL_MODEL (fallback "gpt-5.5") — precedent for the NEW key
```

### Does NOT Exist
- ~~`MantleAdversarialReviewDispatcher`~~ — created BY this task.
- ~~`gpt-5.6-sol` via the `codex` backend~~ — Codex CLI cannot run it; do NOT extend `catalog.py:154`'s codex models tuple (spec-resolved decision).
- ~~A `BedrockMantleModel` enum~~ — Mantle model ids are raw strings (`docs/clients/bedrock-mantle.md:123,132`).
- ~~`JudgeSpec` widening / judge-panel changes~~ — forbidden by spec (review pair rides `ParallelPerspectiveReviewDispatcher`).
- ~~`gpt-5.6-sol` in `OpenAIModel` wiring~~ — enum member only (`parrot/models/openai.py:22`); the transport here is Mantle, not the OpenAI client.

---

## Implementation Notes

### Key Constraints
- Read `NovaAdversarialReviewDispatcher` and its profile
  (`dev_loop/models/nova.py:130` `NovaAdversarialReviewProfile`, no-tools
  by construction) FIRST and mirror the structure — same file layout, same
  registration idioms.
- Catalog changes must be provably additive: a test should assert the
  pre-existing backend rows and triad defaults are unchanged.
- FEAT-479: the dispatcher must run its client call under
  `usage_attribution` like its siblings — check how `dispatchers/nova.py`
  binds the per-run registry and copy it.
- Bearer-key auth failure (missing `AWS_NOVA_API_KEY`) must surface as a
  clean review-degradation, not a crash — match sibling error handling.

### References in Codebase
- `dev_loop/dispatchers/nova.py` — the whole file is the template
- `dev_loop/models/nova.py:51-56` — max-token ceilings pattern

---

## Acceptance Criteria

- [ ] Dispatcher is advisory/read-only: `advisory=True`, no tools, `files_modified=[]` forced (test-asserted)
- [ ] Factory `create("mantle", ...)` returns it; triad resolves `"mantle"`; default stays `"codex"`
- [ ] Catalog additions are additive (existing rows unchanged, test-asserted)
- [ ] All tests pass: `pytest packages/ai-parrot/tests/flows/dev_loop/test_mantle_adversarial.py -v`; `ruff check` clean

---

## Test Specification

```python
# packages/ai-parrot/tests/flows/dev_loop/test_mantle_adversarial.py
import pytest

class TestMantleAdversarial:
    def test_advisory_and_read_only(self): ...
    def test_files_modified_forced_empty(self): ...
    def test_default_model_gpt_5_6_sol(self): ...
    def test_factory_registration_and_triad(self): ...
    def test_catalog_additive(self): ...
```

---

## Agent Instructions

1. **Read the spec**; 2. **Check dependencies** — none
3. **Verify the Codebase Contract** first (read `dispatchers/nova.py` end-to-end before writing)
4. **Update status** in `sdd/tasks/index/refactor-dev-flow.json` → `"in-progress"`
5. **Implement**; 6. **Verify**; 7. **Move this file** to `sdd/tasks/completed/`;
8. **Update index** → `"done"`; 9. **Fill in the Completion Note**

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**:
**Date**:
**Notes**:

**Deviations from spec**: none
