---
type: Wiki Overview
title: 'Feature Specification: GitHub App Authentication for GitToolkit'
id: doc:sdd-specs-github-app-auth-gittoolkit-spec-md
tags:
- overview
timestamp: '2026-07-16T08:34:12+00:00'
summary: authenticates against the GitHub REST API exclusively with a Personal Access
relates_to:
- concept: mod:parrot.bots.github_reviewer
  rel: mentions
- concept: mod:parrot.tools.toolkit
  rel: mentions
- concept: mod:parrot_tools
  rel: mentions
- concept: mod:parrot_tools.decorators
  rel: mentions
- concept: mod:parrot_tools.gittoolkit
  rel: mentions
- concept: mod:parrot_tools.jiratoolkit
  rel: mentions
- concept: mod:parrot_tools.toolkit
  rel: mentions
---

---
# SDD flow type and base branch (FEAT-145).
# - type: feature  (default)  → base_branch: dev (or any non-main branch)
# - type: hotfix              → base_branch MUST be: main
type: feature
base_branch: dev
---

# Feature Specification: GitHub App Authentication for GitToolkit

**Feature ID**: FEAT-179
**Date**: 2026-05-18
**Author**: Jesus Lara
**Status**: draft
**Target version**: 0.25.x

---

## 1. Motivation & Business Requirements

### Problem Statement

`GitToolkit` (`packages/ai-parrot-tools/src/parrot_tools/gittoolkit.py:253`)
authenticates against the GitHub REST API exclusively with a Personal Access
Token (PAT) read from the `GITHUB_TOKEN` env var or passed as `github_token`.
PATs are tied to a human user, expire on a rolling basis, leak that user's
full org-wide permissions, and cannot be safely shared across automated
deployments.

`GitHubReviewer` (`packages/ai-parrot/src/parrot/bots/github_reviewer.py:451`)
inherits the same limitation: every PR review, webhook registration, and
comment posted by an automated reviewer is attributed to the human whose PAT
is in use. This is the wrong identity model for a bot — it conflates human
and automation activity, surfaces the human's avatar on every review, and
breaks the moment that human leaves the project.

GitHub Apps solve this: they have their own identity, scoped permissions per
installation, short-lived installation access tokens (1 hour TTL) minted from
a signed JWT, and no dependency on any individual user account.

### Goals

- Add a second, explicit authentication mode (`auth_type="github_app"`) to
  `GitToolkit` that mints installation access tokens from a GitHub App's
  credentials (App ID, private key, installation ID).
- Keep `auth_type="pat"` working unchanged so existing deployments do not
  break and migration can be opt-in.
- Allow `GitHubReviewer._build_git_toolkit` to construct a toolkit in either
  mode based on configuration, with no behavioural change in PAT mode.
- Refresh installation tokens transparently before they expire so callers
  never have to manage TTL.
- Accept the private key as either a PEM string (for secrets-manager
  injection) or a file path (for mounted secret files).

### Non-Goals (explicitly out of scope)

- **Auto-discovery of installation IDs across orgs.** A toolkit instance is
  bound to a single explicit `installation_id`; multi-installation support
  is deferred to a follow-up spec.
- **OAuth User-to-Server (per-user) flows.** Out of scope — webhook events
  in `GitHubReviewer` have no caller identity, mirroring the same rejection
  documented at `github_reviewer.py:476` for Jira OAuth2 3LO.
- **GitHub Enterprise Server URL configuration.** API base URL stays
  `api.github.com`. ES support is a separate effort.
- **Replacing PAT support.** PAT remains a first-class option; this spec
  adds a *second* mode, not a replacement.
- **Webhook signature verification redesign.** Existing webhook secret
  validation is untouched.

---

## 2. Architectural Design

### Overview

`GitToolkit.__init__` gains a discriminator argument `auth_type: Literal["pat",
"github_app"]` (default `"pat"`). The constructor branches once:

- `pat` mode: today's behaviour. `github_token` (or `GITHUB_TOKEN`) is the
  bearer used on every request.
- `github_app` mode: `app_id`, `installation_id`, and one of
  (`private_key` PEM string | `private_key_path` file path) are required.
  A lazily-constructed `_GitHubAppTokenProvider` mints and caches an
  installation access token using PyGithub's `GithubIntegration`. Every
  outbound HTTP call routes its `Authorization` header through this
  provider instead of reading `self.github_token` directly.

A single new internal seam is introduced: a `_bearer_token()` method that
returns the bearer string to use for the next call. In `pat` mode it returns
`self.github_token`; in `github_app` mode it returns
`self._token_provider.get_token()`, which transparently refreshes when the
cached token is within 60 seconds of expiry.

`GitHubReviewer._build_git_toolkit` reads `GITHUB_AUTH_TYPE`
(default `"pat"`) and routes config accordingly. The reviewer fails closed
(returns `None`, disables itself) when required config for the selected
mode is missing, mirroring the existing PAT-missing behaviour at
`github_reviewer.py:454`.

### Component Diagram

```
                       GitHubReviewer._build_git_toolkit
                                  │
              ┌───────────────────┴───────────────────┐
              │                                       │
         auth_type="pat"                      auth_type="github_app"
              │                                       │
              ▼                                       ▼
       GitToolkit(github_token=PAT)        GitToolkit(app_id, installation_id,
              │                                        private_key|_path)
              │                                       │
              │                                       ▼
              │                       _GitHubAppTokenProvider (new helper)
              │                                       │
              │                                       │ uses PyGithub
              │                                       │  Auth.AppAuth +
              │                                       │  GithubIntegration
              │                                       ▼
              │                          installation access token (cached, ≤1h)
              │                                       │
              └───────────────┬───────────────────────┘
                              ▼
                  GitToolkit._bearer_token() (new internal seam)
                              │
                              ▼
                  GitToolkit._request() (existing, unchanged signature)
                              │
                              ▼
                       api.github.com
```

### Integration Points

| Existing Component | Integration Type | Notes |
|---|---|---|
| `parrot_tools.gittoolkit.GitToolkit` | extends `__init__`; adds private `_bearer_token` / `_token_provider`; modifies `_request`/`_fetch_file_sha` callsites | All existing tools (`create_pull_request`, `get_pull_request`, `get_pull_request_diff`, `add_pr_comment`, `submit_pr_review`, `ensure_webhook`, `generate_git_apply_patch`) keep their public signatures. |
| `parrot_tools.toolkit.AbstractToolkit` | re-export of `parrot.tools.toolkit.AbstractToolkit` (`packages/ai-parrot-tools/src/parrot_tools/toolkit.py:2`) | No changes — base class stays the same. |
| `parrot.bots.github_reviewer.GitHubReviewer._build_git_toolkit` | modified | Reads `GITHUB_AUTH_TYPE` via `navconfig.config`, builds toolkit in selected mode, logs and disables on missing config. |
| `_prepare_github_context` / `_resolve_token` (`gittoolkit.py:376, 578`) | refactored | Return value of `_resolve_token()` becomes "the current bearer", regardless of mode. |

### Data Models

```python
# packages/ai-parrot-tools/src/parrot_tools/gittoolkit.py

class GitToolkitInput(BaseModel):
    """Default configuration shared by all tools in the toolkit (extended)."""

    default_repository: Optional[str] = Field(default=None, ...)
    default_branch: str = Field(default="main", ...)

    # PAT mode (existing)
    github_token: Optional[str] = Field(default=None, ...)

    # GitHub App mode (new)
    auth_type: Literal["pat", "github_app"] = Field(
        default="pat",
        description="Authentication backend. 'pat' uses github_token; "
                    "'github_app' uses app_id + installation_id + private key.",
    )
    app_id: Optional[int] = Field(
        default=None,
        description="GitHub App ID (required when auth_type='github_app').",
    )
    installation_id: Optional[int] = Field(
        default=None,
        description="Installation ID for the org/account the App is installed "
                    "in (required when auth_type='github_app').",
    )
    private_key: Optional[str] = Field(
        default=None,
        description="PEM contents of the App's private key. Mutually exclusive "
                    "with private_key_path.",
    )
    private_key_path: Optional[str] = Field(
        default=None,
        description="Filesystem path to the App's private key PEM. Mutually "
                    "exclusive with private_key.",
    )
```

### New Public Interfaces

```python
# packages/ai-parrot-tools/src/parrot_tools/gittoolkit.py

class GitToolkit(AbstractToolkit):
    """Toolkit dedicated to Git patch generation and GitHub pull requests."""

    def __init__(
        self,
        default_repository: Optional[str] = None,
        default_branch: str = "main",
        github_token: Optional[str] = None,
        # NEW (all optional; required only when auth_type='github_app'):
        auth_type: Literal["pat", "github_app"] = "pat",
        app_id: Optional[int] = None,
        installation_id: Optional[int] = None,
        private_key: Optional[str] = None,
        private_key_path: Optional[str] = None,
        **kwargs: Any,
    ) -> None: ...

    # Existing public coroutine methods retain their exact signatures:
    async def generate_git_apply_patch(...) -> Dict[str, Any]: ...
    async def create_pull_request(...) -> Dict[str, Any]: ...
    async def get_pull_request(...) -> Dict[str, Any]: ...
    async def list_pull_requests(...) -> List[Dict[str, Any]]: ...
    async def get_pull_request_diff(...) -> Dict[str, Any]: ...
    async def add_pr_comment(...) -> Dict[str, Any]: ...
    async def submit_pr_review(...) -> Dict[str, Any]: ...
    async def ensure_webhook(...) -> Dict[str, Any]: ...
```

Internal-only (not exposed as tools):

```python
class _GitHubAppTokenProvider:
    """Mints + caches GitHub App installation access tokens.

    Single explicit installation; no per-repo auto-resolution.
    """

    def __init__(
        self,
        app_id: int,
        installation_id: int,
        private_key_pem: str,  # always resolved to PEM string before construction
    ) -> None: ...

    def get_token(self) -> str:
        """Return a valid installation token, refreshing when ≤60s from expiry."""
```

---

## 3. Module Breakdown

### Module 1: `_GitHubAppTokenProvider` helper

- **Path**: `packages/ai-parrot-tools/src/parrot_tools/gittoolkit.py` (same file, private class)
- **Responsibility**: Hold App credentials, mint installation access tokens
  via PyGithub's `GithubIntegration`, cache the token in memory with its
  `expires_at`, and refresh transparently when within 60 seconds of expiry.
- **Depends on**: PyGithub (new dep); nothing internal.

### Module 2: `GitToolkit.__init__` and bearer-token plumbing

- **Path**: `packages/ai-parrot-tools/src/parrot_tools/gittoolkit.py`
- **Responsibility**:
  - Accept the new constructor kwargs (`auth_type`, `app_id`,
    `installation_id`, `private_key`, `private_key_path`).
  - Validate that exactly the right config is present for the chosen mode
    (raise `GitToolkitError` on init when invalid).
  - Read PEM contents from `private_key_path` if `private_key` is not set.
  - Build a `_GitHubAppTokenProvider` lazily when `auth_type == "github_app"`.
  - Introduce a `_bearer_token()` method returning the current bearer.
  - Update `_request`, `_fetch_file_sha`, `_prepare_github_context`, and
    `_resolve_token` to call `_bearer_token()` instead of returning
    `self.github_token` directly.
- **Depends on**: Module 1.

### Module 3: `GitHubReviewer` wiring

- **Path**: `packages/ai-parrot/src/parrot/bots/github_reviewer.py`
- **Responsibility**: Modify `_build_git_toolkit` (`github_reviewer.py:451`)
  to read `GITHUB_AUTH_TYPE` (default `"pat"`) from `navconfig.config` and:
  - PAT mode: read `GITHUB_TOKEN` (existing behaviour, unchanged).
  - App mode: read `GITHUB_APP_ID`, `GITHUB_APP_INSTALLATION_ID`, and
    `GITHUB_APP_PRIVATE_KEY` *or* `GITHUB_APP_PRIVATE_KEY_PATH`.
  - In either mode, log a clear error and return `None` (disabling the
    reviewer) when required config is absent — mirror the existing
    PAT-missing fail-closed pattern at `github_reviewer.py:454`.
- **Depends on**: Module 2.

### Module 4: Dependency declaration

- **Path**: `packages/ai-parrot-tools/pyproject.toml`
- **Responsibility**: Add `PyGithub>=2.1` to the `dependencies` list (the
  package currently only depends on `ai-parrot`). PyGithub vendors
  `cryptography` and `pyjwt` transitively, so no extra direct deps are
  needed for RS256 signing.
- **Depends on**: nothing.

### Module 5: Tests

- **Path**: `packages/ai-parrot-tools/tests/test_gittoolkit_github_app.py`
  (new) and additions to `packages/ai-parrot-tools/tests/test_gittoolkit_pr_methods.py`.
- **Responsibility**: see §4 below.
- **Depends on**: Modules 1–3.

---

## 4. Test Specification

### Unit Tests

| Test | Module | Description |
|---|---|---|
| `test_init_pat_mode_defaults` | Module 2 | `GitToolkit()` defaults to `auth_type="pat"`; reading `GITHUB_TOKEN` still works. No App fields required. |
| `test_init_app_mode_requires_app_id` | Module 2 | `GitToolkit(auth_type="github_app", installation_id=1, private_key="...")` raises `GitToolkitError` (missing app_id). |
| `test_init_app_mode_requires_installation_id` | Module 2 | Missing `installation_id` raises `GitToolkitError`. |
| `test_init_app_mode_requires_key` | Module 2 | Neither `private_key` nor `private_key_path` → `GitToolkitError`. |
| `test_init_app_mode_rejects_both_keys` | Module 2 | Setting both `private_key` and `private_key_path` raises `GitToolkitError`. |
| `test_init_app_mode_loads_pem_from_path` | Module 2 | `private_key_path=<tmp.pem>` results in the PEM string being passed to the token provider. |
| `test_pat_mode_ignores_app_kwargs` | Module 2 | When `auth_type="pat"`, App-mode kwargs are silently ignored (do not raise). |
| `test_token_provider_caches_until_near_expiry` | Module 1 | A mocked `GithubIntegration.get_access_token` is called exactly once across two `get_token()` calls when the cached token is still ≥60s valid. |
| `test_token_provider_refreshes_when_near_expiry` | Module 1 | When cached `expires_at` is ≤60s away, `get_token()` calls `GithubIntegration.get_access_token` again. |
| `test_request_uses_app_bearer` | Module 2 | With `auth_type="github_app"` and a mocked token provider returning `"ghs_xxx"`, `_request()` sends `Authorization: Bearer ghs_xxx`. |
| `test_request_uses_pat_bearer` | Module 2 | With `auth_type="pat"`, `_request()` sends `Authorization: Bearer <PAT>` (existing behaviour, kept under regression). |
| `test_reviewer_pat_mode_existing_path` | Module 3 | `GITHUB_AUTH_TYPE` unset / `"pat"` + `GITHUB_TOKEN` set → existing PAT toolkit built (regression). |
| `test_reviewer_app_mode_full_config` | Module 3 | `GITHUB_AUTH_TYPE=github_app` + all App env vars set → App-mode toolkit built. |
| `test_reviewer_app_mode_missing_config_disables` | Module 3 | `GITHUB_AUTH_TYPE=github_app` with no App vars → `_build_git_toolkit()` returns `None` and emits an error log. |

### Integration Tests

| Test | Description |
|---|---|
| `test_app_token_minted_against_fake_server` | Stand up a tiny fake GitHub server (responses to `/app/installations/{id}/access_tokens`); confirm an App-mode `GitToolkit.get_pull_request` performs one token mint + the PR fetch with the minted token. |

> Note: tests use `responses` / `pytest-mock` to stub HTTP calls.
> No real GitHub credentials touch CI.

### Test Data / Fixtures

```python
# packages/ai-parrot-tools/tests/test_gittoolkit_github_app.py

@pytest.fixture
def fake_pem(tmp_path) -> str:
    """Generate an in-memory RSA PEM suitable for PyGithub's Auth.AppAuth."""
    from cryptography.hazmat.primitives.asymmetric import rsa
    from cryptography.hazmat.primitives import serialization
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    return key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    ).decode("ascii")


@pytest.fixture
def app_toolkit(fake_pem) -> GitToolkit:
    return GitToolkit(
        default_repository="owner/repo",
        auth_type="github_app",
        app_id=12345,
        installation_id=67890,
        private_key=fake_pem,
    )
```

---

## 5. Acceptance Criteria

> This feature is complete when ALL of the following are true:

- [ ] `GitToolkit(auth_type="pat", github_token="x")` behaves identically
      to today's `GitToolkit(github_token="x")` (regression: all existing
      `test_gittoolkit*.py` tests still pass without modification).
- [ ] `GitToolkit(auth_type="github_app", app_id=N, installation_id=M,
      private_key=PEM)` instantiates successfully; the resulting object's
      first HTTP call carries an `Authorization: Bearer <installation token>`
      header minted via PyGithub's `GithubIntegration`.
- [ ] `private_key_path="/path/to/key.pem"` is accepted as a fully equivalent
      alternative to `private_key=PEM_STRING`; setting both raises
      `GitToolkitError`.
- [ ] Installation tokens are cached in-process and refreshed transparently
      when within 60 seconds of expiry.
- [ ] `GitHubReviewer` honours a new `GITHUB_AUTH_TYPE` env (default `"pat"`)
      and routes constructor kwargs accordingly; missing required config
      for the selected mode disables the reviewer with a clear error log,
      following the same fail-closed shape as `github_reviewer.py:454`.
- [ ] `auth_type="github_app"` with any required field missing raises
      `GitToolkitError` *at construction time*, not on first HTTP call.
- [ ] `PyGithub>=2.1` is added to `packages/ai-parrot-tools/pyproject.toml`.
- [ ] All unit tests pass (`pytest packages/ai-parrot-tools/tests/ -v`).
- [ ] No breaking changes to existing public method signatures of `GitToolkit`.

---

## 6. Codebase Contract

> **CRITICAL — Anti-Hallucination Anchor**
> This section is the single source of truth for what exists in the codebase.
> Implementation agents MUST NOT reference imports, attributes, or methods
> not listed here without first verifying they exist via `grep` or `read`.

### Verified Imports

```python
# Existing (confirmed)
from parrot_tools.gittoolkit import GitToolkit, GitToolkitError                 # gittoolkit.py:809
from parrot_tools.toolkit import AbstractToolkit, ToolkitTool                   # toolkit.py:2 (re-export)
from parrot.tools.toolkit import AbstractToolkit                                # parrot/tools/toolkit.py:191
from parrot_tools.decorators import tool_schema                                 # decorators.py:2 (re-export)
from parrot.bots.github_reviewer import GitHubReviewer                          # github_reviewer.py
from navconfig import config                                                    # github_reviewer.py:42
from parrot_tools.jiratoolkit import JiraToolkit                                # github_reviewer.py:51

# New (to be added)
from github import Auth, GithubIntegration            # PyGithub>=2.1 — verify after `uv add PyGithub`
```

### Existing Class Signatures

```python
# packages/ai-parrot-tools/src/parrot_tools/gittoolkit.py
class GitToolkit(AbstractToolkit):                              # line 253
    input_class = GitToolkitInput                                # line 256

    def __init__(                                                # line 258
        self,
        default_repository: Optional[str] = None,
        default_branch: str = "main",
        github_token: Optional[str] = None,
        **kwargs: Any,
    ) -> None: ...

    # Internal HTTP helper — every external call routes through here.
    @staticmethod
    def _request(                                                # line 395
        method: str, url: str, token: str, *, expected: int, **kwargs: Any,
    ) -> requests.Response: ...

    # GitHub context preparation (returns _GitHubContext with the bearer in `.token`).
    def _prepare_github_context(                                 # line 376
        self, repository: Optional[str], base_branch: Optional[str],
    ) -> _GitHubContext: ...

    # Read-side helpers that re-read self.github_token directly.
    def _resolve_token(self) -> str:                             # line 578
        if not self.github_token: raise GitToolkitError(...)
        return self.github_token

    # Existing fetch helper that ALSO reads self.github_token via direct param.
    def _fetch_file_sha(                                         # line 424
        self, ctx: _GitHubContext, path: str, ref: str, token: str,
    ) -> Optional[str]: ...

# packages/ai-parrot/src/parrot/bots/github_reviewer.py
class GitHubReviewer(Agent):
    def _build_git_toolkit(self) -> Optional[GitToolkit]:        # line 451
        token = config.get("GITHUB_TOKEN")                       # line 452
        if not token:
            self.logger.error("GitHubReviewer: GITHUB_TOKEN is not set; ...")
            return None
        return GitToolkit(
            default_repository=self.repository,
            default_branch=config.get("GIT_DEFAULT_BRANCH", fallback="main"),
            github_token=token,
        )

# packages/ai-parrot/src/parrot/tools/toolkit.py
class AbstractToolkit(ABC):                                      # line 191
    input_class: Optional[Type[BaseModel]] = None                # line 219
```

### Integration Points

| New Component | Connects To | Via | Verified At |
|---|---|---|---|
| `_GitHubAppTokenProvider` | `github.Auth.AppAuth` + `github.GithubIntegration.get_access_token(installation_id)` | direct PyGithub call | PyGithub docs (post-`uv add` verification) |
| `GitToolkit._bearer_token` (new) | `_GitHubAppTokenProvider.get_token()` *or* `self.github_token` | branch on `self.auth_type` | new code |
| `GitToolkit._request` / `_fetch_file_sha` | `self._bearer_token()` | parameter substitution at call sites | `gittoolkit.py:395,424` |
| `GitToolkit._prepare_github_context` | `self._bearer_token()` (in place of `self.github_token`) | direct replacement | `gittoolkit.py:386` |
| `GitToolkit._resolve_token` | `self._bearer_token()` | direct replacement | `gittoolkit.py:578` |
| `GitHubReviewer._build_git_toolkit` | new `auth_type` branch reading `GITHUB_AUTH_TYPE` and App env vars | `navconfig.config.get(...)` | `github_reviewer.py:451–463` |

### Configuration / Environment Variables

| Variable | Mode | Purpose |
|---|---|---|
| `GITHUB_TOKEN` | pat | Existing PAT bearer (unchanged). |
| `GIT_DEFAULT_REPOSITORY` / `GITHUB_REPOSITORY` | both | Existing default repo override (`gittoolkit.py:270`). |
| `GIT_DEFAULT_BRANCH` | both | Existing default branch (`gittoolkit.py:273`, `github_reviewer.py:461`). |
| `GITHUB_AUTH_TYPE` | new | `pat` (default) or `github_app`. Read by `GitHubReviewer._build_git_toolkit`. |
| `GITHUB_APP_ID` | github_app | Integer App ID. |
| `GITHUB_APP_INSTALLATION_ID` | github_app | Integer installation ID for the org the App is installed in. |
| `GITHUB_APP_PRIVATE_KEY` | github_app | PEM contents (multi-line). Mutually exclusive with `_PATH`. |
| `GITHUB_APP_PRIVATE_KEY_PATH` | github_app | Filesystem path to `.pem`. Mutually exclusive with the inline form. |

### Does NOT Exist (Anti-Hallucination)

- ~~`parrot_tools.github_app`~~ — no such module today; App helpers live
  *inside* `gittoolkit.py` as a private class.
- ~~`GitToolkit.refresh_token()`~~ — no such public method. Refresh is
  internal to `_GitHubAppTokenProvider.get_token()`.
- ~~`GitToolkit.github_app_token`~~ — no such public attribute. Bearer is
  resolved via `_bearer_token()` only.
- ~~`PyJWT` / `pyjwt`~~ — NOT a direct dependency. PyGithub bundles it
  transitively; do not import `jwt` directly.
- ~~`GithubIntegration(app_id, private_key)` positional form~~ — PyGithub
  2.x uses the `auth=Auth.AppAuth(app_id, private_key)` form. Verify the
  exact call signature against the installed version before coding.

…(truncated)…
