"""FEAT-638: bot models default `language` to None (TASK-4125)."""

import re
from pathlib import Path

from parrot.handlers.models.bots import BotModel
from parrot.handlers.models.users_bots import UserBotModel


def test_bot_model_language_defaults_none():
    """The shared bot model leaves output language unset by default."""
    assert BotModel(name="x").language is None


def test_user_bot_model_language_defaults_none():
    """The per-user bot model leaves output language unset by default."""
    assert UserBotModel(user_id=1, name="x").language is None


def test_explicit_language_is_kept():
    """Explicit language choices remain available to both persistence models."""
    assert BotModel(name="x", language="es").language == "es"
    assert UserBotModel(user_id=1, name="x", language="es").language == "es"


def test_bot_config_carries_none_language():
    """Bot configuration keeps an unset output language unset."""
    assert BotModel(name="x").to_bot_config()["language"] is None
    assert UserBotModel(user_id=1, name="x").to_bot_kwargs()["language"] is None


def test_creation_sql_has_no_language_default():
    """Fresh-table DDL does not assign an output-language default."""
    package_root = Path(__file__).resolve().parents[1]
    ddl_paths = (
        package_root / "src/parrot/handlers/creation.sql",
        package_root / "src/parrot/handlers/models/users_bots_creation.sql",
    )
    default_pattern = re.compile(r"language\s+VARCHAR\(10\)\s+DEFAULT")

    assert all(not default_pattern.search(path.read_text(encoding="utf-8")) for path in ddl_paths)
