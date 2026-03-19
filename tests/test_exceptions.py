# -*- coding: utf-8 -*-
"""Unit tests for parrot/exceptions.py (pure Python implementation).

These tests target the pure Python source file directly via importlib so they
remain valid even while the legacy compiled ``exceptions.so`` is still present
in the package directory (before TASK-226 removes it).
"""
import importlib.util
import sys
from pathlib import Path

import pytest

# ---------------------------------------------------------------------------
# Load the .py module directly — bypasses the compiled .so if still present
# ---------------------------------------------------------------------------
_PY_PATH = Path(__file__).parent.parent / "parrot" / "exceptions.py"
_spec = importlib.util.spec_from_file_location("parrot.exceptions_py", _PY_PATH)
_mod = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_mod)

ParrotError = _mod.ParrotError
ConfigError = _mod.ConfigError
SpeechGenerationError = _mod.SpeechGenerationError
DriverError = _mod.DriverError
ToolError = _mod.ToolError


# ---------------------------------------------------------------------------
# Helper
# ---------------------------------------------------------------------------
class FakeMsg:
    """Object with a .message attribute — tests object-based message extraction."""

    message = "from object"


# ---------------------------------------------------------------------------
# ParrotError base behaviour
# ---------------------------------------------------------------------------

def test_parrot_error_message_string():
    assert ParrotError("hello").message == "hello"


def test_parrot_error_message_object():
    e = ParrotError(FakeMsg())
    assert e.message == "from object"


def test_parrot_error_str():
    assert str(ParrotError("x")) == "x"


def test_parrot_error_repr():
    assert repr(ParrotError("x")) == "x"


def test_parrot_error_get():
    assert ParrotError("x").get() == "x"


def test_parrot_error_stacktrace():
    e = ParrotError("x", stacktrace="traceback here")
    assert e.stacktrace == "traceback here"


def test_parrot_error_stacktrace_default_none():
    assert ParrotError("x").stacktrace is None


def test_parrot_error_is_exception():
    assert isinstance(ParrotError("x"), Exception)


# ---------------------------------------------------------------------------
# Subclass hierarchy
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("cls", [
    ConfigError,
    SpeechGenerationError,
    DriverError,
    ToolError,
])
def test_subclass_is_parrot_error(cls):
    assert isinstance(cls("x"), ParrotError)


@pytest.mark.parametrize("cls", [
    ConfigError,
    SpeechGenerationError,
    DriverError,
    ToolError,
])
def test_subclass_is_exception(cls):
    assert isinstance(cls("x"), Exception)


# ---------------------------------------------------------------------------
# Catch semantics
# ---------------------------------------------------------------------------

def test_raise_and_catch_as_parrot_error():
    with pytest.raises(ParrotError):
        raise ConfigError("cfg error")


def test_raise_and_catch_as_exception():
    with pytest.raises(Exception):
        raise ToolError("tool error")


def test_catch_specific_subclass():
    with pytest.raises(DriverError):
        raise DriverError("driver error")


# ---------------------------------------------------------------------------
# Pure Python subclassability — would TypeError on Cython cdef class
# ---------------------------------------------------------------------------

def test_pure_python_subclassable():
    class MyError(ParrotError):
        pass

    e = MyError("custom")
    assert isinstance(e, ParrotError)
    assert e.message == "custom"
    assert str(e) == "custom"
    assert repr(e) == "custom"
    assert e.get() == "custom"
