---
id: F006
query_id: Q021
type: read
intent: "Read the ledger event model: fields of an event, allowed kinds, ids — base for escrow.* / work.completed kinds."
executed_at: 2026-11-07T01:22:26Z
duration_ms: 1500
parent_id: null
depth: 1
merged_from: [FC-006, FW-002]
---

# F006 — LedgerEvent is a closed Literal of 12 kinds with a content-addressed id; actor is a free string, nothing is signed

## Summary

`packages/ai-parrot/src/parrot/knowledge/wiki/ledger/events.py` (122 lines) defines `LedgerEventKind` as a closed `Literal` of 12 kinds (`issue.*` ×7, `task.started`, `task.closed`, `spec.registered`, `insight.recorded`, `insight.superseded`). `LedgerEvent` (Pydantic) has `event_id` (SHA-1[:12] of `kind|subject|actor|ts|canonical payload`, computed in `model_post_init`), `kind`, `subject` (e.g. `spec:FEAT-566`, `task:TASK-1234`), `actor` (free string, convention `agent:<name>` / `human:<name>`), `ts`, `payload: dict`. Adding `work.completed` / `escrow.*` requires editing the Literal (Q020 found no dynamic registry). There is **no signature, key, or attestation field**: the only integrity guarantee is that `event_id` matches its own content (`verify_event_identity` in outbox.py). A "signed APPROVED verdict" therefore needs a new mechanism; the closest existing precedent is the `IssueAcknowledgedPayload` rule that `acknowledged_by` "Must be a human actor".

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
  lines: 62-70
  symbol: `IssueAcknowledgedPayload`
  excerpt: |
    class IssueAcknowledgedPayload(BaseModel):
        """Explicit acceptance that an open critical issue must not block a merge.
        Does NOT change `status`; the index sets `acknowledged=True` on the issue page.
        """
        acknowledged_by: str = Field(description="Must be a human actor, e.g. human:jesus")
        reason: str

- path: `packages/ai-parrot/src/parrot/knowledge/wiki/ledger/events.py`
  lines: 86-95
  symbol: `compute_event_id`
  excerpt: |
    def compute_event_id(kind: str, subject: str, actor: str, ts: str, payload: dict[str, Any]) -> str:
        """Compute a deterministic SHA-1 hash hex digest (first 12 chars) for an event."""
        canonical_payload = canonical_json_dumps(payload)
        raw_str = f"{kind}|{subject}|{actor}|{ts}|{canonical_payload}"
        sha1 = hashlib.sha1(raw_str.encode("utf-8")).hexdigest()
        return sha1[:12]

- path: `packages/ai-parrot/src/parrot/knowledge/wiki/ledger/events.py`
  lines: 103-122
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
        def model_post_init(self, __context: Any) -> None:
            if not self.event_id:

- path: `packages/ai-parrot/src/parrot/knowledge/wiki/ledger/outbox.py`
  lines: 106-110
  symbol: `verify_event_identity`
  excerpt: |
    def verify_event_identity(event: LedgerEvent) -> None:
        """Raise when ``event.event_id`` is not the hash of its own content."""
        expected = compute_event_id(event.kind, event.subject, event.actor, event.ts, event.payload)
        if event.event_id != expected:
            raise EventIdentityError(f"event {event.event_id!r} does not match its content (expected {expected})")

## Notes

- Q020 (grep for `kind|def append|def emit|class .*Event` across events.py/shared_log.py/log.py) is folded here: the only append APIs are `LedgerLog.append(event)` and `LedgerLog.append_line(raw)` (used by import in shared_log.py:245).
- Actor strings are produced by `parrot.knowledge.wiki.actor.current_actor()` / `scoped_actor()` (actor.py:19,31) — resolution from env, not from a credential. See FC-008.


---

<!-- merged from FW-002 -->

# F006 — LedgerEvent kinds are a closed Literal of 12 (no work.* / escrow.*); event_id is a content-addressed SHA-1 — no signature exists, only an actor string convention

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
