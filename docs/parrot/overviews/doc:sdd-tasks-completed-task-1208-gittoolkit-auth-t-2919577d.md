---
type: Wiki Overview
title: 'TASK-1208: Extend `GitToolkit.__init__` with `auth_type` + route every call
  through `_bearer_token`'
id: doc:sdd-tasks-completed-task-1208-gittoolkit-auth-type-plumbing-md
tags:
- overview
timestamp: '2026-07-16T08:34:12+00:00'
summary: With the `_GitHubAppTokenProvider` from TASK-1207 in place, this task wires
relates_to:
- concept: mod:parrot_tools.gittoolkit
  rel: mentions
---

# TASK-1208: Extend `GitToolkit.__init__` with `auth_type` + route every call through `_bearer_token`

**Feature**: FEAT-179 — GitHub App Authentication for GitToolkit
**Spec**: `sdd/specs/github-app-auth-gittoolkit.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-1207
**Assigned-to**: unassigned

---

## Context

With the `_GitHubAppTokenProvider` from TASK-1207 in place, this task wires
it into `GitToolkit`: a new `auth_type` discriminator on `__init__`, the
new App-mode constructor kwargs, file-path → PEM resolution, validation
that fails fast on misconfiguration, a single new internal seam
`_bearer_token()` returning the current bearer, and the four callsites
that today read `self.github_token` directly being switched to call
`_bearer_token()`.

The two `GitToolkitInput` fields (`auth_type` and the App-mode fields)
are also added so the toolkit's input schema stays consistent.

See spec §3 Module 2, §6 Codebase Contract, and §5 Acceptance Criteria.

---

## Scope

- Extend `GitToolkitInput` (`gittoolkit.py:42`) with the five new fields
  per spec §2 Data Models: `auth_type`, `app_id`, `installation_id`,
  `private_key`, `private_key_path`.
- Extend `GitToolkit.__init__` (`gittoolkit.py:258`) to accept the same
  five new kwargs (all optional). Default `auth_type="pat"`.
- Read the same fields from environment when constructor args are
  omitted: `GITHUB_APP_ID`, `GITHUB_APP_INSTALLATION_ID`,
  `GITHUB_APP_PRIVATE_KEY`, `GITHUB_APP_PRIVATE_KEY_PATH`. Match the
  existing env-fallback style at `gittoolkit.py:269–275`.
- Validate at construction time:
  - When `auth_type="github_app"`: `app_id` AND `installation_id` are
    required; **exactly one** of `private_key` / `private_key_path` must
    be set (raise `GitToolkitError` otherwise).
  - When `auth_type="pat"`: do NOT raise on missing/empty App-mode kwargs.
    Token-missing errors still surface lazily on first HTTP call via
    `_resolve_token` / `_prepare_github_context` (existing behaviour).
  - `auth_type` must be exactly `"pat"` or `"github_app"` (raise
    `GitToolkitError` on any other value).
- When `private_key_path` is set, read the file's contents and pass the
  PEM string to `_GitHubAppTokenProvider`. Defensively replace literal
  `\n` escape sequences with real newlines (env-var foot-gun documented
  in spec §7 Known Risks).
- Build `self._token_provider = _GitHubAppTokenProvider(...)` only when
  `auth_type == "github_app"`. Set to `None` in PAT mode.
- Add a new private method `_bearer_token(self) -> str`:
  - PAT mode: return `self.github_token`, raising `GitToolkitError`
    (same message as today) when it is `None`.
  - App mode: return `self._token_provider.get_token()`.
- Refactor the four direct readers of `self.github_token`:
  - `_prepare_github_context` (`gittoolkit.py:376–392`): replace the
    `token = self.github_token` block (lines 385–389) with
    `token = self._bearer_token()`. Keep the rest unchanged.
  - `_resolve_token` (`gittoolkit.py:578`): change the body to
    `return self._bearer_token()`.
  - `_fetch_file_sha` (`gittoolkit.py:424`): no change — it already
    accepts `token` as a parameter from its caller. The caller in
    `_create_pull_request_sync` (`gittoolkit.py:484`) already passes
    `token` from `_prepare_github_context`, so this remains correct.
  - All async public methods that today call `_resolve_token()`
    (`get_pull_request`, `list_pull_requests`, `get_pull_request_diff`,
    `add_pr_comment`, `submit_pr_review`, `ensure_webhook`) keep their
    existing call shape — `_resolve_token` is the seam.
- Write the unit tests listed in §Test Specification.

**NOT in scope**:
- Changing any public async method's signature.
- Changing the `_request` HTTP helper (it already takes `token` as a
  parameter, so swapping the source of that token is sufficient).
- Implementing `_GitHubAppTokenProvider` (done in TASK-1207).
- Wiring `GitHubReviewer` (TASK-1209).
- Adding logging to the provider or toolkit.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot-tools/src/parrot_tools/gittoolkit.py` | MODIFY | Extend `GitToolkitInput`, `GitToolkit.__init__`, add `_bearer_token`, refactor `_prepare_github_context` and `_resolve_token`. |
| `packages/ai-parrot-tools/tests/test_gittoolkit_github_app.py` | MODIFY | Append `TestGitToolkitAuthMode` test class per §Test Specification. |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
# Already present in gittoolkit.py (do not re-import):
import os                                              # line 25
import datetime as _dt                                 # line 24 (alias!)
from typing import Any, Dict, List, Literal, Optional  # line 27
from pydantic import BaseModel, Field, model_validator # line 32

# Added by TASK-1207 (already present in this file after that task):
import threading
from github import Auth, GithubIntegration

# This task adds no new imports.
```

### Existing Signatures to Use
```python
# packages/ai-parrot-tools/src/parrot_tools/gittoolkit.py

class GitToolkitError(RuntimeError):                       # line 38
    """Raised when the toolkit cannot satisfy a request."""

class GitToolkitInput(BaseModel):                          # line 42
    default_repository: Optional[str] = Field(default=None, ...)
    default_branch: str = Field(default="main", ...)
    github_token: Optional[str] = Field(default=None, ...)
    # add the 5 new fields here

@dataclass
class _GitHubContext:                                      # line 245
    repository: str
    base_branch: str
    token: str

# Added in TASK-1207:
class _GitHubAppTokenProvider:
    def __init__(self, app_id: int, installation_id: int, private_key_pem: str) -> None: ...
    def get_token(self) -> str: ...

class GitToolkit(AbstractToolkit):                         # line 253
    input_class = GitToolkitInput                          # line 256

    def __init__(                                          # line 258
        self,
        default_repository: Optional[str] = None,
        default_branch: str = "main",
        github_token: Optional[str] = None,
        **kwargs: Any,
    ) -> None:
        super().__init__(**kwargs)
        # current body (lines 265–275) sets:
        #   self.default_repository, self.default_branch, self.github_token
        # via env-var fallbacks. Extend this body — do NOT replace.

    # Four current direct readers of self.github_token:
    def _prepare_github_context(                           # line 376
        self, repository: Optional[str], base_branch: Optional[str],
    ) -> _GitHubContext:
        repo = repository or self.default_repository
        if not repo:
            raise GitToolkitError("A target repository is required ...")
        token = self.github_token                           # line 385 — replace
        if not token:                                       # line 386 — replace
            raise GitToolkitError("A GitHub personal access token is required ...")
        branch = base_branch or self.default_branch
        return _GitHubContext(repository=repo, base_branch=branch, token=token)

    def _resolve_token(self) -> str:                       # line 578
        if not self.github_token:
            raise GitToolkitError(
                "A GitHub personal access token is required via init argument or GITHUB_TOKEN."
            )
        return self.github_token

    # The HTTP helper — takes token as a PARAM, no internal read of self.github_token:
    @staticmethod
    def _request(                                          # line 395
        method: str, url: str, token: str, *, expected: int, **kwargs: Any,
    ) -> requests.Response: ...

    # The fetch helper — also takes token as a PARAM, no internal read of self.github_token:
    def _fetch_file_sha(                                   # line 424
        self, ctx: _GitHubContext, path: str, ref: str, token: str,
    ) -> Optional[str]: ...
```

### Current env-fallback pattern to mirror
```python
# gittoolkit.py:267–275 — copy this style for the new App-mode env vars:
self.default_repository = (
    default_repository
    or os.getenv("GIT_DEFAULT_REPOSITORY")
    or os.getenv("GITHUB_REPOSITORY")
)
self.default_branch = (
    default_branch or os.getenv("GIT_DEFAULT_BRANCH") or "main"
)
self.github_token = github_token or os.getenv("GITHUB_TOKEN")
```

### Does NOT Exist
- ~~`GitToolkit.github_app_token`~~ — no such public attribute. App
  tokens are reached only via `_bearer_token()`.
- ~~`GitToolkit.refresh_token()`~~ — refresh is internal to the provider.
- ~~`auth_type="oauth"`~~ — only `"pat"` and `"github_app"` are valid.
- ~~Modifying `_request` to read `self.github_token` directly~~ — it
  already takes `token` as a parameter; do NOT change its signature.
- ~~Adding `OAuthCredentialResolver`~~ — explicitly rejected in spec §1.

---

## Implementation Notes

### Constructor body sketch

```python
# Inside GitToolkit.__init__, after the existing self.default_* assignments
# (lines 267–275). Order: validate auth_type, resolve App fields, build provider.

self.auth_type: Literal["pat", "github_app"] = auth_type
if self.auth_type not in ("pat", "github_app"):
    raise GitToolkitError(
        f"Unsupported auth_type {self.auth_type!r}; expected 'pat' or 'github_app'."
    )

# Always store the new attributes (None in PAT mode) so dataclass-style
# introspection works.
self.app_id: Optional[int] = app_id or _coerce_int(os.getenv("GITHUB_APP_ID"))
self.installation_id: Optional[int] = (
    installation_id or _coerce_int(os.getenv("GITHUB_APP_INSTALLATION_ID"))
)
self._private_key_pem: Optional[str] = None
self._token_provider: Optional[_GitHubAppTokenProvider] = None

if self.auth_type == "github_app":
    if not self.app_id:
        raise GitToolkitError(
            "auth_type='github_app' requires app_id (or GITHUB_APP_ID env)."
        )
    if not self.installation_id:
        raise GitToolkitError(
            "auth_type='github_app' requires installation_id (or "
            "GITHUB_APP_INSTALLATION_ID env)."
        )

    inline_pem = private_key or os.getenv("GITHUB_APP_PRIVATE_KEY")
    pem_path = private_key_path or os.getenv("GITHUB_APP_PRIVATE_KEY_PATH")
    if inline_pem and pem_path:
        raise GitToolkitError(
            "auth_type='github_app': set EITHER private_key OR "
            "private_key_path, not both."
        )
    if not inline_pem and not pem_path:
        raise GitToolkitError(
            "auth_type='github_app' requires private_key or private_key_path "
            "(or GITHUB_APP_PRIVATE_KEY[_PATH] env)."
        )
    if pem_path:
        try:
            inline_pem = open(pem_path, "r", encoding="utf-8").read()
        except OSError as exc:
            raise GitToolkitError(
                f"Could not read GitHub App private key from {pem_path}: {exc}"
            ) from exc

    # Defensive: env-injected PEMs sometimes carry literal "\n".
    inline_pem = inline_pem.replace("\\n", "\n")
    self._private_key_pem = inline_pem

    self._token_provider = _GitHubAppTokenProvider(
        app_id=self.app_id,
        installation_id=self.installation_id,
        private_key_pem=inline_pem,
    )


def _coerce_int(value: Optional[str]) -> Optional[int]:
    """Module-level helper near the top of gittoolkit.py."""
    if value is None or value == "":
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None
```

### `_bearer_token` sketch

```python
def _bearer_token(self) -> str:
    if self.auth_type == "github_app":
        assert self._token_provider is not None
        return self._token_provider.get_token()
    # PAT mode
    if not self.github_token:
        raise GitToolkitError(
            "A GitHub personal access token is required via init argument or GITHUB_TOKEN."
        )
    return self.github_token
```

### Callsite refactors

- `_prepare_github_context` (line 376): replace lines 385–389 with
  `token = self._bearer_token()` (raises identically when PAT is missing).
- `_resolve_token` (line 578): collapse the body to
  `return self._bearer_token()`.

### Key Constraints

- Default behaviour MUST be unchanged: `GitToolkit(github_token="x")` and
  `GitToolkit()` (with `GITHUB_TOKEN` set) must work exactly as today.
- All public method signatures stay byte-identical.
- No new logging. The toolkit does not log today.
- `Literal["pat", "github_app"]` is already imported via the existing
  `Literal` import at `gittoolkit.py:27` — reuse it.

### References in Codebase

- `packages/ai-parrot-tools/src/parrot_tools/gittoolkit.py:269–275` —
  the env-fallback pattern to mirror.
- `packages/ai-parrot/src/parrot/bots/github_reviewer.py:476–513` —
  the `_build_jira_toolkit` `auth_type` branching pattern is the
  inspiration for the validation style.

---

## Acceptance Criteria

- [ ] `GitToolkitInput` exposes the five new fields with descriptions and
      defaults per spec §2 Data Models.
- [ ] `GitToolkit.__init__` accepts the five new kwargs (all optional);
      default `auth_type="pat"`.
- [ ] PAT-mode regression: every existing test in
      `packages/ai-parrot-tools/tests/test_gittoolkit_pr_methods.py` and
      `packages/ai-parrot/tests/test_gittoolkit.py` passes unchanged.
- [ ] `GitToolkit(auth_type="github_app", ...)` constructs successfully
      when all required fields are present; raises `GitToolkitError`
      eagerly when any required field is missing or when both PEM
      inputs are given.
- [ ] `_bearer_token()` returns the PAT in PAT mode and delegates to
      `_token_provider.get_token()` in App mode.
- [ ] `_request` and `_fetch_file_sha` signatures are unchanged.
- [ ] All new tests in the appended `TestGitToolkitAuthMode` class pass:
      `pytest packages/ai-parrot-tools/tests/test_gittoolkit_github_app.py -v`
- [ ] No linting errors:
      `ruff check packages/ai-parrot-tools/src/parrot_tools/gittoolkit.py`

---

## Test Specification

Append the following test class to
`packages/ai-parrot-tools/tests/test_gittoolkit_github_app.py` (created in
TASK-1207). Keep TASK-1207's tests above untouched.

```python
# Appended to packages/ai-parrot-tools/tests/test_gittoolkit_github_app.py
import os
from unittest.mock import patch, MagicMock

import pytest

from parrot_tools.gittoolkit import GitToolkit, GitToolkitError
from parrot_tools import gittoolkit as gt


PEM_SENTINEL = (
    "-----BEGIN PRIVATE KEY-----\nFAKE\n-----END PRIVATE KEY-----\n"
)


class TestGitToolkitAuthMode:

    # --- PAT mode regression -----------------------------------------

    def test_pat_mode_default(self):
        """auth_type defaults to 'pat' and existing usage works."""
        tk = GitToolkit(default_repository="o/r", github_token="pat_xxx")
        assert tk.auth_type == "pat"
        assert tk._token_provider is None
        assert tk._bearer_token() == "pat_xxx"

    def test_pat_mode_missing_token_raises_on_demand(self):
        """PAT mode does NOT raise at construction; raises on first call."""
        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop("GITHUB_TOKEN", None)
            tk = GitToolkit(default_repository="o/r")
            # Construction succeeds
            assert tk.auth_type == "pat"
            with pytest.raises(GitToolkitError, match="personal access token"):
                tk._bearer_token()

    def test_pat_mode_ignores_app_kwargs(self):
        """auth_type='pat' silently accepts (ignores) App-mode kwargs."""
        tk = GitToolkit(
            default_repository="o/r",
            github_token="pat_xxx",
            app_id=12345,
            installation_id=67890,
            private_key=PEM_SENTINEL,
        )
        assert tk.auth_type == "pat"
        assert tk._token_provider is None

    # --- auth_type validation ----------------------------------------

    def test_invalid_auth_type_raises(self):
        with pytest.raises(GitToolkitError, match="Unsupported auth_type"):
            GitToolkit(default_repository="o/r", auth_type="oauth")  # type: ignore[arg-type]

    # --- App-mode required fields ------------------------------------

    def test_app_mode_missing_app_id_raises(self):
        with pytest.raises(GitToolkitError, match="app_id"):
            GitToolkit(
                default_repository="o/r",
                auth_type="github_app",
                installation_id=67890,
                private_key=PEM_SENTINEL,
            )

    def test_app_mode_missing_installation_id_raises(self):
        with pytest.raises(GitToolkitError, match="installation_id"):
            GitToolkit(
                default_repository="o/r",
                auth_type="github_app",
                app_id=12345,
                private_key=PEM_SENTINEL,
            )

    def test_app_mode_missing_key_raises(self):
        with pytest.raises(GitToolkitError, match="private_key"):
            GitToolkit(
                default_repository="o/r",
                auth_type="github_app",
                app_id=12345,
                installation_id=67890,
            )

    def test_app_mode_rejects_both_keys(self, tmp_path):
        key_file = tmp_path / "key.pem"
        key_file.write_text(PEM_SENTINEL)
        with pytest.raises(GitToolkitError, match="EITHER"):
            GitToolkit(
                default_repository="o/r",
                auth_type="github_app",
                app_id=12345,
                installation_id=67890,
                private_key=PEM_SENTINEL,
                private_key_path=str(key_file),
            )

    # --- App-mode happy path -----------------------------------------

    def test_app_mode_builds_token_provider(self):
        tk = GitToolkit(
            default_repository="o/r",
            auth_type="github_app",
            app_id=12345,
            installation_id=67890,
            private_key=PEM_SENTINEL,
        )
        assert tk.auth_type == "github_app"
        assert isinstance(tk._token_provider, gt._GitHubAppTokenProvider)

    def test_app_mode_loads_pem_from_path(self, tmp_path):
        key_file = tmp_path / "key.pem"
        key_file.write_text(PEM_SENTINEL)
        tk = GitToolkit(
            default_repository="o/r",
            auth_type="github_app",
            app_id=12345,
            installation_id=67890,
            private_key_path=str(key_file),
        )
        assert tk._private_key_pem == PEM_SENTINEL

    def test_app_mode_replaces_literal_backslash_n(self):
        """Env-injected PEMs with literal '\\n' are normalised to real newlines."""
        pem_with_escapes = (
            "-----BEGIN PRIVATE KEY-----\\nFAKE\\n-----END PRIVATE KEY-----\\n"
        )
        tk = GitToolkit(
            default_repository="o/r",
            auth_type="github_app",
            app_id=12345,
            installation_id=67890,
            private_key=pem_with_escapes,
        )
        assert "\\n" not in tk._private_key_pem
        assert "\n" in tk._private_key_pem

    # --- _bearer_token routing ---------------------------------------

    def test_bearer_token_app_mode_delegates_to_provider(self):
        tk = GitToolkit(
            default_repository="o/r",
            auth_type="github_app",
            app_id=12345,
            installation_id=67890,
            private_key=PEM_SENTINEL,
        )
        with patch.object(tk._token_provider, "get_token", return_value="ghs_xxx"):
            assert tk._bearer_token() == "ghs_xxx"

    def test_request_uses_app_bearer(self):
        """End-to-end: an HTTP method emits Authorization: Bearer <app-token>."""
        tk = GitToolkit(
            default_repository="o/r",
            auth_type="github_app",
            app_id=12345,
            installation_id=67890,
            private_key=PEM_SENTINEL,
        )
        with patch.object(tk._token_provider, "get_token", return_value="ghs_xxx"):
            with patch("parrot_tools.gittoolkit.requests.request") as req:
                mock_resp = MagicMock()
                mock_resp.status_code = 200
                mock_resp.json.return_value = {}
                req.return_value = mock_resp
                import asyncio
                asyncio.run(tk.get_pull_request(pr_number=42))
        call = req.call_args
        assert call.kwargs["headers"]["Authorization"] == "Bearer ghs_xxx"
```

---

## Agent Instructions

1. Read the spec at `sdd/specs/github-app-auth-gittoolkit.spec.md` (§3 Module 2, §6, §7).
2. Activate the venv: `source .venv/bin/activate`.
3. Verify TASK-1207 ran: `python -c "from parrot_tools.gittoolkit import _GitHubAppTokenProvider"`.
4. Re-read `gittoolkit.py` and confirm line numbers in the contract above
   are still accurate. Update if needed.
5. Edit `GitToolkitInput` to add the five new fields.
6. Edit `GitToolkit.__init__` per the constructor body sketch.
7. Add module-level `_coerce_int` helper near the existing
   `_ensure_trailing_newline` static method or above `_GitHubContext`.
8. Add `_bearer_token` as a new private method on `GitToolkit`.
9. Refactor `_prepare_github_context` (line 376) and `_resolve_token`
   (line 578) to use `_bearer_token()`.
10. Append the `TestGitToolkitAuthMode` class to
    `packages/ai-parrot-tools/tests/test_gittoolkit_github_app.py`.
11. Run the new tests:
    `pytest packages/ai-parrot-tools/tests/test_gittoolkit_github_app.py -v`
12. Run the regression suites:
    `pytest packages/ai-parrot-tools/tests/ packages/ai-parrot/tests/test_gittoolkit.py -v`
13. Update the per-spec index status to `done`.
14. Move this file to `sdd/tasks/completed/`.

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**:
**Date**:
**Notes**:
