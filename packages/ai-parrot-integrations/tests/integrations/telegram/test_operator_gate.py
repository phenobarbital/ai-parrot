"""
Unit tests for operator authorization gate (FEAT-210 TASK-1394).

Tests cover:
- _is_operator fail-closed defaults (None / empty allowlist)
- Allowlist inclusion/exclusion
- Feature toggle (enable_operator_commands=False)
- Distinction between _is_authorized and _is_operator semantics
"""
import pytest
from unittest.mock import MagicMock


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_wrapper(operator_chat_ids=None, enable_operator_commands=True,
                  allowed_chat_ids=None):
    """Build a minimal TelegramAgentWrapper stand-in for gate tests.

    Uses __new__ to bypass __init__ so no real bot / agent is needed.
    """
    from parrot.integrations.telegram.wrapper import TelegramAgentWrapper

    w = TelegramAgentWrapper.__new__(TelegramAgentWrapper)
    w.logger = MagicMock()
    w.config = MagicMock()
    w.config.operator_chat_ids = operator_chat_ids
    w.config.enable_operator_commands = enable_operator_commands
    w.config.allowed_chat_ids = allowed_chat_ids
    return w


# ---------------------------------------------------------------------------
# TelegramAgentConfig field tests
# ---------------------------------------------------------------------------

class TestTelegramAgentConfigFields:
    """Verify new config fields are defined with correct defaults."""

    def test_operator_chat_ids_default_none(self):
        """operator_chat_ids defaults to None (fail-closed)."""
        from parrot.integrations.telegram.models import TelegramAgentConfig

        cfg = TelegramAgentConfig(name="test", chatbot_id="test")
        assert cfg.operator_chat_ids is None

    def test_enable_operator_commands_default_true(self):
        """enable_operator_commands defaults to True (feature enabled)."""
        from parrot.integrations.telegram.models import TelegramAgentConfig

        cfg = TelegramAgentConfig(name="test", chatbot_id="test")
        assert cfg.enable_operator_commands is True

    def test_operator_chat_ids_can_be_set(self):
        """operator_chat_ids can be set to a list of ints."""
        from parrot.integrations.telegram.models import TelegramAgentConfig

        cfg = TelegramAgentConfig(name="test", chatbot_id="test",
                                  operator_chat_ids=[111, 222])
        assert cfg.operator_chat_ids == [111, 222]

    def test_enable_operator_commands_can_be_disabled(self):
        """enable_operator_commands can be set to False."""
        from parrot.integrations.telegram.models import TelegramAgentConfig

        cfg = TelegramAgentConfig(name="test", chatbot_id="test",
                                  enable_operator_commands=False)
        assert cfg.enable_operator_commands is False

    def test_from_dict_operator_fields(self):
        """from_dict parses operator_chat_ids and enable_operator_commands."""
        from parrot.integrations.telegram.models import TelegramAgentConfig

        cfg = TelegramAgentConfig.from_dict("test", {
            "chatbot_id": "test",
            "operator_chat_ids": [100, 200],
            "enable_operator_commands": False,
        })
        assert cfg.operator_chat_ids == [100, 200]
        assert cfg.enable_operator_commands is False

    def test_from_dict_defaults_when_absent(self):
        """from_dict uses defaults when operator fields are absent."""
        from parrot.integrations.telegram.models import TelegramAgentConfig

        cfg = TelegramAgentConfig.from_dict("test", {"chatbot_id": "test"})
        assert cfg.operator_chat_ids is None
        assert cfg.enable_operator_commands is True


# ---------------------------------------------------------------------------
# _is_operator gate tests
# ---------------------------------------------------------------------------

class TestIsOperator:
    """Unit tests for TelegramAgentWrapper._is_operator."""

    def test_failclosed_none(self):
        """operator_chat_ids=None → _is_operator returns False for everyone."""
        w = _make_wrapper(operator_chat_ids=None)
        assert w._is_operator(111) is False
        assert w._is_operator(0) is False
        assert w._is_operator(999999) is False

    def test_failclosed_empty(self):
        """operator_chat_ids=[] → _is_operator returns False for everyone."""
        w = _make_wrapper(operator_chat_ids=[])
        assert w._is_operator(111) is False
        assert w._is_operator(0) is False

    def test_allowlist_match(self):
        """Chat ID in operator_chat_ids → _is_operator returns True."""
        w = _make_wrapper(operator_chat_ids=[111, 222, 333])
        assert w._is_operator(111) is True
        assert w._is_operator(222) is True
        assert w._is_operator(333) is True

    def test_allowlist_no_match(self):
        """Chat ID NOT in operator_chat_ids → _is_operator returns False."""
        w = _make_wrapper(operator_chat_ids=[111, 222])
        assert w._is_operator(999) is False
        assert w._is_operator(0) is False
        assert w._is_operator(223) is False

    def test_disabled_flag(self):
        """enable_operator_commands=False → _is_operator returns False even if in allowlist."""
        w = _make_wrapper(operator_chat_ids=[111], enable_operator_commands=False)
        assert w._is_operator(111) is False

    def test_authorized_but_not_operator(self):
        """A chat_id in allowed_chat_ids but NOT in operator_chat_ids → _is_operator False."""
        w = _make_wrapper(
            operator_chat_ids=[999],
            allowed_chat_ids=[111, 999],
        )
        # 111 is authorized but not an operator
        assert w._is_authorized(111) is True
        assert w._is_operator(111) is False

    def test_operator_is_also_authorized(self):
        """An operator chat_id returns True from both gates."""
        w = _make_wrapper(
            operator_chat_ids=[999],
            allowed_chat_ids=[111, 999],
        )
        assert w._is_authorized(999) is True
        assert w._is_operator(999) is True

    def test_is_authorized_failopen_when_none(self):
        """_is_authorized remains fail-open (None → everyone) — no regression."""
        w = _make_wrapper(allowed_chat_ids=None)
        assert w._is_authorized(12345) is True
        assert w._is_authorized(0) is True

    def test_is_operator_failclosed_when_none(self):
        """_is_operator is fail-closed (None → nobody) — contrast with _is_authorized."""
        w = _make_wrapper(operator_chat_ids=None)
        assert w._is_operator(12345) is False
