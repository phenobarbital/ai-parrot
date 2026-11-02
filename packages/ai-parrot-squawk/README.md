# AI-Parrot Squawk

Squawk is AI-Parrot's typed binary inter-agent protocol satellite. It owns the
Cap'n Proto schema and codec, RPC and event-bus carriers, serving dispatcher,
policy gate, served ledger, blob storage, client toolkit, and adapters. The
transport-free contract remains in core under `parrot.interagent`.

## Layout

| Area | Responsibility |
| --- | --- |
| `contract/` | Capability bindings and contract catalog integration |
| `schema/` | Cap'n Proto wire schemas |
| `transport/` | RPC and event-bus carriers |
| `server/` | Dispatcher and serving path |
| `client/` | Remote toolkit and handle landing |
| `blobs/` | Squawk blob-store implementations |
| `security/` | Capability policy and Biscuit verification |
| `adapters/` | A2A and MCP adapters |

Install it as part of the AI-Parrot workspace with `uv sync`.
