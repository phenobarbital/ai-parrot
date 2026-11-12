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


class _Agent:
    """Unconfigured AbstractBot stand-in exposing injector attributes."""

    _default_llm = "google"

    def __init__(self, name="feat882-agent", llm=None, llm_kwargs=None, configured=False):
        """Initialize the agent stand-in."""
        self.name = name
        self._llm_raw = llm
        self._llm_kwargs = llm_kwargs if llm_kwargs is not None else {}
        self.is_configured = configured


@pytest.mark.parametrize(
    ("name", "token"),
    [("odoo-helpdesk", "ODOO_HELPDESK"), ("My Agent", "MY_AGENT"), ("a__b", "A_B"), ("--", "")],
)
def test_agent_env_token_normalizes(name: str, token: str) -> None:
    """Agent names normalize to the expected environment-variable token."""
    assert ld.agent_env_token(name) == token


def test_resolve_agent_llm_unset_none(env: dict[str, str]) -> None:
    """An unset agent model does not create an override."""
    assert ld.resolve_agent_llm("feat882-agent", default_provider="google") is None


def test_resolve_agent_llm_provider_model(env: dict[str, str]) -> None:
    """Agent model declarations support both explicit and inherited providers."""
    env["FEAT882_AGENT_MODEL"] = "openai:gpt-4.1"
    assert ld.resolve_agent_llm("feat882-agent", default_provider="google") == ld.ComponentLLM(
        provider="openai", model="gpt-4.1", source="agent"
    )

    env["FEAT882_AGENT_MODEL"] = "gemini-4-argon"
    assert ld.resolve_agent_llm("feat882-agent", default_provider="google") == ld.ComponentLLM(
        provider="google", model="gemini-4-argon", source="agent"
    )


def test_resolve_agent_llm_malformed_names_var(env: dict[str, str]) -> None:
    """Malformed agent model declarations identify their source variable."""
    env["FEAT882_AGENT_MODEL"] = "openai:"

    with pytest.raises(ValueError, match="FEAT882_AGENT_MODEL"):
        ld.resolve_agent_llm("feat882-agent", default_provider="google")


@pytest.mark.parametrize("provider", ["google", "gemini-live", "google-compat"])
def test_resolve_agent_api_key_google_family(env: dict[str, str], provider: str) -> None:
    """Google-family providers use the shared GOOGLE agent key."""
    env["FEAT882_AGENT_GOOGLE_API_KEY"] = "agent-key"
    assert ld.resolve_agent_api_key("feat882-agent", provider) == "agent-key"


def test_is_component_default_key(env: dict[str, str]) -> None:
    """Component defaults and the Google-only legacy key are recognized by value."""
    for component in ld.COMPONENTS:
        value = f"{component.lower()}-key"
        env[f"{component}_GOOGLE_API_KEY"] = value
        assert ld.is_component_default_key(value, "google")

    env["CREW_AI_KEY"] = "legacy-key"
    assert ld.is_component_default_key("legacy-key", "google")
    assert not ld.is_component_default_key("legacy-key", "openai")
    assert not ld.is_component_default_key("unrelated", "google")
    assert not ld.is_component_default_key(None, "google")


def test_apply_component_api_key_flow(env: dict[str, str]) -> None:
    """Component injection copy-on-writes the agent keyword dictionary."""
    env["FLOW_GOOGLE_API_KEY"] = "flow-key"
    shared: dict[str, str] = {}
    agent = _Agent(llm="google", llm_kwargs=shared)

    assert ld.apply_component_api_key(agent, "FLOW")
    assert shared == {}
    assert agent._llm_kwargs == {"api_key": "flow-key"}
    assert agent._llm_kwargs is not shared


@pytest.mark.parametrize(
    "signal",
    [{"api_key": "x"}, {"credentials_file": "f"}, {"credentials": object()}, {"vertexai": True}],
)
def test_apply_component_api_key_noop_explicit(env: dict[str, str], signal: dict[str, object]) -> None:
    """Explicit credentials take precedence over component defaults."""
    env["FLOW_GOOGLE_API_KEY"] = "flow-key"
    agent = _Agent(llm="google", llm_kwargs=signal)

    assert not ld.apply_component_api_key(agent, "FLOW")
    assert agent._llm_kwargs is signal


def test_apply_component_api_key_noop_configured(env: dict[str, str]) -> None:
    """Configured agents are never altered by component injection."""
    env["FLOW_GOOGLE_API_KEY"] = "flow-key"
    agent = _Agent(llm="google", configured=True)

    assert not ld.apply_component_api_key(agent, "FLOW")
    assert agent._llm_kwargs == {}


def test_apply_component_api_key_noop_client_instance(env: dict[str, str]) -> None:
    """A live client-like instance is not altered by component injection."""
    env["FLOW_GOOGLE_API_KEY"] = "flow-key"
    agent = _Agent(llm=object())

    assert not ld.apply_component_api_key(agent, "FLOW")
    assert agent._llm_kwargs == {}


def test_no_key_value_logged(env: dict[str, str], caplog: pytest.LogCaptureFixture) -> None:
    """Credential values do not appear in the injector's logs."""
    secret = "feat882-secret-key"
    env["FLOW_GOOGLE_API_KEY"] = secret
    agent = _Agent(llm="google")

    assert ld.apply_component_api_key(agent, "FLOW")
    assert secret not in caplog.text
