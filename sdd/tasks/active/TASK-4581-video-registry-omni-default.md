# TASK-4581: Video profile registry: drop dead Veo previews, Omni default, validate_request

**Feature**: FEAT-719 — Model Deprecation Follow-ups (Veo → Omni, Computer Use 3.8, gpt-transcribe)
**Spec**: `sdd/specs/model-deprecation-followups.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: none
**Assigned-to**: unassigned

> **Prerequisite**: branch `fix/model-deprecations-2026-10` (the 2026-10-22 deprecation sweep) must be merged into `dev` before this task starts — every anchor below was verified against `origin/dev` 63442566b + that sweep. Re-run each `grep -c` before editing.

---

## Context

Implements spec §3 Module 1. The Gemini Developer API shut down Veo 3.1 previews on 2026-10-22; the FEAT-564 `VideoProfileRegistry` still registers them as enabled and defaults `gemini_developer` to `veo-3.1-generate-preview`. Downstream tasks (TASK-4582 multi-output, TASK-4583 façade) need `max_outputs_per_request`, `VideoRequestOptions` and `validate_request()` from this task.

---

## Scope

- Remove the three `veo-3.1-*-preview` `gemini_developer` profiles from `VideoProfileRegistry.default()`.
- Make `default_video_model("gemini_developer")` return `"gemini-omni-1.1-flash"` (vertex default unchanged).
- Add `max_outputs_per_request: int = Field(1, ge=1)` to `VideoModelProfile`; set it on the Omni profile.
- Add the `VideoRequestOptions` model and `VideoProfileRegistry.validate_request()`.
- Update `test_reel_profiles.py` for the new set/default and add validate_request tests.

**NOT in scope**: enabling Vertex profiles (§8 Q5 gate stays closed); Omni adapter changes (TASK-4582); the façade (TASK-4583).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot-client-google/src/parrot/clients/google/reel/profiles.py` | MODIFY | registry set, default, new field, VideoRequestOptions, validate_request |
| `packages/ai-parrot-client-google/tests/unit/reel/test_reel_profiles.py` | MODIFY | update + new tests |

---

## Codebase Contract (Anti-Hallucination)

> Use these exact imports and signatures. Verify anything not listed before using it.

### Verified Imports
```python
from parrot.clients.google.reel.profiles import VideoProfileRegistry, VideoModelProfile  # verified: reel/profiles.py:34,89
from parrot.clients.google.reel.errors import ReelErrorCode, ReelValidationError       # verified: reel/errors.py:32
```

### Existing Signatures to Use
```python
# packages/ai-parrot-client-google/src/parrot/clients/google/reel/profiles.py
ApiSurface = Literal["gemini_developer", "vertex"]                          # line 24
class VideoModelProfile(BaseModel)                                          # line 34
class VideoProfileRegistry:                                                 # line 89
    def default(cls) -> "VideoProfileRegistry"   # classmethod             # line 104
    def default_video_model(self, surface: ApiSurface) -> str               # line 183
    def resolve(self, model_id: str, surface: ApiSurface) -> VideoModelProfile  # line 206
    def validate_scene(self, profile, *, resolution: str, audio_mode: str, has_starting_frame: bool) -> None  # line 239
# Omni profile fields: backend="omni", durations_seconds=None, resolutions=[], supports_starting_frame=False,
#   supports_reference_guidance=False, native_audio="always", person_generation_values=[]
# ReelErrorCode.UNSUPPORTED_OPTION / UNKNOWN_MODEL / MODEL_DISABLED  # reel/errors.py:45-50
```

### Does NOT Exist
- ~~`VideoProfileRegistry.validate_request`~~ / ~~`VideoRequestOptions`~~ — created by this task
- ~~`VideoModelProfile.max_outputs_per_request`~~ — created by this task
- ~~substring model matching~~ — the registry is exact `(surface, model_id)` only (FEAT-564)

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {
      "path": "packages/ai-parrot-client-google/src/parrot/clients/google/reel/profiles.py",
      "action": "MODIFY"
    },
    {
      "path": "packages/ai-parrot-client-google/tests/unit/reel/test_reel_profiles.py",
      "action": "MODIFY"
    }
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot-client-google/src/parrot/clients/google/reel/profiles.py#VideoModelProfile",
    "sym:packages/ai-parrot-client-google/src/parrot/clients/google/reel/profiles.py#VideoProfileRegistry",
    "sym:packages/ai-parrot-client-google/src/parrot/clients/google/reel/profiles.py#VideoProfileRegistry.validate_scene"
  ]
}
```

---

## Implementation Notes

### Key Constraints
- Async throughout; `self.logger` (never `print`); Pydantic v2; aiohttp only.
- Hard cut — no deprecation shims (no external consumers).
- Never drop an option silently: every unsupported option raises `ReelValidationError(UNSUPPORTED_OPTION)`.
- Keep `source`/`checked_on` on the Omni profile; update `checked_on` only if you re-verify capability data.

---

## Implementation Blueprint

### Steps (in order)
1. Add `max_outputs_per_request` to `VideoModelProfile` — *why*: the façade must cap `number_of_videos` per request (spec §2).
2. Delete the three `veo-3.1-*-preview` gemini_developer entries — *why*: shut down 2026-10-22 (brainstorm decision).
3. Set the Omni profile's `max_outputs_per_request` — *why*: Omni returns several videos per request (§8 resolved).
4. Repoint `default_video_model` — *why*: Omni is the gemini_developer default.
5. Add `VideoRequestOptions` + `validate_request` delegating to `validate_scene` — *why*: one fail-closed check for every façade option.
6. Update/extend tests.

### `packages/ai-parrot-client-google/src/parrot/clients/google/reel/profiles.py` (MODIFY)
```python
# occurrences: 1 (verified: grep -c 'class VideoModelProfile(BaseModel):' reel/profiles.py)
# INSIDE class VideoModelProfile (verified: reel/profiles.py:34) — add as the last field:
    max_outputs_per_request: int = Field(
        1,
        ge=1,
        description="Maximum videos one provider request may return (Omni > 1).",
    )
```
```python
# occurrences: 1 (verified: grep -c 'model_id="veo-3.1-generate-preview",' reel/profiles.py) — :131
# DELETE the three VideoModelProfile(...) entries whose model_id is veo-3.1-generate-preview,
# veo-3.1-fast-generate-preview and veo-3.1-lite-generate-preview with surface="gemini_developer".
# In the gemini-omni-1.1-flash profile add:
                max_outputs_per_request=4,  # FILL IN: confirm the real per-request maximum from google-genai (spec §8 Q2)
```
```python
# occurrences: 1 (verified: grep -c '"gemini_developer": "veo-3.1-generate-preview",' reel/profiles.py) — :196
            "gemini_developer": "gemini-omni-1.1-flash",
```
```python
# AFTER the end of validate_scene (verified: reel/profiles.py:239) — new model at module level above the registry, method on the registry:
class VideoRequestOptions(BaseModel):
    """Normalised single-request video options validated against a profile."""

    resolution: Optional[str] = None
    duration_seconds: Optional[int] = None
    number_of_videos: int = 1
    has_starting_frame: bool = False
    has_last_frame: bool = False
    reference_image_count: int = 0
    extends_video: bool = False
    audio_mode: str = "separate"


    def validate_request(self, profile: VideoModelProfile, *, request: VideoRequestOptions) -> None:
        """Raise ReelValidationError(UNSUPPORTED_OPTION) for any option the profile cannot honour.

        Never drops an option silently. Resolution / starting-frame / audio checks delegate to
        :meth:`validate_scene`.
        """
        if request.resolution is not None or request.has_starting_frame or request.audio_mode == "native":
            self.validate_scene(
                profile,
                resolution=request.resolution or (profile.resolutions[0] if profile.resolutions else ""),
                audio_mode=request.audio_mode,
                has_starting_frame=request.has_starting_frame,
            )
        # FILL IN: resolution on a profile with resolutions == [] must raise UNSUPPORTED_OPTION (Omni) — bounded by spec AC-3
        # FILL IN: duration_seconds set and profile.durations_seconds is None or value not in it → UNSUPPORTED_OPTION
        # FILL IN: number_of_videos > profile.max_outputs_per_request → UNSUPPORTED_OPTION
        # FILL IN: has_last_frame / extends_video / reference_image_count>0 on a profile that cannot honour them
        #          (use supports_reference_guidance; last frame + extension are Veo-only) → UNSUPPORTED_OPTION
```
**Why this shape**: the spec fixes the names `max_outputs_per_request`, `VideoRequestOptions`, `validate_request`
(§3 M1 skeleton). Delegating to `validate_scene` keeps one source of truth for the checks FEAT-564 already tests.

### `packages/ai-parrot-client-google/tests/unit/reel/test_reel_profiles.py` (MODIFY)
```python
# FILL IN: update any assertion that expects veo-3.1-*-preview on gemini_developer or that default to be veo
# ADD the tests listed in Test Specification below.
```

### FILL IN checklist
- [ ] `max_outputs_per_request` value on the Omni profile — bounded by spec §8 Q2 (read google-genai)
- [ ] each `validate_request` branch — bounded by spec AC-3 (zero provider calls) and AC-4
- [ ] existing profile tests updated, none deleted without replacement

---

## Acceptance Criteria

- [ ] `default_video_model("gemini_developer") == "gemini-omni-1.1-flash"`; vertex default unchanged
- [ ] `resolve("veo-3.1-generate-preview", "gemini_developer")` raises `UNKNOWN_MODEL`
- [ ] Vertex profiles still `enabled=False`
- [ ] `validate_request` raises `UNSUPPORTED_OPTION` for resolution, duration, last frame, extension, reference images and over-cap `number_of_videos` on Omni
- [ ] `ruff check` adds no new findings

---

## Validation Commands

- `pytest packages/ai-parrot-client-google/tests/unit/reel/test_reel_profiles.py -q`

---

## Test Specification

```python
import pytest
from parrot.clients.google.reel.profiles import VideoProfileRegistry, VideoRequestOptions
from parrot.clients.google.reel.errors import ReelErrorCode, ReelValidationError


def test_registry_dev_default_is_omni():
    assert VideoProfileRegistry.default().default_video_model("gemini_developer") == "gemini-omni-1.1-flash"


def test_registry_dev_veo_preview_unknown():
    with pytest.raises(ReelValidationError) as exc:
        VideoProfileRegistry.default().resolve("veo-3.1-generate-preview", "gemini_developer")
    assert exc.value.code == ReelErrorCode.UNKNOWN_MODEL


@pytest.mark.parametrize("opts", [
    VideoRequestOptions(resolution="1080p"), VideoRequestOptions(duration_seconds=8),
    VideoRequestOptions(has_starting_frame=True), VideoRequestOptions(has_last_frame=True),
    VideoRequestOptions(reference_image_count=1), VideoRequestOptions(extends_video=True),
    VideoRequestOptions(number_of_videos=999),
])
def test_validate_request_rejects_omni_gaps(opts):
    reg = VideoProfileRegistry.default()
    omni = reg.resolve("gemini-omni-1.1-flash", "gemini_developer")
    with pytest.raises(ReelValidationError) as exc:
        reg.validate_request(omni, request=opts)
    assert exc.value.code == ReelErrorCode.UNSUPPORTED_OPTION
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
9. **Close** with `scripts/sdd/close_task.sh TASK-4581 model-deprecation-followups verified`
10. **Fill in the Completion Note**, then commit the staged SDD state

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**: <session or agent ID>
**Date**: YYYY-MM-DD
**Notes**:

**Deviations from spec**: none
