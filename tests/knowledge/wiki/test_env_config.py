"""Unit tests for FEAT-461 Module 1: env resolution + effective config."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from parrot.knowledge.wiki.project import (
    ClaudeIntegrationConfig,
    WikiConfigError,
    WikiEffectiveConfig,
    WikiEnvOverlay,
    WikiNamespaceConfig,
    WikiProjectConfig,
    derive_env_overlay,
    load_effective_config,
    overlay_path,
    resolve_wiki_env,
    save_env_overlay,
)
from pydantic import ValidationError

# --------------------------------------------------------------------------
# resolve_wiki_env
# --------------------------------------------------------------------------


class TestResolveWikiEnv:
    def test_default_is_local(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("WIKI_ENV", raising=False)
        monkeypatch.delenv("ENV", raising=False)
        assert resolve_wiki_env() == "local"

    def test_env_var_used(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("WIKI_ENV", raising=False)
        monkeypatch.setenv("ENV", "prod")
        assert resolve_wiki_env() == "prod"

    def test_wiki_env_beats_env(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("ENV", "prod")
        monkeypatch.setenv("WIKI_ENV", "dev")
        assert resolve_wiki_env() == "dev"

    def test_explicit_arg_beats_env_vars(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("WIKI_ENV", "dev")
        assert resolve_wiki_env("staging") == "staging"

    def test_invalid_charset_rejected(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("WIKI_ENV", "../evil")
        with pytest.raises(WikiConfigError):
            resolve_wiki_env()

    def test_per_call_env_reads(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("WIKI_ENV", raising=False)
        monkeypatch.delenv("ENV", raising=False)
        assert resolve_wiki_env() == "local"
        monkeypatch.setenv("ENV", "dev")
        assert resolve_wiki_env() == "dev"


# --------------------------------------------------------------------------
# WikiEffectiveConfig / load_effective_config
# --------------------------------------------------------------------------


class TestEffectiveConfig:
    def test_no_overlay_is_base(self, tmp_path: Path) -> None:
        effective = load_effective_config(tmp_path, env="dev")
        assert effective.overlay_path is None
        assert effective.env == "dev"
        assert effective.config.backend == "sqlite"  # WikiProjectConfig default

    def test_overlay_merges_shallow(self, tmp_path: Path) -> None:
        overlay_file = tmp_path / ".parrot" / "wiki.dev.json"
        overlay_file.parent.mkdir(parents=True)
        overlay_file.write_text(
            json.dumps({"backend": "arangodb", "arango_database": "wiki_x"}),
            encoding="utf-8",
        )
        effective = load_effective_config(tmp_path, env="dev")
        assert effective.overlay_path == overlay_file
        assert effective.config.backend == "arangodb"
        assert effective.config.arango_database == "wiki_x"
        # Untouched base field survives.
        assert effective.config.arango_text_analyzer == "text_en"

    def test_overlay_merges_nested_model_as_validated_instance(self, tmp_path: Path) -> None:
        """Regression: a nested-model overlay field (e.g. `claude`) must
        stay a validated instance after merge, not a raw dict left behind
        by `model_copy(update=overlay.model_dump())`."""
        overlay_file = tmp_path / ".parrot" / "wiki.dev.json"
        overlay_file.parent.mkdir(parents=True)
        overlay_file.write_text(
            json.dumps({"claude": {"nudge_tools": ["Grep"]}}),
            encoding="utf-8",
        )
        effective = load_effective_config(tmp_path, env="dev")
        assert isinstance(effective.config.claude, ClaudeIntegrationConfig)
        assert effective.config.claude.nudge_tools == ["Grep"]

    def test_namespaces_merge_per_key(self, tmp_path: Path) -> None:
        base_config = WikiProjectConfig(namespaces={"legal": WikiNamespaceConfig(path="../legal")})
        (tmp_path / ".parrot").mkdir(parents=True)
        (tmp_path / ".parrot" / "wiki.json").write_text(
            json.dumps(base_config.model_dump(mode="json")), encoding="utf-8"
        )
        overlay_file = tmp_path / ".parrot" / "wiki.dev.json"
        overlay_file.write_text(
            json.dumps({"namespaces": {"finance": {"path": "../finance"}}}),
            encoding="utf-8",
        )
        effective = load_effective_config(tmp_path, env="dev")
        assert set(effective.config.namespaces) == {"legal", "finance"}

    def test_namespaces_overlay_wins_on_collision(self, tmp_path: Path) -> None:
        base_config = WikiProjectConfig(namespaces={"legal": WikiNamespaceConfig(path="../legal")})
        (tmp_path / ".parrot").mkdir(parents=True)
        (tmp_path / ".parrot" / "wiki.json").write_text(
            json.dumps(base_config.model_dump(mode="json")), encoding="utf-8"
        )
        overlay_file = tmp_path / ".parrot" / "wiki.dev.json"
        overlay_file.write_text(
            json.dumps({"namespaces": {"legal": {"path": "../legal-override"}}}),
            encoding="utf-8",
        )
        effective = load_effective_config(tmp_path, env="dev")
        assert effective.config.namespaces["legal"].path == "../legal-override"

    def test_invalid_overlay_fails_loud_naming_file(self, tmp_path: Path) -> None:
        overlay_file = tmp_path / ".parrot" / "wiki.dev.json"
        overlay_file.parent.mkdir(parents=True)
        overlay_file.write_text("{not json", encoding="utf-8")
        with pytest.raises(WikiConfigError, match=str(overlay_file)):
            load_effective_config(tmp_path, env="dev")

    def test_overlay_rejects_secret_keys(self, tmp_path: Path) -> None:
        overlay_file = tmp_path / ".parrot" / "wiki.dev.json"
        overlay_file.parent.mkdir(parents=True)
        overlay_file.write_text(json.dumps({"password": "hunter2"}), encoding="utf-8")
        with pytest.raises(WikiConfigError, match=str(overlay_file)):
            load_effective_config(tmp_path, env="dev")

    def test_overlay_model_rejects_unknown_keys_directly(self) -> None:
        with pytest.raises(ValidationError):
            WikiEnvOverlay(password="hunter2")  # type: ignore[call-arg]
        with pytest.raises(ValidationError):
            WikiEnvOverlay(host="evil.example.com")  # type: ignore[call-arg]


# --------------------------------------------------------------------------
# derive_env_overlay / save_env_overlay
# --------------------------------------------------------------------------


class TestDeriveAndSave:
    def test_local_template_is_sqlite(self) -> None:
        base = WikiProjectConfig(backend="arangodb", arango_database="wiki_x")
        overlay = derive_env_overlay(base, "local")
        assert overlay.backend == "sqlite"
        assert overlay.arango_database is None

    def test_other_env_mirrors_base_same_database(self) -> None:
        base = WikiProjectConfig(
            backend="arangodb",
            arango_database="wiki_ai-parrot",
            arango_credentials_env="ARANGODB",
            arango_text_analyzer="text_en",
        )
        overlay = derive_env_overlay(base, "prod")
        assert overlay.backend == "arangodb"
        assert overlay.arango_database == "wiki_ai-parrot"
        assert overlay.arango_credentials_env == "ARANGODB"
        assert overlay.arango_text_analyzer == "text_en"

    def test_save_round_trips_and_is_atomic(self, tmp_path: Path) -> None:
        overlay = WikiEnvOverlay(backend="sqlite")
        path = save_env_overlay(tmp_path, "local", overlay)
        assert path == overlay_path(tmp_path, "local")
        assert path.exists()
        # No leftover tmp files.
        leftovers = list(path.parent.glob(".wiki.local-*"))
        assert leftovers == []

        effective = load_effective_config(tmp_path, env="local")
        assert effective.config.backend == "sqlite"
        assert effective.overlay_path == path

    def test_save_never_clobbers_silently_when_read_twice(self, tmp_path: Path) -> None:
        overlay = WikiEnvOverlay(backend="sqlite")
        path1 = save_env_overlay(tmp_path, "local", overlay)
        # Saving again with different content still succeeds (save itself
        # does not guard against clobbering — that discipline lives in the
        # `build` command, TASK-2463); this just verifies atomicity holds
        # on a second write too.
        overlay2 = WikiEnvOverlay(backend="memory")
        path2 = save_env_overlay(tmp_path, "local", overlay2)
        assert path1 == path2
        effective = load_effective_config(tmp_path, env="local")
        assert effective.config.backend == "memory"


# --------------------------------------------------------------------------
# WikiEffectiveConfig model shape
# --------------------------------------------------------------------------


def test_effective_config_field_compatible_with_project_config(
    tmp_path: Path,
) -> None:
    effective = load_effective_config(tmp_path, env="local")
    assert isinstance(effective, WikiEffectiveConfig)
    assert isinstance(effective.config, WikiProjectConfig)
    assert effective.env == "local"
