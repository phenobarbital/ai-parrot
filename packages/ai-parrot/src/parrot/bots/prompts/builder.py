"""Composable system prompt builder.

PromptBuilder manages a collection of PromptLayer instances and orchestrates
two-phase rendering: CONFIGURE (static vars resolved once) and REQUEST
(dynamic vars resolved per call).

Replaces the monolithic system_prompt_template + create_system_prompt()
string concatenation approach.

See spec: sdd/specs/composable-prompt-layer.spec.md (Section 3.3)
"""
from __future__ import annotations

from copy import deepcopy
from typing import Optional, Dict, Any, List

from .layers import PromptLayer, LayerPriority, RenderPhase


class PromptBuilder:
    """Composable system prompt builder.

    Usage:
        builder = PromptBuilder.default()
        builder.remove("tools")           # no tools for this agent
        builder.add(my_custom_layer)      # add domain-specific layer

        # Phase 1: resolve static vars once
        builder.configure({"name": "Bot", "role": "helper", ...})

        # Phase 2: resolve dynamic vars per request
        prompt = builder.build({"knowledge_content": "...", ...})
    """

    def __init__(self, layers: Optional[List[PromptLayer]] = None):
        self._layers: Dict[str, PromptLayer] = {}
        self._configured: bool = False
        if layers:
            for layer in layers:
                self._layers[layer.name] = layer

    # ── Factory methods ────────────────────────────────────────

    @classmethod
    def default(cls) -> PromptBuilder:
        """Standard layer stack for most bots."""
        from .layers import (
            IDENTITY_LAYER, PRE_INSTRUCTIONS_LAYER, SECURITY_LAYER,
            KNOWLEDGE_LAYER, USER_SESSION_LAYER, TOOLS_LAYER,
            OUTPUT_LAYER, BEHAVIOR_LAYER,
        )
        return cls([
            IDENTITY_LAYER, PRE_INSTRUCTIONS_LAYER, SECURITY_LAYER,
            KNOWLEDGE_LAYER, USER_SESSION_LAYER, TOOLS_LAYER,
            OUTPUT_LAYER, BEHAVIOR_LAYER,
        ])

    @classmethod
    def minimal(cls) -> PromptBuilder:
        """Lightweight stack: identity + security + user_session only."""
        from .layers import IDENTITY_LAYER, SECURITY_LAYER, USER_SESSION_LAYER
        return cls([IDENTITY_LAYER, SECURITY_LAYER, USER_SESSION_LAYER])

    @classmethod
    def voice(cls) -> PromptBuilder:
        """Voice-optimized stack with voice behavior layer."""
        from .layers import (
            IDENTITY_LAYER, PRE_INSTRUCTIONS_LAYER, SECURITY_LAYER,
            KNOWLEDGE_LAYER, USER_SESSION_LAYER, TOOLS_LAYER,
        )
        voice_behavior = PromptLayer(
            name="behavior",
            priority=LayerPriority.BEHAVIOR,
            phase=RenderPhase.CONFIGURE,
            template="""<response_style>
Keep responses concise and conversational.
Speak naturally, as in a face-to-face conversation.
Avoid long lists or complex formatting.
Use conversational transitions and acknowledgments.
$rationale
</response_style>""",
            condition=lambda ctx: True,
        )
        return cls([
            IDENTITY_LAYER, PRE_INSTRUCTIONS_LAYER, SECURITY_LAYER,
            KNOWLEDGE_LAYER, USER_SESSION_LAYER, TOOLS_LAYER,
            voice_behavior,
        ])

    @classmethod
    def agent(cls) -> PromptBuilder:
        """Agent stack with strict grounding behavior."""
        from .domain_layers import STRICT_GROUNDING_LAYER
        builder = cls.default()
        builder.add(STRICT_GROUNDING_LAYER)
        return builder

    # ── Mutation API ────────────────────────────────────────────

    def add(self, layer: PromptLayer) -> PromptBuilder:
        """Add or replace a layer by name.

        Args:
            layer: The PromptLayer to add.

        Returns:
            Self for method chaining.
        """
        self._layers[layer.name] = layer
        return self

    def remove(self, name: str) -> PromptBuilder:
        """Remove a layer by name. No-op if not present.

        Args:
            name: The layer name to remove.

        Returns:
            Self for method chaining.
        """
        self._layers.pop(name, None)
        return self

    def replace(self, name: str, layer: PromptLayer) -> PromptBuilder:
        """Replace an existing layer. Raises KeyError if not found.

        Args:
            name: The layer name to replace.
            layer: The new PromptLayer.

        Returns:
            Self for method chaining.

        Raises:
            KeyError: If the named layer is not in the builder.
        """
        if name not in self._layers:
            raise KeyError(
                f"Layer '{name}' not found. Use add() instead. "
                f"Available: {list(self._layers.keys())}"
            )
        self._layers[name] = layer
        return self

    def get(self, name: str) -> Optional[PromptLayer]:
        """Get a layer by name.

        Args:
            name: The layer name to retrieve.

        Returns:
            The PromptLayer, or None if not found.
        """
        return self._layers.get(name)

    def clone(self) -> PromptBuilder:
        """Deep copy for per-agent customization.

        Returns:
            A new independent PromptBuilder with the same layers.
        """
        new_builder = PromptBuilder(list(deepcopy(self._layers).values()))
        new_builder._configured = self._configured
        return new_builder

    # ── Build ───────────────────────────────────────────────────

    def configure(self, context: Dict[str, Any]) -> None:
        """Phase 1: Resolve CONFIGURE-phase variables once.

        Called during bot.configure(). Resolves static variables
        (name, role, goal, backstory, rationale, dynamic_values, etc.)
        via partial_render(), caching the partially-resolved layers.
        REQUEST-phase $placeholders survive intact for build().

        Args:
            context: Dictionary of static variable values.
        """
        configured_layers: Dict[str, PromptLayer] = {}
        for name, layer in self._layers.items():
            if layer.phase == RenderPhase.CONFIGURE:
                configured_layers[name] = layer.partial_render(context)
            else:
                configured_layers[name] = layer
        self._layers = configured_layers
        self._configured = True

    def build(self, context: Dict[str, Any]) -> str:
        """Phase 2: Resolve REQUEST-phase variables and assemble final prompt.

        Called on every ask()/ask_stream(). Only resolves dynamic
        variables (knowledge_content, user_context, chat_history, etc.)
        because CONFIGURE-phase layers already have their static
        variables baked in from configure().

        If configure() was never called, all layers are rendered
        with the full context (single-phase fallback).

        Args:
            context: Dictionary of dynamic variable values.

        Returns:
            The assembled system prompt string.
        """
        sorted_layers = sorted(self._layers.values(), key=lambda l: l.priority)

        parts: List[str] = []
        for layer in sorted_layers:
            rendered = layer.render(context)
            if rendered is not None:
                stripped = rendered.strip()
                if stripped:
                    parts.append(stripped)

        return "\n\n".join(parts)

    @property
    def is_configured(self) -> bool:
        """Whether configure() has been called."""
        return self._configured

    @property
    def layer_names(self) -> List[str]:
        """List of layer names currently in the builder."""
        return list(self._layers.keys())
