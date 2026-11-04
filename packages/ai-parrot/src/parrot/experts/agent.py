"""The runtime agent an expert bundle produces (FEAT-778 M3)."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Sequence

from parrot.bots.agent import Agent
from parrot.bots.mixins.identity import IdentityMixin
from parrot.experts.knowledge.render import install_layers
from parrot.experts.knowledge.resolver import KnowledgeResolver
from parrot.experts.models import SPAWN_TOOL_NAME, ExpertBundle, KnowledgeContext
from parrot.llm_defaults import resolve_component_api_key
from parrot.models.basic import ModelConfig
from parrot.observability.context import usage_component
from parrot.tools.toolkit import AbstractToolkit


class ExpertAgent(IdentityMixin, Agent):
    """Agent configured from an ExpertBundle: identity, knowledge layers, and tool allowlist.

    ``ask`` and ``invoke`` tag usage with the expert tier. ``ask_stream`` intentionally retains
    the base async-generator behavior and is not tagged by this class.
    """

    enable_identity: bool = True

    def __init__(
        self,
        bundle: ExpertBundle,
        *,
        resolver: KnowledgeResolver,
        model_config: ModelConfig,
        toolkits: Sequence[AbstractToolkit],
        allowed_tools: Sequence[str],
        workspace: Path | None = None,
        **kwargs: Any,
    ) -> None:
        """Build the expert agent.

        Args:
            bundle: The validated expert bundle.
            resolver: Knowledge resolver used at configure time.
            model_config: Resolved model configuration.
            toolkits: Toolkits whose tools are filtered by ``allowed_tools``.
            allowed_tools: Tool names permitted for this expert.
            workspace: Optional workspace root for knowledge resolution.
            **kwargs: Forwarded to ``Agent.__init__``.
        """
        self.bundle = bundle
        self.knowledge_resolver = resolver
        self.knowledge_context: KnowledgeContext | None = None
        self.workspace = workspace
        self.identity_dir = bundle.identity_dir  # read by IdentityMixin._resolve_identity_dir
        allowed = set(allowed_tools)
        tools = [tool for toolkit in toolkits for tool in toolkit.get_tools() if tool.name in allowed]
        tier_component = f"EXPERT_{bundle.manifest.tier.name}"
        api_key = kwargs.get("api_key") or resolve_component_api_key((tier_component,), model_config.provider)
        if api_key:
            # AbstractBot ignores a bare ``api_key`` kwarg; ``llm_kwargs`` reach the client.
            llm_kwargs = dict(kwargs.get("llm_kwargs", {}))
            llm_kwargs.setdefault("api_key", api_key)
            kwargs["llm_kwargs"] = llm_kwargs
        super().__init__(
            name=bundle.manifest.name,
            agent_id=bundle.manifest.name,
            llm=f"{model_config.provider}:{model_config.model}",
            temperature=model_config.temperature,
            max_tokens=model_config.max_tokens,
            tools=tools,
            **kwargs,
        )
        self.model_config = model_config
        self._usage_component = tier_component

    async def ask(self, *args: Any, **kwargs: Any) -> Any:
        """Run ``Agent.ask`` with usage tagged as this expert's tier (FEAT-796)."""
        with usage_component(self._usage_component):
            return await super().ask(*args, **kwargs)

    async def invoke(self, *args: Any, **kwargs: Any) -> Any:
        """Run ``Agent.invoke`` with usage tagged as this expert's tier (FEAT-796)."""
        with usage_component(self._usage_component):
            return await super().invoke(*args, **kwargs)

    async def configure(self, app: Any = None) -> None:
        """Base configure, identity layers, then the resolved knowledge as literal layers.

        Runs last so it also covers tools registered by the base ``Agent``: the final
        tool list never contains ``spawn_sub_agent``.
        """
        await super().configure(app)
        await self._configure_identity()
        self.knowledge_context = await self.knowledge_resolver.resolve(
            self.bundle, None, self.workspace, model=self.model_config.model
        )
        if self._prompt_builder is not None:
            self._prompt_builder = install_layers(self._prompt_builder, self.knowledge_context)
        if self.tool_manager.get_tool(SPAWN_TOOL_NAME) is not None:
            self.tool_manager.unregister_tool(SPAWN_TOOL_NAME)
            self.logger.warning(
                "Removed %s from expert %s: domain experts never spawn sub-agents", SPAWN_TOOL_NAME, self.name
            )
