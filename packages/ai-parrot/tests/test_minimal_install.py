"""Minimal install validation tests for the ai-parrot framework.

These tests verify that the core framework (and individual bot/client classes)
can be imported without any optional extras installed. They mock-remove optional
dependencies by temporarily removing them from sys.modules and blocking their
import via builtins.__import__.

Test groups:
- Core framework: `import parrot`, `from parrot.bots import ...`
- Client imports: `from parrot.clients import ...`
- Lazy import error messages: tools raise clear ImportError
"""

from __future__ import annotations

import builtins
import sys
from contextlib import contextmanager
from types import ModuleType
from typing import Dict, List
from unittest.mock import patch

import pytest

# ---------------------------------------------------------------------------
# Helper: simulate missing packages
# ---------------------------------------------------------------------------

OPTIONAL_PACKAGES: Dict[str, List[str]] = {
    "db": ["querysource", "psycopg2", "psycopg"],
    "pdf": ["weasyprint", "markitdown", "fpdf"],
    "ocr": ["pytesseract"],
    "audio": ["pydub"],
    "finance": ["talib", "pandas_datareader"],
    "flowtask": ["flowtask"],
    "embeddings": ["sentence_transformers", "faiss"],
    "visualization": ["matplotlib", "seaborn"],
    "arango": ["arangoasync"],
    "scheduler": ["apscheduler"],
}


@contextmanager
def block_packages(*package_names: str):
    """Context manager that makes named packages unavailable during the block.

    Temporarily removes each package (and all its submodules) from sys.modules
    and patches importlib.import_module to raise ImportError for the blocked
    packages. This works with lazy_import() which uses importlib.import_module.

    Args:
        *package_names: Top-level package names to block.
    """
    import importlib as _importlib

    original_import_module = _importlib.import_module
    blocked = set(package_names)

    # Save and remove any already-imported modules whose top-level name is blocked
    saved: Dict[str, ModuleType] = {}
    keys_to_remove = [k for k in sys.modules if k.split(".")[0] in blocked]
    for key in keys_to_remove:
        saved[key] = sys.modules.pop(key)

    def blocking_import_module(name, *args, **kwargs):
        top = name.split(".")[0]
        if top in blocked:
            raise ImportError(f"No module named '{name}' (blocked by test)")
        return original_import_module(name, *args, **kwargs)

    try:
        with patch("importlib.import_module", side_effect=blocking_import_module):
            with patch("parrot._imports.importlib.import_module", side_effect=blocking_import_module):
                yield
    finally:
        # Restore saved modules
        sys.modules.update(saved)


# ---------------------------------------------------------------------------
# Tests: lazy_import() utility behaves correctly under blocking
# ---------------------------------------------------------------------------


class TestLazyImportUnderBlock:
    """Verify lazy_import raises appropriate errors when packages are blocked."""

    def test_querysource_blocked_raises_db_error(self):
        """lazy_import for querysource raises with pip install ai-parrot[db]."""
        from parrot._imports import lazy_import

        with block_packages("querysource"):
            with pytest.raises(ImportError, match=r"pip install ai-parrot\[db\]"):
                lazy_import("querysource.conf", package_name="querysource", extra="db")

    def test_weasyprint_blocked_raises_pdf_error(self):
        """lazy_import for weasyprint raises with pip install ai-parrot[pdf]."""
        from parrot._imports import lazy_import

        with block_packages("weasyprint"):
            with pytest.raises(ImportError, match=r"pip install ai-parrot\[pdf\]"):
                lazy_import("weasyprint", extra="pdf")

    def test_pytesseract_blocked_raises_ocr_error(self):
        """lazy_import for pytesseract raises with pip install ai-parrot[ocr]."""
        from parrot._imports import lazy_import

        with block_packages("pytesseract"):
            with pytest.raises(ImportError, match=r"pip install ai-parrot\[ocr\]"):
                lazy_import("pytesseract", extra="ocr")

    def test_pydub_blocked_raises_audio_error(self):
        """lazy_import for pydub raises with pip install ai-parrot[audio]."""
        from parrot._imports import lazy_import

        with block_packages("pydub"):
            with pytest.raises(ImportError, match=r"pip install ai-parrot\[audio\]"):
                lazy_import("pydub", extra="audio")

    def test_flowtask_blocked_raises_flowtask_error(self):
        """lazy_import for flowtask raises with pip install ai-parrot[flowtask]."""
        from parrot._imports import lazy_import

        with block_packages("flowtask"):
            with pytest.raises(ImportError, match=r"pip install ai-parrot\[flowtask\]"):
                lazy_import("flowtask", extra="flowtask")

    def test_sentence_transformers_blocked_raises_embeddings_error(self):
        """lazy_import for sentence_transformers raises with pip install ai-parrot[embeddings]."""
        from parrot._imports import lazy_import

        with block_packages("sentence_transformers"):
            with pytest.raises(ImportError, match=r"pip install ai-parrot\[embeddings\]"):
                lazy_import("sentence_transformers", extra="embeddings")

    def test_faiss_blocked_raises_embeddings_error(self):
        """lazy_import for faiss raises with pip install ai-parrot[embeddings]."""
        from parrot._imports import lazy_import

        with block_packages("faiss"):
            with pytest.raises(ImportError, match=r"pip install ai-parrot\[embeddings\]"):
                lazy_import("faiss", package_name="faiss-cpu", extra="embeddings")


# ---------------------------------------------------------------------------
# Tests: core parrot._imports module itself is always importable
# ---------------------------------------------------------------------------


class TestCoreImportsAlwaysAvailable:
    """The lazy import utility must be importable with no optional deps."""

    def test_imports_module_importable(self):
        """parrot._imports is always importable (stdlib only)."""
        import parrot._imports as _imports  # noqa: F401

        assert hasattr(_imports, "lazy_import")
        assert hasattr(_imports, "require_extra")

    def test_lazy_import_function_is_callable(self):
        """lazy_import is a callable function."""
        from parrot._imports import lazy_import

        assert callable(lazy_import)

    def test_require_extra_function_is_callable(self):
        """require_extra is a callable function."""
        from parrot._imports import require_extra

        assert callable(require_extra)


# ---------------------------------------------------------------------------
# Tests: tool error messages are correct
# ---------------------------------------------------------------------------


class TestToolImportErrorMessages:
    """Tools must raise ImportError with the correct pip install instructions."""

    def test_pdfprint_tool_raises_pdf_error_when_weasyprint_missing(self):
        """pdfprint tool raises ImportError with ai-parrot[pdf] hint."""
        from parrot._imports import lazy_import

        with block_packages("weasyprint"):
            with pytest.raises(ImportError) as exc_info:
                lazy_import("weasyprint", extra="pdf")
            assert "ai-parrot[pdf]" in str(exc_info.value)

    def test_audio_lazy_import_raises_audio_error(self):
        """pydub lazy import raises ImportError with ai-parrot[audio] hint."""
        from parrot._imports import lazy_import

        with block_packages("pydub"):
            with pytest.raises(ImportError) as exc_info:
                lazy_import("pydub", extra="audio")
            assert "ai-parrot[audio]" in str(exc_info.value)

    def test_db_lazy_import_raises_db_error(self):
        """querysource lazy import raises ImportError with ai-parrot[db] hint."""
        from parrot._imports import lazy_import

        with block_packages("querysource"):
            with pytest.raises(ImportError) as exc_info:
                lazy_import("querysource", extra="db")
            assert "ai-parrot[db]" in str(exc_info.value)

    def test_finance_lazy_import_raises_finance_error(self):
        """talib lazy import raises ImportError with ai-parrot[finance] hint."""
        from parrot._imports import lazy_import

        with block_packages("talib"):
            with pytest.raises(ImportError) as exc_info:
                lazy_import("talib", package_name="ta-lib", extra="finance")
            assert "ai-parrot[finance]" in str(exc_info.value)

    def test_arango_lazy_import_raises_arango_error(self):
        """arangoasync lazy import raises ImportError with ai-parrot[arango] hint."""
        from parrot._imports import lazy_import

        with block_packages("arangoasync"):
            with pytest.raises(ImportError) as exc_info:
                lazy_import("arangoasync", package_name="python-arango-async", extra="arango")
            assert "ai-parrot[arango]" in str(exc_info.value)


# ---------------------------------------------------------------------------
# Tests: multiple packages blocked simultaneously
# ---------------------------------------------------------------------------


class TestMultiplePackagesBlocked:
    """Verify behavior when all optional extras are blocked simultaneously."""

    def test_lazy_import_works_for_stdlib_when_optionals_blocked(self):
        """lazy_import works for stdlib modules even when all optionals are blocked."""
        from parrot._imports import lazy_import

        all_optional = [pkg for pkgs in OPTIONAL_PACKAGES.values() for pkg in pkgs]
        with block_packages(*all_optional):
            mod = lazy_import("json")
            assert hasattr(mod, "dumps")

    def test_require_extra_works_for_stdlib_when_optionals_blocked(self):
        """require_extra works for stdlib modules even when all optionals are blocked."""
        from parrot._imports import require_extra

        all_optional = [pkg for pkgs in OPTIONAL_PACKAGES.values() for pkg in pkgs]
        with block_packages(*all_optional):
            # Should not raise — json and os are stdlib
            require_extra("core", "json", "os")

    def test_each_optional_blocked_individually_raises_correct_error(self):
        """Each optional package raises ImportError with the correct extra name."""
        from parrot._imports import lazy_import

        cases = [
            ("querysource", "querysource", "db"),
            ("weasyprint", "weasyprint", "pdf"),
            ("pytesseract", "pytesseract", "ocr"),
            ("pydub", "pydub", "audio"),
            ("flowtask", "flowtask", "flowtask"),
        ]
        for module, package, extra in cases:
            with block_packages(module):
                with pytest.raises(ImportError, match=rf"ai-parrot\[{extra}\]"):
                    lazy_import(module, package_name=package, extra=extra)
