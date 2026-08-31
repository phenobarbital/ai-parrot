# TASK-2637: Confinement core, secret deny-list, and shared contracts

**Feature**: FEAT-484 — ReadOnlyRepoToolkit — Safe Repo Grounding for Any Client
**Spec**: `sdd/specs/readonly-repo-toolkit.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: none
**Assigned-to**: unassigned

---

## Context

Implements spec §3 **Module 1** (confinement half) and §8 **Q1**.

This task builds the **security boundary** of the whole feature. FEAT-484 grants a
hosted model read access to a checkout; `resolve_within_root()` and
`is_secret_path()` are the only things standing between "the model reads the repo"
and "the model reads `~/.ssh/id_rsa`". Every other task in this feature funnels its
caller-supplied paths through this module.

Spec §7 says it plainly: *"a second implementation is a second chance to get it
wrong"* — so confinement lives in exactly one place, and every path-taking tool
calls it. This task exists separately from the toolkit class (TASK-2638) precisely
so the boundary can be tested exhaustively on its own, without a toolkit, a client,
or a wiki plane in the picture.

---

## Scope

- Create the `parrot.tools.repo` package scaffold (`__init__.py`).
- Implement `confinement.py`:
  - `PathOutsideRootError(ValueError)` — raised on containment failure.
  - `SecretFileError(ValueError)` — raised on a deny-list match.
  - `resolve_within_root(root: Path, candidate: str) -> Path` — resolve the
    candidate to an absolute **real** path (`Path.resolve()`, which follows
    symlinks) and assert it is inside `root` (itself resolved). Reject `..`
    traversal, absolute outside paths, **and** symlink escape.
  - `is_secret_path(rel_path: str) -> bool` — the §8 Q1 deny-list.
  - `resolve_readable_path(root, candidate) -> Path` — the composed entry point:
    containment **then** deny-list. This is what tools call.
- Implement `models.py` with the shared Pydantic contracts: `RepoToolError`,
  `RepoReadResult`, `RepoSearchHit`, `RepoSearchResult`.
- Write unit tests in `packages/ai-parrot/tests/tools/repo/test_confinement.py`.

### Deny-list specification (spec §8 Q1 — implement exactly)

Matched **case-insensitively** on the **repo-relative POSIX path**. Any path
segment matching counts (so `config/.env` and `.env` both match).

Deny patterns:
`.env`, `.env.*`, `*.pem`, `*.key`, `*.p12`, `*.pfx`, `id_rsa*`, `id_dsa*`,
`id_ecdsa*`, `id_ed25519*`, `*.local.json`, `credentials`, `.netrc`, `.pgpass`,
`*.keystore`, `*.jks`

Allow-override — a match is **overridden** (file is readable) when the filename
ends in any of: `.example`, `.sample`, `.template`, `.dist`. So `.env.example`
and `server.key.sample` read fine; `.env` and `server.key` do not.

**NOT in scope**:
- The `ReadOnlyRepoToolkit` class itself, `read_file`, `list_files` → TASK-2638.
- `grep_files` → TASK-2639. Git tools → TASK-2640. Graph search → TASK-2641/2642.
- Any `AbstractToolkit` subclassing or `tool_schema` usage — this module is plain
  helpers and models, deliberately importable without the toolkit machinery.
- Byte-bound / truncation logic (that is TASK-2638's `read_file`).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/tools/repo/__init__.py` | CREATE | Package scaffold; re-export the public names |
| `packages/ai-parrot/src/parrot/tools/repo/confinement.py` | CREATE | `resolve_within_root`, `is_secret_path`, `resolve_readable_path`, error types |
| `packages/ai-parrot/src/parrot/tools/repo/models.py` | CREATE | `RepoToolError`, `RepoReadResult`, `RepoSearchHit`, `RepoSearchResult` |
| `packages/ai-parrot/tests/tools/repo/__init__.py` | CREATE | Test package marker |
| `packages/ai-parrot/tests/tools/repo/conftest.py` | CREATE | `temp_repo` fixture (spec §4) |
| `packages/ai-parrot/tests/tools/repo/test_confinement.py` | CREATE | Unit tests |

---

## Codebase Contract (Anti-Hallucination)

> **CRITICAL**: verified against `dev` on 2026-08-31. This task has **no**
> internal `parrot` dependencies beyond `pydantic` — that is deliberate. Do not
> import the toolkit machinery here.

### Verified Imports

```python
from __future__ import annotations

import fnmatch
import logging
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field
```

### Existing Signatures to Use

Nothing from `parrot.*` is required by this task. The models below are the
**target** shapes from spec §2 "Data Models" — create them, do not import them.

```python
# TARGET (create in models.py) — spec §2
class RepoToolError(BaseModel):
    error: str    # "path_outside_root" | "secret_file" | "not_found" | "timeout" | ...
    detail: str
    path: str = ""

class RepoReadResult(BaseModel):
    path: str
    content: str
    truncated: bool = False
    total_bytes: int = 0

class RepoSearchHit(BaseModel):
    page_id: str
    path: str
    summary: str = ""
    outline: list[str] = []
    score: float = 0.0
    approx_tokens: int = 0

class RepoSearchResult(BaseModel):
    query: str
    hits: list[RepoSearchHit] = []
    degraded: bool = False
    degraded_reason: str = ""
    total_tokens: int = 0
```

### Pattern source — read, do NOT import

```python
# packages/ai-parrot/src/parrot/flows/dev_loop/dispatchers/llm.py
# NOTE: the spec's §6 line numbers for these drifted +78; the ACTUAL lines
# on dev as of 2026-08-31 are:
    def _tool_read_file(self, cwd, args) -> Dict[str, Any]     # line 740
    def _tool_list_files(self, cwd, args) -> Dict[str, Any]    # line 755
    async def _tool_search_files(...)                          # line 769
    async def _tool_apply_patch(...)                           # line 801  ← NOT ported
    async def _tool_run_command(...)                           # line 827  ← NOT ported
# `_resolve_repo_path` is the confinement helper whose APPROACH you are porting.
# It is a private method on LLMCodeDispatcher — port the idea, import nothing.
```

### Does NOT Exist

- ~~`parrot.tools.repo`~~ — the entire package is new; you are creating it.
- ~~`parrot.tools.repo.confinement`~~ / ~~`.models`~~ — new files.
- ~~an importable cwd-confined path resolver anywhere in the codebase~~ — the only
  one is the **private** `LLMCodeDispatcher._resolve_repo_path`.
- ~~`FileReaderTool` as a safe base~~ — exists at `parrot_tools/file_reader.py:31`
  but is **not** confined to a repo root. Do not build on it.
- ~~`PathOutsideRootError`~~ / ~~`SecretFileError`~~ / ~~`is_secret_path`~~ /
  ~~`resolve_within_root`~~ / ~~`resolve_readable_path`~~ — all new in this task.
- ~~`Path.resolve(strict=True)` being safe for a not-yet-existing path~~ — it
  raises `FileNotFoundError`. Use `strict=False` (the default) and handle
  non-existence as a `not_found` error at the *caller* level.

---

## Implementation Notes

### Pattern to Follow

Containment must be **realpath-based**, not string-prefix-based on the raw input.
A string check on the unresolved path is the classic bypass.

```python
def resolve_within_root(root: Path, candidate: str) -> Path:
    """Resolve ``candidate`` and assert containment in ``root``."""
    real_root = root.resolve()
    # Join first, THEN resolve — so "../x" and symlinks are both collapsed.
    target = (real_root / candidate).resolve()
    # Path.is_relative_to is 3.9+; the repo targets 3.11.
    if target != real_root and not target.is_relative_to(real_root):
        raise PathOutsideRootError(
            f"{candidate!r} resolves outside the repository root"
        )
    return target
```

Notes on that snippet, all deliberate:
- `real_root / candidate` handles an **absolute** `candidate` correctly: pathlib
  discards the left operand, giving the absolute path, which then fails
  containment. Do not special-case it.
- Resolving **after** the join is what catches a symlink *inside* the root that
  points outside it.
- Resolve `root` too — if the root itself is reached via a symlink, an unresolved
  root makes every containment check wrong.

```python
_SECRET_DENY = (
    ".env", ".env.*", "*.pem", "*.key", "*.p12", "*.pfx",
    "id_rsa*", "id_dsa*", "id_ecdsa*", "id_ed25519*",
    "*.local.json", "credentials", ".netrc", ".pgpass",
    "*.keystore", "*.jks",
)
_SECRET_ALLOW_SUFFIXES = (".example", ".sample", ".template", ".dist")


def is_secret_path(rel_path: str) -> bool:
    """True when ``rel_path`` matches the secret deny-list (spec §8 Q1)."""
    posix = Path(rel_path).as_posix().lower()
    if posix.endswith(_SECRET_ALLOW_SUFFIXES):
        return False
    return any(
        fnmatch.fnmatch(segment, pattern)
        for segment in Path(posix).parts
        for pattern in _SECRET_DENY
    )
```

### Key Constraints

- **Pure sync is correct here.** These are CPU-only path computations; do not make
  them `async`. They will be called from async tools, which is fine.
- Do **not** put these helpers on the toolkit class as public methods —
  `AbstractToolkit._generate_tools()` (`tools/toolkit.py:537`) turns public async
  methods into LLM-callable tools. Module-level functions cannot be exposed by
  accident.
- `resolve_readable_path()` raises; it never returns an error model. Converting
  the exception to a `RepoToolError` is the **caller's** job (TASK-2638 onward).
  Keeping the raise here is what lets each tool attach its own `error` code.
- Google-style docstrings, strict type hints, `logging.getLogger(__name__)`.
- `from __future__ import annotations` at the top of every new module.

### References in Codebase

- `packages/ai-parrot/src/parrot/flows/dev_loop/dispatchers/llm.py:740` — approach
  being ported (private; read only).
- `packages/ai-parrot/src/parrot/tools/toolkit.py:537` — why helpers stay
  module-level / underscore-prefixed.

---

## Acceptance Criteria

- [ ] `parrot/tools/repo/` package exists and imports cleanly:
      `from parrot.tools.repo.confinement import resolve_readable_path`
- [ ] `resolve_within_root` accepts an ordinary nested path
- [ ] `resolve_within_root` rejects `../../etc/passwd` with `PathOutsideRootError`
- [ ] `resolve_within_root` rejects an absolute outside path (`/etc/passwd`)
- [ ] `resolve_within_root` rejects a **symlink inside the root pointing outside**
- [ ] `resolve_within_root` is correct when `root` itself is reached via a symlink
- [ ] `is_secret_path` returns `True` for every deny pattern, `False` for each
      `.example` / `.sample` / `.template` / `.dist` override
- [ ] `is_secret_path` matches on a **nested** path (`config/.env`)
- [ ] `resolve_readable_path` raises `SecretFileError` for `.env`, `PathOutsideRootError`
      for an escape, and returns a `Path` otherwise
- [ ] All four Pydantic models instantiate with defaults
- [ ] Tests pass: `pytest packages/ai-parrot/tests/tools/repo/test_confinement.py -v`
- [ ] Clean: `ruff check packages/ai-parrot/src/parrot/tools/repo/` and
      `mypy packages/ai-parrot/src/parrot/tools/repo/`
- [ ] No `shell=True`, no `subprocess`, no I/O of any kind in `confinement.py`

---

## Test Specification

```python
# packages/ai-parrot/tests/tools/repo/conftest.py
import subprocess
import pytest
from pathlib import Path


@pytest.fixture
def temp_repo(tmp_path: Path) -> Path:
    """git-init'd repo: nested dirs, an ignored build/ dir, a symlink
    escaping the root, an oversized file, secret files, and two commits."""
    root = tmp_path / "repo"
    (root / "pkg" / "sub").mkdir(parents=True)
    (root / "pkg" / "__init__.py").write_text("")
    (root / "pkg" / "sub" / "mod.py").write_text("def alpha():\n    return 1\n")
    (root / ".gitignore").write_text("build/\n")
    (root / "build").mkdir()
    (root / "build" / "artifact.py").write_text("def alpha():\n    return 2\n")
    # Secret files (§8 Q1)
    (root / ".env").write_text("SECRET_KEY=hunter2\n")
    (root / ".env.example").write_text("SECRET_KEY=\n")
    (root / "server.pem").write_text("-----BEGIN PRIVATE KEY-----\n")
    (root / "config").mkdir()
    (root / "config" / ".env").write_text("NESTED=secret\n")
    # Oversized file for the byte-bound test (TASK-2638)
    (root / "big.txt").write_text("x" * 200_000)
    # Symlink escaping the root
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "secret.txt").write_text("do not read me")
    (root / "escape").symlink_to(outside)

    subprocess.run(["git", "init", "-q"], cwd=root, check=True)
    subprocess.run(["git", "config", "user.email", "t@t.t"], cwd=root, check=True)
    subprocess.run(["git", "config", "user.name", "t"], cwd=root, check=True)
    subprocess.run(["git", "add", "-A"], cwd=root, check=True)
    subprocess.run(["git", "commit", "-qm", "first"], cwd=root, check=True)
    (root / "pkg" / "sub" / "mod.py").write_text("def alpha():\n    return 42\n")
    subprocess.run(["git", "commit", "-aqm", "second"], cwd=root, check=True)
    return root
```

```python
# packages/ai-parrot/tests/tools/repo/test_confinement.py
import pytest
from pathlib import Path

from parrot.tools.repo.confinement import (
    PathOutsideRootError,
    SecretFileError,
    is_secret_path,
    resolve_readable_path,
    resolve_within_root,
)
from parrot.tools.repo.models import (
    RepoReadResult, RepoSearchHit, RepoSearchResult, RepoToolError,
)


class TestResolveWithinRoot:
    def test_accepts_nested(self, temp_repo: Path):
        out = resolve_within_root(temp_repo, "pkg/sub/mod.py")
        assert out == (temp_repo / "pkg" / "sub" / "mod.py").resolve()

    def test_rejects_parent_traversal(self, temp_repo: Path):
        with pytest.raises(PathOutsideRootError):
            resolve_within_root(temp_repo, "../../etc/passwd")

    def test_rejects_absolute_outside(self, temp_repo: Path):
        with pytest.raises(PathOutsideRootError):
            resolve_within_root(temp_repo, "/etc/passwd")

    def test_rejects_symlink_escape(self, temp_repo: Path):
        """A symlink INSIDE the root pointing outside is the case a
        string-prefix check would wrongly allow."""
        with pytest.raises(PathOutsideRootError):
            resolve_within_root(temp_repo, "escape/secret.txt")

    def test_root_itself_via_symlink(self, tmp_path: Path, temp_repo: Path):
        link = tmp_path / "link_to_repo"
        link.symlink_to(temp_repo)
        assert resolve_within_root(link, "pkg/sub/mod.py").is_file()


class TestIsSecretPath:
    @pytest.mark.parametrize("p", [
        ".env", ".env.production", "server.pem", "server.key",
        "id_rsa", "id_rsa.pub", "id_ed25519", "config/.env",
        "wiki.local.json", "credentials", ".netrc", ".pgpass",
        "a.p12", "a.pfx", "a.keystore", "a.jks", ".ENV",
    ])
    def test_denied(self, p):
        assert is_secret_path(p) is True

    @pytest.mark.parametrize("p", [
        ".env.example", ".env.sample", "server.pem.example",
        "server.key.template", "credentials.dist",
        "pkg/sub/mod.py", "README.md",
    ])
    def test_allowed(self, p):
        assert is_secret_path(p) is False


class TestResolveReadablePath:
    def test_ok(self, temp_repo: Path):
        assert resolve_readable_path(temp_repo, "pkg/sub/mod.py").is_file()

    def test_secret_raises(self, temp_repo: Path):
        with pytest.raises(SecretFileError):
            resolve_readable_path(temp_repo, ".env")

    def test_nested_secret_raises(self, temp_repo: Path):
        with pytest.raises(SecretFileError):
            resolve_readable_path(temp_repo, "config/.env")

    def test_example_allowed(self, temp_repo: Path):
        assert resolve_readable_path(temp_repo, ".env.example").is_file()

    def test_escape_raises(self, temp_repo: Path):
        with pytest.raises(PathOutsideRootError):
            resolve_readable_path(temp_repo, "escape/secret.txt")


class TestModels:
    def test_defaults(self):
        assert RepoToolError(error="not_found", detail="x").path == ""
        assert RepoReadResult(path="a", content="b").truncated is False
        assert RepoSearchHit(page_id="p", path="a").outline == []
        r = RepoSearchResult(query="q")
        assert r.hits == [] and r.degraded is False
```

---

## Agent Instructions

1. **Read the spec** at `sdd/specs/readonly-repo-toolkit.spec.md` — especially §2
   (Data Models), §3 Module 1, §7 (Known Risks), and §8 Q1.
2. **Check dependencies** — none. This is the first task of the feature.
3. **Verify the Codebase Contract** before writing code. Note the spec's `llm.py`
   line numbers are stale (+78 drift); this task file carries the corrected ones.
4. Update `sdd/tasks/index/readonly-repo-toolkit.json` → `"in-progress"`.
5. **Implement** per scope. This is the security boundary — prefer an explicit,
   boring, exhaustively-tested implementation over a clever one.
6. **Verify** every acceptance criterion, including the symlink cases.
7. **Move this file** to `sdd/tasks/completed/`.
8. **Update index** → `"done"`.
9. **Fill in the Completion Note**.

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**:
**Date**:
**Notes**:

**Deviations from spec**: none | describe if any
