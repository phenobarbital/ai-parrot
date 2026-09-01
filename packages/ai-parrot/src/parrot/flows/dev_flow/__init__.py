"""Dev-flow — SDD-oriented AgentsFlow for feature development (FEAT-412).

A sibling of the operations-oriented :mod:`parrot.flows.dev_loop`, modelling
the *actual* SDD development cycle end-to-end::

    NL request (enhancement | new_feature) ──► ideation (+ HITL Open Questions)
            or an existing SDD document ─────► planner ──► development pool
            ──► synthesis ──► qa ──► draft PR

Only the intake nodes (``dev_flow.dev_intake``, ``dev_flow.ideation``) and
the topology are new: node types, models, session state, streaming,
dispatchers and the runner machinery are all imported from ``dev_loop``
(spec §2 Overview). The flow terminates at a **draft PR against ``dev``** —
never a merge.

See ``sdd/specs/sdd-dev-flow.spec.md`` for the full specification.

Import hygiene mirrors ``dev_loop.__init__``: the light Pydantic contracts
are re-exported eagerly, while the heavier topology/runner symbols are
resolved lazily through :func:`__getattr__` so importing the models never
drags in aiohttp/redis/dispatcher machinery.
"""

from __future__ import annotations

from typing import Any

from parrot.flows.dev_flow.models import (
    DevFlowBrief,
    DevFlowModelPlan,
    DevRequestBrief,
    DevRequestKind,
    IdeationOutput,
    ResearchPartnerPlan,
    ReviewPairPlan,
    parse_dev_brief,
    resolve_model_plan,
)

__all__ = [
    "DevFlowBrief",
    "DevFlowModelPlan",
    "DevRequestBrief",
    "DevRequestKind",
    "IdeationOutput",
    "ResearchPartnerPlan",
    "ReviewPairPlan",
    "parse_dev_brief",
    "resolve_model_plan",
]

# Lazily-resolved exports: attribute name -> submodule it lives in. Keeping
# the mapping here means ``from parrot.flows.dev_flow import X`` works
# without the package init importing the heavy modules (topology, runner,
# nodes) eagerly.
_LAZY_EXPORTS: dict[str, str] = {
    "build_dev_flow_definition": "parrot.flows.dev_flow.definition",
    "build_dev_flow_node_factories": "parrot.flows.dev_flow.factories",
    "build_dev_flow": "parrot.flows.dev_flow.flow",
    "DevFlowRunner": "parrot.flows.dev_flow.runner",
    "DevIntakeNode": "parrot.flows.dev_flow.nodes",
    "IdeationNode": "parrot.flows.dev_flow.nodes",
}


def __getattr__(name: str) -> Any:
    """Resolve a lazily-exported dev-flow symbol on first access.

    Args:
        name: Attribute name requested on the ``parrot.flows.dev_flow``
            package.

    Returns:
        The resolved attribute.

    Raises:
        AttributeError: If ``name`` is not a known lazy export.
    """
    module_name = _LAZY_EXPORTS.get(name)
    if module_name is None:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    from importlib import import_module

    value = getattr(import_module(module_name), name)
    globals()[name] = value
    return value


def __dir__() -> list[str]:
    """Expose eager and lazy exports to ``dir()`` / autocompletion."""
    return sorted(set(__all__) | set(_LAZY_EXPORTS))
