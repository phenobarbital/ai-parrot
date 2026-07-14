"""
Import isolation tests for FEAT-205 — TeamsHumanChannel.

Proves that importing the Teams/botbuilder path does not pull aiogram
into sys.modules, and importing the Telegram/aiogram path does not pull
botbuilder into sys.modules.

This is the acceptance-criteria test for TASK-001 (D3 packaging constraint).
"""
import importlib
import sys


def _clean_modules(*prefixes: str) -> None:
    """Remove modules matching any of the given prefixes from sys.modules.

    Args:
        *prefixes: Module name prefixes to evict.
    """
    to_remove = [
        key for key in list(sys.modules)
        if any(key == p or key.startswith(p + ".") for p in prefixes)
    ]
    for key in to_remove:
        del sys.modules[key]


def test_teams_hitl_adapter_does_not_import_aiogram() -> None:
    """Importing HitlCloudAdapter must not pull aiogram into sys.modules.

    The Teams adapter (hitl_adapter.py) uses botbuilder only and must
    never indirectly import aiogram.  This is the import-isolation
    acceptance criterion for the botbuilder↔aiogram emoji clash (D3).
    """
    # Start from a clean slate for the relevant namespace.
    _clean_modules("parrot.integrations.msteams.hitl_adapter", "aiogram")

    # Ensure aiogram is not already present from a prior test.
    assert "aiogram" not in sys.modules, (
        "aiogram was already in sys.modules before import; "
        "isolate test ordering."
    )

    importlib.import_module("parrot.integrations.msteams.hitl_adapter")

    assert "aiogram" not in sys.modules, (
        "Importing parrot.integrations.msteams.hitl_adapter pulled aiogram "
        "into sys.modules — lazy import isolation is broken."
    )


def test_teams_hitl_cards_does_not_import_aiogram() -> None:
    """Importing TeamsCardRenderer must not pull aiogram into sys.modules."""
    _clean_modules("parrot.integrations.msteams.hitl_cards", "aiogram")

    assert "aiogram" not in sys.modules

    try:
        importlib.import_module("parrot.integrations.msteams.hitl_cards")
    except ImportError:
        # Module not yet created (TASK-003 pending) — skip gracefully.
        return

    assert "aiogram" not in sys.modules, (
        "Importing parrot.integrations.msteams.hitl_cards pulled aiogram "
        "into sys.modules — lazy import isolation is broken."
    )


def test_telegram_channel_does_not_import_botbuilder() -> None:
    """Importing TelegramHumanChannel must not pull botbuilder into sys.modules.

    The Telegram channel imports aiogram, which must stay isolated from
    botbuilder.  If this fails, importing the Teams HITL channel would
    indirectly break aiogram's emoji expectations (D3).
    """
    _clean_modules(
        "parrot.human.channels.telegram",
        "botbuilder",
        "botframework",
    )

    assert "botbuilder" not in sys.modules

    try:
        importlib.import_module("parrot.human.channels.telegram")
    except ImportError:
        # aiogram may not be installed in CI — skip gracefully.
        return

    botbuilder_mods = [k for k in sys.modules if k.startswith("botbuilder")]
    assert not botbuilder_mods, (
        f"Importing parrot.human.channels.telegram pulled botbuilder modules "
        f"into sys.modules: {botbuilder_mods!r}"
    )


def test_integrations_models_does_not_import_pywa() -> None:
    """Importing the shared config models must not pull pywa into sys.modules.

    ``parrot.integrations.models`` imports each channel's ``.models``, which
    in turn runs that channel's package ``__init__``.  The WhatsApp package
    must defer its pywa-dependent ``wrapper`` (PEP 562 lazy re-exports) so
    that ``IntegrationBotManager`` / the config models are importable in
    environments without the optional ``pywa`` dependency installed.
    """
    _clean_modules("parrot.integrations.models", "parrot.integrations.whatsapp", "pywa")

    assert "pywa" not in sys.modules

    mod = importlib.import_module("parrot.integrations.models")

    assert "pywa" not in sys.modules, (
        "Importing parrot.integrations.models pulled pywa into sys.modules — "
        "the WhatsApp package must lazily defer its pywa-dependent wrapper."
    )
    assert hasattr(mod, "WhatsAppAgentConfig")


def test_integration_manager_does_not_import_aiogram_or_pywa() -> None:
    """``IntegrationBotManager`` must import without aiogram or pywa.

    The manager coordinates every channel but only needs a channel's optional
    SDK when that channel is actually started.  Both ``aiogram`` (Telegram) and
    ``pywa`` (WhatsApp) are deferred — via ``from __future__ import annotations``
    plus lazy imports inside ``_start_telegram_bot`` — so a non-Telegram /
    non-WhatsApp deployment can construct the manager without them installed.
    """
    import builtins

    _clean_modules("parrot.integrations.manager", "aiogram", "pywa")

    real_import = builtins.__import__

    def _blocked_import(name, *args, **kwargs):
        top = name.split(".", 1)[0]
        if top in ("aiogram", "pywa"):
            raise ModuleNotFoundError(f"No module named '{name}'", name=name)
        return real_import(name, *args, **kwargs)

    builtins.__import__ = _blocked_import
    try:
        mod = importlib.import_module("parrot.integrations.manager")
    finally:
        builtins.__import__ = real_import

    assert "aiogram" not in sys.modules, (
        "Importing parrot.integrations.manager pulled aiogram into sys.modules."
    )
    assert "pywa" not in sys.modules, (
        "Importing parrot.integrations.manager pulled pywa into sys.modules."
    )
    assert hasattr(mod, "IntegrationBotManager")


def test_hitl_adapter_imports_botbuilder() -> None:
    """Sanity-check: the HITL adapter module does use botbuilder.

    If botbuilder is not installed this test is skipped rather than
    failing, so the isolation test suite stays green in stripped envs.
    """
    try:
        importlib.import_module("botbuilder.integration.aiohttp")
    except ImportError:
        return  # botbuilder not installed — nothing to check.

    mod = importlib.import_module("parrot.integrations.msteams.hitl_adapter")
    assert hasattr(mod, "HitlCloudAdapter"), (
        "HitlCloudAdapter not found in parrot.integrations.msteams.hitl_adapter"
    )


# ---------------------------------------------------------------------------
# FEAT-303 — Semantic UI Model / Adaptive Card renderer import isolation
# ---------------------------------------------------------------------------


def _evict_and_restore(monkeypatch, *prefixes: str) -> None:
    """Evict sys.modules entries matching prefixes, restored at teardown.

    Unlike `_clean_modules` (a permanent, unrestored deletion — fine for the
    isolation tests above since nothing downstream re-imports `aiogram`/
    `botbuilder`/`pywa` with `isinstance` checks against their types), the
    FEAT-303 tests below evict and re-import `parrot.integrations.msagentsdk`
    submodules that define Pydantic model classes (`SemanticUIResult`,
    `StatusPayload`, etc.) consumed via `isinstance` elsewhere in the suite
    (`agent.py`'s card seam, `cards.py`'s renderers). A permanent eviction
    would leave a *second*, distinct copy of those classes in `sys.modules`
    for the rest of the pytest session — any test file that imported them
    at collection time keeps referencing the *original* classes, while
    anything that re-imports afterwards gets the *new* ones, breaking
    `isinstance` across test files (observed as spurious failures in
    `test_msagent_semantic_bridge.py` when the full suite ran in one
    session). Using `monkeypatch.delitem` instead means pytest restores the
    original module objects at this test's teardown, so no state leaks to
    later tests.

    Args:
        monkeypatch: The pytest `MonkeyPatch` fixture for this test.
        *prefixes: Module name prefixes to evict for the duration of the test.
    """
    to_remove = [
        key
        for key in list(sys.modules)
        if any(key == p or key.startswith(p + ".") for p in prefixes)
    ]
    for key in to_remove:
        monkeypatch.delitem(sys.modules, key)


def test_msagentsdk_semantic_and_cards_import_without_microsoft_agents(
    monkeypatch,
) -> None:
    """`semantic.py` / `cards.py` must import with `microsoft_agents` blocked.

    Even if `microsoft-agents-*` is installed in this environment, these two
    modules must never actually import it — they are pure Pydantic /
    plain-dict modules (FEAT-303 spec §7). Blocking the import via
    `builtins.__import__` (same technique as
    `test_integration_manager_does_not_import_aiogram_or_pywa`) proves the
    modules do not depend on it, regardless of what happens to be installed.
    """
    import builtins

    _evict_and_restore(
        monkeypatch,
        "parrot.integrations.msagentsdk.semantic",
        "parrot.integrations.msagentsdk.cards",
        "microsoft_agents",
    )

    real_import = builtins.__import__

    def _blocked_import(name, *args, **kwargs):
        if name == "microsoft_agents" or name.startswith("microsoft_agents."):
            raise ModuleNotFoundError(f"No module named '{name}'", name=name)
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", _blocked_import)
    semantic_mod = importlib.import_module("parrot.integrations.msagentsdk.semantic")
    cards_mod = importlib.import_module("parrot.integrations.msagentsdk.cards")
    # monkeypatch fixture automatically restores builtins.__import__ and the
    # evicted sys.modules entries at test teardown.

    assert "microsoft_agents" not in sys.modules, (
        "Importing semantic.py/cards.py pulled microsoft_agents into "
        "sys.modules — these modules must stay SDK-independent."
    )
    assert hasattr(semantic_mod, "SemanticUIResult")
    assert hasattr(cards_mod, "render_card")
    assert hasattr(cards_mod, "render_text")


def test_msagentsdk_lazy_exports_resolve_semantic_ui_names(monkeypatch) -> None:
    """`msagentsdk.__getattr__` resolves the new FEAT-303 public names."""
    _evict_and_restore(monkeypatch, "parrot.integrations.msagentsdk")

    import parrot.integrations.msagentsdk as msagentsdk_pkg

    assert msagentsdk_pkg.SemanticUIResult is not None
    assert msagentsdk_pkg.UIAction is not None
    assert callable(msagentsdk_pkg.render_card)
    assert callable(msagentsdk_pkg.render_text)
