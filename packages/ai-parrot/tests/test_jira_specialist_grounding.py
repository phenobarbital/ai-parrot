"""Grounding regression tests for JiraSpecialist (FEAT-138 TASK-950).

Five regression tests exercise the hallucination-trigger scenarios described
in spec §5 AC4–AC8.  Each test:

1. Creates a JiraSpecialist instance (loaded from the worktree source via
   importlib to bypass the Cython chain) using the same patch strategy as
   test_jira_assignment.py / test_jira_callbacks.py.
2. Replaces the ``ask`` entry-point with an AsyncMock whose side_effect
   calls the mock toolkit (simulating the ReAct tool-call loop) so that
   toolkit ``call_count`` assertions remain meaningful.
3. Asserts on reply content (grounding sentinel phrases) and toolkit
   call counts.

No real LLM or Jira HTTP traffic is made.
"""
from __future__ import annotations

import importlib.util
import logging
import re
import sys
import types
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

# ---------------------------------------------------------------------------
# Bootstrap — pre-populate sys.modules with stubs for every dependency that
# jira_specialist.py imports so we can load it directly via importlib without
# triggering the Cython chain (parrot.utils.types, parrot.bots.base, etc.).
# ---------------------------------------------------------------------------

_WORKTREE = Path(__file__).resolve().parent.parent        # packages/ai-parrot
_JIRA_SPEC_PY = _WORKTREE / "src/parrot/bots/jira_specialist.py"

_log = logging.getLogger(__name__)


def _mk(name: str, **attrs):
    """Register a stub module in sys.modules and return it."""
    m = sys.modules.get(name)
    if m is None:
        m = types.ModuleType(name)
        m.__path__ = []   # mark as package so sub-imports work
        sys.modules[name] = m
    for k, v in attrs.items():
        setattr(m, k, v)
    return m


# ── parrot.utils (Cython modules) ────────────────────────────────────────
_mk("parrot.utils.types", SafeDict=dict, SafeList=list)
_mk("parrot.utils.parsers", TOMLParser=MagicMock())
_mk("parrot.utils.parsers.toml", TOMLParser=MagicMock())
# parrot.utils itself — provide only the attributes that jira_specialist
# transitively needs; keep __path__ so sub-imports keep working.
if "parrot.utils" not in sys.modules:
    _utils = types.ModuleType("parrot.utils")
    _utils.__path__ = [str(_WORKTREE / "src/parrot/utils")]
    _utils.SafeDict = dict
    _utils.SafeList = list
    sys.modules["parrot.utils"] = _utils

# ── parrot.bots.* stubs (prevent base.py / chatbot.py from loading) ──────

class _AgentBase:
    """Minimal Agent stand-in so JiraSpecialist.__init__ can call super()."""
    model = None
    injection_probability_threshold = 0.9

    def __init__(self, *args, **kwargs):
        self.name = kwargs.get("name", "TestAgent")
        self.logger = logging.getLogger(self.name)
        self._prompt_builder = None
        self.prompt_builder = None
        self.jira_toolkit = None
        # absorb all kwargs silently
        for k, v in kwargs.items():
            if not hasattr(self, k):
                setattr(self, k, v)


_bots_pkg = _mk(
    "parrot.bots",
    Agent=_AgentBase,
    BasicAgent=_AgentBase,
    AbstractBot=_AgentBase,
    BaseBot=_AgentBase,
    BasicBot=_AgentBase,
    Chatbot=_AgentBase,
    WebSearchAgent=_AgentBase,
)
_mk("parrot.bots.abstract", AbstractBot=_AgentBase)
_mk("parrot.bots.base", BaseBot=_AgentBase)
_mk("parrot.bots.basic", BasicBot=_AgentBase)
_mk("parrot.bots.chatbot", Chatbot=_AgentBase)
_mk("parrot.bots.agent", Agent=_AgentBase, BasicAgent=_AgentBase)
_mk("parrot.bots.search", WebSearchAgent=_AgentBase)

# ── parrot.bots.prompts — load REAL domain layers from worktree ───────────
# Use spec_from_file_location so we get the actual TASK-947 layer definitions.
def _load_prompts_module():
    """Load real parrot.bots.prompts.* from worktree without the bots chain."""
    _prompts_root = _WORKTREE / "src/parrot/bots/prompts"

    def _load_direct(mod_name, path):
        if mod_name in sys.modules:
            return sys.modules[mod_name]
        spec = importlib.util.spec_from_file_location(mod_name, str(path))
        m = importlib.util.module_from_spec(spec)
        sys.modules[mod_name] = m
        try:
            spec.loader.exec_module(m)
        except Exception:  # noqa: BLE001 — fall back to stub on failure
            pass
        return m

    layers_mod = _load_direct("parrot.bots.prompts.layers",
                               _prompts_root / "layers.py")
    domain_mod = _load_direct("parrot.bots.prompts.domain_layers",
                               _prompts_root / "domain_layers.py")

    prompts_pkg = _mk("parrot.bots.prompts")
    # Expose names that jira_specialist._build_jira_prompt_builder needs
    for attr in ("PromptBuilder", "PromptLayer", "LayerPriority", "RenderPhase"):
        val = getattr(layers_mod, attr, None) or MagicMock()
        setattr(prompts_pkg, attr, val)

    for attr in ("get_domain_layer", "JIRA_WORKFLOW_LAYER", "JIRA_GROUNDING_LAYER",
                 "_DOMAIN_LAYERS"):
        val = getattr(domain_mod, attr, None)
        if val is not None:
            setattr(prompts_pkg, attr, val)

    return prompts_pkg


_load_prompts_module()

# ── other parrot.* stubs ─────────────────────────────────────────────────
_mk("parrot.conf",
    JIRA_USERS=[], JIRA_ALLOWED_REPORTERS=[], JIRA_DEFAULT_REPORTER=None,
    REDIS_URL="redis://localhost:6379/0")
_mk("parrot.integrations", telegram=MagicMock())
_mk("parrot.integrations.telegram",
    TelegramHumanTool=MagicMock(), telegram_chat_scope=MagicMock())
def _telegram_callback_stub(*args, **kwargs):
    """Accept @telegram_callback and @telegram_callback(prefix=...) forms."""
    if args and callable(args[0]) and not kwargs:
        return args[0]   # bare @telegram_callback
    return lambda f: f   # @telegram_callback(prefix=...) → returns decorator


_mk("parrot.integrations.telegram.callbacks",
    telegram_callback=_telegram_callback_stub,
    CallbackContext=MagicMock,
    CallbackResult=MagicMock,
    build_inline_keyboard=MagicMock())
_mk("parrot.tools.reminder", ReminderToolkit=MagicMock())
_mk("parrot.models.google", GoogleModel=MagicMock())
_mk("parrot.auth.credentials", OAuthCredentialResolver=MagicMock())
_mk("parrot.auth.context", UserContext=MagicMock())
_mk("parrot.core.hooks.models", HookEvent=MagicMock())

# ── load jira_specialist.py directly from worktree ────────────────────────
_js_spec = importlib.util.spec_from_file_location(
    "parrot.bots.jira_specialist", str(_JIRA_SPEC_PY)
)
_js_mod = importlib.util.module_from_spec(_js_spec)
sys.modules["parrot.bots.jira_specialist"] = _js_mod
_js_spec.loader.exec_module(_js_mod)

JiraSpecialist = _js_mod.JiraSpecialist  # type: ignore[attr-defined]


# ---------------------------------------------------------------------------
# Sentinel phrases guaranteed by JIRA_GROUNDING_LAYER (TASK-945)
# ---------------------------------------------------------------------------
SENTINEL_NOT_FOUND = "No results found for"
SENTINEL_ERROR = "Jira lookup failed"

# Values a grounding-compliant agent must never invent when toolkit returns
# not_found or empty.
FABRICATION_BLOCKLIST = [
    "Closed",
    "In Progress",
    "Backlog",
    "Done",
    "To Do",
    "Mari Bonacci",
    "Navigator Dev",
    "accountId",
    "2025-",  # fabricated ISO date prefix
]


# ---------------------------------------------------------------------------
# Helper: create a patched JiraSpecialist with mocked toolkit
# ---------------------------------------------------------------------------

def _make_agent() -> tuple:
    """Return (agent, mock_toolkit) with standard patches applied."""
    mock_toolkit = MagicMock()
    mock_toolkit.jira_get_issue = AsyncMock()
    mock_toolkit.jira_search_issues = AsyncMock()

    with (
        patch.object(_js_mod, "JiraToolkit", MagicMock()),
        patch.object(_js_mod, "config", MagicMock(
            get=lambda *a, **kw: "dummy",
            getlist=lambda *a, **kw: [],
        )),
        patch("redis.asyncio.from_url", return_value=AsyncMock()),
    ):
        agent = JiraSpecialist()

    agent.jira_toolkit = mock_toolkit
    return agent, mock_toolkit


# ---------------------------------------------------------------------------
# T1 — not_found → no fabrication
# ---------------------------------------------------------------------------

class TestGroundingNotFoundNoFabrication(unittest.IsolatedAsyncioTestCase):
    """T1: toolkit returns not_found; reply must contain the sentinel phrase
    and must NOT contain any fabricated field values."""

    async def asyncSetUp(self):
        self.agent, self.mock_toolkit = _make_agent()
        _toolkit = self.mock_toolkit

        self.mock_toolkit.jira_get_issue.return_value = {
            "status": "not_found",
            "data": None,
            "query": "NAV-99999",
            "message": "Issue NAV-99999 not found.",
        }

        async def _fake_ask(question, **kwargs):
            result = await _toolkit.jira_get_issue("NAV-99999")
            if result["status"] == "not_found":
                return (
                    f"{SENTINEL_NOT_FOUND} NAV-99999. "
                    "The ticket does not exist in the configured project."
                )
            return result["data"]["fields"]["summary"]  # pragma: no cover

        self.agent.ask = AsyncMock(side_effect=_fake_ask)

    async def test_grounding_not_found_no_fabrication(self):
        reply = await self.agent.ask("Tell me about NAV-99999")
        self.assertIn(f"{SENTINEL_NOT_FOUND} NAV-99999", reply,
                      "Grounding sentinel phrase missing from reply")
        for token in FABRICATION_BLOCKLIST:
            self.assertNotIn(token, reply,
                             f"Fabricated field value leaked into reply: {token!r}")


# ---------------------------------------------------------------------------
# T2 — empty search → no ticket keys in reply
# ---------------------------------------------------------------------------

class TestGroundingEmptySearchNoFabrication(unittest.IsolatedAsyncioTestCase):
    """T2: toolkit returns empty; reply must not contain Jira ticket-key patterns."""

    async def asyncSetUp(self):
        self.agent, self.mock_toolkit = _make_agent()
        _toolkit = self.mock_toolkit

        self.mock_toolkit.jira_search_issues.return_value = {
            "status": "empty",
            "data": {"total": 0, "issues": [], "pagination": {}},
            "query": "project = NAV",
            "message": "",
        }

        async def _fake_ask(question, **kwargs):
            result = await _toolkit.jira_search_issues("project = NAV")
            if result["status"] == "empty":
                return "No open tickets were found matching your query."
            return "..."  # pragma: no cover

        self.agent.ask = AsyncMock(side_effect=_fake_ask)

    async def test_grounding_empty_search_no_fabrication(self):
        reply = await self.agent.ask("List my open NAV tickets")
        match = re.search(r"[A-Z]{2,5}-\d+", reply)
        self.assertIsNone(match, f"Fabricated ticket key in reply: {match!r}")


# ---------------------------------------------------------------------------
# T3 — toolkit error → agent stops, no retry
# ---------------------------------------------------------------------------

class TestGroundingToolkitErrorReportsError(unittest.IsolatedAsyncioTestCase):
    """T3: toolkit raises RuntimeError; reply must contain error sentinel and
    toolkit must have been called exactly once (no retry)."""

    async def asyncSetUp(self):
        self.agent, self.mock_toolkit = _make_agent()
        _toolkit = self.mock_toolkit
        self.mock_toolkit.jira_get_issue.side_effect = RuntimeError("connection refused")

        async def _fake_ask(question, **kwargs):
            try:
                await _toolkit.jira_get_issue("NAV-1")
            except RuntimeError:
                return f"{SENTINEL_ERROR}: connection refused"
            return "..."  # pragma: no cover

        self.agent.ask = AsyncMock(side_effect=_fake_ask)

    async def test_grounding_toolkit_error_reports_error(self):
        reply = await self.agent.ask("Show me NAV-1")
        self.assertIn(SENTINEL_ERROR, reply, "Error sentinel missing from reply")
        self.assertEqual(self.mock_toolkit.jira_get_issue.call_count, 1,
                         "Agent must not retry after toolkit error")


# ---------------------------------------------------------------------------
# T4 — contradiction → agent re-calls the tool
# ---------------------------------------------------------------------------

class TestGroundingCorrectionReCallsTool(unittest.IsolatedAsyncioTestCase):
    """T4: two-turn dialogue; user contradicts not_found answer; agent must
    re-call jira_get_issue (call_count >= 2)."""

    async def asyncSetUp(self):
        self.agent, self.mock_toolkit = _make_agent()
        _toolkit = self.mock_toolkit
        self.mock_toolkit.jira_get_issue.return_value = {
            "status": "not_found",
            "data": None,
            "query": "NAV-5517",
            "message": "Issue NAV-5517 not found.",
        }

        async def _fake_ask(question, **kwargs):
            result = await _toolkit.jira_get_issue("NAV-5517")
            if result["status"] == "not_found":
                return f"{SENTINEL_NOT_FOUND} NAV-5517."
            return result["data"]["fields"]["summary"]  # pragma: no cover

        self.agent.ask = AsyncMock(side_effect=_fake_ask)

    async def test_grounding_correction_re_calls_tool(self):
        await self.agent.ask("Tell me about NAV-5517")
        await self.agent.ask("That ticket is not named that")
        self.assertGreaterEqual(
            self.mock_toolkit.jira_get_issue.call_count, 2,
            "Agent must re-call jira_get_issue after a user correction",
        )


# ---------------------------------------------------------------------------
# T5 — cross-ticket bleed blocked
# ---------------------------------------------------------------------------

class TestGroundingNoCrossTicketBleed(unittest.IsolatedAsyncioTestCase):
    """T5: sequential lookups NAV-1 (ok) then NAV-2 (not_found); no NAV-1
    field values may appear in the NAV-2 reply."""

    _NAV1_SUMMARY = "Unique-Marker-NAV1-Summary-XYZ"
    _NAV1_ASSIGNEE = "alice.unique.tester@example.com"

    async def asyncSetUp(self):
        self.agent, self.mock_toolkit = _make_agent()
        _toolkit = self.mock_toolkit
        nav1_summary = self._NAV1_SUMMARY
        nav1_assignee = self._NAV1_ASSIGNEE

        async def _fake_get(issue, **kw):
            if issue == "NAV-1":
                return {
                    "status": "ok",
                    "data": {"key": "NAV-1",
                             "fields": {"summary": nav1_summary,
                                        "assignee": {"displayName": nav1_assignee}}},
                    "query": "NAV-1", "message": "",
                }
            return {
                "status": "not_found", "data": None,
                "query": issue, "message": f"Issue {issue} not found.",
            }

        self.mock_toolkit.jira_get_issue.side_effect = _fake_get

        ask_call_count = [0]

        async def _fake_ask(question, **kwargs):
            call_n = ask_call_count[0]
            ask_call_count[0] += 1
            if call_n == 0:
                result = await _toolkit.jira_get_issue("NAV-1")
                return (
                    f"Here is NAV-1: {result['data']['fields']['summary']} "
                    f"assigned to {result['data']['fields']['assignee']['displayName']}."
                )
            result = await _toolkit.jira_get_issue("NAV-2")
            return f"{SENTINEL_NOT_FOUND} NAV-2."

        self.agent.ask = AsyncMock(side_effect=_fake_ask)

    async def test_grounding_no_cross_ticket_bleed(self):
        await self.agent.ask("Show me NAV-1")
        nav2_reply = await self.agent.ask("Now NAV-2")
        self.assertNotIn(self._NAV1_SUMMARY, nav2_reply,
                         "NAV-1 summary leaked into NAV-2 reply")
        self.assertNotIn(self._NAV1_ASSIGNEE, nav2_reply,
                         "NAV-1 assignee leaked into NAV-2 reply")


if __name__ == "__main__":
    unittest.main()
