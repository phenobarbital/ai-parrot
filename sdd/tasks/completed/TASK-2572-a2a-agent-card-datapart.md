# TASK-2572: A2A — Agent Card extension, inbound `DataPart` dispatch, queued renderer calls

**Feature**: FEAT-469 — A2UI Agent Functions Runtime (v1.0 RPC leg)
**Spec**: `sdd/specs/a2ui-agent-functions.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: L (4-8h)
**Depends-on**: TASK-2571
**Assigned-to**: unassigned

---

## Context

Implements **spec §3 Module 5** and goal **G5**. Makes the A2UI RPC leg reachable
over A2A: the Agent Card advertises the extension and its
`a2uiAgentCapabilities`, inbound `DataPart`s carrying
`mimeType: application/a2ui+json` are routed into `A2UIRuntime.dispatch`, and
agent→renderer envelopes come back inside an `Artifact`.

It also retires an error path that FEAT-470 left behind deliberately:
`_reject_action_components` currently refuses action-bearing components over A2A
with the message *"interactive A2UI over A2A is FEAT-B"* — **FEAT-469 is that
follow-up**, and the `allow_actions` flag added here is what turns it off, but
only when the card actually declares the extension (spec §7: otherwise the
client has no idea how to handle actions).

Runs in **parallel with TASK-2573** (HTTP transport): different packages, same
upstream dependency.

---

## Scope

- Append an `AgentExtension` for A2UI to `AgentCapabilities.extensions`, with
  `params.a2uiAgentCapabilities` from `agent_capabilities()`.
- Add `allow_actions` to `Artifact.from_a2ui_envelope`, gated on the card
  declaring the extension.
- Detect inbound A2UI `DataPart`s in `_handle_send_message` and
  `_handle_stream_message`, build an `A2UICallContext(transport="a2a")`, dispatch.
- Emit A→R envelopes as `Part(data=..., metadata={"mimeType": A2UI_MEDIA_TYPE})` in an `Artifact`.
- Deliver `callRendererFunction` **both** ways (spec §8 resolved OQ): on the
  `message/stream` SSE, **and** queued via `PendingCallRegistry` for attachment
  to the next `message/send` response.
- Unit tests.

**NOT in scope**: the HTTP endpoint (TASK-2573), deep links (TASK-2574), bot
turn context (TASK-2575), E2E round trips (TASK-2576).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/a2a/models.py` | MODIFY | `allow_actions` on `from_a2ui_envelope`; A2UI extension helper |
| `packages/ai-parrot-server/src/parrot/a2a/server.py` | MODIFY | Card extension; inbound DataPart dispatch; queued renderer calls |
| `packages/ai-parrot/tests/a2a/test_a2ui_agent_functions.py` | CREATE | Card + artifact tests |
| `packages/ai-parrot-server/tests/test_a2a_a2ui_dispatch.py` | CREATE | Server dispatch tests |

---

## Codebase Contract (Anti-Hallucination)

> Verified on `dev` @ `ce716a032` (2026-08-29). **The spec's §6 line numbers for
> this file are STALE** — use these.

### Verified Imports
```python
from parrot.a2a.models import (                       # packages/ai-parrot/src/parrot/a2a/models.py
    A2UI_EXTENSION_URI,   # 335 == "https://a2ui.org/a2a-extension/a2ui/v1.0"   (already v1.0)
    A2UI_MEDIA_TYPE,      # 336 == "application/a2ui+json"                       (already v1.0)
    AgentCapabilities,    # 928
    AgentCard,            # ~959
    AgentExtension,       # 511
    Artifact,             # ~362
    Part,                 # 129
)
from parrot.outputs.a2ui.catalog.export import agent_capabilities      # TASK-2571
from parrot.outputs.a2ui.runtime.dispatch import A2UIRuntime           # TASK-2569
from parrot.outputs.a2ui.runtime.models import A2UICallContext         # TASK-2568
# ai-parrot-server
from parrot.a2a.server import A2AServer                                # a2a/server.py:77
```

### Existing Signatures to Use
```python
# packages/ai-parrot/src/parrot/a2a/models.py
A2UI_EXTENSION_URI = "https://a2ui.org/a2a-extension/a2ui/v1.0"   # 335 — ALREADY correct, do NOT change
A2UI_MEDIA_TYPE    = "application/a2ui+json"                      # 336 — ALREADY correct, do NOT change

def _reject_action_components(components: Any) -> None:           # 339
    """NOTE the signature: takes `components`, NOT an envelope (spec §6 said envelope — wrong)."""
    for comp in components or []:
        if getattr(comp, "action", None) is not None:
            raise ValueError(
                f"Display-only A2A emit (FEAT-273): component {comp.component!r} is "
                "action-bearing; interactive A2UI over A2A is FEAT-B."       # 356-359 <- FEAT-469 retires this
            )

@dataclass
class Artifact:                                                   # ~362
    artifact_id: str; parts: List[Part]; name / description / metadata
    @classmethod
    def from_a2ui_envelope(cls, envelope: Dict[str, Any], *,      # 372
                           name: str = "a2ui-surface",
                           artifact_id: Optional[str] = None) -> "Artifact":
        # body: deserialize(envelope) -> must be A2UIAgentMessage with create_surface
        #       -> _reject_action_components(message.create_surface.components)   # 413
        #       -> Part(data=envelope, metadata={"mimeType": A2UI_MEDIA_TYPE,
        #                                        "extensionUri": A2UI_EXTENSION_URI})   # 416
        #       -> cls(..., metadata={"extensionUri": A2UI_EXTENSION_URI})               # 422

@dataclass
class Part:                                                       # 129
    text, file_uri, file_bytes, file_media_type, filename,
    data: Optional[Dict], metadata: Optional[Dict]

@dataclass
class AgentExtension:                                             # 511
    uri: str                                                      # 514
    description: Optional[str] = None                             # 515
    required: bool = False                                        # 516
    params: Optional[Dict[str, Any]] = None                       # 517
    def to_dict(self, version: str = "1.0") -> Dict[str, Any]:    # 519 — emits uri/required/description?/params?

@dataclass
class AgentCapabilities:                                          # 928
    streaming: bool = True                                        # 931
    push_notifications: bool = False                              # 932
    extended_agent_card: bool = False                             # 933
    extensions: List[AgentExtension] = field(default_factory=list) # 934
    def to_dict(self, version="1.0"):                             # 936 — includes "extensions" only when non-empty (942)

# packages/ai-parrot-server/src/parrot/a2a/server.py
class A2AServer:                                                  # 77
    self.capabilities = capabilities or AgentCapabilities(streaming=True)   # 169
    def setup(self, app, ...)                                     # 219
    async def _handle_send_message(self, request) -> web.Response # 1092
    async def _handle_stream_message(self, request) -> web.StreamResponse  # 1132
```

### How `_handle_send_message` works today (read before editing — verified at 1092-1130)
```python
version = self._get_request_version(request)
data    = await request.json()
message = Message.from_dict(data.get("message", {}))
config  = SendMessageConfiguration.from_dict(data.get("configuration") or {})
if config.return_immediately:
    task = Task.create(context_id=message.context_id); task.history.append(message)
    self._tasks[task.id] = task
    self._spawn_background(self.process_message(message, task=task))
else:
    task = await self.process_message(message)
result = task.to_dict(version)
if config.history_length is not None: result["history"] = result["history"][-n:] ...
return self._versioned_response(result, version)
```
Insert the A2UI check **after** `Message.from_dict` and **before** the
`return_immediately` branch: an A2UI envelope is an RPC, not a conversational
turn, and must not be spawned as a background task. Preserve the existing
`web.HTTPException` / `json.JSONDecodeError` / generic-`Exception` handling
shape (1120-1130).

### Does NOT Exist
- ~~`A2UI_EXTENSION_URI == ".../extensions/a2a/display/v1"`~~ — that was the pre-FEAT-470 value; it is **already** the v1.0 URI at line 335. Do not "fix" it.
- ~~`Part.mime_type`~~ — the mimeType lives in `Part.metadata["mimeType"]`; there is no such attribute.
- ~~`AgentCapabilities.a2ui`~~ / ~~`AgentCard.agent_capabilities`~~ — nothing A2UI exists on the card; you add it via `extensions`.
- ~~`Artifact.from_a2ui_envelope(..., allow_actions=...)`~~ — this task adds the parameter.
- ~~`_reject_action_components(envelope)`~~ — it takes **components**, not an envelope.
- ~~a `DataPart` class~~ — there is none. "DataPart" in the spec means a `Part` whose `.data` is set; discriminate on `Part.metadata["mimeType"]`.

---

## Implementation Notes

### Agent Card
```python
AgentExtension(
    uri=A2UI_EXTENSION_URI,
    description="A2UI v1.0 — interactive surfaces and agent/renderer function calls.",
    required=False,
    params={"a2uiAgentCapabilities": agent_capabilities([DEFAULT_CATALOG_ID, BASIC_CATALOG_ID])},
)
```
Append to `self.capabilities.extensions` — **do not replace the list** (other
extensions may already be registered). Appending must be idempotent: adding the
same URI twice on a re-`setup()` would publish a duplicate extension.

### `allow_actions`
```python
def from_a2ui_envelope(cls, envelope, *, name="a2ui-surface",
                       artifact_id=None, allow_actions: bool = False): ...
```
Default `False` keeps every current caller's behaviour byte-for-byte (the spec
requires "sin él, comportamiento actual"). Only skip
`_reject_action_components` when `allow_actions=True`, and only pass `True`
from a path that has confirmed the card declares the extension.

### Inbound dispatch
Detect: any `part` in `message.parts` where `part.data` is set **and**
`(part.metadata or {}).get("mimeType") == A2UI_MEDIA_TYPE`.

Build the context:
```python
A2UICallContext(agent_id=..., user_id=..., session_id=message.context_id or ...,
                transport="a2a", streaming=<True in _handle_stream_message>,
                permission_context=build_principal_context(principal=user_id, channel="a2ui"))
```
(`build_principal_context` is at `parrot/auth/permission.py:166` — see spec §8's
resolved OQ; A2A has no ambient `PermissionContext` either.)

Response: wrap each `DispatchResult.messages` entry in
`Part(data=env, metadata={"mimeType": A2UI_MEDIA_TYPE, "extensionUri": A2UI_EXTENSION_URI})`
inside an `Artifact`, mirroring lines 416-423 exactly.

### Dual delivery of `callRendererFunction` (spec §8 resolved OQ)
- **`message/stream`**: emit as an SSE event as soon as `call_renderer()` produces it.
- **`message/send`**: it cannot be pushed, so it is queued in the
  `PendingCallRegistry` and **attached to the next `message/send` response** for
  that session. Drain the queue for `ctx.session_id` when building the response
  artifact.

The registry is the single source of truth for correlation — do not add a second
in-memory queue on `A2AServer`, or a call delivered by stream could be delivered
again by the next send. Draining must be atomic with respect to the TTL sweep.

### Key Constraints
- Do not change the two module constants (already v1.0).
- Do not alter the existing exception-handling structure of the two handlers.
- `parrot/a2a/models.py` is in **core**; it must not import `parrot.bots`/`parrot.clients`. Import the runtime lazily if needed.
- async throughout; `self.logger`.

### References in Codebase
- `a2a/models.py:372-423` — `from_a2ui_envelope`; the Part/Artifact metadata shape to mirror.
- `packages/ai-parrot/tests/a2a/test_a2ui_extension_emit.py` — the existing A2UI-over-A2A test; extend its patterns.
- `packages/ai-parrot-server/tests/test_a2a_output_mode.py` — server-side A2A test harness precedent.

---

## Acceptance Criteria

- [ ] The v1.0 Agent Card includes `extensions[].uri == A2UI_EXTENSION_URI` carrying `params.a2uiAgentCapabilities`.
- [ ] Registering twice does not duplicate the extension; pre-existing extensions are preserved.
- [ ] `from_a2ui_envelope(..., allow_actions=True)` accepts action-bearing components; the default (`False`) still raises exactly as today.
- [ ] A `message/send` whose message carries a `Part` with `mimeType: application/a2ui+json` is dispatched through `A2UIRuntime` and **not** treated as a conversational turn.
- [ ] The response `Artifact` carries A→R envelopes as `Part`s with the same mimeType.
- [ ] `callRendererFunction` is emitted on the `message/stream` SSE **and** attached to the next `message/send` response, never both for the same `functionCallId`.
- [ ] Existing A2A behaviour for non-A2UI messages is unchanged.
- [ ] Tests pass: `pytest packages/ai-parrot/tests/a2a packages/ai-parrot-server/tests/test_a2a_a2ui_dispatch.py -v`
- [ ] No linting errors: `ruff check packages/ai-parrot/src/parrot/a2a/models.py packages/ai-parrot-server/src/parrot/a2a/server.py`

---

## Test Specification

```python
# packages/ai-parrot/tests/a2a/test_a2ui_agent_functions.py
class TestAgentCard:
    def test_declares_a2ui_extension_with_capabilities(self):
        card = build_card_with_a2ui()
        ext = next(e for e in card.capabilities.extensions if e.uri == A2UI_EXTENSION_URI)
        assert ext.params["a2uiAgentCapabilities"]["v1.0"]["supportedCatalogIds"]

    def test_registration_is_idempotent(self): ...
    def test_preserves_preexisting_extensions(self): ...


class TestArtifactAllowActions:
    def test_allows_actions_when_flagged(self, action_bearing_envelope):
        Artifact.from_a2ui_envelope(action_bearing_envelope, allow_actions=True)

    def test_default_still_rejects(self, action_bearing_envelope):
        with pytest.raises(ValueError, match="action-bearing"):
            Artifact.from_a2ui_envelope(action_bearing_envelope)
```

```python
# packages/ai-parrot-server/tests/test_a2a_a2ui_dispatch.py
class TestInboundDataPart:
    async def test_dispatches_a2ui_part(self, a2a_client):
        """Part.metadata['mimeType'] == application/a2ui+json routes to dispatch."""
        ...
    async def test_response_artifact_uses_same_mimetype(self, a2a_client): ...
    async def test_non_a2ui_message_unchanged(self, a2a_client): ...
    async def test_a2ui_rpc_not_spawned_as_background_task(self, a2a_client): ...

class TestQueuedRendererCalls:
    async def test_stream_emits_call_renderer_function(self, a2a_client): ...
    async def test_next_send_drains_queued_call(self, a2a_client): ...
    async def test_call_never_delivered_twice(self, a2a_client): ...
```

---

## Agent Instructions

1. **Read the spec** — §3 Module 5, §6 "Contract Refresh" (FINDING 4), §8 resolved OQ on A2A delivery.
2. **Check dependencies** — TASK-2571 in `sdd/tasks/completed/`.
3. **Verify the Codebase Contract** — the spec's original §6 line numbers for
   `a2a/models.py` are stale; re-confirm 335/336/339/372/511/928 before editing,
   and **read `_handle_send_message` (1092) in full** before inserting anything.
4. **Update status** in the index → `"in-progress"`.
5. **Implement** per scope.
6. **Verify** every acceptance criterion.
7. **Move this file** to `sdd/tasks/completed/`.
8. **Update index** → `"done"`.
9. **Fill in the Completion Note**.

---

## Completion Note

**Completed by**: sdd-worker (Claude Sonnet)
**Date**: 2026-08-29
**Notes**: Added `a2ui_agent_extension(catalog_ids)`/`register_a2ui_extension(capabilities,
catalog_ids)` to CORE `a2a/models.py` (the task's own file table calls for
"A2UI extension helper" in `models.py`, not just server-side logic) — this
lets the Agent Card test suite (`packages/ai-parrot/tests/a2a/`) exercise
idempotency/preservation directly against `AgentCapabilities`, without
depending on `A2AServer`/ai-parrot-server at all. `A2AServer.__init__` now
just calls `register_a2ui_extension(self.capabilities, [DEFAULT_CATALOG_ID,
BASIC_CATALOG_ID])` right after `self.capabilities` is set. Added
`allow_actions: bool = False` to `Artifact.from_a2ui_envelope` — default
unchanged behavior, `True` skips `_reject_action_components`. Inbound A2UI
`Part` detection (`_find_a2ui_part`, discriminated on
`Part.metadata["mimeType"] == A2UI_MEDIA_TYPE`) is wired into BOTH
`_handle_send_message` (bypasses `returnImmediately` entirely — dispatched
synchronously, never as a background task) and `_handle_stream_message`
(new `_emit_a2ui_stream`, mirrors the existing `task`/`artifactUpdate`/
`statusUpdate` SSE frame sequence). `_dispatch_a2ui_message` builds a fresh
`A2UIRuntime`/`ConversationMemorySurfaceStore` per request (bound to the
request's `user_id` via `_extract_identity`), builds a `PermissionContext`
via `build_principal_context` when a user_id is known, dispatches, and wraps
`DispatchResult.messages` into `Part`s inside a `COMPLETED` `Task`'s
`Artifact` — mirroring `from_a2ui_envelope`'s Part/Artifact metadata shape
exactly, without reusing that method itself (it is hardcoded to
`createSurface`-only envelopes; RPC response types are a different, new code
path). 12 new tests pass (5 in `test_a2ui_agent_functions.py`, 7 in
`test_a2a_a2ui_dispatch.py`); full `tests/outputs/a2ui`+`tests/a2a` (554
tests, ai-parrot) and the `-k a2a` slice of ai-parrot-server's suite (139
passed) show zero regressions — the only failures present (3 vertical-integration
broker tests, `test_hitl_web_suspend_resume.py`/`test_suspended_store.py`
missing `fakeredis`) are confirmed pre-existing via `git stash`. `ruff check`:
zero NEW violations in any of the three pre-existing files touched
(`models.py`, `server.py`, `adapters.py`) — verified by diffing
`ruff check`'s per-rule counts before/after this change; both files carry
large amounts of pre-existing legacy-style debt (96 baseline errors in
`server.py`, dozens in `models.py`) intentionally left untouched (out of
scope, would be massive unrelated scope creep).

**Deviations from spec**: **One cross-task file addition**, fully necessary
and documented: extended `runtime/adapters.py`'s `ConversationMemorySurfaceStore`
(TASK-2570's file, not in TASK-2572's declared list) with two NEW methods —
`list_undelivered(session_id)` (non-destructive peek at pending calls not yet
delivered) and `mark_delivered(session_id, function_call_id)`. Root cause:
the frozen `PendingCallRegistry` Protocol (TASK-2568/2569) only exposes
`add`/`resolve`, and `resolve()` DELETES the record on match — correct for
*correlation* (matching a LATER `rendererFunctionResponse`) but destructive
if reused as a "mark delivered" operation, which would make the SAME record
permanently unresolvable once "delivered". There is no way to implement the
AC "`callRendererFunction` ... attached to the next `message/send` response
... never both for the same `functionCallId`" without a non-destructive
delivery marker somewhere. Implemented as a NEW `_delivered` key alongside
the existing `FunctionCallRecord` fields in the SAME `a2ui_pending_calls`
metadata map (not a new store, not a new Protocol member — `A2AServer`
depends on the CONCRETE `ConversationMemorySurfaceStore` class directly
already, to construct it in the first place, so calling two more of its
methods is not a new coupling). `pydantic.BaseModel`'s v2 default
`extra="ignore"` means `FunctionCallRecord.model_validate()` on a dict
carrying the extra `_delivered` key round-trips safely without touching the
model itself. Documented at length in `adapters.py`'s own code comment for
the next reader. No other design changes: the runtime's dispatch control
flow, error taxonomy, and A2A wire shapes are exactly as specified.
