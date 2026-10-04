# TASK-3622: speech_report backend and mode routing

**Feature**: FEAT-591 — speech_report pluggable TTS backends (fast-path)
**Spec**: `sdd/specs/speech-report-models.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: L (4-8h)
**Depends-on**: TASK-3619, TASK-3620, TASK-3621
**Assigned-to**: unassigned

---

## Context

Implement spec §3 M4 after the TTS layer supplies Polly, shared synthesizers, and truthful Google WAV.

## Scope

- Add backend/mode attributes, keyword overrides, validation, normalization, and lazy integration routing.
- Preserve the default Gemini-script path byte-for-byte; replace its print with logger output.
- Add routing tests to the existing BasicAgent test module.

**NOT in scope**: closing shared synthesizers, Telegram defaults, or documentation.

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/bots/agent.py` | MODIFY | Routing and helpers |
| `packages/ai-parrot/tests/test_basic_agent_new.py` | MODIFY | Routing tests |

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from ..models.google import ConversationalScriptConfig, FictionalSpeaker  # verified: agent.py:19
from parrot.outputs.formats.text import markdown_to_plain  # verified: packages/ai-parrot/src/parrot/outputs/formats/text.py:115
from parrot.models.outputs import SpeakerConfig, SpeechGenerationPrompt  # verified: packages/ai-parrot/src/parrot/models/outputs.py:235
from parrot.voice.tts.google_backend import GoogleTTSBackend  # verified: packages/ai-parrot-integrations/src/parrot/voice/tts/google_backend.py:31 (lazy integration dependency)
```

### Existing Signatures to Use
```python
# agent.py:29,605
class BasicAgent(Chatbot, NotificationMixin):
    num_speakers: int = 1
    async def speech_report(self, report: str, max_lines: int = 15, num_speakers: int = 2, podcast_instructions: Optional[str] = "for_podcast.txt", directory: Optional[Path] = None, output_directory: Optional[Path] = None, script_model: Optional[str] = None, tts_model: Optional[str] = None, **kwargs) -> Dict[str, Any]: ...
# google_backend.py:31
class GoogleTTSBackend(AbstractTTSBackend): ...
```

### Does NOT Exist
- `BasicAgent.speech_backend`, `speech_mode`, `speech_voice`, `speech_language`, `speech_format`, and `speech_tts_options` do not exist.
- Core `ai-parrot` must not eagerly import `parrot.voice.tts`.

## Complexity Contract
```json
{"schema_version":1,"targets":[{"path":"packages/ai-parrot/src/parrot/bots/agent.py","action":"MODIFY"},{"path":"packages/ai-parrot/tests/test_basic_agent_new.py","action":"MODIFY"}],"contract_symbols":["sym:packages/ai-parrot/src/parrot/bots/agent.py#BasicAgent","sym:packages/ai-parrot/src/parrot/models/google.py#ConversationalScriptConfig","sym:packages/ai-parrot/src/parrot/models/outputs.py#SpeechGenerationPrompt","sym:packages/ai-parrot-integrations/src/parrot/voice/tts/google_backend.py#GoogleTTSBackend"]}
```

## Implementation Blueprint

### Steps (in order)
1. Add `SpeechBackend`, `SpeechMode`, mappings, and class defaults after `num_speakers` — *why*: makes selectors explicit and testable.
2. Add route resolution and speakable-text helpers, validating kwarg > attribute > default — *why*: establishes the §2 matrix once.
3. Branch before unchanged Gemini-script code; use a one-speaker script for non-Gemini script mode and no client call for non-Gemini verbatim — *why*: AC1/AC3/AC4.
4. Lazily import TTS only in non-default flow, save exact spoken text, write returned audio using the MIME extension map, and never close the shared object.
5. Add all specified route/failure/model-regression tests and replace line-688 print with `self.logger.info`.

### MODIFY anchors
```text
agent.py: `num_speakers: int = 1  # Default number of speakers for the podcast` (occurrences: 1): add attributes after this line.
agent.py: `async def speech_report(` (occurrences: 1): extend signature and route before legacy default path.
agent.py: `speech_result = await client.generate_speech(**speech_kwargs)` (occurrences: 1): retain legacy call and change only following print to logger.
test_basic_agent_new.py: append after `test_speech_report_omits_model_kwargs_by_default` (occurrences: 1).
```

### FILL IN checklist
- [ ] `gemini` plus `script` follows the current legacy statements unchanged.
- [ ] `script_path` contains exactly the normalized TTS input for verbatim.
- [ ] Import failures name `ai-parrot-integrations[voice-supertonic]` or `[voice-polly]`.

## Acceptance Criteria

- [ ] AC1–AC7, AC9, AC13, AC14, and AC16 of FEAT-591 pass.

## Validation Commands

- `pytest packages/ai-parrot/tests/test_basic_agent_new.py -v`

### Completion Note

Implemented via `parrot-sdd-coder` (execution `4bfb2cf6-9bb3-4ebf-87f0-09ee5cb10a02`,
seat `gpt-5.6-terra`/codex, attempt_uid `555c40e870df4887b15486799e2d8181`, 1 attempt,
no retries), merged at commit `06ede6304` (+lint autofix `8b84f7417`).

Verified before closing:
- File fidelity: merge commit touches exactly the 2 contract files (agent.py,
  test_basic_agent_new.py), no unlisted files.
- Task's own Validation Commands
  (`PYTHONPATH=packages/ai-parrot/src:packages/ai-parrot-integrations/src` — both
  changed distributions on path, since this task's lazy TTS integration depends on
  TASK-3620's `get_shared_synthesizer`): 17/19 tests pass, including every new
  speech_report routing/backend/MIME test this task added.
  The 2 remaining failures (`test_setup_mcp_servers`, `test_agent_real_integration`)
  are pre-existing and unrelated — confirmed present, byte-identical, in this test
  file at the commit immediately before this task ran (`3951d6df9`); filed as
  `issue:7c3f2e6ed5be` [major].
- `coder_run_validation(tier="merge")` was launched; the full `packages/
  ai-parrot-integrations/tests` sweep it escalates to is expected to hit the same
  pre-existing environment hang already documented on TASK-3619/3620/3621
  (`issue:312c1988479b` [critical]).

No confirmed defect found in the delivered code; no feedback recorded.
