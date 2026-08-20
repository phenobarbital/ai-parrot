# TASK-2273: `DigestScope` + derived digest computation (OQ-7)

**Feature**: FEAT-435 — GraphIndex Retrieval Layer
**Spec**: `sdd/specs/graphindex-retriever.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M
**Depends-on**: TASK-2271
**Assigned-to**: unassigned
**Spec task ref**: T2c (spec §10)

---

## Context

Spec §3.5.1. This is half of the OQ-7 "derive, don't store" decision and the
only reason INV-2 is evaluable at all.

**Why this task exists:** L0 records digests only per *file*
(`SQLitePersistence.is_stale(ctx, source_uri, mtime, sha1)`), and
`UniversalNode` has no digest field. Rather than change L0 — which spec §1.2
forbids — digests are computed at request time over the bytes actually served.
That makes INV-2 closure true by construction for the returned unit instead of
a claim about an index field.

Not every node has a span, so the granularity is **declared** rather than
assumed. That honesty is the point: a `FILE`-scoped digest invalidates more
coarsely, and the evidence says so.

---

## Scope

- `DigestScope(StrEnum)`: `SPAN`, `FILE`, `SUMMARY`.
- `derive_digest(node: UniversalNode, *, source_bytes: bytes | None,
  file_sha1: str | None) -> tuple[str, DigestScope]`:
  - `SPAN` when `domain_tags` carries both `lineno` and `end_lineno` →
    `sha256` of exactly those source lines.
  - `FILE` when there is no span but a file exists → reuse the `files`-table
    `sha1`. Applies to `RATIONALE` nodes (they carry only
    `domain_tags["tag"]`) and module nodes.
  - `SUMMARY` when there is no file at all → `sha256` of `title + summary`.
    Applies to `CONCEPT` / `WIKI_PAGE`.
- A span reader that returns the exact byte range for a 1-indexed inclusive
  `(lineno, end_lineno)` pair — matching how `code.py` emits them
  (`start_point[0] + 1`).
- Tighten `Evidence.digest_scope` to the enum (TASK-2271 left it loose).

**NOT in scope**:

- Reading content *at a pinned rev* — TASK-2275 owns `git cat-file`. This task
  takes bytes it is given and hashes them.
- Section-level invalidation — TASK-2283 consumes this.
- **Do NOT "fix" the missing rationale linenos.** That is a one-line L0 change
  in `extractors/code.py:500`, deliberately out of scope (§1.2, RQ-4). Emit
  `FILE` scope for those nodes and move on; when L0 is fixed they upgrade with
  no change here.

---

## Files to Create / Modify

- `packages/ai-parrot/src/parrot/knowledge/retrieval/digest.py` — new.
- `packages/ai-parrot/src/parrot/knowledge/retrieval/models.py` — tighten `Evidence.digest_scope` to `DigestScope`.
- `packages/ai-parrot/tests/knowledge/retrieval/test_digest.py` — new.

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
# parrot/knowledge/graphindex/extractors/code.py — where spans come from
#   class node   :296-299  domain_tags={"symbol_type": "class",
#                            "lineno": node.start_point[0] + 1,
#                            "end_lineno": node.end_point[0] + 1}
#   function     :365-369  same + "qualified_name"
#   RATIONALE    :500      domain_tags={"tag": tag}   # <-- NO lineno at all
#
# parrot/knowledge/graphindex/persist_sqlite.py
class SQLitePersistence:
    async def is_stale(self, ctx: TenantContext, source_uri: str,
                       mtime: float, sha1: str) -> bool          # :463
    #   the `files` table holds (source_uri, mtime, sha1) — FILE granularity
#
# parrot/knowledge/graphindex/sqlite_reader.py
class SQLiteGraphReader:
    @staticmethod
    def _read_span(path: Path, lineno: int, end: int) -> Optional[str]  # :404
    #   private; read it for the 1-indexed inclusive convention, do not import
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
- **There is no node-level digest to read.** Do not look for
  `node.digest`, `node.content_hash`, or a `digests` table. The only stored
  hash is the per-file `sha1` in the `files` table.
- **`stable_edge_id()` is not a content digest.** `schema.py:122` hashes
  `"source::target::kind"` into a 12-char citation handle for *edges*. Unrelated
  to this task; do not reuse it.
- **`RATIONALE` nodes have no `lineno`.** Verified at `code.py:500`. Any code
  path assuming they do will crash on real data.

---

## Implementation Notes

### Pattern to Follow

`_read_span` in `sqlite_reader.py:404` is private, so do not import it — but
read it first and copy its line-indexing convention exactly, so a `SPAN` digest
covers the same bytes the retriever will later serve as `ContextUnit.text`. A
mismatch between "bytes hashed" and "bytes served" would silently break INV-2
while every test still passed.

### Key Constraints

- **Frozen Pydantic v2 everywhere**: `model_config = ConfigDict(frozen=True,
  extra="forbid")`. Every model in spec §3 declares this; match it.
- **Google-style docstrings + strict type hints** on every public function and
  class (project rule, `CLAUDE.md`).
- `self.logger = logging.getLogger(__name__)` — never `print`.
- `async`/`await` throughout; `aiosqlite` for SQLite, never blocking `sqlite3`.
- No `requests`/`httpx` — `aiohttp` only (project rule).
- `sha256` for derived digests (not `sha1`) — new code, no compatibility
  constraint, and `sha1` is only kept where L0 already uses it.
- Pure function, no I/O: the caller supplies bytes. That keeps it trivially
  testable and lets TASK-2275 decide *where* bytes come from.

### References in Codebase

- Spec §3.5.1 (`DigestScope`), INV-2 as amended in §2, RQ-4, §14.2/§14.3.

---

## Acceptance Criteria

- [ ] Changing a line **inside** the span changes the `SPAN` digest.
- [ ] Changing a line **outside** the span does NOT change it.
- [ ] A `RATIONALE` node yields `DigestScope.FILE` and never raises for the
      missing `lineno`.
- [ ] A `CONCEPT` node with no `source_uri` yields `DigestScope.SUMMARY`.
- [ ] `derive_digest` performs no file or network I/O (assert by patching
      `open` and `Path.read_bytes` to raise).
- [ ] `ruff` + `mypy` clean.

---

## Test Specification

```python
# packages/ai-parrot/tests/knowledge/retrieval/test_digest.py
def test_span_digest_sensitive_to_inside_edit(): ...
def test_span_digest_insensitive_to_outside_edit(): ...
def test_rationale_node_falls_back_to_file_scope(): ...
def test_concept_node_uses_summary_scope(): ...
def test_derive_digest_does_no_io(monkeypatch): ...
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
