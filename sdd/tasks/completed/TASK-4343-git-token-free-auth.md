# TASK-4343: Authenticate private clone and pull without persisting the token

**Feature**: FEAT-672 — GitHubReviewer local clone + wikitoolkit graph
**Spec**: `sdd/specs/github-reviewer-local-repo-wiki.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-4336 (done)
**Assigned-to**: unassigned
**discovered_from**: issue:93f2022d934a

---

## Context

Ledger issue `issue:93f2022d934a` (review of FEAT-672): a private clone made by
`GitToolkit.clone_repo(..., private=True, prefer_gh=False)` puts the token in
the clone URL (`https://x-access-token:<token>@github.com/...`), so git stores
it as `remote.origin.url` in `.git/config` under the reviewer cache directory.
The token stays at rest on disk for the life of the cache entry. The cache then
pulls with `pull_repo`, which only works today because the token is in the
origin URL.

This task moves authentication into the subprocess environment so the token
never reaches argv or `.git/config` (spec Module 4, "GitToolkit clone
hardening"; secrets-never-at-rest constraint).

---

## Scope

- Add an optional `env` keyword to `GitToolkit._run_subprocess` and merge it over
  `os.environ` for the child.
- Add `GitToolkit._auth_env(url, token)` returning the git environment-config
  variables that send an `Authorization` header for the URL's host
  (`GIT_CONFIG_COUNT` / `GIT_CONFIG_KEY_0` / `GIT_CONFIG_VALUE_0`, plus
  `GIT_TERMINAL_PROMPT=0`).
- Change the private, non-`gh` path of `clone_repo` to clone the **clean** URL
  and authenticate through `env=` instead of a token-bearing URL.
- Add a keyword-only `private: bool = False` to `pull_repo`. When `True`,
  authenticate through `env=`, and first rewrite a credential-bearing
  `origin` URL (left by an earlier clone) to its clean form.
- Update the existing private-clone tests and add new ones.

**NOT in scope**: the `gh repo clone` path (gh keeps its own credential store);
`RepoWikiCache` passing `private=True` to `pull_repo` (TASK-4345); any change to
`_clone_url` callers other than `clone_repo`.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot-tools/src/parrot_tools/gittoolkit.py` | MODIFY | `env` on `_run_subprocess`, `_auth_env`, clean-URL private clone, `pull_repo(private=)` |
| `packages/ai-parrot-tools/tests/test_gittoolkit_clone.py` | MODIFY | Recorder accepts `env`; private-clone tests assert token-free argv/origin |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
import base64  # verified: packages/ai-parrot-tools/src/parrot_tools/gittoolkit.py:24 (already imported)
import os      # verified: gittoolkit.py:27 (already imported)
from urllib.parse import urlparse  # verified: a LOCAL import inside _display/_clone_slug at gittoolkit.py:1413 — NOT a module-level import; import it locally inside _auth_env / pull_repo the same way
```

### Existing Signatures to Use
```python
# packages/ai-parrot-tools/src/parrot_tools/gittoolkit.py
def _clone_url(self, slug_or_url: str, private: bool) -> tuple[str, Optional[str]]:  # line 1421
    # private=False returns (base_url, None) — the clean https URL. Keep this method unchanged.
def _scrub(self, text: str, token: Optional[str] = None) -> str:  # line 1442
@staticmethod
async def _run_subprocess(argv: List[str], timeout: Optional[float] = None) -> tuple[int, str, str]:  # line 1461
async def clone_repo(self, repository, dest_dir, branch=None, *, private=False, depth=None,
                     timeout=None, prefer_gh=True) -> Dict[str, Any]:  # line 1502
    #   url, token = self._clone_url(slug, private)   # line 1551 — the line this task changes
async def pull_repo(self, repo_path: str, branch: Optional[str] = None, *,
                    timeout: Optional[float] = None) -> Dict[str, Any]:  # line 1572
    #   argv = ["git", "-C", repo_path, "pull", "--ff-only"]   # line 1595
def _resolve_token(self) -> str:  # line 1613 — sync; returns PAT or App installation token
```

```python
# packages/ai-parrot-tools/tests/test_gittoolkit_clone.py
class _Recorder:  # line 24 — async def __call__(self, argv, timeout=None)  (no env yet)
# tests asserting the token-in-URL behaviour that this task REPLACES:
#   test_clone_repo_private_uses_token_in_url        (line 58, asserts line 68)
#   test_clone_repo_prefer_gh_false_uses_token_url   (line 105, asserts line 116)
```

### Does NOT Exist
- ~~`GitToolkit._auth_env`~~ — created by this task
- ~~`pull_repo(private=...)`~~ — created by this task
- ~~`_run_subprocess(env=...)`~~ — created by this task
- ~~a git credential-helper module in parrot_tools~~ — do not add one; env-config is the mechanism

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {"path": "packages/ai-parrot-tools/src/parrot_tools/gittoolkit.py", "action": "MODIFY"},
    {"path": "packages/ai-parrot-tools/tests/test_gittoolkit_clone.py", "action": "MODIFY"}
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot-tools/src/parrot_tools/gittoolkit.py#GitToolkit._run_subprocess",
    "sym:packages/ai-parrot-tools/src/parrot_tools/gittoolkit.py#GitToolkit.clone_repo",
    "sym:packages/ai-parrot-tools/src/parrot_tools/gittoolkit.py#GitToolkit.pull_repo",
    "sym:packages/ai-parrot-tools/src/parrot_tools/gittoolkit.py#GitToolkit._clone_url",
    "sym:packages/ai-parrot-tools/src/parrot_tools/gittoolkit.py#GitToolkit._resolve_token",
    "sym:packages/ai-parrot-tools/src/parrot_tools/gittoolkit.py#GitToolkit._scrub"
  ]
}
```

---

## Implementation Notes

### Key Constraints
- The token must never appear in argv, in `.git/config`, or in any returned
  payload or exception text (`_scrub` still applies to stderr).
- Pass `env=` to `_run_subprocess` **only** when authentication is needed, so
  public clone/pull calls keep the exact `(argv, timeout=...)` call shape that
  existing tests and `RepoWikiCache._git_output` rely on.
- `GIT_CONFIG_COUNT` env-config needs git ≥ 2.31. Do not add a version probe.
  Note the requirement in the docstring.
- The header value is `AUTHORIZATION: basic <base64("x-access-token:<token>")>`,
  the same form `actions/checkout` uses. The config key is scoped to the URL's
  origin: `http.<scheme>://<host>/.extraheader`.

---

## Implementation Blueprint

### Steps (in order)
1. Add `env` to `_run_subprocess`, because every authenticated call goes through it.
2. Add `_auth_env`, because clone and pull must build the header the same way.
3. Switch the private non-gh clone to the clean URL plus `env`, because that alone stops new clones writing the token to `.git/config`.
4. Add `pull_repo(private=)` with an origin rewrite, because existing caches already hold a tokenized origin that must be cleaned on the next pull.
5. Update the tests, because two current tests assert the old token-in-URL behaviour.

### `packages/ai-parrot-tools/src/parrot_tools/gittoolkit.py` (MODIFY) — `_run_subprocess`
```python
# occurrences: 1 (verified: grep -cF 'async def _run_subprocess(argv: List[str], timeout: Optional[float] = None) -> tuple[int, str, str]:' gittoolkit.py)
# REPLACE the signature line (gittoolkit.py:1461) and the create_subprocess_exec call inside it:
    async def _run_subprocess(
        argv: List[str],
        timeout: Optional[float] = None,
        env: Optional[Dict[str, str]] = None,
    ) -> tuple[int, str, str]:
        # docstring: add "env: extra environment merged over os.environ (auth headers); never logged."
        proc = await asyncio.create_subprocess_exec(
            *argv,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            env={**os.environ, **env} if env else None,
        )
```
**Why**: `env=None` keeps the inherited environment, which is today's behaviour, so nothing changes for existing callers.

### `gittoolkit.py` (MODIFY) — `_auth_env` (new, insert right after `_clone_url`)
```python
    def _auth_env(self, url: str, token: str) -> Dict[str, str]:
        """Return git env-config that authenticates ``url``'s host without persisting ``token``.

        Requires git >= 2.31 (``GIT_CONFIG_COUNT``). The token lives only in the
        child's environment: never in argv, never in ``.git/config``.
        """
        parsed = urlparse(url)
        # FILL IN: build key f"http.{parsed.scheme}://{parsed.hostname}/.extraheader";
        #          header = base64.b64encode(f"x-access-token:{token}".encode()).decode();
        #          return GIT_CONFIG_COUNT="1", GIT_CONFIG_KEY_0=key,
        #          GIT_CONFIG_VALUE_0=f"AUTHORIZATION: basic {header}", GIT_TERMINAL_PROMPT="0"
        #          — bounded by: no token in argv / .git/config
```

### `gittoolkit.py` (MODIFY) — `clone_repo` private non-gh branch
```python
# occurrences: 1 (verified: grep -cF 'url, token = self._clone_url(slug, private)' gittoolkit.py → line 1551)
# REPLACE that line with:
            url, _ = self._clone_url(slug, False)
            env: Optional[Dict[str, str]] = None
            if private:
                token = self._resolve_token()
                env = self._auth_env(url, token)
# and pass env only when set:
# FILL IN: call self._run_subprocess(argv, ...) with env=env only when env is not None
#          (keep the existing timeout/no-timeout split) — bounded by: public calls keep their call shape
```
**Why**: the clone URL is now clean, so git writes a token-free `remote.origin.url`. `token` is still kept for `_scrub`.

### `gittoolkit.py` (MODIFY) — `pull_repo`
```python
# occurrences: 1 (verified: grep -cF 'argv = ["git", "-C", repo_path, "pull", "--ff-only"]' gittoolkit.py → line 1595)
# Signature: add `private: bool = False` after `timeout` (keyword-only). Docstring: document it.
# INSERT before the `argv = [...]` line:
        env: Optional[Dict[str, str]] = None
        token: Optional[str] = None
        if private:
            token = self._resolve_token()
            # FILL IN: read origin via `git -C repo_path remote get-url origin`; if it carries
            #          credentials (user/pass in the netloc), rewrite it with
            #          `git -C repo_path remote set-url origin <clean url>` — bounded by:
            #          an existing cache clone must lose its stored token on the next pull;
            #          scrub any error text with self._scrub(err, token)
            # FILL IN: env = self._auth_env(<clean origin url>, token)
# and scrub pull errors with self._scrub(err, token).
```
**Why**: caches built before this fix already hold the token in their origin URL, and this is the one place that touches them on every refresh.

### FILL IN checklist
- [ ] `_auth_env` — header and key built as specified; no token in the key
- [ ] `clone_repo` — env passed only for private non-gh clones
- [ ] `pull_repo` — tokenized origin rewritten to its clean form; env auth; errors scrubbed
- [ ] tests — `_Recorder.__call__(self, argv, timeout=None, env=None)` records `env`

---

## Acceptance Criteria

- [ ] A private non-gh clone's argv contains no token, and its clone URL is the clean `https://github.com/owner/name.git`
- [ ] The private clone's `env` carries an `AUTHORIZATION: basic` extraheader for `https://github.com/`
- [ ] `pull_repo(..., private=True)` rewrites a credential-bearing origin to the clean URL and authenticates via `env`
- [ ] Public clone/pull call `_run_subprocess` without `env`
- [ ] Error text never contains the token
- [ ] `ruff check` is clean on both files

---

## Validation Commands

- `pytest packages/ai-parrot-tools/tests/test_gittoolkit_clone.py -q --import-mode=importlib`

---

## Test Specification

```python
# packages/ai-parrot-tools/tests/test_gittoolkit_clone.py — replace the two token-in-URL tests
async def test_clone_repo_private_keeps_token_out_of_argv(tmp_path):
    """Private non-gh clone uses the clean URL and auth via env."""
    # FILL IN: rec = _Recorder(); patch _run_subprocess; clone_repo(private=True, prefer_gh=False)
    #          assert TOKEN not in " ".join(rec.calls[0]); assert url arg == clean URL;
    #          assert "AUTHORIZATION: basic" in rec.env["GIT_CONFIG_VALUE_0"]

async def test_pull_repo_private_rewrites_tokenized_origin(tmp_path):
    """A pull on an old clone cleans its origin URL and authenticates via env."""
    # FILL IN: recorder replies to `remote get-url origin` with a tokenized URL; assert a
    #          `remote set-url origin https://github.com/owner/name.git` call happens before pull

async def test_public_pull_passes_no_env(tmp_path):
    # FILL IN
```

---

## Agent Instructions

Standard SDD task flow (see `sdd/templates/task.md` → Agent Instructions). Run the
validation command with `PYTHONPATH` set to the worktree's absolute `packages/*/src`.

---

## Completion Note

Implemented by sdd-worker (sequential, no coder seats). Implementing commit 06808192a. Tests: 15 passed, 0 failed (validation command). ruff: only 2 pre-existing ASYNC240 findings in gittoolkit.py (baseline identical). No contract drift.
