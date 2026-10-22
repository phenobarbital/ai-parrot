# TASK-4583: Registry-routed video_generation / generate_videos façade

**Feature**: FEAT-719 — Model Deprecation Follow-ups (Veo → Omni, Computer Use 3.8, gpt-transcribe)
**Spec**: `sdd/specs/model-deprecation-followups.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: L (4-8h)
**Depends-on**: TASK-4581, TASK-4582
**Assigned-to**: unassigned

> **Prerequisite**: branch `fix/model-deprecations-2026-10` (the 2026-10-22 deprecation sweep) must be merged into `dev` before this task starts — every anchor below was verified against `origin/dev` 63442566b + that sweep. Re-run each `grep -c` before editing.

---

## Context

Implements spec §3 Module 3. After the sweep `video_generation()`/`generate_videos()` have no default model and raise without one. They become thin façades over the FEAT-564 registry: resolve → `validate_request` → Veo adapter per clip or Omni `generate_many` → `AIMessage`.

---

## Scope

- Rewrite `video_generation()` as a façade; keep its signature exactly.
- `model or registry.default_video_model(surface)`; resolve; build `VideoRequestOptions`; `validate_request` BEFORE any provider call.
- Dispatch: Omni → `OmniClipAdapter.generate_many`; Veo (vertex, when enabled) → `VeoClipAdapter` via the existing `generate_video_clip` pattern.
- Move the inline Veo-only logic out of `video_generation` (it already exists in `VeoClipAdapter`).
- Rewrite `generate_videos()` to drop the `veo-` prefix check and rely on registry resolution.
- Wrap clips into the existing `AIMessage` return.
- New test file for the façade.

**NOT in scope**: `/mediagen` and `VideoGenerationPrompt` (TASK-4584); reel pipeline (`generate_video_reel`); enabling Vertex profiles.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot-client-google/src/parrot/clients/google/generation.py` | MODIFY | video_generation + generate_videos façades |
| `packages/ai-parrot-client-google/tests/unit/test_video_generation_facade.py` | CREATE | façade tests |

---

## Codebase Contract (Anti-Hallucination)

> Use these exact imports and signatures. Verify anything not listed before using it.

### Verified Imports
```python
from parrot.clients.google.reel.profiles import VideoProfileRegistry  # verified: reel/profiles.py:89
from parrot.clients.google.reel.omni import OmniClipAdapter           # verified: reel/omni.py:75
from parrot.clients.google.reel.veo import VeoClipAdapter             # verified: reel/veo.py:62
# generation.py already imports these inside generate_video_clip (:2050) — follow its import style
# VideoRequestOptions comes from TASK-4581 (reel/profiles.py)
```

### Existing Signatures to Use
```python
# packages/ai-parrot-client-google/src/parrot/clients/google/generation.py
async def video_generation(self, prompt: Union[str, VideoGenInput], output_directory=None,
    model: Optional[str] = None, aspect_ratio=AspectRatio.RATIO_16_9, negative_prompt=None,
    number_of_videos: int = 1, reference_image=None, generate_image_first: bool = False, image_prompt=None,
    duration: int = 8, resolution=None, person_generation: str = "allow_adult", include_audio: bool = True,
    last_frame=None, reference_images=None, reference_type: str = "asset", extend_video=None, seed=None,
    user_id=None, session_id=None, **kwargs) -> AIMessage                    # line 954
async def generate_videos(self, prompt, reference_image=None, output_directory=None,
    mime_format: str = "video/mp4", model: Optional[str] = None) -> AIMessage   # line 2005
async def generate_video_clip(self, *, prompt, model, output_directory, aspect_ratio, resolution,
    target_duration_seconds, starting_frame=None, audio_mode="separate", timeout_seconds=600.0)  # line 2050
#   registry.resolve(model, api_surface); registry.validate_scene(...);
#   profile.backend == "veo" → VeoClipAdapter(self) else OmniClipAdapter(self, ProviderMediaDownloader())
# api_surface derivation: see generate_video_reel (:2141, :2363 `registry.default_video_model(api_surface)`)
```

### Does NOT Exist
- ~~`GoogleModel.VEO_3_1*`~~ — removed in the sweep; never reintroduce Veo ids in generation.py
- ~~a `duration` default sent to Omni~~ — `duration=8` in the signature must NOT be forwarded to Omni (treat the untouched default as 'unset')
- ~~`AIMessageFactory.from_video`~~ — unverified; reuse whatever the current video_generation return path uses

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {
      "path": "packages/ai-parrot-client-google/src/parrot/clients/google/generation.py",
      "action": "MODIFY"
    },
    {
      "path": "packages/ai-parrot-client-google/tests/unit/test_video_generation_facade.py",
      "action": "CREATE"
    }
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot-client-google/src/parrot/clients/google/generation.py#GoogleGeneration.video_generation",
    "sym:packages/ai-parrot-client-google/src/parrot/clients/google/generation.py#GoogleGeneration.generate_videos",
    "sym:packages/ai-parrot-client-google/src/parrot/clients/google/generation.py#GoogleGeneration.generate_video_clip"
  ]
}
```

---

## Implementation Notes

### Key Constraints
- Async throughout; `self.logger` (never `print`); Pydantic v2; aiohttp only.
- Hard cut — no deprecation shims (no external consumers).
- Signatures of both methods stay byte-identical (public API).
- Validation runs before ANY provider call (spec AC-3).
- Vertex client with no model ⇒ `MODEL_DISABLED` from the registry — do not work around it.

---

## Implementation Blueprint

### Steps (in order)
1. Extract the api_surface derivation used by `generate_video_reel` — *why*: one rule for which surface a client targets.
2. Normalise inputs (keep the existing `VideoGenInput` unpacking) into `VideoRequestOptions`; treat `duration == 8` default as unset — *why*: Omni rejects any duration (spec §7).
3. Resolve + `validate_request` — *why*: fail closed before paying.
4. Dispatch per backend; wrap clips into the existing AIMessage shape — *why*: unchanged return contract.
5. Delete the inline Veo personGeneration/resolution/extension logic from `video_generation` — *why*: it lives in VeoClipAdapter (spec §2).
6. Simplify `generate_videos` to delegate — *why*: registry decides valid models.

### `packages/ai-parrot-client-google/src/parrot/clients/google/generation.py` (MODIFY)
```python
# occurrences: 1 (verified: grep -c '    async def video_generation(' generation.py) — :954
# REPLACE the body of video_generation (keep the signature and docstring header; rewrite the docstring body):
        """Generate videos through the FEAT-564 profile registry.

        ``model`` None → the registry default for this client's API surface
        (``gemini-omni-1.1-flash`` on the Gemini Developer API). Options the resolved
        profile cannot honour raise ``ReelValidationError`` before any provider call.
        """
        # FILL IN: keep the existing VideoGenInput unpacking block verbatim
        registry = VideoProfileRegistry.default()
        # FILL IN: api_surface = <same derivation as generate_video_reel>
        model_id = model.value if isinstance(model, Enum) else model
        model_id = model_id or registry.default_video_model(api_surface)
        profile = registry.resolve(model_id, api_surface)
        # FILL IN: options = VideoRequestOptions(...) from the arguments — duration only when != 8 or from VideoGenInput
        registry.validate_request(profile, request=options)
        # FILL IN: generate_image_first → keep current behaviour only if profile.supports_starting_frame, else it was rejected above
        # FILL IN: omni → OmniClipAdapter(self, ProviderMediaDownloader()).generate_many(...); veo → VeoClipAdapter per clip
        # FILL IN: build and return the AIMessage exactly as the current implementation does (media paths)
```
```python
# occurrences: 1 (verified: grep -c '    async def generate_videos(' generation.py) — :2005
# REPLACE the 'veo-' prefix check with: let video_generation's registry resolution decide (UNKNOWN_MODEL etc.)
```
**Why this shape**: spec §2 "registry-routed" + resolved brainstorm decision "route by profile". The façade must not
duplicate Veo knowledge that already lives in `VeoClipAdapter`.

### `packages/ai-parrot-client-google/tests/unit/test_video_generation_facade.py` (CREATE)
```python
"""FEAT-719 TASK-4583 — registry-routed video façade."""
import pytest
from unittest.mock import AsyncMock, patch

from parrot.clients.google import GoogleGenAIClient
from parrot.clients.google.reel.errors import ReelErrorCode, ReelValidationError

# FILL IN: tests from Test Specification — patch OmniClipAdapter / VeoClipAdapter, never call the network
```

### FILL IN checklist
- [ ] api_surface derivation — bounded by generate_video_reel's existing rule
- [ ] VideoRequestOptions mapping, duration default handling — bounded by spec §7 (Omni rejects duration)
- [ ] AIMessage construction — bounded by the current return path (unchanged contract)

---

## Acceptance Criteria

- [ ] No model on the Developer API → Omni adapter, zero Veo calls
- [ ] Every unsupported Omni option raises before any adapter call
- [ ] `number_of_videos=2` on Omni → one `generate_many` call
- [ ] Vertex client, no model → `MODEL_DISABLED`
- [ ] Both signatures unchanged

---

## Validation Commands

- `pytest packages/ai-parrot-client-google/tests/unit/test_video_generation_facade.py -q`
- `pytest packages/ai-parrot-client-google/tests/unit/reel/test_reel_sdk_contract.py -q`

---

## Test Specification

```python
async def test_video_generation_default_routes_omni(tmp_path):
    client = GoogleGenAIClient(api_key="k", vertexai=False)
    with patch("parrot.clients.google.reel.omni.OmniClipAdapter.generate_many", new=AsyncMock(return_value=[clip])) as gm:
        msg = await client.video_generation("a lion", output_directory=tmp_path)
    gm.assert_awaited_once()


async def test_video_generation_rejects_before_paid_call(tmp_path):
    client = GoogleGenAIClient(api_key="k", vertexai=False)
    with patch("parrot.clients.google.reel.omni.OmniClipAdapter.generate_many", new=AsyncMock()) as gm:
        with pytest.raises(ReelValidationError):
            await client.video_generation("a lion", resolution="1080p", output_directory=tmp_path)
    gm.assert_not_awaited()
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
9. **Close** with `scripts/sdd/close_task.sh TASK-4583 model-deprecation-followups verified`
10. **Fill in the Completion Note**, then commit the staged SDD state

---

## Completion Note

Implemented by an sdd-coder seat (codex gpt-5.6-luna); merged by the orchestrator. Task validation commands re-run green in the sub-worktree (engine task-tier validation unavailable: attempt had no execution_id).
