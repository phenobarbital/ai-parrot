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


class TestResolveArangoParams:
    """Credential resolution from ``ARANGODB_*`` (or custom-prefixed) env vars."""

    def test_defaults_when_env_unset(self, monkeypatch: pytest.MonkeyPatch):
        for key in (
            "ARANGODB_HOST",
            "ARANGODB_PORT",
            "ARANGODB_PROTOCOL",
            "ARANGODB_USERNAME",
            "ARANGODB_PASSWORD",
        ):
            monkeypatch.delenv(key, raising=False)
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
