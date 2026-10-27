# TASK-4620: `speech_report` + `google_tts` verbatim zero-LLM-calls test

**Feature**: FEAT-726 — Configure-Override Idempotency & `speech_report` Hardening
**Spec**: `sdd/specs/bots-agent-tech-debt.spec.md`
**Status**: pending
**Priority**: low
**Estimated effort**: S (< 2h)
**Depends-on**: TASK-4619
**Assigned-to**: unassigned

**Discovered-from**: `issue:b858ae4ad636`

---

## Context

Implements spec §3 Module 5, closing `issue:b858ae4ad636` — a coverage gap
deferred from FEAT-591's adversarial code review.

`speech_report`'s verbatim mode is supposed to route straight to TTS and make
**zero** LLM calls. Two of the three non-Gemini backends have an agent-level
test asserting that through `speech_report` itself:

- `supertonic` — `test_speech_report_verbatim_supertonic_zero_llm_calls`
  (`tests/test_basic_agent_new.py:351`)
- `aws_polly` — covered by the Polly extension test

`google_tts` is covered only at the **backend unit** level
(`test_google_backend.py`), never exercised through `speech_report()`. The
routing code is backend-agnostic so the risk is low, which is why this is a
`low`-severity tech-debt item rather than a bug — but the asymmetry means a
regression in `google_tts`'s route through `speech_report` would be caught for
two backends and missed for the third.

This task is test-only. No source file changes.

**Depends-on note**: depends on TASK-4619 only because both append to
`packages/ai-parrot/tests/test_basic_agent_new.py`. There is no logical
dependency.

---

## Scope

- Add `test_speech_report_verbatim_google_tts_zero_llm_calls` to
  `packages/ai-parrot/tests/test_basic_agent_new.py`, mirroring the existing
  supertonic test.

**NOT in scope**:
- Any change to `packages/ai-parrot/src/parrot/bots/agent.py`. This task is
  test-only; if the test fails, report it rather than changing the source —
  a real `google_tts` routing defect is a new ledger issue, not a silent fix
  inside a coverage task.
- Backend-level tests in `test_google_backend.py` — already covered.
- The empty-`speakers` guard — TASK-4619.
- Any `configure()` work — TASK-4616/4617/4618.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/tests/test_basic_agent_new.py` | MODIFY | add the google_tts verbatim zero-LLM-calls test |

---

## Codebase Contract (Anti-Hallucination)

> Verified at `36b9847aa`. Anchor re-confirmed `grep -c` = 1.

### Verified Imports

Already present at the top of `tests/test_basic_agent_new.py` — reuse them, add
nothing:

```python
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
```

### Existing Signatures to Use

```python
# packages/ai-parrot/src/parrot/bots/agent.py — verified constants
SpeechBackend = Literal["gemini", "google_tts", "supertonic", "aws_polly"]        # line 32
_SPEECH_TO_TTS_BACKEND = {"google_tts": "google", "supertonic": "supertonic", "aws_polly": "polly"}  # line 35
_NATIVE_MIME = {"google": "audio/wav", "supertonic": "audio/wav", "polly": "audio/mpeg"}             # line 36
_MIME_EXT = {"audio/wav": "wav", "audio/mpeg": "mp3", "audio/ogg": "ogg", "audio/pcm": "pcm"}        # line 37

class BasicAgent(Chatbot, NotificationMixin):
    async def _synthesize_with_backend(self, text: str, backend: str, output_directory: Path) -> Path:
        tts_backend = _SPEECH_TO_TTS_BACKEND[backend]     # maps "google_tts" -> "google"
        # imports parrot.voice.tts.models.TTSConfig and
        #         parrot.voice.tts.synthesizer.get_shared_synthesizer
        # mime_format = self.speech_format or _NATIVE_MIME[tts_backend]   -> "audio/wav" for google

    @staticmethod
    def _to_speakable(text, *, strip_speaker_labels: bool = False) -> str:   # line 674

    async def speech_report(self, report: str, ..., tts_backend=None, speech_mode=None, **kwargs) -> Dict[str, Any]:  # line 736
```

The test to mirror, verbatim (read it before writing anything):

```python
# packages/ai-parrot/tests/test_basic_agent_new.py:350-376 (verified)
@pytest.mark.asyncio
async def test_speech_report_verbatim_supertonic_zero_llm_calls(mock_agent_deps, tmp_path):
    """Non-Gemini verbatim synthesis bypasses all LLM calls."""
    from parrot.bots.agent import BasicAgent

    agent = BasicAgent(name="Podcaster")
    result = MagicMock(audio=b"wav", mime_format="audio/wav")
    synthesizer = MagicMock()
    synthesizer.synthesize = AsyncMock(return_value=result)

    with patch(
        "parrot.voice.tts.synthesizer.get_shared_synthesizer",
        AsyncMock(return_value=synthesizer),
    ):
        response = await agent.speech_report(
            report="# Heading\n\n**Plain** report",
            tts_backend="supertonic",
            speech_mode="verbatim",
            directory=tmp_path,
            output_directory=tmp_path,
        )

    mock_agent_deps.create_conversation_script.assert_not_awaited()
    mock_agent_deps.generate_speech.assert_not_awaited()
    synthesizer.synthesize.assert_awaited_once_with("Heading\n\nPlain report", language=None)
    assert response["script_path"].read_text() == "Heading\n\nPlain report"
    assert response["podcast_path"].suffix == ".wav"
```

### Does NOT Exist

- ~~`tts_backend="google"`~~ — the **`speech_report` selector** is
  `"google_tts"` (`SpeechBackend`, `agent.py:32`). `"google"` is the internal
  *TTS* backend name it maps to via `_SPEECH_TO_TTS_BACKEND` (`agent.py:35`).
  Passing `"google"` to `speech_report` is invalid — `_resolve_speech_route`
  validates against `("gemini", "google_tts", "supertonic", "aws_polly")`
  (`agent.py:665`).
- ~~`_NATIVE_MIME["google_tts"]`~~ — the dict is keyed by the *TTS* name;
  `_NATIVE_MIME` has `"google"`, not `"google_tts"`. The mapping at
  `agent.py:35` is applied first, so there is **no** `KeyError` here — do not
  "fix" it.
- ~~a `mock_agent_deps.synthesize` attribute~~ — the synthesizer is patched in
  via `parrot.voice.tts.synthesizer.get_shared_synthesizer`, not taken from the
  fixture.
- ~~`tests/test_google_backend.py` needing changes~~ — the backend unit level is
  already covered; this task adds the agent-level test only.

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {
      "path": "packages/ai-parrot/tests/test_basic_agent_new.py",
      "action": "MODIFY"
    }
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot/src/parrot/bots/agent.py#BasicAgent.speech_report",
    "sym:packages/ai-parrot/src/parrot/bots/agent.py#BasicAgent._synthesize_with_backend",
    "sym:packages/ai-parrot/src/parrot/bots/agent.py#BasicAgent._to_speakable"
  ]
}
```

---

## Implementation Notes

### Key Constraints

- **Mirror the supertonic test, do not invent a new shape.** The point of the
  issue is symmetry between the three backends' agent-level coverage; a test
  written differently does not close the asymmetry it reports.
- `tts_backend="google_tts"` (the `speech_report` selector), `speech_mode="verbatim"`.
- The expected extension is `.wav`: `google_tts` → `"google"`
  (`_SPEECH_TO_TTS_BACKEND`) → `_NATIVE_MIME["google"] == "audio/wav"` →
  `_MIME_EXT["audio/wav"] == "wav"`.
- **The zero-LLM-calls assertions are the substance of the test.** Keep both
  `create_conversation_script.assert_not_awaited()` and
  `generate_speech.assert_not_awaited()` — those two are what "zero LLM calls"
  means here.
- Offline only: no real Google TTS client, no network, no credentials. Patch
  `parrot.voice.tts.synthesizer.get_shared_synthesizer` exactly as the
  supertonic test does.
- Use `tmp_path` for both `directory` and `output_directory` so nothing is
  written into `STATIC_DIR`.
- `ruff check --fix`; 120-column lines.

### References in Codebase

- `packages/ai-parrot/tests/test_basic_agent_new.py:350-376` — the test to mirror
- `packages/ai-parrot/src/parrot/bots/agent.py:32-37` — the backend/MIME mapping chain
- `packages/ai-parrot/src/parrot/bots/agent.py:690-722` — `_synthesize_with_backend`

---

## Implementation Blueprint

### Steps (in order)

1. Confirm TASK-4619 is `done` — *why*: it appends to this same test file;
   running concurrently conflicts.
2. Read `test_basic_agent_new.py:350-376` — *why*: this task is "the same test
   with a different backend", and the fixture/patch wiring must match exactly.
3. Append the new test directly below the supertonic one — *why*: keeping the
   three backend tests adjacent is what makes the coverage symmetry visible to
   the next reader.
4. Run the Validation Commands — *why*: a green run through `speech_report` with
   `google_tts` is the evidence that closes `issue:b858ae4ad636`.

### `packages/ai-parrot/tests/test_basic_agent_new.py` (MODIFY)

```python
# occurrences: 1 (verified: grep -c 'async def test_speech_report_verbatim_supertonic_zero_llm_calls(mock_agent_deps, tmp_path):' packages/ai-parrot/tests/test_basic_agent_new.py)
# AFTER — append below the END of the test that starts at
# `async def test_speech_report_verbatim_supertonic_zero_llm_calls(...)`
# (test_basic_agent_new.py:351; its body ends at the `.suffix == ".wav"` assert),
# and ABOVE `async def test_speech_report_script_mode_single_narrator(...)`.


@pytest.mark.asyncio
async def test_speech_report_verbatim_google_tts_zero_llm_calls(mock_agent_deps, tmp_path):
    """google_tts verbatim synthesis bypasses all LLM calls.

    Closes issue:b858ae4ad636 — google_tts was covered only at the backend unit
    level (test_google_backend.py), never through speech_report() itself, while
    supertonic and aws_polly both had an agent-level zero-LLM-calls test.
    """
    from parrot.bots.agent import BasicAgent

    agent = BasicAgent(name="Podcaster")
    result = MagicMock(audio=b"wav", mime_format="audio/wav")
    synthesizer = MagicMock()
    synthesizer.synthesize = AsyncMock(return_value=result)

    with patch(
        "parrot.voice.tts.synthesizer.get_shared_synthesizer",
        AsyncMock(return_value=synthesizer),
    ):
        response = await agent.speech_report(
            report="# Heading\n\n**Plain** report",
            tts_backend="google_tts",
            speech_mode="verbatim",
            directory=tmp_path,
            output_directory=tmp_path,
        )

    mock_agent_deps.create_conversation_script.assert_not_awaited()
    mock_agent_deps.generate_speech.assert_not_awaited()
    # FILL IN: assert the synthesizer was awaited once with the speakable text.
    # Confirm the expected text by reading BasicAgent._to_speakable (agent.py:674)
    # — the supertonic test expects "Heading\n\nPlain report" for this same input,
    # so it should match; verify rather than assume
    # — bounded by AC "asserts zero LLM calls and one TTS synthesis"
    # FILL IN: assert the TTSConfig the synthesizer was built with carries
    # backend "google" (NOT "google_tts") — this is the one behaviour that differs
    # from the supertonic test and the reason the mapping at agent.py:35 exists.
    # Inspect the get_shared_synthesizer call args to reach the TTSConfig
    # — bounded by AC "the google_tts -> google mapping is exercised"
    assert response["script_path"].read_text() == "Heading\n\nPlain report"
    assert response["podcast_path"].suffix == ".wav"
```

**Why this shape**: it is deliberately the supertonic test with
`tts_backend="google_tts"`, because the issue is about *symmetry* of agent-level
coverage. The one added assertion — that the resolved TTS backend is `"google"`
— is what makes this test more than a copy: it pins the
`_SPEECH_TO_TTS_BACKEND` mapping that the supertonic case (where selector and
backend name are identical) cannot exercise. Do not rename the test; the issue
and the spec both refer to it by this name.

### FILL IN checklist

- [ ] `test_speech_report_verbatim_google_tts_zero_llm_calls` — the `synthesizer.synthesize` await assertion, expected text verified against `_to_speakable`; bounded by AC "zero LLM calls and one TTS synthesis"
- [ ] `test_speech_report_verbatim_google_tts_zero_llm_calls` — the assertion that the `TTSConfig` backend is `"google"`, reached via the `get_shared_synthesizer` call args; bounded by AC "the google_tts → google mapping is exercised"

---

## Acceptance Criteria

- [ ] `test_speech_report_verbatim_google_tts_zero_llm_calls` exists in
      `packages/ai-parrot/tests/test_basic_agent_new.py`, directly below the
      supertonic test.
- [ ] It drives `speech_report(tts_backend="google_tts",
      speech_mode="verbatim", ...)` — the agent-level entry point, not the
      backend unit.
- [ ] It asserts **zero** LLM calls: both
      `create_conversation_script.assert_not_awaited()` and
      `generate_speech.assert_not_awaited()`.
- [ ] It asserts exactly one TTS synthesis, with the speakable text.
- [ ] It asserts the resolved TTS backend is `"google"`, exercising
      `_SPEECH_TO_TTS_BACKEND` (`agent.py:35`).
- [ ] It asserts the produced `podcast_path` suffix is `.wav`.
- [ ] Fully offline — no network, no credentials, nothing written outside
      `tmp_path`.
- [ ] **No source file is modified** by this task.
- [ ] `test_speech_report_verbatim_supertonic_zero_llm_calls` and the rest of
      the file still pass.
- [ ] `ruff check` clean.

---

## Validation Commands

- `pytest packages/ai-parrot/tests/test_basic_agent_new.py -q`
- `pytest packages/ai-parrot/tests/test_basic_agent_new.py::test_speech_report_verbatim_google_tts_zero_llm_calls -q`

---

## Test Specification

See the Implementation Blueprint — this task *is* a test. Run inside the
worktree with `PYTHONPATH=packages/ai-parrot/src`.

---

## Agent Instructions

When you pick up this task:

1. **Work in the feature worktree** — never on `dev`
   (`python -m scripts.sdd.ensure_worktree --slug bots-agent-tech-debt --feature-id FEAT-726`)
2. **Read the spec** at `sdd/specs/bots-agent-tech-debt.spec.md` (§3 Module 5)
3. **Check dependencies** — TASK-4619 must be `"done"` in
   `sdd/tasks/index/bots-agent-tech-debt.json` (same test file)
4. **Verify the Codebase Contract** — re-run the `grep -c`; TASK-4619 has just
   appended to this file, so line numbers shift while the anchor stays stable
5. **Update status** in `sdd/tasks/index/bots-agent-tech-debt.json` →
   `"in-progress"` (set `started_at`) and commit only that index file
6. **Implement** from the Implementation Blueprint; complete every `# FILL IN:`
7. **Verify** the acceptance criteria — run the Validation Commands. If the test
   fails for a reason in the source, STOP and report it — do not change
   `agent.py` under this task
8. **Commit the code** — stage only the one file this task lists
9. **Close the task** with
   `scripts/sdd/close_task.sh TASK-4620 bots-agent-tech-debt verified`
10. **Fill in the Completion Note** below, then commit the staged SDD state

---

## Completion Note

Test-only, as scoped — no source file touched.

Mirrors `test_speech_report_verbatim_supertonic_zero_llm_calls`, with both
zero-LLM assertions (`create_conversation_script` and `generate_speech` not
awaited), the single `synthesizer.synthesize` await, and the `.wav` suffix.

The one assertion beyond a copy is the resolved backend: the patched
`get_shared_synthesizer`'s `await_args.args[0]` is the `TTSConfig`, and its
`backend` is `"google"` while the `speech_report` selector is `"google_tts"`.
That pins `_SPEECH_TO_TTS_BACKEND` (`agent.py:35`), which the supertonic twin
cannot exercise because its selector and backend name are the same string.
`mime_format` is asserted as `"audio/wav"` for the same reason — it comes from
`_NATIVE_MIME["google"]`, a dict keyed by the TTS name, not the selector.

No `google_tts` routing defect surfaced, so nothing was escalated.

Validation: `pytest tests/test_basic_agent_new.py::test_speech_report_verbatim_google_tts_zero_llm_calls
tests/test_basic_agent_new.py::test_speech_report_verbatim_supertonic_zero_llm_calls -q`
-> **2 passed**. Full file earlier in the feature: 27 passed. `ruff check` clean.
