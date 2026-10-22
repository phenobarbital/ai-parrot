# TASK-4588: OpenAI transcription: gpt-transcribe default, per-model response format, ISO language

**Feature**: FEAT-719 — Model Deprecation Follow-ups (Veo → Omni, Computer Use 3.8, gpt-transcribe)
**Spec**: `sdd/specs/model-deprecation-followups.spec.md`
**Status**: pending
**Priority**: medium
**Estimated effort**: M (2-4h)
**Depends-on**: none
**Assigned-to**: unassigned

> **Prerequisite**: branch `fix/model-deprecations-2026-10` (the 2026-10-22 deprecation sweep) must be merged into `dev` before this task starts — every anchor below was verified against `origin/dev` 63442566b + that sweep. Re-run each `grep -c` before editing.

---

## Context

Implements spec §3 Module 7. `whisper-1` shuts down 2027-02-26. Live probe: `gpt-transcribe` accepts only `json`/`text`; json = `{text, languages:[{code}], usage:{type:duration, seconds}}`; whisper `verbose_json` returns `language` as a NAME ("english").

---

## Scope

- Default `model` → `"gpt-transcribe"`.
- `_RESPONSE_FORMATS` table: `whisper-1` → `verbose_json`; default `json`.
- `_parse_result(model, payload, language_hint)` → `(text, iso_language, duration_seconds)` for both shapes.
- Normalise language to ISO 639-1 (code list or whisper name); fallback hint → `"en"`.
- Tests using the probe payloads verbatim.

**NOT in scope**: realtime/live transcription; the FasterWhisper/Moonshine backends; renaming the class.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot-integrations/src/parrot/voice/transcriber/openai_backend.py` | MODIFY | format table, parsing, default |
| `packages/ai-parrot-integrations/tests/integrations/msteams/test_openai_whisper_backend.py` | MODIFY | tests |

---

## Codebase Contract (Anti-Hallucination)

> Use these exact imports and signatures. Verify anything not listed before using it.

### Verified Imports
```python
from parrot.voice.transcriber import OpenAIWhisperBackend  # verified: voice/transcriber/__init__.py:21
```

### Existing Signatures to Use
```python
# packages/ai-parrot-integrations/src/parrot/voice/transcriber/openai_backend.py
class OpenAIWhisperBackend(AbstractTranscriberBackend)                      # line 23
def __init__(self, api_key: str, model: str = "whisper-1", max_retries: int = 3, timeout_seconds: int = 60)  # line 52-55
async def _transcribe_attempt(self, audio_path, language, start_time, ...)   # line 172
data.add_field("response_format", "verbose_json")                          # line 208
TranscriptionResult(text=result_json.get("text", ""), language=result_json.get("language", "en"),
    duration_seconds=result_json.get("duration", 0.0), confidence=None, processing_time_ms=...)  # line 238-243
# voice/transcriber/models.py:90 TranscriptionResult — text, language, duration_seconds, confidence, processing_time_ms
```

### Does NOT Exist
- ~~segments in gpt-transcribe responses~~ — none (probe); `timestamp_granularities[]` is ignored
- ~~`TranscriptionResult.segments`~~ — not a field; do not add one

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {
      "path": "packages/ai-parrot-integrations/src/parrot/voice/transcriber/openai_backend.py",
      "action": "MODIFY"
    },
    {
      "path": "packages/ai-parrot-integrations/tests/integrations/msteams/test_openai_whisper_backend.py",
      "action": "MODIFY"
    }
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot-integrations/src/parrot/voice/transcriber/openai_backend.py#OpenAIWhisperBackend",
    "sym:packages/ai-parrot-integrations/src/parrot/voice/transcriber/openai_backend.py#OpenAIWhisperBackend._transcribe_attempt"
  ]
}
```

---

## Implementation Notes

### Key Constraints
- Async throughout; `self.logger` (never `print`); Pydantic v2; aiohttp only.
- Hard cut — no deprecation shims (no external consumers).
- Never send `verbose_json` to a model outside the table (400 `unsupported_value`).
- `response_format=json` responses must be parsed with `response.json()`; `text` is not used.

---

## Implementation Blueprint

### Steps (in order)
1. Add the table + default — *why*: per-model format (probe).
2. Add `_parse_result` — *why*: two response shapes.
3. Language normalisation — *why*: whisper returns names, gpt-transcribe ISO codes (spec §7).
4. Tests with the probe payloads.

### `packages/ai-parrot-integrations/src/parrot/voice/transcriber/openai_backend.py` (MODIFY)
```python
# module level, after imports:
_RESPONSE_FORMATS: Dict[str, str] = {"whisper-1": "verbose_json"}  # default "json" (gpt-transcribe rejects verbose_json)
```
```python
# occurrences: 1 (verified: grep -c '        model: str = "whisper-1",' openai_backend.py) — :55
        model: str = "gpt-transcribe",
```
```python
# occurrences: 1 (verified: grep -c '        data.add_field("response_format", "verbose_json")' openai_backend.py) — :208
        data.add_field("response_format", _RESPONSE_FORMATS.get(self.model, "json"))
```
```python
# occurrences: 1 (verified: grep -c '                    language=result_json.get("language", "en"),' openai_backend.py) — :239
# REPLACE the TranscriptionResult(...) construction with:
                text, lang, duration = self._parse_result(self.model, result_json, language)
                return TranscriptionResult(
                    text=text,
                    language=lang,
                    duration_seconds=duration,
                    confidence=None,
                    processing_time_ms=processing_time_ms,
                )

    @staticmethod
    def _parse_result(model: str, payload: dict, language_hint: Optional[str]) -> tuple[str, str, float]:
        """Return (text, iso_language, duration_seconds) for whisper verbose_json or gpt-transcribe json."""
        # FILL IN: languages[0]["code"] | whisper name → ISO 639-1 | language_hint | "en"; duration ← "duration" | usage.seconds
```

### FILL IN checklist
- [ ] name→ISO mapping (cover at least the languages the repo already references, e.g. en/es) — bounded by spec AC-8
- [ ] duration fallback chain — bounded by probe payload shapes

---

## Acceptance Criteria

- [ ] default model `gpt-transcribe`; it receives `response_format=json`
- [ ] `whisper-1` still receives `verbose_json`
- [ ] probe payloads parse to `en` and 5.0 / 4.97
- [ ] `TranscriptionResult` fields unchanged

---

## Validation Commands

- `pytest packages/ai-parrot-integrations/tests/integrations/msteams/test_openai_whisper_backend.py -q`
- `pytest packages/ai-parrot-integrations/tests/integrations/msteams/test_voice_transcriber.py -q`

---

## Test Specification

```python
from parrot.voice.transcriber import OpenAIWhisperBackend

GPT_TRANSCRIBE_JSON = {"text": "Hello, welcome to the world of generative AI audio.",
                       "languages": [{"code": "en"}], "usage": {"type": "duration", "seconds": 5}}
WHISPER_VERBOSE = {"task": "transcribe", "language": "english", "duration": 4.97, "text": "Hello!", "segments": []}


def test_gpt_transcribe_json_parsing():
    assert OpenAIWhisperBackend._parse_result("gpt-transcribe", GPT_TRANSCRIBE_JSON, None) == (
        GPT_TRANSCRIBE_JSON["text"], "en", 5.0)


def test_whisper_language_iso():
    assert OpenAIWhisperBackend._parse_result("whisper-1", WHISPER_VERBOSE, None)[1] == "en"
```

---

## Agent Instructions

When you pick up this task:

1. **Work in the feature worktree** — never on `base_branch`
   (`python -m scripts.sdd.ensure_worktree --slug model-deprecation-followups --feature-id FEAT-719`)
2. **Read the spec** at `sdd/specs/model-deprecation-followups.spec.md` for full context
3. **Check dependencies** — every `Depends-on` task must be `"done"` in `sdd/tasks/index/model-deprecation-followups.json`
4. **Verify the Codebase Contract** — re-run every `grep -c` in the blueprint; a changed count means the
   anchor moved (re-locate it), a `0` means drift (stop and report)
5. **Update status** in the per-spec index → `"in-progress"` (set `started_at`) and commit only that file
6. **Implement** from the Implementation Blueprint; complete every `# FILL IN:`; never change a fixed
   signature or path
7. **Verify** — run the Validation Commands with `PYTHONPATH` pointing at the worktree's `packages/*/src`
8. **Commit the code** — stage only the files listed above
9. **Close** with `scripts/sdd/close_task.sh TASK-4588 model-deprecation-followups verified`
10. **Fill in the Completion Note**, then commit the staged SDD state

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**: <session or agent ID>
**Date**: YYYY-MM-DD
**Notes**:

**Deviations from spec**: none
