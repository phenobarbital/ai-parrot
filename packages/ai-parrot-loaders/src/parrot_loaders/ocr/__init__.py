"""
OCR subpackage for parrot_loaders.

Provides OCR backend abstraction, data models, and a factory function for
selecting the best available OCR backend at runtime.

Public API:
    OCRBlock: Dataclass for a single text region.
    LayoutLine: Dataclass for a horizontal line of text.
    LayoutResult: Dataclass for complete layout analysis.
    OCRBackend: Protocol that all backends must satisfy.
    get_ocr_backend: Factory to select/instantiate an OCR backend.

Example:
    from parrot_loaders.ocr import OCRBlock, get_ocr_backend

    backend = get_ocr_backend("auto")
    blocks = backend.extract(image, language="en")
"""
from .base import OCRBackend
from .models import LayoutLine, LayoutResult, OCRBlock

__all__ = [
    "OCRBlock",
    "LayoutLine",
    "LayoutResult",
    "OCRBackend",
    "get_ocr_backend",
]


def get_ocr_backend(name: str, language: str = "en") -> OCRBackend:
    """Factory function to instantiate an OCR backend by name.

    For ``name="auto"`` the function probes the installed packages in
    priority order and returns the first available backend:
    PaddleOCR > EasyOCR > Tesseract.

    Backends are imported lazily so only the requested backend's
    dependencies need to be installed.

    Args:
        name: Backend identifier. One of: ``"paddleocr"``, ``"tesseract"``,
            ``"easyocr"``, or ``"auto"`` (best available).
        language: Default language code for the backend (e.g. ``"en"``).

    Returns:
        An instantiated OCR backend that satisfies the :class:`OCRBackend`
        protocol.

    Raises:
        ValueError: If ``name`` is not a recognised backend identifier.
        ImportError: If the requested backend (or any backend for ``"auto"``)
            is not installed.
    """
    name = name.lower().strip()

    if name == "paddleocr":
        from .paddle import PaddleOCRBackend

        return PaddleOCRBackend(language=language)

    if name == "tesseract":
        from .tesseract import TesseractBackend

        return TesseractBackend(language=language)

    if name == "easyocr":
        from .easyocr_backend import EasyOCRBackend

        return EasyOCRBackend(language=language)

    if name == "auto":
        # Try PaddleOCR first (best quality), then EasyOCR, then Tesseract.
        for _backend_name, _module, _class in [
            ("paddleocr", ".paddle", "PaddleOCRBackend"),
            ("easyocr", ".easyocr_backend", "EasyOCRBackend"),
            ("tesseract", ".tesseract", "TesseractBackend"),
        ]:
            try:
                import importlib

                mod = importlib.import_module(_module, package=__name__)
                cls = getattr(mod, _class)
                return cls(language=language)
            except (ImportError, Exception):
                continue

        raise ImportError(
            "No OCR backend is available. Install at least one of: "
            "paddleocr (pip install paddleocr paddlepaddle), "
            "easyocr (pip install easyocr), or "
            "tesseract (apt install tesseract-ocr && pip install pytesseract)."
        )

    raise ValueError(
        f"Unknown OCR backend: {name!r}. "
        f"Valid options are: 'paddleocr', 'tesseract', 'easyocr', 'auto'."
    )
