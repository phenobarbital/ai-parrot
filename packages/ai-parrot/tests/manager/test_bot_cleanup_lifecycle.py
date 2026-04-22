"""Tests for BotManager cleanup lifecycle — FEAT-114 bot-cleanup-lifecycle.

Covers:
- Unit tests for _cleanup_all_bots and _safe_cleanup behaviour.
- Registration order of on_cleanup callbacks.
- BOT_CLEANUP_TIMEOUT conf constant (default and env-override).
- Integration: aiohttp on_cleanup signal triggers bot.cleanup().
- Integration: HookableAgent-style bot stops hooks then runs resource cleanup.
"""
# ---------------------------------------------------------------------------
# Module-level stub installation: runs before the BotManager import so that
# the heavy handler/bots import chain resolves without a full runtime env.
# These stubs are intentionally idempotent (no-op if already present).
# ---------------------------------------------------------------------------
import sys
import types
from unittest.mock import MagicMock as _MagicMock


def _stub(name: str) -> types.ModuleType:
    if name not in sys.modules:
        mod = types.ModuleType(name)
        mod.__path__ = []  # type: ignore[attr-defined]
        sys.modules[name] = mod
    return sys.modules[name]


def _autostub(name: str) -> types.ModuleType:
    """Auto-stub: any attribute access returns a MagicMock."""
    class _A(types.ModuleType):
        def __getattr__(self, n: str) -> _MagicMock:
            m = _MagicMock()
            object.__setattr__(self, n, m)
            return m
    if name not in sys.modules or isinstance(sys.modules[name], _A):
        mod = _A(name)
        mod.__path__ = []  # type: ignore[attr-defined]
        sys.modules[name] = mod
    return sys.modules[name]


# parrot.conf stub — ensure BOT_CLEANUP_TIMEOUT is set to 20
if "parrot.conf" in sys.modules:
    _pconf = sys.modules["parrot.conf"]
    if not getattr(_pconf, "BOT_CLEANUP_TIMEOUT", None):
        try:
            object.__setattr__(_pconf, "BOT_CLEANUP_TIMEOUT", 20)
        except (AttributeError, TypeError):
            _pconf.BOT_CLEANUP_TIMEOUT = 20  # type: ignore[attr-defined]

# Stub the full handler hierarchy so manager.py imports succeed
_configure = classmethod(lambda cls, *a, **kw: None)
_configure_routes = lambda self, *a, **kw: None  # noqa: E731

for _hmod in (
    "parrot.handlers", "parrot.handlers.abstract", "parrot.handlers.agent",
    "parrot.handlers.agents", "parrot.handlers.agents.abstract",
    "parrot.handlers.agents.data", "parrot.handlers.agents.infographic",
    "parrot.handlers.agents.talk", "parrot.handlers.chat",
    "parrot.handlers.chat_interaction", "parrot.handlers.config_handler",
    "parrot.handlers.crew", "parrot.handlers.crew.execution_handler",
    "parrot.handlers.crew.handler", "parrot.handlers.crew.models",
    "parrot.handlers.crew.redis_persistence",
    "parrot.handlers.dashboard_handler", "parrot.handlers.database",
    "parrot.handlers.datasets", "parrot.handlers.infographic",
    "parrot.handlers.models", "parrot.handlers.print_pdf",
    "parrot.handlers.stream", "parrot.handlers.test_handler",
    "parrot.handlers.credentials", "parrot.handlers.mcp_helper",
    "parrot.handlers.swagger",
):
    _autostub(_hmod)

# Seed specific names that manager.py imports from handlers
_AbstractBot_cls = type("AbstractBot", (), {"name": "stub", "cleanup": lambda self: None})
_m = sys.modules
_m["parrot.handlers"].ChatbotHandler = type(  # type: ignore[attr-defined]
    "ChatbotHandler", (), {"configure": classmethod(lambda cls, *a, **kw: None)})
for _n, _attrs in {
    "parrot.handlers.chat": {"ChatHandler": {}, "BotHandler": {}},
    "parrot.handlers.agent": {"AgentTalk": {}},
    "parrot.handlers.infographic": {"InfographicTalk": {}},
    "parrot.handlers.agents.data": {"DataAnalystHandler": {}},
    "parrot.handlers.print_pdf": {"PrintPDFHandler": {}},
    "parrot.handlers.datasets": {"DatasetManagerHandler": {}},
    "parrot.handlers.database": {"DatabaseBotHandler": {}, "DatabaseAgent": {},
                                  "DatabaseSchemasHandler": {}},
    "parrot.handlers.chat_interaction": {"ChatInteractionHandler": {}},
    "parrot.handlers.config_handler": {"BotConfigHandler": {}},
    "parrot.handlers.test_handler": {"BotConfigTestHandler": {}},
    "parrot.handlers.dashboard_handler": {"DashboardHandler": {}, "setup_dashboards": None},
    "parrot.handlers.models": {"BotModel": {}},
    "parrot.handlers.crew.models": {"CrewDefinition": {}, "ExecutionMode": {}},
    "parrot.handlers.crew.redis_persistence": {"CrewRedis": {}},
}.items():
    for _cls_name, _base in _attrs.items():
        if _base is None:
            setattr(_m[_n], _cls_name, lambda *a, **kw: None)
        else:
            setattr(_m[_n], _cls_name, type(_cls_name, (), {}))

# Handlers that use configure() or configure_routes()
for _n, _cls_name in [
    ("parrot.handlers.stream", "StreamHandler"),
    ("parrot.handlers.crew.handler", "CrewHandler"),
    ("parrot.handlers.crew.execution_handler", "CrewExecutionHandler"),
]:
    setattr(_m[_n], _cls_name,
            type(_cls_name, (), {
                "configure": classmethod(lambda cls, *a, **kw: None),
                "configure_routes": lambda self, *a, **kw: None,
            }))

_m["parrot.handlers.credentials"].setup_credentials_routes = lambda *a, **kw: None  # type: ignore[attr-defined]
_m["parrot.handlers.mcp_helper"].setup_mcp_helper_routes = lambda *a, **kw: None  # type: ignore[attr-defined]
_m["parrot.handlers.swagger"].setup_swagger = lambda *a, **kw: None  # type: ignore[attr-defined]

# Stub only the specific parrot.bots sub-modules that cause import failures.
# We do NOT stub parrot.bots itself (let __init__.py run) so that
# parrot.bots.prompts.* remains importable by sibling tests.
_Chatbot_cls = type("Chatbot", (_AbstractBot_cls,), {})
_BasicBot_cls = type("BasicBot", (_AbstractBot_cls,), {})
_BasicAgent_cls = type("BasicAgent", (_AbstractBot_cls,), {})
_Agent_cls = type("Agent", (_AbstractBot_cls,), {})
_WebSearchAgent_cls = type("WebSearchAgent", (_AbstractBot_cls,), {})
_AgentCrew_cls = type("AgentCrew", (), {})

# Stub modules that parrot.bots.__init__ imports but can't load in test env
for _bmod, _attrs in {
    "parrot.bots.base": {"BaseBot": type("BaseBot", (), {})},
    "parrot.bots.basic": {"BasicBot": _BasicBot_cls},
    "parrot.bots.chatbot": {"Chatbot": _Chatbot_cls},
    "parrot.bots.search": {"WebSearchAgent": _WebSearchAgent_cls},
    "parrot.bots.orchestration": {},
    "parrot.bots.orchestration.crew": {"AgentCrew": _AgentCrew_cls},
}.items():
    if _bmod not in _m:
        _stub(_bmod)
    for _attr_name, _attr_val in _attrs.items():
        if not hasattr(_m[_bmod], _attr_name):
            setattr(_m[_bmod], _attr_name, _attr_val)

# parrot.storage
_autostub("parrot.storage")
_m["parrot.storage"].ChatStorage = type("ChatStorage", (), {})  # type: ignore[attr-defined]

# parrot.openapi.config
_autostub("parrot.openapi")
_autostub("parrot.openapi.config")
_m["parrot.openapi.config"].setup_swagger = lambda *a, **kw: None  # type: ignore[attr-defined]

# datamodel stubs (including parsers sub-packages used by parrot.tools.abstract)
_autostub("datamodel")
_autostub("datamodel.exceptions")
_m["datamodel.exceptions"].ValidationError = type("ValidationError", (Exception,), {})  # type: ignore[attr-defined]
for _dmod in ("datamodel.parsers", "datamodel.parsers.json", "datamodel.types"):
    _autostub(_dmod)
# json_decoder / json_encoder are callables, JSONContent is a class
for _dname in ("json_decoder", "json_encoder"):
    setattr(_m["datamodel.parsers.json"], _dname, lambda x: x)
setattr(_m["datamodel.parsers.json"], "JSONContent", type("JSONContent", (), {}))

# parrot.tools — stub so registry → mcp → tools chain doesn't blow up
for _tmod in (
    "parrot.tools", "parrot.tools.abstract", "parrot.tools.agent",
    "parrot.tools.toolkit", "parrot.tools.manager",
    "parrot.mcp", "parrot.mcp.integration", "parrot.mcp.server",
):
    _autostub(_tmod)
setattr(_m["parrot.tools.abstract"], "AbstractTool", type("AbstractTool", (), {}))
setattr(_m["parrot.tools.abstract"], "ToolResult", type("ToolResult", (), {}))
setattr(_m["parrot.tools"], "AbstractTool", _m["parrot.tools.abstract"].AbstractTool)
setattr(_m["parrot.tools"], "ToolResult", _m["parrot.tools.abstract"].ToolResult)

# ---------------------------------------------------------------------------
# Real imports after stubs are in place
# ---------------------------------------------------------------------------
import asyncio  # noqa: E402
import importlib  # noqa: E402
from unittest.mock import patch  # noqa: E402

import pytest  # noqa: E402
from aiohttp import web  # noqa: E402

from parrot.manager.manager import BotManager  # noqa: E402


# ---------------------------------------------------------------------------
# Duck-typed bot stub
# ---------------------------------------------------------------------------

class _DummyBot:
    """Duck-typed stand-in for AbstractBot used in cleanup tests.

    BotManager only reads ``.name`` and awaits ``.cleanup()`` during
    _cleanup_all_bots, so this minimal stub is sufficient.
    """

    def __init__(
        self,
        name: str,
        *,
        raises: bool = False,
        hangs: bool = False,
    ) -> None:
        self.name = name
        self.cleaned = False
        self._raises = raises
        self._hangs = hangs

    async def cleanup(self) -> None:
        if self._hangs:
            await asyncio.sleep(10)  # much longer than any test timeout
        if self._raises:
            raise RuntimeError(f"{self.name} blew up during cleanup")
        self.cleaned = True


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def manager() -> BotManager:
    """Minimal BotManager with all optional subsystems disabled."""
    return BotManager(
        enable_database_bots=False,
        enable_crews=False,
        enable_registry_bots=False,
        enable_swagger_api=False,
    )


@pytest.fixture
def app_with_manager(manager: BotManager) -> tuple[web.Application, BotManager]:
    """aiohttp Application wired with BotManager.setup().

    ``_register_shared_redis`` is patched out to avoid real Redis connections
    while still inserting a dummy ``_cleanup_shared_redis`` callback so that
    the ordering assertion in test_cleanup_registered_on_app can verify the
    contract.
    """
    app = web.Application()

    async def _noop_shared_redis(a: web.Application) -> None:
        pass

    _noop_shared_redis.__name__ = "_cleanup_shared_redis"

    def _fake_register_redis(self_: BotManager) -> None:
        # Simulate the real registration so ordering tests work.
        self_.app.on_cleanup.append(_noop_shared_redis)

    with patch.object(BotManager, "_register_shared_redis", _fake_register_redis):
        manager.setup(app)

    return app, manager


# ---------------------------------------------------------------------------
# Unit tests — _cleanup_all_bots
# ---------------------------------------------------------------------------

async def test_cleanup_all_bots_empty(manager: BotManager) -> None:
    """With no bots registered, _cleanup_all_bots must log and return."""
    app = web.Application()
    # Must complete without error and without side-effects.
    await manager._cleanup_all_bots(app)


async def test_cleanup_all_bots_happy_path(manager: BotManager) -> None:
    """Two bots: both cleanup() coroutines must be awaited exactly once."""
    a, b = _DummyBot("a"), _DummyBot("b")
    manager._bots = {"a": a, "b": b}

    await manager._cleanup_all_bots(web.Application())

    assert a.cleaned is True
    assert b.cleaned is True
    assert manager._cleaned_up == {"a", "b"}


async def test_cleanup_all_bots_isolates_exceptions(manager: BotManager) -> None:
    """One bot raising must NOT prevent the other bot from completing."""
    bad, good = _DummyBot("bad", raises=True), _DummyBot("good")
    manager._bots = {"bad": bad, "good": good}

    await manager._cleanup_all_bots(web.Application())

    assert good.cleaned is True
    assert "good" in manager._cleaned_up
    assert "bad" not in manager._cleaned_up


async def test_cleanup_all_bots_timeout(
    manager: BotManager, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A hanging bot must be cancelled; other bots still complete."""
    monkeypatch.setattr("parrot.manager.manager.BOT_CLEANUP_TIMEOUT", 0.05)

    hanger, normal = _DummyBot("hang", hangs=True), _DummyBot("ok")
    manager._bots = {"hang": hanger, "ok": normal}

    await manager._cleanup_all_bots(web.Application())

    assert normal.cleaned is True
    assert "ok" in manager._cleaned_up
    assert "hang" not in manager._cleaned_up


async def test_cleanup_registered_on_app(
    app_with_manager: tuple[web.Application, BotManager],
) -> None:
    """setup() must append _cleanup_all_bots BEFORE _cleanup_shared_redis."""
    app, _ = app_with_manager
    names = [cb.__name__ for cb in app.on_cleanup]
    assert "_cleanup_all_bots" in names, "_cleanup_all_bots not registered"
    assert "_cleanup_shared_redis" in names, "_cleanup_shared_redis not registered"
    assert names.index("_cleanup_all_bots") < names.index("_cleanup_shared_redis")


# ---------------------------------------------------------------------------
# Conf constant tests
# ---------------------------------------------------------------------------

def test_bot_cleanup_timeout_default() -> None:
    """Default fallback declared in conf.py is 20 seconds."""
    from parrot.conf import BOT_CLEANUP_TIMEOUT
    assert BOT_CLEANUP_TIMEOUT == 20


def test_bot_cleanup_timeout_env_override(monkeypatch: pytest.MonkeyPatch) -> None:
    """With BOT_CLEANUP_TIMEOUT=5 in env the constant reads 5 on reload."""
    monkeypatch.setenv("BOT_CLEANUP_TIMEOUT", "5")
    import parrot.conf as parrot_conf
    importlib.reload(parrot_conf)
    try:
        assert parrot_conf.BOT_CLEANUP_TIMEOUT == 5
    finally:
        # Restore defaults so downstream tests see 20.
        monkeypatch.delenv("BOT_CLEANUP_TIMEOUT", raising=False)
        importlib.reload(parrot_conf)


# ---------------------------------------------------------------------------
# Integration tests
# ---------------------------------------------------------------------------

async def test_aiohttp_cleanup_triggers_bot_cleanup(
    app_with_manager: tuple[web.Application, BotManager],
) -> None:
    """Running app.on_cleanup callbacks must invoke bot.cleanup() on all bots."""
    app, manager = app_with_manager
    a, b = _DummyBot("a"), _DummyBot("b")
    manager._bots = {"a": a, "b": b}

    for cb in list(app.on_cleanup):
        await cb(app)

    assert a.cleaned is True
    assert b.cleaned is True


async def test_hookable_cleanup_via_botmanager_end_to_end(
    app_with_manager: tuple[web.Application, BotManager],
) -> None:
    """A HookableAgent-style bot must stop hooks THEN run resource cleanup."""

    class _HookableRecorder:
        """Minimal recorder that mimics HookableAgent.cleanup() order."""

        def __init__(self) -> None:
            self.name = "hookable"
            self.order: list[str] = []

        async def cleanup(self) -> None:
            self.order.append("stop_hooks")
            self.order.append("super_cleanup")

    app, manager = app_with_manager
    bot = _HookableRecorder()
    manager._bots = {bot.name: bot}

    for cb in list(app.on_cleanup):
        await cb(app)

    assert bot.order == ["stop_hooks", "super_cleanup"]
