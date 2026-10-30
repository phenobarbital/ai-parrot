from pathlib import Path

import pytest

from parrot.auth.oauth2.descriptor import (
    OAuth2ProviderDescriptor,
    PostExchangeHookRegistry,
    load_provider_descriptors,
)

BASE = {
    "provider_id": "dummy",
    "display_name": "Dummy",
    "authorization_url": "https://idp/authorize",
    "token_url": "https://idp/token",
    "default_scopes": ["read"],
}


def test_descriptor_validation_and_secrets_from_conf():
    assert load_provider_descriptors([BASE])[0].provider_id == "dummy"
    with pytest.raises(ValueError, match="dummy"):
        load_provider_descriptors([{**BASE, "pkce": "sometimes"}])
    for secret_key in ("client_id", "client_secret", "redirect_uri"):
        with pytest.raises(ValueError) as exc_info:
            load_provider_descriptors([{**BASE, secret_key: "secret-value"}])
        assert "secret-value" not in str(exc_info.value)
    with pytest.raises(ValueError):
        load_provider_descriptors([BASE, BASE])


def test_post_exchange_hook_registry_is_typed():
    reg = PostExchangeHookRegistry()
    with pytest.raises(KeyError):
        reg.get("parrot.auth.jira_oauth:hook")

    async def hook(manager, payload, token_set):
        return token_set

    reg.register("noop", hook)
    assert reg.get("noop") is hook


def test_load_provider_descriptors_accepts_yaml_path_and_provider_mapping(tmp_path: Path):
    descriptor_file = tmp_path / "providers.yaml"
    descriptor_file.write_text("providers:\n  - provider_id: yaml\n    display_name: YAML\n    authorization_url: https://idp/authorize\n    token_url: https://idp/token\n    default_scopes: [read]\n", encoding="utf-8")

    descriptors = load_provider_descriptors(descriptor_file)

    assert descriptors == [
        OAuth2ProviderDescriptor(
            provider_id="yaml",
            display_name="YAML",
            authorization_url="https://idp/authorize",
            token_url="https://idp/token",
            default_scopes=["read"],
        )
    ]


def test_registry_rejects_invalid_registration():
    reg = PostExchangeHookRegistry()
    with pytest.raises(TypeError):
        reg.register("invalid", object())
    with pytest.raises(ValueError):
        reg.register("  ", lambda: None)
