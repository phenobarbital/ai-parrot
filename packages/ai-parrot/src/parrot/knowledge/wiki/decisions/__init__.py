"""ADR extraction and decision retrieval (FEAT-578).

Deterministic ingestion of Architecture Decision Records into the wiki
retrieval plane, symbol-to-decision lookup, cited "why" dossiers, and
explicitly labeled candidate generation.

Re-exports the service, its Pydantic contracts, the ``AbstractTool``
wrappers and :class:`DecisionToolkit`. ``review.py`` is deliberately NOT
re-exported here — keeping it off the package surface makes "review is a
maintainer CLI action, never an autonomous agent tool" (spec §2, AC11)
visible in the API shape itself.

Resolution is LAZY (PEP 562: module ``__getattr__``), not eager imports at
module scope. ``project.py`` imports ``decisions.models`` directly
(``from parrot.knowledge.wiki.decisions.models import DecisionConfig``),
which — like any ``pkg.submodule`` import — runs this ``__init__.py``
first. ``decisions.service`` imports ``structural.service``, which imports
``wiki.cli``, which imports ``wiki.federation``, which imports
``wiki.project`` — the very module already being imported. Eagerly
importing ``service``/``toolkit``/``tools`` here would make that a real
import cycle; resolving them only when an attribute is actually accessed
keeps ``decisions.models`` importable standalone, as it always was.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:  # pragma: no cover — for type checkers only, never executed
    from parrot.knowledge.wiki.decisions.models import (
        CandidateEdit,
        DecisionConfig,
        DecisionDossier,
        DecisionError,
        DecisionHit,
        DecisionRecord,
        EvidenceRef,
        GenerationResult,
        ReviewRequest,
        SyncResult,
    )
    from parrot.knowledge.wiki.decisions.service import DecisionService
    from parrot.knowledge.wiki.decisions.toolkit import DecisionToolkit
    from parrot.knowledge.wiki.decisions.tools import (
        WikiDecisionGenerateTool,
        WikiDecisionsForSymbolTool,
        WikiDecisionWhyTool,
        create_decision_tools,
    )

__all__ = [
    "CandidateEdit",
    "DecisionConfig",
    "DecisionDossier",
    "DecisionError",
    "DecisionHit",
    "DecisionRecord",
    "DecisionService",
    "DecisionToolkit",
    "EvidenceRef",
    "GenerationResult",
    "ReviewRequest",
    "SyncResult",
    "WikiDecisionGenerateTool",
    "WikiDecisionWhyTool",
    "WikiDecisionsForSymbolTool",
    "create_decision_tools",
]

#: name -> submodule it actually lives in, resolved on first access only.
_LAZY_SOURCES = {
    "CandidateEdit": "parrot.knowledge.wiki.decisions.models",
    "DecisionConfig": "parrot.knowledge.wiki.decisions.models",
    "DecisionDossier": "parrot.knowledge.wiki.decisions.models",
    "DecisionError": "parrot.knowledge.wiki.decisions.models",
    "DecisionHit": "parrot.knowledge.wiki.decisions.models",
    "DecisionRecord": "parrot.knowledge.wiki.decisions.models",
    "EvidenceRef": "parrot.knowledge.wiki.decisions.models",
    "GenerationResult": "parrot.knowledge.wiki.decisions.models",
    "ReviewRequest": "parrot.knowledge.wiki.decisions.models",
    "SyncResult": "parrot.knowledge.wiki.decisions.models",
    "DecisionService": "parrot.knowledge.wiki.decisions.service",
    "DecisionToolkit": "parrot.knowledge.wiki.decisions.toolkit",
    "WikiDecisionGenerateTool": "parrot.knowledge.wiki.decisions.tools",
    "WikiDecisionsForSymbolTool": "parrot.knowledge.wiki.decisions.tools",
    "WikiDecisionWhyTool": "parrot.knowledge.wiki.decisions.tools",
    "create_decision_tools": "parrot.knowledge.wiki.decisions.tools",
}


def __getattr__(name: str) -> Any:
    """PEP 562 lazy attribute resolution — see module docstring."""
    module_path = _LAZY_SOURCES.get(name)
    if module_path is None:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    import importlib

    module = importlib.import_module(module_path)
    value = getattr(module, name)
    globals()[name] = value  # cache: subsequent access skips __getattr__ entirely
    return value


def __dir__() -> list[str]:
    return sorted(__all__)
