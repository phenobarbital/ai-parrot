"""Build a tenant's LLM agents from that tenant's own API keys (BYOK).

Each tenant brings its own credentials — Google GenAI for triage, Anthropic for
reply drafting — so the agents cannot be shared: an ``AnthropicClient`` holds
its key inside its transport backend, and two tenants must never end up behind
the same one.

Three parts of the framework shape how this is done, and each rules out an
approach that looks obvious:

* **``model_config={"api_key": …}`` does not work.** ``AbstractBot.__init__``
  stores the dict but mines only five keys from it, and ``configure()`` calls
  ``_resolve_llm_config(llm=…, model=…, preset=…, **self._llm_kwargs)`` with no
  ``model_config=`` argument at all — so the branch that would have forwarded
  the key is unreachable from a bot. The key is dropped in silence.
* **``llm_kwargs={"api_key": …}`` works for Anthropic but not Google**, and
  ``AbstractBot.__init__`` mutates the dict you hand it (it adds temperature /
  top_k / top_p / max_tokens), so it cannot be shared between agents.
* **Passing a pre-built client as ``llm=`` is a clean passthrough.**
  ``_resolve_llm_config`` returns it immediately and ``_create_llm_client``
  short-circuits on ``config.client_instance`` — which also means the sampling
  parameters it would otherwise inject are never applied. That matters: recent
  Claude models 400 on ``temperature`` / ``top_p`` / ``top_k``.

The last point is why this module constructs the clients itself. The secondary
benefit is containment: the plaintext key lives inside the client (its
transport backend and its auth header) instead of sitting in the bot's
``_model_config`` dict for the lifetime of the agent, reachable by any repr,
log line or serialization of the bot.

Agents are :class:`~parrot.bots.chatbot.Chatbot`, not ``Agent``: these two
nodes call the model and nothing else, and ``BasicAgent.__init__``
unconditionally builds an environment-keyed ``GoogleGenAIClient`` for its TTS
and multi-modal helpers — a platform credential inside a per-tenant object.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, Mapping, Optional, Sequence

from navconfig.logging import logging

from .. import conf
from ..tenancy.context import TenantContext
from .credentials import (
    ANTHROPIC_API_KEY_SECRET,
    GOOGLE_API_KEY_SECRET,
    TenantCredentialMissing,
    require_secret,
)

logger = logging.getLogger("parrot_saas.llm.builder")

#: Roles the Community Manager flow resolves out of ``TenantRuntime.agents``.
ROLE_TRIAGE = "triage"
ROLE_REPLY = "reply_draft"

#: Minimal working prompts. Brand voice, locale shaping and the revise-round
#: wording are the LLM nodes' own concern (they own the output contract), so
#: these stay deliberately plain rather than pretending to be final.
_TRIAGE_PROMPT = (
    "You triage guest reviews for a hospitality business. Read the review and "
    "decide whether it warrants a public reply, classifying its sentiment and "
    "severity. Answer only with the requested structured fields."
)
_REPLY_PROMPT = (
    "You draft short, sincere public replies to guest reviews for a "
    "hospitality business. Never invent facts about the visit, never promise "
    "compensation, and never mention discounts or coupons. Answer only with "
    "the reply text."
)


@dataclass(frozen=True, slots=True)
class AgentSpec:
    """One agent a tenant runtime needs.

    Attributes:
        role: Key under which the agent is published in
            ``TenantRuntime.agents`` and read by the flow's node factories.
        provider: ``"google"`` or ``"anthropic"``.
        secret_key: Name of the stored secret holding this provider's key.
        model: Model identifier passed to the client.
        system_prompt: System prompt for the bot.
    """

    role: str
    provider: str
    secret_key: str
    model: str
    system_prompt: str


def default_cm_agent_specs(tenant: TenantContext) -> tuple[AgentSpec, ...]:
    """Build the Community Manager agent specs for one tenant.

    Model choice is a tenant setting first and a deployment default second, so
    a tenant that wants a stronger reply model can say so without a redeploy.

    Args:
        tenant: The tenant to serve.

    Returns:
        The triage and reply specs, in that order.
    """
    settings: Mapping[str, Any] = tenant.settings or {}
    return (
        AgentSpec(
            role=ROLE_TRIAGE,
            provider="google",
            secret_key=GOOGLE_API_KEY_SECRET,
            model=settings.get("triage_model") or conf.SAAS_CM_TRIAGE_MODEL,
            system_prompt=_TRIAGE_PROMPT,
        ),
        AgentSpec(
            role=ROLE_REPLY,
            provider="anthropic",
            secret_key=ANTHROPIC_API_KEY_SECRET,
            model=settings.get("reply_model") or conf.SAAS_CM_REPLY_MODEL,
            system_prompt=_REPLY_PROMPT,
        ),
    )


def _build_client(provider: str, model: str, api_key: str) -> Any:
    """Instantiate a provider client bound to one tenant's key.

    Args:
        provider: ``"google"`` or ``"anthropic"``.
        model: Model identifier.
        api_key: The tenant's key.

    Returns:
        A configured ``AbstractClient``.

    Raises:
        ValueError: For a provider this builder does not support. Deliberately
            narrow — a typo in a tenant's settings must not silently resolve to
            some other vendor's client.
    """
    if provider == "google":
        from parrot.clients.google.client import GoogleGenAIClient

        return GoogleGenAIClient(model=model, api_key=api_key)
    if provider in ("anthropic", "claude"):
        from parrot.clients.claude import AnthropicClient

        return AnthropicClient(model=model, api_key=api_key)
    raise ValueError(f"unsupported BYOK provider: {provider!r}")


async def build_agent(
    spec: AgentSpec,
    *,
    tenant: TenantContext,
    secret_store: Any,
    tool_manager: Optional[Any] = None,
) -> Any:
    """Build and configure one agent for a tenant.

    Args:
        spec: What to build.
        tenant: The tenant this agent serves.
        secret_store: Store holding the tenant's credentials.
        tool_manager: The tenant's cloned tool manager, if any. These agents
            run without tools, but the manager is still the object the bot
            reports through.

    Returns:
        A configured ``Chatbot``.

    Raises:
        TenantCredentialMissing: If the provider key is absent or blank.
    """
    from parrot.bots.chatbot import Chatbot

    api_key = await require_secret(secret_store, tenant.tenant_id, spec.secret_key)
    client = _build_client(spec.provider, spec.model, api_key)

    kwargs: Dict[str, Any] = {}
    if tool_manager is not None:
        kwargs["tool_manager"] = tool_manager

    agent = Chatbot(
        name=f"saas.{tenant.tenant_id}.{spec.role}",
        llm=client,
        system_prompt=spec.system_prompt,
        # A database lookup here would find some unrelated bot that happens to
        # share this name and overwrite the tenant's model configuration with
        # that row's — so never look.
        from_database=False,
        use_tools=False,
        **kwargs,
    )
    # configure() is not idempotent: it resets ``_configured`` and re-runs the
    # whole body, re-registering toolkits. Exactly once, here.
    await agent.configure()
    return agent


async def build_tenant_agents(
    *,
    tenant: TenantContext,
    secret_store: Any,
    specs: Optional[Sequence[AgentSpec]] = None,
    tool_manager: Optional[Any] = None,
    strict: bool = False,
) -> Dict[str, Any]:
    """Build every agent a tenant's runtime needs.

    Args:
        tenant: The tenant to serve.
        secret_store: Store holding the tenant's credentials.
        specs: Agents to build. Defaults to the Community Manager pair.
        tool_manager: The tenant's cloned tool manager, if any.
        strict: Whether a missing credential is fatal.

            ``False`` (the default, used when a runtime is built to serve an
            HTTP request) skips the role and carries on. That is not
            leniency — the runtime is built by the tenant middleware, so a
            newly onboarded tenant that has not uploaded any key yet must
            still be able to reach ``PUT /api/v1/saas/secrets/{key}`` to
            upload one. Failing here would trap it behind a 500 with no way
            out. The flow's LLM nodes fall back to their deterministic paths
            when a role is absent.

            ``True`` is for the ingest path, which is about to run the flow
            for real and should refuse rather than quietly degrade.

    Returns:
        Configured agents by role. Possibly empty when ``strict`` is False.

    Raises:
        TenantCredentialMissing: If ``strict`` and a credential is missing.
    """
    agents: Dict[str, Any] = {}
    for spec in specs if specs is not None else default_cm_agent_specs(tenant):
        try:
            agents[spec.role] = await build_agent(
                spec,
                tenant=tenant,
                secret_store=secret_store,
                tool_manager=tool_manager,
            )
        except TenantCredentialMissing:
            if strict:
                raise
            logger.info(
                "tenant %s has no %r credential; the %r agent is unavailable "
                "and its node will use the deterministic fallback",
                tenant.tenant_id,
                spec.secret_key,
                spec.role,
            )
        except Exception as exc:  # noqa: BLE001 - one bad role must not sink the rest
            if strict:
                raise
            logger.error(
                "building the %r agent for tenant %s failed: %s",
                spec.role,
                tenant.tenant_id,
                exc,
            )
    return agents


__all__ = (
    "ROLE_REPLY",
    "ROLE_TRIAGE",
    "AgentSpec",
    "build_agent",
    "build_tenant_agents",
    "default_cm_agent_specs",
)
