# TASK-2274: `WorkspacePin` + admission-time pin resolution + `StalePinError`

**Feature**: FEAT-435 — GraphIndex Retrieval Layer
**Spec**: `sdd/specs/graphindex-retriever.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M
**Depends-on**: TASK-2270
**Assigned-to**: unassigned
**Spec task ref**: T1b (spec §10)

---

## Context

Spec §3.4 (and OQ-1). Retrieval is point-in-time: HEAD is resolved to a
concrete SHA once, at admission, and pinned for the whole request — for every
repo in the workspace, not just one. A `dev_loop` session holds its pin for the
session's lifetime; HEAD moving underneath does not change results.

The reducer precedent already exists: `dev_loop/session_state.py` has a
discriminated union of action classes (`:397+`) and the `parrot-session:/`
channel scheme (`:97`). `RefreshWorkspace` follows that model but is new.

---

## Scope

- `WorkspacePin`: `primary: str`, `pins: Mapping[str, str]`,
  `pinned_at: datetime`, `weight_table_version: str`, plus
  `package_map_version: str | None = None` (RQ-1).
- `rev_of(repo) -> str`, raising a clear error for an unpinned repo.
- Real frozen semantics: `pins` must be immutable and the whole model hashable
  and cacheable (§3.4 says "validated to `frozen` semantics"). Coerce the input
  mapping to an immutable form in a validator — a bare `Mapping` annotation
  does not stop a `dict` being mutated by the caller.
- `resolve_workspace(refs: Mapping[str, str]) -> WorkspacePin`: per repo,
  `git rev-parse --verify <ref>^{{commit}}` → concrete SHA.
- `StalePinError` — raised when a pinned SHA is unreachable (force-push, branch
  delete, GC). §3.4: fail loudly, **never** silently fall back to HEAD.
- Warn on the trace when `pinned_at` is older than `stale_pin_warning_days`
  (config, default 7).

**NOT in scope**:

- The index-coherence check and `IndexPinMismatchError` — TASK-2275.
- Reading file content at a rev — TASK-2275.
- `RefreshWorkspace` as a `dev_loop` reducer action — that is a `dev_loop`
  change, out of scope here. This task provides the immutable value the reducer
  would swap in.

---

## Files to Create / Modify

- `packages/ai-parrot/src/parrot/knowledge/retrieval/pin.py` — new.
- `packages/ai-parrot/src/parrot/knowledge/retrieval/exceptions.py` — new, `StalePinError`.
- `packages/ai-parrot/tests/knowledge/retrieval/test_pin.py` — new.

---

## Codebase Contract (Anti-Hallucination)

Verified on `dev` @ `bfa056bc7`, 2026-08-20. Spec §14 holds the full contract;
this is the slice this task needs. **Re-verify before you rely on it** — run
the greps yourself if anything looks stale.

### Verified Imports

```python
from parrot.knowledge.retrieval.models import NodeRef   # TASK-2270
```

### Existing Signatures to Use

```python
# parrot/flows/dev_loop/session_state.py — the precedent to follow
def session_channel(run_id: str) -> str:            # :95-97
    return f"parrot-session:/{run_id}"
class _DispatchAction(_ActionBase): ...              # :397  discriminated union
class DispatchQueued(_DispatchAction): ...           # :401
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
- **`RefreshWorkspace` does not exist.** No reducer action by that name is in
  `dev_loop/session_state.py`. Do not import it.
- **L0 does not record the rev it was indexed at.** There is no `rev` column,
  no `build_rev`, nothing. Do not look for one — TASK-2275 works around its
  absence deliberately.
- **`asyncdb` is not needed here.** Pin resolution is git, not a database.

---

## Implementation Notes

### Pattern to Follow

Shell out to git with `asyncio.create_subprocess_exec` (never
`subprocess.run` — no blocking I/O in async paths, project rule). Use
`git rev-parse --verify <ref>^{commit}`: the `^{commit}` suffix and `--verify`
together make an unreachable or non-commit ref exit non-zero instead of echoing
the input back, which is exactly the failure `StalePinError` must catch.

### Key Constraints

- **Frozen Pydantic v2 everywhere**: `model_config = ConfigDict(frozen=True,
  extra="forbid")`. Every model in spec §3 declares this; match it.
- **Google-style docstrings + strict type hints** on every public function and
  class (project rule, `CLAUDE.md`).
- `self.logger = logging.getLogger(__name__)` — never `print`.
- `async`/`await` throughout; `aiosqlite` for SQLite, never blocking `sqlite3`.
- No `requests`/`httpx` — `aiohttp` only (project rule).
- `pinned_at` must be timezone-aware UTC. A naive datetime here would make the
  `stale_pin_warning_days` comparison ambiguous.

### References in Codebase

- Spec §3.4 (WorkspacePin, pin lifecycle, both failure modes), §9 OQ-1,
  RQ-1 for `package_map_version`.
- `parrot/flows/dev_loop/session_state.py:95-97, 397+`.

---

## Acceptance Criteria

- [ ] `WorkspacePin` is hashable; `pins` cannot be mutated after construction.
- [ ] `rev_of("unknown-repo")` raises a clear, typed error.
- [ ] An unreachable SHA raises `StalePinError` — and does NOT resolve to HEAD.
- [ ] Symbolic input refs resolve to concrete SHAs that pass `NodeRef`'s rev
      validation from TASK-2270.
- [ ] Git is invoked via `asyncio.create_subprocess_exec`, not `subprocess`.
- [ ] `ruff` + `mypy` clean.

---

## Test Specification

```python
# packages/ai-parrot/tests/knowledge/retrieval/test_pin.py
def test_pin_is_hashable_and_pins_immutable(): ...
async def test_resolve_workspace_returns_concrete_shas(tmp_git_repo): ...
async def test_unreachable_sha_raises_stale_pin_error(tmp_git_repo): ...
def test_rev_of_unpinned_repo_raises(): ...
async def test_uses_async_subprocess_not_blocking(monkeypatch): ...
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
