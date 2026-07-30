"""Dream-cycle package: episodic -> wiki brain consolidation (FEAT-390).

Exposes the data models and JSON sidecar persistence helpers for the
dream-cycle pipeline. See ``sdd/specs/dream-cycle-brain-consolidation.spec.md``
for the full design.
"""
from .brain import BrainStore
from .models import (
    DistilledKnowledge,
    DreamConfig,
    DreamCycleReport,
    DreamState,
    load_state,
    save_state,
)
from .runner import DreamCycleRunner

__all__ = [
    "BrainStore",
    "DistilledKnowledge",
    "DreamConfig",
    "DreamCycleReport",
    "DreamCycleRunner",
    "DreamState",
    "load_state",
    "save_state",
]
