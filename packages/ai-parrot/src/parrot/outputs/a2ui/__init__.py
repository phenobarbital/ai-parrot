"""``parrot.outputs.a2ui`` — A2UI v1.0 rendering core (FEAT-273).

Core-side contract for the A2UI output pipeline: the v1.0 wire message models,
the serialization layer that owns the protocol ``version``, the component catalog
with mandatory lowering, and the capability-declaring renderer registry.

One-way import rule (spec G8): this package MUST NEVER import from
``parrot.bots``, ``parrot.clients``, agents, or DatasetManager. Concrete
renderers live in the ``ai-parrot-visualizations`` satellite.
"""

from parrot.outputs.a2ui.models import (
    Action,
    ActionResponse,
    A2UIMessage,
    A2UIMessageBase,
    CallFunction,
    Component,
    CreateSurface,
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
    "A2UIMessage",
    "A2UIMessageBase",
    "Action",
    "ActionResponse",
    "CallFunction",
    "Component",
    "CreateSurface",
    "UpdateComponents",
    "UpdateDataModel",
    "deserialize",
    "is_binding_expression",
    "is_valid_pointer",
    "iter_jsonl",
    "serialize",
    "to_jsonl",
]
