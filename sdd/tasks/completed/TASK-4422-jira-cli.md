# TASK-4422: Jira CLI (auth, status, logout, sync-kb)

**Feature**: FEAT-696 — JiraToolkit upgrades
**Spec**: `sdd/specs/jiratoolkit-upgrades.spec.md`
**Status**: pending
**Priority**: medium
**Estimated effort**: L (4-8h)
**Depends-on**: TASK-4417, TASK-4418, TASK-4419
**Assigned-to**: unassigned

---

## Context

> Implements spec Module 5 — the `parrot jiratoolkit` click group with `auth`,
> `status`, `logout`, and `sync-kb` subcommands. Registered as a lazy command in
> `parrot/cli/__init__.py`. Depends on TASK-4417 (KB model for sync-kb),
> TASK-4418 (3LO helpers for auth), and TASK-4419 (local store for token
> persistence).

---

## Scope

- Create `jira_cli.py` with `auth`, `status`, `logout`, `sync-kb` subcommands.
- `auth`: prints authorize URL, reads pasted URL/code, validates state, exchanges,
  picks site, calls /myself, saves tokens, upserts `.env`.
- `status`: shows site, account, expiry, probes /myself; never prints secrets.
- `logout`: deletes site entry; does not touch `.env`.
- `sync-kb`: creates/updates a KB YAML via live Jira queries.
- `parse_pasted_redirect()` and `upsert_env()` helpers.
- Register `"jiratoolkit"` in `parrot/cli/__init__.py` `_lazy_commands`.
- Write CLI tests with `CliRunner`.

**NOT in scope**: toolkit wiring (TASK-4421), local store internals (TASK-4419),
or KB model internals (TASK-4417).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot-tools/src/parrot_tools/jira_cli.py` | CREATE | CLI group |
| `packages/ai-parrot/src/parrot/cli/__init__.py` | MODIFY | Register lazy command |
| `packages/ai-parrot-tools/tests/unit/test_jira_cli.py` | CREATE | CLI tests |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
import click                                                         # verified: used in parrot_tools/procedures/cli.py
import asyncio                                                       # stdlib
import aiohttp                                                       # verified: throughout project
from parrot.auth.jira_oauth import (                                 # verified: jira_oauth.py
    build_authorization_url, exchange_code,                          # created by TASK-4418
    fetch_accessible_resources, fetch_myself,
    DEFAULT_SCOPES,
)
from parrot_tools.jira_local_auth import LocalJiraTokenStore          # created by TASK-4419
from parrot_tools.jira_kb import JiraKnowledgeBase                    # created by TASK-4417
```

### Existing Signatures to Use
```python
# parrot/cli/__init__.py:109
cli._lazy_commands = {
    ...
    "manuals": "parrot_tools.procedures.cli",                        # L127
    ...
}
```

### Does NOT Exist
- ~~`parrot_tools.jira_cli`~~ — does not exist yet; this task creates it
- ~~`parrot jiratoolkit`~~ CLI command — does not exist yet
- ~~`python-dotenv`~~ — not a declared dependency; `upsert_env` is hand-written

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {
      "path": "packages/ai-parrot-tools/src/parrot_tools/jira_cli.py",
      "action": "CREATE"
    },
    {
      "path": "packages/ai-parrot/src/parrot/cli/__init__.py",
      "action": "MODIFY"
    },
    {
      "path": "packages/ai-parrot-tools/tests/unit/test_jira_cli.py",
      "action": "CREATE"
    }
  ],
  "contract_symbols": []
}
```

---

## Implementation Notes

### Pattern to Follow
Follow `parrot_tools/procedures/cli.py`: click group, lazily imported,
`asyncio.run` per command.

### Key Constraints
- `auth`: state mismatch → abort non-zero; bare code → accept with warning;
  `error=` in redirect → abort with that error (S6). Secret prompt hidden.
- `.env` upsert: replace existing lines in place, atomic write, quote values
  with `#` or spaces. Never reorder or drop unrelated lines.
- `status`: never prints secrets (tokens, client secret).
- `sync-kb`: regenerates structural sections, keeps curated ones (uses
  `JiraKnowledgeBase.merge_generated()`).

---

## Implementation Blueprint

### Steps (in order)
1. Create `jira_cli.py` — *why*: the CLI is the primary user-facing deliverable of the local auth feature.
2. Register in `cli/__init__.py` — *why*: makes `parrot jiratoolkit` discoverable.
3. Write tests — *why*: CliRunner tests validate the auth flow without real Jira.

### `packages/ai-parrot-tools/src/parrot_tools/jira_cli.py` (CREATE)
```python
"""Jira toolkit CLI — local 3LO auth, KB sync (FEAT-696 M5)."""
from __future__ import annotations

import asyncio
import logging
import os
import secrets
import sys
import tempfile
from pathlib import Path
from typing import Mapping, Optional, Tuple
from urllib.parse import parse_qs, urlparse

import click

logger = logging.getLogger(__name__)


def parse_pasted_redirect(text: str) -> Tuple[str, Optional[str]]:
    """Extract (code, state|None) from a pasted redirect URL or bare code."""
    text = text.strip()
    if text.startswith("http"):
        parsed = urlparse(text)
        qs = parse_qs(parsed.query)
        if "error" in qs:
            raise click.ClickException(f"Authorization denied: {qs['error'][0]}")
        code = qs.get("code", [None])[0]
        if not code:
            raise click.ClickException("No 'code' parameter in the pasted URL.")
        state = qs.get("state", [None])[0]
        return code, state
    return text, None


def upsert_env(path: Path, values: Mapping[str, str]) -> None:
    """Replace-or-append env vars in a .env file, atomically."""
    # FILL IN: read existing lines, replace matching KEY= lines in place,
    #          append missing ones, quote values containing # or spaces,
    #          write to tempfile + os.replace — bounded by spec §7 .env upsert
    raise NotImplementedError


@click.group(name="jiratoolkit")
def cli() -> None:
    """Jira toolkit utilities."""


@cli.command()
@click.option("--site", default=None, help="Jira site URL")
@click.option("--scopes", default=None, help="Comma-separated scopes")
@click.option("--env-file", default=".env", type=click.Path(), help="Path to .env file")
@click.option("--client-id", default=None, help="OAuth client ID")
@click.option("--client-secret", default=None, help="OAuth client secret")
@click.option("--redirect-uri", default=None, help="OAuth redirect URI")
def auth(site, scopes, env_file, client_id, client_secret, redirect_uri) -> None:
    """Authenticate with Jira using OAuth 2.0 (3LO) — manual paste flow."""
    # FILL IN: steps 1-8 from spec §2 M5 — bounded by AC3, AC4
    raise NotImplementedError


@cli.command()
@click.option("--site", default=None, help="Jira site URL")
def status(site) -> None:
    """Show current Jira authentication status."""
    # FILL IN: load store, show site/account/expiry/scopes, probe /myself
    #          Never print secrets — bounded by spec §2 M5
    raise NotImplementedError


@cli.command()
@click.option("--site", default=None, help="Jira site URL to remove")
def logout(site) -> None:
    """Remove stored Jira credentials for a site."""
    # FILL IN: store.delete(site), does NOT touch .env — bounded by spec §2 M5
    raise NotImplementedError


@cli.command(name="sync-kb")
@click.option("--output", "-o", default=None, type=click.Path(), help="Output YAML path")
@click.option("--projects", default=None, help="Comma-separated project keys")
def sync_kb(output, projects) -> None:
    """Generate or update a Jira knowledge base YAML file."""
    # FILL IN: query live Jira for structure, merge with existing if present,
    #          save — bounded by spec §2 M6 sync-kb, AC9
    raise NotImplementedError
```
**Why this shape**: spec §3 M5 interface skeleton. Each command uses `asyncio.run`
internally for async helpers. The group name `"jiratoolkit"` matches the lazy
command registration.

### `packages/ai-parrot/src/parrot/cli/__init__.py` (MODIFY)
```python
# occurrences: 1 (verified: grep -c '"manuals": "parrot_tools.procedures.cli",' packages/ai-parrot/src/parrot/cli/__init__.py)
# AFTER — insert below `    "manuals": "parrot_tools.procedures.cli",` (verified: cli/__init__.py:127)
    "jiratoolkit": "parrot_tools.jira_cli",
```
**Why**: lazy registration makes `parrot jiratoolkit` available without eager import.

```python
# Also add to _lazy_extras (after L149):
# occurrences: 1 (verified: grep -c '"manuals": "ai-parrot-tools' packages/ai-parrot/src/parrot/cli/__init__.py)
# AFTER — insert below `    "manuals": "ai-parrot-tools: pip install ai-parrot-tools ai-parrot[manuals]",` (verified: cli/__init__.py:149)
    "jiratoolkit": "ai-parrot-tools: pip install ai-parrot-tools",
```

### `packages/ai-parrot-tools/tests/unit/test_jira_cli.py` (CREATE)
```python
"""Tests for Jira CLI (FEAT-696 M5)."""
from __future__ import annotations

import pytest
from click.testing import CliRunner
from unittest.mock import AsyncMock, MagicMock, patch


class TestParseRedirect:
    def test_url_with_code_and_state(self):
        from parrot_tools.jira_cli import parse_pasted_redirect
        code, state = parse_pasted_redirect("http://localhost/cb?code=abc&state=xyz")
        assert code == "abc"
        assert state == "xyz"

    def test_bare_code(self):
        from parrot_tools.jira_cli import parse_pasted_redirect
        code, state = parse_pasted_redirect("abc123")
        assert code == "abc123"
        assert state is None

    def test_error_redirect_raises(self):
        from parrot_tools.jira_cli import parse_pasted_redirect
        with pytest.raises(Exception, match="Authorization denied"):
            parse_pasted_redirect("http://localhost/cb?error=access_denied")

    def test_state_mismatch_detected(self):
        from parrot_tools.jira_cli import parse_pasted_redirect
        code, state = parse_pasted_redirect("http://localhost/cb?code=abc&state=wrong")
        assert state == "wrong"  # caller checks the mismatch


class TestUpsertEnv:
    def test_replaces_existing_line(self, tmp_path):
        # FILL IN: write a .env, upsert a key, verify replacement — bounded by spec §7
        pass

    def test_appends_new_key(self, tmp_path):
        # FILL IN: upsert a new key, verify appended — bounded by spec §7
        pass

    def test_quotes_values_with_hash(self, tmp_path):
        # FILL IN: upsert a value containing #, verify quoted — bounded by spec §7
        pass


class TestCliHelp:
    def test_jiratoolkit_help(self):
        from parrot_tools.jira_cli import cli
        runner = CliRunner()
        result = runner.invoke(cli, ["--help"])
        assert result.exit_code == 0
        assert "auth" in result.output


class TestAuthCommand:
    def test_state_mismatch_aborts(self):
        # FILL IN: mock prompts to return a URL with wrong state — bounded by AC3
        pass

    def test_bare_code_accepted_with_warning(self):
        # FILL IN: mock prompts to return a bare code — bounded by spec §4 M5
        pass


class TestLazyRegistration:
    def test_lazy_command_resolves(self):
        # FILL IN: verify "jiratoolkit" in _lazy_commands — bounded by spec §4 S12
        pass
```
**Why this shape**: spec §4 M5 test rows.

### FILL IN checklist
- [ ] `jira_cli.py::upsert_env` — atomic .env upsert with quoting; bounded by spec §7
- [ ] `jira_cli.py::auth` — steps 1-8 from spec §2 M5; bounded by AC3, AC4
- [ ] `jira_cli.py::status` — show site/account/expiry; bounded by spec §2 M5
- [ ] `jira_cli.py::logout` — delete site entry; bounded by spec §2 M5
- [ ] `jira_cli.py::sync_kb` — live query + merge; bounded by AC9
- [ ] `test_jira_cli.py` — all test bodies; bounded by spec §4 M5

---

## Acceptance Criteria

- [ ] `parrot jiratoolkit auth` completes with a pasted URL/code, no listening socket (AC3)
- [ ] State mismatch aborts with non-zero exit (AC3)
- [ ] Client id/secret/redirect URI land in `.env`; tokens only in `settings.local.json` with 0600 (AC4)
- [ ] `sync-kb` over an existing file keeps curated sections (AC9)
- [ ] `parrot jiratoolkit --help` resolves through the lazy group (S12)
- [ ] `ruff check` clean; no new dependency (AC11)

---

## Validation Commands

- `pytest packages/ai-parrot-tools/tests/unit/test_jira_cli.py -q`

---

## Test Specification

See `test_jira_cli.py` in the blueprint above.

---

## Agent Instructions

When you pick up this task:

1. **Work in the feature worktree** — `python -m scripts.sdd.ensure_worktree --slug jiratoolkit-upgrades --feature-id FEAT-696`
2. **Read the spec** at `sdd/specs/jiratoolkit-upgrades.spec.md`
3. **Check dependencies** — TASK-4417, TASK-4418, TASK-4419 must be `"done"`
4. **Verify the Codebase Contract** — confirm `_lazy_commands` dict in `cli/__init__.py`
5. **Update status** in `sdd/tasks/index/jiratoolkit-upgrades.json` → `"in-progress"`
6. **Implement** — create `jira_cli.py`, register in `cli/__init__.py`
7. **Verify** acceptance criteria
8. **Commit** — stage `jira_cli.py`, `cli/__init__.py`, `test_jira_cli.py`
9. **Close** with `scripts/sdd/close_task.sh TASK-4422 jiratoolkit-upgrades verified`

---

## Completion Note

- Seat: haiku · Backend: native · Model: haiku · Attempts: 1 · Duration: ~235s · Tokens: n/a
- Code commit: 094ec8616 (+ engine lint c0d7baf19, merge 66e4bb0a3)
- Closed by sdd-worker via close_task.sh (finalize_task refused: implementation_sha must equal HEAD, and HEAD already carried TASK-4420's closure commit).

**Completed by**: sdd-worker (coder: haiku native)
**Date**: 2026-10-16

**Notes**:
- Validation: 27 tests in test_jira_cli.py pass; ruff clean. Engine merge-tier run hung on a pre-existing Textual TUI test
  (tests/cli/tui/test_widgets.py::test_composer_enter_submits_and_ctrl_j_newline, also hangs on dev); jira-scope ai-parrot failures (75) identical to dev baseline.
- Coder reported: `jiratoolkit = cli` alias added for the lazy loader; sync-kb output path is -o, then $JIRA_KB_PATH, then ./jira_kb.yaml;
  sync-kb endpoints (/project, /priority, /field, ...) mocked in tests, not verified against a live Jira; `status` probes /myself with an expired token and reports a failed probe;
  projects not listed in --projects are dropped from sync output; only pre-existing hand-edited field aliases are kept (no new aliases generated).
- Review recorded: coder-review:d47c80c6705992b0dc799d79 (no fix commits).

**Deviations from spec**: AC9 (sync-kb preserves YAML comments) and AC11 (ruamel.yaml dependency) in the amended spec are NOT met. TASK-4417 was
implemented with PyYAML per its (stale) task file, so JiraKnowledgeBase.save() drops comments. Needs a follow-up: declare ruamel.yaml in ai-parrot-tools and switch jira_kb.save().
