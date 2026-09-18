# TASK-3386: M0 — repair `UnifiedMemoryManager` episodic recording with a real-store regression test

**Feature**: FEAT-571 — Agent Memory Dynamics
**Spec**: `sdd/specs/memory-dynamics.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: S (< 2h)
**Depends-on**: none
**Assigned-to**: unassigned

---

## Context

Spec §3 **M0: Unified Recording Prerequisite** (Lane 0c, AC02) — the one Lane 0 module that
is *not* a gate and has **no dynamics dependency**. `UnifiedMemoryManager._record_episodic`
calls `self.episodic.record_tool_episode(namespace=…, query=…, response=…, tool_calls=…)`
— keywords that method does not accept (its real signature is
`record_tool_episode(namespace, tool_name, tool_args, tool_result, user_query=None)`, C1).
The resulting `TypeError` is swallowed by `record_interaction`'s broad `except`, so every
`LongTermMemoryMixin` agent (which passes `tool_calls=[]` from
`_post_response_memory_hook`) records **no** episodes today (C4). The existing unit test
masks this with a permissive `AsyncMock()` store.

The new dynamics must operate on durably recorded episodes (spec §1), so this repair lands
first, alone, and emits **no memory review**.

---

## Scope

- Keep `_record_episodic(self, query, response, tool_calls, user_id, session_id) -> None`.
  Build the namespace from `self.namespace` with the supplied user/session **and preserve
  `room_id`/`crew_id`**. Record one conversational episode through the existing
  `record_episode(...)` using the query/response text, `EpisodeCategory.QUERY_RESOLUTION`,
  `EpisodeOutcome.PARTIAL` and the store's existing importance inference (`importance=None`).
- `tool_calls` is accepted for signature compatibility only: tool calls are not proof of
  success and their own hooks own tool episodes — they are **not** re-recorded here.
- Do **not** change `record_tool_episode`'s signature to accommodate the invalid keywords.
- Harden `tests/memory/unified/test_manager.py`: autospec the store mock so calls with
  keywords the real store lacks raise; retarget the failure-path test; assert the exact
  `record_episode` kwargs.
- Add `tests/memory/unified/test_manager_real_store.py`: a **real** `EpisodicMemoryStore` over
  an in-memory `FAISSBackend` proves a persisted PARTIAL/QUERY_RESOLUTION episode with
  room/crew retained, and that calling `_record_episodic` directly raises nothing.

**NOT in scope**: any `parrot/memory/dynamics/*` code (M1); changing `EpisodicMemoryMixin`
(M3 changes *its* SUCCESS/no-signal semantics separately); memory reviews or exposure
manifests; touching `record_tool_episode`; the gate tasks.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/memory/unified/manager.py` | MODIFY | import enums; rewrite `_record_episodic` body to call `record_episode` |
| `packages/ai-parrot/tests/memory/unified/test_manager.py` | MODIFY | autospec store fixture; retarget side-effect; add kwargs assertion test |
| `packages/ai-parrot/tests/memory/unified/test_manager_real_store.py` | CREATE | real-store regression (FAISS in-memory) |

---

## Codebase Contract (Anti-Hallucination)

> Verified against `dev` @ `fc1a5728a55648566e264cb95c5df36190438204` on 2026-09-18.
> `core/` = `packages/ai-parrot/src/parrot/`.

### Verified Imports
```python
from parrot.memory.episodic.models import EpisodeCategory, EpisodeOutcome, MemoryNamespace  # core/memory/episodic/models.py:29,20,214
from parrot.memory.episodic.store import EpisodicMemoryStore                                # core/memory/episodic/store.py:57
from parrot.memory.episodic.backends.faiss import FAISSBackend                              # core/memory/episodic/backends/faiss.py:54 (faiss 1.15.1 installed; _ensure_faiss :35 raises ImportError otherwise)
from parrot.memory.unified.manager import UnifiedMemoryManager                              # core/memory/unified/manager.py:53
from parrot.memory.unified.models import MemoryConfig                                       # core/memory/unified/models.py:89
```

### Existing Signatures to Use
```python
# core/memory/unified/manager.py
from parrot.memory.episodic.models import MemoryNamespace          # :14  ← the import line this task extends
class UnifiedMemoryManager:                                          # :53
    def __init__(self, namespace: MemoryNamespace, conversation_memory=None, episodic_store: Optional[EpisodicMemoryStore] = None,
                 skill_registry=None, config=None, cross_domain_router=None, brain=None, org_brain=None) -> None  # :81-101
    #   self.namespace = namespace :94 ; self.episodic = episodic_store :95 ; self.logger :102
    async def record_interaction(self, query: str, response: Any, tool_calls: list[Any], user_id: str, session_id: str) -> None  # :177 — try/except Exception → logger.warning :197-205
    async def _record_episodic(self, query: str, response: Any, tool_calls: list[Any], user_id: str, session_id: str) -> None  # :368
    #   ns = MemoryNamespace(tenant_id=…, agent_id=…, user_id=…, session_id=…) :385-390  (drops room_id/crew_id)
    #   await self.episodic.record_tool_episode(namespace=ns, query=query, response=response_text, tool_calls=tool_calls) :395-400  ← INVALID keywords
    #   also calls self.episodic.get_failure_warnings(namespace=…, current_query=…, max_warnings=…) :229-233 (valid; autospec must keep passing)

# core/memory/episodic/store.py
class EpisodicMemoryStore:                                           # :57
    def __init__(self, backend: AbstractEpisodeBackend, embedding_provider=None, reflection_engine=None, redis_cache=None,
                 default_ttl_days: int = 90, importance_scorer=None, recall_strategy=None) -> None   # :86
    async def record_episode(self, namespace: MemoryNamespace, situation: str, action_taken: str, outcome: EpisodeOutcome,
                             outcome_details: str | None = None, error_type: str | None = None, error_message: str | None = None,
                             category: EpisodeCategory = EpisodeCategory.TOOL_EXECUTION, importance: int | None = None,
                             related_tools: list[str] | None = None, related_entities: list[str] | None = None,
                             metadata: dict[str, Any] | None = None, generate_reflection: bool = True,
                             ttl_days: int | None = None) -> EpisodicMemory                         # :106
    #   importance=None → _auto_importance(outcome, error_type) :148-153 (PARTIAL → 5 :46-47) ; ttl_days=0 → no expiry :157
    #   builds EpisodicMemory with room_id=namespace.room_id, crew_id=namespace.crew_id :180-181 ; await self._backend.store(episode) :221
    async def record_tool_episode(self, namespace: MemoryNamespace, tool_name: str, tool_args: dict[str, Any], tool_result: Any,
                                  user_query: str | None = None) -> EpisodicMemory                   # :235  (DO NOT change)
    async def get_failure_warnings(self, namespace: MemoryNamespace, current_query: str | None = None, max_warnings: int = 5) -> str  # :436

# core/memory/episodic/models.py
class EpisodeOutcome(str, Enum): SUCCESS, FAILURE, PARTIAL, TIMEOUT            # :20
class EpisodeCategory(str, Enum): TOOL_EXECUTION, QUERY_RESOLUTION, …          # :29
class EpisodicMemory(BaseModel): user_id :89, session_id :92, room_id :95, crew_id :98, situation :103, action_taken :106, outcome :109, category, importance, is_failure  # :55
class MemoryNamespace(BaseModel): tenant_id="default", agent_id (required), user_id, session_id, room_id, crew_id  # :214 ; def build_filter(self) -> dict[str, Any] :245

# core/memory/episodic/backends/faiss.py
class FAISSBackend:                                                            # :54
    def __init__(self, dimension: int = 384, persistence_path: str | None = None, max_episodes: int = 10000, auto_save_interval: int = 100) -> None  # :70
    async def configure(self) -> None   # :89        async def store(self, episode) -> str   # :111 (stores without embedding too)
    async def get_recent(self, namespace_filter: dict[str, Any], limit: int = 10, since: datetime | None = None) -> list[EpisodicMemory]  # :199 (uses _matches_filter :44 — getattr equality on every filter key)

# core/memory/unified/mixin.py
async def _post_response_memory_hook(self, query, response, user_id, session_id) -> None   # :313 → record_interaction(..., tool_calls=[], ...) :328-334

# packages/ai-parrot/tests/memory/unified/test_manager.py (current)
from unittest.mock import AsyncMock, MagicMock                                 # :3
def mock_episodic() -> AsyncMock: store = AsyncMock(); …; store.record_tool_episode = AsyncMock()  # :15-22 (permissive → masks the bug)
async def test_record_interaction_safe(...): mock_episodic.record_tool_episode.side_effect = Exception("Redis down")  # :72-82
# packages/ai-parrot/pyproject.toml:999  asyncio_mode = "auto"  (async tests/fixtures need no marker)
```

### Does NOT Exist
- ~~`EpisodicMemoryStore.record_tool_episode(query=..., response=..., tool_calls=...)`~~ — no such overload; that is the bug.
- ~~`EpisodicMemoryStore.configure()` / `.cleanup()`~~ — the store has neither; the manager skips subsystems lacking them. The unit fixture *sets* them on the mock (allowed on an autospec without `spec_set`).
- ~~`EpisodicMemoryStore._embedding` as a class attribute~~ — instance attribute set in `__init__`; on an autospec'd instance `getattr(store, "_embedding", None)` returns `None` (manager.py:244 relies on that default).
- ~~any review/exposure/`MemoryState`~~ — M0 emits no review; nothing from `parrot.memory.dynamics` exists yet.
- ~~a `conftest.py` FAISS fixture~~ — none under `tests/memory/unified/`; the new test builds its own backend.

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {"path": "packages/ai-parrot/src/parrot/memory/unified/manager.py", "action": "MODIFY"},
    {"path": "packages/ai-parrot/tests/memory/unified/test_manager.py", "action": "MODIFY"},
    {"path": "packages/ai-parrot/tests/memory/unified/test_manager_real_store.py", "action": "CREATE"}
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot/src/parrot/memory/unified/manager.py#UnifiedMemoryManager",
    "sym:packages/ai-parrot/src/parrot/memory/unified/manager.py#UnifiedMemoryManager.record_interaction",
    "sym:packages/ai-parrot/src/parrot/memory/unified/manager.py#UnifiedMemoryManager._record_episodic",
    "sym:packages/ai-parrot/src/parrot/memory/episodic/store.py#EpisodicMemoryStore",
    "sym:packages/ai-parrot/src/parrot/memory/episodic/store.py#EpisodicMemoryStore.record_episode",
    "sym:packages/ai-parrot/src/parrot/memory/episodic/store.py#EpisodicMemoryStore.record_tool_episode",
    "sym:packages/ai-parrot/src/parrot/memory/episodic/store.py#EpisodicMemoryStore.get_failure_warnings",
    "sym:packages/ai-parrot/src/parrot/memory/episodic/models.py#EpisodeOutcome",
    "sym:packages/ai-parrot/src/parrot/memory/episodic/models.py#EpisodeCategory",
    "sym:packages/ai-parrot/src/parrot/memory/episodic/models.py#EpisodicMemory",
    "sym:packages/ai-parrot/src/parrot/memory/episodic/models.py#MemoryNamespace",
    "sym:packages/ai-parrot/src/parrot/memory/episodic/backends/faiss.py#FAISSBackend",
    "sym:packages/ai-parrot/src/parrot/memory/episodic/backends/faiss.py#FAISSBackend.get_recent"
  ]
}
```

---

## Delegation Contract

```json
{
  "schema_version": 1,
  "task_id": "TASK-3386",
  "spec_path": "sdd/specs/memory-dynamics.spec.md",
  "design_complete": true,
  "targets": [
    {
      "path": "packages/ai-parrot/src/parrot/memory/unified/manager.py",
      "action": "modify",
      "expected_sha256": "2a9fd3222c72b8463da9f9df5b8dcf1a48cc6a5bec4f53421fa6fbf0fdd5cdc5",
      "planned_changes": "Extend the episodic models import (line 14) with EpisodeCategory and EpisodeOutcome; replace the _record_episodic body (lines 385-400) so it builds the namespace with room_id/crew_id and calls record_episode(PARTIAL, QUERY_RESOLUTION) instead of the non-existent record_tool_episode(query=, response=, tool_calls=) overload",
      "blocks": ["impl-manager-import", "impl-manager-body"]
    },
    {
      "path": "packages/ai-parrot/tests/memory/unified/test_manager.py",
      "action": "modify",
      "expected_sha256": "582da7d17d47ac2cf7939c28762ff6b2f45fac37f8090f35754077d23dca706a",
      "planned_changes": "Autospec the store mock (lines 15-22) so invalid keywords raise TypeError; retarget the failure-path side_effect (line 75) to record_episode; add test_record_interaction_calls_record_episode after test_record_interaction_safe",
      "blocks": ["impl-test-imports", "impl-test-fixture", "impl-test-safe", "impl-test-new"]
    },
    {
      "path": "packages/ai-parrot/tests/memory/unified/test_manager_real_store.py",
      "action": "create",
      "expected_sha256": null,
      "planned_changes": "New regression module: real EpisodicMemoryStore over in-memory FAISSBackend proves a persisted PARTIAL/QUERY_RESOLUTION episode with room/crew and that _record_episodic raises nothing",
      "blocks": ["impl-real-store-test"]
    }
  ],
  "references": [
    {
      "path": "packages/ai-parrot/src/parrot/memory/unified/manager.py",
      "sha256": "2a9fd3222c72b8463da9f9df5b8dcf1a48cc6a5bec4f53421fa6fbf0fdd5cdc5",
      "start_line": 368,
      "end_line": 400,
      "purpose": "_record_episodic as it exists today (namespace without room/crew; invalid record_tool_episode keywords)"
    },
    {
      "path": "packages/ai-parrot/tests/memory/unified/test_manager.py",
      "sha256": "582da7d17d47ac2cf7939c28762ff6b2f45fac37f8090f35754077d23dca706a",
      "start_line": 1,
      "end_line": 82,
      "purpose": "imports, permissive mock_episodic fixture and test_record_interaction_safe being retargeted"
    }
  ],
  "implementation_blocks": ["impl-manager-import", "impl-manager-body", "impl-test-imports", "impl-test-fixture", "impl-test-safe", "impl-test-new", "impl-real-store-test"],
  "acceptance_criteria": [
    "pytest packages/ai-parrot/tests/memory/unified/test_manager.py -q passes",
    "pytest packages/ai-parrot/tests/memory/unified/test_manager_real_store.py -q passes",
    "record_tool_episode signature unchanged",
    "no import from parrot.memory.dynamics"
  ],
  "validation_commands": [
    ["pytest", "packages/ai-parrot/tests/memory/unified/test_manager.py", "-q"],
    ["pytest", "packages/ai-parrot/tests/memory/unified/test_manager_real_store.py", "-q"]
  ]
}
```

```python id=impl-manager-import
# Apply to packages/ai-parrot/src/parrot/memory/unified/manager.py — replace line 14, which reads exactly:
#     from parrot.memory.episodic.models import MemoryNamespace
# with the following single line (occurrences: 1 — verified: grep -c 'from parrot.memory.episodic.models import MemoryNamespace' manager.py):
from parrot.memory.episodic.models import EpisodeCategory, EpisodeOutcome, MemoryNamespace
```

```python id=impl-manager-body
# Apply to packages/ai-parrot/src/parrot/memory/unified/manager.py — inside `async def _record_episodic(...)` (line 368),
# replace the body statements from `ns = MemoryNamespace(` (line 385) through the closing `)` of the
# `await self.episodic.record_tool_episode(` call (line 400) with the block below. Keep the signature and docstring.
# occurrences of `await self.episodic.record_tool_episode(`: 1 (verified: grep -c on manager.py).
        ns = MemoryNamespace(
            tenant_id=self.namespace.tenant_id,
            agent_id=self.namespace.agent_id,
            user_id=user_id,
            session_id=session_id,
            room_id=self.namespace.room_id,
            crew_id=self.namespace.crew_id,
        )
        response_text = (
            response if isinstance(response, str)
            else getattr(response, "content", str(response))
        )
        if not isinstance(response_text, str):
            response_text = str(response_text)
        # ``tool_calls`` is accepted for signature compatibility only: tool calls
        # are not proof of success and their own hooks record tool episodes
        # (FEAT-571 M0). A conversation turn has no verified outcome here, so it
        # is recorded as PARTIAL and no memory review is emitted.
        self.logger.debug(
            "_record_episodic: recording query episode for %s/%s (tool_calls=%d ignored)",
            user_id,
            session_id,
            len(tool_calls or []),
        )
        await self.episodic.record_episode(  # type: ignore[union-attr]
            namespace=ns,
            situation=query[:500],
            action_taken=f"Responded: {response_text}",
            outcome=EpisodeOutcome.PARTIAL,
            category=EpisodeCategory.QUERY_RESOLUTION,
        )
```

```python id=impl-test-imports
# Apply to packages/ai-parrot/tests/memory/unified/test_manager.py — replace lines 2-7 (the import block) with:
import pytest
from unittest.mock import AsyncMock, MagicMock, create_autospec

from parrot.memory.unified.manager import UnifiedMemoryManager
from parrot.memory.unified.models import MemoryConfig
from parrot.memory.episodic.models import EpisodeCategory, EpisodeOutcome, MemoryNamespace
from parrot.memory.episodic.store import EpisodicMemoryStore
```

```python id=impl-test-fixture
# Apply to packages/ai-parrot/tests/memory/unified/test_manager.py — replace the `mock_episodic` fixture (lines 15-22) with:
@pytest.fixture
def mock_episodic() -> MagicMock:
    """Autospecced store: a call with keywords the real store lacks raises TypeError instead of passing silently."""
    store = create_autospec(EpisodicMemoryStore, instance=True)
    store.get_failure_warnings.return_value = "Warning: API rate limit hit"
    store.configure = AsyncMock()
    store.cleanup = AsyncMock()
    return store
```

```python id=impl-test-safe
# Apply to packages/ai-parrot/tests/memory/unified/test_manager.py — in test_record_interaction_safe replace line 75, which reads exactly:
#         mock_episodic.record_tool_episode.side_effect = Exception("Redis down")
# with:
        mock_episodic.record_episode.side_effect = Exception("Redis down")
```

```python id=impl-test-new
# Apply to packages/ai-parrot/tests/memory/unified/test_manager.py — insert as a new method of TestUnifiedMemoryManager
# immediately after test_record_interaction_safe (after line 82, before test_all_none_subsystems):
    @pytest.mark.asyncio
    async def test_record_interaction_calls_record_episode(self, namespace, mock_episodic):
        """record_interaction records ONE PARTIAL query episode via record_episode (FEAT-571 M0)."""
        manager = UnifiedMemoryManager(namespace=namespace, episodic_store=mock_episodic)
        await manager.record_interaction("what now?", "do this", [], "user1", "session1")
        mock_episodic.record_episode.assert_awaited_once()
        kwargs = mock_episodic.record_episode.await_args.kwargs
        assert kwargs["outcome"] == EpisodeOutcome.PARTIAL
        assert kwargs["category"] == EpisodeCategory.QUERY_RESOLUTION
        assert kwargs["situation"] == "what now?"
        assert "do this" in kwargs["action_taken"]
        assert kwargs["namespace"].user_id == "user1"
        assert kwargs["namespace"].session_id == "session1"
        mock_episodic.record_tool_episode.assert_not_called()
```

```python id=impl-real-store-test path=packages/ai-parrot/tests/memory/unified/test_manager_real_store.py
"""Regression tests: UnifiedMemoryManager records a REAL conversation episode (FEAT-571 M0, AC02).

These tests use a real ``EpisodicMemoryStore`` over an in-memory ``FAISSBackend`` — no
``AsyncMock`` of the store — so a signature mismatch between the manager and the store
surfaces as a failure instead of being swallowed by ``record_interaction``.
"""
from __future__ import annotations

from types import SimpleNamespace

import pytest

from parrot.memory.episodic.models import EpisodeCategory, EpisodeOutcome, MemoryNamespace
from parrot.memory.episodic.store import EpisodicMemoryStore
from parrot.memory.unified.manager import UnifiedMemoryManager

pytest.importorskip("faiss")

from parrot.memory.episodic.backends.faiss import FAISSBackend  # noqa: E402


@pytest.fixture
async def backend() -> FAISSBackend:
    be = FAISSBackend(dimension=8)
    await be.configure()
    return be


@pytest.fixture
def store(backend: FAISSBackend) -> EpisodicMemoryStore:
    return EpisodicMemoryStore(backend=backend, default_ttl_days=0)


@pytest.fixture
def namespace() -> MemoryNamespace:
    return MemoryNamespace(tenant_id="acme", agent_id="planner", room_id="room-7", crew_id="crew-3")


@pytest.fixture
def manager(namespace: MemoryNamespace, store: EpisodicMemoryStore) -> UnifiedMemoryManager:
    return UnifiedMemoryManager(namespace=namespace, episodic_store=store)


def _expected_filter(namespace: MemoryNamespace, user_id: str, session_id: str) -> dict:
    return MemoryNamespace(
        tenant_id=namespace.tenant_id,
        agent_id=namespace.agent_id,
        user_id=user_id,
        session_id=session_id,
        room_id=namespace.room_id,
        crew_id=namespace.crew_id,
    ).build_filter()


async def test_unified_records_real_episode(manager, backend, namespace) -> None:
    """A conversation turn is persisted as a PARTIAL QUERY_RESOLUTION episode with room/crew retained."""
    await manager.record_interaction("What is the rollout plan?", "Ship on Tuesday.", [], "u1", "s1")

    episodes = await backend.get_recent(_expected_filter(namespace, "u1", "s1"), limit=10)
    assert len(episodes) == 1
    episode = episodes[0]
    assert episode.outcome == EpisodeOutcome.PARTIAL
    assert episode.category == EpisodeCategory.QUERY_RESOLUTION
    assert episode.situation == "What is the rollout plan?"
    assert "Ship on Tuesday." in episode.action_taken
    assert (episode.room_id, episode.crew_id) == ("room-7", "crew-3")
    assert (episode.user_id, episode.session_id) == ("u1", "s1")
    assert 1 <= episode.importance <= 10
    assert episode.is_failure is False


async def test_record_episodic_does_not_raise_signature_error(manager) -> None:
    """Calling the private recorder directly surfaces any store-signature mismatch (nothing swallows it here)."""
    await manager._record_episodic("q", "a", [], "u2", "s2")


async def test_response_object_content_is_used(manager, backend, namespace) -> None:
    """Objects exposing ``.content`` are stringified through that attribute."""
    await manager.record_interaction("q", SimpleNamespace(content="structured answer"), [], "u3", "s3")
    episodes = await backend.get_recent(_expected_filter(namespace, "u3", "s3"), limit=10)
    assert len(episodes) == 1
    assert "structured answer" in episodes[0].action_taken


async def test_tool_calls_are_not_recorded_as_tool_episodes(manager, backend, namespace) -> None:
    """Tool calls passed to record_interaction are not proof of success and produce no extra episodes."""
    tool_calls = [SimpleNamespace(name="search", args={"q": "x"})]
    await manager.record_interaction("q", "a", tool_calls, "u4", "s4")
    episodes = await backend.get_recent(_expected_filter(namespace, "u4", "s4"), limit=10)
    assert len(episodes) == 1
    assert episodes[0].category == EpisodeCategory.QUERY_RESOLUTION
```

---

## Implementation Notes

### Key Constraints
- **No dynamics dependency**: nothing from `parrot.memory.dynamics` may be imported (it does not exist yet, and M0 must merge independently of the gates).
- **No review**: `record_episode` only; no grade, no exposure, no citation.
- **Keep the entry point**: `record_interaction` and `_record_episodic` signatures are unchanged; `LongTermMemoryMixin._post_response_memory_hook` keeps passing `tool_calls=[]`.
- **Real store in tests**: `AsyncMock()` of the whole store is insufficient (spec §3 M0); the FAISS backend runs in-memory (`persistence_path=None`) so no files are written.
- **Importance**: leave `importance=None` so `_auto_importance(PARTIAL)` applies (spec: "existing importance inference"); tests assert the 1..10 range, not the literal.
- Formatting: `black` (120 cols) on the three files; `ruff check` clean.

### References in Codebase
- `core/memory/episodic/mixin.py:464-481` — the sibling conversation recorder (`situation=query[:500]`, `action_taken=f"Responded: …"`) whose shape this repair mirrors, minus its hard-coded SUCCESS.
- `core/memory/unified/mixin.py:313-336` — the caller that today silently records nothing.

---

## Implementation Blueprint

> Design complete — the Delegation Contract blocks above **are** the blueprint. Apply them
> verbatim in the order below.

### Steps (in order)
1. Apply `impl-manager-import` then `impl-manager-body` — *why*: the enums must be imported before the body references them; the body is the actual bug fix (valid `record_episode` call, namespace keeps room/crew).
2. Apply `impl-test-imports`, `impl-test-fixture`, `impl-test-safe`, `impl-test-new` in that order — *why*: the autospec fixture is what makes the unit suite fail on invalid keywords from now on (AC02 "existing tests no longer mask the signature mismatch").
3. Write `impl-real-store-test` to its path — *why*: proves durable persistence with room/crew and PARTIAL/no-review semantics on a real store.
4. Run both validation commands, then `black --check` and `ruff check` on the three files — *why*: AC18.

### FILL IN checklist
- [ ] none — design complete (Delegation Contract, `design_complete: true`)

---

## Acceptance Criteria

- [ ] `_record_episodic` calls `record_episode(namespace=…, situation=query[:500], action_taken="Responded: …", outcome=PARTIAL, category=QUERY_RESOLUTION)` with `room_id`/`crew_id` from `self.namespace` (AC02)
- [ ] `record_tool_episode` signature untouched; no import from `parrot.memory.dynamics`
- [ ] `test_manager.py` uses `create_autospec(EpisodicMemoryStore, instance=True)`; all existing tests still pass; new kwargs test passes
- [ ] `test_manager_real_store.py` passes against a real FAISS-backed store: one persisted PARTIAL/QUERY_RESOLUTION episode, room/crew retained, `_record_episodic` raises nothing, tool calls add no episodes
- [ ] `black --check` and `ruff check` clean on the three files
- [ ] No memory review emitted anywhere in this change

---

## Validation Commands

- `pytest packages/ai-parrot/tests/memory/unified/test_manager.py -q`
- `pytest packages/ai-parrot/tests/memory/unified/test_manager_real_store.py -q`

---

## Test Specification

```python
# packages/ai-parrot/tests/memory/unified/test_manager.py (added)
async def test_record_interaction_calls_record_episode(self, namespace, mock_episodic): ...  # PARTIAL / QUERY_RESOLUTION kwargs; record_tool_episode never called

# packages/ai-parrot/tests/memory/unified/test_manager_real_store.py (new — full content in impl-real-store-test)
async def test_unified_records_real_episode(manager, backend, namespace): ...
async def test_record_episodic_does_not_raise_signature_error(manager): ...
async def test_response_object_content_is_used(manager, backend, namespace): ...
async def test_tool_calls_are_not_recorded_as_tool_episodes(manager, backend, namespace): ...
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** — §1 Problem Statement, §3 M0, §6 C1/C4, AC02
2. **Check dependencies** — none
3. **Verify the Codebase Contract** — re-check `manager.py:14`, `:385-400` and `test_manager.py:15-22`, `:75` still match; if the Delegation Contract hashes are stale, refresh the packet in this file first
4. **Update status** in `sdd/tasks/index/memory-dynamics.json` → `"in-progress"`
5. **Implement** by applying the seven blocks in order; never widen scope to the mixin or the store
6. **Verify** with the two validation commands plus `black --check` / `ruff check`
7. **Move this file** to `sdd/tasks/completed/TASK-3386-m0-unified-recording-repair.md`, update the index → `"done"`, fill the Completion Note

---

## Completion Note

**Completed by**: sdd-worker (orchestrated native `sonnet` delivery, via the task's
Delegation Contract — design-complete blueprint, all impl-* blocks applied verbatim)
**Date**: 2026-09-18
**Notes**: `UnifiedMemoryManager._record_episodic` repaired: it was calling
`EpisodicMemoryStore.record_tool_episode(query=, response=, tool_calls=)` — an overload
that does not exist (real signature is `record_tool_episode(namespace, tool_name,
tool_args, tool_result, ...)`), so every real-store call silently raised inside a
broad except and no episode was ever persisted (only the mock in the old test suite hid
this). Fixed to call `record_episode(namespace=ns, situation=query[:500],
action_taken=f"Responded: {response_text}", outcome=EpisodeOutcome.PARTIAL,
category=EpisodeCategory.QUERY_RESOLUTION)`, preserving room_id/crew_id in the namespace.
Hardened `test_manager.py`'s mock fixture with `create_autospec(EpisodicMemoryStore,
instance=True)` so an invalid-keyword regression raises `TypeError` instead of passing
silently (verified: calling the old broken signature against the autospec now raises
"missing a required argument: tool_name", proving the hardened fixture would have caught
the original bug). Added `test_manager_real_store.py` with a real `EpisodicMemoryStore`
over an in-memory `FAISSBackend` (4 tests) as the real-store regression test the task
required. All 15 tests pass (11 + 4) verified post-merge in the feature worktree. One
pre-existing `ruff` B905 finding at `manager.py:268` (inside `_get_episodic_warnings`,
untouched by this task) — not a regression, left for `/sdd-done`'s feature-wide lint pass.

**Deviations from spec**: none — the task's own file list already excluded `sdd/`
entirely (pure code repair), so no Option A relocation was needed here.

Seat: sonnet (native) · Backend: native · Model: sonnet · Attempts: 1 · Duration: ~906s ·
Tokens: n/a (native — usage not tracked by the engine)
