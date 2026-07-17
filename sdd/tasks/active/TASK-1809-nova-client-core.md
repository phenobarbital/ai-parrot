# TASK-1809: NovaClient core — compose base + mixins in nova/client.py

**Feature**: FEAT-315 — Unified NovaClient for all Amazon Nova models
**Spec**: `sdd/specs/novaclient-amazon-aws.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-1806, TASK-1807, TASK-1808
**Assigned-to**: unassigned

---

## Context

Implements spec §3 Module 2 — the unification point of the feature. One class,
`NovaClient(BedrockConverseBase, NovaAudio, NovaGeneration)`, mirrors
`GoogleGenAIClient(AbstractClient, GoogleGeneration, GoogleAnalysis)`
(`clients/google/client.py`). Text methods are INHERITED from the Converse
base (resolved U1: no delegation object); voice and generation come from the
mixins (TASK-1807/1808).

---

## Scope

- Create `nova/client.py`:
  ```python
  class NovaClient(BedrockConverseBase, NovaAudio, NovaGeneration):
      client_type: str = "nova"
      client_name: str = "nova"
      _default_model: str = "nova-2-lite"
  ```
  - `__init__(self, aws_id=None, region=None, profile=None,
    region_prefix="us", guardrail_id=None, guardrail_version=None,
    voice_id="matthew", aws_access_key=None, aws_secret_key=None,
    aws_session_token=None, **kwargs)` — store `voice_id`, then call
    `super().__init__(...)` forwarding everything else to
    `BedrockConverseBase`. `region_prefix` DEFAULTS to `"us"` (spec §2:
    Nova 2 Lite / Premier are geo-inference-only).
  - Set an appropriate `_fallback_model` (e.g. `"nova-lite"`) or explicitly
    inherit; preserve the `kwargs.setdefault('fallback_model', ...)` behavior
    from the base.
- Finalize `nova/__init__.py` mirroring `google/__init__.py:1-6`:
  ```python
  from .client import NovaClient
  __all__ = ["NovaClient"]
  ```
- Unit tests: MRO/defaults, inherited-not-delegated text path, model
  translation with the `"us"` prefix.

**NOT in scope**: factory key + model-map entries (TASK-1810), call-site
migration (TASK-1811).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/clients/nova/client.py` | CREATE | `NovaClient` composition |
| `packages/ai-parrot/src/parrot/clients/nova/__init__.py` | MODIFY | final exports |
| `packages/ai-parrot/tests/clients/test_nova_client.py` | CREATE | MRO/defaults/inheritance tests |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from parrot.clients.bedrock import BedrockConverseBase   # created by TASK-1806
from parrot.clients.nova.audio import NovaAudio          # created by TASK-1807
from parrot.clients.nova.generation import NovaGeneration  # created by TASK-1808
```

### Existing Signatures to Use
```python
# packages/ai-parrot/src/parrot/clients/bedrock.py (post TASK-1806):
class BedrockConverseBase(AbstractClient):
    def __init__(self, aws_id=None, region=None, profile=None, region_prefix=None,
        guardrail_id=None, guardrail_version=None, max_retries: int = 4,
        read_timeout: int = 120, aws_access_key=None, aws_secret_key=None,
        aws_session_token=None, **kwargs): ...
    # concrete: get_client, ask (was line 494), ask_stream (780), resume (916),
    # invoke (1046), _translate_model (179), apply_guardrail_text (400)

# packages/ai-parrot/src/parrot/clients/google/client.py — composition precedent:
class GoogleGenAIClient(AbstractClient, GoogleGeneration, GoogleAnalysis):  # line 95
# packages/ai-parrot/src/parrot/clients/google/__init__.py:1-6 — export pattern:
#   from .client import GoogleGenAIClient
#   GoogleClient = GoogleGenAIClient
#   __all__ = ["GoogleGenAIClient", "GoogleClient", "GoogleModel"]

# packages/ai-parrot/src/parrot/models/bedrock_models.py:
translate(public_id: str, region_prefix: str | None = None) -> str   # line 100
# "nova-2-lite" → "amazon.nova-2-lite-v1:0" (line 75); with region_prefix="us"
# → "us.amazon.nova-2-lite-v1:0" (lines 140-142)
```

### Does NOT Exist
- ~~`NovaSonicClient` reuse~~ — NovaClient does NOT subclass or wrap it.
- ~~an internal text-delegate client (`_get_text_client`, `_text_client`)~~ —
  must not exist on NovaClient (acceptance criterion).
- ~~`GoogleModel`-equivalent `NovaModel`~~ — no such model class is required;
  do not invent one.
- ~~`SUPPORTED_CLIENTS["nova"]`~~ — added in TASK-1810, not here.
- MRO gotcha (spec §7): `AbstractClient.__init__` unconditionally sets
  `self._fallback_model = kwargs.get('fallback_model', None)` — keep the
  base's `kwargs.setdefault` workaround intact through the super() chain.

---

## Implementation Notes

### Pattern to Follow
`GoogleGenAIClient` class declaration + `google/__init__.py` exports. Mixins
carry no `__init__`; `NovaClient.__init__` only adds `voice_id` and the
`region_prefix="us"` default before delegating to the base.

### Key Constraints
- `NovaClient` must satisfy the `AbstractClient` ABC purely via inheritance —
  no method stubs, no `NotImplementedError` overrides for text methods.
- `NovaClient(region_prefix=None)` must be possible (explicit opt-out for
  in-region custom deployments) — only the DEFAULT is `"us"`.
- Docstring: document the modalities, the default model, the `aws_id`
  credential story, and the EU/JP `region_prefix` override (spec §7 gotcha).

### References in Codebase
- `packages/ai-parrot/src/parrot/clients/google/client.py:95` — composition
- `packages/ai-parrot/src/parrot/clients/google/__init__.py` — exports

---

## Acceptance Criteria

- [ ] `from parrot.clients.nova import NovaClient` works
- [ ] `NovaClient.__mro__` = NovaClient → BedrockConverseBase → AbstractClient path with NovaAudio/NovaGeneration mixed in; class is instantiable (ABC satisfied)
- [ ] `client_type == "nova"`; `NovaClient()._translate_model(None) == "us.amazon.nova-2-lite-v1:0"`
- [ ] No `_text_client`/`_get_text_client` attribute exists; `ask` resolves to the base implementation (`NovaClient.ask is BedrockConverseBase.ask`)
- [ ] `stream_voice`, `generate_image`, `video_generation` are present on instances
- [ ] `pytest packages/ai-parrot/tests/clients/test_nova_client.py -v` passes
- [ ] `ruff check packages/ai-parrot/src/parrot/clients/nova/` clean

---

## Test Specification

```python
# packages/ai-parrot/tests/clients/test_nova_client.py
from parrot.clients.bedrock import BedrockConverseBase
from parrot.clients.nova import NovaClient


class TestNovaClientComposition:
    def test_defaults(self):
        c = NovaClient()
        assert c.client_type == "nova"
        assert c._translate_model(None) == "us.amazon.nova-2-lite-v1:0"

    def test_region_prefix_opt_out(self):
        c = NovaClient(region_prefix=None)
        assert c._translate_model(None) == "amazon.nova-2-lite-v1:0"

    def test_text_methods_inherited_not_delegated(self):
        assert NovaClient.ask is BedrockConverseBase.ask
        assert not hasattr(NovaClient(), "_text_client")

    def test_capabilities_present(self):
        c = NovaClient()
        for m in ("stream_voice", "generate_image", "video_generation"):
            assert callable(getattr(c, m))

    def test_voice_id_stored(self):
        assert NovaClient(voice_id="tiffany").voice_id == "tiffany"
```

---

## Agent Instructions

1. **Read the spec** at `sdd/specs/novaclient-amazon-aws.spec.md` (§2, §3 Module 2, §6, §7)
2. **Check dependencies** — TASK-1806, TASK-1807, TASK-1808 in `sdd/tasks/completed/`
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
