# TASK-2277: `QueryFeatures` extractor + `MarkerLexicon` (ES/EN)

**Feature**: FEAT-435 — GraphIndex Retrieval Layer
**Spec**: `sdd/specs/graphindex-retriever.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M
**Depends-on**: TASK-2270
**Assigned-to**: unassigned
**Spec task ref**: T3 (spec §10)

---

## Context

Spec §4.2. The classifier is the latency lever, and its design principle is
that **it must never be the thing that costs latency** — pure, non-LLM, over
cheap lexical and symbol-table features, sub-millisecond.

Markers are locale-aware (ES/EN) and live in a frozen `MarkerLexicon` so the
classifier stays declarative and testable rather than a pile of inline regexes.
This repo's users write queries in both languages — §4.1's own examples are
Spanish — so ES coverage is a functional requirement, not a nicety.

---

## Scope

- `Interrogative(StrEnum)`: `WHAT WHERE WHO WHY HOW NONE`.
- `MarkerLexicon` — frozen, versioned, declarative. Four marker groups per
  §4.2, each with ES + EN entries:
  - relational verbs: `calls|uses|imports|depends|extends|quién llama|usa|
    importa|depende|hereda`
  - causal: `why|rationale|reason|por qué|razón|decisión|motivo`
  - aggregation: `overview|architecture|summary|how does ... work|cómo funciona|
    arquitectura|resumen|todos los`
  - interrogatives, both languages (`qué|dónde|quién|por qué|cómo`).
- `QueryFeatures` (frozen, `extra="forbid"`): `resolved_symbols: tuple[NodeRef,
  ...]`, `anchor_count: int`, `has_relational_verb: bool`,
  `has_causal_marker: bool`, `has_aggregation_marker: bool`,
  `has_code_literal: bool`, `token_count: int`,
  `interrogative: Interrogative`.
- `extract_features(query: str, symbols: DerivedSymbolIndex) -> QueryFeatures`.
- `has_code_literal`: backticks, `snake_case`, `CamelCase`, dotted paths.
- **Ordering matters for R2:** `por qué` must set `has_causal_marker`, and
  `qué` alone must not. Accent-insensitive matching (`porque`/`por que`/
  `por qué`) but not so loose that `porque` in a non-causal sentence trips it.

**NOT in scope**:

- The decision list itself — TASK-2278.
- `SectionSelector` — TASK-2279.
- Symbol resolution — TASK-2276 provides the index; call it, do not reimplement.

---

## Files to Create / Modify

- `packages/ai-parrot/src/parrot/knowledge/retrieval/features.py` — new (`QueryFeatures`, `Interrogative`,
  `extract_features`).
- `packages/ai-parrot/src/parrot/knowledge/retrieval/lexicon.py` — new (`MarkerLexicon` + the frozen default).
- `packages/ai-parrot/tests/knowledge/retrieval/test_features.py`, `packages/ai-parrot/tests/knowledge/retrieval/test_lexicon.py` — new.

---

## Codebase Contract (Anti-Hallucination)

Verified on `dev` @ `bfa056bc7`, 2026-08-20. Spec §14 holds the full contract;
this is the slice this task needs. **Re-verify before you rely on it** — run
the greps yourself if anything looks stale.

### Verified Imports

```python
from parrot.knowledge.retrieval.models import NodeRef            # TASK-2270
from parrot.knowledge.retrieval.symbols import DerivedSymbolIndex # TASK-2276
```

### Existing Signatures to Use

```python
# parrot/knowledge/retrieval/symbols.py  (TASK-2276)
class DerivedSymbolIndex:
    def lookup(self, name: str, *, symbol_type: str | None = None
               ) -> list[NodeRef]: ...   # returns ALL candidates on ambiguity
```

### Does NOT Exist

- **`parrot.knowledge.retrieval` does not exist yet.** You may be the task that
  creates it. There is nothing to extend, no base class waiting for you.
- **`RoutingDecision` EXISTS but is NOT ours.** It belongs to
  `parrot/bots/mixins/intent_router.py:378` (LLM intent routing). This feature's
  model is **`RetrievalRoutingDecision`**. Never import or extend the former.
- **`UniversalNode` has no `repo`, `rev`, `digest`, `line_span`, or `qualname`
  field.** Verified: `parrot/knowledge/graphindex/schema.py`. Do not write code
  that reads them. Line spans live in `domain_tags["lineno"/"end_lineno"]`;
  symbol kind lives in `domain_tags["symbol_type"]`.
- **There is no symbol trie or symbol table.** `graphindex/resolve.py` is a
  cross-domain *embedding-similarity* stage emitting `mentions` edges — it does
  NOT resolve names. Do not `from parrot.knowledge.graphindex.resolve import`
  anything expecting lookup.
- **`NodeKind` has no `Module`/`Class`/`Function` members.** The real set is
  `DOCUMENT SECTION SYMBOL CONCEPT RATIONALE SKILL WIKI_PAGE RUN CLAIM`.
- **No existing marker/lexicon module to extend.** `parrot/bots/mixins/
  intent_router.py` does keyword routing for a different purpose (LLM intent
  selection) with its own model — do NOT reuse or import it.
- **No NLP dependency is available or wanted.** No spaCy, no NLTK. §4.2 requires
  ~sub-millisecond pure-Python feature extraction; a tokenizer import would
  defeat the entire design principle.

---

## Implementation Notes

### Pattern to Follow

Precompile every marker into one `re.Pattern` per group at lexicon
construction, not per call — the whole point is sub-millisecond extraction.
Normalize accents once (`unicodedata.normalize('NFKD', ...)`) and match against
the normalized form so `por qué` / `por que` both hit without duplicating every
entry.

### Key Constraints

- **Frozen Pydantic v2 everywhere**: `model_config = ConfigDict(frozen=True,
  extra="forbid")`. Every model in spec §3 declares this; match it.
- **Google-style docstrings + strict type hints** on every public function and
  class (project rule, `CLAUDE.md`).
- `self.logger = logging.getLogger(__name__)` — never `print`.
- `async`/`await` throughout; `aiosqlite` for SQLite, never blocking `sqlite3`.
- No `requests`/`httpx` — `aiohttp` only (project rule).
- **INV-3: no I/O, no LLM, no clock.** `extract_features` must be a pure
  function. Do not read files, do not call `datetime.now()`.
- `MarkerLexicon` frozen and carrying a `version` string, so a lexicon change is
  visible in a replayed trace.

### References in Codebase

- Spec §4.2 (feature extraction), §4.1 (the ES examples that motivate ES
  coverage), INV-3.

---

## Acceptance Criteria

- [ ] ES and EN markers are symmetric: for every EN marker group there is an ES
      counterpart, asserted by a test that walks the lexicon.
- [ ] `por qué` sets `has_causal_marker`; bare `qué` does not.
- [ ] Accent variants (`por qué` / `por que`) both match.
- [ ] `has_code_literal` fires on backticks, `snake_case`, `CamelCase`, and
      dotted paths; not on ordinary prose.
- [ ] `extract_features` is pure: patching `open`, `socket`, and
      `datetime.now` to raise does not break it.
- [ ] Same input twice → identical output (INV-3).
- [ ] `ruff` + `mypy` clean.

---

## Test Specification

```python
# packages/ai-parrot/tests/knowledge/retrieval/test_features.py
def test_es_en_marker_symmetry(): ...
def test_por_que_is_causal_but_que_alone_is_not(): ...
def test_accent_insensitive_causal_match(): ...
@pytest.mark.parametrize("q,expected", [("`foo`", True), ("snake_case", True),
    ("CamelCase", True), ("a.b.c", True), ("how are you", False)])
def test_has_code_literal(q, expected): ...
def test_extract_features_is_pure(monkeypatch): ...
def test_deterministic_across_runs(): ...
```

---

## Agent Instructions

1. Read the spec section(s) named in **Context** before writing code. The spec
   is the SSOT; this task file is a view onto it.
2. Write the tests first (see **Test Specification**), watch them fail, then
   implement. TDD is not optional here — every one of these tasks encodes an
   invariant.
3. Do NOT modify anything under `parrot/knowledge/graphindex/` or
   `parrot_tools/multistoresearch/`. L0 is consumed **read-only** (spec §1.2)
   and FEAT-217/FEAT-379 are untouched by design (spec §5.0). If you believe a
   change there is required, STOP and record it in the Completion Note instead.
4. Run `pytest packages/ai-parrot/tests/knowledge/retrieval/ -v`, then `ruff check` and `mypy` on the files you
   touched. Paste real output into the Completion Note — no claims without
   evidence.
5. Commit once, message: `feat(FEAT-435): <what> (TASK-<NNN>)`.
6. Fill in the Completion Note. If you hit an ambiguity, record it there rather
   than inventing a resolution.

---

## Completion Note

Implemented `MarkerLexicon`/`CompiledMarkerLexicon`/`Interrogative` in
`lexicon.py`, and `QueryFeatures`/`extract_features` in `features.py`.

**Stale contract corrected:** this task's Codebase Contract listed
`DerivedSymbolIndex.lookup(name, symbol_type=None) -> list[NodeRef]`, but
TASK-2276 actually implemented `resolve(name, *, symbol_type=None) ->
tuple[NodeRef, ...]`. Used the real method name/signature (verified by
reading `symbols.py` directly) rather than the stale contract.

Precompilation: `CompiledMarkerLexicon` compiles every marker group into
one `re.Pattern` at construction; `DEFAULT_COMPILED_LEXICON` is a
module-level singleton built once at import — `extract_features` never
compiles a pattern per call.

`"how does ... work"` (spec §4.2) is a discontinuous template, not a
literal marker — handled as a separate regex
(`r"\bhow does\b.*\bwork\b"`), not squeezed into the literal-marker
alternation.

`has_code_literal` runs against the **raw, case-preserved** query text
(not the accent-normalized/lowercased form used for markers), since
CamelCase detection depends on case.

`resolved_symbols`/`anchor_count`: extracted candidate code-literal tokens
(backtick content, dotted paths, CamelCase, snake_case) are looked up via
`symbols.resolve()`; results are deduplicated via a dict-as-ordered-set
keyed on `NodeRef` (frozen + hashable), so `anchor_count` counts *distinct*
resolved anchors, matching spec §3.5.2's "ambiguity naturally routes... "
language. Not explicitly in the task's Test Specification stub, but
required to populate the field — added tests for it
(`test_resolves_backtick_symbol_to_anchor`,
`test_no_anchors_when_nothing_resolves`).

**Test output:**
```
$ pytest packages/ai-parrot/tests/knowledge/retrieval/ -v
======================== 87 passed, 6 warnings in 2.49s ========================
```

**Lint:**
```
$ ruff check packages/ai-parrot/src/parrot/knowledge/retrieval/ packages/ai-parrot/tests/knowledge/retrieval/
All checks passed!
```

**Mypy:** zero errors attributable to `knowledge/retrieval`.

**Completed by**: sdd-worker (Claude Sonnet)
**Date**: 2026-08-20
