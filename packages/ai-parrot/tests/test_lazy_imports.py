"""Unit tests for parrot._imports — Lazy Import Utility.

Tests cover:
- lazy_import() for installed and missing modules
- require_extra() for all-present and partially-missing modules
- Custom package_name parameter
- Submodule imports
- Error message formatting
"""

import builtins
import importlib
import importlib.util
import sys
from unittest.mock import patch

import pytest

from parrot._imports import (
    _ensure_torchcodec_optional,
    lazy_import,
    require_extra,
)


@pytest.fixture
def clean_torchcodec():
    """Remove any real/stub torchcodec modules before and after a test."""
    def _purge():
        for name in [m for m in sys.modules if m == "torchcodec" or m.startswith("torchcodec.")]:
            del sys.modules[name]
    _purge()
    yield
    _purge()


class TestLazyImport:
    """Tests for the lazy_import() function."""

    def test_import_installed_module(self):
        """Successfully imports an installed module."""
        mod = lazy_import("json")
        assert hasattr(mod, "dumps")

    def test_import_missing_module_with_extra(self):
        """Raises ImportError with install instructions for missing module."""
        with pytest.raises(ImportError, match=r"pip install ai-parrot\[testextra\]"):
            lazy_import("nonexistent_pkg_xyz_12345", extra="testextra")

    def test_import_missing_module_without_extra(self):
        """Raises ImportError with pip install for missing module."""
        with pytest.raises(ImportError, match=r"pip install nonexistent"):
            lazy_import("nonexistent_pkg_xyz_12345", package_name="nonexistent")

    def test_import_submodule(self):
        """Can import submodules."""
        mod = lazy_import("os.path")
        assert hasattr(mod, "join")

    def test_custom_package_name(self):
        """Error message uses custom package name."""
        with pytest.raises(ImportError, match="my-custom-pkg"):
            lazy_import("nonexistent", package_name="my-custom-pkg")

    def test_returns_module_object(self):
        """Returns the actual module object, not a proxy."""
        mod = lazy_import("json")
        import json
        assert mod is json

    def test_import_missing_module_default_package_name(self):
        """Uses first segment of module_path as package name when not given."""
        with pytest.raises(ImportError, match="definitely_not_installed"):
            lazy_import("definitely_not_installed.submod")

    def test_error_message_contains_package_name(self):
        """Error message mentions the package name."""
        with pytest.raises(ImportError, match="my-special-pkg"):
            lazy_import("nonexistent_xyz_abc", package_name="my-special-pkg", extra="myextra")

    def test_error_message_with_extra_format(self):
        """Error message uses correct ai-parrot[extra] format."""
        with pytest.raises(ImportError) as exc_info:
            lazy_import("nonexistent_xyz_abc", extra="audio")
        assert "pip install ai-parrot[audio]" in str(exc_info.value)

    def test_error_message_without_extra_format(self):
        """Error message uses plain pip install format without extra."""
        with pytest.raises(ImportError) as exc_info:
            lazy_import("nonexistent_xyz_abc", package_name="nonexistent-xyz-abc")
        assert "pip install nonexistent-xyz-abc" in str(exc_info.value)
        assert "ai-parrot" not in str(exc_info.value)

    def test_raises_import_error_not_other_exception(self):
        """Raises ImportError specifically, not any other exception type."""
        with pytest.raises(ImportError):
            lazy_import("nonexistent_pkg_xyz_12345")

    def test_chained_exception(self):
        """The raised ImportError chains the original ImportError."""
        with pytest.raises(ImportError) as exc_info:
            lazy_import("nonexistent_pkg_xyz_12345", extra="db")
        assert exc_info.value.__cause__ is not None
        assert isinstance(exc_info.value.__cause__, ImportError)


class TestTorchcodecOptional:
    """Tests for _ensure_torchcodec_optional() — resilience to broken FFmpeg.

    ``sentence_transformers`` eagerly imports ``torchcodec`` at package import
    time; a missing/incomplete FFmpeg makes torchcodec raise ``RuntimeError``
    while loading its C extension, which would otherwise crash agent startup.
    """

    def test_broken_torchcodec_is_stubbed(self, clean_torchcodec):
        """A torchcodec that fails to load (RuntimeError) is replaced by stubs."""
        original = importlib.import_module

        def fake(name, *args, **kwargs):
            if name == "torchcodec":
                raise RuntimeError("Could not load libtorchcodec (simulated)")
            return original(name, *args, **kwargs)

        with patch("parrot._imports.importlib.import_module", side_effect=fake):
            _ensure_torchcodec_optional()

        # Stub is registered and the guarded downstream import resolves to None.
        assert "torchcodec" in sys.modules
        from torchcodec.decoders import AudioDecoder, VideoDecoder
        assert AudioDecoder is None
        assert VideoDecoder is None

    def test_stub_has_valid_spec(self, clean_torchcodec):
        """The stub exposes a non-None __spec__ so find_spec() does not raise.

        ``transformers`` probes availability with importlib.util.find_spec,
        which raises ValueError on a live module whose __spec__ is None.
        """
        original = importlib.import_module

        def fake(name, *args, **kwargs):
            if name == "torchcodec":
                raise OSError("libavdevice.so.60: cannot open shared object file")
            return original(name, *args, **kwargs)

        with patch("parrot._imports.importlib.import_module", side_effect=fake):
            _ensure_torchcodec_optional()

        # Must not raise ValueError("torchcodec.__spec__ is None")
        assert importlib.util.find_spec("torchcodec") is not None

    def test_missing_torchcodec_is_not_stubbed(self, clean_torchcodec):
        """When torchcodec is not installed at all, no stub is registered."""
        original = importlib.import_module

        def fake(name, *args, **kwargs):
            if name == "torchcodec":
                raise ModuleNotFoundError("No module named 'torchcodec'")
            return original(name, *args, **kwargs)

        with patch("parrot._imports.importlib.import_module", side_effect=fake):
            _ensure_torchcodec_optional()

        assert "torchcodec" not in sys.modules

    def test_already_loaded_is_noop(self, clean_torchcodec):
        """If torchcodec is already in sys.modules, nothing is re-imported."""
        sentinel = object()
        sys.modules["torchcodec"] = sentinel  # type: ignore[assignment]

        called = {"n": 0}
        original = importlib.import_module

        def fake(name, *args, **kwargs):
            if name == "torchcodec":
                called["n"] += 1
            return original(name, *args, **kwargs)

        with patch("parrot._imports.importlib.import_module", side_effect=fake):
            _ensure_torchcodec_optional()

        assert sys.modules["torchcodec"] is sentinel
        assert called["n"] == 0

    def test_lazy_import_of_host_triggers_neutralizer(self, clean_torchcodec):
        """lazy_import of a torchcodec-hosting module invokes the neutralizer."""
        with patch("parrot._imports._ensure_torchcodec_optional") as neutralizer:
            # json stands in for the host so we don't import the heavy real one;
            # the branch keys on the top-level module name in _TORCHCODEC_HOSTS.
            with patch("parrot._imports._TORCHCODEC_HOSTS", ("json",)):
                lazy_import("json")
            neutralizer.assert_called_once()

    def test_lazy_import_non_host_skips_neutralizer(self):
        """lazy_import of an unrelated module does not touch torchcodec."""
        with patch("parrot._imports._ensure_torchcodec_optional") as neutralizer:
            lazy_import("os.path")
            neutralizer.assert_not_called()


class TestRequireExtra:
    """Tests for the require_extra() function."""

    def test_all_available(self):
        """Passes when all modules are importable."""
        require_extra("core", "json", "os")

    def test_missing_module(self):
        """Raises ImportError when a module is missing."""
        with pytest.raises(ImportError, match=r"pip install ai-parrot\[db\]"):
            require_extra("db", "json", "nonexistent_pkg_xyz_12345")

    def test_first_missing_raises(self):
        """Stops at first missing module and raises immediately."""
        with pytest.raises(ImportError, match=r"pip install ai-parrot\[pdf\]"):
            require_extra("pdf", "nonexistent_first_xyz", "json")

    def test_single_module_ok(self):
        """Accepts a single module with no error."""
        require_extra("core", "json")

    def test_no_modules_is_noop(self):
        """With no module arguments, does nothing and returns None."""
        result = require_extra("core")
        assert result is None

    def test_error_uses_correct_extra_name(self):
        """Error message uses the extra name passed to require_extra."""
        with pytest.raises(ImportError) as exc_info:
            require_extra("finance", "nonexistent_talib_xyz")
        assert "ai-parrot[finance]" in str(exc_info.value)

    def test_all_missing_raises_on_first(self):
        """When multiple modules are missing, raises on the first one."""
        with pytest.raises(ImportError):
            require_extra("embeddings", "nonexistent_a", "nonexistent_b")


class TestLazyImportWithMockedImport:
    """Tests using mocked builtins.__import__ to simulate missing packages."""

    def test_import_blocked_package_raises_with_extra(self):
        """Simulates a package not being installed via mock."""
        original_import = builtins.__import__

        def block_fake_pkg(name, *args, **kwargs):
            if name == "fake_blocked_pkg":
                raise ImportError(f"No module named '{name}'")
            return original_import(name, *args, **kwargs)

        with patch("builtins.__import__", side_effect=block_fake_pkg):
            with pytest.raises(ImportError, match=r"pip install ai-parrot\[ocr\]"):
                lazy_import("fake_blocked_pkg", extra="ocr")

    def test_import_blocked_package_raises_without_extra(self):
        """Simulates a package not being installed — no extra given."""
        original_import = builtins.__import__

        def block_fake_pkg(name, *args, **kwargs):
            if name == "another_fake_pkg":
                raise ImportError(f"No module named '{name}'")
            return original_import(name, *args, **kwargs)

        with patch("builtins.__import__", side_effect=block_fake_pkg):
            with pytest.raises(ImportError, match=r"pip install another_fake_pkg"):
                lazy_import("another_fake_pkg")


class TestLazyImportIntegration:
    """Integration-style tests verifying lazy_import works with real optional extras."""

    def test_lazy_import_returns_same_object_as_direct_import(self):
        """lazy_import returns the exact same module object as a direct import."""
        import os.path as direct_ospath

        result = lazy_import("os.path")
        assert result is direct_ospath

    def test_lazy_import_all_extras_have_correct_error_format(self):
        """Every optional extra produces the correct pip install error format."""
        import importlib as _importlib

        original_import_module = _importlib.import_module
        extras_and_packages = [
            ("querysource", "querysource", "db"),
            ("weasyprint", "weasyprint", "pdf"),
            ("pytesseract", "pytesseract", "ocr"),
            ("pydub", "pydub", "audio"),
            ("talib", "ta-lib", "finance"),
            ("flowtask", "flowtask", "flowtask"),
            ("apscheduler", "apscheduler", "scheduler"),
            ("arangoasync", "python-arango-async", "arango"),
        ]
        for module_name, package_name, extra in extras_and_packages:
            def blocking_import_module(name, *args, blocked=module_name, orig=original_import_module, **kwargs):
                if name.split(".")[0] == blocked:
                    raise ImportError(f"No module named '{name}'")
                return orig(name, *args, **kwargs)

            with patch("parrot._imports.importlib.import_module", side_effect=blocking_import_module):
                with pytest.raises(ImportError) as exc_info:
                    lazy_import(module_name, package_name=package_name, extra=extra)
                error_msg = str(exc_info.value)
                assert f"pip install ai-parrot[{extra}]" in error_msg, (
                    f"Expected 'pip install ai-parrot[{extra}]' in error for {module_name}, "
                    f"got: {error_msg!r}"
                )

    def test_lazy_import_submodule_blocked_raises_top_level_package_name(self):
        """When a submodule is blocked, error references the top-level package name."""
        import importlib as _importlib

        original_import_module = _importlib.import_module

        def block_submod(name, *args, **kwargs):
            if name == "fake_top.submod":
                raise ImportError(f"No module named '{name}'")
            return original_import_module(name, *args, **kwargs)

        with patch("parrot._imports.importlib.import_module", side_effect=block_submod):
            with pytest.raises(ImportError, match="fake_top") as exc_info:
                lazy_import("fake_top.submod", extra="db")
            # The error message should reference the top-level module
            assert "fake_top" in str(exc_info.value)

    def test_require_extra_with_multiple_missing_raises_on_first(self):
        """require_extra raises on the first missing module even with many specified."""
        import importlib as _importlib

        original_import_module = _importlib.import_module
        call_order = []

        def tracking_import_module(name, *args, **kwargs):
            call_order.append(name.split(".")[0])
            if name.split(".")[0] in ("missing_a", "missing_b", "missing_c"):
                raise ImportError(f"No module named '{name}'")
            return original_import_module(name, *args, **kwargs)

        with patch("parrot._imports.importlib.import_module", side_effect=tracking_import_module):
            with pytest.raises(ImportError, match=r"ai-parrot\[myextra\]"):
                require_extra("myextra", "json", "missing_a", "missing_b", "missing_c")

        # json should have been tried (and succeeded), missing_a should have failed
        # missing_b and missing_c should NOT have been tried
        assert "missing_b" not in call_order
        assert "missing_c" not in call_order
