"""Capability Registry package for Intent Router (FEAT-070).

Provides routing models, enums, and the CapabilityRegistry for
embedding-based semantic resource discovery.
"""
from .models import (
    CapabilityEntry,
    IntentRouterConfig,
    ResourceType,
    RouterCandidate,
    RoutingDecision,
    RoutingTrace,
    RoutingType,
    TraceEntry,
)
from .registry import CapabilityRegistry

__all__ = [
    "CapabilityEntry",
    "CapabilityRegistry",
    "IntentRouterConfig",
    "ResourceType",
    "RouterCandidate",
    "RoutingDecision",
    "RoutingTrace",
    "RoutingType",
    "TraceEntry",
]
