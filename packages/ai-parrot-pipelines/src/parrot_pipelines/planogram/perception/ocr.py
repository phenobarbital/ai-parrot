"""Optional local OCR of shape crops (FEAT-574). RapidOCR is imported lazily; without it, text is read by the LLM."""

from __future__ import annotations

import logging
from typing import Optional, Tuple

import cv2
import numpy as np

logger = logging.getLogger(__name__)

_UPSCALE: float = 4.0


class OcrReader:
    """RapidOCR wrapper.

    The import is probed at construction and the engine is built lazily on the first
    ``read`` — inside the worker process when called through the CPU executor.

    Attributes:
        available: False when ``rapidocr`` cannot be imported (the ``planogram`` extra is absent).
    """

    available: bool

    def __init__(self) -> None:
        """Probe the optional ``rapidocr`` dependency (the engine itself is built on first read)."""
        self._engine: Optional[object] = None
        try:
            import rapidocr  # noqa: F401  (availability probe only)

            self.available = True
        except ImportError:
            self.available = False
            logger.info("rapidocr is not installed: shape text will be read by the LLM only")

    def read(self, crop: np.ndarray) -> Tuple[str, float]:
        """Read the text inside a BGR crop. Synchronous and CPU-bound.

        Args:
            crop: BGR crop in source-image pixels.

        Returns:
            ``(text, confidence)`` — texts joined with ``" | "`` and the mean score in [0, 1];
            ``("", 0.0)`` when OCR is unavailable, the crop is empty, or nothing is read.
            Never raises ImportError.
        """
        if not self.available or crop is None or crop.size == 0:
            return "", 0.0
        try:
            if self._engine is None:
                from rapidocr import RapidOCR

                self._engine = RapidOCR()
            upscaled = cv2.resize(crop, None, fx=_UPSCALE, fy=_UPSCALE, interpolation=cv2.INTER_CUBIC)
            result = self._engine(upscaled)  # type: ignore[operator]
        except Exception as exc:  # noqa: BLE001 - OCR is best effort; the LLM reads text otherwise
            logger.warning("Local OCR failed: %s", exc)
            return "", 0.0
        texts = [t for t in (getattr(result, "txts", None) or ()) if t]
        scores = [float(s) for s in (getattr(result, "scores", None) or ())]
        if not texts:
            return "", 0.0
        confidence = sum(scores) / len(scores) if scores else 0.0
        return " | ".join(texts), min(1.0, max(0.0, confidence))


_READER: Optional[OcrReader] = None


def read_crop(crop: np.ndarray) -> Tuple[str, float]:
    """Module-level, picklable entry point using a per-process ``OcrReader`` singleton.

    Args:
        crop: BGR crop in source-image pixels.

    Returns:
        ``(text, confidence)`` as returned by :meth:`OcrReader.read`.
    """
    global _READER  # noqa: PLW0603 - deliberate per-process singleton
    if _READER is None:
        _READER = OcrReader()
    return _READER.read(crop)
