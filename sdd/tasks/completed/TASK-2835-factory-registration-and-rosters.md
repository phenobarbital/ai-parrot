# TASK-2835: Factory registration + wire-subclass test rosters

**Feature**: FEAT-526 — Meta Model API (Muse Spark) LLM Client
**Spec**: `sdd/specs/meta-llm-client.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: S (< 2h)
**Depends-on**: TASK-2834
**Assigned-to**: unassigned

---

## Context

Implements **Module 4**. Makes `MetaClient` reachable through
`LLMFactory.create("meta:muse-spark-1.3")` and enrols it in the two existing
parametrized test sweeps that guard every OpenAI-wire subclass against
`gpt-*` default leakage and funnel divergence.

Step 2 of the seven-step recipe in `docs/clients/openai-compatible.md`.

---

## Scope

- Add `from .meta import MetaClient` to `factory.py` imports (resolves to the
  `clients/meta/` **package** init — unchanged syntax, new layout).
- Register `"meta"` plus aliases `"muse"` and `"meta-muse"` in `SUPPORTED_CLIENTS`.
- Add `MetaClient` to `WIRE_SUBCLASSES` in **both** roster files.
- Add a factory-resolution test.

**NOT in scope**: any change to `MetaClient` itself, the Responses path, docs,
or `PROVIDER_BACKEND` (that is an Anthropic-backend mechanism, irrelevant here).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/clients/factory.py` | MODIFY | import + 3 registry keys |
| `tests/clients/test_openai_compatible_defaults.py` | MODIFY | add to `WIRE_SUBCLASSES` |
| `tests/clients/test_openai_base_parity.py` | MODIFY | add to `WIRE_SUBCLASSES` |
| `tests/clients/test_meta_client.py` | MODIFY | factory tests |

> **Codebase Contract correction (same as TASK-2833/2834)**: test path
> corrected to the root `tests/clients/test_meta_client.py` (created by
> TASK-2834), not `packages/ai-parrot/tests/clients/test_meta_client.py`.

---

## Codebase Contract (Anti-Hallucination)

### Verified Signatures
```python
# packages/ai-parrot/src/parrot/clients/factory.py
from .openrouter import OpenRouterClient          # :8  — direct-import pattern
from .moonshot import MoonshotClient              # :13
SUPPORTED_CLIENTS = {                             # :107
    "openrouter": OpenRouterClient,
    "moonshot": MoonshotClient, "kimi": MoonshotClient,   # alias pattern
    "grok": GrokClient, "xai": GrokClient,
    "zai": ZaiClient, "z.ai": ZaiClient,
    ...
}
PROVIDER_BACKEND: Dict[str, str] = {...}          # :155  — do NOT touch
class LLMFactory:                                 # :161
    @staticmethod
    def parse_llm_string(llm: str) -> Tuple[str, Optional[str]]   # :171
    @staticmethod
    def create(llm: str, model_args=None, tool_manager=None, **kwargs)  # :193
```
`create()` lowercases the provider and raises `ValueError` listing supported
keys for an unknown provider.

```python
# tests/clients/test_openai_compatible_defaults.py:49
WIRE_SUBCLASSES = [OpenRouterClient, MoonshotClient, NvidiaClient,
                   LocalLLMClient, vLLMClient, BedrockMantleClient,
                   GroqClient, ZaiClient]
# tests/clients/test_openai_base_parity.py:341  — identical roster
```

### Does NOT Exist
- ~~`from .meta.client import MetaClient` in factory.py~~ — import from the
  package (`from .meta import MetaClient`); the init is the public surface.
- ~~A lazy loader for `MetaClient`~~ — **not needed**. `MetaClient` only requires
  the `openai` SDK, already imported directly by six sibling clients. Use a
  direct import, matching `OpenRouterClient`, not the `_lazy_*` pattern.
- ~~A `PROVIDER_BACKEND` entry for `"meta"`~~ — that map injects an
  `AnthropicClient` backend kwarg (FEAT-232). Adding `"meta"` would be wrong.
- ~~Exporting `MetaClient` from `parrot/clients/__init__.py`~~ — decided against
  (spec §8, resolved).

---

## Implementation Notes

- Place the alias keys next to each other, with a short comment naming FEAT-526,
  matching how `bedrock-mantle`/`mantle` and `moonshot`/`kimi` are commented.
- Adding `MetaClient` to the two rosters automatically enrols it in
  `test_no_gpt_default_leak`, `test_invoke_chain_never_yields_gpt`,
  `test_ask_payload_model_never_leaks_gpt`, and the ask/ask_stream/invoke funnel
  parity sweeps. **Expect these to pass with no further work** — if any fails,
  that is a real defect in TASK-2834, not a reason to exclude `MetaClient` from
  the roster.
- Note `_ASK_PAYLOAD_ROSTER` / `_INVOKE_FUNNEL_ROSTER` derive from
  `WIRE_SUBCLASSES` by filtering out specific classes; `MetaClient` should not
  be filtered out of any of them.

---

## Acceptance Criteria

- [ ] `LLMFactory.create("meta:muse-spark-1.3")` returns a `MetaClient` with
      `model == "muse-spark-1.3"`.
- [ ] `LLMFactory.create("meta")` returns a `MetaClient` on the default model.
- [ ] Aliases `"muse"` and `"meta-muse"` resolve to `MetaClient`.
- [ ] `MetaClient` appears in `WIRE_SUBCLASSES` in both roster files.
- [ ] `pytest tests/clients/test_openai_compatible_defaults.py -v` fully passes.
- [ ] `pytest tests/clients/test_openai_base_parity.py -v` fully passes.
- [ ] The three registered keys exactly match `MetaClient.provider_keys`
      (`("meta", "muse", "meta-muse")`) — FEAT-523 generates satellite entry
      points from that tuple, so a drift here breaks the follow-on feature.
- [ ] `ruff check` clean on all modified files.

---

## Test Specification

```python
import pytest
from parrot.clients.factory import LLMFactory, SUPPORTED_CLIENTS
from parrot.clients.meta import MetaClient


class TestMetaFactoryRegistration:
    @pytest.mark.parametrize("alias", ["meta", "muse", "meta-muse"])
    def test_aliases_resolve(self, alias):
        assert SUPPORTED_CLIENTS[alias] is MetaClient

    def test_create_with_explicit_model(self):
        client = LLMFactory.create("meta:muse-spark-1.3")
        assert isinstance(client, MetaClient)
        assert client.model == "muse-spark-1.3"

    def test_create_with_default_model(self):
        assert LLMFactory.create("meta").model == "muse-spark-1.3"

    def test_registered_keys_match_provider_keys(self):
        keys = {k for k, v in SUPPORTED_CLIENTS.items() if v is MetaClient}
        assert keys == set(MetaClient.provider_keys)

    def test_in_both_wire_rosters(self):
        from tests.clients.test_openai_compatible_defaults import WIRE_SUBCLASSES as A
        from tests.clients.test_openai_base_parity import WIRE_SUBCLASSES as B
        assert MetaClient in A and MetaClient in B
```

---

## Agent Instructions

1. Confirm TASK-2834 is in `sdd/tasks/completed/`.
2. Verify the Codebase Contract (line numbers may have shifted).
3. Implement, run both roster suites in full, verify acceptance criteria.
4. Move to `sdd/tasks/completed/`, set `done` in the index, fill the note.

---

## Completion Note

**Completed by**: sdd-worker (Claude)
**Date**: 2026-09-04
**Notes**: Registered `MetaClient` in `SUPPORTED_CLIENTS` under `"meta"`,
`"muse"`, `"meta-muse"` (direct import, matching `OpenRouterClient` — no
lazy loader needed). Added `MetaClient` to `WIRE_SUBCLASSES` in both
`test_openai_compatible_defaults.py` and `test_openai_base_parity.py`;
all 96 tests across both files pass with zero further changes, confirming
TASK-2834's implementation is funnel-clean. `PROVIDER_BACKEND` untouched.
One test in the task's own scaffold needed adjusting:
`test_create_with_default_model` originally asserted
`LLMFactory.create("meta").model == "muse-spark-1.3"`, but `.model` is only
populated when a model kwarg is explicitly passed (per
`AbstractClient`/`OpenAIBaseClient` — the default is resolved lazily via
`default_model`/`_resolve_model` at call time, never stamped onto `.model`
at construction). Rewrote the assertion to check `client.default_model`
instead, matching `MoonshotClient`'s own factory tests
(`test_factory_create_moonshot`), which never assert `.model` for a
no-argument `LLMFactory.create()`.
**Deviations from spec**: test-path correction (see TASK-2833/2834); the
`test_create_with_default_model` assertion described above.
