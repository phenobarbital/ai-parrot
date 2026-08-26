"""ai_parrot_openlit_bridge — minimal OpenLIT OTLP endpoint helper.

FEAT-462 — Unified Telemetry Bus. Replaces the `openlit` SDK (a
monkey-patching LLM SDK instrumentor whose version-pinned `openai`
dependency conflicted with ai-parrot's own `openai` pin) with a
zero-heavy-dependency bridge: an async OTLP endpoint reachability probe
plus a ``parrot-openlit-check`` CLI, for deployments that still want a
quick sanity check against their OpenLIT/OTLP collector.

OpenLIT itself is now a pure deployment-time OTLP endpoint configuration —
see ``ai-parrot``'s ``ObservabilityConfig.otlp_targets`` (multi-endpoint
OTLP export) and ``OpenLitUsageRecorder`` (usage-only spans).

Public surface:
  * ``validate_endpoint`` — async OTLP endpoint reachability probe.
  * ``EndpointStatus`` — probe result dataclass.
"""

from ai_parrot_openlit_bridge.probe import EndpointStatus, validate_endpoint

__all__: list[str] = [
    "EndpointStatus",
    "validate_endpoint",
]

__version__ = "0.1.0"
