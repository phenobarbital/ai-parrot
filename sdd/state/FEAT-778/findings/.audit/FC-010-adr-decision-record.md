---
id: FC-010
query_id: Q029
type: read
intent: "Read ADR models: status enum (proposed/accepted/superseded), tags/components, source revision."
executed_at: 2026-10-30T16:42:58Z
duration_ms: 700
parent_id: null
depth: 0
---

# FC-010 — `DecisionRecord` (ADR) has `source_status` {unknown,proposed,accepted,rejected,deprecated,superseded}, `review_status`, `revision`, evidence with `source_sha1`, `content_fingerprint`; no tag/component field

## Summary

`knowledge/wiki/decisions/models.py` (326 lines, FEAT-578). The canonical per-`adr:` page record is `DecisionRecord` with `origin` documented|inferred, `source_status` (from the ADR text) separate from `review_status` (maintainer gate), `evidence: list[EvidenceRef]` (each with `source_sha1`), `links`, `review_history: list[ReviewEvent]` (revision, before/after sha1), `generation: GenerationInfo` (`input_sha1`). Filtering by `status: accepted` is directly supported; filtering "by tag or component" is not — there is no tags field, only `links` and `evidence` paths. Produced ADRs born `proposed` + review gate matches the existing `review_status` workflow (`ReviewRequest` with `expected_revision`).

## Citations

- path: `packages/ai-parrot/src/parrot/knowledge/wiki/decisions/models.py`
  lines: 172-194
  symbol: `DecisionRecord`
  excerpt: |
    class DecisionRecord(_Strict):
        decision_id: str; revision: int = 1; title; context; decision: str; consequences
        source_status: Literal["unknown","proposed","accepted","rejected","deprecated","superseded"] = "unknown"
        origin: Literal["documented", "inferred"]
        review_status: Literal["unreviewed", "accepted", "rejected"] = "unreviewed"
        evidence: list[EvidenceRef]; links: list[DecisionLink]; review_history: list[ReviewEvent]
        generation: GenerationInfo | None; content_fingerprint: str = ""

- path: `packages/ai-parrot/src/parrot/knowledge/wiki/decisions/models.py`
  lines: 107-114
  symbol: `EvidenceRef`
  excerpt: |
    class EvidenceRef(_Strict): ... source_sha1: str = Field(..., min_length=1)

- path: `packages/ai-parrot/src/parrot/knowledge/wiki/decisions/models.py`
  lines: 149-170
  symbol: `ReviewEvent / GenerationInfo`
  excerpt: |
    class ReviewEvent(_Strict): revision: int; before_sha1: str; after_sha1: str
    class GenerationInfo(_Strict): input_sha1: str

- path: `packages/ai-parrot/src/parrot/knowledge/wiki/decisions/models.py`
  lines: 299-303
  symbol: `ReviewRequest`
  excerpt: |
    class ReviewRequest(_Strict):
        """An attributed, revision-checked review action."""
        expected_revision: int = Field(..., ge=1)

## Notes

ADRs are wiki pages (`adr:` prefix) — "ADR filter by domain tag" would need either wiki tags or `links` to component pages.
