"""OcrReader: lazy, optional, silent when unavailable (FEAT-574, spec Module 8)."""

from __future__ import annotations

import builtins
import logging
import pickle
import sys
import tomllib
from pathlib import Path
from types import SimpleNamespace

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


def _available_reader(engine) -> OcrReader:
    """A reader forced available with a fake engine (never loads ONNX models)."""
    reader = OcrReader.__new__(OcrReader)
    reader.available = True
    reader._engine = engine
    return reader


def test_ocr_reader_unavailable_is_silent(no_rapidocr):
    """available False; read(anything) == ("", 0.0)."""
    reader = OcrReader()
    assert reader.available is False
    assert reader.read(np.ones((8, 8, 3), np.uint8)) == ("", 0.0)


def test_module_import_does_not_import_rapidocr():
    """Importing the module never imports rapidocr/onnxruntime at module scope."""
    import subprocess

    code = (
        "import sys; import parrot_pipelines.planogram.perception.ocr; "
        "print('rapidocr' in sys.modules or 'onnxruntime' in sys.modules)"
    )
    out = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, check=True)
    assert out.stdout.strip().splitlines()[-1] == "False"


def test_empty_and_none_crop():
    """("", 0.0) for a zero-size array and for None, regardless of availability."""
    reader = _available_reader(engine=lambda img: pytest.fail("engine must not be called"))
    assert reader.read(np.zeros((0, 0, 3), np.uint8)) == ("", 0.0)
    assert reader.read(None) == ("", 0.0)


def test_read_joins_texts_and_averages_scores():
    """Texts joined with " | "; confidence is the mean score, clamped to [0, 1]."""
    seen = []

    def engine(img):
        seen.append(img.shape)
        return SimpleNamespace(txts=("A", "B"), scores=(0.5, 1.0))

    reader = _available_reader(engine)
    assert reader.read(np.ones((10, 20, 3), np.uint8)) == ("A | B", 0.75)
    assert seen == [(40, 80, 3)]  # upscaled x4 before OCR

    over = _available_reader(lambda img: SimpleNamespace(txts=("X",), scores=(1.7,)))
    assert over.read(np.ones((4, 4, 3), np.uint8)) == ("X", 1.0)
    empty = _available_reader(lambda img: SimpleNamespace(txts=None, scores=None))
    assert empty.read(np.ones((4, 4, 3), np.uint8)) == ("", 0.0)


def test_engine_failure_is_swallowed(caplog):
    """An engine exception ⇒ ("", 0.0) and one WARNING record."""

    def boom(img):
        raise RuntimeError("onnx exploded")

    reader = _available_reader(boom)
    with caplog.at_level(logging.WARNING, logger=ocr_module.__name__):
        assert reader.read(np.ones((4, 4, 3), np.uint8)) == ("", 0.0)
    warnings = [r for r in caplog.records if r.levelno == logging.WARNING]
    assert len(warnings) == 1


def test_read_crop_is_picklable_and_singleton(monkeypatch):
    """pickle.dumps(read_crop) works; two calls build ONE OcrReader per process."""
    pickle.dumps(read_crop)
    monkeypatch.setattr(ocr_module, "_READER", None)
    built = []

    class _Counting(OcrReader):
        def __init__(self) -> None:
            built.append(1)
            self.available = False
            self._engine = None

    monkeypatch.setattr(ocr_module, "OcrReader", _Counting)
    assert read_crop(np.ones((4, 4, 3), np.uint8)) == ("", 0.0)
    assert read_crop(np.ones((4, 4, 3), np.uint8)) == ("", 0.0)
    assert len(built) == 1


def test_pyproject_declares_extra_and_direct_deps():
    """Direct dependencies and the planogram extra are declared."""
    project = tomllib.loads(_PYPROJECT.read_text())["project"]
    deps = project["dependencies"]
    for dep in (
        "ai-parrot>=1.0.4",
        "opencv-python-headless>=4.8",
        "pytesseract>=0.3.13",
        "numpy",
        "pillow",
        "rapidfuzz>=3.0",
    ):
        assert dep in deps
    assert project["optional-dependencies"]["planogram"] == ["rapidocr>=3.9", "onnxruntime>=1.20"]
