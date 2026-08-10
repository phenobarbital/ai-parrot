"""BYOK agent construction: the tenant's key reaches the client, and only it.

No network. The clients are constructed for real (that is the point — the
regressions this guards against all live in construction) but never called.
"""
from __future__ import annotations

import inspect
import logging
from typing import Any, Dict, Optional

import pytest

from parrot_saas.llm.builder import (
    AgentSpec,
    build_agent,
    build_tenant_agents,
    default_cm_agent_specs,
)
from parrot_saas.llm.credentials import (
    ANTHROPIC_API_KEY_SECRET,
    GOOGLE_API_KEY_SECRET,
    TenantCredentialMissing,
)
from parrot_saas.tenancy.context import TenantContext, TenantMode

TENANT_GOOGLE_KEY = "AIza-tenant-one-google"
TENANT_ANTHROPIC_KEY = "sk-ant-tenant-one-anthropic"


class _Store:
    """In-memory secret store with the two methods the builder uses."""

    def __init__(self, secrets: Optional[Dict[tuple, str]] = None) -> None:
        self._secrets = dict(secrets or {})

    async def get(self, tenant_id: str, key: str) -> Optional[str]:
        return self._secrets.get((tenant_id, key))


def _tenant(tenant_id: str = "bar-pepe", **settings: Any) -> TenantContext:
    return TenantContext(
        tenant_id=tenant_id,
        name=tenant_id.title(),
        mode=TenantMode.SHARED,
        settings=settings,
    )


@pytest.fixture
def store() -> _Store:
    """A tenant with both keys stored."""
    return _Store(
        {
            ("bar-pepe", GOOGLE_API_KEY_SECRET): TENANT_GOOGLE_KEY,
            ("bar-pepe", ANTHROPIC_API_KEY_SECRET): TENANT_ANTHROPIC_KEY,
        }
    )


@pytest.fixture(autouse=True)
def platform_keys_in_the_environment(monkeypatch):
    """Put platform keys in the environment for every test in this module.

    This is the whole point of the suite. Both SDKs fall back to these when no
    key reaches them, so a builder that loses the tenant's key would still
    produce a working client — billed to the platform, shared across tenants,
    and completely silent. Every assertion below is only meaningful with these
    set.
    """
    monkeypatch.setenv("GOOGLE_API_KEY", "AIza-PLATFORM-DO-NOT-USE")
    monkeypatch.setenv("GEMINI_API_KEY", "AIza-PLATFORM-DO-NOT-USE")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-PLATFORM-DO-NOT-USE")


# ---------------------------------------------------------------------------
# The tenant's key reaches the client
# ---------------------------------------------------------------------------


async def test_google_client_carries_the_tenant_key(store: _Store) -> None:
    """The Google client must not fall back to the platform key.

    ``GoogleGenAIClient`` pops ``api_key`` out of its kwargs, so the base
    class used to blank it and ``genai.Client(api_key=None)`` silently used
    ``GOOGLE_API_KEY`` from the environment instead.
    """
    agents = await build_tenant_agents(tenant=_tenant(), secret_store=store)

    client = agents["triage"]._llm
    assert client.api_key == TENANT_GOOGLE_KEY


async def test_anthropic_client_carries_the_tenant_key(store: _Store) -> None:
    """The Anthropic key must reach the transport and the auth header.

    ``client.api_key`` is not the thing to assert on — the value that is
    actually sent lives on the backend and in ``x-api-key``.
    """
    agents = await build_tenant_agents(tenant=_tenant(), secret_store=store)

    client = agents["reply_draft"]._llm
    assert client._backend.api_key == TENANT_ANTHROPIC_KEY
    assert client.base_headers["x-api-key"] == TENANT_ANTHROPIC_KEY


async def test_two_tenants_get_separate_clients() -> None:
    """One tenant's key must never appear in another tenant's client."""
    store = _Store(
        {
            ("bar-pepe", ANTHROPIC_API_KEY_SECRET): "sk-ant-AAA",
            ("hotel-x", ANTHROPIC_API_KEY_SECRET): "sk-ant-BBB",
        }
    )
    spec = default_cm_agent_specs(_tenant())[1]

    first = await build_agent(spec, tenant=_tenant("bar-pepe"), secret_store=store)
    second = await build_agent(spec, tenant=_tenant("hotel-x"), secret_store=store)

    assert first._llm is not second._llm
    assert first._llm._backend.api_key == "sk-ant-AAA"
    assert second._llm._backend.api_key == "sk-ant-BBB"


async def test_no_sampling_params_are_injected(store: _Store) -> None:
    """Passing a built client keeps ``_create_llm_client`` from adding params.

    Recent Claude models 400 on ``temperature`` / ``top_p`` / ``top_k``, and
    the bot layer passes all three whenever it builds the client itself.
    """
    agents = await build_tenant_agents(tenant=_tenant(), secret_store=store)

    assert agents["reply_draft"]._llm_config.client_instance is not None


# ---------------------------------------------------------------------------
# Model selection
# ---------------------------------------------------------------------------


def test_tenant_settings_override_the_default_models() -> None:
    """A tenant can pick its own models without a redeploy."""
    specs = default_cm_agent_specs(
        _tenant(triage_model="gemini-2.5-pro", reply_model="claude-opus-5")
    )

    assert specs[0].model == "gemini-2.5-pro"
    assert specs[1].model == "claude-opus-5"


def test_default_reply_model_is_not_a_legacy_dated_id() -> None:
    """The shipped default must be a current model identifier."""
    from parrot_saas import conf

    assert conf.SAAS_CM_REPLY_MODEL == "claude-sonnet-5"


# ---------------------------------------------------------------------------
# Missing credentials
# ---------------------------------------------------------------------------


async def test_strict_raises_on_a_missing_credential() -> None:
    """The ingest path must refuse rather than quietly degrade."""
    with pytest.raises(TenantCredentialMissing) as excinfo:
        await build_tenant_agents(
            tenant=_tenant(), secret_store=_Store(), strict=True
        )

    assert excinfo.value.key == GOOGLE_API_KEY_SECRET
    assert excinfo.value.tenant_id == "bar-pepe"


async def test_a_blank_credential_counts_as_missing() -> None:
    """An empty string must not reach the SDK, which would use the env key."""
    store = _Store({("bar-pepe", GOOGLE_API_KEY_SECRET): "   "})

    with pytest.raises(TenantCredentialMissing):
        await build_tenant_agents(
            tenant=_tenant(),
            secret_store=store,
            specs=default_cm_agent_specs(_tenant())[:1],
            strict=True,
        )


async def test_tolerant_mode_omits_the_role(caplog) -> None:
    """A tenant with no keys yet must still get a usable runtime.

    The runtime is built by the tenant middleware, so failing here would trap
    a newly onboarded tenant behind a 500 — including on the very request that
    would have uploaded its first key.
    """
    caplog.set_level(logging.INFO)

    agents = await build_tenant_agents(tenant=_tenant(), secret_store=_Store())

    assert agents == {}


async def test_tolerant_mode_keeps_the_roles_it_can_build() -> None:
    """One missing credential must not cost the other agent."""
    store = _Store({("bar-pepe", ANTHROPIC_API_KEY_SECRET): TENANT_ANTHROPIC_KEY})

    agents = await build_tenant_agents(tenant=_tenant(), secret_store=store)

    assert set(agents) == {"reply_draft"}


def test_an_unknown_provider_is_refused() -> None:
    """A typo must not silently resolve to some other vendor's client."""
    from parrot_saas.llm.builder import _build_client

    with pytest.raises(ValueError, match="unsupported BYOK provider"):
        _build_client("gooogle", "some-model", "key")


# ---------------------------------------------------------------------------
# No leakage
# ---------------------------------------------------------------------------


async def test_the_key_never_reaches_the_logs(store: _Store, caplog) -> None:
    """Nothing in the build path may write a plaintext key to a log."""
    caplog.set_level(logging.DEBUG)

    await build_tenant_agents(tenant=_tenant(), secret_store=store)

    combined = "\n".join(record.getMessage() for record in caplog.records)
    assert TENANT_GOOGLE_KEY not in combined
    assert TENANT_ANTHROPIC_KEY not in combined


async def test_the_key_is_not_parked_on_the_bot(store: _Store) -> None:
    """The key must live in the client, not in the bot's config dict.

    ``_model_config`` is carried for the lifetime of the agent and is reachable
    from any repr or serialization of it — which is why the builder passes a
    constructed client instead of a ``model_config`` dict.
    """
    agents = await build_tenant_agents(tenant=_tenant(), secret_store=store)

    for agent in agents.values():
        assert TENANT_GOOGLE_KEY not in repr(agent._model_config)
        assert TENANT_ANTHROPIC_KEY not in repr(agent._model_config)
        assert TENANT_ANTHROPIC_KEY not in repr(agent)


async def test_the_missing_credential_error_never_carries_a_value() -> None:
    """The exception names the key, never what it failed to find."""
    error = TenantCredentialMissing("bar-pepe", ANTHROPIC_API_KEY_SECRET)

    assert ANTHROPIC_API_KEY_SECRET in str(error)
    assert "sk-" not in str(error)


# ---------------------------------------------------------------------------
# Construction discipline
# ---------------------------------------------------------------------------


async def test_bots_never_load_themselves_from_the_database(store: _Store) -> None:
    """A name collision in ``navigator.bots`` must not hijack a tenant's agent.

    ``Chatbot.configure`` looks the bot up by name and overwrites its model
    configuration from the row it finds, so ``from_database`` has to be off.
    """
    source = inspect.getsource(build_agent)

    assert "from_database=False" in source
    agents = await build_tenant_agents(tenant=_tenant(), secret_store=store)
    for agent in agents.values():
        assert agent._from_database is False


async def test_configure_runs_exactly_once_per_agent(store: _Store, mocker) -> None:
    """``configure()`` is not idempotent — re-entering re-registers toolkits."""
    from parrot.bots.chatbot import Chatbot

    spy = mocker.spy(Chatbot, "configure")

    await build_tenant_agents(tenant=_tenant(), secret_store=store)

    assert spy.call_count == 2  # one per role, never twice for the same agent


async def test_runtime_close_cleans_up_every_agent() -> None:
    """Eviction must actually close the tenant's LLM connections.

    Bots have no ``aclose`` or ``close``, and ``shutdown`` is an empty stub —
    so a teardown loop that stopped at ``shutdown`` would leak the pool.
    """
    from parrot_saas.tenancy.runtime import TenantRuntime

    calls: list = []

    class _Agent:
        def __init__(self, name: str) -> None:
            self._name = name

        async def cleanup(self) -> None:
            calls.append(self._name)

        async def shutdown(self) -> None:  # the stub that must not win
            calls.append(f"{self._name}:shutdown")

    runtime = TenantRuntime(
        tenant=_tenant(),
        agents={"triage": _Agent("triage"), "reply_draft": _Agent("reply")},
    )

    await runtime.aclose()
    await runtime.aclose()  # idempotent

    assert sorted(calls) == ["reply", "triage"]


def test_the_builder_spec_is_a_frozen_record() -> None:
    """Specs are shared between tenants; they must not be mutable."""
    spec = AgentSpec(
        role="triage",
        provider="google",
        secret_key=GOOGLE_API_KEY_SECRET,
        model="gemini-2.5-flash",
        system_prompt="x",
    )

    with pytest.raises(Exception):
        spec.model = "something-else"  # type: ignore[misc]
