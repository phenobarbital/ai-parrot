# TASK-4582: OmniClipAdapter.generate_many — N videos in one Interactions request

**Feature**: FEAT-719 — Model Deprecation Follow-ups (Veo → Omni, Computer Use 3.8, gpt-transcribe)
**Spec**: `sdd/specs/model-deprecation-followups.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-4581
**Assigned-to**: unassigned

> **Prerequisite**: branch `fix/model-deprecations-2026-10` (the 2026-10-22 deprecation sweep) must be merged into `dev` before this task starts — every anchor below was verified against `origin/dev` 63442566b + that sweep. Re-run each `grep -c` before editing.

---

## Context

Implements spec §3 Module 2. Omni returns several videos per request (resolved in brainstorm); the current `OmniClipAdapter.generate()` produces exactly one clip. TASK-4583's façade calls `generate_many` for `number_of_videos > 1`.

---

## Scope

- Add `OmniClipAdapter.generate_many(...)` that issues ONE `client.aio.interactions.create` for `number_of_videos` outputs.
- Materialise, measure and return every output as a `GeneratedReelClip`.
- Raise `ReelValidationError(UNSUPPORTED_OPTION)` when `number_of_videos > profile.max_outputs_per_request`.
- Tests in `test_reel_omni.py`.

**NOT in scope**: changing `generate()` behaviour for reels; the façade (TASK-4583); Veo multi-output.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot-client-google/src/parrot/clients/google/reel/omni.py` | MODIFY | add generate_many |
| `packages/ai-parrot-client-google/tests/unit/reel/test_reel_omni.py` | MODIFY | multi-output tests |

---

## Codebase Contract (Anti-Hallucination)

> Use these exact imports and signatures. Verify anything not listed before using it.

### Verified Imports
```python
from parrot.clients.google.reel.omni import OmniClipAdapter        # verified: reel/omni.py:75
from parrot.clients.google.reel.clip import GeneratedReelClip      # verified: reel/clip.py:11
from parrot.clients.google.reel.profiles import VideoModelProfile  # verified: reel/profiles.py:34
```

### Existing Signatures to Use
```python
# packages/ai-parrot-client-google/src/parrot/clients/google/reel/omni.py
class OmniClipAdapter:                                                      # line 75
    def __init__(self, owner, downloader, *, max_download_bytes=...)        # line 86
    async def generate(self, *, profile, prompt, output_directory, aspect_ratio, resolution,
                       target_duration_seconds, starting_frame, deadline) -> GeneratedReelClip  # line 97
    async def _normalize_and_materialize(self, interaction, output_directory: Path, *, deadline: float,
                                         operation_id: Optional[str])       # line 199
    async def _measure(self, path: Path) -> Tuple[float, bool]              # line 294
# generate() body: response_format = {"type": "video", "aspect_ratio": aspect_ratio};
#   client = await self._owner.get_client(model=profile.model_id); try: client.aio.interactions.create(
#   agent=profile.model_id, input=prompt, background=False, store=False, stream=False,
#   response_format=response_format, timeout=remaining) ... finally: await client.aio.aclose()
# errors: classify_provider_error(exc, stage="omni_submit"); ReelError(ReelErrorCode.TIMEOUT, ..., stage=, retryable=)
```

### Does NOT Exist
- ~~`OmniClipAdapter.generate_many`~~ — created by this task
- ~~a verified Omni multi-output request field~~ — must be read from the installed `google-genai` (spec §8 Q2)
- ~~`response_format.duration`~~ — intentionally never sent (FEAT-564 spec §3 M4)

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {
      "path": "packages/ai-parrot-client-google/src/parrot/clients/google/reel/omni.py",
      "action": "MODIFY"
    },
    {
      "path": "packages/ai-parrot-client-google/tests/unit/reel/test_reel_omni.py",
      "action": "MODIFY"
    }
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot-client-google/src/parrot/clients/google/reel/omni.py#OmniClipAdapter",
    "sym:packages/ai-parrot-client-google/src/parrot/clients/google/reel/omni.py#OmniClipAdapter.generate",
    "sym:packages/ai-parrot-client-google/src/parrot/clients/google/reel/omni.py#OmniClipAdapter._normalize_and_materialize",
    "sym:packages/ai-parrot-client-google/src/parrot/clients/google/reel/omni.py#OmniClipAdapter._measure"
  ]
}
```

---

## Implementation Notes

### Key Constraints
- Async throughout; `self.logger` (never `print`); Pydantic v2; aiohttp only.
- Hard cut — no deprecation shims (no external consumers).
- Never retry an ambiguous creation failure (same rule as `generate()`).
- Close the owned client in `finally` (same ownership rule as `generate()`).

---

## Implementation Blueprint

### Steps (in order)
1. Read the installed `google-genai` Interactions types to find the multi-output field and how outputs are returned — *why*: spec §8 Q2 is open; never invent a field.
2. Add `generate_many` reusing `generate()`'s deadline, ownership and error classification — *why*: identical failure semantics for reels and façade.
3. Materialise every output (generalise `_normalize_and_materialize` only if it hard-codes a single output) — *why*: each clip must be measured, never trusted.
4. Tests with a mocked client asserting exactly one `interactions.create` call.

### `packages/ai-parrot-client-google/src/parrot/clients/google/reel/omni.py` (MODIFY)
```python
# occurrences: 1 (verified: grep -c 'class OmniClipAdapter:' reel/omni.py)
# AFTER the end of generate() (verified: reel/omni.py:97), before _normalize_and_materialize (:199):
    async def generate_many(
        self,
        *,
        profile: VideoModelProfile,
        prompt: str,
        output_directory: Path,
        aspect_ratio: str,
        number_of_videos: int,
        deadline: float,
    ) -> List[GeneratedReelClip]:
        """Generate ``number_of_videos`` Omni videos in ONE Interactions request.

        Raises:
            ReelValidationError: ``unsupported_option`` when ``number_of_videos`` exceeds
                ``profile.max_outputs_per_request``.
            ReelError: same submission/timeout/download semantics as :meth:`generate`.
        """
        if number_of_videos > profile.max_outputs_per_request:
            raise ReelValidationError(
                ReelErrorCode.UNSUPPORTED_OPTION,
                f"Model {profile.model_id!r} returns at most {profile.max_outputs_per_request} videos per request.",
            )
        # FILL IN: deadline check + owned client + ONE interactions.create carrying the multi-output field — bounded by
        #          generate()'s structure (copy it) and spec §8 Q2 (field read from google-genai, never guessed)
        # FILL IN: materialise + _measure each output; return GeneratedReelClip(backend="omni", submitted_duration_seconds=None, ...)
```
**Why**: the spec fixes `generate_many`'s signature (§3 M2 skeleton). `List` must be imported from `typing` if not already.

### `packages/ai-parrot-client-google/tests/unit/reel/test_reel_omni.py` (MODIFY)
```python
# FILL IN: add tests from Test Specification, reusing the file's existing mocked-client fixtures
```

### FILL IN checklist
- [ ] multi-output request field + response parsing — bounded by spec §8 Q2 (google-genai source)
- [ ] per-output materialisation — bounded by `_normalize_and_materialize` contract

---

## Acceptance Criteria

- [ ] `generate_many(number_of_videos=N)` issues exactly one `interactions.create` and returns N clips
- [ ] over-cap request raises `UNSUPPORTED_OPTION` with zero provider calls
- [ ] existing `generate()` tests unchanged and green

---

## Validation Commands

- `pytest packages/ai-parrot-client-google/tests/unit/reel/test_reel_omni.py -q`

---

## Test Specification

```python
async def test_omni_generate_many_single_request(omni_adapter, mock_client, omni_profile, tmp_path):
    clips = await omni_adapter.generate_many(profile=omni_profile, prompt="p", output_directory=tmp_path,
                                             aspect_ratio="16:9", number_of_videos=2, deadline=far_future())
    assert len(clips) == 2
    assert mock_client.aio.interactions.create.await_count == 1


async def test_omni_generate_many_over_cap(omni_adapter, mock_client, omni_profile, tmp_path):
    with pytest.raises(ReelValidationError):
        await omni_adapter.generate_many(profile=omni_profile, prompt="p", output_directory=tmp_path,
                                         aspect_ratio="16:9", number_of_videos=999, deadline=far_future())
    mock_client.aio.interactions.create.assert_not_awaited()
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
9. **Close** with `scripts/sdd/close_task.sh TASK-4582 model-deprecation-followups verified`
10. **Fill in the Completion Note**, then commit the staged SDD state

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**: <session or agent ID>
**Date**: YYYY-MM-DD
**Notes**:

**Deviations from spec**: none
