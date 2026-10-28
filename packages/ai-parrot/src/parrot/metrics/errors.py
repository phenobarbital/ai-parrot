"""Errors raised by the metric definition registry (FEAT-756)."""

from __future__ import annotations


class MetricRegistryError(Exception):
    """Base error of the metric registry."""


class MetricNotFound(MetricRegistryError):
    """No definition with that id is visible to the caller."""


class MetricSourceUnavailable(MetricRegistryError):
    """The source kind is declared but cannot run here (e.g. ``semantic_metric``, FEAT-704)."""
