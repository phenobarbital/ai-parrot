---
type: Wiki Overview
title: 'TASK-1209: Wire `GitHubReviewer._build_git_toolkit` to honour `GITHUB_AUTH_TYPE`'
id: doc:sdd-tasks-completed-task-1209-github-reviewer-auth-type-wiring-md
tags:
- overview
timestamp: '2026-07-16T08:34:12+00:00'
summary: Today `GitHubReviewer._build_git_toolkit` (`github_reviewer.py:451`) only
relates_to:
- concept: mod:parrot.bots
  rel: mentions
- concept: mod:parrot.bots.github_reviewer
  rel: mentions
- concept: mod:parrot_tools.gittoolkit
  rel: mentions
- concept: mod:parrot_tools.jiratoolkit
  rel: mentions
---

# TASK-1209: Wire `GitHubReviewer._build_git_toolkit` to honour `GITHUB_AUTH_TYPE`

**Feature**: FEAT-179 — GitHub App Authentication for GitToolkit
**Spec**: `sdd/specs/github-app-auth-gittoolkit.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: S (< 2h)
**Depends-on**: TASK-1208
**Assigned-to**: unassigned

---

## Context

Today `GitHubReviewer._build_git_toolkit` (`github_reviewer.py:451`) only
knows how to build the toolkit with a PAT. After TASK-1208 the toolkit
accepts an `auth_type` discriminator. This task closes the loop: the
reviewer reads `GITHUB_AUTH_TYPE` (default `"pat"`) from `navconfig.config`
and routes config accordingly, so an operator can switch a deployment from
PAT to GitHub App identity by setting env vars only.

See spec §3 Module 3, §5 Acceptance Criteria, and the structural inspiration
`_build_jira_toolkit` (`github_reviewer.py:465–513`).

---

## Scope

- Modify `GitHubReviewer._build_git_toolkit` (`github_reviewer.py:451`) to:
  1. Read `auth_type = (config.get("GITHUB_AUTH_TYPE") or "pat").lower()`.
  2. PAT mode (`"pat"`): preserve today's behaviour exactly — read
     `GITHUB_TOKEN`, log + return `None` if absent.
  3. App mode (`"github_app"`): read `GITHUB_APP_ID`,
     `GITHUB_APP_INSTALLATION_ID`, and `GITHUB_APP_PRIVATE_KEY`
     *or* `GITHUB_APP_PRIVATE_KEY_PATH`. Log + return `None` if any
     required field is missing. Construct
     `GitToolkit(auth_type="github_app", app_id=..., installation_id=...,
     private_key=...|private_key_path=...)`.
  4. Unknown `auth_type` value: log a clear error and return `None`
     (mirrors the JIRA fallback behaviour at lines 476–483 stylistically,
     but here we fail closed rather than silently downgrade — the reviewer
     having NO identity is safer than picking the wrong one).
- The log lines must keep the existing prefix `"GitHubReviewer: …"` so
  operators grep the same pattern.
- Add the unit tests listed in §Test Specification.

**NOT in scope**:
- Touching `_build_jira_toolkit` or any other method of `GitHubReviewer`.
- Telegram alerting on disable (deferred per spec §8 Open Questions).
- Changes to `GitToolkit` itself (TASK-1208).
- Changes to webhook signature verification.
- Changes to any other agent that uses `GitToolkit`.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/bots/github_reviewer.py` | MODIFY | Rewrite `_build_git_toolkit` (lines 451–463) to honour `GITHUB_AUTH_TYPE`. |
| `packages/ai-parrot/tests/test_github_reviewer_auth.py` | CREATE | Unit tests for the three modes (PAT, App-full-config, App-missing-config). |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
# Already imported at github_reviewer.py (verbatim — do not duplicate):
from navconfig import config                                      # line 42
from parrot_tools.gittoolkit import GitToolkit                    # line 50
from parrot_tools.jiratoolkit import JiraToolkit                  # line 51
from parrot.bots import Agent                                     # line 45
from typing import Any, Dict, Optional, ...                       # line 38

# This task adds NO new imports.
```

### Existing Signature to Modify
```python
# packages/ai-parrot/src/parrot/bots/github_reviewer.py:451
def _build_git_toolkit(self) -> Optional[GitToolkit]:
    token = config.get("GITHUB_TOKEN")                            # line 452
    if not token:                                                  # line 453
        self.logger.error(                                         # line 454
            "GitHubReviewer: GITHUB_TOKEN is not set; the agent will "
            "disable itself (no PR fetch/review/webhook calls)."
        )
        return None
    return GitToolkit(
        default_repository=self.repository,
        default_branch=config.get("GIT_DEFAULT_BRANCH", fallback="main"),
        github_token=token,
    )
```

### Inspiration pattern (DO follow this style)
```python
# packages/ai-parrot/src/parrot/bots/github_reviewer.py:465 — _build_jira_toolkit
def _build_jira_toolkit(self) -> Optional[JiraToolkit]:
    auth_type = (config.get("JIRA_AUTH_TYPE") or "").lower()      # line 476
    ...
    effective = auth_type or "basic_auth"
    toolkit_kwargs: Dict[str, Any] = {
        "server_url": config.get("JIRA_INSTANCE"),
        "auth_type": effective,
        ...
    }
    if effective == "basic_auth":
        username = config.get("JIRA_USERNAME")
        password = config.get("JIRA_API_TOKEN")
        if not (username and password):
            self.logger.error(...)
            return None
        toolkit_kwargs["username"] = username
        toolkit_kwargs["password"] = password
    return JiraToolkit(**toolkit_kwargs)
```

Mirror this shape: read `auth_type`, build a `toolkit_kwargs` dict, fail
closed via `return None` + a `self.logger.error` on missing config.

### `GitToolkit` constructor after TASK-1208
```python
class GitToolkit(AbstractToolkit):
    def __init__(
        self,
        default_repository: Optional[str] = None,
        default_branch: str = "main",
        github_token: Optional[str] = None,
        auth_type: Literal["pat", "github_app"] = "pat",
        app_id: Optional[int] = None,
        installation_id: Optional[int] = None,
        private_key: Optional[str] = None,
        private_key_path: Optional[str] = None,
        **kwargs: Any,
    ) -> None: ...
```

### Does NOT Exist
- ~~`navconfig.config.get("GITHUB_APP_*")` returning ints~~ — `navconfig`
  returns strings (or `None`). Convert to `int(value)` explicitly when
  constructing `GitToolkit`; let `int()` raise on bad input — the toolkit's
  own validation will surface it cleanly in any case via `GitToolkitError`.
  Actually: pass strings directly — `GitToolkit.__init__` from TASK-1208
  already coerces via its `_coerce_int` helper for env-sourced values,
  but when WE pass via kwargs we are responsible for coercion. Safest
  pattern: explicit `int(...)`.
- ~~An auto-fallback from `github_app` → `pat`~~ — fail closed. Do not
  silently downgrade.
- ~~A new method `_build_github_app_toolkit`~~ — keep all branching inside
  the existing `_build_git_toolkit` method.
- ~~`self.app_id` / `self.installation_id` attributes on `GitHubReviewer`~~
  — do not stash them on the reviewer; they live only in `GitToolkit`.

---

## Implementation Notes

### Sketch

```python
# packages/ai-parrot/src/parrot/bots/github_reviewer.py — replaces lines 451–463

def _build_git_toolkit(self) -> Optional[GitToolkit]:
    auth_type = (config.get("GITHUB_AUTH_TYPE") or "pat").lower()
    default_branch = config.get("GIT_DEFAULT_BRANCH", fallback="main")

    if auth_type == "pat":
        token = config.get("GITHUB_TOKEN")
        if not token:
            self.logger.error(
                "GitHubReviewer: GITHUB_TOKEN is not set; the agent will "
                "disable itself (no PR fetch/review/webhook calls)."
            )
            return None
        return GitToolkit(
            default_repository=self.repository,
            default_branch=default_branch,
            github_token=token,
        )

    if auth_type == "github_app":
        app_id_raw = config.get("GITHUB_APP_ID")
        installation_id_raw = config.get("GITHUB_APP_INSTALLATION_ID")
        private_key = config.get("GITHUB_APP_PRIVATE_KEY")
        private_key_path = config.get("GITHUB_APP_PRIVATE_KEY_PATH")

        missing = []
        if not app_id_raw:
            missing.append("GITHUB_APP_ID")
        if not installation_id_raw:
            missing.append("GITHUB_APP_INSTALLATION_ID")
        if not (private_key or private_key_path):
            missing.append("GITHUB_APP_PRIVATE_KEY or GITHUB_APP_PRIVATE_KEY_PATH")
        if missing:
            self.logger.error(
                "GitHubReviewer: GITHUB_AUTH_TYPE=github_app but missing %s; "
                "the agent will disable itself (no PR fetch/review/webhook calls).",
                ", ".join(missing),
            )
            return None

        try:
            return GitToolkit(
                default_repository=self.repository,
                default_branch=default_branch,
                auth_type="github_app",
                app_id=int(app_id_raw),
                installation_id=int(installation_id_raw),
                private_key=private_key,
                private_key_path=private_key_path,
            )
        except (ValueError, Exception) as exc:  # GitToolkitError surfaces as Exception
            self.logger.error(
                "GitHubReviewer: failed to build GitHub App toolkit: %s. "
                "The agent will disable itself.", exc,
            )
            return None

    self.logger.error(
        "GitHubReviewer: unknown GITHUB_AUTH_TYPE=%r (expected 'pat' or "
        "'github_app'); the agent will disable itself.", auth_type,
    )
    return None
```

### Key Constraints

- PAT branch must produce *bit-identical* behaviour to today (same log
  message wording, same constructor call shape).
- App-mode `try/except` swallows toolkit-construction errors and logs +
  returns `None` — fail closed, never bubble out of the reviewer init.
- `default_branch` is computed once at the top so both branches share it.
- No new attributes on `self`.
- Use `self.logger` (consistent with existing code at line 454, 478, 481).

### References in Codebase

- `packages/ai-parrot/src/parrot/bots/github_reviewer.py:465–513` —
  `_build_jira_toolkit` shows the discriminator + per-mode kwargs pattern.
- `packages/ai-parrot-tools/src/parrot_tools/gittoolkit.py` — the
  constructor whose validation the reviewer relies on.

---

## Acceptance Criteria

- [ ] `GITHUB_AUTH_TYPE` unset → identical PAT-mode behaviour as today
      (regression: existing GitHubReviewer tests still pass).
- [ ] `GITHUB_AUTH_TYPE=pat` with no `GITHUB_TOKEN` → `_build_git_toolkit`
      returns `None` and the existing error log is emitted.
- [ ] `GITHUB_AUTH_TYPE=github_app` with all required vars → returns a
      `GitToolkit` whose `auth_type == "github_app"`.
- [ ] `GITHUB_AUTH_TYPE=github_app` with any required var missing →
      returns `None` and logs an error naming the missing vars.
- [ ] `GITHUB_AUTH_TYPE=garbage` → returns `None` and logs an unknown-mode
      error.
- [ ] `GitToolkitError` from `GitToolkit.__init__` does NOT propagate out
      of `_build_git_toolkit`; it is caught and logged.
- [ ] All new tests pass:
      `pytest packages/ai-parrot/tests/test_github_reviewer_auth.py -v`
- [ ] Existing `test_gittoolkit*` suites still pass.
- [ ] No linting errors:
      `ruff check packages/ai-parrot/src/parrot/bots/github_reviewer.py`

---

## Test Specification

```python
# packages/ai-parrot/tests/test_github_reviewer_auth.py
"""Unit tests for GitHubReviewer._build_git_toolkit auth_type routing (FEAT-179, TASK-1209)."""
from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from parrot.bots.github_reviewer import GitHubReviewer
from parrot_tools.gittoolkit import GitToolkit


PEM_SENTINEL = (
    "-----BEGIN PRIVATE KEY-----\nFAKE\n-----END PRIVATE KEY-----\n"
)


def _make_reviewer() -> GitHubReviewer:
    """Build a bare GitHubReviewer with the minimum scaffolding needed to
    invoke _build_git_toolkit. The reviewer's __init__ pulls in heavy
    dependencies; we bypass it via __new__ + manual attribute setup."""
    reviewer = GitHubReviewer.__new__(GitHubReviewer)
    reviewer.repository = "owner/repo"
    reviewer.logger = MagicMock()
    return reviewer


class TestBuildGitToolkitAuthType:

    def test_pat_mode_default_with_token(self, monkeypatch):
        """No GITHUB_AUTH_TYPE → PAT mode, token present → toolkit built."""
        reviewer = _make_reviewer()

        def fake_config_get(key, fallback=None):
            return {
                "GITHUB_TOKEN": "pat_xxx",
                "GIT_DEFAULT_BRANCH": "main",
            }.get(key, fallback)

        with patch(
            "parrot.bots.github_reviewer.config.get", side_effect=fake_config_get
        ):
            tk = reviewer._build_git_toolkit()
        assert isinstance(tk, GitToolkit)
        assert tk.auth_type == "pat"
        assert tk.github_token == "pat_xxx"

    def test_pat_mode_missing_token_disables(self):
        reviewer = _make_reviewer()
        with patch(
            "parrot.bots.github_reviewer.config.get", return_value=None,
        ):
            tk = reviewer._build_git_toolkit()
        assert tk is None
        reviewer.logger.error.assert_called()
        args, _ = reviewer.logger.error.call_args
        assert "GITHUB_TOKEN" in args[0]

    def test_app_mode_full_config_builds_toolkit(self):
        reviewer = _make_reviewer()
        env = {
            "GITHUB_AUTH_TYPE": "github_app",
            "GITHUB_APP_ID": "12345",
            "GITHUB_APP_INSTALLATION_ID": "67890",
            "GITHUB_APP_PRIVATE_KEY": PEM_SENTINEL,
        }
        with patch(
            "parrot.bots.github_reviewer.config.get",
            side_effect=lambda k, fallback=None: env.get(k, fallback),
        ):
            tk = reviewer._build_git_toolkit()
        assert isinstance(tk, GitToolkit)
        assert tk.auth_type == "github_app"
        assert tk.app_id == 12345
        assert tk.installation_id == 67890

    def test_app_mode_with_private_key_path(self, tmp_path):
        reviewer = _make_reviewer()
        key_file = tmp_path / "key.pem"
        key_file.write_text(PEM_SENTINEL)
        env = {
            "GITHUB_AUTH_TYPE": "github_app",
            "GITHUB_APP_ID": "12345",
            "GITHUB_APP_INSTALLATION_ID": "67890",
            "GITHUB_APP_PRIVATE_KEY_PATH": str(key_file),
        }
        with patch(
            "parrot.bots.github_reviewer.config.get",
            side_effect=lambda k, fallback=None: env.get(k, fallback),
        ):
            tk = reviewer._build_git_toolkit()
        assert isinstance(tk, GitToolkit)
        assert tk.auth_type == "github_app"

    @pytest.mark.parametrize("missing", [
        "GITHUB_APP_ID",
        "GITHUB_APP_INSTALLATION_ID",
        "GITHUB_APP_PRIVATE_KEY",
    ])
    def test_app_mode_missing_required_var_disables(self, missing):
        reviewer = _make_reviewer()
        env = {
            "GITHUB_AUTH_TYPE": "github_app",
            "GITHUB_APP_ID": "12345",
            "GITHUB_APP_INSTALLATION_ID": "67890",
            "GITHUB_APP_PRIVATE_KEY": PEM_SENTINEL,
        }
        env.pop(missing)
        with patch(
            "parrot.bots.github_reviewer.config.get",
            side_effect=lambda k, fallback=None: env.get(k, fallback),
        ):
            tk = reviewer._build_git_toolkit()
        assert tk is None
        reviewer.logger.error.assert_called()

    def test_unknown_auth_type_disables(self):
        reviewer = _make_reviewer()
        env = {"GITHUB_AUTH_TYPE": "oauth"}
        with patch(
            "parrot.bots.github_reviewer.config.get",
            side_effect=lambda k, fallback=None: env.get(k, fallback),
        ):
            tk = reviewer._build_git_toolkit()
        assert tk is None
        args, _ = reviewer.logger.error.call_args
        assert "unknown GITHUB_AUTH_TYPE" in args[0]

    def test_app_mode_constructor_failure_is_caught(self):
        """If GitToolkit.__init__ raises (e.g. bad PEM combination), the
        reviewer logs and disables — does not propagate."""
        reviewer = _make_reviewer()
        env = {
            "GITHUB_AUTH_TYPE": "github_app",
            "GITHUB_APP_ID": "not-an-int",  # int() will raise
            "GITHUB_APP_INSTALLATION_ID": "67890",
            "GITHUB_APP_PRIVATE_KEY": PEM_SENTINEL,
        }
        with patch(
            "parrot.bots.github_reviewer.config.get",
            side_effect=lambda k, fallback=None: env.get(k, fallback),
        ):
            tk = reviewer._build_git_toolkit()
        assert tk is None
        reviewer.logger.error.assert_called()
```

---

## Agent Instructions

1. Read the spec at `sdd/specs/github-app-auth-gittoolkit.spec.md` (§3 Module 3, §5).
2. Activate the venv: `source .venv/bin/activate`.
3. Verify TASK-1208 ran: `python -c "from parrot_tools.gittoolkit import GitToolkit; t = GitToolkit(auth_type='pat', github_token='x'); print(t.auth_type)"`.
4. Edit `packages/ai-parrot/src/parrot/bots/github_reviewer.py` and replace
   the body of `_build_git_toolkit` (lines 451–463) with the auth-type
   branching sketch above. Do NOT touch any other method.
5. Create the test file
   `packages/ai-parrot/tests/test_github_reviewer_auth.py`.
6. Run the new tests:
   `pytest packages/ai-parrot/tests/test_github_reviewer_auth.py -v`
7. Run the regression suites:
   `pytest packages/ai-parrot-tools/tests/ packages/ai-parrot/tests/test_gittoolkit.py -v`
8. Update the per-spec index status to `done` and set `completed_at`.
9. Move this file to `sdd/tasks/completed/`.

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**:
**Date**:
**Notes**:
