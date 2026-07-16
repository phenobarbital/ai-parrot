---
type: Wiki Overview
title: 'TASK-002: GitToolkit — `clone_repo` / `pull_repo` (public + private)'
id: doc:sdd-tasks-completed-task-002-gittoolkit-clone-pull-md
tags:
- overview
timestamp: '2026-07-16T08:34:12+00:00'
summary: Implements spec §2.B and Module 2 (G3). `GitToolkit` today is REST-only;
  it has
relates_to:
- concept: mod:parrot_tools.gittoolkit
  rel: mentions
---

# TASK-002: GitToolkit — `clone_repo` / `pull_repo` (public + private)

**Feature**: FEAT-250 — Dev-Loop Refactor
**Spec**: `sdd/specs/dev-loop-refactor.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: none
**Assigned-to**: unassigned

---

## Context

Implements spec §2.B and Module 2 (G3). `GitToolkit` today is REST-only; it has
NO local git operations. The dev-loop needs to clone/pull repositories (incl.
**private** ones) before the Development node runs against them.

---

## Scope

- Add `async def clone_repo(self, repository, dest_dir, branch=None, *, private=False, depth=None) -> Dict[str, Any]`
  using `asyncio.create_subprocess_exec("git", ...)`.
  - Resolve `repository` from alias (the `repositories` registry), `owner/name`
    slug, or full URL.
  - Private: prefer `gh repo clone` when `gh` is on `$PATH`; else inject the
    toolkit's token into the URL
    (`https://x-access-token:<token>@github.com/<slug>.git`).
  - Idempotent: if `dest_dir` is already a clone of the same remote, call
    `pull_repo` instead of re-cloning.
- Add `async def pull_repo(self, repo_path, branch=None) -> Dict[str, Any]`
  (fast-forward the existing clone).
- **Never** log or return the tokenized URL; scrub the token from any subprocess
  stderr before surfacing it.
- Unit tests with subprocess mocked.

**NOT in scope**: the flow-side provisioning step (TASK-006); PR/draft logic
(TASK-007).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot-tools/src/parrot_tools/gittoolkit.py` | MODIFY | Add `clone_repo` / `pull_repo` |
| `packages/ai-parrot-tools/tests/test_gittoolkit_clone.py` | CREATE | Unit tests (subprocess mocked) |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from parrot_tools.gittoolkit import GitToolkit, RepositoryCredential  # gittoolkit.py:968,47
```

### Existing Signatures to Use
```python
# packages/ai-parrot-tools/src/parrot_tools/gittoolkit.py
class GitToolkit(AbstractToolkit):                                       # :968
    def __init__(self, default_repository=None, default_branch="main",
                 github_token=None, auth_type="pat", app_id=None,
                 installation_id=None, private_key=None, private_key_path=None,
                 repositories=None, **kwargs)                            # :976
    # internals available:
    self.default_repository  # :1022
    self.default_branch      # :1027
    self.github_token        # :1030  (PAT mode; from arg or GITHUB_TOKEN env)
    self.auth_type           # :1032  ("pat" | "github_app")
    self._token_provider     # :1044  (_GitHubAppTokenProvider | None, App mode)
    async def create_pull_request(self, repository, title, body, base_branch,
                                  head_branch, commit_message, files,
                                  draft=False, labels=None) -> Dict[str, Any]   # :1488
class RepositoryCredential(BaseModel): ...                              # :47
```

### Does NOT Exist
- ~~`GitToolkit.clone_repo` / `GitToolkit.pull_repo`~~ — this task creates them.
- ~~any `git`/`gh` subprocess in GitToolkit today~~ — it uses `requests`/REST only.
- ~~`gh` is guaranteed on PATH~~ — must degrade to token-in-URL when absent
  (mirror `deployment_handoff.py:205 _gh_available` pattern via `shutil.which`).

---

## Implementation Notes

### Pattern to Follow
```python
import asyncio, os, shutil

async def clone_repo(self, repository, dest_dir, branch=None, *, private=False, depth=None):
    slug = self._resolve_slug(repository)            # alias → owner/name
    if os.path.isdir(os.path.join(dest_dir, ".git")):
        return await self.pull_repo(dest_dir, branch)
    if private and shutil.which("gh"):
        argv = ["gh", "repo", "clone", slug, dest_dir]
    else:
        url = self._auth_url(slug, private)          # token-in-url when private
        argv = ["git", "clone", *(["--branch", branch] if branch else []),
                *(["--depth", str(depth)] if depth else []), url, dest_dir]
    proc = await asyncio.create_subprocess_exec(*argv, stdout=PIPE, stderr=PIPE)
    out, err = await proc.communicate()
    if proc.returncode != 0:
        raise GitToolkitError(self._scrub(err.decode()))
    return {"path": dest_dir, "repository": slug, "branch": branch}
```

### Key Constraints
- Async throughout (no blocking `subprocess.run`).
- Token scrubbing is mandatory (R2). Use a helper that replaces the token with `***`.
- Reuse App-mode token via `self._token_provider` when `auth_type == "github_app"`.

### References in Codebase
- `packages/ai-parrot/src/parrot/flows/dev_loop/nodes/deployment_handoff.py:182,205,212` — existing async git/`gh` subprocess + `_gh_available`.

---

## Acceptance Criteria

- [ ] `clone_repo("owner/name", dest)` runs `git clone` into `dest` (public).
- [ ] Private clone uses `gh repo clone` when available, else token-in-URL; token never in return/logs.
- [ ] Re-clone over an existing clone delegates to `pull_repo` (idempotent).
- [ ] `pull_repo` fast-forwards an existing clone.
- [ ] `pytest packages/ai-parrot-tools/tests/test_gittoolkit_clone.py -v` passes.
- [ ] `ruff check packages/ai-parrot-tools/src/parrot_tools/gittoolkit.py` clean.

---

## Test Specification
```python
async def test_clone_repo_public(monkeypatch, tmp_path):
    tk = GitToolkit(github_token="x")
    # patch asyncio.create_subprocess_exec to a fake returning rc=0
    res = await tk.clone_repo("owner/name", str(tmp_path / "r"))
    assert res["repository"].endswith("owner/name") or res["path"]

async def test_clone_repo_private_scrubs_token(...):
    """Returned dict and raised errors never contain the PAT."""
```

---

## Agent Instructions
Standard SDD lifecycle. Re-verify GitToolkit internal attribute line numbers
before relying on them.

## Completion Note

**Status**: done — 2026-06-20

**What changed** (`parrot_tools/gittoolkit.py`)
- Added `import shutil`.
- Added async `clone_repo(repository, dest_dir, branch=None, *, private=False,
  depth=None)` and `pull_repo(repo_path, branch=None)` plus helpers:
  `_gh_available` (via `shutil.which`), `_clone_slug` (alias→slug without
  minting a token — public clones need no creds), `_display_slug`, `_clone_url`
  (token-in-URL `https://x-access-token:<token>@github.com/<slug>.git` for
  private), `_scrub` (redacts the token + `self.github_token` to `***`), and a
  static async `_run_subprocess`.
- Private clone prefers `gh repo clone` when `gh` is on `$PATH`, else
  token-in-URL. Idempotent: an existing `.git` dir at `dest_dir` delegates to
  `pull_repo`. Token never appears in returned payloads or scrubbed errors.

**Line-number note**: contract said GitToolkit at `:968` / ctor `:976`; actual
ctor is `:986`, helpers `_resolve_repository`/`_resolve_token`/`_default_token`
present and reused. No other line drift affected the work.

**Verification**
- `pytest test_gittoolkit_clone.py` → 7 passed (public, private token-in-URL,
  token-scrub-on-error, gh-preferred, idempotent→pull, pull ff, non-clone
  reject). Subprocess fully mocked.
- `ruff check` clean on both files.
