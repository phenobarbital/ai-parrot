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
from unittest.mock import patch

import pytest

from parrot._imports import lazy_import, require_extra


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
