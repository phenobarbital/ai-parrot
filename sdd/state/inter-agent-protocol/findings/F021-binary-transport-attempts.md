---
id: F021
query_id: Q059
type: git_log
intent: "Recent history: protobuf/grpc mentions anywhere in history to see if a binary transport was attempted."
executed_at: 2026-10-25T22:41:57Z
duration_ms: 900
parent_id: null
depth: 0
lane_origin: FG-009-binary-transport-attempts
---

# F021 — A gRPC + protobuf ingress (`parrot.events.v1`) WAS built in Jul 2026 — and extracted to navigator-eventbus; OTLP gRPC exporters exist

## Summary

8 commits in 365 days match protobuf/grpc/arrow flight/capnp. The substantive one: `632d2cbf7a` (2026-07-16, FEAT-310 eventbus-v2, TASK-1791) added `parrot/core/events/bus/ingress/grpc.py` (239 lines, `GrpcIngress(BaseHook)`, grpc.aio server), `websocket.py`, a committed `events.proto` + generated `events_pb2*.py`, an optional `grpc` extra (grpcio/grpcio-tools ≥1.74) in `packages/ai-parrot/pyproject.toml`, and tests. One day later FEAT-312 (TASK-1804, `1f5445470e`) moved the whole bus **out of ai-parrot into the external `navigator-eventbus` package** (proto wire package `parrot.events.v1` preserved; imports now `navigator_eventbus.ingress.proto.events_pb2`), and FEAT-317 migrated parrot to consume it. On dev today `parrot/core/events/` contains only `lifecycle/` (events, subscribers incl. `opentelemetry.py`, legacy_bridge, turn_scope); no `bus/ingress/`. Other hits: OTLP exporter factory helpers HTTP + gRPC (TASK-1234, 05-19) and an OTLP endpoint fix (08-26). Nothing on Arrow Flight or Cap'n Proto.

## Citations

- path: `packages/ai-parrot/src/parrot/core/events/bus/ingress/grpc.py`
  commit: `632d2cbf7a` 2026-07-16 Jesus Lara — feat(eventbus-v2): TASK-1791 — WebSocket + gRPC ingress adapters (parrot.events.v1) on BaseHook contract
  excerpt: |
    9 files, +900: pyproject.toml (+9, [grpc] extra), ingress/__init__.py, ingress/grpc.py (239),
    ingress/proto/{README.md, events.proto (52), events_pb2.py, events_pb2_grpc.py}, ingress/websocket.py (163),
    tests/core/events/bus/test_ingress.py (248)   — path NO LONGER EXISTS on dev (moved, see below)
- path: `sdd/tasks/completed/TASK-1791-ws-grpc-ingress.md`
  symbol: Completion Note
  excerpt: |
    GrpcIngress(BaseHook): grpc.aio server for parrot.events.v1.EventBusIngress — proto mirrors the A2UI
    versioned-message shape (explicit version field + typed payload; open dict fields travel as JSON strings
    so the Pydantic boundary stays SSOT); auth failures abort UNAUTHENTICATED ... Optional extra
    grpc = [grpcio>=1.74.0, grpcio-tools>=1.74.0] added to packages/ai-parrot/pyproject.toml
- path: `sdd/tasks/completed/TASK-1804-ingress-ws-grpc.md`
  symbol: Completion Note
  excerpt: |
    regenerated absolute import inside events_pb2_grpc.py (now navigator_eventbus.ingress.proto.events_pb2
    instead of the old parrot.core.events.bus.ingress.proto path) ... proto wire package (parrot.events.v1)
    is preserved verbatim ... Committed in navigator-eventbus as 6537fbd
- path: `sdd/tasks/index/eventbus-core-extraction.json`
  symbol: FEAT-312
  excerpt: |
    completed_at 2026-07-17, 8/8 done (bus extracted to navigator-eventbus)
- path: `sdd/tasks/index/parrot-eventbus-migration.json`
  symbol: FEAT-317
  excerpt: |
    completed_at 2026-07-20, 9/9 done (parrot consumes navigator-eventbus)
- path: `packages/ai-parrot/src/parrot/core/events/lifecycle/subscribers/opentelemetry.py`
  excerpt: |
    only lifecycle/ remains under parrot/core/events on dev (events/, subscribers/, legacy_bridge.py, turn_scope.py, yaml_loader.py)
- commit: `d0751c9567` 2026-05-19 — feat(otel-observability): TASK-1234 — OTLP exporter factory helpers (HTTP + gRPC)
- commit: `97485f734d` 2026-08-26 — fix(unified-telemetry-bus): fix critical OTLP endpoint bug + address 2nd review round

## Notes

Implications for the brainstorm: (1) the VERIFY line "no gRPC transport in ai-parrot / no protobuf-defined envelope" holds for the ai-parrot repo, but a protobuf envelope + grpc.aio server pattern already exists in the sibling `navigator-eventbus` package, including auth-in-metadata and a "JSON strings for open dicts" convention; (2) the `[grpc]` extra may or may not still be in `packages/ai-parrot/pyproject.toml` after the extraction — [cross-lane: type=grep, intent=check whether packages/ai-parrot/pyproject.toml still declares the grpc extra (grpcio/grpcio-tools) after FEAT-312]; (3) the eventbus RPC-on-bus pattern (reply_to/correlation) should be checked in navigator-eventbus, not in parrot — [cross-lane: type=read, intent=inspect how parrot publishes to navigator-eventbus (FEAT-317 migration) for envelope/headers/correlation support].
