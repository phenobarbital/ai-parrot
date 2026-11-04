# TASK-5147: GoogleVoiceModel → gemini-3.8-live default; reel director → gemini-3.8-flash

**Feature**: FEAT-798 — Retire gemini-2.5-{pro,flash}: move the Google defaults to Gemini 4 Argon / 3.8-flash and bump google-genai
**Spec**: `sdd/specs/google-migration.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: S (< 2h)
**Depends-on**: none
**Assigned-to**: unassigned

---

## Context

Spec §3 **Module 4**, deadline **2026-11-17**: Google shuts down `gemini-2.5-flash-native-audio-preview-*`
and `gemini-2.5-flash-preview-tts` that day, two weeks before the chat models (proposal F028). The core
Live catalogue `GoogleVoiceModel` defaults to the 12-2025 native-audio preview, and `GeminiLiveClient`
reads `GoogleVoiceModel.DEFAULT.value` at class-definition time (`live.py:376`), so flipping `DEFAULT` is
the whole runtime change — `live.py` is **not** edited (spec AC-13). The same file holds the video-reel
director default (`gemini-2.5-flash`), which moves to `gemini-3.8-flash` (spec §2 table, flash-class).
This task has no cross-module dependency and should land first.

## Scope

- Replace the four 2.5 members of `GoogleVoiceModel` (lines 21-25) with `GEMINI_3_8_LIVE` and
  `GEMINI_3_8_FLASH_TTS`; set `DEFAULT = "gemini-3.8-live"`.
- Change the reel director default and its field description (lines 456, 602) to `gemini-3.8-flash`.
- Update `test_voicebot_provider_switch.py:90` to the new Live id.
- Create `packages/ai-parrot/tests/models/test_google_voice_model.py`.
- Record the live `models.get` evidence for `gemini-3.8-live` and `gemini-3.8-flash-tts` (spec AC-12, opt-in).

**NOT in scope**: `clients/google/live.py` (must stay untouched); `GoogleModel` in the client satellite
(TASK-5146 / TASK-5155); `bots/voice.py` text-LLM default (TASK-5151); docs/examples (TASK-5154).

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/models/google.py` | MODIFY | voice enum end state; reel director default |
| `packages/ai-parrot/tests/bots/test_voicebot_provider_switch.py` | MODIFY | Live id literal at :90 |
| `packages/ai-parrot/tests/models/test_google_voice_model.py` | CREATE | enum default + no-2.5 tests |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from parrot.models.google import GoogleVoiceModel   # verified: models/google.py:13; consumed relatively at clients/google/live.py:58
from parrot.models.google import VideoReelRequest   # FILL-IN CHECK: confirm the class that owns director_model (models/google.py:452) is named VideoReelRequest before importing — grep '^class ' models/google.py
```

### Existing Signatures to Use
```python
# packages/ai-parrot/src/parrot/models/google.py
class GoogleVoiceModel(str, Enum):                                                   # line 13
    GEMINI_2_5_FLASH_NATIVE_AUDIO_LATEST = "gemini-2.5-flash-native-audio-preview-12-2025"  # line 22
    GEMINI_2_5_FLASH_NATIVE_AUDIO_DEC_2025 = "gemini-2.5-flash-native-audio-preview-12-2025" # line 23
    GEMINI_2_5_FLASH_NATIVE_AUDIO_SEP_2025 = "gemini-2.5-flash-native-audio-preview-09-2025" # line 24
    GEMINI_2_5_FLASH_PREVIEW_TTS = "gemini-2.5-flash-preview-tts"                    # line 25
    GEMINI_3_FLASH_TTS = "gemini-3.1-flash-tts-preview"                              # line 26 (KEEP)
    DEFAULT = "gemini-2.5-flash-native-audio-preview-12-2025"                        # line 28
    @classmethod
    def all_models(cls) -> List[str]:                                                # line 31 — filters m.name == "DEFAULT"
    director_model: Optional[str] = Field(None, description=(...))                   # lines 452-458 (text at :456)
    def effective_director_model(self) -> str:                                       # line 600
        return self.director_model or "gemini-2.5-flash"                             # line 602

# packages/ai-parrot-client-google/src/parrot/clients/google/live.py  (READ ONLY — do not edit)
    _default_model: str = GoogleVoiceModel.DEFAULT.value                             # line 376
```

### Does NOT Exist
- ~~`GoogleVoiceModel.GEMINI_3_8_LIVE`~~, ~~`GoogleVoiceModel.GEMINI_3_8_FLASH_TTS`~~ — created by THIS task.
- ~~`GoogleVoiceModel` consumers other than `live.py`~~ — only `live.py` and two comments in `bots/voice.py:259-262` (wiki blast radius: none).
- ~~`gemini-3.8-live-native-audio`~~ — not a real id; the live ids are `gemini-3.8-live` and `gemini-3.8-live-extended-thinking`.

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {"path": "packages/ai-parrot/src/parrot/models/google.py", "action": "MODIFY"},
    {"path": "packages/ai-parrot/tests/bots/test_voicebot_provider_switch.py", "action": "MODIFY"},
    {"path": "packages/ai-parrot/tests/models/test_google_voice_model.py", "action": "CREATE"}
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot/src/parrot/models/google.py#GoogleVoiceModel"
  ]
}
```

---

## Implementation Notes

### Key Constraints
- `GoogleVoiceModel` is `(str, Enum)`: `DEFAULT = "gemini-3.8-live"` becomes an alias of `GEMINI_3_8_LIVE`.
  `all_models()` filters by name `"DEFAULT"`, and an alias is never yielded by iteration anyway, so the listing stays alias-free.
- Keep `GEMINI_3_FLASH_TTS` (3.1 preview) untouched.
- `live.py` reads `DEFAULT.value` at import, so a fresh interpreter picks up the change with no client edit.

---

## Implementation Blueprint

### Steps (in order)
1. Replace lines 21-25 and line 28 of `models/google.py` — *why*: these ids die on 2026-11-17.
2. Replace the director literal at :456 and :602 — *why*: flash-class default per spec §2.
3. Update the voice test literal and create the new test module.
4. Optional, opt-in: run the live `models.get` check and save its output under `artifacts/logs/`.

### `packages/ai-parrot/src/parrot/models/google.py` (MODIFY)
```python
# occurrences: 1 (verified: grep -c 'GEMINI_2_5_FLASH_NATIVE_AUDIO_LATEST = ' models/google.py)
# REPLACE lines 21-25 (from `    # Latest Native Audio models` through `GEMINI_2_5_FLASH_PREVIEW_TTS = ...`) with:
    # Live / native-audio models (FEAT-798: 2.5 previews shut down 2026-11-17)
    GEMINI_3_8_LIVE = "gemini-3.8-live"
    GEMINI_3_8_FLASH_TTS = "gemini-3.8-flash-tts"
```
```python
# occurrences: 1 (verified: grep -c 'DEFAULT = "gemini-2.5-flash-native-audio-preview-12-2025"' models/google.py)
# REPLACE (models/google.py:28)
    DEFAULT = "gemini-3.8-live"
```
```python
# occurrences: 1 each (verified: models/google.py:456, :602) — REPLACE the literal 'gemini-2.5-flash' with 'gemini-3.8-flash'
            "None resolves to the default director model ('gemini-3.8-flash')."
        return self.director_model or "gemini-3.8-flash"
```
**Why**: spec M4 skeleton. `GEMINI_3_FLASH_TTS` (line 26) and the `# Aliases` comment stay.

### `packages/ai-parrot/tests/bots/test_voicebot_provider_switch.py` (MODIFY)
```python
# occurrences: 1 (verified: grep -c 'gemini-2.5-flash-native-audio-preview-12-2025' test_voicebot_provider_switch.py → :90)
        bot.voice_config.model = "gemini-3.8-live"
```

### `packages/ai-parrot/tests/models/test_google_voice_model.py` (CREATE)
```python
"""FEAT-798: GoogleVoiceModel and reel-director defaults no longer name retired 2.5 ids."""

from parrot.models.google import GoogleVoiceModel


def test_google_voice_model_default_is_3_8_live() -> None:
    """The Live default is gemini-3.8-live and is an alias of GEMINI_3_8_LIVE."""
    assert GoogleVoiceModel.DEFAULT.value == "gemini-3.8-live"
    assert GoogleVoiceModel.DEFAULT is GoogleVoiceModel.GEMINI_3_8_LIVE


def test_google_voice_model_has_no_2_5_members() -> None:
    """No member name or value of the voice catalogue refers to Gemini 2.5."""
    # FILL IN: assert no name in GoogleVoiceModel.__members__ starts with "GEMINI_2_5" and no
    #          value in GoogleVoiceModel.all_models() contains "gemini-2.5" — bounded by spec AC-5


def test_reel_director_default_is_3_8_flash() -> None:
    """The video-reel director falls back to gemini-3.8-flash."""
    # FILL IN: construct the model that owns `director_model` (models/google.py:452) with only its
    #          required fields and assert effective_director_model() == "gemini-3.8-flash".
    #          Verify the class name and required fields first; bounded by spec §2 replacement table
```
**Why**: the `tests/models/` package already exists (`__init__.py` present).

### FILL IN checklist
- [ ] `test_google_voice_model_has_no_2_5_members` body.
- [ ] `test_reel_director_default_is_3_8_flash`: verify the owner class and its required fields.

---

## Acceptance Criteria

- [ ] `GoogleVoiceModel.DEFAULT.value == "gemini-3.8-live"`; no 2.5 member on the enum (spec AC-5).
- [ ] `git diff --stat` shows no change to `packages/ai-parrot-client-google/src/parrot/clients/google/live.py`.
- [ ] `effective_director_model()` returns `gemini-3.8-flash` when `director_model` is unset.
- [ ] Optional live evidence saved under `artifacts/logs/` (needs `GOOGLE_API_KEY` and `curl .../v1beta/models/gemini-3.8-live`).
- [ ] `ruff check` clean on the touched Python files.

## Validation Commands
- `pytest packages/ai-parrot/tests/models/test_google_voice_model.py -q`
- `pytest packages/ai-parrot/tests/bots/test_voicebot_provider_switch.py -q`

## Test Specification
See the CREATE block above.

---

## Agent Instructions

1. Work in the feature worktree: `parrot sdd worktree ensure --slug google-migration --feature-id FEAT-798 --spec sdd/specs/google-migration.spec.md --index sdd/tasks/index/google-migration.json`
2. Read the spec (§2, §3 M4, §6).
3. Check dependencies: none.
4. Verify the Codebase Contract with `grep -c`.
5. Mark the task `in-progress` in the index and commit only that file.
6. Implement from the blueprint and complete every `# FILL IN:`.
7. Run the Validation Commands with an absolute worktree `PYTHONPATH`.
8. Commit only the files listed above.
9. Close with `parrot sdd task close TASK-5147 google-migration verified`, then fill the Completion Note.

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**:
**Date**:
**Notes**:

**Deviations from spec**: none
