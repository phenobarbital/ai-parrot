"""Unit tests for per-component LLM default resolution."""

import pytest

from parrot import llm_defaults as ld
from parrot.clients import factory


@pytest.fixture
def env(monkeypatch: pytest.MonkeyPatch) -> dict[str, str]:
    """Provide hermetic configuration and supported LLM providers."""
    values: dict[str, str] = {}
    monkeypatch.setattr(ld.config, "get", lambda key, fallback=None: values.get(key, fallback))
    monkeypatch.setattr(ld.conf, "DEFAULT_LLM", None, raising=False)
    monkeypatch.setattr(factory, "SUPPORTED_CLIENTS", {"google": object(), "openai": object()})
    return values


def test_resolve_builtin_when_unset(env: dict[str, str]) -> None:
    """Builtins are retained when no component or global default is set."""
    assert ld.resolve_component_llm("CREW", builtin="google:gemini-4-argon") == ld.ComponentLLM(
        provider="google", model="gemini-4-argon", source="builtin"
    )


def test_component_var_wins_over_global(env: dict[str, str], monkeypatch: pytest.MonkeyPatch) -> None:
    """A component-specific LLM overrides the global default."""
    env["CREW_LLM"] = "openai:gpt-4.1"
    monkeypatch.setattr(ld.conf, "DEFAULT_LLM", "google:gemini-4-argon")

    resolved = ld.resolve_component_llm("CREW", builtin="google:gemini-2.0-flash")

    assert resolved == ld.ComponentLLM(provider="openai", model="gpt-4.1", source="component")


def test_global_used_when_component_unset(env: dict[str, str], monkeypatch: pytest.MonkeyPatch) -> None:
    """The global default applies when no component-specific value is set."""
    monkeypatch.setattr(ld.conf, "DEFAULT_LLM", "openai:gpt-4.1")

    resolved = ld.resolve_component_llm("CREW", builtin="google:gemini-2.0-flash")

    assert resolved == ld.ComponentLLM(provider="openai", model="gpt-4.1", source="global")


def test_bare_model_inherits_builtin_provider(env: dict[str, str]) -> None:
    """Bare component models retain the provider from the builtin default."""
    env["CREW_LLM"] = "gemini-4-argon"

    resolved = ld.resolve_component_llm("CREW", builtin="google:gemini-2.0-flash")

    assert resolved == ld.ComponentLLM(provider="google", model="gemini-4-argon", source="component")


def test_explicit_override_preserves_retired_id(env: dict[str, str]) -> None:
    """FEAT-798 (codex S9): an operator-set retired id is preserved, never remapped by the resolver."""
    env["CREW_LLM"] = "google:gemini-2.5-pro"

    resolved = ld.resolve_component_llm("CREW", builtin="google:gemini-4-argon")

    assert resolved == ld.ComponentLLM(provider="google", model="gemini-2.5-pro", source="component")


@pytest.mark.parametrize("value", ["nope:x", "google:", ":model", "  "])
def test_malformed_raises_named_var(env: dict[str, str], value: str) -> None:
    """Malformed component settings identify the offending environment variable."""
    env["CREW_LLM"] = value

    with pytest.raises(ValueError, match="CREW_LLM"):
        ld.resolve_component_llm("CREW", builtin="google:gemini-2.0-flash")


@pytest.mark.parametrize("provider", ["google", "gemini-live", "google-compat"])
def test_provider_token_google_family(provider: str) -> None:
    """Google provider aliases resolve to the shared GOOGLE key token."""
    assert ld.provider_key_token(provider) == "GOOGLE"


def test_api_key_cascade_order(env: dict[str, str]) -> None:
    """Component keys take precedence in order, followed by legacy keys."""
    env.update(
        {
            "CREW_GOOGLE_API_KEY": "crew-key",
            "AGENT_GOOGLE_API_KEY": "agent-key",
            "CREW_AI_KEY": "legacy-key",
        }
    )
    assert ld.resolve_component_api_key(("CREW", "AGENT"), "google", legacy=("CREW_AI_KEY",)) == "crew-key"

    del env["CREW_GOOGLE_API_KEY"]
    assert ld.resolve_component_api_key(("CREW", "AGENT"), "google", legacy=("CREW_AI_KEY",)) == "agent-key"

    del env["AGENT_GOOGLE_API_KEY"]
    assert ld.resolve_component_api_key(("CREW", "AGENT"), "google", legacy=("CREW_AI_KEY",)) == "legacy-key"

    del env["CREW_AI_KEY"]
    assert ld.resolve_component_api_key(("CREW", "AGENT"), "google", legacy=("CREW_AI_KEY",)) is None
