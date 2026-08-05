"""TASK-2136: Environment selector on WorkdayConfig + WORKDAY_* conf settings."""
from __future__ import annotations

import pytest
from parrot_tools.interfaces.workday import config as config_module
from parrot_tools.interfaces.workday.config import WorkdayConfig


class TestEnvResolution:
    def test_defaults_to_prod(self):
        assert WorkdayConfig().resolved_env == "prod"
        assert WorkdayConfig().resolved_is_sandbox is False

    @pytest.mark.parametrize(
        "value", ["sandbox", "impl", "implementation", "SANDBOX", " sandbox "]
    )
    def test_sandbox_aliases(self, value):
        # Explicit workday_url so the URL-alignment validator does not need
        # to resolve credentials just to determine resolved_is_sandbox.
        cfg = WorkdayConfig(env=value, workday_url="https://example.com")
        assert cfg.resolved_is_sandbox is True

    def test_sandbox_selects_impl_credentials(self, monkeypatch):
        """env=sandbox resolves WORKDAY_*_IMPL, not the production values."""
        monkeypatch.setattr(config_module, "WORKDAY_CLIENT_ID_IMPL", "impl-client-id")
        monkeypatch.setattr(config_module, "WORKDAY_CLIENT_SECRET_IMPL", "impl-secret")
        monkeypatch.setattr(config_module, "WORKDAY_TOKEN_URL_IMPL", "https://impl.example.com/token")
        monkeypatch.setattr(config_module, "WORKDAY_REFRESH_TOKEN_IMPL", "impl-refresh")
        monkeypatch.setattr(config_module, "WORKDAY_CLIENT_ID", "prod-client-id")
        monkeypatch.setattr(config_module, "WORKDAY_CLIENT_SECRET", "prod-secret")
        monkeypatch.setattr(config_module, "WORKDAY_TOKEN_URL", "https://prod.example.com/token")
        monkeypatch.setattr(config_module, "WORKDAY_REFRESH_TOKEN", "prod-refresh")

        cfg = WorkdayConfig(env="sandbox")
        assert cfg.resolved_client_id == "impl-client-id"
        assert cfg.resolved_client_secret == "impl-secret"
        assert cfg.resolved_token_url == "https://impl.example.com/token"
        assert cfg.resolved_refresh_token == "impl-refresh"

    def test_production_selects_prod_credentials(self, monkeypatch):
        monkeypatch.setattr(config_module, "WORKDAY_CLIENT_ID", "prod-client-id")
        monkeypatch.setattr(config_module, "WORKDAY_CLIENT_SECRET", "prod-secret")

        cfg = WorkdayConfig()
        assert cfg.resolved_client_id == "prod-client-id"
        assert cfg.resolved_client_secret == "prod-secret"

    def test_sandbox_missing_impl_raises(self, monkeypatch):
        """Unset _IMPL credential must raise, naming the setting — NEVER fall back to prod."""
        # token_url_impl must resolve so the URL-alignment validator does not
        # itself raise for a different (unrelated) missing setting.
        monkeypatch.setattr(config_module, "WORKDAY_TOKEN_URL_IMPL", "https://impl.example.com/token")
        monkeypatch.setattr(config_module, "WORKDAY_CLIENT_SECRET_IMPL", None)
        monkeypatch.setattr(config_module, "WORKDAY_CLIENT_SECRET", "prod-secret")

        cfg = WorkdayConfig(env="sandbox")
        with pytest.raises(ValueError, match="WORKDAY_CLIENT_SECRET_IMPL"):
            _ = cfg.resolved_client_secret

    def test_sandbox_missing_token_url_impl_raises_at_construction(self, monkeypatch):
        """Missing WORKDAY_TOKEN_URL_IMPL raises during construction (URL-alignment validator)."""
        monkeypatch.setattr(config_module, "WORKDAY_TOKEN_URL_IMPL", None)
        with pytest.raises(ValueError, match="WORKDAY_TOKEN_URL_IMPL"):
            WorkdayConfig(env="sandbox")

    def test_explicit_value_wins_over_conf(self):
        assert WorkdayConfig(client_id="explicit").resolved_client_id == "explicit"

    def test_explicit_value_wins_in_sandbox(self, monkeypatch):
        monkeypatch.setattr(config_module, "WORKDAY_CLIENT_ID_IMPL", None)
        cfg = WorkdayConfig(env="sandbox", client_id="explicit", token_url="https://x.example.com")
        assert cfg.resolved_client_id == "explicit"


class TestUrlAlignment:
    def test_align_url_to_sandbox_host(self, monkeypatch):
        monkeypatch.setattr(config_module, "WORKDAY_TOKEN_URL_IMPL", "https://impl.example.com/oauth/token")
        cfg = WorkdayConfig(env="sandbox")
        assert cfg.workday_url == "https://impl.example.com"

    def test_explicit_workday_url_respected(self, monkeypatch):
        monkeypatch.setattr(config_module, "WORKDAY_TOKEN_URL_IMPL", "https://impl.example.com/oauth/token")
        cfg = WorkdayConfig(env="sandbox", workday_url="https://custom.example.com")
        assert cfg.workday_url == "https://custom.example.com"

    def test_prod_url_untouched(self):
        cfg = WorkdayConfig()
        assert cfg.workday_url is None


class TestVendorNeutrality:
    def test_no_hardcoded_tenant_defaults(self):
        cfg = WorkdayConfig()
        assert cfg.tenant is None
        assert cfg.report_owner is None
        assert cfg.workday_url is None
