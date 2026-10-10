"""Tests for AudioSegmentCache and recordings (FEAT-649, Module 6)."""
import asyncio
import re
import uuid
from types import SimpleNamespace

import pytest

from parrot_formdesigner.audio import segments
from parrot_formdesigner.audio.recordings import delete_recording, recording_blob_id, store_recording
from parrot_formdesigner.audio.segments import AudioSegmentCache
from parrot_formdesigner.services.blob_storage import AbstractBlobStorage


class _FakeSynth:
    def __init__(self, fail_on=None):
        self.calls = []
        self.fail_on = fail_on
        self.config = SimpleNamespace(mime_format="audio/wav")

    async def synthesize(self, text, *, language=None):
        self.calls.append(text)
        if text == self.fail_on:
            raise RuntimeError("boom")
        return SimpleNamespace(audio=f"WAV:{text}".encode(), mime_format="audio/wav")


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
    yield
    segments._PROCESS_LRU.clear()


async def test_segment_cache_shared_lock_and_key():
    synth, lock = _FakeSynth(), asyncio.Lock()
    a, b = AudioSegmentCache(synth, lock=lock), AudioSegmentCache(synth, lock=lock)
    await a.ensure({"q:1:label": "Hola"}, locale="es", voice=None, form_uid="f", version="1")
    out = await b.ensure({"q:1:label": "Hola"}, locale="es", voice=None, form_uid="f", version="1")
    assert synth.calls == ["Hola"]
    assert out == {"q:1:label": b"WAV:Hola"}
    await b.ensure({"k": "Hola"}, locale="en", voice=None, form_uid="f", version="1")
    await b.ensure({"k": "Hola"}, locale="en", voice="v", form_uid="f", version="1")
    await b.ensure({"k": "Hola"}, locale="en", voice="v", form_uid="f", version="2")
    assert len(synth.calls) == 4


def test_cache_key_varies():
    base = dict(form_uid="f", version="1", locale="es", voice=None, text="x")
    k = AudioSegmentCache.cache_key(**base)
    for change in ({"locale": "en"}, {"voice": "v"}, {"version": "2"}, {"text": "y"}):
        assert AudioSegmentCache.cache_key(**{**base, **change}) != k


async def test_skips_pause_blank_and_none_synth():
    synth = _FakeSynth()
    c = AudioSegmentCache(synth, lock=asyncio.Lock())
    out = await c.ensure({"pause:1": "x", "blank": "  "}, locale="es", voice=None, form_uid="f", version="1")
    assert out == {} and synth.calls == []
    none_cache = AudioSegmentCache(None, lock=asyncio.Lock())
    assert await none_cache.ensure({"a": "b"}, locale="es", voice=None, form_uid="f", version="1") == {}
    assert c.mime() == "audio/wav" and none_cache.mime() == "audio/wav"


async def test_failure_omits_key_and_lru_bounded():
    synth = _FakeSynth(fail_on="bad")
    c = AudioSegmentCache(synth, lock=asyncio.Lock(), max_entries=2)
    out = await c.ensure({"a": "bad", "b": "one", "c": "two", "d": "three"},
                         locale="es", voice=None, form_uid="f", version="1")
    assert set(out) == {"b", "c", "d"}
    assert len(segments._PROCESS_LRU) == 2


def _form_field():
    form = SimpleNamespace(form_uid=uuid.uuid4(), form_id="frm")
    field = SimpleNamespace(field_uid=uuid.uuid4(), field_id="fld")
    return form, field


async def test_recording_blob_id_deterministic():
    fu = uuid.uuid4()
    assert recording_blob_id("s1", fu) == recording_blob_id("s1", fu) == f"voice-s1-{fu}"
    bid = recording_blob_id("we ird/" + "x" * 300, fu)
    assert re.fullmatch(r"[A-Za-z0-9_-]{1,128}", bid)
    assert bid.endswith(str(fu))


async def test_store_overwrites_and_delete_idempotent():
    storage = _MemoryBlobs()
    form, field = _form_field()
    kw = dict(mime="audio/wav", form=form, field=field, session_id="s1", submission_id="sub", tenant=None)
    r1 = await store_recording(storage, audio=b"one", **kw)
    r2 = await store_recording(storage, audio=b"two", **kw)
    assert r1 == r2 and len(storage.blobs) == 1 and storage.blobs[r1] == b"two"
    await delete_recording(storage, r1)
    await delete_recording(storage, r1)
    assert storage.blobs == {}


async def test_delete_never_raises():
    class _Boom(_MemoryBlobs):
        async def delete(self, blob_ref):
            raise OSError("x")

    await delete_recording(_Boom(), "ref")
