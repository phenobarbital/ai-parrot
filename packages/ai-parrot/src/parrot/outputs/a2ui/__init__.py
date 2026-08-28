"""``parrot.outputs.a2ui`` — A2UI v1.0 rendering core (FEAT-470 / FEAT-273).

Core-side contract for the A2UI output pipeline: the v1.0 wire message models
(envelope-by-key, top-level component props), the serialization layer that
owns the protocol ``version``, the read-only legacy-dialect compatibility
layer, the component catalog with mandatory lowering, and the
capability-declaring renderer registry.

One-way import rule (spec G8): this package MUST NEVER import from
``parrot.bots``, ``parrot.clients``, agents, or DatasetManager. Concrete
renderers live in the ``ai-parrot-visualizations`` satellite.
"""

from parrot.outputs.a2ui.compat import (
    is_legacy_envelope,
    normalize_legacy,
    normalize_legacy_component,
)
from parrot.outputs.a2ui.models import (
    A2UIAgentMessage,
    A2UIMessageBase,
    A2UIRendererMessage,
    Action,
    ActionMessage,
    AgentFunctionResponse,
    CallAgentFunction,
    CallRendererFunction,
    Component,
    CreateSurface,
    DeleteSurface,
    ErrorMessage,
    RendererFunctionResponse,
    UpdateComponents,
    UpdateDataModel,
    is_binding_expression,
    is_valid_pointer,
)
from parrot.outputs.a2ui.serialization import (
    A2UI_VERSION,
    deserialize,
    iter_jsonl,
    serialize,
    to_jsonl,
)

__all__ = [
    "A2UI_VERSION",
    "A2UIAgentMessage",
    "A2UIMessageBase",
    "A2UIRendererMessage",
    "Action",
    "ActionMessage",
    "AgentFunctionResponse",
    "CallAgentFunction",
    "CallRendererFunction",
    "Component",
    "CreateSurface",
    "DeleteSurface",
    "ErrorMessage",
    "RendererFunctionResponse",
    "UpdateComponents",
    "UpdateDataModel",
    "deserialize",
    "is_binding_expression",
    "is_legacy_envelope",
    "is_valid_pointer",
    "iter_jsonl",
    "normalize_legacy",
    "normalize_legacy_component",
    "serialize",
    "to_jsonl",
]
