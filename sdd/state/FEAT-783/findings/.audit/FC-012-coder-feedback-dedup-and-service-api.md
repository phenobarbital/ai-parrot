---
id: FC-012
query_id: Q020
type: read
intent: "Read coder_feedback.py - the per-execution plane whose key and retry-dedup rule the usage plane is supposed to copy."
executed_at: 2026-10-30T23:03:00Z
duration_ms: 350
parent_id: null
depth: 0
---

# FC-012 — CONFIRMED: the coder-feedback dedup rule is exactly as the source quotes it — but its key omits `execution_id`, and LedgerService exposes no generic plane API

## Summary

`CoderFeedback.feedback_id` is a computed "stable occurrence key" whose docstring is
verbatim the line the source quotes: *"retries of the recording call are not
recurrences."* The key is `sha256([backend, model, task_id, attempt_uid, pattern])[:24]`.
Two corrections to the source's description: the key is
`(backend, model, task_id, attempt_uid, pattern)` — **it does not include
`execution_id`**, contrary to the source's "per-execution planes keyed by
`(task_id, attempt_uid, backend, model, execution_id)`" — and the dedup dimension is the
*semantic* `pattern`, not a request identifier, so it is a near-miss analogue for the
source's proposed `(seat, source_ref)` idempotency, not a template for it.

`LedgerService`'s entire public API is issue-shaped: `open_issue`, `ready_work`,
`active_issues`, `list_issues`, `get_issue`, `issue_history`, `claim`, `acknowledge`,
`close_issue`, `unclaim`, `get_context`, `merge_blockers`, `feature_index_status`,
`export_snapshot`, `export_shared_log` / `import_shared_log` / `rotate_shared_log`,
`compact`, `audit`. There is **no generic register-a-plane seam**: a usage plane would not
"inherit `export_snapshot`/`compact`/`audit` for free" as the source assumes — each of
those methods is hand-written against issues (see FC-002 for `compact`).

## Citations

- path: `packages/ai-parrot/src/parrot/knowledge/wiki/ledger/coder_feedback.py`
  lines: 66-71
  symbol: `CoderFeedback.feedback_id`
  excerpt: |
    def feedback_id(self) -> str:
        """Stable occurrence key: retries of the recording call are not recurrences."""
        key = [self.backend, self.model, self.task_id, self.attempt_uid, self.pattern]
        digest = hashlib.sha256(json.dumps(key, ensure_ascii=True).encode()).hexdigest()[:24]

- path: `packages/ai-parrot/src/parrot/knowledge/wiki/ledger/coder_feedback.py`
  lines: 80-96
  symbol: `CoderFeedbackStore`
  excerpt: |
    class CoderFeedbackStore:
        def __init__(self, log: LedgerLog) -> None:
        @classmethod
        def from_root(cls, root: Path) -> CoderFeedbackStore:
        async def record(self, feedback: CoderFeedback) -> CoderFeedbackReceipt:

- path: `packages/ai-parrot/src/parrot/knowledge/wiki/ledger/coder_feedback.py`
  lines: 114-160
  symbol: `retract` / `context`
  excerpt: |
    async def retract(self, feedback_id: str, reason: str, actor: str) -> bool:
    def _read(self) -> list[tuple[str, CoderFeedback]]:
    async def context(...):
        """Render prior corrections for this model, ranked by scope and recurrence."""

- path: `packages/ai-parrot/src/parrot/knowledge/wiki/ledger/service.py`
  lines: 243-532
  symbol: `LedgerService public API`
  excerpt: |
    async def open_issue(...)          async def ready_work(...)
    async def active_issues(...)       async def list_issues(...)
    async def get_issue(...)           async def issue_history(...)
    async def claim(...)               async def acknowledge(...)
    async def close_issue(...)         async def unclaim(...)
    async def get_context(...)         async def merge_blockers(...)
    async def feature_index_status(...) async def export_snapshot(...)

- path: `packages/ai-parrot/src/parrot/knowledge/wiki/ledger/service.py`
  lines: 577-646
  symbol: `shared-log + maintenance API`
  excerpt: |
    async def export_shared_log(self, repo_root: Path | None = None) -> "SharedLogExportReport":
    async def import_shared_log(self, repo_root: Path | None = None, *, force: bool = False) -> ...
    async def rotate_shared_log(...)
    async def compact(self, older_than_days: int = 30) -> int:
    async def audit(self) -> dict[str, Any]:

## Notes

- `CoderFeedbackStore` takes a `LedgerLog`, not a `LedgerIndex` — the coder planes write to
  the event log and **re-read it with a synchronous `_read()` scan** rather than querying an
  index. At per-attempt volume that is fine; at per-request usage volume it is not (FC-002).
- `coder_reviews.py` and `coder_suspensions.py` follow the same `from_root(Path)` + log-scan
  shape, so "a plane" in this package means "a Pydantic model plus a log scan", not a table.
