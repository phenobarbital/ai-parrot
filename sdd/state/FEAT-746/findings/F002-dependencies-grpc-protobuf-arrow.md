---
id: F002
query_id: [Q021]
type: grep
intent: "Dependency check: does any workspace pyproject declare grpc / protobuf / pyarrow / polars / capnp / flight?"
executed_at: 2026-10-25T22:42:35Z
duration_ms: 0
parent_id: null
depth: 0
lane_origin: FC-002-dependencies-grpc-protobuf-arrow
---

# F002 — Workspace already pins protobuf and pyarrow; gRPC only via navigator-eventbus extra; no polars, no capnp, no Arrow Flight

## Summary

The root `pyproject.toml` pins `protobuf>=6.31.1,<6.32` (for LiveKit stubs) and depends on `opentelemetry-exporter-otlp-proto-grpc`. `ai-parrot` declares `pyarrow>=25.0` as a hard dependency and an optional `grpc = ["navigator-eventbus[grpc]"]` extra (the gRPC ingress adapter moved to navigator-eventbus in FEAT-310/317). `ai-parrot-server` also requires `pyarrow>=25.0` and ships "the gRPC proto definition" as a package data file (comment at line 116) with a "MCP server transports (QUIC, gRPC, etc.)" section. No match for `polars`, `capnp` or `flight` anywhere — Polars (D6) is a new dependency.

## Citations

- path: `pyproject.toml`
  lines: 150
  symbol: `opentelemetry-exporter-otlp-proto-grpc`
  excerpt: |
    "opentelemetry-exporter-otlp-proto-grpc>=1.39.0",
- path: `pyproject.toml`
  lines: 199-203
  symbol: `protobuf`
  excerpt: |
    # Keep the shared runtime on the Protobuf 6.31 line. This is required by
    # LiveKit 1.1.18 still ships stubs generated with Protobuf 5.29.3; remove
    "protobuf>=6.31.1,<6.32",
- path: `packages/ai-parrot/pyproject.toml`
  lines: 174-180
  symbol: `pyarrow`
  excerpt: |
    # every DataFrame into the worker) imports `pyarrow` unconditionally.
    "pyarrow>=25.0",
- path: `packages/ai-parrot/pyproject.toml`
  lines: 707-712
  symbol: `grpc` (extra)
  excerpt: |
    # FEAT-310/FEAT-317: gRPC ingress adapter now lives in navigator-eventbus
    grpc = [
        "navigator-eventbus[grpc]",
- path: `packages/ai-parrot-server/pyproject.toml`
  lines: 37-39
  symbol: `pyarrow`
  excerpt: |
    # (FEAT-327) — dtype-preserving via pyarrow. Declared here (not
    "pyarrow>=25.0",
- path: `packages/ai-parrot-server/pyproject.toml`
  lines: 52
  symbol: (comment)
  excerpt: |
    # MCP server transports (QUIC, gRPC, etc.)
- path: `packages/ai-parrot-server/pyproject.toml`
  lines: 116
  symbol: (comment)
  excerpt: |
    # Non-Python data files: schema DDL and the gRPC proto definition. Without
- path: `packages/ai-parrot-tools/pyproject.toml`
  lines: 118
  symbol: `powerbi` extra
  excerpt: |
    powerbi = ["pyarrow>=25.0"]

## Notes

No `polars`, `capnp`, `flight` hits in any pyproject. The "gRPC proto definition" data file referenced at ai-parrot-server pyproject:116 was not located within this lane's budget (grpc_session.py imports its proto commented out — see FC-003). [cross-lane: type=glob, intent=find the .proto file shipped by ai-parrot-server (pattern packages/ai-parrot-server/**/*.proto)]

[citation-check: note] 2026-10-26 probe triage — 185 checks: 130 verified, 6 ambiguous, 49 'missing'. Of the 49, all but the items tagged above are probe-sheet artifacts (descriptive labels such as `module`, `import`, `transport`, dependency strings in pyproject files, and directory paths submitted as `file` checks); each of those was re-verified inline: pyarrow>=25.0 (core:180, server:39, tools:118), protobuf (root:203), navigator-eventbus[grpc] (core:712), grpc_host (server mcp/config.py:203), exclude_tools (working_memory/tool.py:89), GovernedDatasetSink (semantic-layer.spec.md:682), mcp.proto present, no polars in any pyproject.
