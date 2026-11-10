"""Tolerant PyMuPDF import shared by the PageIndex PDF modules.

PyMuPDF ships under two import names: ``pymupdf`` (current) and ``fitz`` (the legacy alias still
used by older releases). ``pymupdf`` is ``None`` when neither is installed, so callers keep their
existing ``if pymupdf is None`` guards.
"""

from __future__ import annotations

from types import ModuleType
from typing import Optional

pymupdf: Optional[ModuleType]
try:
    import pymupdf
except ImportError:  # pragma: no cover - depends on the installed PyMuPDF release
    try:
        import fitz as pymupdf  # type: ignore[no-redef]
    except ImportError:
        pymupdf = None

__all__ = ["pymupdf"]
