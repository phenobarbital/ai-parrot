"""Expert stages (FEAT-890 M4).

Importing this package registers the ``expert_stage`` AgentsFlow node type in
``NODE_REGISTRY`` as a side effect of importing :mod:`parrot.experts.stages.node`.
"""

from __future__ import annotations

from parrot.experts.stages.inline import InlineCompositionError, build_inline_conductor
from parrot.experts.stages.node import ExpertStageError, ExpertStageNode

__all__ = [
    "ExpertStageError",
    "ExpertStageNode",
    "InlineCompositionError",
    "build_inline_conductor",
]
