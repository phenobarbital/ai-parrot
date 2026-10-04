"""Backward-compatible proxy for ai-parrot-pipelines."""

from importlib import import_module

__all__ = (
    "PlanogramCompliance",
    "AbstractPlanogramType",
)


def __getattr__(name: str):
    mod = import_module("parrot_pipelines.planogram")
    return getattr(mod, name)
