# TASK-2641: resolve_plane_root — worktree-aware wiki plane resolution

**Feature**: FEAT-484 — ReadOnlyRepoToolkit — Safe Repo Grounding for Any Client
**Spec**: `sdd/specs/readonly-repo-toolkit.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-2637
**Assigned-to**: unassigned

---

## Context

Implements spec §3 **Module 4** (plane-resolution half) and §8 **Q5**.

This task exists as its own unit because it solves a specific, easy-to-get-wrong
problem: **the wiki plane is 548 MB and rooted at a checkout, but this feature's
first consumer runs inside a git worktree.**

The naive behavior — resolve `.parrot/wiki` relative to `repo_root` — means a
worktree either finds no plane at all (and every `search_code` degrades to grep,
silently destroying the feature's whole value proposition) or triggers a
half-gigabyte rebuild per worktree. Neither is acceptable.

The fix, per spec §2 and §8 Q5: when `repo_root` is a worktree, resolve the **main
checkout** via `git rev-parse --path-format=absolute --git-common-dir` and query
*its* plane. `WikiProjectConfig.storage_dir` already supports this — `project.py:74`
documents that it "may be absolute, so two repositories can share one".

The accepted tradeoff, which the docs must state (TASK-2643): the partner sees the
repo at roughly last-commit state. `git_*` (TASK-2640) and `read_file` (TASK-2638)
cover uncommitted edits. Spec §2 notes this is right for *research* and would be
wrong for a *reviewer* — a distinction worth preserving if the toolkit is reused.

This task deliberately ships **no tool**. It is infrastructure that TASK-2642
consumes. Keeping it separate means the worktree logic gets tested against a real
`git worktree add` without a wiki plane, a search, or an LLM in the picture.

---

## Scope

- Create `parrot/tools/repo/graph_search.py`.
- Implement `resolve_plane_root(repo_root: Path) -> Path` — returns the checkout
  whose plane should be queried:
  - Run `git rev-parse --path-format=absolute --git-common-dir` in `repo_root`.
  - In a **worktree**, `--git-common-dir` points at the **main** checkout's `.git`
    directory; its parent is the main checkout.
  - In a **plain checkout**, it points at `<repo_root>/.git`; parent is `repo_root`.
  - Not a git repo, `git` missing, or the command fails → return `repo_root`
    unchanged. Never raise.
- Implement `open_plane(repo_root: Path) -> tuple[object | None, str]` — returns
  `(store, wiki_name)` or `(None, reason)`:
  - Resolve the plane root, load the wiki project config, check `is_built()`,
    and open the store. **Never build.**
  - Return `None` plus a human-readable reason on any failure.
- Write unit tests in `test_graph_search.py` covering both resolution paths against
  a **real** `git worktree add`.

### Behavior detail

- `resolve_plane_root` is **sync** — it must not become an async public method on
  the toolkit (that would make it an LLM-callable tool). It shells out with
  `subprocess.run`… **no**: see Key Constraints. Use a bounded blocking call
  *inside* `asyncio.to_thread` at the call site, or make these helpers `async` at
  module level (module-level async functions are not toolkit methods, so they are
  safe). Prefer **module-level `async def`** and use
  `asyncio.create_subprocess_exec`, consistent with the rest of the package.
- `open_plane` must **never** trigger a plane build. Spec §1 Non-Goals: "Building or
  refreshing the code graph … This toolkit is a pure consumer". A test asserts no
  build was attempted.
- Honour an **absolute** `storage_dir`: `config.storage_path(root)` already returns
  it unchanged when absolute (`project.py:457`) — pass the resolved plane root and
  let the config decide.

**NOT in scope**:
- `search_code` / `related_code` / result mapping / degradation → TASK-2642.
- Any tool method on `ReadOnlyRepoToolkit` — this task adds **no** tool. Do not
  wire anything into the class yet.
- Building or refreshing the plane — explicitly forbidden.
- Embedders / the vector leg → out of scope for the whole feature (spec §8 Q4).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/tools/repo/graph_search.py` | CREATE | `resolve_plane_root`, `open_plane` |
| `packages/ai-parrot/tests/tools/repo/test_graph_search.py` | CREATE | Unit tests incl. real worktree |
| `packages/ai-parrot/tests/tools/repo/conftest.py` | MODIFY | Add `temp_worktree` fixture |

---

## Codebase Contract (Anti-Hallucination)

> Verified against `dev` on 2026-08-31 by reading the files.

### Verified Imports

```python
from __future__ import annotations

import asyncio
import logging
from pathlib import Path
from typing import Any, Optional

# All four VERIFIED to exist and to be used exactly this way by
# parrot/flows/dev_loop/wiki_search.py:56-62 — copy that import style.
from parrot.knowledge.wiki.project import (
    WikiProjectConfig,
    find_project_root,
    load_project_config,
)
from parrot.knowledge.wiki.store import create_wiki_store
```

### Existing Signatures to Use

```python
# packages/ai-parrot/src/parrot/knowledge/wiki/project.py
class WikiProjectConfig(BaseModel):                                  # line 368
    wiki_name: str = Field(default="codebase")                       # line 401
    storage_dir: str = Field(default=f"{PARROT_DIR}/wiki")           # line 402
    backend: Literal["sqlite", "memory", "arangodb"] = "sqlite"      # line 403

    def storage_path(self, root: Path) -> Path:                      # line 457
        """Resolve the wiki storage directory against the repo root."""
        storage = Path(self.storage_dir)
        return storage if storage.is_absolute() else root / storage
        # ^ VERIFIED BODY. An absolute storage_dir IGNORES `root` entirely —
        #   this is the mechanism spec §8 Q5 relies on (project.py:74).

    def db_path(self, root: Path) -> Path:                           # line 462
        """Path of the SQLite retrieval plane (sqlite backend)."""
        return self.storage_path(root) / "wiki.db"

    def is_built(self, root: Path) -> bool:                          # line 466
        # sqlite   -> self.db_path(root).exists()
        # arangodb -> True (server-hosted, no local artifact)

def find_project_root(start: Path | None = None) -> Path | None       # line 625
def load_project_config(root: Path) -> WikiProjectConfig             # line 652
class WikiConfigError(ValueError)                                    # line 648

# packages/ai-parrot/src/parrot/knowledge/wiki/store.py
def create_wiki_store(                                               # line 1359
    storage_dir: str | Path,
    wiki_name: str = "",
    backend: str = "sqlite",
    **kwargs: Any,
) -> BaseWikiStore: ...
```

### The pattern to copy — VERIFIED WORKING CODE

`packages/ai-parrot/src/parrot/flows/dev_loop/wiki_search.py:39-88` does exactly
this resolution, minus the worktree hop. Read it in full and follow it:

```python
# wiki_search.py:70-83 — verbatim, this is the sequence you need
resolved_root = root or find_project_root()
if resolved_root is None:
    return None
config: WikiProjectConfig = load_project_config(resolved_root)
if not config.is_built(resolved_root):
    logger.debug("Wiki plane not built at %s — wiki search disabled",
                 config.storage_path(resolved_root))
    return None
storage = config.storage_path(resolved_root)
store = create_wiki_store(
    storage, wiki_name=config.wiki_name, backend=config.backend,
)
```

Note its whole-function `try/except Exception -> return None` and its
`except ImportError -> return None` around the wiki imports. Spec §7 tells you to
mirror this best-effort contract: **warn and degrade, never raise.**

### Does NOT Exist

- ~~`parrot.tools.repo.graph_search`~~ — new in this task.
- ~~`resolve_plane_root`~~ / ~~`open_plane`~~ — new in this task.
- ~~`WikiProjectConfig.worktree_root`~~ / ~~`.main_checkout`~~ / ~~`.common_dir`~~ —
  no worktree awareness exists in the wiki config at all. That is the gap this
  task fills.
- ~~`find_project_root` handling worktrees~~ — it walks up to `.parrot/wiki.json`
  or `.git`. In a worktree it finds the **worktree**, which is exactly the wrong
  answer here. Do not rely on it for the plane root; use `--git-common-dir`.
- ~~`git rev-parse --show-toplevel` giving the main checkout~~ — in a worktree it
  gives the **worktree** root. The flag you need is `--git-common-dir`.
- ~~`config.is_built()` building anything~~ — it is a pure file-existence probe for
  sqlite (`project.py:466`). Safe to call. But there is no "build" API you should
  call, and you must not add one.
- ~~`create_wiki_store` returning `None` on a missing plane~~ — it raises. Gate on
  `is_built()` first, and wrap in `try/except`.
- ~~an embedder being available~~ — none is wired (spec §6 last bullet). Do not
  pass one; do not look for one.

### Git facts to rely on (verify once, then trust)

```bash
# In a PLAIN checkout:
git rev-parse --path-format=absolute --git-common-dir   # -> /path/to/repo/.git
# In a WORKTREE at /path/to/repo/.claude/worktrees/wt:
git rev-parse --path-format=absolute --git-common-dir   # -> /path/to/repo/.git
git rev-parse --show-toplevel                           # -> .../worktrees/wt  (WRONG for planes)
# So: plane_root = Path(common_dir).parent  in BOTH cases.
```
`--path-format=absolute` requires git ≥ 2.31. If it is unsupported, fall back to
plain `--git-common-dir` and resolve the (possibly relative) result against
`repo_root`.

---

## Implementation Notes

### Pattern to Follow

```python
async def resolve_plane_root(repo_root: Path) -> Path:
    """Return the checkout whose wiki plane should be queried.

    For a git worktree this is the MAIN checkout, so the (large) plane is
    shared rather than rebuilt per worktree — spec §8 Q5. For a plain
    checkout, and for anything that is not a git repository at all, this is
    ``repo_root`` itself.

    Never raises: a missing ``git``, a non-repo directory, or an unexpected
    git version all fall back to ``repo_root``.

    Args:
        repo_root: The checkout the toolkit is confined to.

    Returns:
        The directory to resolve the wiki project config against.
    """
    root = Path(repo_root).resolve()
    for argv in (
        ["git", "rev-parse", "--path-format=absolute", "--git-common-dir"],
        ["git", "rev-parse", "--git-common-dir"],   # git < 2.31 fallback
    ):
        try:
            proc = await asyncio.create_subprocess_exec(
                *argv,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                cwd=str(root),
            )
            out, _ = await asyncio.wait_for(proc.communicate(), timeout=10)
        except (FileNotFoundError, asyncio.TimeoutError, OSError) as exc:
            logger.debug("resolve_plane_root: %s failed: %s", argv, exc)
            continue
        if proc.returncode != 0:
            continue
        raw = out.decode("utf-8", "replace").strip()
        if not raw:
            continue
        common = Path(raw)
        if not common.is_absolute():
            common = (root / common).resolve()
        plane_root = common.parent
        if plane_root != root:
            logger.info(
                "resolve_plane_root: %s is a worktree — sharing the plane at %s",
                root, plane_root,
            )
        return plane_root
    logger.debug("resolve_plane_root: not a git repo — using %s", root)
    return root
```

`open_plane` then reuses the verified `wiki_search.py` sequence:

```python
async def open_plane(repo_root: Path) -> tuple[Optional[Any], str]:
    """Open the wiki retrieval plane for ``repo_root``, worktree-aware.

    NEVER builds the plane — spec §1 Non-Goals. When the plane is absent,
    unbuilt, or fails to open, returns ``(None, <reason>)`` so the caller can
    degrade with a reason the model can read.

    Returns:
        ``(store, wiki_name)`` on success; ``(None, reason)`` otherwise.
    """
    try:
        plane_root = await resolve_plane_root(repo_root)
        config = load_project_config(plane_root)
        if not config.is_built(plane_root):
            return None, (
                f"wiki plane not built at {config.storage_path(plane_root)}"
            )
        store = create_wiki_store(
            config.storage_path(plane_root),
            wiki_name=config.wiki_name,
            backend=config.backend,
        )
        return store, config.wiki_name
    except ImportError as exc:
        return None, f"wiki modules unavailable: {exc}"
    except Exception as exc:  # noqa: BLE001
        logger.warning("open_plane failed: %s", exc)
        return None, f"wiki plane unavailable: {exc}"
```

### Key Constraints

> **Gotcha — the `dev_loop` grep.** TASK-2642 ships a test asserting the string
> `dev_loop` appears nowhere in `parrot/tools/repo/*.py` (spec §5: "No dev-flow /
> dev-loop import anywhere"). That test greps **raw source**, so a *comment* or
> docstring citing `parrot/flows/dev_loop/wiki_search.py` as a reference will fail
> it just as an import would. Cite that reference in **this task file** and in the
> commit message, not in the shipped source. If you want a pointer in the code,
> write it without the literal token — e.g. "mirrors the best-effort plane-open
> pattern used elsewhere in the codebase (see the feature spec §7)".


- **Module-level `async def`, not toolkit methods.** A public `async def` on
  `ReadOnlyRepoToolkit` becomes an LLM-callable tool (`toolkit.py:537`). These are
  plumbing, not tools. Keeping them in `graph_search.py` at module level sidesteps
  the issue entirely.
- Use `asyncio.create_subprocess_exec` with an argv list. No `shell=True`, no
  blocking `subprocess.run` — the package-wide greps in TASK-2639/2640 check this.
- **Never build the plane.** No call that could write to it. An acceptance
  criterion and a test assert this.
- Never raise. Every failure path returns a value.
- `logging.getLogger(__name__)` at module level (there is no `self` here).
- `from __future__ import annotations`, Google-style docstrings, strict type hints.

### References in Codebase

- `packages/ai-parrot/src/parrot/flows/dev_loop/wiki_search.py:39-88` — **the**
  reference implementation for opening a plane. Read it before writing.
- `packages/ai-parrot/src/parrot/knowledge/wiki/project.py:74` — the comment that
  licenses plane sharing.
- `packages/ai-parrot/src/parrot/knowledge/wiki/project.py:457,466` — verified
  `storage_path` / `is_built` bodies.
- `CLAUDE.md` "Worktree Creation" — how this repo's worktrees are laid out
  (`.claude/worktrees/<name>`), useful when writing the fixture.

---

## Acceptance Criteria

- [ ] `from parrot.tools.repo.graph_search import open_plane, resolve_plane_root` works
- [ ] **Plain checkout**: `resolve_plane_root(temp_repo)` returns `temp_repo`
- [ ] **Real worktree**: with a `git worktree add`-created worktree,
      `resolve_plane_root(worktree)` returns the **main** checkout path, not the
      worktree path
- [ ] **Not a git repo**: returns the input path unchanged, no raise
- [ ] **`git` unavailable**: returns the input path unchanged, no raise
      (simulate by monkeypatching PATH or the subprocess call)
- [ ] `open_plane` returns `(None, reason)` with a non-empty reason when no
      `.parrot/wiki.json` exists — and does **not** raise
- [ ] `open_plane` returns `(None, reason)` when the config exists but
      `is_built()` is `False`
- [ ] `open_plane` returns a store when given a built plane (use a minimal fixture
      plane, or skip if unavailable)
- [ ] **No plane build is ever attempted**: assert no `wiki.db` is created by any
      `open_plane` call against an unbuilt plane, and that the package contains no
      call to a build API
- [ ] `resolve_plane_root` adds **no** tool: `ReadOnlyRepoToolkit(...).get_tools()`
      is unchanged by this task
- [ ] Honours an absolute `storage_dir` (assert `storage_path` is passed through)
- [ ] Tests pass: `pytest packages/ai-parrot/tests/tools/repo/test_graph_search.py -v`
- [ ] Clean: `ruff check` + `mypy` on the package

---

## Test Specification

```python
# packages/ai-parrot/tests/tools/repo/conftest.py   (ADD to the existing file)
import subprocess
import pytest
from pathlib import Path


@pytest.fixture
def temp_worktree(temp_repo: Path, tmp_path: Path) -> Path:
    """A real `git worktree add` off temp_repo — drives plane resolution."""
    wt = tmp_path / "wt"
    subprocess.run(
        ["git", "worktree", "add", "-q", "-b", "wt-branch", str(wt), "HEAD"],
        cwd=temp_repo, check=True,
    )
    return wt
```

```python
# packages/ai-parrot/tests/tools/repo/test_graph_search.py
import json
import pytest
from pathlib import Path

from parrot.tools.repo.graph_search import open_plane, resolve_plane_root


class TestResolvePlaneRoot:
    async def test_plain_checkout_returns_itself(self, temp_repo: Path):
        assert await resolve_plane_root(temp_repo) == temp_repo.resolve()

    async def test_worktree_returns_main_checkout(self, temp_repo, temp_worktree):
        """The whole point of spec §8 Q5: a worktree shares the main plane."""
        got = await resolve_plane_root(temp_worktree)
        assert got == temp_repo.resolve()
        assert got != temp_worktree.resolve()

    async def test_non_git_dir_returns_itself(self, tmp_path: Path):
        plain = tmp_path / "plain"
        plain.mkdir()
        assert await resolve_plane_root(plain) == plain.resolve()

    async def test_git_missing_degrades(self, temp_repo, monkeypatch):
        monkeypatch.setenv("PATH", "/nonexistent")
        assert await resolve_plane_root(temp_repo) == temp_repo.resolve()


class TestOpenPlane:
    async def test_no_config_returns_reason(self, temp_repo: Path):
        store, reason = await open_plane(temp_repo)
        assert store is None
        assert reason  # non-empty, model-readable

    async def test_unbuilt_plane_returns_reason(self, temp_repo: Path):
        (temp_repo / ".parrot").mkdir(exist_ok=True)
        (temp_repo / ".parrot" / "wiki.json").write_text(json.dumps({
            "wiki_name": "test", "backend": "sqlite",
            "storage_dir": ".parrot/wiki",
        }))
        store, reason = await open_plane(temp_repo)
        assert store is None
        assert "not built" in reason.lower() or reason

    async def test_never_builds(self, temp_repo: Path):
        """Spec §1 Non-Goals: this toolkit is a pure consumer."""
        (temp_repo / ".parrot").mkdir(exist_ok=True)
        (temp_repo / ".parrot" / "wiki.json").write_text(json.dumps({
            "wiki_name": "test", "backend": "sqlite",
            "storage_dir": ".parrot/wiki",
        }))
        await open_plane(temp_repo)
        assert not (temp_repo / ".parrot" / "wiki" / "wiki.db").exists()

    async def test_worktree_resolves_to_main_config(
        self, temp_repo, temp_worktree,
    ):
        """A config present ONLY in the main checkout is still found from
        inside the worktree."""
        (temp_repo / ".parrot").mkdir(exist_ok=True)
        (temp_repo / ".parrot" / "wiki.json").write_text(json.dumps({
            "wiki_name": "mainplane", "backend": "sqlite",
            "storage_dir": ".parrot/wiki",
        }))
        store, reason = await open_plane(temp_worktree)
        # Either it opened the main plane, or it reported the MAIN path as
        # unbuilt — never the worktree path.
        assert str(temp_worktree) not in reason


class TestAddsNoTool:
    def test_toolkit_tool_set_unchanged(self, temp_repo: Path):
        from parrot.tools.repo import ReadOnlyRepoToolkit
        names = {t.name for t in ReadOnlyRepoToolkit(repo_root=temp_repo).get_tools()}
        assert "resolve_plane_root" not in names
        assert "open_plane" not in names
```

---

## Agent Instructions

1. **Read the spec** — §2 ("Worktree plane resolution" + the component diagram),
   §3 Module 4, §8 Q4 and Q5.
2. **Check dependencies** — TASK-2637 must be in `sdd/tasks/completed/`.
3. **Verify the Codebase Contract.** Before writing, read
   `parrot/flows/dev_loop/wiki_search.py:39-88` end to end — it is the working
   reference — and confirm the two `git rev-parse` behaviours yourself in a scratch
   worktree.
4. Update the index → `"in-progress"`.
5. **Implement** per scope. Add **no** tool method to the toolkit.
6. **Verify** all acceptance criteria, especially the real-worktree test and the
   never-builds assertion.
7. **Move this file** to `sdd/tasks/completed/`.
8. **Update index** → `"done"`.
9. **Fill in the Completion Note**.

---

## Completion Note

**Completed by**: sdd-worker (autonomous)
**Date**: 2026-09-01
**Notes**: Added `graph_search.py` with module-level `async def
resolve_plane_root(repo_root)` (tries `--path-format=absolute
--git-common-dir` then the git<2.31 fallback; falls back to `repo_root`
unchanged on any failure) and `async def open_plane(repo_root)` (mirrors
the verified best-effort plane-open pattern used elsewhere in the
codebase, per this task's own guidance to avoid the literal `dev_loop`
token in shipped source — confirmed absent via grep). Added the
`temp_worktree` fixture to `conftest.py` (a real `git worktree add`).
Neither function is a toolkit method, so `get_tools()` is unchanged
(asserted). All 9 new tests pass, plus the full `tests/tools/repo/` suite
(108 tests); `ruff check` / `mypy` clean. Confirmed no plane build is ever
attempted (no `wiki.db` created in any test).

**Deviations from spec**: none.
