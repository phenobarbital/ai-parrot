"""Tests for the WhatsApp allowlist fail-closed financial control (FEAT-453
TASK-2397).

An empty ``WhatsAppBridgeConfig.allowed_numbers`` is a convenience for a
general assistant, but for an agent that exposes an ``OperationKind.SUBMIT``
business operation (can spend money / file tax-relevant records) it means
anyone who learns the bridge's number can instruct it. These tests exercise
both directions: refusal when a SUBMIT operation is exposed, and unchanged
permissive behaviour when it is not — plus the digits-only normalization
used for allowlist comparisons.
"""

import sys
from pathlib import Path
from types import SimpleNamespace

import pytest
from aiohttp import web

# The repo's editable install of ai-parrot-tools points at the main-repo
# checkout, not this worktree (see packages/ai-parrot-integrations/conftest.py
# for the same pattern applied to ai-parrot-integrations/ai-parrot core).
# BusinessAutomationToolkit/OperationKind were only added to this worktree
# (FEAT-453 TASK-2390), so prepend the worktree's own src for this test
# module specifically rather than editing that shared conftest.py (out of
# this task's file scope). If some other test collected earlier in the same
# session already imported (and cached) `parrot_tools` from the main-repo
# location, sys.path alone won't help — also splice the worktree's
# `parrot_tools` directory onto the front of the already-imported package's
# `__path__` so submodule lookups (`parrot_tools.business_automation`) find
# this worktree's copy regardless of collection order.
_TOOLS_SRC = Path(__file__).resolve().parents[4] / "packages" / "ai-parrot-tools" / "src"
if str(_TOOLS_SRC) not in sys.path:
    sys.path.insert(0, str(_TOOLS_SRC))
if "parrot_tools" in sys.modules:
    _worktree_parrot_tools = str(_TOOLS_SRC / "parrot_tools")
    if _worktree_parrot_tools not in sys.modules["parrot_tools"].__path__:
        sys.modules["parrot_tools"].__path__.insert(0, _worktree_parrot_tools)

from parrot.integrations.whatsapp.bridge_config import WhatsAppBridgeConfig
from parrot.integrations.whatsapp.bridge_wrapper import WhatsAppBridgeWrapper
from parrot.tools.toolkit import ToolkitTool
from parrot_tools.business_automation.models import BusinessOperation, OperationKind
from parrot_tools.business_automation.toolkit import BusinessAutomationToolkit


def _make_business_toolkit(tmp_path, *, kind: OperationKind) -> BusinessAutomationToolkit:
    """A minimal BusinessAutomationToolkit with a single operation of *kind*."""
    return BusinessAutomationToolkit(
        plans_dir=tmp_path,
        browser=None,
        operations={
            "an_operation": BusinessOperation(
                name="an_operation",
                description="A test operation",
                kind=kind,
                flow_ref="an_operation_flow",
            )
        },
    )


def _make_agent_with_toolkit(toolkit: BusinessAutomationToolkit) -> SimpleNamespace:
    """A fake agent exposing *toolkit* the same way a real registration
    would: a ``ToolkitTool`` bound to one of the toolkit's own methods,
    reachable via ``agent.tool_manager._tools`` — the exact path
    ``ToolManager.cleanup_toolkits()`` already walks.
    """
    tool = ToolkitTool(name="list_operations", bound_method=toolkit.list_operations)
    tool_manager = SimpleNamespace(_tools={"list_operations": tool})
    return SimpleNamespace(tool_manager=tool_manager)


def _make_agent_without_business_toolkit() -> SimpleNamespace:
    """A fake agent with a tool_manager but no BusinessAutomationToolkit at all."""
    return SimpleNamespace(tool_manager=SimpleNamespace(_tools={}))


class TestFailClosed:
    def test_empty_allowlist_with_submit_refuses(self, tmp_path):
        toolkit = _make_business_toolkit(tmp_path, kind=OperationKind.SUBMIT)
        agent = _make_agent_with_toolkit(toolkit)
        cfg = WhatsAppBridgeConfig(name="g", chatbot_id="gestoria", allowed_numbers=None)

        with pytest.raises(ValueError, match="allowed_numbers"):
            WhatsAppBridgeWrapper(agent=agent, config=cfg, app=web.Application())

    def test_empty_allowlist_with_submit_names_the_config(self, tmp_path):
        toolkit = _make_business_toolkit(tmp_path, kind=OperationKind.SUBMIT)
        agent = _make_agent_with_toolkit(toolkit)
        cfg = WhatsAppBridgeConfig(name="g", chatbot_id="gestoria", allowed_numbers=[])

        with pytest.raises(ValueError, match="gestoria"):
            WhatsAppBridgeWrapper(agent=agent, config=cfg, app=web.Application())

    def test_empty_allowlist_without_submit_is_allowed(self, tmp_path):
        toolkit = _make_business_toolkit(tmp_path, kind=OperationKind.READ)
        agent = _make_agent_with_toolkit(toolkit)
        cfg = WhatsAppBridgeConfig(name="g", chatbot_id="reader", allowed_numbers=None)

        # Must not raise.
        wrapper = WhatsAppBridgeWrapper(agent=agent, config=cfg, app=web.Application())
        assert wrapper.config is cfg

    def test_empty_allowlist_no_business_toolkit_is_allowed(self):
        agent = _make_agent_without_business_toolkit()
        cfg = WhatsAppBridgeConfig(name="g", chatbot_id="unrelated", allowed_numbers=None)

        # Unrelated bots (no BusinessAutomationToolkit at all) must be
        # completely unaffected by this control.
        wrapper = WhatsAppBridgeWrapper(agent=agent, config=cfg, app=web.Application())
        assert wrapper.config is cfg

    def test_draft_operation_does_not_trigger_failclosed(self, tmp_path):
        toolkit = _make_business_toolkit(tmp_path, kind=OperationKind.DRAFT)
        agent = _make_agent_with_toolkit(toolkit)
        cfg = WhatsAppBridgeConfig(name="g", chatbot_id="drafts", allowed_numbers=None)

        # DRAFT is unattended but has no legal effect — only SUBMIT gates.
        wrapper = WhatsAppBridgeWrapper(agent=agent, config=cfg, app=web.Application())
        assert wrapper.config is cfg

    def test_populated_allowlist_with_submit_starts_normally(self, tmp_path):
        toolkit = _make_business_toolkit(tmp_path, kind=OperationKind.SUBMIT)
        agent = _make_agent_with_toolkit(toolkit)
        cfg = WhatsAppBridgeConfig(name="g", chatbot_id="gestoria", allowed_numbers=["34600112233"])

        wrapper = WhatsAppBridgeWrapper(agent=agent, config=cfg, app=web.Application())
        assert wrapper.config is cfg


class TestNormalization:
    def test_normalizes_numbers(self):
        cfg = WhatsAppBridgeConfig(name="g", chatbot_id="x", allowed_numbers=["+34 600 11 22 33"])
        assert "34600112233" in cfg.normalized_allowed_numbers

    def test_empty_allowlist_normalizes_to_empty(self):
        cfg = WhatsAppBridgeConfig(name="g", chatbot_id="x", allowed_numbers=None)
        assert not cfg.normalized_allowed_numbers

    def test_is_authorized_accepts_differently_formatted_number(self, tmp_path):
        toolkit = _make_business_toolkit(tmp_path, kind=OperationKind.SUBMIT)
        agent = _make_agent_with_toolkit(toolkit)
        cfg = WhatsAppBridgeConfig(name="g", chatbot_id="gestoria", allowed_numbers=["+34 600 11 22 33"])
        wrapper = WhatsAppBridgeWrapper(agent=agent, config=cfg, app=web.Application())

        assert wrapper._is_authorized("34600112233") is True
        assert wrapper._is_authorized("+34-600-11-22-33") is True

    def test_is_authorized_rejects_unlisted_number(self, tmp_path):
        toolkit = _make_business_toolkit(tmp_path, kind=OperationKind.SUBMIT)
        agent = _make_agent_with_toolkit(toolkit)
        cfg = WhatsAppBridgeConfig(name="g", chatbot_id="gestoria", allowed_numbers=["34600112233"])
        wrapper = WhatsAppBridgeWrapper(agent=agent, config=cfg, app=web.Application())

        assert wrapper._is_authorized("34999999999") is False

    def test_is_authorized_allows_all_when_no_allowlist(self):
        agent = _make_agent_without_business_toolkit()
        cfg = WhatsAppBridgeConfig(name="g", chatbot_id="unrelated", allowed_numbers=None)
        wrapper = WhatsAppBridgeWrapper(agent=agent, config=cfg, app=web.Application())

        assert wrapper._is_authorized("34600112233") is True
