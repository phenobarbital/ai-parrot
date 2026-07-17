# TASK-1810: Model catalog entries + 'nova' factory registration

**Feature**: FEAT-315 — Unified NovaClient for all Amazon Nova models
**Spec**: `sdd/specs/novaclient-amazon-aws.spec.md`
**Status**: pending
**Priority**: medium
**Estimated effort**: S (< 2h)
**Depends-on**: TASK-1809
**Assigned-to**: unassigned

---

## Context

Implements spec §3 Module 5. Two small, bounded edits: extend the
public→Bedrock model-ID map with the missing Nova entries (IDs verified
against AWS model cards 2026-07-17, spec §6 "Verified AWS Facts"), and
register the `'nova'` provider key in `LLMFactory` via the established
lazy-loader pattern. `NovaSonicClient` was never factory-registered — this
ADDS a key, it does not migrate one.

---

## Scope

- `packages/ai-parrot/src/parrot/models/bedrock_models.py` — add to
  `PUBLIC_TO_BEDROCK` (keep the existing Nova section grouping/comments):
  - `"nova-premier": "amazon.nova-premier-v1:0"`
  - `"nova-canvas":  "amazon.nova-canvas-v1:0"`
  - `"nova-reel":    "amazon.nova-reel-v1:0"`
- `packages/ai-parrot/src/parrot/clients/factory.py`:
  - Add `_lazy_nova()` loader (docstring pattern of `_lazy_bedrock_converse`,
    line 21-34) returning `NovaClient` from `parrot.clients.nova`.
  - Add `"nova": _lazy_nova` to `SUPPORTED_CLIENTS`.
- Unit tests for the new map entries (incl. `region_prefix` interaction) and
  factory creation.

**NOT in scope**: `'nova_sonic'` voice-provider key rename (TASK-1811),
Nova 2 Pro/Micro/Premier (they DO NOT exist on Bedrock — spec §6).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/models/bedrock_models.py` | MODIFY | 3 new map entries |
| `packages/ai-parrot/src/parrot/clients/factory.py` | MODIFY | `_lazy_nova` + `"nova"` key |
| `packages/ai-parrot/tests/models/test_bedrock_models.py` | MODIFY | new-entry tests |
| `packages/ai-parrot/tests/clients/test_factory_nova.py` | CREATE | factory tests |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from parrot.models.bedrock_models import translate, PUBLIC_TO_BEDROCK  # models/bedrock_models.py:38,100
from parrot.clients.factory import LLMFactory, SUPPORTED_CLIENTS       # clients/factory.py:65,106
from parrot.clients.nova import NovaClient                              # created by TASK-1809
```

### Existing Signatures to Use
```python
# packages/ai-parrot/src/parrot/models/bedrock_models.py
PUBLIC_TO_BEDROCK: dict[str, str]        # line 38; current Nova entries at 67-75:
#   nova-sonic, nova-pro, nova-lite, nova-micro (v1 gen); nova-2-sonic, nova-2-lite
def translate(public_id: str, region_prefix: str | None = None) -> str:  # line 100
#   pass-through when "amazon." in id (line 92); region_prefix prepends "<p>." (140-142)

# packages/ai-parrot/src/parrot/clients/factory.py
def _lazy_bedrock_converse():            # line 21 — docstring + return-class pattern to copy
SUPPORTED_CLIENTS = { ... }              # lines 65-94; "bedrock-converse": _lazy_bedrock_converse at 74
class LLMFactory:                        # line 106
    @staticmethod
    def create(llm: str, model_args=None, tool_manager=None, **kwargs) -> AbstractClient:  # line 138
    # lazy loaders resolved at lines 186-188:
    # if callable(client_class) and not isinstance(client_class, type): client_class = client_class()
```

### Does NOT Exist
- ~~`nova-2-pro` / `nova-2-micro` / `nova-2-premier` / `nova-2-omni`~~ — NOT on
  Bedrock (July 2026); do NOT add speculative entries.
- ~~`amazon.nova-reel-v1:1`~~ — model card lists `v1:0`.
- ~~`us.amazon.nova-canvas-v1:0` / geo IDs for Canvas & Reel~~ — Canvas/Reel are
  in-region only (no inference profiles); the base IDs are the only valid ones.
- ~~`SUPPORTED_CLIENTS["nova-sonic"]`~~ — never existed; do not add.
- ~~`PROVIDER_BACKEND["nova"]`~~ — the backend-injection map (factory.py:100) is
  FEAT-232/Anthropic-specific; `nova` must NOT be added there.

---

## Implementation Notes

### Pattern to Follow
`_lazy_bedrock_converse` (factory.py:21-34): module-level function, Google-style
docstring explaining why lazy, returns the class.

### Key Constraints
- Keep the map's comment structure (── Amazon Nova ── / ── Amazon Nova 2 ──
  sections, lines 67-75).
- Note in a comment that Premier is geo-only (`us.` prefix needed at call
  time via `region_prefix`) and that Canvas/Reel are in-region only — the map
  stores BASE IDs; prefixing stays the caller's `region_prefix` concern.
- `LLMFactory.create("nova:nova-micro")` must set `model="nova-micro"` via
  the existing init-params path (factory.py:194-195) — no special-casing.

### References in Codebase
- `packages/ai-parrot/tests/models/test_bedrock_models.py` — existing map tests to extend
- `packages/ai-parrot/tests/clients/test_factory_bedrock.py` — factory-test precedent

---

## Acceptance Criteria

- [ ] `translate("nova-premier") == "amazon.nova-premier-v1:0"`; same for canvas/reel
- [ ] `translate("nova-premier", region_prefix="us") == "us.amazon.nova-premier-v1:0"`
- [ ] `LLMFactory.create("nova")` returns a `NovaClient` (default model resolves to `us.amazon.nova-2-lite-v1:0`)
- [ ] `LLMFactory.create("nova:nova-micro")` sets `model == "nova-micro"`
- [ ] `pytest packages/ai-parrot/tests/models/test_bedrock_models.py packages/ai-parrot/tests/clients/test_factory_nova.py -v` passes
- [ ] `ruff check` clean on both modified files

---

## Test Specification

```python
# packages/ai-parrot/tests/clients/test_factory_nova.py
from parrot.clients.factory import LLMFactory, SUPPORTED_CLIENTS
from parrot.clients.nova import NovaClient


def test_nova_key_registered_lazy():
    assert "nova" in SUPPORTED_CLIENTS
    assert callable(SUPPORTED_CLIENTS["nova"])

def test_create_default():
    client = LLMFactory.create("nova")
    assert isinstance(client, NovaClient)

def test_create_with_model():
    client = LLMFactory.create("nova:nova-micro")
    assert client.model == "nova-micro"
```

---

## Agent Instructions

1. **Read the spec** at `sdd/specs/novaclient-amazon-aws.spec.md` (§3 Module 5, §6 Verified AWS Facts)
2. **Check dependencies** — TASK-1809 in `sdd/tasks/completed/`
3. **Verify the Codebase Contract** before writing any code
4. **Update status** in `sdd/tasks/index/novaclient-amazon-aws.json` → `"in-progress"`
5. **Implement**, **verify**, move this file to `sdd/tasks/completed/`, update index → `"done"`, fill the Completion Note

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**:
**Date**:
**Notes**:

**Deviations from spec**: none
