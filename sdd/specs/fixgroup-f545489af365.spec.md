---
type: feature
base_branch: dev
feature_id: FEAT-883
projects: [ai-parrot, ai-parrot-client-google]
tags: [voice, gemini-live, tests, ledger-fix]
discovered_from: issue:33b76e470d2b
docs:
  policy: none
  pages: []
  api_modules: []
---

# Feature Specification: Gemini Live envelope tests — match the AUDIO-mode role contract

**Feature ID**: FEAT-883
**Date**: 2026-11-12
**Author**: Jesus Lara
**Status**: approved
**Target version**: next patch

---

## 1. Motivation & Business Requirements

### Problem Statement

Ledger `issue:33b76e470d2b` (minor bug, discovered from `spec:BRIEF-otel-attribution`): two tests in
`packages/ai-parrot/tests/clients/test_live_envelope.py` fail —
`TestCanonicalRole::test_model_text_is_assistant` and `::test_mixed_turn_both_roles_present`. Every
response carries role `user` (or empty text); no assistant-role text appears.

Reproduced on `origin/dev` @ `37057bbb59` (2026-11-12), so the cause is not the brief's branch. Root cause
(read from source, confirmed by a prototype run):

- `GeminiLiveClient._build_live_config` defaults the response modality to AUDIO
  (`modalities = response_modalities or ["AUDIO"]`, live.py:643).
- In AUDIO mode, `stream_voice` deliberately treats `model_turn` text parts as the model's internal
  reasoning: it yields `LiveVoiceResponse(text="", metadata={"thinking": part.text}, role="assistant")`
  (live.py:866). The spoken words arrive as `output_transcription` frames, yielded as assistant text
  (live.py:929).
- The test helper `_text_response` builds a `model_turn` text frame and the tests call `stream_voice`
  without `response_modalities`, so they run in AUDIO mode. The text never reaches `.text`, and the
  `if r.text` filters find no assistant response.

The ledger's suspicion about the fixture model (`gemini-3.8-live`) is unrelated: the connection is faked.
The fixture predates the AUDIO-mode semantics the client documents in its own comments (live.py:777–783),
so the tests are stale. `live.py` behaves as intended and is not changed.

### Goals
- `test_live_envelope.py` passes on `dev`: assistant text in AUDIO mode is asserted through an
  `output_transcription` frame.
- Keep coverage of `model_turn` text: a TEXT-mode test asserts it is assistant text, and an AUDIO-mode
  test asserts it is surfaced only as `metadata["thinking"]` with empty `text`.

### Non-Goals (explicitly out of scope)
- No change to `GeminiLiveClient.stream_voice` or `_build_live_config` — the AUDIO-mode thinking
  suppression is the intended contract.
- No changes to other voice test files or to the BRIEF-otel-attribution branch.

---

## Governing Decisions

<!-- decision-audit: input_digest=sha256:aa94e83359b7a0026c32b22ff9aa493c97c3ef15b1d669febc4e2651fea20da4 evaluation_digest=sha256:99ff6d3e45b74b89ea17609573f608712c7b88b522078a7e0bcd44806cfa4518 rules_version=1 status=pass -->

## 2. Architectural Design

### Overview

Test-only fix in one file. Replace the ambiguous `_text_response` helper with two helpers named after
the frame they build:

- `_model_turn_text_response(text)` — a `server_content.model_turn` text part (same shape as today's
  `_text_response`).
- `_output_transcription_response(text)` — a `server_content.output_transcription` frame.

Then align `TestCanonicalRole` with the client's modality contract:

| Test | Mode | Frames | Assertion |
|---|---|---|---|
| `test_model_text_is_assistant` (kept, rewired) | AUDIO (default) | output transcription "Hello there" | some response has `role == "assistant"` and `text == "Hello there"` |
| `test_text_mode_model_turn_is_assistant` (new) | TEXT (`response_modalities=["TEXT"]`) | model_turn "Hello there" | some response has `role == "assistant"` and `text == "Hello there"` |
| `test_audio_mode_model_turn_is_thinking_only` (new) | AUDIO (default) | model_turn "planning the answer" | every response has empty `text`; some has `role == "assistant"` and `metadata["thinking"] == "planning the answer"` |
| `test_mixed_turn_both_roles_present` (kept, rewired) | AUDIO (default) | user transcription + output transcription | `{r.role for r in responses if r.text} == {"user", "assistant"}` |

`test_user_transcription_is_role_user`, `test_no_user_transcription_metadata`, `TestVoiceOverride` and
`TestGeminiCapabilitiesVoiceFlip` are untouched.

### Component Diagram
```
test_live_envelope.py ──fake session──→ GeminiLiveClient.stream_voice (unchanged)
   _model_turn_text_response        ──→ model_turn branch (TEXT: text / AUDIO: metadata["thinking"])
   _output_transcription_response   ──→ output_transcription branch (assistant text)
   _user_transcription_response     ──→ input_transcription branch (user text)
```

### Integration Points

| Existing Component | Integration Type | Notes |
|---|---|---|
| `GeminiLiveClient.stream_voice` | exercised by tests | `response_modalities` kwarg forwarded to `_build_live_config` (live.py:773) |
| `LiveVoiceResponse` | asserted on | `role` (voice.py:430), `metadata` (voice.py:438) |

### Data Models
None.

### New Public Interfaces
None (test helpers are module-private).

---

## 3. Module Breakdown

#### Delegation-eligible modules

| Module | Eligible? | Decided patterns / exact contracts | Why not (if no) |
|---|---|---|---|
| M1: envelope test realignment | yes | Exact diff fixed in §3 M1 and in the task blueprint; black-formatted (line 120) | — |

### Module 1: Envelope test realignment
- **Path**: `packages/ai-parrot/tests/clients/test_live_envelope.py`
- **Responsibility**: Make `TestCanonicalRole` assert the AUDIO/TEXT role contract of `stream_voice`.
- **Depends on**: existing `GeminiLiveClient` (unchanged)
- **Interface Skeleton** *(signatures + docstrings only)*:
  ```python
  # packages/ai-parrot/tests/clients/test_live_envelope.py  (modifies)
  def _model_turn_text_response(text: str):  # renames _text_response, verified: test_live_envelope.py:74
      """A ``model_turn`` text part.

      It is the model's reply in TEXT mode but its internal reasoning
      ("thinking") in the default AUDIO mode.
      """

  def _output_transcription_response(text: str):  # new; branch verified: live.py:929
      """An ``output_transcription`` frame: the model's spoken words in AUDIO mode."""

  class TestCanonicalRole:
      async def test_model_text_is_assistant(self, monkeypatch, client):  # verified: test_live_envelope.py:103
          """AUDIO mode (default): the spoken transcript is the assistant's text."""
      async def test_text_mode_model_turn_is_assistant(self, monkeypatch, client):  # new
          """TEXT mode: ``model_turn`` text is the reply and carries role="assistant"."""
      async def test_audio_mode_model_turn_is_thinking_only(self, monkeypatch, client):  # new; verified: live.py:866
          """AUDIO mode: ``model_turn`` text is thinking — metadata only, never response text."""
      async def test_mixed_turn_both_roles_present(self, monkeypatch, client):  # verified: test_live_envelope.py:121
          ...
  ```

---

## 4. Test Specification

### Unit Tests
| Test | Module | Description |
|---|---|---|
| `TestCanonicalRole::test_model_text_is_assistant` | M1 | AUDIO-mode output transcription is assistant text |
| `TestCanonicalRole::test_text_mode_model_turn_is_assistant` | M1 | TEXT-mode model_turn text is assistant text |
| `TestCanonicalRole::test_audio_mode_model_turn_is_thinking_only` | M1 | AUDIO-mode model_turn text only in `metadata["thinking"]` |
| `TestCanonicalRole::test_mixed_turn_both_roles_present` | M1 | user + assistant roles both present in one AUDIO turn |

### Integration Tests
| Test | Description |
|---|---|
| — | none; the module is itself a fake-session integration test of `stream_voice` |

### Validation Contract

tests:
- packages/ai-parrot/tests/clients/test_live_envelope.py
markers: none

### Test Data / Fixtures

Fake Live session helpers already in the file (`_FakeLiveSession`, `_mock_client`,
`_empty_audio_iterator`) — reused, not changed.

---

## 5. Acceptance Criteria

- [ ] `pytest packages/ai-parrot/tests/clients/test_live_envelope.py` passes (13 tests) with
      `PYTHONPATH=packages/ai-parrot/src:packages/ai-parrot-client-google/src` from the worktree.
- [ ] `_text_response` no longer exists in the file; both new helpers do.
- [ ] `packages/ai-parrot-client-google/src/parrot/clients/google/live.py` is unchanged in the feature diff.
- [ ] `ruff check` and `black --check` (line length 120) pass on the changed file.

---

## 6. Codebase Contract

### Verified Imports
```python
from parrot.clients.google.live import GeminiLiveClient  # verified: test_live_envelope.py:13
```

### Existing Class Signatures
```python
# packages/ai-parrot-client-google/src/parrot/clients/google/live.py
class GeminiLiveClient(...):  # line 328
    def _build_live_config(self, system_prompt=None, response_modalities: Optional[List[str]] = None,
                           stt_only: bool = False, ...)  # line 572; AUDIO default at line 643
    async def stream_voice(self, audio_iterator: AsyncIterator[bytes], system_prompt=None, session_id=None,
                           user_id=None, stt_only: bool = False, options=None, **kwargs)
        -> AsyncIterator[LiveVoiceResponse]  # line 693
        # line 773: response_modalities=kwargs.get("response_modalities")
        # line 783: is_audio_mode = not stt_only and "AUDIO" in (live_config.response_modalities or [])
        # line 866: AUDIO-mode model_turn text → LiveVoiceResponse(text="", metadata={"thinking": ...}, role="assistant")
        # line 913: input_transcription → role="user" text
        # line 929: output_transcription → role="assistant" text

# packages/ai-parrot/src/parrot/models/voice.py
class LiveVoiceResponse:  # line 398
    text: str = ""
    role: Optional[str] = None  # line 430
    metadata: Dict[str, Any] = field(default_factory=dict)  # line 438
```

### Integration Points
| New Component | Connects To | Via | Verified At |
|---|---|---|---|
| `_output_transcription_response` | `stream_voice` output_transcription branch | `server_content.output_transcription.text` | `live.py:929` |
| `test_text_mode_model_turn_is_assistant` | `_build_live_config(response_modalities=...)` | `stream_voice(..., response_modalities=["TEXT"])` | `live.py:773`, `live.py:643` |

### Does NOT Exist (Anti-Hallucination)
- ~~`GeminiLiveClient(response_modalities=...)` constructor argument~~ — modality is per call, via the
  `stream_voice` kwarg.
- ~~a `thinking` field on `LiveVoiceResponse`~~ — thinking text lives in `metadata["thinking"]`.
- ~~`server_content.output_transcription` in the existing test helpers~~ — no helper builds it today.

### Edit Sites (Blueprint Anchors)

Verified against: `37057bbb59`

| File | Action | Verbatim anchor line | Verified at | Occurrences |
|---|---|---|---|---|
| `packages/ai-parrot/tests/clients/test_live_envelope.py` | MODIFY | `def _text_response(text: str):` | `test_live_envelope.py:74` | 1 |
| `packages/ai-parrot/tests/clients/test_live_envelope.py` | MODIFY | `async def test_model_text_is_assistant(self, monkeypatch, client):` | `test_live_envelope.py:103` | 1 |
| `packages/ai-parrot/tests/clients/test_live_envelope.py` | MODIFY | `_text_response("It's sunny"),` | `test_live_envelope.py:127` | 1 |

---

## 7. Implementation Notes & Constraints

### Patterns to Follow
- Keep the existing `SimpleNamespace` frame style and the `@pytest.mark.asyncio` markers.
- Format with `black` (line length 120, `target-version = ["py311", "py312"]` from the root `pyproject.toml`).

### Known Risks / Gotchas
- In a worktree the shared venv imports the main checkout; run pytest with
  `PYTHONPATH=packages/ai-parrot/src:packages/ai-parrot-client-google/src`.
- `_model_turn_text_response(` contains `_text_response(` as a substring — check for the old name with a
  word boundary (`\b_text_response\(`).

### External Dependencies
None.

---

## Consequences

<!-- decision-audit: input_digest=sha256:aa94e83359b7a0026c32b22ff9aa493c97c3ef15b1d669febc4e2651fea20da4 evaluation_digest=sha256:99ff6d3e45b74b89ea17609573f608712c7b88b522078a7e0bcd44806cfa4518 rules_version=1 status=pass -->

Audit status: `pass` (exit 0)

Findings:
- none

Diagnostics:
- `SPEC_BLOCK_MISSING`; path: /tmp/claude-1000/-home-jesuslara-proyectos-ai-parrot/8d3438e6-5d3f-4982-bd70-95a45fe93b36/scratchpad/dev-clone/sdd/specs/fixgroup-f545489af365.spec.md; message: no fenced yaml block under '## Decisions'

Coverage:
- Subsystems: bots, clients, config, flows, knowledge-graphindex, knowledge-pageindex, knowledge-wiki, memory, skills, tools
- Unmapped tags: gemini-live, ledger-fix, tests, voice
- Targets resolved: 0/0
- Impact complete: true
- Inventory complete: true
- Omitted ids: not recorded

```json
{
  "coverage": {
    "impact_complete": true,
    "inventory_complete": true,
    "omitted_ids": [],
    "subsystems": [
      "bots",
      "clients",
      "config",
      "flows",
      "knowledge-graphindex",
      "knowledge-pageindex",
      "knowledge-wiki",
      "memory",
      "skills",
      "tools"
    ],
    "targets_resolved": 0,
    "targets_total": 0,
    "unmapped_tags": [
      "gemini-live",
      "ledger-fix",
      "tests",
      "voice"
    ]
  },
  "diagnostics": [
    {
      "code": "SPEC_BLOCK_MISSING",
      "decision_id": null,
      "message": "no fenced yaml block under '## Decisions'",
      "path": "/tmp/claude-1000/-home-jesuslara-proyectos-ai-parrot/8d3438e6-5d3f-4982-bd70-95a45fe93b36/scratchpad/dev-clone/sdd/specs/fixgroup-f545489af365.spec.md"
    }
  ],
  "evaluation_digest": "sha256:99ff6d3e45b74b89ea17609573f608712c7b88b522078a7e0bcd44806cfa4518",
  "exit_code": 0,
  "findings": [],
  "input_digest": "sha256:aa94e83359b7a0026c32b22ff9aa493c97c3ef15b1d669febc4e2651fea20da4",
  "snapshot": {
    "approvals_digest": "6e5b5a5fb07d04ec7e7cdbf3afac1a634711ea195aa4061a8261bcf61b19992f",
    "config_digest": "sha256:a6bce9c0800713c30eaa78146ad0c06399f6ec0e9b083129e494abb6fd073343",
    "inventory": {
      "adr:doc:171b17ccd26bdbd2d71040746b22371a335d364d": "b22c79daae2a187f2091ea23449825e8769e2c07",
      "adr:doc:34394c36f5bf140678b8e17d43c3628e3d2c1440": "3fa15352d0e9ed972bd5de7ac1fd60e06906e60b",
      "adr:doc:666d8f740c695673063f76777db7b7b0e9d95a2e": "47f1bebe56724843f6c0981f67bbba72917b4b0b",
      "adr:doc:87781d348dff80cbfb25c253989a8940badd08d1": "49458f64f4bb614a9ff42750b53d9caa806f81a0",
      "adr:doc:89e808b78adee5c727e047ac239817bfd29e5cfe": "9feeb90ec52cb53395d978a3b946323a7b9072ab",
      "adr:doc:96dabb33251cd210186d7ab5c456ded102a4b025": "b537050f62f77a85b651af8c2595f4dc7fd4cebe",
      "adr:doc:c3c29b415ba46e730ee37c6fc520914a1905d022": "0cd9cc9f082b9d988da023e3886d310f8eed8eae",
      "adr:doc:c6b0e17a26d4b1ae2be8569a33db9a3aeedc0fbd": "804496ec336c99570df5502580ff980a38f56bfc",
      "adr:doc:e7c5ae770b06db3b35cdd4cba93001a58bfa7bef": "394f4656c71618a256427d81350fdc32335fa791"
    },
    "rules_version": 1,
    "structural_revision": "sha256:b11fe8e33d80455017c18de7c66615b790b28eae29c88d3cc6defc398db393fb",
    "taxonomy_digest": "65548b9a71329b13ab44f4904dff99814e1aac0da4bb2b58171a7201e3a9ba39"
  },
  "status": "pass"
}
```

## 8. Open Questions

- [x] Fix the test or `live.py`? — *Resolved (Jesus Lara via /sdd-fix triage)*: the test. AUDIO-mode
  thinking suppression is intended and documented in `stream_voice` (live.py:777–783).

---

## 9. Design Research Cross-Check

> Model: — · Status: skipped (no accepted exploration document; spec authored by /sdd-fix from a ledger issue)

| # | Suggestion (kind) | Disposition | Reason | Landed in |
|---|---|---|---|---|

Summary: **0** confirmed · **0** rejected · **0** escalated.

---

## 10. Documentation

- **Policy**: `none` — test-only change; no runtime behavior or public API changes.
- **Pages**: none.
- **API modules**: none.

---

## Worktree Strategy

One feature worktree `feat-FEAT-883-fixgroup-f545489af365` off `origin/dev`.

- Module graph: one module, no edges.
- Shared files: none.
- Exclusive resources: none.
- Cross-feature: none. The BRIEF-otel-attribution branch touches `live.py` (telemetry only), not this test.

---

## Revision History

| Version | Date | Author | Change |
|---|---|---|---|
| 0.1 | 2026-11-12 | Jesus Lara | Created by /sdd-fix from `issue:33b76e470d2b` (fixgroup:f545489af365) |
