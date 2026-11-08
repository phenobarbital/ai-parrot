---
id: FC-008
query_id: Q023
type: grep
intent: "Does the ledger sign or attest anything today? (signature, hmac, actor identity)."
executed_at: 2026-11-07T01:22:26Z
duration_ms: 1200
parent_id: null
depth: 0
---

# FC-008 — Nothing in the ledger is signed; actor is an env-derived string; the only verified approval precedent is GitCommitApprovalAdapter in the decisions plane

## Summary

Grep for `sign|hmac|attest|actor` over `parrot/knowledge/wiki/ledger/`, `actor.py` and `identity.py`: zero hits for `hmac`/`attest`/cryptographic `sign`. `actor` appears only as a free-form string attribute: `current_actor()`/`scoped_actor()`/`actor_scope()` in `actor.py` (19/31/37) resolve it from environment/context and the ledger service accepts `params.actor` from the caller (operations.py:124,135). The worker writes events as `actor="agent:sdd-worker"` (coder_reviews.py:88, coder_feedback.py:108, coder_suspensions.py:302) — i.e. any process can claim any actor. The sole "verified approval" mechanism in the codebase is outside the ledger: `parrot/knowledge/wiki/decisions/approvals.py` — `ApprovalEntry` (block_sha256 + commit + actor) checked by `GitCommitApprovalAdapter.verify`, which trusts an approval only through the git commit that recorded it (commit, ancestry, actor, block hashes). That is the in-repo precedent for a "signed" verdict: bind it to a commit on a protected branch rather than to a cryptographic key.

## Citations

- path: `packages/ai-parrot/src/parrot/knowledge/wiki/actor.py`
  lines: 19-37
  symbol: `current_actor`
  excerpt: |
    def current_actor(default: str = DEFAULT_ACTOR) -> str:
    def scoped_actor() -> str | None:
    def actor_scope(actor: str | None) -> Iterator[None]:

- path: `packages/ai-parrot/src/parrot/knowledge/wiki/ledger/operations.py`
  lines: 122-124
  symbol: `ledger_claim`
  excerpt: |
    """ledger_claim — claim an issue; the scoped actor wins over the argument."""
        success = await service.claim(params.issue_id, scoped_actor() or params.actor or current_actor())

- path: `packages/ai-parrot/src/parrot/knowledge/wiki/ledger/coder_reviews.py`
  lines: 88-88
  symbol: null
  excerpt: |
    kind="insight.recorded", subject=subject, actor="agent:sdd-worker", payload=payload.model_dump()

- path: `packages/ai-parrot/src/parrot/knowledge/wiki/decisions/approvals.py`
  lines: 31-42
  symbol: `ApprovalEntry`
  excerpt: |
    class ApprovalEntry(_Strict):
        """One append-only approval event."""
        kind: Literal["spec", "seed", "retirement", "waiver"]
        batch_id: str = Field(..., min_length=1)
        spec_path: str = Field(..., min_length=1)
        document_id: str = Field(..., min_length=1)
        entries: list[DecisionRef]
        block_sha256: str
        commit: str = Field(..., min_length=7)
        actor: str = Field(..., min_length=1)

- path: `packages/ai-parrot/src/parrot/knowledge/wiki/decisions/approvals.py`
  lines: 45-46
  symbol: `ApprovalManifest`
  excerpt: |
    class ApprovalManifest:
        """Parsed ``sdd/decisions/approvals.jsonl`` (append-only)."""

- path: `packages/ai-parrot/src/parrot/knowledge/wiki/decisions/approvals.py`
  lines: 96-104
  symbol: `ApprovalAdapter`
  excerpt: |
    class ApprovalAdapter(Protocol):
        """Pluggable trust check for an approval entry."""
        async def verify(self, entry: ApprovalEntry, *, spec_text: str) -> tuple[bool, list[DecisionDiagnostic]]:
    class GitCommitApprovalAdapter:
        """Trust an approval only through the git commit that recorded it."""
        def __init__(self, root: Path, base_branch: str) -> None:

- path: `packages/ai-parrot/src/parrot/knowledge/wiki/decisions/approvals.py`
  lines: 123-125
  symbol: `GitCommitApprovalAdapter.verify`
  excerpt: |
        async def verify(self, entry: ApprovalEntry, *, spec_text: str) -> tuple[bool, list[DecisionDiagnostic]]:
            """Verify commit, ancestry, actor, and required block hashes for an approval."""

## Notes

- Depth-1 follow-up read of `decisions/approvals.py` (parent Q023) included above; it is the FEAT-578 wiki ADR plane.
- Because the worker and the verdict agent would both write to the same `.parrot/ledger/events.jsonl` with self-declared actors, "the verdict was produced by someone who did not participate" cannot be enforced by the ledger alone — it needs process separation (different launch / sandbox) plus a verification that mirrors `GitCommitApprovalAdapter` (verdict recorded by a host-side process, bound to head SHA).
