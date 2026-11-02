# TASK-4982: Docs: parrot login + connections, mcp-local credentials, agentd rules, Jira migration

**Feature**: FEAT-774 — Connections for CLI agents and local MCP toolkits
**Spec**: `sdd/specs/connections-cli-local-mcp.spec.md`
**Status**: done
**Priority**: low
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-4979, TASK-4980, TASK-4981
**Assigned-to**: unassigned

---

## Context

Spec §3 Module 11 (AC-15): operators need the deployment prerequisites (navigator-auth `Oauth2Provider` backend in
`AUTHENTICATION_BACKENDS`, the static public client `parrot-cli` with device_code + refresh_token grants and
openid/profile/email scopes, `OAUTH_DEVICE_*` settings, §8 Q1), and users need the login/connect walkthrough, the stdio
binding + auth-required envelope, the agentd per-user login-file rules (§8 Q3) and the migration from
`parrot jiratoolkit auth`.

---

## Scope

- Create `docs/cli/parrot-login-and-connections.md`.
- `docs/mcp-local-toolkits.md`: add a "Credentials and identity" section.
- `docs/auth/connections.md`: add a "CLI consumers" section (endpoints `/me`, `/token`, `/complete`, `/device/*`).
- `docs/cli/parrot-agent.md`: identity regimes (login, `--user`, `--server`).
- A smoke test asserting the required headings exist.

**NOT in scope**: code changes; README/CHANGELOG release notes (the release flow writes those).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `docs/cli/parrot-login-and-connections.md` | CREATE | login/connect guide + prerequisites |
| `docs/mcp-local-toolkits.md` | MODIFY | Credentials and identity section |
| `docs/auth/connections.md` | MODIFY | CLI consumers section |
| `docs/cli/parrot-agent.md` | MODIFY | identity regimes |
| `packages/ai-parrot/tests/docs/test_cli_connections_docs.py` | CREATE | headings smoke test |

---

## Codebase Contract (Anti-Hallucination)

> Re-verified against `dev` @ `8ab2f60782` (2026-10-31), after FEAT-773 merged. The spec's §6 entries marked
> **planned** are re-anchored to code here; line numbers below are the current ones.

### Verified Imports
```python
from pathlib import Path   # test only
```

### Existing Signatures to Use
```python
# docs/mcp-local-toolkits.md:1 `# Expose Toolkits as Local MCP (\`parrot mcp-local\`)` (occurrences 1)
# docs/auth/connections.md — FEAT-773 doc (exists) ; docs/cli/parrot-agent.md — exists
# Facts to document (verify against the merged code before writing):
#   parrot login --server URL [--client-id parrot-cli] [--scopes ...] [--no-browser]; parrot logout; parrot whoami
#   parrot connect PROVIDER [--paste|--device|--no-browser|--scopes]; parrot connections; parrot disconnect PROVIDER
#   files: ~/.parrot/login.json (0600), ~/.parrot/connections.cache (AES-GCM, access tokens only); PARROT_LOGIN_FILE
#   parrot mcp-local --login-file; host entries pass PARROT_LOGIN_FILE
#   agentd: AGENTD_LOGIN_FILE_LOOKUP, identity_source=login_file, per-user daemon only
#   navigator-auth conf: OAUTH_ACCESS_TOKEN_TTL=3600, OAUTH_REFRESH_TOKEN_TTL=2592000, OAUTH_REFRESH_ROTATION=True,
#     OAUTH_REQUIRE_PKCE_PUBLIC=True, OAUTH_DEVICE_CODE_TTL=600, OAUTH_DEVICE_POLL_INTERVAL=5,
#     OAUTH_DEVICE_SLOW_DOWN_INCREMENT=5, OAUTH_DEVICE_VERIFICATION_URI
#   provider descriptors (OAUTH2_PROVIDERS_FILE): device_authorization_url — Microsoft
#     https://login.microsoftonline.com/{tenant}/oauth2/v2.0/devicecode, Google https://oauth2.googleapis.com/device/code;
#     Atlassian: no device grant → poll + paste only (§8 Q4)
```

### Does NOT Exist
- ~~`docs/cli/parrot-login-and-connections.md`~~ — created here.
- ~~documenting a shared-service-user agentd~~ — out of scope (§8 Q3).
- ~~documenting `oauth2_local` / `parrot jiratoolkit auth` as current~~ — only as a migration note.

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {
      "path": "docs/cli/parrot-login-and-connections.md",
      "action": "CREATE"
    },
    {
      "path": "docs/mcp-local-toolkits.md",
      "action": "MODIFY"
    },
    {
      "path": "docs/auth/connections.md",
      "action": "MODIFY"
    },
    {
      "path": "docs/cli/parrot-agent.md",
      "action": "MODIFY"
    },
    {
      "path": "packages/ai-parrot/tests/docs/test_cli_connections_docs.py",
      "action": "CREATE"
    }
  ],
  "contract_symbols": []
}
```

---

## Implementation Notes

- Write for operators first (prerequisites, exact settings), then users (walkthrough), then integrators (envelope JSON
  example with every `AuthRequiredPayload` field).
- Never include real tokens in examples; use `<access-token>` placeholders.
- The smoke test reads each doc file and asserts the section headings below exist — it guards AC-15 only.

---

## Implementation Blueprint

> **CRITICAL — Executor-ready starting point.** Write each block below to its declared
> path nearly verbatim, then complete every `# FILL IN:` marker. This is NOT the full
> implementation: branches, edge cases and test bodies are `FILL IN` stubs by design.
> Never change a signature, class name, or file path the blueprint fixes.

### Steps (in order)
1. Re-read the merged code of TASK-4968…4981 for flags and names — *why*: docs must match shipped behaviour.
2. Write the new guide and the three section additions.
3. Write the headings smoke test and run it.

### `docs/cli/parrot-login-and-connections.md` (CREATE — outline)
```markdown
# parrot login and connections

## Deployment prerequisites
<!-- FILL IN: Oauth2Provider in AUTHENTICATION_BACKENDS; static public client parrot-cli (client_type public,
     allowed_grant_types ⊇ device_code + refresh_token, default_scopes ⊇ openid profile email); OAUTH_DEVICE_* settings;
     what `parrot login` prints when they are missing (exit 2) -->
## Logging in
## Connecting a provider
<!-- poll, --paste (SSH), --device; providers with device grant (Microsoft, Google) vs Atlassian (poll + paste) -->
## Where credentials live
<!-- login.json 0600 + cache_key; connections.cache AES-GCM access tokens only; refresh tokens never leave the server -->
## Local MCP toolkits
## agentd
## Migrating from `parrot jiratoolkit auth`
```

### `docs/mcp-local-toolkits.md` (MODIFY)
```markdown
<!-- APPEND a section at the end of the file -->
## Credentials and identity
<!-- FILL IN: --login-file / PARROT_LOGIN_FILE, process-start binding, no login = unchanged, the auth-required envelope
     JSON example (isError, content, structuredContent), host entries pass PARROT_LOGIN_FILE -->
```

### `docs/auth/connections.md` / `docs/cli/parrot-agent.md` (MODIFY)
```markdown
<!-- connections.md: APPEND "## CLI consumers" (GET /me, POST /{provider}/token (PBAC integration:use, 409 body),
     POST /{provider}/complete, POST /{provider}/device/start|poll, POST /{provider}/start {"channel": "cli"}) -->
<!-- parrot-agent.md: APPEND "## Identity" (login → Navigator id; --user refused with a login; --server → login bearer,
     one refresh on 401) -->
```

### `packages/ai-parrot/tests/docs/test_cli_connections_docs.py` (CREATE)
```python
"""AC-15 smoke test: the FEAT-774 docs carry their required sections."""
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[4]


@pytest.mark.parametrize("rel,heading", [
    ("docs/cli/parrot-login-and-connections.md", "## Deployment prerequisites"),
    ("docs/cli/parrot-login-and-connections.md", "## agentd"),
    ("docs/mcp-local-toolkits.md", "## Credentials and identity"),
    ("docs/auth/connections.md", "## CLI consumers"),
    ("docs/cli/parrot-agent.md", "## Identity"),
])
def test_cli_connections_docs_sections(rel, heading):
    assert heading in (ROOT / rel).read_text(encoding="utf-8")
```

### FILL IN checklist
- [ ] guide body sections; bounded by AC-15 and the shipped flags
- [ ] the three appended sections

---

## Acceptance Criteria

- [ ] `docs/cli/parrot-login-and-connections.md` documents prerequisites, login/connect walkthrough, the stdio envelope and agentd rules (AC-15)
- [ ] `docs/mcp-local-toolkits.md` has the credentials section (AC-15)
- [ ] The docs smoke test passes

---

## Validation Commands

- `pytest packages/ai-parrot/tests/docs/test_cli_connections_docs.py -q`

---

## Test Specification

```python
# see packages/ai-parrot/tests/docs/test_cli_connections_docs.py block in the blueprint
```

---

## Agent Instructions

When you pick up this task:

1. **Work in the feature worktree** — never on `dev`
   (`python -m scripts.sdd.ensure_worktree --slug connections-cli-local-mcp --feature-id FEAT-774 --spec sdd/specs/connections-cli-local-mcp.spec.md --index sdd/tasks/index/connections-cli-local-mcp.json`)
2. **Read the spec** at the path listed above for full context (§2 Overview, §3 for this module, §7 gotchas)
3. **Check dependencies** — every `Depends-on` task must be `"done"` in `sdd/tasks/index/connections-cli-local-mcp.json`
4. **Verify the Codebase Contract** — before writing ANY code re-run each `grep -c` in the blueprint;
   if a count differs, fix the anchor in this file first. Never use anything under "Does NOT Exist".
5. **Update status** in the per-spec index → `"in-progress"` (set `started_at`) and commit only that index file
6. **Implement** — start from the Implementation Blueprint blocks, complete every `# FILL IN:` marker,
   never change a signature or path the blueprint fixes
7. **Verify** — run the Validation Commands with `PYTHONPATH=packages/ai-parrot/src` (plus one entry per other
   changed package, e.g. `packages/ai-parrot-server/src`) and `ruff check` the touched files
8. **Commit the code** — stage only the files this task lists (never `git add .` / `-A`)
9. **Close the task** with `scripts/sdd/close_task.sh <TASK-ID> connections-cli-local-mcp verified` — never move the file by hand
10. **Fill in the Completion Note** below, then commit the staged SDD state

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**: gpt-5.6-sol (codex) (1 attempt), orchestrated by sdd-worker
**Date**: 2026-10-31
**Notes**: Implemented as specified; task tests green. Merge-tier: only sandbox-limited tests/cli/test_session.py::test_stream_closed_in_turn_task_after_final_message fails (read-only ~/.parrot/cli).
