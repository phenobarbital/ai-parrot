# TASK-1791: WebSocket + gRPC ingress adapters on the BaseHook contract

**Feature**: FEAT-310 — Unified EventBus v2 — queue-based dispatch, severity, ingress channels, and notifications
**Spec**: `sdd/specs/eventbus-v2.spec.md`
**Status**: done
**Priority**: medium
**Estimated effort**: L (4-8h)
**Depends-on**: TASK-1786
**Assigned-to**: unassigned

---

## Context

Module 9 of FEAT-310 (spec §3, Phase 3) — goal G5's second half. Parrot has
no WebSocket or gRPC ingress; external systems can only push events via HTTP
webhooks. This task adds both as `BaseHook` implementations that validate
input with `IngressEnvelope` (Pydantic boundary, *resolved in brainstorm*)
and publish to the bus. gRPC proto mirrors the A2UI versioned-envelope shape
(*resolved in brainstorm*).

---

## Scope

- `ingress/websocket.py`: `WebSocketIngress(BaseHook)` — aiohttp WebSocket
  endpoint registered via `setup_routes(app)`; each inbound JSON message →
  `IngressEnvelope` validation → `to_envelope()` → bus publish; malformed
  input rejected with a structured error frame (connection kept open);
  auth via configurable token header/query (reuse whatever auth pattern
  existing webhook hooks use — verify with grep).
- `ingress/grpc.py` + `ingress/proto/`: `GrpcIngress(BaseHook)` — proto
  `parrot.events.v1.PublishRequest`/`PublishResponse` mirroring the
  `A2UIMessageBase` versioned-message shape (version field + typed payload);
  `grpcio` imported lazily; clear `ImportError` message pointing to
  `pip install ai-parrot[grpc]`.
- New optional extra `grpc` in `pyproject.toml` (`grpcio`, `grpcio-tools`)
  — added via `uv`, no new REQUIRED runtime deps (spec AC).
- Proto compilation: check how the repo handles generated code elsewhere;
  commit generated `_pb2.py`/`_pb2_grpc.py` alongside the `.proto` with a
  regeneration script/README note.
- Tests: `test_ws_grpc_ingress_validation` — malformed external payload
  rejected at the `IngressEnvelope` boundary (both adapters); gRPC tests
  skip cleanly when `grpcio` is not installed.

**NOT in scope**: hooks manager changes (TASK-1790), egress subscribers,
client SDKs for the new endpoints.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/core/events/bus/ingress/__init__.py` | CREATE | exports (grpc lazily) |
| `packages/ai-parrot/src/parrot/core/events/bus/ingress/websocket.py` | CREATE | `WebSocketIngress` |
| `packages/ai-parrot/src/parrot/core/events/bus/ingress/grpc.py` | CREATE | `GrpcIngress` |
| `packages/ai-parrot/src/parrot/core/events/bus/ingress/proto/events.proto` | CREATE | `parrot.events.v1` |
| `packages/ai-parrot/src/parrot/core/events/bus/ingress/proto/` (generated) | CREATE | pb2 modules + regen note |
| `pyproject.toml` | MODIFY | optional extra `grpc` |
| `packages/ai-parrot/tests/core/events/bus/test_ingress.py` | CREATE | validation tests |

---

## Codebase Contract (Anti-Hallucination)

> Verified on `dev` 2026-07-16 (commit b7226186d).

### Verified Imports
```python
from parrot.core.hooks.base import BaseHook                 # hooks/base.py:96
from parrot.core.events.bus.ingress_models import IngressEnvelope   # TASK-1783
from parrot.core.events import EventBus                     # facade (TASK-1786)
from aiohttp import web                                     # aiohttp already required
```

### Existing Signatures to Use
```python
# packages/ai-parrot/src/parrot/core/hooks/base.py:96
class BaseHook(ABC):
    @abstractmethod
    async def start(self) -> None        # line 169
    @abstractmethod
    async def stop(self) -> None         # line 173
    def setup_routes(self, app: Any) -> None   # line 176 — aiohttp route hook

# packages/ai-parrot/src/parrot/outputs/a2ui/models.py:157 — proto shape inspiration
class A2UIMessageBase(BaseModel):
    # versioned-message envelope: version + message type + payload
```

### Does NOT Exist
- ~~gRPC or WebSocket ingress hooks anywhere~~ — hooks today cover HTTP webhooks/IMAP/brokers/scheduler/watchdog only; both adapters are new.
- ~~`grpcio` in dependencies~~ — NEW optional extra `parrot[grpc]`; never import at module top-level of `ingress/__init__.py`.
- ~~An existing `.proto` toolchain in the repo~~ — verify with `find . -name "*.proto"` before assuming; if none, this task establishes the pattern (document regen command).
- ~~`parrot.events.v1` package~~ — created by THIS task's proto.

---

## Implementation Notes

### Pattern to Follow
`BaseHook` lifecycle exactly like existing webhook hooks (grep a concrete
hook under `parrot/core/hooks/` for `setup_routes` usage and auth handling
and mirror it). WS handler: `web.WebSocketResponse()` loop, `msg.type ==
WSMsgType.TEXT` → validate → publish → ack frame `{"status": "accepted",
"event_id": ...}`.

### Key Constraints
- ALL external input passes through `IngressEnvelope` (extra="forbid") —
  never construct `EventEnvelope` directly from raw client JSON (spec §2).
- gRPC servicer publishes via the same validation path (proto → dict →
  `IngressEnvelope`).
- Auth required by default; configurable via navconfig; unauthenticated →
  4401 close (WS) / UNAUTHENTICATED (gRPC).
- Both adapters register with `HookManager.register()` like any hook.
- Google docstrings, strict typing, `self.logger`.

### References in Codebase
- `packages/ai-parrot/src/parrot/core/hooks/` — concrete hook implementations (auth + routes pattern)
- `packages/ai-parrot/src/parrot/outputs/a2ui/models.py:157` — versioned envelope shape

---

## Acceptance Criteria

- [ ] `WebSocketIngress` accepts a valid JSON event and it arrives at a bus subscriber (aiohttp test client).
- [ ] Malformed/extra-field payload rejected at `IngressEnvelope` boundary with structured error; connection survives.
- [ ] `GrpcIngress` importable ONLY with extra installed; helpful ImportError otherwise; core test suite passes WITHOUT grpcio installed.
- [ ] Proto shape mirrors A2UI versioned-message pattern (`version` field present) under package `parrot.events.v1`.
- [ ] `pyproject.toml` gains optional extra `grpc`; no new required runtime deps.
- [ ] All tests pass: `pytest packages/ai-parrot/tests/core/events/bus/test_ingress.py -v`
- [ ] `ruff check packages/ai-parrot/src/parrot/core/events/bus/ingress/` clean (generated pb2 files excluded).

---

## Test Specification

```python
# packages/ai-parrot/tests/core/events/bus/test_ingress.py
import pytest

async def test_ws_ingress_valid_event_reaches_bus(aiohttp_client): ...
async def test_ws_ingress_malformed_payload_rejected(aiohttp_client): ...
async def test_ws_ingress_requires_auth(aiohttp_client): ...

grpc = pytest.importorskip("grpc")
async def test_grpc_ingress_validation(): ...
```

---

## Agent Instructions

1. Read spec §2 (Ingress), §6 contract, and an existing concrete hook before coding.
2. Verify TASK-1786 is in `sdd/tasks/completed/`.
3. Use `uv` for the optional-extra change; activate `.venv` first.
4. Update `sdd/tasks/index/eventbus-v2.json` status transitions.
5. Move this file to `sdd/tasks/completed/` and fill in the Completion Note.

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**: sdd-worker (Claude)
**Date**: 2026-07-16
**Notes**: `WebSocketIngress(BaseHook)`: aiohttp WS endpoint via setup_routes; every TEXT frame -> IngressEnvelope (extra=forbid) -> facade emit; malformed input answered with structured {status: rejected, error} frame, connection survives; auth REQUIRED by default (Bearer header / X-API-Key / ?token=, from kwarg or navconfig BUS_INGRESS_TOKEN; no token configured -> all refused with 401 pre-upgrade). `GrpcIngress(BaseHook)`: grpc.aio server for `parrot.events.v1.EventBusIngress` — proto mirrors the A2UI versioned-message shape (explicit `version` field + typed payload; open dict fields travel as JSON strings so the Pydantic boundary stays SSOT); auth failures abort UNAUTHENTICATED, validation failures return structured status=rejected; grpcio imported at module level of grpc.py only, exposed lazily via ingress/__init__ __getattr__ with a helpful `pip install ai-parrot[grpc]` ImportError. Generated events_pb2/_pb2_grpc COMMITTED alongside events.proto + regen README (grpcio-tools 1.74.0 / protobuf-6.31.1-compatible gencode — forward-compatible with 7.x runtimes; repo venv left at protobuf 6.31.1 per lockfile). Optional extra `grpc = [grpcio>=1.74.0, grpcio-tools>=1.74.0]` added to packages/ai-parrot/pyproject.toml — no new required runtime deps. 9 ingress tests pass incl. real in-process grpc.aio round-trip (grpc present transitively in this env; tests importorskip cleanly without it); full events+hooks regression 177 passed; ruff clean (pb2 excluded).

**Deviations from spec**: (1) validation failures return an application-level status=rejected PublishResponse over an OK transport status instead of INVALID_ARGUMENT — grpc.aio cannot both set a non-OK code and deliver the structured response; the structured contract won. (2) HookType has no WEBSOCKET/GRPC member and models.py is outside this task's file list — both adapters keep BaseHook's default hook_type; they publish directly to the bus so the enum value is cosmetic (stats only). Consider adding enum members in a follow-up.
