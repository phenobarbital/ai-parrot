"""Planogram Compliance Pipeline exports."""

from importlib import import_module

__all__ = (
    "PlanogramCompliance",
    "AbstractPlanogramType",
    "InkWall",
)


def __getattr__(name: str):
    if name == "PlanogramCompliance":
        mod = import_module(".plan", __name__)
        return getattr(mod, name)
    if name == "AbstractPlanogramType":
        mod = import_module(".types", __name__)
        return getattr(mod, name)
    if name == "InkWall":
        mod = import_module(".types", __name__)
        return getattr(mod, name)
    raise AttributeError(name)
