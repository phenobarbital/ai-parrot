"""FEAT-557 — WikiProjectConfig SQLite settings."""
from __future__ import annotations

import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from parrot.knowledge.wiki.project import (
    WikiConfigError,
    WikiProjectConfig,
    config_path,
    load_project_config,
    save_project_config,
)


class TestSQLiteConfigFields:
    def test_defaults(self) -> None:
        """Spec §2 defaults (AC-2)."""
        config = WikiProjectConfig()
        assert config.sqlite_busy_timeout == 15.0
        assert config.sqlite_performance_pragmas is False

    @pytest.mark.parametrize("value", [0.5, 0.0, 120.5, -1.0])
    def test_rejects_out_of_range(self, value: float) -> None:
        """Validated to 1-120 seconds (AC-2)."""
        with pytest.raises(ValidationError):
            WikiProjectConfig(sqlite_busy_timeout=value)

    @pytest.mark.parametrize("value", [1.0, 120.0])
    def test_accepts_bounds(self, value: float) -> None:
        """Both bounds are inclusive."""
        assert WikiProjectConfig(sqlite_busy_timeout=value).sqlite_busy_timeout == value

    def test_legacy_config_loads_with_defaults(self, tmp_path: Path) -> None:
        """A wiki.json written before FEAT-557 still loads (AC-2)."""
        path = config_path(tmp_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps({"wiki_name": "legacy", "backend": "sqlite"}),
            encoding="utf-8",
        )
        config = load_project_config(tmp_path)
        assert config.wiki_name == "legacy"
        assert config.sqlite_busy_timeout == 15.0
        assert config.sqlite_performance_pragmas is False

    def test_round_trip_persists_both_fields(self, tmp_path: Path) -> None:
        """Saving then loading preserves a non-default value."""
        config = WikiProjectConfig(
            wiki_name="roundtrip",
            sqlite_busy_timeout=30.0,
            sqlite_performance_pragmas=True,
        )
        save_project_config(tmp_path, config)
        reloaded = load_project_config(tmp_path)
        assert reloaded.sqlite_busy_timeout == 30.0
        assert reloaded.sqlite_performance_pragmas is True

    def test_invalid_persisted_value_raises_wiki_config_error(self, tmp_path: Path) -> None:
        """An out-of-range value on disk is a clear config error, not a crash."""
        path = config_path(tmp_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps({"wiki_name": "legacy", "sqlite_busy_timeout": 999}),
            encoding="utf-8",
        )
        with pytest.raises(WikiConfigError):
            load_project_config(tmp_path)
