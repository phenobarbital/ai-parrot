---
id: F043
query_id: Q006
type: wiki_page
intent: "ADR subsystem overview: models, status lifecycle, service, toolkit"
executed_at: 2026-10-30T16:47:12Z
duration_ms: 400
parent_id: null
depth: 0
merged_from: [FW-006-adr-decisions-plane]
---

# F043 — A full ADR "decision plane" exists (FEAT-578/540): `DecisionRecord` with `source_status` in {proposed, accepted, rejected, deprecated, superseded}, evidence refs hashed by `source_sha1`, `DecisionService.why()/for_symbol()`, bounded candidate generation + attributed review

## Summary

`parrot/knowledge/wiki/decisions/` has 16 modules: `models.py` (strict Pydantic: `DecisionRecord` with `source_status` Literal `unknown|proposed|accepted|rejected|deprecated|superseded`, `review_status`, `origin` documented|inferred, `EvidenceRef` with `rel_path/start_line/end_line/source_sha1`, `DecisionLink` relations `explains|supported_by|supersedes`), `ingest.py` (ADR discovery from `docs/adr/**`, `docs/adrs/**`, `docs/decisions/**` globs, idempotent refresh), `service.py` (`DecisionService.why(question)`, `for_symbol(symbol)` → `DecisionDossier` with `documented` vs `candidates`, freshness `current|stale|missing|unverified` by re-hashing evidence; `HISTORICAL_STATUSES` hidden by default; zero LLM calls on read), `generation.py` (bounded `CandidateBatch` via `AbstractClient.invoke`, off by default), `review.py` (`ReviewRequest` accept/reject/revise/link, revision-checked, attributed), `render.py` (budgeted dossier packing), `toolkit.py`/`tools.py` (agent-facing tools; MCP `wiki_decision_why`, `wiki_decisions_for_symbol`), `cli.py` (`wikitoolkit adr`).

## Citations

- path: `packages/ai-parrot/src/parrot/knowledge/wiki/decisions/models.py`
  lines: 1-120
  symbol: `DecisionRecord`
  wiki_page_id: file:packages/ai-parrot/src/parrot/knowledge/wiki/decisions/models.py
  score: 0.89
  excerpt: |
    class DecisionRecord(_Strict):
        decision_id: str; revision: int = 1
        source_status: Literal["unknown","proposed","accepted","rejected","deprecated","superseded"] = "unknown"
        origin: Literal["documented", "inferred"]
        review_status: Literal["unreviewed", "accepted", "rejected"] = "unreviewed"
        evidence: list[EvidenceRef]; links: list[DecisionLink]; review_history: list[ReviewEvent]

- path: `packages/ai-parrot/src/parrot/knowledge/wiki/decisions/models.py`
  symbol: `DecisionConfig`
  wiki_page_id: file:packages/ai-parrot/src/parrot/knowledge/wiki/decisions/models.py
  score: 0.89
  excerpt: |
    adr_globs: list[str] = ["docs/adr/**/*.md", "docs/adrs/**/*.md", "docs/decisions/**/*.md"]
    generation_enabled: bool = False
    max_input_tokens: int = 12_000; max_candidates: int = 3

- path: `packages/ai-parrot/src/parrot/knowledge/wiki/decisions/service.py`
  symbol: `DecisionService.why` / `DecisionService.for_symbol`
  wiki_page_id: file:packages/ai-parrot/src/parrot/knowledge/wiki/decisions/service.py
  score: 0.89
  excerpt: |
    HISTORICAL_STATUSES = frozenset({"rejected", "deprecated", "superseded"})
    async def for_symbol(self, symbol, *, include_history=False, limit=10, budget_tokens=3000) -> DecisionDossier
    async def why(self, question, *, include_history=False, limit=10, budget_tokens=3000) -> DecisionDossier
    # _group_rank: documented+current+accepted first

- path: `packages/ai-parrot/src/parrot/knowledge/wiki/decisions/`
  symbol: `(16 modules: cli, codec, evidence, factory, generation, ingest, models, operations, parser, render, repository, review, service, toolkit, tools)`
  wiki_page_id: dir:packages/ai-parrot/src/parrot/knowledge/wiki/decisions
  score: 0.89
  excerpt: |
    ingest.py — ADR discovery and idempotent source refresh (FEAT-578 Module 3)
    generation.py — Bounded candidate generation (FEAT-578 Module 5)
    review.py — Attributed, revision-checked review transforms

## Notes

The source's "ADR como consumidor y productor" maps 1:1: consume = `DecisionService.why()/for_symbol()` filtered to `source_status == "accepted"` with a token budget (already supports `budget_tokens`); produce = `generate()` yields `origin="inferred"` candidates whose `source_status` is forced to `"unknown"` until human review — the "nace en proposed, solo el gate lo acepta" rule exists with different vocabulary (`review_status`). Filtering is by symbol/file link or token overlap — there is NO tag/component filter on records today (`DecisionRecord` has no `tags` field).
