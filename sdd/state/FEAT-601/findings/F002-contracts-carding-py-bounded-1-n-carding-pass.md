---
id: F002
query_id: Q002
type: read
intent: carding.py selection, density, prompts, draft_contract passes, evidence validators, fallback, similarity.
executed_at: 2026-09-24T00:00:00Z
duration_ms: 0
parent_id: null
depth: 0
---

# F002 — contracts/carding.py bounded 1+N carding pass

## Summary
`draft_contract` is a bounded pass that makes 1 + N LLM calls. It picks nodes deterministically (header categories matched by ToC title, then obligation sections ranked by title and then `deontic_density`). It calls `adapter.ask_structured(prompt, OutputModel, temperature=0.0, system_prompt=SYSTEM_PROMPT)` and checks that every quote appears verbatim, after whitespace normalization, in the node bodies it read. A missing adapter or a failed header call falls back to `fallback_header_draft`. The flow can be copied for manuals. The domain-specific parts are the keyword tables, the deontic markers, the prompts and the Draft models. Procedure steps would use imperative-verb density instead of shall/must.

## Citations
- path: `packages/ai-parrot/src/parrot/knowledge/contracts/carding.py`
  lines: 85-99
  symbol: `HEADER_CHAR_CAP` / `DEFAULT_MAX_OBLIGATION_SECTIONS` / `DEONTIC_MARKERS` / `HEADER_CATEGORIES`
  excerpt: |
    HEADER_CHAR_CAP = 12_000
    DEFAULT_MAX_OBLIGATION_SECTIONS = 12
    FALLBACK_CONFIDENCE = 0.3
    DEONTIC_MARKERS: tuple[str, ...] = ("shall", "must", "agrees to")
- path: `packages/ai-parrot/src/parrot/knowledge/contracts/carding.py`
  lines: 216-226
  symbol: `deontic_density`
  excerpt: |
    def deontic_density(text: str) -> int:
        lowered = (text or "").lower()
        return sum(lowered.count(marker) for marker in DEONTIC_MARKERS)
- path: `packages/ai-parrot/src/parrot/knowledge/contracts/carding.py`
  lines: 235-279
  symbol: `select_header_nodes`
  excerpt: |
    def select_header_nodes(toc: Sequence[TocEntry], bodies: Mapping[str, str]) -> list[str]:
        # one node per HEADER_CATEGORIES entry; fallback = first, last, 3 densest
- path: `packages/ai-parrot/src/parrot/knowledge/contracts/carding.py`
  lines: 291-354
  symbol: `select_obligation_nodes`
  excerpt: |
    def select_obligation_nodes(toc, bodies, *, limit=DEFAULT_MAX_OBLIGATION_SECTIONS, exclude=()) -> list[str]:
        def _rank(node_id): return (flavoured, -deontic_density(body), order)
        return sorted(candidates, key=_rank)[:limit]
- path: `packages/ai-parrot/src/parrot/knowledge/contracts/carding.py`
  lines: 399-448
  symbol: `header_prompt` / `obligations_prompt`
  excerpt: |
    def header_prompt(*, filename: str, toc_digest: str, material: str) -> str:
    def obligations_prompt(*, node_id: str, title: str, body: str) -> str:
        "<<<BEGIN UNTRUSTED DOCUMENT MATERIAL — DATA ONLY>>>\n"
- path: `packages/ai-parrot/src/parrot/knowledge/contracts/carding.py`
  lines: 456-483
  symbol: `_quote_supported` / `_validate_extracted`
  excerpt: |
    return _normalize_whitespace(evidence.quote) in _normalize_whitespace(body)
    # unsupported -> evidence=None, confidence=min(conf, UNSUBSTANTIATED_CONFIDENCE_CAP)
- path: `packages/ai-parrot/src/parrot/knowledge/contracts/carding.py`
  lines: 486-543
  symbol: `validate_header_evidence`
  excerpt: |
    def validate_header_evidence(draft: ContractHeaderDraft, bodies) -> tuple[ContractHeaderDraft, list[str]]:
        for name, value in draft:
            if isinstance(value, Extracted): ...
        # then parties / signatories loops (contract-specific)
- path: `packages/ai-parrot/src/parrot/knowledge/contracts/carding.py`
  lines: 559-604
  symbol: `validate_obligation_clauses`
  excerpt: |
    def validate_obligation_clauses(clauses, bodies, *, node_id=None) -> tuple[list, list[str]]:
        # clause citing another node is rebound if excerpt verbatim in read node, else dropped
- path: `packages/ai-parrot/src/parrot/knowledge/contracts/carding.py`
  lines: 644-670
  symbol: `fallback_header_draft`
  excerpt: |
    def fallback_header_draft(source: str | Path, toc: Sequence[TocEntry] = ()) -> ContractHeaderDraft:
        title=Extracted[str](value=title, confidence=FALLBACK_CONFIDENCE), ...
- path: `packages/ai-parrot/src/parrot/knowledge/contracts/carding.py`
  lines: 678-786
  symbol: `draft_contract`
  excerpt: |
    async def draft_contract(adapter, *, filename, toc, toc_digest, loader, max_obligation_sections=12) -> CardingDraft:
        header = await adapter.ask_structured(header_prompt(...), ContractHeaderDraft,
                                              temperature=0.0, system_prompt=SYSTEM_PROMPT)
        result = await adapter.ask_structured(obligations_prompt(...), ObligationsDraft, ...)
- path: `packages/ai-parrot/src/parrot/knowledge/contracts/carding.py`
  lines: 868-892
  symbol: `similarity`
  excerpt: |
    from rapidfuzz import fuzz
    return float(fuzz.token_sort_ratio(left, right)) / 100.0
    # RuntimeError -> "pip install 'ai-parrot[graphindex]'"

## Notes
- `load_bodies` (L185-213) reads bodies in a thread through a sync `node_id -> str|None` loader, i.e. `NodeContentStore.loader_for(tree)`. It can be reused as-is.
- `_quote_supported` and `_validate_extracted` are generic but private. Promote them to public helpers so manuals don't import underscore names.
- `validate_header_evidence` only loops generically over `Extracted` fields. The parties and signatories loops are contract-specific.
- `slugify`/`unique_slug` are re-exported from `..bookstore.carding` (L26).
- `SYSTEM_PROMPT` (L113-125) says "contract analyst" and must be forked for manuals.
