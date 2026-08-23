# TASK-2275: Pin coherence check + `IndexPinMismatchError` (OQ-7)

**Feature**: FEAT-435 — GraphIndex Retrieval Layer
**Spec**: `sdd/specs/graphindex-retriever.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M
**Depends-on**: TASK-2274
**Assigned-to**: unassigned
**Spec task ref**: T1c (spec §10)

---

## Context

Spec §3.5.3. The other half of OQ-7 "derive, don't store", and the most subtle
task in the v1 cut — read §3.5.3 in full before starting.

**The problem.** L0 does not record the rev it was built from. So a pin cannot
be *verified* against the index, only *corroborated*. Worse: stored line spans
were computed at index time, so a pin far from the index's build rev can point a
span at the wrong code — silently.

**The resolution.** Content is read **at the pinned rev** (not from the working
tree), so served bytes and `Evidence.digest` always agree with the pin. Index
correspondence is corroborated by hashing a bounded sample of the `files` table
at the pinned rev and comparing to the stored `sha1`.

The spec states the residual weakness plainly and so must your docstring: a
sampled check can false-pass. This is strictly weaker than storing the build rev
in L0, and it is the accepted price of keeping L0 read-only.

---

## Scope

- `read_at_rev(repo_path, rev, path) -> bytes` via
  `git cat-file blob <rev>:<path>`. All content served by any policy flows
  through here, so `Evidence.digest` (TASK-2273) hashes bytes that provably
  match the pin.
- `check_pin_coherence(pin, persistence, *, sample: int = 16) -> CoherenceReport`:
  sample up to `sample` rows of the `files` table, hash each path's content at
  the pinned rev **with the same hash function the builder used** (sha1 — match
  it exactly, do not "upgrade" to sha256 here), compare to the stored `sha1`.
- `IndexPinMismatchError` in `exceptions.py`.
- Behaviour on mismatch: raise `IndexPinMismatchError`, **unless**
  `budget.allow_stale` is true, in which case return a report that sets
  `ContextBundle.index_pin_mismatch = True`.
- `pin_verification_sample` as config, default 16. Sampling must be
  **deterministic** given the same pin (sort paths, take a stable stride) so
  INV-3-style replay of a request is reproducible.
- Docstring must state the false-pass limitation and name the one-column L0 fix
  that would remove it.

**NOT in scope**:

- Exhaustive verification. §3.5.3 explicitly rejects it: O(files) git calls per
  request. Bounded sample only.
- Adding a rev column to the `files` table. That is the L0 change §1.2 forbids,
  and the whole point of this task is to avoid it.
- Digest computation itself — TASK-2273.

---

## Files to Create / Modify

- `packages/ai-parrot/src/parrot/knowledge/retrieval/pin.py` — extend.
- `packages/ai-parrot/src/parrot/knowledge/retrieval/exceptions.py` — add `IndexPinMismatchError`.
- `packages/ai-parrot/tests/knowledge/retrieval/test_pin_coherence.py` — new.

---

## Codebase Contract (Anti-Hallucination)

Verified on `dev` @ `bfa056bc7`, 2026-08-20. Spec §14 holds the full contract;
this is the slice this task needs. **Re-verify before you rely on it** — run
the greps yourself if anything looks stale.

### Verified Imports

```python
from parrot.knowledge.retrieval.pin import WorkspacePin           # TASK-2274
from parrot.knowledge.retrieval.exceptions import StalePinError   # TASK-2274
```

### Existing Signatures to Use

```python
# parrot/knowledge/graphindex/persist_sqlite.py
class SQLitePersistence:
    def _db_path(self, ctx: TenantContext) -> Path                # :161
    #   NOTE: partitioned by TENANT, not by repo
    async def is_stale(self, ctx, source_uri: str,
                       mtime: float, sha1: str) -> bool           # :463
    #   reads: SELECT mtime, sha1 FROM files WHERE source_uri = ?
    #   "sha1: SHA-1 hex digest of the current file content."     # :483
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
- **No stored index rev.** No `build_rev`, `indexed_at_rev`, or git SHA anywhere
  in the schema. This absence is the entire premise of the task.
- **The `files` table is per-tenant, not per-repo** (`_db_path(ctx)`). A
  multi-repo workspace shares one tenant DB and distinguishes files only by
  `source_uri`. Do not assume a repo column.
- **`git hash-object` is not directly comparable to the stored `sha1`.** Git's
  blob SHA hashes `"blob <len>\0" + content`; the builder stores a plain SHA-1
  of file content. Read the content via `git cat-file blob` and hash it
  yourself with the builder's function — do NOT compare against
  `git rev-parse <rev>:<path>`.

---

## Implementation Notes

### Pattern to Follow

That last "Does NOT Exist" bullet is the trap this task exists to avoid: the
obvious implementation — compare the stored `sha1` to `git rev-parse
<rev>:<path>` — is wrong, silently, because the two hash different byte strings.
Verify the builder's hashing call site before you write the comparison, and add
a test with a real git fixture that would fail if you got it backwards.

### Key Constraints

- **Frozen Pydantic v2 everywhere**: `model_config = ConfigDict(frozen=True,
  extra="forbid")`. Every model in spec §3 declares this; match it.
- **Google-style docstrings + strict type hints** on every public function and
  class (project rule, `CLAUDE.md`).
- `self.logger = logging.getLogger(__name__)` — never `print`.
- `async`/`await` throughout; `aiosqlite` for SQLite, never blocking `sqlite3`.
- No `requests`/`httpx` — `aiohttp` only (project rule).
- `git cat-file` via `asyncio.create_subprocess_exec`; batch where practical
  (`git cat-file --batch`) since the sample is up to 16 paths.
- Deterministic sampling — no `random` without a fixed seed derived from the
  pin, or replay breaks.

### References in Codebase

- Spec §3.5.3 (the whole subsection), §3.4 failure modes, §14.3.

---

## Acceptance Criteria

- [ ] A drifted pin (index built from rev A, pin at rev B with a changed file)
      raises `IndexPinMismatchError`.
- [ ] The same drift under `allow_stale=True` does NOT raise and sets
      `index_pin_mismatch` on the report.
- [ ] A coherent pin passes with no error.
- [ ] Comparison uses content hashed with the builder's function, verified by a
      test that would fail if `git rev-parse <rev>:<path>` were used instead.
- [ ] Sampling is deterministic: two runs on the same pin sample the same paths.
- [ ] Sample size is bounded — assert the git-call count is ≤ `sample`.
- [ ] `ruff` + `mypy` clean.

---

## Test Specification

```python
# packages/ai-parrot/tests/knowledge/retrieval/test_pin_coherence.py
async def test_coherent_pin_passes(git_fixture_with_index): ...
async def test_drifted_pin_raises(git_fixture_with_index): ...
async def test_drifted_pin_allow_stale_sets_marker(...): ...
async def test_blob_sha_vs_content_sha_not_confused(...): ...
async def test_sampling_is_deterministic(...): ...
async def test_git_call_count_bounded_by_sample(...): ...
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

Implemented `read_at_rev()`, `CoherenceReport`, and `check_pin_coherence()`
in `pin.py` (extended), plus `IndexPinMismatchError` in `exceptions.py`
(extended). Confirmed the sha1 hashing trap named in the task's Codebase
Contract by reading the actual builder call site
(`extractors/code.py:124`: `hashlib.sha1(source_bytes).hexdigest()` — a
plain content hash) and wrote `test_blob_sha_vs_content_sha_not_confused`,
which asserts `git rev-parse <rev>:<path>` (git's blob SHA, which hashes
`"blob <len>\0" + content`) differs from the plain content sha1, then
verifies the coherence check passes using the correct one.

**Signature extension (documented, not silently invented):** the task's
literal pseudocode signature is
`check_pin_coherence(pin, persistence, *, sample: int = 16) -> CoherenceReport`.
Implemented as
`check_pin_coherence(pin, persistence, ctx, repo, repo_path, *, sample=16, allow_stale=True)`
— `ctx: TenantContext` and `repo_path: Path` are required to actually
resolve the tenant's SQLite db file (`persistence._db_path(ctx)`, per this
task's own Codebase Contract) and to run `git cat-file` in the right
repository; `repo` disambiguates which `WorkspacePin` entry to corroborate
in a multi-repo workspace. Added `allow_stale: bool = True` directly on
the function (rather than threading a `RetrievalBudget` through, which
doesn't exist as a dependency here) so the raise-vs-report-marker behavior
described in Scope is enforced at a single call site instead of split
across caller and callee.

Deterministic sampling: `_select_deterministic_sample()` takes a stable
stride over the `files` table sorted by `source_uri` — no `random`, same
pin always samples the same paths (verified by
`test_sampling_is_deterministic`).

**Test output:**
```
$ pytest packages/ai-parrot/tests/knowledge/retrieval/ -v
======================== 51 passed, 6 warnings in 2.41s ========================
```

**Lint:**
```
$ ruff check packages/ai-parrot/src/parrot/knowledge/retrieval/ packages/ai-parrot/tests/knowledge/retrieval/
All checks passed!
```

**Mypy:** zero errors attributable to `knowledge/retrieval`.

**Completed by**: sdd-worker (Claude Sonnet)
**Date**: 2026-08-20
