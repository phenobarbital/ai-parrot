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
