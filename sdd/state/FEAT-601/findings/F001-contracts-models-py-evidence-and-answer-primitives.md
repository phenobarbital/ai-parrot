---
id: F001
query_id: Q001
type: read
intent: Ground Evidence, Extracted[T], FieldProvenance, ContractVersion, Citation, AnswerProvenance, ContractAnswer + _check_kind_invariants, derive_provenance, AnswerKind, MAX_QUOTE_CHARS; generic vs contract-specific.
executed_at: 2026-09-24T00:00:00Z
duration_ms: 0
parent_id: null
depth: 0
---

# F001 — contracts/models.py evidence and answer primitives

## Summary
`Evidence`, `Extracted[T]`, `FieldProvenance`, `trim_quote`, `MAX_QUOTE_CHARS=300`, `UNSUBSTANTIATED_CONFIDENCE_CAP=0.5` and the `ProvenanceOrigin`/`VerificationState` literals contain nothing about contracts, so a ManualCard can import them directly. `ContractVersion`, `Citation` (required `contract_id`), `ContractAnswer` (with `HandoffBrief`) and the `AnswerKind` literal are tied to contracts. A manual needs its own versions with `manual_id` and its own answer kinds, e.g. a safety-refusal kind instead of `interpretation_required`. `derive_provenance` is generic logic, but its signature takes the contract `Citation`. `TocEntry` is re-exported from `..bookstore.models`.

## Citations
- path: `packages/ai-parrot/src/parrot/knowledge/contracts/models.py`
  lines: 88-106
  symbol: `MAX_QUOTE_CHARS` / `trim_quote`
  excerpt: |
    MAX_QUOTE_CHARS = 300
    def trim_quote(value: Any) -> Any:
        if not isinstance(value, str) or len(value) <= MAX_QUOTE_CHARS:
            return value
        cut = value[:MAX_QUOTE_CHARS]
- path: `packages/ai-parrot/src/parrot/knowledge/contracts/models.py`
  lines: 160-175
  symbol: `ProvenanceOrigin` / `AnswerKind` / `AnswerProvenance`
  excerpt: |
    VerificationState = Literal["extracted", "verified", "stale"]
    ProvenanceOrigin = Literal["llm", "rule", "manual"]
    AnswerKind = Literal["lookup","interpretation_required","not_found","out_of_scope","denied",]
    AnswerProvenance = Literal["verified", "mixed", "extracted"]
- path: `packages/ai-parrot/src/parrot/knowledge/contracts/models.py`
  lines: 205-229
  symbol: `Evidence`
  excerpt: |
    node_id: str = Field(..., min_length=1)
    quote: str = Field(default="", max_length=MAX_QUOTE_CHARS)
    page: Optional[int] = Field(default=None, ge=1)
    def substantiates(self) -> bool: return bool(self.quote.strip())
- path: `packages/ai-parrot/src/parrot/knowledge/contracts/models.py`
  lines: 235-262
  symbol: `Extracted`
  excerpt: |
    class Extracted(BaseModel, Generic[T]):
        value: Optional[T] = None
        evidence: Optional[Evidence] = None
        confidence: float = Field(default=0.0, ge=0.0, le=1.0)
        # _cap_unsubstantiated_confidence caps at 0.5 without a quote
- path: `packages/ai-parrot/src/parrot/knowledge/contracts/models.py`
  lines: 265-311
  symbol: `FieldProvenance`
  excerpt: |
    origin: ProvenanceOrigin = "llm"
    verification: VerificationState = "extracted"
    node_id / page / quote / confidence / verified_by / verified_at
    derived_from: list[str]; candidate: Optional[Any]
    _check_axes: verified requires verified_by+verified_at; rule requires derived_from
- path: `packages/ai-parrot/src/parrot/knowledge/contracts/models.py`
  lines: 417-475
  symbol: `ContractVersion`
  excerpt: |
    n: int; revision: int; valid_from/valid_to: Optional[date]
    kind: VersionKind = "original"; amended_by: Optional[str]
    source_sha256: str; card_snapshot: dict; evidence_ref: Optional[str]
    def in_force(self, as_of: date) -> bool
- path: `packages/ai-parrot/src/parrot/knowledge/contracts/models.py`
  lines: 701-737
  symbol: `Citation`
  excerpt: |
    contract_id: str = Field(..., min_length=1)
    node_id: str; quote: str = Field(..., min_length=1, max_length=MAX_QUOTE_CHARS)
    page; verification; version_n: int; source_sha256: str
    def key(self) -> tuple[str, str]: return (self.contract_id, self.node_id)
- path: `packages/ai-parrot/src/parrot/knowledge/contracts/models.py`
  lines: 750-797
  symbol: `ContractAnswer._check_kind_invariants`
  excerpt: |
    if kind == "lookup": requires answer text + >=1 citation, no handoff
    elif kind == "interpretation_required": requires handoff, no answer
    else: no answer, no citations, no handoff
    self.provenance = derive_provenance(self.citations)
- path: `packages/ai-parrot/src/parrot/knowledge/contracts/models.py`
  lines: 800-818
  symbol: `derive_provenance`
  excerpt: |
    if not citations: return "extracted"
    verified = sum(1 for c in citations if c.verification == "verified")
    if verified == len(citations): return "verified"
    if verified: return "mixed"
- path: `packages/ai-parrot/src/parrot/knowledge/contracts/models.py`
  lines: 22
  symbol: `TocEntry` (import)
  excerpt: |
    from ..bookstore.models import TocEntry

## Notes
- Generic, import as-is: `Evidence`, `Extracted`, `FieldProvenance`, `trim_quote`, `MAX_QUOTE_CHARS`, `UNSUBSTANTIATED_CONFIDENCE_CAP` (L111), `VerificationState`, `ProvenanceOrigin`, `AnswerProvenance`.
- Needs changes or copying:
  - `Citation`: has a `contract_id` field and a `(contract_id, node_id)` retirement key.
  - `ContractVersion`: its `VersionKind` values (amendment/renewal/restatement) and effective-date interval are contract ideas. A manual has a revision or edition instead.
  - `ContractAnswer`/`AnswerKind`/`HandoffBrief`.
- Suggestion: move the generic primitives into a shared `knowledge/evidence_models` module rather than having manuals import from `contracts`.
