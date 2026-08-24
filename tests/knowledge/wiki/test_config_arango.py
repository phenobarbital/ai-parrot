"""Tests for the ArangoDB backend config extensions (FEAT-400, TASK-2058).

Covers ``WikiProjectConfig`` (``.parrot/wiki.json``), ``WikiConfig``
(runtime), and the ``resolve_arango_params()`` credential-resolution
helper.
"""

from pathlib import Path

import pytest
from parrot.knowledge.wiki.models import WikiConfig
from parrot.knowledge.wiki.project import WikiProjectConfig, resolve_arango_params


class TestWikiProjectConfigArango:
    """``WikiProjectConfig`` accepts the new ``arangodb`` backend."""

    def test_default_backend_unchanged(self):
        config = WikiProjectConfig()
        assert config.backend == "sqlite"

    def test_arangodb_backend_accepted(self):
        config = WikiProjectConfig(backend="arangodb")
        assert config.backend == "arangodb"

    def test_arango_fields_defaults(self):
        config = WikiProjectConfig(backend="arangodb")
        assert config.arango_database is None
        assert config.arango_credentials_env == "ARANGODB"
        assert config.arango_text_analyzer == "text_en"

    def test_arango_fields_explicit(self):
        config = WikiProjectConfig(
            backend="arangodb",
            arango_database="custom_wiki_db",
            arango_credentials_env="MY_ARANGO",
            arango_text_analyzer="text_es",
        )
        assert config.arango_database == "custom_wiki_db"
        assert config.arango_credentials_env == "MY_ARANGO"
        assert config.arango_text_analyzer == "text_es"

    def test_existing_config_no_arango_fields(self):
        config = WikiProjectConfig(wiki_name="test", backend="sqlite")
        assert config.arango_database is None
        assert config.arango_credentials_env == "ARANGODB"
        assert config.arango_text_analyzer == "text_en"

    def test_memory_backend_still_works(self):
        config = WikiProjectConfig(backend="memory")
        assert config.backend == "memory"

    def test_model_dump_roundtrip(self):
        config = WikiProjectConfig(backend="arangodb", arango_database="wiki_x")
        dumped = config.model_dump(mode="json")
        restored = WikiProjectConfig.model_validate(dumped)
        assert restored.backend == "arangodb"
        assert restored.arango_database == "wiki_x"


class TestWikiConfigArango:
    """``WikiConfig.storage_backend`` accepts ``"arangodb"``."""

    def test_storage_backend_arangodb_accepted(self, tmp_path: Path):
        config = WikiConfig(
            wiki_name="test-wiki",
            storage_dir=tmp_path,
            storage_backend="arangodb",
        )
        assert config.storage_backend == "arangodb"

    def test_storage_backend_default_unchanged(self, tmp_path: Path):
        config = WikiConfig(wiki_name="test-wiki", storage_dir=tmp_path)
        assert config.storage_backend == "sqlite"


class _FakeNavConfig:
    """Stand-in for navconfig's ``config`` — a `get` that may return None."""

    def __init__(self, values: dict | None = None):
        self.values = values or {}
        self.asked: list[str] = []

    def get(self, key, default=None):
        self.asked.append(key)
        return self.values.get(key, default)


def _clear_env(monkeypatch: pytest.MonkeyPatch, prefix: str = "ARANGODB") -> None:
    for suffix in ("HOST", "PORT", "PROTOCOL", "USERNAME", "PASSWORD"):
        monkeypatch.delenv(f"{prefix}_{suffix}", raising=False)


def _no_navconfig(monkeypatch: pytest.MonkeyPatch) -> None:
    """Neutralise the env-file layer so a test sees only what it sets.

    Required now that navconfig is in the resolution chain: this repo's
    own ``env/.env`` defines ``ARANGODB_*``, so "unset" means unset in
    BOTH sources.
    """
    monkeypatch.setattr("parrot.knowledge.wiki.project._navconfig", lambda: None)


class TestResolveArangoParams:
    """Credential resolution from ``ARANGODB_*`` (or custom-prefixed) env vars."""

    def test_defaults_when_env_unset(self, monkeypatch: pytest.MonkeyPatch):
        _clear_env(monkeypatch)
        _no_navconfig(monkeypatch)
        config = WikiProjectConfig(backend="arangodb", wiki_name="my-wiki")
        params = resolve_arango_params(config)
        assert params == {
            "host": "127.0.0.1",
            "port": 8529,
            "protocol": "http",
            "username": "root",
            "password": "",
            "database": "wiki_my-wiki",
        }

    def test_reads_env_vars(self, monkeypatch: pytest.MonkeyPatch):
        monkeypatch.setenv("ARANGODB_HOST", "arango.internal")
        monkeypatch.setenv("ARANGODB_PORT", "8530")
        monkeypatch.setenv("ARANGODB_PROTOCOL", "https")
        monkeypatch.setenv("ARANGODB_USERNAME", "wiki_user")
        monkeypatch.setenv("ARANGODB_PASSWORD", "secret")
        config = WikiProjectConfig(backend="arangodb", wiki_name="my-wiki")
        params = resolve_arango_params(config)
        assert params["host"] == "arango.internal"
        assert params["port"] == 8530
        assert params["protocol"] == "https"
        assert params["username"] == "wiki_user"
        assert params["password"] == "secret"

    def test_falls_back_to_navconfig_when_os_environ_is_empty(self, monkeypatch):
        """The actual bug: navconfig is what loads env/.env, so a process
        that never imported it resolved a remote wiki to 127.0.0.1."""
        _clear_env(monkeypatch)
        fake = _FakeNavConfig(
            {
                "ARANGODB_HOST": "arangodb.internal-dev.example.io",
                "ARANGODB_PORT": 443,
                "ARANGODB_PROTOCOL": "https",
                "ARANGODB_USERNAME": "root",
                "ARANGODB_PASSWORD": "s3cret",
            }
        )
        monkeypatch.setattr("parrot.knowledge.wiki.project._navconfig", lambda: fake)

        params = resolve_arango_params(WikiProjectConfig(backend="arangodb", wiki_name="w"))

        assert params["host"] == "arangodb.internal-dev.example.io"
        assert params["port"] == 443
        assert params["protocol"] == "https"
        assert params["password"] == "s3cret"
        assert "ARANGODB_HOST" in fake.asked

    def test_os_environ_wins_over_navconfig(self, monkeypatch: pytest.MonkeyPatch):
        """An explicit export (or a test's setenv) must not be shadowed."""
        _clear_env(monkeypatch)
        monkeypatch.setenv("ARANGODB_HOST", "exported.example.io")
        fake = _FakeNavConfig({"ARANGODB_HOST": "envfile.example.io"})
        monkeypatch.setattr("parrot.knowledge.wiki.project._navconfig", lambda: fake)

        params = resolve_arango_params(WikiProjectConfig(backend="arangodb", wiki_name="w"))

        assert params["host"] == "exported.example.io"

    def test_navconfig_values_are_type_normalised(self, monkeypatch: pytest.MonkeyPatch):
        """navconfig can hand back non-strings; the params dict must not."""
        _clear_env(monkeypatch)
        fake = _FakeNavConfig({"ARANGODB_PORT": 8530, "ARANGODB_PASSWORD": 12345})
        monkeypatch.setattr("parrot.knowledge.wiki.project._navconfig", lambda: fake)

        params = resolve_arango_params(WikiProjectConfig(backend="arangodb", wiki_name="w"))

        assert params["port"] == 8530 and isinstance(params["port"], int)
        assert params["password"] == "12345" and isinstance(params["password"], str)

    def test_unimportable_navconfig_degrades_to_defaults(self, monkeypatch):
        """This module is imported by the PreToolUse hook — a missing or
        broken navconfig must never make it raise.

        Exercises the REAL accessor: ``None`` in ``sys.modules`` makes
        ``from navconfig import config`` raise, so nothing here is stubbed
        out except the import itself.
        """
        import sys

        import parrot.knowledge.wiki.project as project_mod

        _clear_env(monkeypatch)
        monkeypatch.setitem(sys.modules, "navconfig", None)

        assert project_mod._navconfig() is None

        params = resolve_arango_params(WikiProjectConfig(backend="arangodb", wiki_name="w"))
        assert params["host"] == "127.0.0.1"
        assert params["port"] == 8529

    def test_custom_prefix_also_reaches_navconfig(self, monkeypatch: pytest.MonkeyPatch):
        _clear_env(monkeypatch, prefix="WIKI_ARANGO")
        fake = _FakeNavConfig({"WIKI_ARANGO_HOST": "isolated.example.io"})
        monkeypatch.setattr("parrot.knowledge.wiki.project._navconfig", lambda: fake)

        config = WikiProjectConfig(
            backend="arangodb", wiki_name="w", arango_credentials_env="WIKI_ARANGO"
        )
        params = resolve_arango_params(config)

        assert params["host"] == "isolated.example.io"

    def test_explicit_database_overrides_default(self):
        config = WikiProjectConfig(
            backend="arangodb", wiki_name="my-wiki", arango_database="shared_db"
        )
        params = resolve_arango_params(config)
        assert params["database"] == "shared_db"

    def test_custom_credentials_env_prefix(self, monkeypatch: pytest.MonkeyPatch):
        monkeypatch.setenv("MY_ARANGO_HOST", "custom-host")
        config = WikiProjectConfig(
            backend="arangodb",
            wiki_name="my-wiki",
            arango_credentials_env="MY_ARANGO",
        )
        params = resolve_arango_params(config)
        assert params["host"] == "custom-host"
