"""FEAT-726 — the configure() no-op decision is published to subclass overrides.

`AbstractBot.configure()` has been idempotent per instance since FEAT-721, but
the guard protected only the base pipeline: subclass overrides did their own
work around `await super().configure(app)` unguarded (issue:81fa838a18c1).

These tests pin the two signals that let an override skip correctly:

* `configure_skipped` — read AFTER `super().configure()` returned.
* `configure_is_noop(app)` — a sync predicate, asked BEFORE doing own work.

The case that matters most is CLI-then-server (an app arriving where none was
bound): there `configure_count == 2` while the pipeline genuinely DID run, so
the `configure_count > 1` recipe the docs used to prescribe is wrong.
"""

import inspect
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest
from aiohttp import web

from parrot.bots.abstract import AbstractBot

# The lifecycle stubs mirror test_double_configure.py's (FEAT-721). They are
# duplicated rather than imported because cross-test-module imports are not
# available under this suite's pytest import mode; keep the two in sync.


class _ConfigureTestBot(AbstractBot):
    """Concrete shell used to exercise AbstractBot lifecycle behavior."""

    async def ask(self, *args, **kwargs):
        """Satisfy the AbstractBot contract for a lifecycle-only test."""
        return None

    async def ask_stream(self, *args, **kwargs):
        """Satisfy the AbstractBot contract for a lifecycle-only test."""
        return None

    async def conversation(self, *args, **kwargs):
        """Satisfy the AbstractBot contract for a lifecycle-only test."""
        return None

    async def invoke(self, *args, **kwargs):
        """Satisfy the AbstractBot contract for a lifecycle-only test."""
        return None


def _stub_bot(cls: type = _ConfigureTestBot) -> AbstractBot:
    """Return a bot of ``cls`` with every configure collaborator stubbed.

    Built with ``object.__new__``, so ``__init__`` never runs and neither
    ``_configure_count`` nor ``_configure_skipped`` is set — which is exactly
    the instance shape the tolerant ``getattr`` in both properties exists for.
    """
    bot = object.__new__(cls)
    bot.logger = MagicMock()
    bot.configure_conversation_memory = MagicMock()
    bot.apply_tooling_specs = AsyncMock(return_value=[])
    bot.configure_kb = AsyncMock()
    bot._use_local_kb = False
    bot._llm_model_explicit = False
    bot._llm_raw = None
    bot._llm_preset = None
    bot._llm_kwargs = {}
    bot._llm_model = None
    bot._resolve_llm_config = MagicMock(return_value=MagicMock(model=None))
    bot._create_llm_client = MagicMock(return_value=MagicMock())
    bot.tool_manager = MagicMock(_server_param_source=None)
    bot.sync_tools = MagicMock()
    bot.get_tools_summary = MagicMock(
        return_value={
            "tools_enabled": False,
            "operation_mode": "",
            "tools_count": 0,
            "categories": [],
            "effective_mode": "",
        }
    )
    bot._define_prompt = MagicMock()
    bot._prompt_builder = None
    bot.define_store_config = MagicMock(return_value=None)
    bot._use_vector = False
    bot._vector_store = None
    bot._refresh_context_recs_from_store = MagicMock()
    bot.warmup_on_configure = False
    bot.store = None
    bot.use_kb = False
    bot._credentials = []
    bot.post_configure = AsyncMock()
    bot._llm_config = None
    bot._events_registry = MagicMock()
    bot.name = "test-bot"
    return bot


def _app() -> SimpleNamespace:
    """Return a truthy app wrapper around a stable resolved app object."""
    real = web.Application()
    real["configured"] = True
    return SimpleNamespace(get_app=lambda: real)

# ---------------------------------------------------------------------------
# Module 1 — the two published signals
# ---------------------------------------------------------------------------


def test_configure_is_noop_is_sync() -> None:
    """configure_is_noop is a plain def — pre-super overrides call it before any await."""
    assert not inspect.iscoroutinefunction(AbstractBot.configure_is_noop)


def test_configure_skipped_false_before_first_configure() -> None:
    """A fresh instance reports False, not a missing attribute.

    `_stub_bot()` builds the bot with `object.__new__`, so `__init__` never ran
    and `_configure_skipped` is genuinely absent — the tolerant getattr in the
    property is what makes this pass.
    """
    assert _stub_bot().configure_skipped is False


@pytest.mark.asyncio
async def test_configure_skipped_false_after_first_configure() -> None:
    """The first configure() runs the pipeline, so the flag stays False."""
    bot, app = _stub_bot(), _app()

    await bot.configure(app)

    assert bot.configure_skipped is False
    assert bot.configure_count == 1


@pytest.mark.asyncio
async def test_configure_skipped_true_on_repeat_same_app() -> None:
    """A second configure() with an unchanged app sets the flag True."""
    bot, app = _stub_bot(), _app()

    await bot.configure(app)
    await bot.configure(app)

    assert bot.configure_skipped is True
    assert bot.configure_count == 2
    bot.post_configure.assert_awaited_once()


@pytest.mark.asyncio
async def test_configure_skipped_true_on_bare_repeat_entry() -> None:
    """A bare re-entry after an app was bound is also a no-op."""
    bot, app = _stub_bot(), _app()

    await bot.configure(app)
    await bot.configure()

    assert bot.configure_skipped is True


@pytest.mark.asyncio
async def test_configure_skipped_false_when_app_arrives_later() -> None:
    """CLI-then-server: an app arriving where none was bound RUNS the pipeline.

    This is the case `configure_count > 1` gets wrong, and the reason this
    feature publishes the base's decision instead of letting overrides guess.
    """
    bot, app = _stub_bot(), _app()

    await bot.configure()
    await bot.configure(app)

    assert bot.configure_count == 2
    assert bot.configure_skipped is False
    assert bot.post_configure.await_count == 2


@pytest.mark.asyncio
async def test_configure_skipped_false_after_reconfigure() -> None:
    """reconfigure() resets the counter, so the pipeline runs and the flag is False."""
    bot, app = _stub_bot(), _app()

    await bot.configure(app)
    await bot.configure(app)
    assert bot.configure_skipped is True

    await bot.reconfigure()

    assert bot.configure_skipped is False
    assert bot.post_configure.await_count == 2


@pytest.mark.asyncio
async def test_configure_is_noop_matches_configure_decision() -> None:
    """The predicate agrees with the branch configure() actually takes.

    Asked before each call, `configure_is_noop(app)` must predict exactly the
    `configure_skipped` value observed after it — on all three paths.
    """
    bot, app = _stub_bot(), _app()

    # path 1: first call
    predicted = bot.configure_is_noop(app)
    await bot.configure(app)
    assert predicted is False and bot.configure_skipped is False

    # path 2: repeat with the same app
    predicted = bot.configure_is_noop(app)
    await bot.configure(app)
    assert predicted is True and bot.configure_skipped is True

    # path 3: an app arriving where none was bound
    fresh, later = _stub_bot(), _app()
    await fresh.configure()
    predicted = fresh.configure_is_noop(later)
    await fresh.configure(later)
    assert predicted is False and fresh.configure_skipped is False


@pytest.mark.asyncio
async def test_configure_is_noop_is_prospective_before_any_increment() -> None:
    """The predicate answers for the call about to be made, not the last one.

    A pre-super override asks BEFORE entering configure(), so after exactly one
    completed configure() (`configure_count == 1`) the predicate must already
    say True for an unchanged app. A `> 1` test would answer False here and let
    the override's pre-super work run a second time.
    """
    bot, app = _stub_bot(), _app()

    await bot.configure(app)

    assert bot.configure_count == 1
    assert bot.configure_is_noop(app) is True
    assert bot.configure_is_noop() is True


def test_resolve_configure_app_is_shared() -> None:
    """configure() and the predicate resolve the app through one helper."""
    bot, app = _stub_bot(), _app()

    assert bot._resolve_configure_app(None) is None
    assert bot._resolve_configure_app(app) is app.get_app()


# ---------------------------------------------------------------------------
# Module 2 — post-super overrides return early on configure_skipped
# ---------------------------------------------------------------------------


class _PostSuperBot(_ConfigureTestBot):
    """An override in the canonical post-super shape."""

    async def configure(self, app=None) -> None:
        """Do own setup only when the base pipeline actually ran."""
        await super().configure(app)
        if self.configure_skipped:
            return
        self.own_calls += 1


def _post_super_bot() -> AbstractBot:
    """Return a stubbed _PostSuperBot with its own-work counter zeroed."""
    bot = _stub_bot(_PostSuperBot)
    bot.own_calls = 0
    return bot


@pytest.mark.asyncio
async def test_post_super_work_skipped_on_repeat_configure() -> None:
    """A post-super override body runs ONCE across two configure() calls."""
    bot, app = _post_super_bot(), _app()

    await bot.configure(app)
    await bot.configure(app)

    assert bot.own_calls == 1
    assert bot.configure_count == 2


@pytest.mark.asyncio
async def test_post_super_work_runs_when_app_arrives_later() -> None:
    """The same body DOES run on a genuine reconfiguration (CLI-then-server).

    This is the regression a `configure_count > 1` guard would introduce: the
    counter is 2 here, yet the base pipeline ran and the override's setup is
    needed.
    """
    bot, app = _post_super_bot(), _app()

    await bot.configure()
    await bot.configure(app)

    assert bot.own_calls == 2
    assert bot.configure_count == 2


@pytest.mark.asyncio
async def test_post_super_work_runs_again_after_reconfigure() -> None:
    """reconfigure() is the supported way to force the override's setup again."""
    bot, app = _post_super_bot(), _app()

    await bot.configure(app)
    await bot.configure(app)
    await bot.reconfigure()

    assert bot.own_calls == 2


# The nine real post-super override sites (issue:81fa838a18c1). Each is checked
# structurally: the guard must follow its super().configure(...) call directly.
_POST_SUPER_SITES = [
    ("parrot.bots.agent", "BasicAgent"),
    ("parrot.bots.fireflies_insights", "FirefliesInsightsAgent"),
    ("parrot.agents.obsidian", "FirefliesObsidianAgent"),
    ("parrot.bots.chrome", "WebAgent"),
    ("parrot.bots.document", "DocumentAgent"),
    ("parrot.bots.flows.agents.orchestrator", "OrchestratorAgent"),
    ("parrot.bots.flows.agents.a2a_orchestrator", "A2AOrchestratorAgent"),
    ("parrot.bots.a2a_agent", "A2AAgent"),
    ("parrot_tools.computer.agent", "ComputerAgent"),
]


@pytest.mark.parametrize(("module_name", "class_name"), _POST_SUPER_SITES)
def test_post_super_override_is_guarded(module_name: str, class_name: str) -> None:
    """Every post-super override guards on configure_skipped, right after super().

    Structural rather than behavioural on purpose: the nine sites share one
    two-line mechanism (covered behaviourally above), and what regresses is a
    *new or edited* override losing its guard. Asserting the guard follows the
    super() call catches that for all nine without nine sets of heavy mocks.
    """
    import importlib

    module = pytest.importorskip(module_name)
    cls = getattr(importlib.import_module(module.__name__), class_name)
    source = inspect.getsource(cls.configure)
    lines = [ln.strip() for ln in source.splitlines()]

    super_calls = [i for i, ln in enumerate(lines) if ln.startswith("await super().configure(")]
    assert len(super_calls) == 1, f"{class_name}.configure: expected one super().configure() call"

    after = lines[super_calls[0] + 1 :]
    assert after[:2] == ["if self.configure_skipped:", "return"], (
        f"{class_name}.configure must guard its post-super work with "
        f"`if self.configure_skipped: return` immediately after super().configure(); got {after[:2]!r}"
    )
    assert "configure_count > 1" not in source, (
        f"{class_name}.configure uses the counter-based guard, which is wrong on "
        "the CLI-then-server path; use configure_skipped"
    )


# Sites assessed and deliberately NOT guarded (spec §1). Pinned so that
# "completing" the fix by guarding them fails loudly instead of silently
# changing behaviour that is already correct.
_EXEMPT_SITES = [
    ("parrot.bots.data", "PandasAgent"),
    ("parrot.bots.mixins.narrative", "NarrativeMixin"),
    ("parrot.bots.mixins.infographic_authoring", "InfographicAuthoringMixin"),
]


@pytest.mark.parametrize(("module_name", "class_name"), _EXEMPT_SITES)
def test_exempt_override_is_not_guarded(module_name: str, class_name: str) -> None:
    """The assessed-exempt overrides stay unguarded, for the reasons in the spec.

    data.py self-gates on `not self.dataframes`; NarrativeMixin is a pure
    passthrough; InfographicAuthoringMixin's set_bot() is idempotent behind a
    sentinel header. See docs/agent-configure-lifecycle.md §8.
    """
    import importlib

    module = pytest.importorskip(module_name)
    cls = getattr(importlib.import_module(module.__name__), class_name)
    source = inspect.getsource(cls.configure)

    assert "configure_skipped" not in source, (
        f"{class_name}.configure is a documented exemption (docs/agent-configure-lifecycle.md §8); "
        "guarding it was not intended — update the doc and the spec if that has genuinely changed"
    )
