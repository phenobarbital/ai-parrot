# TASK-3428: Lazy optional `OcrReader` + `pyproject.toml` extra and direct dependency declarations

**Feature**: FEAT-574 — New Planogram Compliance Pipeline
**Spec**: `sdd/specs/new-planogram-pipeline.spec.md`
**Status**: pending
**Priority**: medium
**Estimated effort**: S (< 2h)
**Depends-on**: TASK-3418
**Assigned-to**: unassigned

---

## Context

Spec §3 **Module 8** (constraint "local OCR is an optional extra, with lazy imports"). Stage 1 of
the new cycle reads the text inside each detected shape with RapidOCR **when it is installed**;
without it the pipeline still runs, the LLM reads the text, and the result reports
`ocr_available=False`. This task delivers the reader and is the **single owner of every
`pyproject.toml` edit in this feature**:

- new extra `planogram = ["rapidocr>=3.9", "onnxruntime>=1.20"]`;
- `numpy`, `pillow`, `rapidfuzz` declared directly (used by the package, only transitive today);
- OpenCV stays a hard dependency — it is **not** moved into the extra.

> **EXCLUSIVE task (`parallel: false`)** — it edits a dependency manifest. Edit
> `pyproject.toml` **declaratively only**: never run `uv sync`, `uv lock`, `uv add` or `pip install`
> in the worktree. The shared `.venv` already has `rapidocr` 3.9.2 and `onnxruntime` 1.30.0
> installed; nothing needs installing to run this task's tests.

---

## Scope

- Create `planogram/perception/ocr.py` with `OcrReader` and the picklable module-level `read_crop`.
- Edit `packages/ai-parrot-pipelines/pyproject.toml`: three direct dependencies + the `planogram` extra.
- Unit tests that pass **with or without** RapidOCR installed.

**NOT in scope**: the bounded process executor that will call `read_crop` from worker processes
(another task); deciding *which* crops to read (type hooks); price parsing; any `uv.lock` change;
other distributions' `pyproject.toml`.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/perception/ocr.py` | CREATE | `OcrReader`, `read_crop` |
| `packages/ai-parrot-pipelines/pyproject.toml` | MODIFY | direct deps + `[project.optional-dependencies] planogram` |
| `packages/ai-parrot-pipelines/tests/planogram_cycle/test_ocr_reader.py` | CREATE | Unit tests |

---

## Codebase Contract (Anti-Hallucination)

> **CRITICAL**: VERIFIED references. **DO NOT** invent imports, attributes or methods not listed here.

### Verified Imports
```python
import logging                     # stdlib — module-level `logger = logging.getLogger(__name__)` (there is no `self.logger` owner here)
from typing import Optional, Tuple
import cv2                         # opencv-python-headless>=4.8 — hard dep (pyproject.toml:30)
import numpy as np                 # installed 2.4.6; declared directly BY THIS TASK
# LAZY — only inside methods, never at module scope:
#   import rapidocr                       (availability probe)
#   from rapidocr import RapidOCR         (engine construction on first read)
# tests
from parrot_pipelines.planogram.perception.ocr import OcrReader, read_crop
```

### Existing Signatures to Use
```python
# RapidOCR 3.9.2 (installed in the shared venv; verified by introspection 2026-09-18):
#   engine = RapidOCR()
#   result = engine(img_bgr_ndarray)
#   result.txts    -> tuple[str, ...] | None
#   result.scores  -> tuple[float, ...] | None      (one score per text)
#   RapidOCROutput dataclass fields: img, boxes, txts, scores, word_results, elapse_list, elapse, viser

# Pattern reference (ALGORITHMIC REFERENCE ONLY — never import it) — examples/planogram/plancheck/prices.py:72-107
class TagOcr:
    available: bool
    def __init__(self) -> None:          # :77  try: import rapidocr → available True / except ImportError → False + warning
    def read(self, crop: np.ndarray) -> str:   # :87
        # if not self.available or crop is None or crop.size == 0: return ""            :96
        # if self._engine is None: from rapidocr import RapidOCR; self._engine = RapidOCR()   :99-102
        # upscaled = cv2.resize(crop, None, fx=4, fy=4, interpolation=cv2.INTER_CUBIC)  :104
        # result = self._engine(upscaled); texts = result.txts or ()                    :105-106

# packages/ai-parrot-pipelines/pyproject.toml  (50 lines)
#   :28-32  dependencies = [ "ai-parrot>=1.0.4", "opencv-python-headless>=4.8", "pytesseract>=0.3.13", ]
#   :34     [project.urls]
#   :46-47  [tool.setuptools.package-data]  "parrot_pipelines" = ["py.typed", "*.sql"]
#   :49-50  [tool.uv.sources]  ai-parrot = { workspace = true }
# packages/ai-parrot/pyproject.toml:282  "rapidfuzz>=3.0"   (the version floor already used by core)
```

### Does NOT Exist
- ~~`[project.optional-dependencies]` in `packages/ai-parrot-pipelines/pyproject.toml`~~ — section absent; this task adds it.
- ~~`rapidocr` / `onnxruntime` declared in any workspace `pyproject.toml`~~ — installed in the venv, declared nowhere.
- ~~`numpy`, `pillow`, `rapidfuzz` declared by `ai-parrot-pipelines`~~ — transitive only today.
- ~~a module-level `import rapidocr` anywhere in the package~~ — and there must never be one (AC: importing the module must work without the extra).
- ~~`result.text` / `result.confidence` on RapidOCR output~~ — the fields are `txts` and `scores`.
- ~~`self.logger` in this module~~ — `OcrReader` is a plain class with no pipeline; use the module-level `logger`.
- ~~importing `onnxruntime` directly~~ — it is RapidOCR's backend; never import it.
- ~~a `conftest.py` fixture for OCR~~ — build images inline.

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {
      "path": "packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/perception/ocr.py",
      "action": "CREATE"
    },
    {
      "path": "packages/ai-parrot-pipelines/pyproject.toml",
      "action": "MODIFY"
    },
    {
      "path": "packages/ai-parrot-pipelines/tests/planogram_cycle/test_ocr_reader.py",
      "action": "CREATE"
    }
  ],
  "contract_symbols": []
}
```

---

## Implementation Notes

### Key Constraints
- **Lazy in two steps**: probe the import at construction (`available`), build the engine on the
  **first `read`** — so that when `read_crop` runs inside a worker process the ONNX model loads in
  that process, not in the parent.
- `read` is synchronous and CPU-bound by design; async callers go through the executor task's
  pool. Do not add `async` here and do not call it from the event loop in tests of other tasks.
- `read` **never raises `ImportError`** and never raises for an empty/`None` crop — it returns
  `("", 0.0)`. An engine failure at run time is logged (`logger.warning`) and also yields `("", 0.0)`.
- Return value: texts joined with `" | "`, confidence = arithmetic mean of `result.scores`
  (0.0 when there are none), clamped to `[0.0, 1.0]`.
- `read_crop` must be a **module-level function** (picklable for `ProcessPoolExecutor`) using one
  per-process `OcrReader` singleton.
- `pyproject.toml`: keep the existing three dependencies and their order; append the new ones.
  `pillow` and `numpy` unpinned, `rapidfuzz>=3.0` (spec §7 External Dependencies).
- The directory `planogram/perception/` may not exist yet in your worktree if no other perception
  task has merged: create the directory if needed, but create **only** `ocr.py` in it (the package
  `__init__.py` belongs to another task — a directory without it is still importable as a nested
  namespace package, so your tests run either way).
- Run tests with `PYTHONPATH=packages/ai-parrot-pipelines/src:packages/ai-parrot/src`.

### References in Codebase
- `examples/planogram/plancheck/prices.py:72-107` — lazy-OCR pattern to re-implement (not import)

---

## Implementation Blueprint

> **CRITICAL — Executor-ready starting point.** Write each block nearly verbatim, then complete
> every `# FILL IN:` marker. Never change a signature, class name or path the blueprint fixes.

### Steps (in order)
1. Create `ocr.py` (block A) — *why*: the reader has no dependency on any other new module.
2. Edit `pyproject.toml` (block B) **by hand, declaratively** — *why*: running `uv sync`/`uv lock` inside a worktree repoints the shared venv's editable install and breaks every other session.
3. Write the tests (block C); run the Validation Command — *why*: the "unavailable ⇒ silent" contract is what lets the pipeline run without the extra.

### `packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/perception/ocr.py` (CREATE) — block A
```python
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
        # FILL IN: lazily build the engine (`from rapidocr import RapidOCR`), upscale with
        #          cv2.resize(fx=_UPSCALE, fy=_UPSCALE, interpolation=cv2.INTER_CUBIC), call the engine,
        #          join `result.txts or ()`, average `result.scores or ()`, clamp to [0, 1]; wrap the engine
        #          call in try/except Exception → logger.warning + ("", 0.0) — bounded by the docstring contract.
        return "", 0.0


_READER: Optional[OcrReader] = None


def read_crop(crop: np.ndarray) -> Tuple[str, float]:
    """Module-level, picklable entry point using a per-process ``OcrReader`` singleton."""
    global _READER  # noqa: PLW0603 - deliberate per-process singleton
    if _READER is None:
        _READER = OcrReader()
    return _READER.read(crop)
```
**Why this shape**: class name, `available`, `read(crop) -> Tuple[str, float]` and `read_crop` are fixed by the
spec Module 8 skeleton. The singleton is per *process* on purpose: each pool worker pays the ONNX load once.

### `packages/ai-parrot-pipelines/pyproject.toml` (MODIFY) — block B
```toml
# occurrences: 1 (verified: grep -c '"pytesseract>=0.3.13",' pyproject.toml)
# AFTER — insert below `    "pytesseract>=0.3.13",` (verified: pyproject.toml:31), inside the dependencies list:
    "numpy",
    "pillow",
    "rapidfuzz>=3.0",

# occurrences: 1 (verified: grep -c '^\[project.urls\]$' pyproject.toml)
# BEFORE — insert above `[project.urls]` (verified: pyproject.toml:34), keeping one blank line on each side:
[project.optional-dependencies]
# FEAT-574: local OCR for the planogram compliance cycle. Without it the pipeline still runs
# and text is read by the LLM only.
planogram = [
    "rapidocr>=3.9",
    "onnxruntime>=1.20",
]
```
**Why**: exactly the declarations of spec Module 8 / §7. `opencv-python-headless` stays where it is — it is a
hard dependency by decision. Do not regenerate any lockfile.

### `packages/ai-parrot-pipelines/tests/planogram_cycle/test_ocr_reader.py` (CREATE) — block C
```python
"""OcrReader: lazy, optional, silent when unavailable (FEAT-574, spec Module 8)."""
from __future__ import annotations

import builtins
import pickle
import sys
from pathlib import Path

import numpy as np
import pytest

from parrot_pipelines.planogram.perception import ocr as ocr_module
from parrot_pipelines.planogram.perception.ocr import OcrReader, read_crop

_PYPROJECT = Path(__file__).resolve().parents[2] / "pyproject.toml"


@pytest.fixture
def no_rapidocr(monkeypatch):
    """Make `import rapidocr` fail even when the extra is installed."""
    real_import = builtins.__import__

    def fake_import(name, *args, **kwargs):
        if name == "rapidocr" or name.startswith("rapidocr."):
            raise ImportError("rapidocr not installed (test)")
        return real_import(name, *args, **kwargs)

    monkeypatch.delitem(sys.modules, "rapidocr", raising=False)
    monkeypatch.setattr(builtins, "__import__", fake_import)

# FILL IN: test bodies per the Test Specification below. Use a fake engine object
#          (callable returning SimpleNamespace(txts=(...), scores=(...))) assigned to reader._engine
#          to test the happy path WITHOUT loading ONNX models.
```
**Why**: tests must pass on machines with and without the extra, and must never load real OCR models
(slow, and the models may need a download).

### FILL IN checklist
- [ ] `ocr.py::OcrReader.read` — engine build, upscale, join, mean score, error swallow; bounded by the docstring contract
- [ ] `test_ocr_reader.py` — six test bodies; bounded by the Test Specification

---

## Acceptance Criteria

- [ ] Importing `parrot_pipelines.planogram.perception.ocr` never imports `rapidocr` or `onnxruntime` (`"rapidocr" not in sys.modules` right after a fresh import in a subprocess, or assert via the `no_rapidocr` fixture that construction succeeds).
- [ ] Without RapidOCR: `OcrReader().available is False` and `read(anything) == ("", 0.0)` — no exception.
- [ ] Empty crop (`np.zeros((0, 0, 3), np.uint8)`) and `None` ⇒ `("", 0.0)`.
- [ ] With a fake engine: texts joined with `" | "`, confidence is the mean score, clamped to `[0, 1]`; an engine exception ⇒ `("", 0.0)` + a warning log.
- [ ] `read_crop` is picklable (`pickle.dumps(read_crop)` works) and reuses one reader per process.
- [ ] `pyproject.toml` parses (`tomllib`) and contains: the three original dependencies, `numpy`, `pillow`, `rapidfuzz>=3.0`, and `optional-dependencies.planogram == ["rapidocr>=3.9", "onnxruntime>=1.20"]`; `opencv-python-headless>=4.8` is still in `dependencies`.
- [ ] No lockfile changed; `git status` shows only the three files of this task.
- [ ] All tests pass: `pytest packages/ai-parrot-pipelines/tests/planogram_cycle/test_ocr_reader.py -q`
- [ ] `ruff check packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/perception/ocr.py` clean.

---

## Validation Commands

> File-level pytest only — no directories, no package roots.

- `pytest packages/ai-parrot-pipelines/tests/planogram_cycle/test_ocr_reader.py -q`

---

## Test Specification

```python
def test_ocr_reader_unavailable_is_silent(no_rapidocr):
    """available False; read(np.ones((8, 8, 3), np.uint8)) == ("", 0.0)."""

def test_empty_and_none_crop():
    """("", 0.0) for a zero-size array and for None, regardless of availability."""

def test_read_joins_texts_and_averages_scores():
    """reader.available = True; reader._engine = fake → ("A | B", 0.75) for scores (0.5, 1.0)."""

def test_engine_failure_is_swallowed(caplog):
    """fake engine raises RuntimeError → ("", 0.0) and one WARNING record."""

def test_read_crop_is_picklable_and_singleton(monkeypatch):
    """pickle.dumps(read_crop) OK; monkeypatch ocr_module._READER = None; two calls build ONE OcrReader."""

def test_pyproject_declares_extra_and_direct_deps():
    """tomllib.loads(_PYPROJECT.read_text()) → assertions of the pyproject AC."""
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** (§3 Module 8, §7 External Dependencies)
2. **Check dependencies** — none. This task is **exclusive**: it is never dispatched alongside another task.
3. **Verify the Codebase Contract** — re-grep the `pyproject.toml` anchors and occurrence counts
4. **Implement** from the blueprint; complete every `# FILL IN:`. **Never run `uv sync` / `uv lock` / `uv add` / `pip install`.**
5. **Verify** all acceptance criteria
6. Commit only the three files listed above; never touch `sdd/`
7. **Fill in the Completion Note** below

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**: <session or agent ID>
**Date**: YYYY-MM-DD
