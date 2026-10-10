# TASK-4218: AudioSegmentCache (shared synthesiser + lock, LRU) and blob recordings with deterministic ids

**Feature**: FEAT-649 — Audio Form Interaction Workflow
**Spec**: `sdd/specs/audio-form-interaction-workflow.spec.md`
**Status**: pending
**Priority**: medium
**Estimated effort**: M (2-4h)
**Depends-on**: none
**Assigned-to**: unassigned

---

## Context

Implements spec §3 **Module 6**. Two I/O helpers the WebSocket adapter (TASK-4227)
calls when the pure engine requests them:

1. **`AudioSegmentCache`** — pre-synthesises narration segments (protocol v2
   `audio_segment` prefetch). Today every handler instance owns its own synthesiser
   and an ad-hoc `_audio_cache: dict[int, str]` (`api/audio_ws.py:230`, `:1237-1330`,
   `:1414`). The owner decided **one shared synthesiser per process behind an
   `asyncio.Lock`** (ONNX memory, §7) and a cache keyed by
   `(form_uid, version, locale, voice, template_rev, sha1(text))` (S7, AC17).
2. **Recordings** — every spoken answer's audio is persisted to blob storage with a
   **deterministic** `blob_id = f"voice-{session_id}-{field_uid}"` so a re-answer
   overwrites the same blob (AC8). `data_url` is never produced server-side.

---

## Scope

- Create `audio/segments.py`: module-level `_SYNTH_LOCK`, `NARRATION_TEMPLATE_REV`,
  a bounded process-wide LRU, and `AudioSegmentCache` (`__init__`, `ensure`, `mime`).
- `ensure(items, *, locale, voice, form_uid, version)` synthesises **only missing**
  keys, sequentially, under the shared lock; returns `key → bytes` for every key it
  could synthesise (keys starting with `pause:` are skipped — client-side pauses).
  Synthesis failure for one key logs a warning and omits that key (text-only for it).
  `synthesizer is None` ⇒ returns `{}` (text-only session, §7 "No TTS").
- Create `audio/recordings.py`: `recording_blob_id`, `store_recording`, `delete_recording`.
- `store_recording` builds `BlobMetadata(form_uid, form_id, field_uid, field_id,
  submission_id, tenant, content_type=mime, size_bytes=len(audio), blob_id=recording_blob_id(...))`
  and calls `storage.put(<async iterator yielding audio once>, metadata=...)`.
- Write `test_audio_segments_recordings.py` (shared synthesiser called once for identical
  text across two caches; key includes locale/voice/version; deterministic blob id;
  re-store overwrites same ref; delete idempotent; `pause:` keys skipped).

**NOT in scope**: deciding *when* to prefetch or to store (engine TASK-4225/4226 via
`Synthesize` / `StoreBlob` outbound); `store_recordings=False` handling (engine simply
does not emit `StoreBlob`); obtaining the shared synthesiser instance (adapter,
TASK-4227, via `get_shared_synthesizer`); removing the old handler code (TASK-4227).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/parrot-formdesigner/src/parrot_formdesigner/audio/segments.py` | CREATE | `AudioSegmentCache`, `_SYNTH_LOCK`, process LRU |
| `packages/parrot-formdesigner/src/parrot_formdesigner/audio/recordings.py` | CREATE | `recording_blob_id`, `store_recording`, `delete_recording` |
| `packages/parrot-formdesigner/tests/formdesigner/test_audio_segments_recordings.py` | CREATE | unit tests |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from parrot_formdesigner.core.schema import FormField, FormSchema                       # core/schema.py:65, :401
from parrot_formdesigner.services.blob_storage import AbstractBlobStorage, BlobMetadata   # services/blob_storage.py:119, :55
# optional — TYPE_CHECKING only (pattern api/audio_ws.py:47-50)
from parrot.voice.tts.synthesizer import VoiceSynthesizer                               # packages/ai-parrot-integrations/src/parrot/voice/tts/synthesizer.py:23
```

#### Provided by dependency tasks
- none (this task only uses existing code).

### Existing Signatures to Use
```python
# packages/ai-parrot-integrations/src/parrot/voice/tts/synthesizer.py:124
async def synthesize(self, text: str, *, language: Optional[str] = None) -> SynthesisResult
#   SynthesisResult(audio: bytes, mime_format: str, duration_s: ...)   # tts/models.py:115-146
# synthesizer.py:186 — async def get_shared_synthesizer(config: TTSConfig) -> VoiceSynthesizer  (callers must NOT close it)
#   self.config.mime_format — the synthesiser's configured MIME (synthesizer.py:165)
# services/blob_storage.py:55-93
class BlobMetadata(BaseModel):   # extra="forbid"
    form_uid: uuid.UUID; form_id: str; field_uid: uuid.UUID; field_id: str; submission_id: str | None = None
    tenant: str | None = None; content_type: str; size_bytes: int
    blob_id: str | None = Field(default=None, pattern=r"^[A-Za-z0-9_-]{1,128}$")
# services/blob_storage.py:131 — async def put(self, stream: AsyncIterator[bytes], *, metadata: BlobMetadata) -> str
#   NOTE: the stream must be an ASYNC iterator (backends `async for chunk in stream`, :287) — not `iter([audio])`.
#   Pattern: services/thumbnail.py:90-93 (`async def _stream(): yield thumb_bytes`).
# services/blob_storage.py:169 — async def delete(self, blob_ref: str) -> None   (idempotent)
# services/blob_storage.py:241-242 — key = f"{prefix}{form_uid}/{field_uid}/{blob_id or uuid4}"  → same blob_id overwrites
# core/schema.py: FormSchema.form_uid: uuid.UUID; .form_id: str; .version: str (:453-455); FormField.field_uid/.field_id (:123-124)
```

### Does NOT Exist
- ~~`audio/segments.py`~~, ~~`audio/recordings.py`~~, ~~`AudioSegmentCache`~~, ~~`store_recording`~~ — created here.
- ~~`VoiceSynthesizer.synthesize_to_base64()`~~, ~~`VoiceSynthesizer.synthesize_many()`~~ — one text per `synthesize()` call.
- ~~`AbstractBlobStorage.put_bytes()`~~ — only `put(stream, metadata=)`.
- ~~`data_url` generation~~ — never server-side (AC8).
- ~~A runtime import of `parrot.voice`~~ here — type-only.

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {"path": "packages/parrot-formdesigner/src/parrot_formdesigner/audio/segments.py", "action": "CREATE"},
    {"path": "packages/parrot-formdesigner/src/parrot_formdesigner/audio/recordings.py", "action": "CREATE"},
    {"path": "packages/parrot-formdesigner/tests/formdesigner/test_audio_segments_recordings.py", "action": "CREATE"}
  ],
  "contract_symbols": [
    "sym:packages/parrot-formdesigner/src/parrot_formdesigner/services/blob_storage.py#AbstractBlobStorage.put",
    "sym:packages/parrot-formdesigner/src/parrot_formdesigner/services/blob_storage.py#AbstractBlobStorage.delete",
    "sym:packages/parrot-formdesigner/src/parrot_formdesigner/services/blob_storage.py#BlobMetadata",
    "sym:packages/ai-parrot-integrations/src/parrot/voice/tts/synthesizer.py#VoiceSynthesizer.synthesize"
  ]
}
```

---

## Implementation Notes

### Key Constraints
- Synthesis is **sequential** per call and serialised process-wide by `_SYNTH_LOCK` (one ONNX inference at a time).
- The process LRU is shared by all caches in the process (module-level `OrderedDict`), bounded by the first cache's `max_entries` (or a module constant) — evict oldest on insert.
- Per-instance dict avoids re-hashing within a session; process LRU dedups across sessions (AC17: identical text synthesised once per `(form_uid, version, locale, voice, text)`).
- `recording_blob_id` must satisfy `^[A-Za-z0-9_-]{1,128}$`: replace any other character in `session_id` with `_` and truncate the session part so the total stays ≤ 128.
- Never log audio bytes; log key counts and sizes at DEBUG.

---

## Implementation Blueprint

### Steps (in order)
1. Write `segments.py` — *why*: AC17 cache identity and lock.
2. Write `recordings.py` — *why*: AC8 deterministic ids.
3. Write tests with a counting fake synthesiser and an in-memory `AbstractBlobStorage` subclass.

### `packages/parrot-formdesigner/src/parrot_formdesigner/audio/segments.py` (CREATE)
```python
"""Pre-synthesised narration segments (FEAT-649, Module 6)."""
from __future__ import annotations

import asyncio
import hashlib
import logging
from collections import OrderedDict
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from parrot.voice.tts.synthesizer import VoiceSynthesizer

logger = logging.getLogger(__name__)

NARRATION_TEMPLATE_REV = "1"   # bump when narration.yaml semantics change (S7 cache identity)
_SYNTH_LOCK: asyncio.Lock = asyncio.Lock()   # one per process (owner decision)
_PROCESS_LRU: "OrderedDict[tuple[str, ...], bytes]" = OrderedDict()


class AudioSegmentCache:
    """Synthesise and cache narration segments with one shared synthesiser per process."""

    def __init__(self, synthesizer: "VoiceSynthesizer | None", *, lock: asyncio.Lock, max_entries: int = 512) -> None:
        self.synthesizer = synthesizer
        self.lock = lock
        self.max_entries = max_entries
        self._session: dict[tuple[str, ...], bytes] = {}
        self.logger = logging.getLogger(__name__)

    @staticmethod
    def cache_key(*, form_uid: str, version: str, locale: str, voice: str | None, text: str) -> tuple[str, ...]:
        """(form_uid, version, locale, voice, template_rev, sha1(text)) — S7."""
        digest = hashlib.sha1(text.encode("utf-8")).hexdigest()  # noqa: S324 — cache key, not security
        return (form_uid, version, locale, voice or "", NARRATION_TEMPLATE_REV, digest)

    def mime(self) -> str:
        """MIME of produced audio (synthesiser config), ``audio/wav`` when unknown."""
        cfg = getattr(self.synthesizer, "config", None)
        return getattr(cfg, "mime_format", None) or "audio/wav"

    async def ensure(self, items: dict[str, str], *, locale: str, voice: str | None, form_uid: str,
                     version: str) -> dict[str, bytes]:
        """Synthesise missing keys sequentially under the shared lock; return key → bytes."""
        out: dict[str, bytes] = {}
        if self.synthesizer is None:
            return out
        for seg_key, text in items.items():
            if seg_key.startswith("pause:") or not text.strip():
                continue
            ck = self.cache_key(form_uid=form_uid, version=version, locale=locale, voice=voice, text=text)
            cached = self._session.get(ck) or _PROCESS_LRU.get(ck)
            if cached is None:
                async with self.lock:
                    # FILL IN: re-check _PROCESS_LRU inside the lock (another session may have filled it); else
                    #   `await self.synthesizer.synthesize(text, language=locale)` → result.audio; on Exception log a
                    #   warning with seg_key only and `continue`; insert into _PROCESS_LRU with move_to_end + evict
                    #   oldest while len > self.max_entries — bounded by AC17, spec §3 M6
                    pass
            if cached is not None:
                self._session[ck] = cached
                out[seg_key] = cached
        return out
```
**Why this shape**: `lock` is injected (the adapter passes `_SYNTH_LOCK`) so tests can use their own lock; the cache key helper is static so tests assert identity without synthesising. Creating `asyncio.Lock()` at import time is safe on Python ≥ 3.10 (no loop binding until first use).

### `packages/parrot-formdesigner/src/parrot_formdesigner/audio/recordings.py` (CREATE)
```python
"""Blob persistence for spoken-answer recordings (FEAT-649, Module 6)."""
from __future__ import annotations

import logging
import re
import uuid
from collections.abc import AsyncIterator

from ..core.schema import FormField, FormSchema
from ..services.blob_storage import AbstractBlobStorage, BlobMetadata

logger = logging.getLogger(__name__)

_SAFE = re.compile(r"[^A-Za-z0-9_-]")


def recording_blob_id(session_id: str, field_uid: uuid.UUID) -> str:
    """``f"voice-{session_id}-{field_uid}"`` — matches BlobMetadata.blob_id regex (services/blob_storage.py:93)."""
    suffix = f"-{field_uid}"
    safe_session = _SAFE.sub("_", session_id)[: 128 - len("voice-") - len(suffix)]
    return f"voice-{safe_session}{suffix}"


async def _one_chunk(data: bytes) -> AsyncIterator[bytes]:
    yield data


async def store_recording(storage: AbstractBlobStorage, *, audio: bytes, mime: str, form: FormSchema, field: FormField,
                          session_id: str, submission_id: str, tenant: str | None) -> str:
    """storage.put(<one-chunk async stream>, metadata=BlobMetadata(...)) → blob_ref; same session+field overwrites."""
    metadata = BlobMetadata(
        form_uid=form.form_uid,
        form_id=form.form_id,
        field_uid=field.field_uid,
        field_id=field.field_id,
        submission_id=submission_id,
        tenant=tenant,
        content_type=mime,
        size_bytes=len(audio),
        blob_id=recording_blob_id(session_id, field.field_uid),
    )
    blob_ref = await storage.put(_one_chunk(audio), metadata=metadata)
    logger.debug("Stored recording for field %s (%d bytes)", field.field_id, len(audio))
    return blob_ref


async def delete_recording(storage: AbstractBlobStorage, blob_ref: str) -> None:
    """Delete a stored recording; idempotent, never raises for a missing blob."""
    try:
        await storage.delete(blob_ref)
    except Exception as exc:  # noqa: BLE001 — cleanup is best-effort (cascade_clear / failed commit)
        logger.warning("delete_recording failed: %s", type(exc).__name__)
```
**Why this shape**: deterministic `blob_id` + the backend's `{form_uid}/{field_uid}/{blob_id}` key gives overwrite-on-re-record for free; the async one-chunk generator follows `services/thumbnail.py:90-93` because `put()` consumes an async iterator (the spec's `iter([audio])` would fail).

### FILL IN checklist
- [ ] `AudioSegmentCache.ensure` — locked re-check, synthesise, LRU insert/evict, per-key failure; AC17

---

## Acceptance Criteria

- [ ] Two `AudioSegmentCache` instances sharing one fake synthesiser synthesise identical text once (process LRU).
- [ ] Changing locale, voice or version produces a different cache key.
- [ ] `pause:` keys and blank texts are never synthesised; `synthesizer=None` returns `{}`.
- [ ] `recording_blob_id` is deterministic, matches `^[A-Za-z0-9_-]{1,128}$`, and storing twice for the same session+field yields the same `blob_ref` (overwrite).
- [ ] `delete_recording` never raises.
- [ ] `ruff check` passes on both modules.

---

## Validation Commands

- `pytest packages/parrot-formdesigner/tests/formdesigner/test_audio_segments_recordings.py -q`

---

## Test Specification

```python
# packages/parrot-formdesigner/tests/formdesigner/test_audio_segments_recordings.py
import asyncio
import uuid

import pytest

from parrot_formdesigner.audio import segments
from parrot_formdesigner.audio.recordings import delete_recording, recording_blob_id, store_recording
from parrot_formdesigner.audio.segments import AudioSegmentCache
from parrot_formdesigner.services.blob_storage import AbstractBlobStorage


class _FakeSynth:
    def __init__(self):
        self.calls = []
        self.config = type("C", (), {"mime_format": "audio/wav"})()

    async def synthesize(self, text, *, language=None):
        self.calls.append(text)
        return type("R", (), {"audio": f"WAV:{text}".encode(), "mime_format": "audio/wav"})()


class _MemoryBlobs(AbstractBlobStorage):
    def __init__(self):
        self.blobs = {}

    async def put(self, stream, *, metadata):
        ref = f"mem://{metadata.form_uid}/{metadata.field_uid}/{metadata.blob_id}"
        self.blobs[ref] = b"".join([c async for c in stream])
        return ref

    async def get(self, blob_ref):
        yield self.blobs[blob_ref]

    async def delete(self, blob_ref):
        self.blobs.pop(blob_ref, None)


@pytest.fixture(autouse=True)
def _clear_lru():
    segments._PROCESS_LRU.clear()


async def test_segment_cache_shared_lock_and_key():
    synth, lock = _FakeSynth(), asyncio.Lock()
    a, b = AudioSegmentCache(synth, lock=lock), AudioSegmentCache(synth, lock=lock)
    await a.ensure({"q:1:label": "Hola"}, locale="es", voice=None, form_uid="f", version="1")
    await b.ensure({"q:1:label": "Hola"}, locale="es", voice=None, form_uid="f", version="1")
    assert synth.calls == ["Hola"]
    # FILL IN: different locale/voice/version → new synthesis; pause: keys skipped; synthesizer None → {}


async def test_recording_blob_id_deterministic(): ...       # FILL IN: same ref twice, regex, unsafe session chars
```

---

## Agent Instructions

1. **Work in the feature worktree** — never on `dev`
   (`python -m scripts.sdd.ensure_worktree --slug audio-form-interaction-workflow --feature-id FEAT-649`).
2. **Read the spec** (§3 Module 6, §7 ONNX memory, §9 S7/S8).
3. **Check dependencies** — none.
4. **Verify the Codebase Contract** — re-read `services/blob_storage.py:55-170` and `tts/synthesizer.py:124-170`.
5. **Update status** in the per-spec index → `"in-progress"` and commit only that file.
6. **Implement** from the blueprint; complete every `# FILL IN:`; never change a fixed signature or path.
7. **Verify** — run the Validation Commands with `PYTHONPATH=packages/parrot-formdesigner/src`.
8. **Commit the code** — stage only the files listed above.
9. **Close the task** with `scripts/sdd/close_task.sh TASK-4218 audio-form-interaction-workflow verified`.
10. **Fill in the Completion Note**, then commit the staged SDD state.

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**:
**Date**:
**Notes**:

**Deviations from spec**:
