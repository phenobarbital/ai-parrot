"""TOOL_REGISTRY[\"metrics\"] resolves to MetricsToolkit (FEAT-756, TASK-4856)."""

import importlib

from parrot_tools import TOOL_REGISTRY


def test_tool_registry_has_metrics() -> None:
    """Resolve the metrics registry entry to its toolkit class."""
    path = TOOL_REGISTRY["metrics"]
    module_name, _, cls_name = path.rpartition(".")
    cls = getattr(importlib.import_module(module_name), cls_name)
    assert cls.__name__ == "MetricsToolkit"


def test_mixin_exported() -> None:
    """Expose the metric routing mixin from the public mixins package."""
    from parrot.bots.mixins import MetricRoutingMixin

    assert MetricRoutingMixin.__name__ == "MetricRoutingMixin"
