"""Unit tests for `parrot_formdesigner.services.sink_aliases` (FEAT-457, TASK-2418)."""

import pytest
from parrot_formdesigner.services.sink_aliases import SinkAliasRegistry


@pytest.fixture
def registry(tmp_path, monkeypatch):
    monkeypatch.setenv("SURVEY_DB_DSN", "postgresql://u:p@localhost/surveys")
    reg = SinkAliasRegistry()
    reg.register("survey_db", tenant="navigator", dsn_env="SURVEY_DB_DSN")
    reg.register("exports", tenant="navigator", base_dir=str(tmp_path))
    return reg


class TestSinkAliasRegistry:
    def test_unknown_alias_raises(self, registry):
        with pytest.raises(ValueError):
            registry.resolve_dsn("survey_db2", tenant="navigator")

    def test_alias_is_tenant_scoped(self, registry):
        with pytest.raises(ValueError):
            registry.resolve_dsn("survey_db", tenant="other")

    def test_resolves_via_get_env(self, registry):
        assert registry.resolve_dsn("survey_db", tenant="navigator").startswith(
            "postgresql://"
        )

    @pytest.mark.parametrize("bad", ["../escape.csv", "/etc/passwd"])
    def test_contain_rejects_escape(self, registry, bad):
        with pytest.raises(ValueError):
            registry.contain("exports", tenant="navigator", relative_path=bad)

    def test_contain_allows_inside(self, registry, tmp_path):
        got = registry.contain("exports", tenant="navigator", relative_path="nps.csv")
        assert got.parent == tmp_path.resolve()

    def test_contain_rejects_symlink_escape(self, registry, tmp_path):
        outside = tmp_path.parent / "outside_dir"
        outside.mkdir(exist_ok=True)
        link = tmp_path / "escape_link"
        link.symlink_to(outside, target_is_directory=True)
        with pytest.raises(ValueError):
            registry.contain(
                "exports", tenant="navigator", relative_path="escape_link/x.csv"
            )

    def test_is_allowed(self, registry):
        assert registry.is_allowed("survey_db", tenant="navigator") is True
        assert registry.is_allowed("survey_db", tenant="other") is False
        assert registry.is_allowed("nonexistent", tenant="navigator") is False

    def test_resolve_dsn_without_dsn_env_raises(self, registry):
        with pytest.raises(ValueError):
            registry.resolve_dsn("exports", tenant="navigator")

    def test_no_credential_logged(self, registry, caplog):
        caplog.set_level("DEBUG")
        registry.resolve_dsn("survey_db", tenant="navigator")
        for record in caplog.records:
            assert "postgresql://u:p@" not in record.getMessage()

    def test_resolve_credentials(self, monkeypatch):
        monkeypatch.setenv("GSHEET_CREDS", "service-account-blob")
        reg = SinkAliasRegistry()
        reg.register("sheets", tenant="navigator", credentials_env="GSHEET_CREDS")
        assert reg.resolve_credentials("sheets", tenant="navigator") == (
            "service-account-blob"
        )
