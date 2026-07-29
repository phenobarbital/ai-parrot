---
type: Wiki Overview
title: 'TASK-1207: Implement `_GitHubAppTokenProvider` helper + unit tests'
id: doc:sdd-tasks-completed-task-1207-github-app-token-provider-md
tags:
- overview
timestamp: '2026-07-16T08:34:12+00:00'
summary: GitHub Apps authenticate to the REST API with short-lived (≤1h) installation
relates_to:
- concept: mod:parrot_tools
  rel: mentions
- concept: mod:parrot_tools.gittoolkit
  rel: mentions
---

# TASK-1207: Implement `_GitHubAppTokenProvider` helper + unit tests

**Feature**: FEAT-179 — GitHub App Authentication for GitToolkit
**Spec**: `sdd/specs/github-app-auth-gittoolkit.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-1206
**Assigned-to**: unassigned

---

## Context

GitHub Apps authenticate to the REST API with short-lived (≤1h) installation
access tokens minted from a JWT signed with the App's private key. This task
delivers a thin in-process helper that owns that lifecycle — mint, cache,
refresh near expiry — so TASK-1208 can simply call `provider.get_token()`
to obtain the bearer used on every outbound HTTP request.

The provider is intentionally private to `gittoolkit.py` (mirrors how
`_GitHubContext` at `gittoolkit.py:245` is kept module-local) and uses
PyGithub's `GithubIntegration` (installed in TASK-1206) so we never touch
JWT signing by hand. See spec §3 Module 1 and §7 Known Risks (clock skew,
PEM newlines, token TTL race, thread safety).

---

## Scope

- Add a private class `_GitHubAppTokenProvider` to
  `packages/ai-parrot-tools/src/parrot_tools/gittoolkit.py` (do NOT create
  a new module — keep it module-local like `_GitHubContext`).
- The provider's constructor takes `app_id: int`, `installation_id: int`,
  `private_key_pem: str` (always a PEM string — file-path resolution
  happens in TASK-1208, not here).
- Method `get_token() -> str` returns a valid installation access token,
  re-minting via `Auth.AppAuth` + `GithubIntegration.get_access_token`
  when the cached token is missing or within **60 seconds** of expiry.
- Cache: in-process per-instance only. Single tuple of
  `(token: str, expires_at: datetime)` plus a `threading.Lock` guarding
  the refresh path (the toolkit calls into this provider from threads
  spawned by `asyncio.to_thread`).
- Raise `GitToolkitError` from `get_token()` if the underlying
  `GithubIntegration.get_access_token` call fails — message must include
  the GitHub error text.
- Write the unit tests listed in §Test Specification below.

**NOT in scope**:
- Touching `GitToolkit.__init__` / `_request` / `_resolve_token` (TASK-1208).
- Touching `GitHubReviewer` (TASK-1209).
- File-path handling for `private_key_path` (TASK-1208 resolves it to PEM
  before passing it here).
- Process-wide / module-level token cache shared across instances
  (deferred per spec §8 Open Questions).
- Retry / backoff on mint failures (spec §7 explicitly defers this).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot-tools/src/parrot_tools/gittoolkit.py` | MODIFY | Add `_GitHubAppTokenProvider` class near `_GitHubContext` (around line 245). Add `from github import Auth, GithubIntegration` to imports. Add `import threading` and `from datetime import datetime, timedelta, timezone` if not already present (today only `datetime as _dt` is imported — see `gittoolkit.py:24`). |
| `packages/ai-parrot-tools/tests/test_gittoolkit_github_app.py` | CREATE | Unit tests for `_GitHubAppTokenProvider` per §Test Specification. |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
# Existing in gittoolkit.py (already there — do not duplicate):
import asyncio                                    # gittoolkit.py:22
import base64                                      # gittoolkit.py:23
import datetime as _dt                             # gittoolkit.py:24  (note: aliased!)
import os                                          # gittoolkit.py:25
import difflib                                     # gittoolkit.py:29
import requests                                    # gittoolkit.py:31
from pydantic import BaseModel, Field, model_validator   # gittoolkit.py:32

# New, to be added by THIS task (top of file, alphabetised with stdlib then 3rd-party):
import threading                                   # stdlib
from github import Auth, GithubIntegration         # PyGithub>=2.1 (installed in TASK-1206)
```

Important: the existing file aliases `datetime` as `_dt`. Use `_dt.datetime`
and `_dt.timedelta` rather than re-importing. Reuse the existing alias.

### Existing Signatures to Use
```python
# packages/ai-parrot-tools/src/parrot_tools/gittoolkit.py
class GitToolkitError(RuntimeError):                       # line 38
    """Raised when the toolkit cannot satisfy a request."""

@dataclass
class _GitHubContext:                                      # line 245
    repository: str
    base_branch: str
    token: str

class GitToolkit(AbstractToolkit):                         # line 253
    input_class = GitToolkitInput                          # line 256

    def __init__(self, ...):                               # line 258
        ...
```

### PyGithub API the provider must call
```python
# PyGithub >= 2.1 (verify with `python -c "import github; print(github.__version__)"` after TASK-1206)
from github import Auth, GithubIntegration

auth = Auth.AppAuth(app_id, private_key_pem)       # app_id: int, private_key_pem: str
integration = GithubIntegration(auth=auth)
installation_auth = integration.get_access_token(installation_id)
# installation_auth has:
#   .token       -> str (the bearer to use)
#   .expires_at  -> datetime (UTC, tz-aware)
```

Note: PyGithub 2.x uses the keyword `auth=Auth.AppAuth(...)` form. If a
different version is installed, verify the exact constructor signature
before coding.

### Does NOT Exist
- ~~`parrot_tools.github_app`~~ — no such module today and this task does
  NOT create one. The provider stays inside `gittoolkit.py`.
- ~~`GitToolkit._token_provider`~~ — this attribute is added in TASK-1208,
  not here.
- ~~Direct `import jwt` / `import pyjwt`~~ — PyGithub vendors it; do not
  import directly.
- ~~`Auth.AppInstallationAuth`~~ — exists in PyGithub but is NOT the path
  used here; we use `Auth.AppAuth` + `GithubIntegration.get_access_token`.
- ~~`GithubIntegration(app_id, private_key)` positional form~~ — PyGithub
  2.x requires the `auth=` kwarg form.

---

## Implementation Notes

### Pattern to Follow

```python
# packages/ai-parrot-tools/src/parrot_tools/gittoolkit.py
# (add near _GitHubContext at line 245)

class _GitHubAppTokenProvider:
    """Mints + caches GitHub App installation access tokens.

    Single explicit installation. Token is cached in-process and refreshed
    when within 60 seconds of expiry. Safe to call from threads spawned by
    ``asyncio.to_thread``.
    """

    _REFRESH_LEEWAY = _dt.timedelta(seconds=60)

    def __init__(self, app_id: int, installation_id: int, private_key_pem: str) -> None:
        self._app_id = app_id
        self._installation_id = installation_id
        self._private_key_pem = private_key_pem
        self._token: Optional[str] = None
        self._expires_at: Optional[_dt.datetime] = None
        self._lock = threading.Lock()

    def get_token(self) -> str:
        with self._lock:
            now = _dt.datetime.now(_dt.timezone.utc)
            if (
                self._token is None
                or self._expires_at is None
                or self._expires_at - now <= self._REFRESH_LEEWAY
            ):
                self._refresh()
            return self._token  # type: ignore[return-value]

    def _refresh(self) -> None:
        try:
            auth = Auth.AppAuth(self._app_id, self._private_key_pem)
            integration = GithubIntegration(auth=auth)
            installation_auth = integration.get_access_token(self._installation_id)
        except Exception as exc:
            raise GitToolkitError(
                f"Failed to mint GitHub App installation token: {exc}"
            ) from exc
        self._token = installation_auth.token
        self._expires_at = installation_auth.expires_at
        if self._expires_at is not None and self._expires_at.tzinfo is None:
            # Defensive: PyGithub returns tz-aware UTC, but normalise just in case.
            self._expires_at = self._expires_at.replace(tzinfo=_dt.timezone.utc)
```

### Key Constraints

- **Reuse the existing `_dt` alias.** Do not add `from datetime import ...`.
- **Threading lock is mandatory.** `asyncio.to_thread` invocations from
  multiple coroutines can call `get_token` concurrently.
- **Refresh leeway is exactly 60 seconds** (per spec §5 acceptance criteria).
- **No retries.** A single mint failure raises `GitToolkitError`.
- **Logger:** the provider has no `self.logger`. Do not invent one. Errors
  surface via the raised exception.

### References in Codebase

- `packages/ai-parrot-tools/src/parrot_tools/gittoolkit.py:245` — `_GitHubContext`
  is the structural pattern (module-local private class).
- `packages/ai-parrot-tools/src/parrot_tools/gittoolkit.py:38` — `GitToolkitError`
  is the error to raise.

---

## Acceptance Criteria

- [ ] `_GitHubAppTokenProvider` class exists in `gittoolkit.py`, located
      near `_GitHubContext` (between lines ~240 and ~260).
- [ ] Class is NOT included in the `__all__` list at the bottom of the file.
- [ ] `from github import Auth, GithubIntegration` import is present.
- [ ] `import threading` is present.
- [ ] `get_token()` returns a string; raises `GitToolkitError` on mint
      failure with a message that includes the underlying exception text.
- [ ] All new tests in `test_gittoolkit_github_app.py` pass:
      `pytest packages/ai-parrot-tools/tests/test_gittoolkit_github_app.py -v`
- [ ] Existing tests still pass:
      `pytest packages/ai-parrot-tools/tests/test_gittoolkit_pr_methods.py -v`
- [ ] No linting errors: `ruff check packages/ai-parrot-tools/src/parrot_tools/gittoolkit.py`

---

## Test Specification

```python
# packages/ai-parrot-tools/tests/test_gittoolkit_github_app.py
"""Unit tests for _GitHubAppTokenProvider (FEAT-179, TASK-1207)."""
from __future__ import annotations

import datetime as _dt
from unittest.mock import patch, MagicMock

import pytest

from parrot_tools.gittoolkit import GitToolkitError
# _GitHubAppTokenProvider is private — import via attribute access on the module:
from parrot_tools import gittoolkit as gt


@pytest.fixture
def fake_pem() -> str:
    """Generate an in-memory RSA PEM. PyGithub will not actually parse it
    in unit tests because we mock GithubIntegration entirely."""
    return (
        "-----BEGIN PRIVATE KEY-----\n"
        "FAKE-DOES-NOT-NEED-TO-PARSE\n"
        "-----END PRIVATE KEY-----\n"
    )


def _mock_installation_auth(token: str, expires_in_seconds: int) -> MagicMock:
    inst = MagicMock()
    inst.token = token
    inst.expires_at = _dt.datetime.now(_dt.timezone.utc) + _dt.timedelta(
        seconds=expires_in_seconds
    )
    return inst


class TestGitHubAppTokenProvider:

    def test_first_call_mints_token(self, fake_pem):
        """First get_token() call invokes GithubIntegration once."""
        provider = gt._GitHubAppTokenProvider(
            app_id=12345, installation_id=67890, private_key_pem=fake_pem,
        )
        with patch.object(gt, "GithubIntegration") as gi_cls:
            gi_cls.return_value.get_access_token.return_value = (
                _mock_installation_auth("ghs_abc", expires_in_seconds=3600)
            )
            token = provider.get_token()
        assert token == "ghs_abc"
        gi_cls.return_value.get_access_token.assert_called_once_with(67890)

    def test_caches_until_near_expiry(self, fake_pem):
        """Second get_token() within the validity window does NOT re-mint."""
        provider = gt._GitHubAppTokenProvider(12345, 67890, fake_pem)
        with patch.object(gt, "GithubIntegration") as gi_cls:
            gi_cls.return_value.get_access_token.return_value = (
                _mock_installation_auth("ghs_abc", expires_in_seconds=3600)
            )
            provider.get_token()
            provider.get_token()
        # Only one mint despite two get_token() calls.
        assert gi_cls.return_value.get_access_token.call_count == 1

    def test_refreshes_when_near_expiry(self, fake_pem):
        """When cached token is ≤60s from expiry, get_token() re-mints."""
        provider = gt._GitHubAppTokenProvider(12345, 67890, fake_pem)
        with patch.object(gt, "GithubIntegration") as gi_cls:
            gi_cls.return_value.get_access_token.side_effect = [
                _mock_installation_auth("ghs_old", expires_in_seconds=30),
                _mock_installation_auth("ghs_new", expires_in_seconds=3600),
            ]
            first = provider.get_token()
            second = provider.get_token()
        assert first == "ghs_old"
        assert second == "ghs_new"
        assert gi_cls.return_value.get_access_token.call_count == 2

    def test_mint_failure_raises_gittoolkit_error(self, fake_pem):
        """A PyGithub exception is wrapped in GitToolkitError."""
        provider = gt._GitHubAppTokenProvider(12345, 67890, fake_pem)
        with patch.object(gt, "GithubIntegration") as gi_cls:
            gi_cls.return_value.get_access_token.side_effect = RuntimeError(
                "401 Bad credentials"
            )
            with pytest.raises(GitToolkitError, match="401 Bad credentials"):
                provider.get_token()

    def test_uses_app_auth_with_app_id_and_pem(self, fake_pem):
        """Provider hands (app_id, pem) to Auth.AppAuth on each refresh."""
        provider = gt._GitHubAppTokenProvider(12345, 67890, fake_pem)
        with patch.object(gt, "GithubIntegration") as gi_cls, patch.object(
            gt, "Auth"
        ) as auth_mod:
            gi_cls.return_value.get_access_token.return_value = (
                _mock_installation_auth("ghs_abc", 3600)
            )
            provider.get_token()
        auth_mod.AppAuth.assert_called_once_with(12345, fake_pem)
        gi_cls.assert_called_once_with(auth=auth_mod.AppAuth.return_value)
```

---

## Agent Instructions

1. Read the spec at `sdd/specs/github-app-auth-gittoolkit.spec.md` (§3 Module 1, §7 Known Risks).
2. Activate the venv: `source .venv/bin/activate`.
3. Verify TASK-1206 ran: `python -c "from github import Auth, GithubIntegration"`.
4. Add the imports (`threading`, `from github import Auth, GithubIntegration`)
   to `gittoolkit.py`. Reuse the existing `_dt` alias (`gittoolkit.py:24`).
5. Add the `_GitHubAppTokenProvider` class near `_GitHubContext` (line 245).
6. Create the test file at
   `packages/ai-parrot-tools/tests/test_gittoolkit_github_app.py`.
7. Run the tests:
   `pytest packages/ai-parrot-tools/tests/test_gittoolkit_github_app.py -v`.
8. Run the regression: `pytest packages/ai-parrot-tools/tests/ -v`.
9. Update the per-spec index status to `done`.
10. Move this file to `sdd/tasks/completed/`.

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**:
**Date**:
**Notes**:
