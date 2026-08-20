# TASK-2270: `NodeRef` + `parrot-graph://` URI parse/serialize

**Feature**: FEAT-435 — GraphIndex Retrieval Layer
**Spec**: `sdd/specs/graphindex-retriever.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M
**Depends-on**: none
**Assigned-to**: unassigned
**Spec task ref**: T1 (spec §10)

---

## Context

Spec §3.1. `NodeRef` is the identity primitive for the whole retrieval layer:
every `Evidence`, every `WikiPage.scope`, every resolved anchor is one. It must
round-trip losslessly through the `parrot-graph://` URI form so a bundle can be
serialized, replayed offline (§8) and cited in a trace.

The spec's original draft said `kind` reuses an L0 enum with
`Module|Class|Function|Rationale` members. **It does not** — verified against
`graphindex/schema.py`. The real `NodeKind` has a single `SYMBOL` member and the
module/class/function distinction lives in `domain_tags["symbol_type"]`. §3.1
was corrected to carry both fields; implement the corrected version.

---

## Scope

- Create the `parrot.knowledge.retrieval` package (`__init__.py` exporting the
  public surface as it grows).
- `NodeRef(BaseModel)`, frozen + `extra="forbid"`, fields: `repo: str`,
  `rev: str`, `path: str`, `kind: NodeKind`, `symbol_type: str | None`,
  `qualname: str`.
- `NodeRef.uri` property producing
  `parrot-graph://{repo}@{rev}/{path}#{kind}:{qualname}`.
- `NodeRef.parse(uri: str) -> NodeRef` classmethod, the exact inverse.
- **Reject symbolic revs** at validation time: `HEAD`, `head`, `main`, `dev`,
  `staging`, anything that is not a hex SHA of length 7–40. §3.1 says `rev` is
  "a concrete SHA, never a symbolic ref" — enforce it in the model, not in a
  caller.
- `EdgeRef` (used by `Evidence.edge_path` in T2): `source: NodeRef`,
  `target: NodeRef`, `kind: EdgeKind`, `derivation: Literal["ast",
  "package_metadata"]`.

**NOT in scope**:

- `Evidence`/`ContextBundle` — TASK-2271.
- Digest computation — TASK-2273.
- Any symbol *lookup* — TASK-2276. This task defines the identity, not how to
  find it.

---

## Files to Create / Modify

- `packages/ai-parrot/src/parrot/knowledge/retrieval/__init__.py` — new, package root.
- `packages/ai-parrot/src/parrot/knowledge/retrieval/models.py` — new, `NodeRef` + `EdgeRef`.
- `packages/ai-parrot/tests/knowledge/retrieval/__init__.py`, `packages/ai-parrot/tests/knowledge/retrieval/test_models.py` — new.

---

## Codebase Contract (Anti-Hallucination)

Verified on `dev` @ `bfa056bc7`, 2026-08-20. Spec §14 holds the full contract;
this is the slice this task needs. **Re-verify before you rely on it** — run
the greps yourself if anything looks stale.

### Verified Imports

```python
from parrot.knowledge.graphindex.schema import (   # verified: schema.py
    NodeKind, EdgeKind, Provenance, UniversalNode, UniversalEdge,
)
```

### Existing Signatures to Use

```python
# parrot/knowledge/graphindex/schema.py — the ONLY L0 surface this task needs
class NodeKind(str, Enum):
    DOCUMENT = "document"; SECTION = "section"; SYMBOL = "symbol"
    CONCEPT = "concept"; RATIONALE = "rationale"; SKILL = "skill"
    WIKI_PAGE = "wiki_page"; RUN = "run"; CLAIM = "claim"

class EdgeKind(str, Enum):
    CONTAINS REFERENCES DEFINES MENTIONS EXPLAINS EXTENDS PRODUCED ABOUT \
    SUPPORTED_BY CONTRADICTS
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
- **No existing URI helper to reuse.** `parrot-session:/` is built by a
  one-line f-string (`parrot/flows/dev_loop/session_state.py:97`) with no
  parser. There is no URI-scheme framework in this repo; write the parse/format
  pair by hand.

---

## Implementation Notes

### Pattern to Follow

Mirror the frozen-model style already used across spec §3 and the
`dev_loop/session_state.py` action models. For the round-trip test, use
`hypothesis` (already a dev dependency) with a strategy that generates valid
component strings, including paths with `/` and qualnames with `.` — those are
the characters that break naive splitting. Split `path` from `#` on the LAST
`#`, and `repo` from `rev` on the LAST `@`, so paths containing those
characters survive.

### Key Constraints

- **Frozen Pydantic v2 everywhere**: `model_config = ConfigDict(frozen=True,
  extra="forbid")`. Every model in spec §3 declares this; match it.
- **Google-style docstrings + strict type hints** on every public function and
  class (project rule, `CLAUDE.md`).
- `self.logger = logging.getLogger(__name__)` — never `print`.
- `async`/`await` throughout; `aiosqlite` for SQLite, never blocking `sqlite3`.
- No `requests`/`httpx` — `aiohttp` only (project rule).

### References in Codebase

- Spec §3.1 (URI scheme), §14.2 (verified `NodeKind`/`EdgeKind`).
- `parrot/flows/dev_loop/session_state.py:95-97` — the `parrot-session:/`
  precedent this scheme is consistent with.

---

## Acceptance Criteria

- [ ] `NodeRef.parse(ref.uri) == ref` for all generated inputs (property test).
- [ ] Symbolic revs (`HEAD`, `main`, `dev`) raise `ValidationError`.
- [ ] A path containing `#` or `@` still round-trips.
- [ ] Model is frozen: attribute assignment raises; `extra="forbid"` rejects an
      unknown field.
- [ ] `pytest packages/ai-parrot/tests/knowledge/retrieval/test_models.py -v`
      green; `ruff` + `mypy` clean.

---

## Test Specification

```python
# packages/ai-parrot/tests/knowledge/retrieval/test_models.py
from hypothesis import given, strategies as st

@given(st.builds(...))  # valid component strategy
def test_uri_round_trip(ref): assert NodeRef.parse(ref.uri) == ref

def test_rejects_symbolic_rev():
    for bad in ("HEAD", "main", "dev", "staging", "v1.0"):
        with pytest.raises(ValidationError): NodeRef(rev=bad, ...)

def test_path_with_hash_and_at_round_trips(): ...
def test_frozen_and_extra_forbid(): ...
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
