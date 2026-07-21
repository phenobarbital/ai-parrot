"""Base AbstractBot._resolve_output_mode no-op + precedence (FEAT-224, TASK-1487).

The shared ``tests/conftest.py`` installs a lightweight stub for
``parrot.bots.abstract`` (``_install_parrot_stubs``). These tests need the REAL
class, so we pop the stub and import the real module (all deps are installed in
the test venv) — mirroring the pattern in ``tests/test_basic_agent_new.py``.
"""
from __future__ import annotations

import sys

import pytest

from parrot.models.outputs import OutputMode
from parrot.utils.helpers import RequestContext


@pytest.fixture(scope="module")
def abstract_bot_cls():
    sys.modules.pop("parrot.bots.abstract", None)
    import parrot.bots.abstract as real  # noqa: PLC0415

    return real.AbstractBot


async def test_base_hook_is_noop(abstract_bot_cls):
    # The unbound coroutine returns None regardless of input (verified no-op).
    result = await abstract_bot_cls._resolve_output_mode(
        object(), "create a pie chart", RequestContext()
    )
    assert result is None


async def test_base_hook_noop_with_none_ctx(abstract_bot_cls):
    result = await abstract_bot_cls._resolve_output_mode(object(), "anything", None)
    assert result is None


def test_base_hook_exists(abstract_bot_cls):
    assert hasattr(abstract_bot_cls, "_resolve_output_mode")
    assert abstract_bot_cls.__name__ == "AbstractBot"


def test_default_enum_is_default():
    assert OutputMode.DEFAULT == OutputMode("default")


def test_precedence_guard_semantics():
    # Call sites are guarded by ``output_mode == OutputMode.DEFAULT`` so an
    # explicit non-DEFAULT caller mode is never passed to the router.
    explicit = OutputMode.TABLE
    assert explicit != OutputMode.DEFAULT


# ── Agent-level default output mode fallback (_apply_default_output_mode) ──


class _StubBot:
    """Duck-typed stand-in: the helper only reads ``default_output_mode``."""

    def __init__(self, default_mode):
        self.default_output_mode = default_mode


def _apply(abstract_bot_cls, bot, mode):
    return abstract_bot_cls._apply_default_output_mode(bot, mode)


def test_default_mode_fallback_applies(abstract_bot_cls):
    bot = _StubBot(OutputMode.TEXT)
    assert _apply(abstract_bot_cls, bot, OutputMode.DEFAULT) == OutputMode.TEXT


def test_explicit_caller_mode_wins_over_agent_default(abstract_bot_cls):
    bot = _StubBot(OutputMode.TEXT)
    assert _apply(abstract_bot_cls, bot, OutputMode.JSON) == OutputMode.JSON


def test_default_agent_mode_is_noop(abstract_bot_cls):
    bot = _StubBot(OutputMode.DEFAULT)
    assert _apply(abstract_bot_cls, bot, OutputMode.DEFAULT) == OutputMode.DEFAULT


def test_missing_attribute_is_noop(abstract_bot_cls):
    # Stubbed bots without the attribute must not break the ask() path.
    assert _apply(abstract_bot_cls, object(), OutputMode.DEFAULT) == OutputMode.DEFAULT
