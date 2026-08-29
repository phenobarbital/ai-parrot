# TASK-2576: End-to-end integration and conformance tests

**Feature**: FEAT-469 — A2UI Agent Functions Runtime (v1.0 RPC leg)
**Spec**: `sdd/specs/a2ui-agent-functions.spec.md`
**Status**: pending
**Priority**: medium
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-2572, TASK-2573, TASK-2574, TASK-2575
**Assigned-to**: unassigned

---

## Context

Implements the **Integration Tests** table of spec §4 plus the two cross-cutting
acceptance criteria that no single earlier task can prove on its own:

- *"Todo sobre A→R emitido por el runtime valida contra `agent_to_renderer.json`;
  todo sobre R→A aceptado valida contra `renderer_to_agent.json`."*
- *"`dispatch` de un `callAgentFunction` añade < 5 ms de overhead sobre
  `execute_tool`."*

Every prior task tested its own layer against fakes. This one wires a real agent
with a real `@tool` to a real transport and proves the whole RPC leg works
end to end.

---

## Scope

- The five integration tests from spec §4.
- A conformance sweep validating every envelope the runtime emits/accepts
  against the vendored schemas.
- The `< 5 ms` dispatch-overhead benchmark.
- Shared fixtures (`v1_schemas`, `memory_store`, `a2ui_call_ctx`) consolidated
  so unit and integration suites share one definition.

**NOT in scope**: implementation fixes — if a test fails, that is a defect in the
task that owns that layer; record it and fix it there rather than patching around
it here. Docs are TASK-2577.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/tests/outputs/a2ui/conformance/test_runtime_envelopes.py` | CREATE | Schema conformance sweep |
| `packages/ai-parrot/tests/outputs/a2ui/runtime/test_performance.py` | CREATE | Dispatch overhead benchmark |
| `packages/ai-parrot-server/tests/integration/test_a2ui_e2e.py` | CREATE | The five E2E tests |
| `packages/ai-parrot/tests/outputs/a2ui/conftest.py` | MODIFY | Shared `v1_schemas` fixture |

---

## Codebase Contract (Anti-Hallucination)

> Verified on `dev` @ `ce716a032` (2026-08-29).

### Vendored schemas — the exact paths (verified to exist)
```
packages/ai-parrot/src/parrot/outputs/a2ui/catalog/basic/spec/agent_to_renderer.json
packages/ai-parrot/src/parrot/outputs/a2ui/catalog/basic/spec/renderer_to_agent.json
packages/ai-parrot/src/parrot/outputs/a2ui/catalog/basic/spec/agent_capabilities.json
packages/ai-parrot/src/parrot/outputs/a2ui/catalog/basic/spec/catalog_definition.json
```
Load them via `parrot.outputs.a2ui.catalog.basic.load_spec(...)` — the same
helper `catalog/export.py` already uses — rather than hard-coding paths.

### Verified Imports
```python
from parrot.outputs.a2ui.catalog import validate_message, validate_envelope   # catalog/__init__.py:334, :378
from parrot.outputs.a2ui.catalog.basic import load_spec
from parrot.outputs.a2ui.serialization import serialize, deserialize, to_jsonl, iter_jsonl  # 104, 155, 201, 215
from parrot.memory.file import FileConversationMemory     # memory/file.py:9
from parrot.memory.redis import RedisConversation         # memory/redis.py:10
from parrot.tools import tool                             # the @tool decorator
```

### Existing test infrastructure to reuse (do not reinvent)
```
packages/ai-parrot/tests/outputs/a2ui/conformance/   — existing conformance suite dir
packages/ai-parrot/tests/outputs/a2ui/golden/        — golden-file fixtures
packages/ai-parrot/tests/a2a/test_a2ui_extension_emit.py       — A2UI-over-A2A test precedent
packages/ai-parrot-server/tests/conftest.py                    — server fixtures
packages/ai-parrot-server/tests/integration/                   — integration suite dir
packages/ai-parrot-server/tests/test_deeplink_resume_web.py    — deep-link test precedent
packages/ai-parrot-server/tests/test_a2a_output_mode.py        — A2A server test precedent
```

### The R→A / A→R split (needed to route each envelope to the right schema)
- **Renderer → Agent** (`renderer_to_agent.json`): `action`, `callAgentFunction`,
  `rendererFunctionResponse`, `error`. Envelope is `minProperties: 2, maxProperties: 2`.
- **Agent → Renderer** (`agent_to_renderer.json`): `createSurface`,
  `updateComponents`, `updateDataModel`, `deleteSurface`, `callRendererFunction`,
  `agentFunctionResponse`, `error`.

Note `error` appears on **both** sides with the two-shape rule (validation codes
`{VALIDATION_FAILED, UNALLOWED_PARENT, UNALLOWED_CHILD}` require
`surfaceId`+`path`; any other code requires exactly one of
`surfaceId`/`functionCallId`). The conformance sweep must exercise both shapes.

### Does NOT Exist
- ~~a shared `v1_schemas` fixture~~ — this task consolidates one.
- ~~`jsonschema` as a hard dependency~~ — spec §7 lists it as an **optional** extra (`>=4.20`) from FEAT-470. Guard the conformance tests with `pytest.importorskip("jsonschema")`.
- ~~a Redis test container~~ — check what `packages/ai-parrot-server/tests/conftest.py` and `tests/fixtures/` actually provide before assuming; fall back to `FileConversationMemory` and mark the Redis-specific test appropriately rather than inventing infrastructure.

---

## Implementation Notes

### The five integration tests (spec §4, verbatim intent)
| Test | What it must actually prove |
|---|---|
| `test_e2e_http_call_agent_function` | A real `@tool`-decorated function, invoked via POST, returns its real result in `agentFunctionResponse` |
| `test_e2e_http_action_with_send_data_model` | `action` + `dataModel` persists to memory, and the **next turn sees it** via `_a2ui_surface_state` |
| `test_e2e_a2a_round_trip` | The card advertises the extension; `message/send` with an A2UI `DataPart` returns an A2UI `Artifact` |
| `test_e2e_call_renderer_function_correlation` | A tool calls `runtime.call_renderer()`; the stream delivers it; `rendererFunctionResponse` resolves the pending record |
| `test_e2e_deeplink_to_action` | A deep-link click produces a v1.0 `action` → a bot turn |

### The performance criterion
"< 5 ms overhead over `execute_tool`, measured with a no-op executor." Measure
`dispatch` with a no-op executor against a direct no-op call, over enough
iterations to be stable, and compare **medians** — a mean over a handful of runs
is noise on a shared CI box. If it is flaky in CI, mark it and record the real
measured number in the completion note rather than loosening the threshold
silently.

### The conformance sweep
Parametrize over every message type the runtime can emit or accept, assert
direction-correct schema validation, and include the negative cases the earlier
tasks established:
- `callAgentFunction` **must reject** a `dataModel` key (`additionalProperties: false`).
- `action` **must accept** one (no `additionalProperties` key ⇒ permitted).
- `callRendererFunction` **requires** `callFunction.catalogId` (stricter than the
  pydantic model — this is exactly the kind of gap only a schema test catches).

### Key Constraints
- `pytest` + `pytest-asyncio`; fixtures for all shared state.
- Do not weaken an assertion to make a test pass — file the defect against the owning task.
- No network calls; everything local.

### References in Codebase
- `tests/outputs/a2ui/conformance/` — follow the existing conformance style.
- `tests/outputs/a2ui/test_serialization.py` — round-trip test patterns.
- `.agent/CONTEXT.md` — async/pytest conventions.

---

## Acceptance Criteria

- [ ] All five integration tests from spec §4 exist and pass.
- [ ] Every A→R envelope the runtime emits validates against `agent_to_renderer.json`.
- [ ] Every R→A envelope the runtime accepts validates against `renderer_to_agent.json`.
- [ ] Both `error` shapes (validation and generic) are exercised and validated.
- [ ] `callAgentFunction` + `dataModel` is proven schema-invalid; `action` + `dataModel` proven valid.
- [ ] `callRendererFunction` is proven to require `callFunction.catalogId`.
- [ ] The dispatch-overhead benchmark runs and reports a median under 5 ms with a no-op executor.
- [ ] Conformance tests skip cleanly when `jsonschema` is not installed.
- [ ] Full suite passes: `pytest packages/ai-parrot/tests/outputs/a2ui packages/ai-parrot/tests/a2a packages/ai-parrot-server/tests -v`
- [ ] No linting errors: `ruff check packages/ai-parrot/tests/outputs/a2ui packages/ai-parrot-server/tests/integration`

---

## Test Specification

```python
# packages/ai-parrot/tests/outputs/a2ui/conformance/test_runtime_envelopes.py
import pytest

jsonschema = pytest.importorskip("jsonschema")
from jsonschema import Draft202012Validator


@pytest.fixture(scope="session")
def v1_schemas():
    from parrot.outputs.a2ui.catalog.basic import load_spec
    return {n: load_spec(n) for n in
            ("agent_to_renderer", "renderer_to_agent",
             "agent_capabilities", "catalog_definition")}


@pytest.mark.parametrize("envelope", ALL_AGENT_TO_RENDERER_ENVELOPES)
def test_agent_to_renderer_conformance(envelope, v1_schemas):
    Draft202012Validator(v1_schemas["agent_to_renderer"]).validate(envelope)


@pytest.mark.parametrize("envelope", ALL_RENDERER_TO_AGENT_ENVELOPES)
def test_renderer_to_agent_conformance(envelope, v1_schemas):
    Draft202012Validator(v1_schemas["renderer_to_agent"]).validate(envelope)


def test_call_agent_function_rejects_data_model(v1_schemas):
    """additionalProperties: false on callAgentFunction."""
    with pytest.raises(jsonschema.ValidationError):
        Draft202012Validator(v1_schemas["renderer_to_agent"]).validate({
            "version": "v1.0",
            "callAgentFunction": {"surfaceId": "s", "functionCallId": "f",
                                  "callFunction": {"call": "x", "args": {}},
                                  "dataModel": {}}})


def test_action_accepts_data_model(v1_schemas): ...
def test_call_renderer_function_requires_catalog_id(v1_schemas): ...
def test_error_validation_shape_requires_surface_and_path(v1_schemas): ...
def test_error_generic_shape_requires_exactly_one_id(v1_schemas): ...
```

```python
# packages/ai-parrot-server/tests/integration/test_a2ui_e2e.py
class TestE2E:
    async def test_e2e_http_call_agent_function(self, agent_with_real_tool, client): ...
    async def test_e2e_http_action_with_send_data_model(self, client, memory): ...
    async def test_e2e_a2a_round_trip(self, a2a_server, a2a_client): ...
    async def test_e2e_call_renderer_function_correlation(self, client): ...
    async def test_e2e_deeplink_to_action(self, client, deeplink_service): ...
```

```python
# packages/ai-parrot/tests/outputs/a2ui/runtime/test_performance.py
async def test_dispatch_overhead_under_5ms(noop_runtime, a2ui_call_ctx):
    """Compare MEDIANS over many iterations — a mean over a few is CI noise."""
    ...
```

---

## Agent Instructions

1. **Read the spec** — §4 (Integration Tests + Test Data/Fixtures) and §5 (Acceptance Criteria).
2. **Check dependencies** — TASK-2572, 2573, 2574, 2575 all in `sdd/tasks/completed/`.
3. **Verify the Codebase Contract** — confirm the four schema paths and inspect
   `packages/ai-parrot-server/tests/conftest.py` + `tests/fixtures/` for what
   Redis/aiohttp infrastructure already exists before building any.
4. **Update status** in the index → `"in-progress"`.
5. **Implement** the tests. **Do not weaken assertions to make them pass** — file
   defects against the owning task instead.
6. **Verify** every acceptance criterion.
7. **Move this file** to `sdd/tasks/completed/`.
8. **Update index** → `"done"`.
9. **Fill in the Completion Note**, including the measured dispatch overhead.

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**: <session or agent ID>
**Date**: YYYY-MM-DD
**Notes**:

**Measured dispatch overhead (median)**: ___ ms
**Defects found and where filed**:

**Deviations from spec**: none | describe if any
