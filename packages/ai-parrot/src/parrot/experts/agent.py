"""The runtime agent an expert bundle produces (FEAT-778 M3)."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Sequence

from parrot.bots.agent import Agent
from parrot.bots.mixins.identity import IdentityMixin
from parrot.experts.knowledge.render import install_layers
from parrot.experts.knowledge.resolver import KnowledgeResolver
from parrot.experts.models import ExpertBundle, KnowledgeContext
from parrot.models.basic import ModelConfig
from parrot.tools.toolkit import AbstractToolkit


class ExpertAgent(IdentityMixin, Agent):
    """Agent configured from an ExpertBundle: bundle identity, literal knowledge layers, tool allowlist."""

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

    async def configure(self, app: Any = None) -> None:
        """Base configure, identity layers, then the resolved knowledge as literal layers."""
        await super().configure(app)
        await self._configure_identity()
        self.knowledge_context = await self.knowledge_resolver.resolve(
            self.bundle, None, self.workspace, model=self.model_config.model
        )
        if self._prompt_builder is not None:
            self._prompt_builder = install_layers(self._prompt_builder, self.knowledge_context)
