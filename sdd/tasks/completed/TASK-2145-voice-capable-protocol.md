# TASK-2145: VoiceCapable Protocol

**Feature**: FEAT-416 — Voice Agent Framework
**Spec**: `sdd/specs/voice-agent-framework.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: S (< 2h)
**Depends-on**: none
**Assigned-to**: unassigned

---

## Context

AI-Parrot has two voice-capable clients (`GeminiLiveClient`, `NovaAudio`
mixin) that both implement `stream_voice()` with compatible signatures, but
there is no shared type-check target. `VoiceBot._create_llm_client()`
returns `AbstractClient` and calls `.stream_voice()` without type safety —
a non-voice provider silently fails at runtime.

This task creates the `VoiceCapable` typing.Protocol so voice clients can
be verified at type-check time and runtime.

Implements spec §3 Module 1.

---

## Scope

- Create `parrot/clients/protocols.py` with a `VoiceCapable` Protocol
  declaring `stream_voice()`.
- Use `@runtime_checkable` so `isinstance(client, VoiceCapable)` works.
- Write unit tests verifying GeminiLiveClient and NovaClient satisfy the
  protocol, and a plain AbstractClient subclass does NOT.

**NOT in scope**: modifying `AbstractClient` (VoiceCapable is a separate
Protocol, not a new ABC method), modifying any client class, or adding
voice to `__init__.py` exports.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `parrot/clients/protocols.py` | CREATE | `VoiceCapable` Protocol definition |
| `tests/bots/test_voice_capable_protocol.py` | CREATE | Protocol satisfaction tests |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports

```python
from parrot.clients.live import LiveVoiceResponse       # verified: live.py:156
from parrot.clients.live import GeminiLiveClient         # verified: live.py:488
from parrot.clients.nova import NovaClient               # verified: nova/__init__.py:11
from parrot.clients.base import AbstractClient           # verified: base.py:253
```

### Existing Signatures to Use

```python
# parrot/clients/live.py:729
async def stream_voice(
    self,
    audio_iterator: AsyncIterator[bytes],
    system_prompt: Optional[str] = None,
    session_id: Optional[str] = None,
    user_id: Optional[str] = None,
    stt_only: bool = False,
    **kwargs,
) -> AsyncIterator[LiveVoiceResponse]: ...

# parrot/clients/nova/audio.py:613
async def stream_voice(
    self,
    audio_iterator: AsyncIterator[bytes],
    system_prompt: Optional[str] = None,
    session_id: Optional[str] = None,
    user_id: Optional[str] = None,
    **kwargs,
) -> AsyncIterator[LiveVoiceResponse]: ...

# parrot/clients/anthropic_backends.py:39 — reference pattern
# Uses typing.Protocol with @runtime_checkable (AnthropicBackendProtocol)
```

### Does NOT Exist

- ~~`parrot.clients.protocols`~~ — does not exist yet; must be created
- ~~`VoiceCapable`~~ — does not exist anywhere in the codebase
- ~~`AbstractClient.stream_voice()`~~ — NOT defined on the base class

---

## Implementation Notes

### Pattern to Follow

```python
# Follow the AnthropicBackendProtocol pattern in anthropic_backends.py:39
from typing import Protocol, runtime_checkable, AsyncIterator, Optional

@runtime_checkable
class VoiceCapable(Protocol):
    """Protocol for clients that support bidirectional voice streaming."""

    async def stream_voice(
        self,
        audio_iterator: AsyncIterator[bytes],
        system_prompt: Optional[str] = None,
        session_id: Optional[str] = None,
        user_id: Optional[str] = None,
        **kwargs,
    ) -> AsyncIterator[LiveVoiceResponse]: ...
```

### Key Constraints

- The Protocol must use the **common** parameter set (no `stt_only` in the
  Protocol — that's Gemini-specific and passed via `**kwargs` by others).
- `@runtime_checkable` is required for `isinstance()` checks.
- Do NOT add `close()` or `disconnect()` to the Protocol — resolved in spec
  Q1: keep VoiceCapable minimal.

---

## Acceptance Criteria

- [ ] `parrot/clients/protocols.py` exists with `VoiceCapable` Protocol
- [ ] `isinstance(GeminiLiveClient(...), VoiceCapable)` returns `True`
- [ ] `isinstance(NovaClient(...), VoiceCapable)` returns `True`
- [ ] A plain `AbstractClient` subclass without `stream_voice()` does NOT satisfy VoiceCapable
- [ ] All tests pass: `pytest tests/bots/test_voice_capable_protocol.py -v`
- [ ] No linting errors: `ruff check parrot/clients/protocols.py`

---

## Test Specification

```python
# tests/bots/test_voice_capable_protocol.py
import pytest
from parrot.clients.protocols import VoiceCapable


class TestVoiceCapableProtocol:
    def test_gemini_satisfies_protocol(self):
        """GeminiLiveClient structurally satisfies VoiceCapable."""
        from parrot.clients.live import GeminiLiveClient
        assert issubclass(GeminiLiveClient, VoiceCapable)

    def test_nova_satisfies_protocol(self):
        """NovaClient (via NovaAudio mixin) satisfies VoiceCapable."""
        from parrot.clients.nova import NovaClient
        assert issubclass(NovaClient, VoiceCapable)

    def test_plain_client_rejected(self):
        """A client without stream_voice() does NOT satisfy VoiceCapable."""
        from parrot.clients.base import AbstractClient
        # AbstractClient itself does not define stream_voice()
        assert not issubclass(AbstractClient, VoiceCapable)
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at `sdd/specs/voice-agent-framework.spec.md` for full context
2. **Check dependencies** — none for this task
3. **Verify the Codebase Contract** — confirm imports and signatures still match
4. **Create** `parrot/clients/protocols.py` with the VoiceCapable Protocol
5. **Write tests** in `tests/bots/test_voice_capable_protocol.py`
6. **Run** `pytest tests/bots/test_voice_capable_protocol.py -v`
7. **Update status** in per-spec index → `"in-progress"` then `"done"`
8. **Move this file** to `sdd/tasks/completed/`

---

## Completion Note

Implemented exactly as specified:

- Created `packages/ai-parrot/src/parrot/clients/protocols.py` (actual repo
  path — the codebase root is `packages/ai-parrot/src/parrot/`, not a
  top-level `parrot/`; contract paths in the spec/task are relative to
  that root) with `@runtime_checkable class VoiceCapable(Protocol)`
  declaring only `stream_voice()` with the common parameter set, matching
  the `AnthropicBackendProtocol` pattern verified at
  `anthropic_backends.py:39`.
- Created `packages/ai-parrot/tests/bots/test_voice_capable_protocol.py`
  exactly per the task's Test Specification.
- Lint: `ruff check --select=E,F,W,C,B` passes (bare `ruff check` flags
  `UP035`/`UP045` pyupgrade rules that contradict this codebase's own
  `Optional[X]`/`typing.AsyncIterator` convention used throughout
  `live.py`; the project's configured linter is `.flake8`, which does not
  enable those rules — `flake8` itself is not installed in either project
  venv, so the equivalent `ruff --select` subset was used instead).

**Environment limitation (pre-existing, not introduced by this task):**
this sandbox's Python venvs (`.venv`, `.venv12`) ship with native/compiled
extensions stripped across a wide swath of third-party dependencies
(`pydantic_core`, `python-datamodel`, `orjson`, `asyncpg`,
`psycopg2-binary`, `numpy`/`pandas`, and the internal `navconfig` package
all failed to import with `ModuleNotFoundError` on their compiled
submodules). I reinstalled the first several (pydantic-core, datamodel,
orjson, asyncpg, psycopg2-binary, numpy, pandas) to try to unblock
`import parrot.clients.live`, but the cascade continued into
`navconfig.utils.functions` (a private internal package) and I stopped
there — full remediation is out of scope for this feature and risks
disrupting other concurrent sessions sharing the same venvs. As a result
**`pytest` could not be executed** for this or any other task's tests in
this session. This mirrors the pre-existing, documented limitation in
`tests/bots/test_voicebot_nova_wiring.py` (`parrot.bots` unimportable due
to an unbuilt Cython extension) but is broader in this session.
Recommend running
`pytest packages/ai-parrot/tests/bots/test_voice_capable_protocol.py -v`
in a fully-provisioned environment before merge.
