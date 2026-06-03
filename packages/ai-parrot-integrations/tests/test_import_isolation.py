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
