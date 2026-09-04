# TASK-2841: Core convention prerequisites: google/ folder, enum split, LiveVoiceResponse move

**Feature**: FEAT-523 — PEP 420 LLM Client Extraction
**Spec**: `sdd/specs/pep-420-llm-clients.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M
**Depends-on**: none
**Assigned-to**: unassigned
**Parallel**: false — Touches parrot/models/__init__.py and parrot/models/google.py that every following folder-conversion task also edits; must land first.

---

## Context

Spec §2 'Convention first, in core' + §3 Module 1. `google/` is already a folder but its enum lives in `parrot/models/google.py` (mixed with media/voice/video models), `live.py` is flat, and core `protocols.py` imports a type from `live.py` (a future satellite). This task fixes those three things and creates the convention-conformance test that later tasks extend.

---

## Scope

- Create `parrot/clients/google/models.py` holding `GoogleModel` (from `parrot/models/google.py:11`) and `VertexAIModel` (`:280`) byte-identical; remove both from `parrot/models/google.py`, keep every media/voice/video model there.
- Move `LiveVoiceResponse` (and only the types `protocols.py` needs) from `parrot/clients/live.py:176` to `parrot/models/voice.py`; make `live.py` import it from there; change `protocols.py:13` to import from `..models.voice`.
- `git mv parrot/clients/live.py parrot/clients/google/live.py`; update every importer of `parrot.clients.live`.
- Add `provider_keys = ("google",)`, `models = GoogleModel` to `GoogleGenAIClient` (`google/client.py:100`) and `provider_keys = ("gemini-live",)`, `models = GoogleModel` to `GeminiLiveClient`.
- `google/__init__.py` re-exports `GoogleGenAIClient`, `GeminiLiveClient`, `GoogleModel`, `VertexAIModel`.
- Drop `GoogleModel` from `parrot/models/__init__.py:76-86`; keep the media exports.
- Create `tests/unit/clients/test_folder_convention.py` parametrised over `CONVERTED = ["google"]` (later tasks append) asserting the three files exist and the class attrs are present; add `test_google_media_models_intact`.

**NOT in scope**: Changing core call sites that import `GoogleModel` (TASK-2846). Other providers. Factory changes.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/clients/google/models.py` | CREATE | GoogleModel, VertexAIModel |
| `packages/ai-parrot/src/parrot/clients/google/live.py` | MOVE | from clients/live.py |
| `packages/ai-parrot/src/parrot/clients/google/__init__.py` | MODIFY | re-exports + __all__ |
| `packages/ai-parrot/src/parrot/clients/google/client.py` | MODIFY | class attrs; import enum from .models |
| `packages/ai-parrot/src/parrot/models/google.py` | MODIFY | remove GoogleModel/VertexAIModel only |
| `packages/ai-parrot/src/parrot/models/voice.py` | MODIFY | receive LiveVoiceResponse (+ deps) |
| `packages/ai-parrot/src/parrot/models/__init__.py` | MODIFY | drop GoogleModel export |
| `packages/ai-parrot/src/parrot/clients/protocols.py` | MODIFY | import LiveVoiceResponse from ..models.voice |
| `packages/ai-parrot/tests/unit/clients/test_folder_convention.py` | CREATE | conformance test, extended by later tasks |

---

## Codebase Contract (Anti-Hallucination)

> **CRITICAL**: VERIFIED references from `dev` @ `d44045f51` (2026-09-04). Re-verify line
> numbers with `grep`/`read` before relying on them — earlier tasks in this feature move files.

### Verified Imports
```python
from pkgutil import extend_path                                  # parrot/__init__.py:9
from parrot.clients.google import GoogleGenAIClient              # clients/google/client.py:100 (re-exported today)
from parrot.clients.live import GeminiLiveClient                 # clients/live.py:498  → becomes parrot.clients.google.live
from parrot.models.google import GoogleModel, VertexAIModel      # models/google.py:11, :280  → REMOVED by this task
from parrot.models.voice import VoiceCapabilities, VoiceStreamOptions  # models/voice.py:180, :144
from ..models.voice import VoiceCapabilities, VoiceStreamOptions # clients/protocols.py:12
from .live import LiveVoiceResponse                              # clients/protocols.py:13 (to change)
```

### Existing Signatures to Use
```python
# parrot/clients/google/client.py:100
class GoogleGenAIClient(AbstractClient, GoogleGeneration, GoogleAnalysis): ...
# parrot/clients/live.py
class LiveCompletionUsage: ...   # :78
class LiveToolCall: ...          # :135
class VoiceTurnMetadata: ...     # :157
class LiveVoiceResponse: ...     # :176  ← moves to parrot/models/voice.py (take its dataclass deps with it if they are pure data)
class LiveToolAdapter: ...       # :251  (stays in live.py)
class GeminiLiveClient(AbstractClient): ...  # :498
# parrot/models/google.py — classes that STAY: GoogleVoiceModel:76 TTSVoice:100 MusicGenre:134 MusicMood:206
#   MusicGenerationRequest:242 LyriaModel:255 MusicBatchRequest:262 MusicBatchResponse:273 AspectRatio:306
#   ImageResolution:323 FictionalSpeaker:334 ConversationalScriptConfig:349 VoiceProfile:373 VoiceRegistry:419
#   VideoReelScene:467 VideoReelRequest:489
# parrot/models/__init__.py:76-86  from .google import (GoogleModel, TTSVoice, MusicGenre, MusicMood,
#   MusicGenerationRequest, AspectRatio, ImageResolution, VideoReelRequest, VideoReelScene)
```

### Does NOT Exist
- ~~`parrot/clients/google/models.py`~~ — does not exist yet; this task creates it.
- ~~`GoogleGenAIClient.provider_keys` / `.models`~~ — introduced here.
- ~~`parrot.models.voice.LiveVoiceResponse`~~ — not there yet.
- ~~`_ParrotClientsRedirector`~~ — never existed (v0.2 idea, dropped in v0.3). Do NOT add a MetaPathFinder.
- ~~`AbstractClient.conversation_memory`, `create_conversation_memory()`~~ — removed by FEAT-524; clients are memory-less.
- ~~`parrot/clients/openai.py`~~ — the OpenAI client file is `gpt.py` today.
- ~~`parrot.clients.registry`~~ — no registry module; `SUPPORTED_CLIENTS` in `factory.py` is the only registry.

---

## Implementation Notes

### Folder convention (normative, spec §2)
```
parrot/clients/<provider>/
├── __init__.py   # re-exports client class(es) + model enum, __all__
├── client.py     # AbstractClient / OpenAIBaseClient subclass(es)
└── models.py     # <Provider>Model(str, Enum) + capability sets + DEPRECATIONS; pure data
```
Every client class gets: `provider_keys: tuple[str, ...]` (primary key first, every factory alias),
`models: type[Enum]`, optional `deprecated_models: Mapping[str, str] | None = None`.
`models.py` must not import `client.py`. Use `git mv` so history follows the file.
Enum members/values are moved **byte-identical**. Any caller of a renamed module path
(inside `packages/*/src`, `tests/`, `examples/`) is updated in THIS task — the tree must be
green (import-clean, `pytest packages/ai-parrot/tests/unit/clients -q`) when the task ends.

### Key Constraints
Server handlers `lyria_music.py`, `video_reel.py`, `google_generation.py`, `mediagen.py`, `handlers/models/understanding.py` (ai-parrot-server) import media models from `parrot.models.google` — run `python -c 'import parrot.handlers.lyria_music'`-style import checks after the split. `GoogleModel` consumers in core (`conf.py:433`, `loaders/abstract.py:27`) will break at import time when you remove the export — leave them for TASK-2846 **only if** they still resolve via `parrot.models.google`; if you removed the symbol from that module, point them at `parrot.clients.google.models` temporarily so the tree stays green (TASK-2846 finishes the hard cut).

### References in Codebase
- `packages/ai-parrot/src/parrot/embeddings/__init__.py` — `extend_path` pattern (FEAT-201)
- `packages/ai-parrot-embeddings/pyproject.toml` — satellite packaging pattern
- `packages/ai-parrot/src/parrot/clients/google/`, `nova/` — folders that already exist
- `sdd/specs/pep-420-llm-clients.spec.md` §2 map, §6 contract, §7 gotchas

---

## Acceptance Criteria

- [ ] `parrot/clients/google/` has `__init__.py`, `client.py`, `models.py` (+ existing `analysis.py`, `generation.py`, new `live.py`)
- [ ] `from parrot.models.google import GoogleModel` raises ImportError; `from parrot.clients.google import GoogleModel, VertexAIModel` works
- [ ] `from parrot.models.voice import LiveVoiceResponse` works; `parrot/clients/protocols.py` does not import `.live`
- [ ] `pytest packages/ai-parrot/tests/unit/clients -q` green; `ruff check` clean on touched files

---

## Test Specification

```python
# tests/unit/clients/test_folder_convention.py
import importlib, pathlib, enum, pytest
CONVERTED = ["google"]           # later tasks append their providers
@pytest.mark.parametrize("provider", CONVERTED)
def test_three_canonical_files(provider):
    pkg = importlib.import_module(f"parrot.clients.{provider}")
    d = pathlib.Path(pkg.__file__).parent
    assert {(d/f).exists() for f in ("__init__.py","client.py","models.py")} == {True}
@pytest.mark.parametrize("provider", CONVERTED)
def test_client_class_attrs(provider):
    pkg = importlib.import_module(f"parrot.clients.{provider}")
    clients = [getattr(pkg, n) for n in pkg.__all__ if n.endswith("Client")]
    assert clients
    for cls in clients:
        assert cls.provider_keys and isinstance(cls.provider_keys, tuple)
        assert issubclass(cls.models, enum.Enum)
def test_google_media_models_intact():
    from parrot.models.google import TTSVoice, MusicGenre, VideoReelRequest, VoiceRegistry  # noqa
def test_google_model_left_parrot_models():
    with pytest.raises(ImportError):
        from parrot.models.google import GoogleModel  # noqa
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at the path listed above for full context
2. **Check dependencies** — verify `Depends-on` tasks are in `sdd/tasks/completed/`
3. **Verify the Codebase Contract** — before writing ANY code, confirm every import/signature still exists; if a prior task moved it, update the contract FIRST
4. **Update status** in `sdd/tasks/index/pep-420-llm-clients.json` → `"in-progress"` with your session ID
5. **Implement** following the scope, contract and notes above — hard cuts, no shims
6. **Verify** all acceptance criteria are met (run the commands, paste evidence in the note)
7. **Move this file** to `sdd/tasks/completed/TASK-2841-core-convention-google-and-live-voice.md`
8. **Update index** → `"done"`
9. **Fill in the Completion Note** below

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**: <session or agent ID>
**Date**: YYYY-MM-DD
**Notes**:

**Deviations from spec**: none | describe if any
