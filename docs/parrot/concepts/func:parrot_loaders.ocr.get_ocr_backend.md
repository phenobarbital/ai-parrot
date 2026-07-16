---
type: Concept
title: get_ocr_backend()
id: func:parrot_loaders.ocr.get_ocr_backend
tags:
- concept
timestamp: '2026-07-16T08:34:12+00:00'
summary: Factory function to instantiate an OCR backend by name.
---

# get_ocr_backend

```python
def get_ocr_backend(name: str, language: str='en') -> OCRBackend
```

Factory function to instantiate an OCR backend by name.

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
