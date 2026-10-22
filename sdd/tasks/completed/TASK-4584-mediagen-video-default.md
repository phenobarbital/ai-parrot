# TASK-4584: /mediagen + VideoGenerationPrompt: no hard-coded Veo default

**Feature**: FEAT-719 — Model Deprecation Follow-ups (Veo → Omni, Computer Use 3.8, gpt-transcribe)
**Spec**: `sdd/specs/model-deprecation-followups.spec.md`
**Status**: pending
**Priority**: medium
**Estimated effort**: S (< 2h)
**Depends-on**: TASK-4583
**Assigned-to**: unassigned

> **Prerequisite**: branch `fix/model-deprecations-2026-10` (the 2026-10-22 deprecation sweep) must be merged into `dev` before this task starts — every anchor below was verified against `origin/dev` 63442566b + that sweep. Re-run each `grep -c` before editing.

---

## Context

Implements spec §3 Module 4. `/mediagen` (action=video) still defaults to `veo-3.1-generate-preview`, and `VideoGenerationPrompt` requires a model and defaults `resolution` to `"720p"`, which Omni rejects.

---

## Scope

- `mediagen.py`: when no model is given for `video`, pass `None` (the façade applies the registry default); image default unchanged.
- `VideoGenerationPrompt.model` → `Optional[str] = None`; `resolution` default → `None`; description/example → `gemini-omni-1.1-flash`.
- Handler test.

**NOT in scope**: the façade itself (TASK-4583); `VideoGenInput` (separate model) unless the same 720p default exists there — check and report.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot-server/src/parrot/handlers/mediagen.py` | MODIFY | drop Veo default |
| `packages/ai-parrot/src/parrot/models/generation.py` | MODIFY | optional model, resolution None, example |
| `packages/ai-parrot-server/tests/handlers/test_mediagen_video_default.py` | CREATE | handler test |

---

## Codebase Contract (Anti-Hallucination)

> Use these exact imports and signatures. Verify anything not listed before using it.

### Verified Imports
```python
from parrot.models import VideoGenerationPrompt  # verified: used by examples/next/google.py and generation.py
```

### Existing Signatures to Use
```python
# packages/ai-parrot-server/src/parrot/handlers/mediagen.py
default_model = "gemini-nano-banana-2.1" if action == "image" else "veo-3.1-generate-preview"   # line 82
model = data.get("model") or default_model
client = GoogleGenAIClient(model=model)
r = await client.generate_videos(prompt=prompt_data)                                          # line 186
# packages/ai-parrot/src/parrot/models/generation.py
class VideoGenerationPrompt(BaseModel)                                                         # line 138
    model: str = Field(..., description="The video generation model to use (e.g., 'veo-3.1-generate-preview').")  # line 146-149
    resolution: Optional[str] = Field(default="720p", ...)                                     # line 156
    json_schema_extra example "model": "veo-3.1-generate-preview"                             # line 190
```

### Does NOT Exist
- ~~a video default model constant in the server package~~ — the registry owns it; do not add one

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {
      "path": "packages/ai-parrot-server/src/parrot/handlers/mediagen.py",
      "action": "MODIFY"
    },
    {
      "path": "packages/ai-parrot/src/parrot/models/generation.py",
      "action": "MODIFY"
    },
    {
      "path": "packages/ai-parrot-server/tests/handlers/test_mediagen_video_default.py",
      "action": "CREATE"
    }
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot/src/parrot/models/generation.py#VideoGenerationPrompt"
  ]
}
```

---

## Implementation Notes

### Key Constraints
- Async throughout; `self.logger` (never `print`); Pydantic v2; aiohttp only.
- Hard cut — no deprecation shims (no external consumers).
- `GoogleGenAIClient(model=None)` must keep working for the video branch — verify before relying on it.

---

## Implementation Blueprint

### Steps (in order)
1. Change the handler default to `None` for video — *why*: one source of truth (registry).
2. Make `VideoGenerationPrompt.model` optional and `resolution` default `None` — *why*: Omni rejects resolution (spec §7).
3. Update description/example — *why*: dead Veo id in public schema.
4. Handler test asserting `prompt_data.model is None` when absent.

### `packages/ai-parrot-server/src/parrot/handlers/mediagen.py` (MODIFY)
```python
# occurrences: 1 (verified: grep -c 'default_model = "gemini-nano-banana-2.1" if action == "image" else "veo-3.1-generate-preview"' mediagen.py) — :82
        default_model = "gemini-nano-banana-2.1" if action == "image" else None
        # FILL IN: ensure GoogleGenAIClient(model=None) and the VideoGenerationPrompt construction accept None
```
### `packages/ai-parrot/src/parrot/models/generation.py` (MODIFY)
```python
# occurrences: 1 (verified: grep -c "The video generation model to use (e.g., 'veo-3.1-generate-preview')." generation.py) — :148
    model: Optional[str] = Field(
        None,
        description="Video model id; None uses the registry default for the API surface (e.g. 'gemini-omni-1.1-flash').",
    )
# resolution (:156): default=None
# example (:190): "model": "gemini-omni-1.1-flash" — FILL IN: drop "resolution"/"duration" from the example (Omni rejects them)
```

### FILL IN checklist
- [ ] handler path with model None end-to-end — bounded by TASK-4583 façade contract
- [ ] example payload valid for Omni — bounded by spec AC-3

---

## Acceptance Criteria

- [ ] `/mediagen` video with no model passes `None` down
- [ ] `VideoGenerationPrompt(prompt="x")` validates; `resolution` is `None`
- [ ] no `veo-3.1-*-preview` literal remains in either file

---

## Validation Commands

- `pytest packages/ai-parrot-server/tests/handlers/test_mediagen_video_default.py -q`
- `pytest packages/ai-parrot-server/tests/handlers/test_video_reel_inputs.py -q`

---

## Test Specification

```python
from parrot.models import VideoGenerationPrompt


def test_video_prompt_defaults():
    p = VideoGenerationPrompt(prompt="x")
    assert p.model is None and p.resolution is None

# FILL IN: handler test patching GoogleGenAIClient.generate_videos and asserting prompt.model is None
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
9. **Close** with `scripts/sdd/close_task.sh TASK-4584 model-deprecation-followups verified`
10. **Fill in the Completion Note**, then commit the staged SDD state

---

## Completion Note

Two seat attempts returned empty deliveries; attempt 3 implemented by the sdd-worker orchestrator.

**Divergence (flag for reviewer)**: `parrot.models.VideoGenerationPrompt` (the class the handler and `GoogleGeneration.generate_videos` actually use) is defined in `packages/ai-parrot/src/parrot/models/outputs.py`, NOT `generation.py` — `models/__init__.py` imports it from `.outputs`. The `generation.py` class named in the task contract is a shadowed duplicate. Both were updated (model Optional/None, resolution None); `outputs.py` was added to the file list because the acceptance criteria are unmeetable otherwise. Also, the mediagen image default in the repo is `gemini-3.1-flash-image`, left unchanged.

Validation: new handler test 2 passed; tests/handlers/test_mediagen_handler.py 7 passed.
