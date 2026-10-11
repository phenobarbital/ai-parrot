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

NARRATION_TEMPLATE_REV = "1"  # bump when narration.yaml semantics change (S7 cache identity)
_SYNTH_LOCK: asyncio.Lock = asyncio.Lock()  # one per process (owner decision)
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
    def cache_key(
        *, form_uid: str, version: str, locale: str, voice: str | None, text: str, variant: str = ""
    ) -> tuple[str, ...]:
        """(form_uid, version, locale, voice, template_rev, sha1(text), synthesis variant) — S7.

        ``variant`` is the effective synthesis config (output mime + backend/model): the same text rendered by a
        different backend or container format must never share bytes.
        """
        digest = hashlib.sha1(text.encode("utf-8")).hexdigest()  # noqa: S324 — cache key, not security
        return (form_uid, version, locale, voice or "", NARRATION_TEMPLATE_REV, digest, variant)

    def variant(self) -> str:
        """Identity of the effective synthesis config: ``mime|backend|model``."""
        cfg = getattr(self.synthesizer, "config", None)
        parts = (self.mime(), getattr(cfg, "backend", None), getattr(cfg, "model", None))
        return "|".join(p if isinstance(p, str) else "" for p in parts)

    def mime(self) -> str:
        """MIME of produced audio (synthesiser config), ``audio/wav`` when unknown."""
        cfg = getattr(self.synthesizer, "config", None)
        return getattr(cfg, "mime_format", None) or "audio/wav"

    async def ensure(
        self, items: dict[str, str], *, locale: str, voice: str | None, form_uid: str, version: str
    ) -> dict[str, bytes]:
        """Synthesise missing keys sequentially under the shared lock; return key → bytes."""
        out: dict[str, bytes] = {}
        if self.synthesizer is None:
            return out
        for seg_key, text in items.items():
            if seg_key.startswith("pause:") or not text.strip():
                continue
            ck = self.cache_key(
                form_uid=form_uid, version=version, locale=locale, voice=voice, text=text, variant=self.variant()
            )
            cached = self._session.get(ck) or _PROCESS_LRU.get(ck)
            if cached is None:
                async with self.lock:
                    cached = _PROCESS_LRU.get(ck)
                    if cached is None:
                        try:
                            result = await self.synthesizer.synthesize(text, language=locale)
                            cached = result.audio
                        except Exception as exc:  # noqa: BLE001 — text-only fallback for this key
                            self.logger.warning("Segment synthesis failed for %s: %s", seg_key, type(exc).__name__)
                            continue
                        self.logger.debug("Synthesised %s (%d bytes)", seg_key, len(cached))
                    _PROCESS_LRU[ck] = cached
                    _PROCESS_LRU.move_to_end(ck)
                    while len(_PROCESS_LRU) > self.max_entries:
                        _PROCESS_LRU.popitem(last=False)
            if cached is not None:
                self._session[ck] = cached
                out[seg_key] = cached
        return out
