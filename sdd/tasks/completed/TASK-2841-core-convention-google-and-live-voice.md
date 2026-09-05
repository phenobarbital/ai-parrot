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

- [x] `parrot/clients/google/` has `__init__.py`, `client.py`, `models.py` (+ existing `analysis.py`, `generation.py`, new `live.py`)
- [x] `from parrot.models.google import GoogleModel` raises ImportError; `from parrot.clients.google import GoogleModel, VertexAIModel` works
- [x] `from parrot.models.voice import LiveVoiceResponse` works; `parrot/clients/protocols.py` does not import `.live`
- [x] `pytest packages/ai-parrot/tests/unit/clients -q` green; `ruff check` clean on touched files

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

**Completed by**: sdd-worker (Claude Sonnet 5)
**Date**: 2026-09-04
**Notes**:

Implemented exactly per scope. Commit `77b599141` on
`feat-FEAT-523-pep-420-llm-clients`.

- `parrot/clients/google/models.py` created: `GoogleModel` + `VertexAIModel`
  moved byte-identical from `parrot/models/google.py` (verified member names
  and values unchanged, diffed against the original).
- `LiveVoiceResponse` moved to `parrot/models/voice.py`, and — per the
  contract's own note ("take its dataclass deps with it if they are pure
  data") — its three pure-data dependencies `LiveCompletionUsage`,
  `LiveToolCall`, `VoiceTurnMetadata` moved with it (all `@dataclass`, no
  I/O, no SDK imports). `live.py` (now `google/live.py`) imports all four
  back from `...models.voice` for its own internal use (~30 call sites).
- `git mv clients/live.py clients/google/live.py`; `GeminiLiveClient` gained
  `provider_keys = ("gemini-live",)` / `models = GoogleModel`;
  `GoogleGenAIClient` gained `provider_keys = ("google",)` /
  `models = GoogleModel`.
- `protocols.py` now imports `LiveVoiceResponse` from `..models.voice`
  alongside `VoiceCapabilities`/`VoiceStreamOptions`; no more `.live` import.
- `google/analysis.py` and `google/generation.py` (same-provider-folder,
  not "core call sites") updated to import `GoogleModel` from the new
  `.models` instead of `...models.google` — required for the folder to be
  self-contained per the convention, not part of TASK-2846's cross-package
  hard cut.
- **Blast radius**: the task's own Scope text — "update every importer of
  `parrot.clients.live`" and the Implementation Notes' "point [GoogleModel
  importers] at `parrot.clients.google.models` temporarily so the tree
  stays green" — meant fixing ~40 additional files across `ai-parrot`,
  `ai-parrot-integrations`, `ai-parrot-server`, `ai-parrot-loaders`,
  `ai-parrot-pipelines`, `tests/`, and `examples/`. Full list is in the
  commit. Every one of these is a single import-line change (or a
  `sys.modules` stub-key rename in test scaffolding) — no logic changed.
- `nova/audio.py` also imported the four moved dataclasses via the old
  `..live` path — fixed to `...models.voice` (not listed in the task's
  file table but required for the tree to stay green; nova/ is a sibling
  provider folder, out of TASK-2841's conversion scope itself).

**Deviations from spec**:

1. **`conf.py`**: the contract said to point removed-symbol importers at
   `parrot.clients.google.models` "temporarily" (leaving the full hard cut
   to TASK-2846). For `conf.py` specifically this is impossible: `parrot.
   clients.base` → `parrot.memory` → `parrot.tools` → `parrot.plugins` →
   `parrot.conf` is an existing import chain, so anything under
   `parrot.clients` that `conf.py` imports re-enters
   `parrot.clients.google.__init__` → `.client` → `..base`, which is still
   mid-import — a genuine circular import (verified: reproduced the
   `ImportError: cannot import name 'AbstractClient' from partially
   initialized module 'parrot.clients.base'` before fixing). Since the
   spec's own §3 Module 2 / Integration Points table already prescribes
   `DEFAULT_LLM_MODEL`'s permanent end state as the literal
   `"gemini-flash-latest"` with no `GoogleModel` import, I applied that
   now instead of a workaround that cannot work, with the reasoning
   documented inline in `conf.py`. TASK-2846 has one fewer line to change
   as a result.
2. **Compiled `.so` artifacts**: this worktree had no `.venv` of its own
   (shared venv's editable installs point at the main checkout's
   `packages/*/src`). Copied two pre-built, gitignored `.so` files
   (`parrot/utils/types.cpython-312*.so`,
   `parrot/utils/parsers/toml.cpython-312*.so`) from the main repo purely
   so `PYTHONPATH`-based verification could import `parrot` from this
   worktree. Not committed (confirmed gitignored); no source change.

**Verification evidence**:
- `pytest packages/ai-parrot/tests/unit/clients -q` → 355 passed, 8
  pre-existing failures (verified byte-identical failures against `dev`
  HEAD, unrelated to this change: `test_groq_multiround_usage.py` /
  `test_openai_multiround_usage.py`, a `raw_response` Pydantic validation
  issue with `MagicMock`).
- `pytest tests/unit/clients/test_folder_convention.py -v` → 7/7 passed.
- Broader sanity sweep (not required by the AC, done for confidence given
  the blast radius): `tests/clients`, `tests/voice`, targeted
  `tests/bots/test_voicebot_*` — every failure found was reproduced
  identically on `dev` HEAD before this change.
- `ruff check` clean on every file with substantial new content
  (`google/models.py`, `google/__init__.py`, `google/live.py`,
  `models/voice.py`, `models/google.py`, `models/__init__.py`,
  `protocols.py`, `conf.py`, `nova/audio.py`,
  `tests/unit/clients/test_folder_convention.py`). Pre-existing
  `F841`/`F821`/`E402` findings in files where I only changed one import
  line were spot-checked against `dev` and confirmed pre-existing.
- `ai-parrot-integrations/tests/voice` (137 tests) and the two
  `ai-parrot-server` voice STT test modules collect with zero import
  errors.
