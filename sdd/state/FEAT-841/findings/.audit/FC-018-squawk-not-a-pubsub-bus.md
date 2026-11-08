---
id: FC-018
query_id: Q034
type: grep
intent: "Squawk/Roost local inter-agent transport: can a host-side monitor subscribe to a worker's completion message?"
executed_at: 2026-11-07T01:25:27Z
duration_ms: 1200
parent_id: null
depth: 0
---

# FC-018 — Squawk exposes no publish/subscribe/broadcast API; it is a contract/blob/served-ledger package, not a message bus

## Summary

Grep for `class *(Hub|Roost|Channel|Envelope|Transport)` and `def (publish|send|subscribe|broadcast)` under `packages/ai-parrot-squawk/src/parrot/squawk/` returned **no matches**. The package layout is `blobs/` (`SquawkBlobStore`, `LocalDiskBlobStore`, `FileManagerBlobStore`, `BlobSweeper`), `client/` (`ReceivedLedger`), `contract/` (`LLMBackedSpec`, `CapabilityBinding`, `ContractCache`), `server/` (`ServedLedger`, `PromotionAnalyzer`), `sql/`, `telemetry.py` (`ServedTelemetry`). Nothing resembles an event fan-out that a host-side monitor could subscribe to. The brainstorm's assumption that a Squawk/Roost bus could carry `work.completed` is not supported by the code as it stands; Squawk is out of scope for v1 transport.

## Citations

- path: `packages/ai-parrot-squawk/src/parrot/squawk/server/ledger.py`
  lines: 24-24
  symbol: `ServedLedger`
  excerpt: |
    class ServedLedger:

- path: `packages/ai-parrot-squawk/src/parrot/squawk/client/received_ledger.py`
  lines: 28-28
  symbol: `ReceivedLedger`
  excerpt: |
    class ReceivedLedger:

- path: `packages/ai-parrot-squawk/src/parrot/squawk/contract/bindings.py`
  lines: 30-30
  symbol: `CapabilityBinding`
  excerpt: |
    class CapabilityBinding(BaseModel):

- path: `packages/ai-parrot-squawk/src/parrot/squawk/blobs/store.py`
  lines: 93-93
  symbol: `SquawkBlobStore`
  excerpt: |
    class SquawkBlobStore(ABC):

## Notes

- Squawk's `ServedLedger`/`ReceivedLedger` are the inter-agent protocol's own ledgers (FEAT-746), unrelated to the SDD work ledger.
- [cross-lane: type=git_log, intent=confirm whether a Roost (FEAT-747) local transport landed under a different package name]
