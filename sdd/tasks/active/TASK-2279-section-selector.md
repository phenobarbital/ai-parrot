# TASK-2279: `SectionSelector` derivation from `QueryClass`

**Feature**: FEAT-435 — GraphIndex Retrieval Layer
**Spec**: `sdd/specs/graphindex-retriever.spec.md`
**Status**: pending
**Priority**: medium
**Estimated effort**: S
**Depends-on**: TASK-2278
**Assigned-to**: unassigned
**Spec task ref**: T4b (spec §10)

---

## Context

Spec §6.1 (retrieval args) + OQ-5. This is where §4's taxonomy "pays off a
second time": the classifier supplies a section selector, so a hot module never
produces an unusable 8k-token page — because nobody ever asks for the whole
page.

`SectionSelector` is on the retrieval path, which is why T9's section model
moved *into* the v1 cut while the policy that consumes it (T10) stayed out
(§10). This task is small but it is a core contract, not a convenience.

---

## Scope

- `SectionKind(StrEnum)`: `OVERVIEW CONTRACTS RATIONALE USAGE GOTCHAS
  DEPENDENCIES`.
- `SectionSelector` (frozen, `extra="forbid"`): `include: tuple[SectionKind,
  ...]`, `max_tokens_per_section: int = 1_200`,
  `fill_order: tuple[SectionKind, ...]`.
- `selector_for(query_class: QueryClass) -> SectionSelector`, with the two
  mappings §6.1 states explicitly:
  - `RATIONALE` → `(RATIONALE, OVERVIEW)`
  - `GLOBAL_SUMMARY` → `(OVERVIEW, CONTRACTS, DEPENDENCIES)`
  and a documented, sensible default for the remaining classes.
- `fill_order` drives greedy fill when the budget is tight — default it to
  `include` order unless a class needs otherwise.
- **`GOTCHAS` is a filter over existing L0** (RQ-4): rationale nodes whose
  `domain_tags["tag"]` is in `{{HACK, TODO, FIXME, XXX}}`, while `NOTE`/`WHY`
  route to `RATIONALE`. Encode that tag partition here as a constant so T9 and
  a future T10 share one definition.

**NOT in scope**:

- `WikiSection`/`WikiPage` themselves — TASK-2283.
- Any policy that consumes the selector (`AncestrySummaryPolicy`,
  `RationalePolicy`) — both deferred to v1.1.
- Generating section bodies. No LLM call in this task.

---

## Files to Create / Modify

- `packages/ai-parrot/src/parrot/knowledge/retrieval/sections.py` — new (`SectionKind`, `SectionSelector`,
  `selector_for`, the tag partition constant).
- `packages/ai-parrot/tests/knowledge/retrieval/test_sections.py` — new.

---

## Codebase Contract (Anti-Hallucination)

Verified on `dev` @ `bfa056bc7`, 2026-08-20. Spec §14 holds the full contract;
this is the slice this task needs. **Re-verify before you rely on it** — run
the greps yourself if anything looks stale.

### Verified Imports

```python
from parrot.knowledge.retrieval.classifier import QueryClass   # TASK-2278
```

### Existing Signatures to Use

```python
# parrot/knowledge/graphindex/extractors/code.py — the GOTCHAS source of truth
_DEFAULT_TAGS: set[str] = {"NOTE", "WHY", "HACK", "TODO", "FIXME", "XXX"}  # :29
#   each tagged comment becomes ONE NodeKind.RATIONALE node with
#   domain_tags={"tag": tag} and an EdgeKind.EXPLAINS edge to the nearest
#   enclosing symbol (:494-512)
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
- **`SectionKind` is NOT `WikiPageCategory`.** `parrot/knowledge/wiki/
  models.py` defines `WikiPageCategory` (SUMMARY, ENTITY, CONCEPT, COMPARISON,
  OVERVIEW, SYNTHESIS, ANSWER, ARCHIVE) — Karpathy's *page-type* taxonomy for
  FEAT-260. It is a **different, orthogonal** taxonomy. The two coexist (spec
  §14.3). Do not import it, do not "unify" them, do not map one onto the other.
- **No commit-message or diff source for `GOTCHAS`.** `extractors/` has only
  `code`, `llm`, `loader`, `odoo_code`, `skill` — no VCS-history extractor
  exists (RQ-4). Comments only.

---

## Implementation Notes

### Pattern to Follow

Keep `selector_for` a plain dict lookup with an explicit default — it is on
the hot path and must not grow logic. Put the tag partition in this module (not
in T9's) so there is exactly one place defining which tags are gotchas and which
are rationale; T9 imports it.

### Key Constraints

- **Frozen Pydantic v2 everywhere**: `model_config = ConfigDict(frozen=True,
  extra="forbid")`. Every model in spec §3 declares this; match it.
- **Google-style docstrings + strict type hints** on every public function and
  class (project rule, `CLAUDE.md`).
- `self.logger = logging.getLogger(__name__)` — never `print`.
- `async`/`await` throughout; `aiosqlite` for SQLite, never blocking `sqlite3`.
- No `requests`/`httpx` — `aiohttp` only (project rule).

### References in Codebase

- Spec §6.1 (SectionSelector, the two stated mappings), §9 OQ-5, §9.1 RQ-4,
  §14.3 (the `WikiPageCategory` distinction).

---

## Acceptance Criteria

- [ ] `RATIONALE` → `(RATIONALE, OVERVIEW)` exactly.
- [ ] `GLOBAL_SUMMARY` → `(OVERVIEW, CONTRACTS, DEPENDENCIES)` exactly.
- [ ] Every `QueryClass` member has a selector (no `KeyError` possible) —
      parametrised over the enum.
- [ ] Tag partition: `{HACK, TODO, FIXME, XXX}` → gotchas;
      `{NOTE, WHY}` → rationale; union equals `code.py:29`'s `_DEFAULT_TAGS`,
      asserted against the real constant so drift is caught.
- [ ] `ruff` + `mypy` clean.

---

## Test Specification

```python
# packages/ai-parrot/tests/knowledge/retrieval/test_sections.py
def test_rationale_class_selector(): ...
def test_global_summary_class_selector(): ...
@pytest.mark.parametrize("qc", list(QueryClass))
def test_every_query_class_has_a_selector(qc): ...
def test_tag_partition_covers_l0_default_tags():
    from parrot.knowledge.graphindex.extractors.code import _DEFAULT_TAGS
    assert GOTCHA_TAGS | RATIONALE_TAGS == _DEFAULT_TAGS
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

*(Agent fills this in when done — include real command output, not claims.)*

**Completed by**:
**Date**:
