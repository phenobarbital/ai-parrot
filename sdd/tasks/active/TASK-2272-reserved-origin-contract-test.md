# TASK-2272: Reserved-origin contract test — no policy may emit `L2_*`

**Feature**: FEAT-435 — GraphIndex Retrieval Layer
**Spec**: `sdd/specs/graphindex-retriever.spec.md`
**Status**: pending
**Priority**: medium
**Estimated effort**: S
**Depends-on**: TASK-2271
**Assigned-to**: unassigned
**Spec task ref**: T2b (spec §10)

---

## Context

Spec §3.2 / OQ-6. `EvidenceOrigin` widens the union pre-emptively for the
cross-corpus bridge, and the spec states plainly: "Emitting a reserved origin is
a contract violation, caught in tests." This task is that test.

It is small but load-bearing: it is the only thing stopping a future policy
author from quietly using `L2_DOC` because it was already in the enum, which
would silently make bundles from that policy incompatible with the bridge spec
before the bridge spec exists.

---

## Scope

- A parametrised test over **every** member of the `RetrievalPolicy` union that
  asserts no emitted `Evidence.origin` is in the reserved set.
- Parametrisation must be **derived from the union**, not a hand-written list,
  so a policy added later is automatically covered and cannot skip the gate.
  Use `typing.get_args` on the annotated union.
- A second test asserting the reserved set itself is exactly
  `{L2_DOC, L2_NORM, L2_EXTERNAL}` — so widening the reservation is a
  deliberate, visible edit.
- A module-level constant `RESERVED_ORIGINS` in the source package (not the
  test) that both the test and any future admission check can import.

**NOT in scope**:

- Implementing any policy. This task tests whatever policies exist; with only
  TASK-2280/2281 landed it covers those two, and grows automatically.
- Runtime enforcement in `assemble` — the spec asks for a *test*, not a
  validator. Do not add a runtime check that costs latency on every unit.

---

## Files to Create / Modify

- `packages/ai-parrot/src/parrot/knowledge/retrieval/models.py` — add `RESERVED_ORIGINS: frozenset[EvidenceOrigin]`.
- `packages/ai-parrot/tests/knowledge/retrieval/test_reserved_origins.py` — new.

---

## Codebase Contract (Anti-Hallucination)

Verified on `dev` @ `bfa056bc7`, 2026-08-20. Spec §14 holds the full contract;
this is the slice this task needs. **Re-verify before you rely on it** — run
the greps yourself if anything looks stale.

### Verified Imports

```python
from typing import get_args
from parrot.knowledge.retrieval.models import EvidenceOrigin, RESERVED_ORIGINS
```

### Existing Signatures to Use

```python
# parrot/knowledge/retrieval/models.py  (TASK-2271)
class EvidenceOrigin(StrEnum):
    L0_SOURCE = "l0_source"; L1_WIKI = "l1_wiki"; L1_RATIONALE = "l1_rationale"
    L2_DOC = "l2_doc"; L2_NORM = "l2_norm"; L2_EXTERNAL = "l2_external"
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
- **The `RetrievalPolicy` union may not be complete yet.** In the v1 cut only
  `DirectSymbolPolicy` (TASK-2280) and `VectorSeedPolicy` (TASK-2281) exist.
  Write the parametrisation so an empty or partial union still yields a passing,
  meaningful test — do NOT hardcode six policy names that do not exist.

---

## Implementation Notes

### Pattern to Follow

Derive the policy list at collection time:

```python
POLICIES = [p for p in get_args(get_args(RetrievalPolicy)[0])]  # unwrap Annotated
@pytest.mark.parametrize("policy_cls", POLICIES, ids=lambda c: c.__name__)
```

If the union is a bare union rather than `Annotated[...]` at the time you write
this, unwrap accordingly — assert the list is non-empty so the test cannot
silently pass by covering nothing.

### Key Constraints

- **Frozen Pydantic v2 everywhere**: `model_config = ConfigDict(frozen=True,
  extra="forbid")`. Every model in spec §3 declares this; match it.
- **Google-style docstrings + strict type hints** on every public function and
  class (project rule, `CLAUDE.md`).
- `self.logger = logging.getLogger(__name__)` — never `print`.
- `async`/`await` throughout; `aiosqlite` for SQLite, never blocking `sqlite3`.
- No `requests`/`httpx` — `aiohttp` only (project rule).

### References in Codebase

- Spec §3.2 (`EvidenceOrigin` docstring, RESERVED semantics), §9 OQ-6,
  §13 acceptance criteria.

---

## Acceptance Criteria

- [ ] Test is parametrised from the union via `get_args`, not a literal list.
- [ ] Test asserts the derived policy list is non-empty (cannot vacuously pass).
- [ ] Adding a policy class to the union requires no test edit to be covered.
- [ ] `RESERVED_ORIGINS` lives in source, imported by the test.
- [ ] `ruff` + `mypy` clean.

---

## Test Specification

```python
# packages/ai-parrot/tests/knowledge/retrieval/test_reserved_origins.py
def test_reserved_set_is_exactly_the_l2_members(): ...
def test_policy_list_is_non_empty(): ...

@pytest.mark.parametrize("policy_cls", POLICIES, ids=...)
async def test_policy_never_emits_reserved_origin(policy_cls, fixture_graph):
    bundle = await run_policy(policy_cls, fixture_graph)
    assert not {u.evidence.origin for u in bundle.units} & RESERVED_ORIGINS
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
