---
id: FC-001
query_id: Q013
type: read
intent: "Read the LedgerEventKind enum and LedgerEvent envelope verbatim - the exact extension point for usage.* kinds."
executed_at: 2026-10-30T22:37:10Z
duration_ms: 180
parent_id: null
depth: 0
---

# FC-001 — LedgerEventKind is a 12-member Literal with no usage.* kind; the envelope has no `worktree` field

## Summary

`LedgerEventKind` is a **`typing.Literal`, not an Enum** (events.py:7-20) with exactly 12
members, all in the `issue.* / task.* / spec.* / insight.*` families. **No `usage.*` kind
exists** — the source document's "Does NOT exist" claim is CONFIRMED. The `LedgerEvent`
envelope is `(event_id, kind, subject, actor, ts, payload)` — it has **no `worktree`
field**, refuting the source's claim that the envelope is `(ts, actor, worktree, kind,
payload)`. `event_id` is a deterministic SHA-1[:12] over `kind|subject|actor|ts|payload`,
computed in `model_post_init` when not supplied — this is the existing idempotency
primitive a `usage.recorded` dedup rule would build on.

## Citations

- path: `packages/ai-parrot/src/parrot/knowledge/wiki/ledger/events.py`
  lines: 7-20
  symbol: `LedgerEventKind`
  excerpt: |
    LedgerEventKind = Literal[
        "issue.opened",
        "issue.claimed",
        "issue.acknowledged",
        "issue.closed",
        "issue.superseded",
        "issue.unclaimed",
        "issue.linked",
        "task.started",
        "task.closed",
        "spec.registered",
        "insight.recorded",
        "insight.superseded",
    ]

- path: `packages/ai-parrot/src/parrot/knowledge/wiki/ledger/events.py`
  lines: 103-111
  symbol: `LedgerEvent`
  excerpt: |
    class LedgerEvent(BaseModel):
        """Immutable single-line event serialized into events.jsonl."""

        event_id: str = Field(default="", description="SHA-1 hash hex digest (first 12 chars)")
        kind: LedgerEventKind
        subject: str = Field(description="Target identifier, e.g. issue:3f8a1c9e, task:TASK-1234, spec:FEAT-566")
        actor: str = Field(description="Author identifier, e.g. agent:codex, human:jesus")
        ts: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
        payload: dict[str, Any] = Field(default_factory=dict)

- path: `packages/ai-parrot/src/parrot/knowledge/wiki/ledger/events.py`
  lines: 88-93
  symbol: `compute_event_id`
  excerpt: |
    def compute_event_id(kind: str, subject: str, actor: str, ts: str, payload: dict[str, Any]) -> str:
        """Compute a deterministic SHA-1 hash hex digest (first 12 chars) for an event."""
        canonical_payload = canonical_json_dumps(payload)
        raw_str = f"{kind}|{subject}|{actor}|{ts}|{canonical_payload}"
        sha1 = hashlib.sha1(raw_str.encode("utf-8")).hexdigest()
        return sha1[:12]

- path: `packages/ai-parrot/src/parrot/knowledge/wiki/ledger/events.py`
  lines: 113-122
  symbol: `LedgerEvent.model_post_init`
  excerpt: |
    def model_post_init(self, __context: Any) -> None:
        """Compute event_id if not provided."""
        if not self.event_id:
            self.event_id = compute_event_id(...)

## Notes

- Every payload family has its own Pydantic model (`IssueOpenedPayload`, `IssueClaimedPayload`,
  `InsightRecordedPayload`, …, events.py:35-80) but `LedgerEvent.payload` itself is an untyped
  `dict[str, Any]` — payload models are validated by the *writer*, not by the envelope.
- `subject` is a prefixed id (`issue:`, `task:`, `spec:`). A usage event would need to pick its
  subject convention; `spec:FEAT-NNN` is the documented form for specs.
- `compute_event_id` includes `ts`, so two identical usage records written at different
  timestamps get different event_ids. Envelope-level dedup alone will NOT satisfy the
  source's `(seat, source_ref)` idempotency requirement — that needs a payload-level
  unique index. See FC-002 for whether the index layer offers one.
