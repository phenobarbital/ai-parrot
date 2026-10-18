# HOTFIX-cs-228-1: Parse the clone origin host before matching it in `RepoWikiCache._origin_matches`

**Feature**: cs:228 — Incomplete URL substring sanitization in `RepoWikiCache._origin_matches` (CodeQL `py/incomplete-url-substring-sanitization`, CWE-020)
**Spec**: `sdd/briefs/repo-cache-origin-url-check.brief.md`
**Status**: pending
**Priority**: high
**Estimated effort**: S (< 2h)
**Depends-on**: none
**Assigned-to**: unassigned

---

## Context

`RepoWikiCache._clone_matches()` (repo_cache.py:273-291) guards the wiki cache
against pulling from and indexing a clone that does not belong to the canonical
`owner/name` repository. It reads `git remote get-url origin` and delegates to
`_origin_matches(origin, repository)` (repo_cache.py:296-306). That helper
checks `"github.com/" in normalized` (line 304) and keeps whatever follows the
first `github.com/`, so an origin such as
`https://evil.example/github.com/owner/name` is accepted as `owner/name`.
GitHub code-scanning alert #228 flags exactly this line.

This task implements the brief's single fix chunk: parse the URL, allowlist the
host, derive the slug from the parsed path only.

---

## Scope

- Add module-level allowlists to `packages/ai-parrot/src/parrot/knowledge/wiki/repo_cache.py`:
  `_GITHUB_HOSTS: frozenset[str] = frozenset({"github.com", "www.github.com"})`
  and `_ORIGIN_SCHEMES: frozenset[str] = frozenset({"https", "http", "ssh", "git"})`.
- Rewrite `RepoWikiCache._origin_matches` so that:
  - an origin starting with `git@github.com:` (SCP form) keeps its current
    exact-prefix handling, taking the path after the first `:`;
  - any other origin is parsed with `urllib.parse.urlparse`; it matches only if
    `parsed.scheme in _ORIGIN_SCHEMES` and `parsed.hostname in _GITHUB_HOSTS`,
    and the repository slug is taken from `parsed.path` only;
  - the derived path is stripped of surrounding `/`, a trailing `.git`, and
    lower-cased before being compared with `repository`;
  - everything else (no scheme, other hosts, host embedded in path/userinfo/
    subdomain, extra path components) returns `False`.
- Extend `packages/ai-parrot/tests/knowledge/wiki/test_repo_cache.py` with
  (a) parametrized unit tests of `RepoWikiCache._origin_matches` for accepted
  and rejected origins and (b) one behavioural `_ensure_clone` test proving a
  look-alike-host origin is discarded and re-cloned once.

**NOT in scope**:
- `GitToolkit` (`parrot_tools/gittoolkit.py`) — its `_display_slug` already parses.
- Admitting GitHub Enterprise hosts or a configurable host allowlist.
- Changing `paths_for` validation, `_clone_matches` branch/upstream checks, or
  the recovery loop in `_ensure_clone`.
- Any other CodeQL alert.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/knowledge/wiki/repo_cache.py` | MODIFY | Add `urlparse` import + two allowlist constants; rewrite `_origin_matches` |
| `packages/ai-parrot/tests/knowledge/wiki/test_repo_cache.py` | MODIFY | Add `_origin_matches` unit tests and a look-alike-origin `_ensure_clone` test |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from urllib.parse import urlparse  # stdlib; same pattern as parrot_tools/gittoolkit.py:1412
from parrot.knowledge.wiki.repo_cache import BuildOutcome, RepoCachePaths, RepoWikiCache, repo_lock  # verified: test_repo_cache.py:14
```

### Existing Signatures to Use
```python
# packages/ai-parrot/src/parrot/knowledge/wiki/repo_cache.py
_IDENTITY_FILENAME = ".repo_cache_identity.json"   # line 23 — put the new constants right after _STATE_FILENAME (line 24)
_STATE_FILENAME = ".repo_cache_state.json"         # line 24

class RepoWikiCache:                                # line 93
    async def _clone_matches(self, paths: RepoCachePaths) -> bool:   # line 273
        # line 281: if origin is None or not self._origin_matches(origin, paths.repository):
    @staticmethod
    def _origin_matches(origin: str, repository: str) -> bool:       # lines 296-306 — the body to replace
        """Compare a GitHub origin URL with a canonical owner/name identity."""
        normalized = origin.strip().rstrip("/")
        if normalized.endswith(".git"):
            normalized = normalized[:-4]
        if normalized.startswith("git@github.com:"):
            normalized = normalized.partition(":")[2]
        elif "github.com/" in normalized:
            normalized = normalized.split("github.com/", 1)[1]
        return normalized.lower() == repository

# packages/ai-parrot/tests/knowledge/wiki/test_repo_cache.py
class FakeGit:                                      # line 17; FakeGit().origin is answered to `remote get-url origin` (lines 49-51)
def _cache(tmp_path, git=None, *, clone_branch=None, ...) -> RepoWikiCache   # helper used by test_ensure_clone_validates_origin_and_branch (line 197)
async def test_ensure_clone_validates_origin_and_branch(tmp_path: Path) -> None:  # line 197 — pattern to copy
```

### Does NOT Exist
- ~~`RepoWikiCache.github_hosts` / a constructor parameter for allowed hosts~~ — the allowlist is a module constant
- ~~`parrot.knowledge.wiki.repo_cache._GITHUB_HOSTS` / `_ORIGIN_SCHEMES`~~ — this task CREATES them
- ~~a `parse_origin()` helper elsewhere in `parrot.knowledge.wiki`~~ — none; do not import from `parrot_tools`

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {
      "path": "packages/ai-parrot/src/parrot/knowledge/wiki/repo_cache.py",
      "action": "MODIFY"
    },
    {
      "path": "packages/ai-parrot/tests/knowledge/wiki/test_repo_cache.py",
      "action": "MODIFY"
    }
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot/src/parrot/knowledge/wiki/repo_cache.py#RepoWikiCache._origin_matches",
    "sym:packages/ai-parrot/src/parrot/knowledge/wiki/repo_cache.py#RepoWikiCache._clone_matches"
  ]
}
```

---

## Implementation Notes

### Pattern to Follow
```python
# repo_cache.py — replacement body (mirrors GitToolkit._display_slug's host allowlist)
    @staticmethod
    def _origin_matches(origin: str, repository: str) -> bool:
        """Compare a GitHub origin URL with a canonical owner/name identity.

        The origin is parsed before its host is checked (CodeQL
        ``py/incomplete-url-substring-sanitization``): only the SCP form
        ``git@github.com:owner/name`` or a URL whose parsed host is exactly a
        GitHub host matches. The slug is taken from the parsed path alone.
        """
        normalized = origin.strip()
        if normalized.lower().startswith("git@github.com:"):
            path = normalized.partition(":")[2]
        else:
            parsed = urlparse(normalized)
            if parsed.scheme.lower() not in _ORIGIN_SCHEMES or parsed.hostname not in _GITHUB_HOSTS:
                return False
            path = parsed.path
        path = path.strip("/")
        if path.lower().endswith(".git"):
            path = path[:-4]
        return path.lower() == repository
```

### Key Constraints
- `parsed.hostname` is already lower-cased and has userinfo/port stripped, so
  `https://x-access-token:tok@github.com/o/n.git` still matches while
  `https://github.com@evil.example/o/n` does not (its hostname is `evil.example`).
- Never use `in`/`endswith` on the raw origin string for the host decision —
  that is the pattern the alert flags.
- The function stays a `@staticmethod` with the same signature and the same
  call site (repo_cache.py:281); `_clone_matches` is untouched.
- Do not log the origin at any new level (it may carry credentials in other
  deployments).
- 120-column lines, Google-style docstrings, strict type hints.

### References in Codebase
- `packages/ai-parrot-tools/src/parrot_tools/gittoolkit.py:1409-1419` —
  `_display_slug`, the existing parse-then-allowlist pattern
- `packages/ai-parrot/tests/knowledge/wiki/test_repo_cache.py:197-207` —
  `test_ensure_clone_validates_origin_and_branch`, the behavioural pattern to copy

---

## Implementation Blueprint

### Steps (in order)
1. Add `from urllib.parse import urlparse` to the stdlib import block of
   repo_cache.py (alphabetical, after `from typing import ...`) — *why*: parse
   before checking.
2. Add `_GITHUB_HOSTS` and `_ORIGIN_SCHEMES` after `_STATE_FILENAME`
   (repo_cache.py:24) — *why*: one explicit, exact host allowlist.
3. Replace the body of `_origin_matches` (repo_cache.py:296-306) with the
   Pattern above — *why*: the fix itself.
4. Add the tests from the Test Specification — *why*: lock the contract and
   give CodeQL-equivalent bypass inputs a regression test.

### `packages/ai-parrot/src/parrot/knowledge/wiki/repo_cache.py` (MODIFY)
```python
# occurrences: 1 (verified: repo_cache.py:24)
# REPLACE
_STATE_FILENAME = ".repo_cache_state.json"
# WITH
_STATE_FILENAME = ".repo_cache_state.json"
#: Exact hosts a cache clone's ``origin`` may point at (never a suffix match).
_GITHUB_HOSTS: frozenset[str] = frozenset({"github.com", "www.github.com"})
#: URL schemes accepted for a clone ``origin``.
_ORIGIN_SCHEMES: frozenset[str] = frozenset({"https", "http", "ssh", "git"})
```
**Why this shape**: the host check becomes an equality against a closed set on
the *parsed* hostname, which is what the CodeQL rule asks for.

### FILL IN checklist
- [ ] `repo_cache.py::_origin_matches` — replacement body; bounded by the Pattern above
- [ ] `test_repo_cache.py` — the parametrized cases and behavioural test; bounded by Test Specification

---

## Acceptance Criteria

- [ ] `RepoWikiCache._origin_matches("https://evil.example/github.com/owner/name", "owner/name")` is `False`
- [ ] `RepoWikiCache._origin_matches("https://github.com.evil.example/owner/name", "owner/name")` is `False`
- [ ] `RepoWikiCache._origin_matches("https://github.com@evil.example/owner/name", "owner/name")` is `False`
- [ ] All of `https://github.com/Owner/Name.git`, `https://github.com/owner/name/`,
      `https://www.github.com/owner/name`, `ssh://git@github.com/owner/name.git`,
      `git@github.com:owner/name.git`, `https://x-access-token:t@github.com/owner/name.git`
      match `"owner/name"`
- [ ] `_ensure_clone` with a look-alike-host origin discards the clone and
      re-clones exactly once (`FakeGit.clone_calls == 1`)
- [ ] `test_ensure_clone_validates_origin_and_branch` and the rest of
      `test_repo_cache.py` / `test_repo_build.py` pass unchanged
- [ ] No substring/`endswith` test on the raw origin string remains in `_origin_matches`
- [ ] `ruff check` clean on both files

---

## Validation Commands

- `pytest packages/ai-parrot/tests/knowledge/wiki/test_repo_cache.py -q`
- `pytest packages/ai-parrot/tests/knowledge/wiki/test_repo_build.py -q`

---

## Test Specification

```python
# Extend packages/ai-parrot/tests/knowledge/wiki/test_repo_cache.py


@pytest.mark.parametrize(
    "origin",
    [
        "https://github.com/owner/name.git",
        "https://github.com/owner/name",
        "https://github.com/owner/name/",
        "https://github.com/Owner/Name.git",
        "https://www.github.com/owner/name",
        "http://github.com/owner/name",
        "ssh://git@github.com/owner/name.git",
        "git@github.com:owner/name.git",
        "git@github.com:owner/name",
        "https://x-access-token:secret@github.com/owner/name.git",
        "  https://github.com/owner/name.git\n",
    ],
)
def test_origin_matches_accepts_github_origins(origin: str) -> None:
    """Every legitimate GitHub origin form for owner/name matches."""
    assert RepoWikiCache._origin_matches(origin, "owner/name")


@pytest.mark.parametrize(
    "origin",
    [
        "https://evil.example/github.com/owner/name",
        "https://evil.example/github.com/owner/name.git",
        "https://github.com.evil.example/owner/name",
        "https://github.com@evil.example/owner/name",
        "https://evil.example/?u=github.com/owner/name",
        "https://github.com/other/name",
        "https://github.com/owner/name/extra",
        "https://github.com/owner",
        "github.com/owner/name",
        "owner/name",
        "file:///tmp/github.com/owner/name",
        "git@gitlab.com:owner/name.git",
        "",
    ],
)
def test_origin_matches_rejects_lookalike_origins(origin: str) -> None:
    """A host embedded elsewhere in the URL, or any non-GitHub host, never matches."""
    assert not RepoWikiCache._origin_matches(origin, "owner/name")


async def test_ensure_clone_rejects_lookalike_host(tmp_path: Path) -> None:
    """A clone whose origin merely contains github.com/ is discarded and re-cloned once."""
    git = FakeGit()
    cache = _cache(tmp_path, git)
    paths = cache.paths_for("owner/name")
    (paths.clone_dir / ".git").mkdir(parents=True)
    git.origin = "https://evil.example/github.com/owner/name.git"
    await cache._ensure_clone(paths)
    assert git.clone_calls == 1
    assert git.pull_calls == 0
```

---

## Agent Instructions

When you pick up this task:

1. **Work in the brief worktree**
   (`.claude/worktrees/hotfix-cs-228-repo-cache-origin-url-check`) — never on
   `main` or `dev`.
2. **Read the brief** at `sdd/briefs/repo-cache-origin-url-check.brief.md`.
3. **Verify the Codebase Contract** — confirm repo_cache.py:24, :281 and
   :296-306 still match before editing; if lines drifted, re-grep and update
   the contract first.
4. **Implement** per the blueprint; touch only the two listed files.
5. **Verify** — run every Validation Command with
   `PYTHONPATH=packages/ai-parrot/src`, then
   `ruff check packages/ai-parrot/src/parrot/knowledge/wiki/repo_cache.py packages/ai-parrot/tests/knowledge/wiki/test_repo_cache.py`.
6. **Commit code** staging only the two files:
   `fix(wiki): HOTFIX-cs-228-1 — parse clone origin host before matching (CodeQL cs:228)`.
7. **Update** this file's Completion Note and the per-brief index status, then
   commit the SDD state.
8. Done → the owner runs `/sdd-done cs-228`.

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**:
**Date**:
**Notes**:

**Deviations from spec**:
