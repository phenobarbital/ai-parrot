---
id: FW-002
query_id: Q002
type: wiki_page
intent: "Orient: the shared ledger event log (FEAT-694) — event kinds, append API, hooks, archive rotation."
executed_at: 2026-11-07T01:23:54Z
duration_ms: 900
parent_id: null
depth: 1
---

# FW-002 — LedgerEvent kinds are a closed Literal of 12 (no work.* / escrow.*); event_id is a content-addressed SHA-1 — no signature exists, only an actor string convention

## Summary

`parrot/knowledge/wiki/ledger/events.py` defines `LedgerEventKind` as a closed `Literal` of 12 kinds (`issue.*` ×7, `task.started`, `task.closed`, `spec.registered`, `insight.recorded`, `insight.superseded`). `LedgerEvent` is an immutable Pydantic line `{event_id, kind, subject, actor, ts, payload}`; `event_id = sha1(kind|subject|actor|ts|canonical(payload))[:12]` is computed in `model_post_init`. Nothing cryptographic exists: "signed" today means an `actor` prefix convention (`agent:…`, `human:…`) that a service method may check (FW-007). Adding `work.completed` / `escrow.*` means extending the Literal, adding payload models, and teaching the index reducer the new kinds.

## Citations

- path: `packages/ai-parrot/src/parrot/knowledge/wiki/ledger/events.py`
  lines: 7-20
  symbol: `LedgerEventKind`
  wiki_page_id: file:packages/ai-parrot/src/parrot/knowledge/wiki/ledger/events.py
  excerpt: |
    LedgerEventKind = Literal[
        "issue.opened", "issue.claimed", "issue.acknowledged", "issue.closed",
        "issue.superseded", "issue.unclaimed", "issue.linked",
        "task.started", "task.closed", "spec.registered",
        "insight.recorded", "insight.superseded",
    ]
- path: `packages/ai-parrot/src/parrot/knowledge/wiki/ledger/events.py`
  lines: 88-93
  symbol: `compute_event_id`
  excerpt: |
    def compute_event_id(kind, subject, actor, ts, payload) -> str:
        raw_str = f"{kind}|{subject}|{actor}|{ts}|{canonical_payload}"
        return hashlib.sha1(raw_str.encode("utf-8")).hexdigest()[:12]
- path: `packages/ai-parrot/src/parrot/knowledge/wiki/ledger/events.py`
  lines: 102-120
  symbol: `LedgerEvent`
  excerpt: |
    class LedgerEvent(BaseModel):
        event_id: str = Field(default="")
        kind: LedgerEventKind
        subject: str   # e.g. issue:3f8a1c9e, task:TASK-1234, spec:FEAT-566
        actor: str     # e.g. agent:codex, human:jesus
        ts: str
        payload: dict[str, Any]
- path: `packages/ai-parrot/src/parrot/knowledge/wiki/ledger/events.py`
  lines: 57-66
  symbol: `IssueAcknowledgedPayload`
  excerpt: |
    acknowledged_by: str = Field(description="Must be a human actor, e.g. human:jesus")
    reason: str

## Notes

FEAT-694 spec (approved) states `event_id` dedup is exact and union-mergeable across machines — a verdict event appended on the host and imported elsewhere folds without conflict. [cross-lane: type=read, intent=codebase lane Q021 should confirm exact line numbers of the Literal and LedgerEvent; index.py reducer must learn new kinds.]
