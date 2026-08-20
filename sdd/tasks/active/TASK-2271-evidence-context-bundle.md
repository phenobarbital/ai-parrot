# TASK-2271: `Evidence`, `EvidenceOrigin`, `ContextUnit`, `ContextBundle`, `RetrievalBudget`

**Feature**: FEAT-435 — GraphIndex Retrieval Layer
**Spec**: `sdd/specs/graphindex-retriever.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M
**Depends-on**: TASK-2270
**Assigned-to**: unassigned
**Spec task ref**: T2 (spec §10)

---

## Context

Spec §3.2, §3.3. The bundle is the layer's output contract and the carrier of
INV-4 (attribution) and INV-5 (budget honesty). `schema_version: Literal[1]` is
deliberate — §3.2 notes it exists so this model does not repeat the
`EventEnvelope` omission.

`EvidenceOrigin` declares three **RESERVED** `L2_*` members for the future
cross-corpus bridge (OQ-6). They are part of the union now so it is stable, but
no policy may emit them. TASK-2272 enforces that.

---

## Scope

- `EvidenceOrigin(StrEnum)`: `L0_SOURCE`, `L1_WIKI`, `L1_RATIONALE`, plus
  RESERVED `L2_DOC`, `L2_NORM`, `L2_EXTERNAL`. Document the reservation in the
  docstring exactly as §3.2 words it.
- `Evidence`: `node: NodeRef`, `digest: str`, `digest_scope` (from T2c — accept
  a plain `str` now and tighten to the enum when TASK-2273 lands, or import if
  already merged), `line_span: tuple[int, int] | None`,
  `edge_path: tuple[EdgeRef, ...] = ()`, `origin: EvidenceOrigin`,
  `score: float`.
- `ContextUnit`: `text: str`, `evidence: Evidence`, `token_estimate: int`.
- `ContextBundle`: `schema_version: Literal[1] = 1`, `units: tuple[...]`,
  `decision: RetrievalRoutingDecision` (forward ref — keep it `Any`-typed or a
  `TYPE_CHECKING` import until TASK-2278 lands), `truncated: bool`,
  `stale_sources: tuple[NodeRef, ...] = ()`, `token_total: int`,
  `elapsed_ms: float`, plus `mixed_freshness: bool = False` (RQ-2) and
  `index_pin_mismatch: bool = False` (§3.5.3) and
  `boundary_truncation: bool = False` (§5.3.1).
- `RetrievalBudget`: `deadline_ms=800`, `max_tokens=12_000`, `max_llm_calls=0`,
  `max_expansion_nodes=400`, `allow_stale=True`.
- `RetrievalRequest`: `query`, `workspace: WorkspacePin` (forward ref until
  TASK-2274), `budget`, `policy_override`.
- `score` docstring MUST record that it is policy-local and **not comparable
  across policies** (§3.2).

**NOT in scope**:

- The reserved-origin contract test — TASK-2272.
- Computing `digest`/`line_span` values — TASK-2273. This task defines the
  field; it does not populate it.
- `RetrievalRoutingDecision` itself — TASK-2278.

---

## Files to Create / Modify

- `packages/ai-parrot/src/parrot/knowledge/retrieval/models.py` — extend.
- `packages/ai-parrot/tests/knowledge/retrieval/test_models.py` — extend.

---

## Codebase Contract (Anti-Hallucination)

Verified on `dev` @ `bfa056bc7`, 2026-08-20. Spec §14 holds the full contract;
this is the slice this task needs. **Re-verify before you rely on it** — run
the greps yourself if anything looks stale.

### Verified Imports

```python
from parrot.knowledge.retrieval.models import NodeRef, EdgeRef   # TASK-2270
```

### Existing Signatures to Use

```python
# parrot/knowledge/retrieval/models.py  (TASK-2270, this repo)
class NodeRef(BaseModel):   # frozen, extra="forbid"
    repo: str; rev: str; path: str
    kind: NodeKind; symbol_type: str | None; qualname: str
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
- **No `EventEnvelope` to inherit or mimic for versioning.** §3.2's reference to
  it is a cautionary note about a *past omission*, not a pointer to a base
  class. Just declare `schema_version: Literal[1] = 1`.

---

## Implementation Notes

### Pattern to Follow

Use `StrEnum` from `enum` (Python 3.11 — the venv is 3.11, confirmed by the
compiled test artifacts). Tuples not lists for every collection field, so the
models stay hashable and frozen semantics are real rather than nominal.

### Key Constraints

- **Frozen Pydantic v2 everywhere**: `model_config = ConfigDict(frozen=True,
  extra="forbid")`. Every model in spec §3 declares this; match it.
- **Google-style docstrings + strict type hints** on every public function and
  class (project rule, `CLAUDE.md`).
- `self.logger = logging.getLogger(__name__)` — never `print`.
- `async`/`await` throughout; `aiosqlite` for SQLite, never blocking `sqlite3`.
- No `requests`/`httpx` — `aiohttp` only (project rule).
- `ContextBundle` must survive `model_dump_json()` → `model_validate_json()`
  unchanged. §8 requires the decision be fully serializable for offline replay
  with no retrieval re-execution.

### References in Codebase

- Spec §3.2 (Evidence and bundle), §3.3 (request and budget), §8
  (observability / replay requirement).
- RQ-2 for `mixed_freshness`; §3.5.3 for `index_pin_mismatch`.

---

## Acceptance Criteria

- [ ] All five models frozen with `extra="forbid"`.
- [ ] `ContextBundle` round-trips through JSON with `schema_version` preserved.
- [ ] `EvidenceOrigin` has exactly six members, three documented as RESERVED.
- [ ] `RetrievalBudget` defaults match §3.3 exactly (800 / 12_000 / 0 / 400 /
      True).
- [ ] `ruff` + `mypy` clean.

---

## Test Specification

```python
# packages/ai-parrot/tests/knowledge/retrieval/test_models.py
def test_bundle_json_round_trip_preserves_schema_version(): ...
def test_budget_defaults_match_spec(): ...
def test_evidence_origin_members_and_reserved_docstring(): ...
def test_all_models_frozen_and_forbid_extra(): ...
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
