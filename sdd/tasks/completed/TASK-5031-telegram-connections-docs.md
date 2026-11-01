# TASK-5031: Docs — Telegram connections guide + connections.md adapter row

**Feature**: FEAT-776 — Connections on Telegram
**Spec**: `sdd/specs/connections-telegram.spec.md`
**Status**: done
**Priority**: medium
**Estimated effort**: S (< 2h)
**Depends-on**: TASK-5029, TASK-5030, TASK-5026
**Assigned-to**: unassigned

---

## Context

Spec §3 Module 11, AC-15. Documents the finished behaviour, so it runs last. Describe what the code actually does —
read the merged modules, not just the spec.

---

## Scope

Create `docs/integrations/telegram-connections.md` covering:
- User commands `/connect [<provider>]`, `/disconnect <provider>`, `/connections`; aliases `/connect_jira`,
  `/disconnect_jira`, `/jira_status`; `/connect_office365` family (alias only when `o365` is registered).
- `connection_providers` allowlist (YAML example); private-chat rule; plain-text replies.
- `/login` persists the Telegram principal link, `/logout` removes it (logout semantics change).
- **PBAC deploy precondition**: `integration:connect` / `integration:disconnect` policy (action/provider/scopes) plus
  the §8 Q1 production adapter parity prerequisite (FEAT-775); without it `/connect` is refused.
- Needs-auth behaviour: LLM instruction, Connect button after the reply, device-code text, "/login first".
- `post_auth_actions` for any registered provider; staged primary-then-secondary login; required-step failure/expiry;
  discarding a login attempt vs revoking principal-owned connections.
- Cutover runbook: audit → announce to unbound users (forced re-connect) → date passes → `--purge --channel telegram --confirm`;
  Redis only — residual vault cleanup is a separate operation with the same expiry gate.

Modify `docs/auth/connections.md`: add the Telegram adapter row (generic `TelegramConnectionNotifier`, commands, link).

**NOT in scope**: code changes; Teams/Slack docs.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `docs/integrations/telegram-connections.md` | CREATE | user/operator guide |
| `docs/auth/connections.md` | MODIFY | Telegram adapter row |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
None (docs only).

### Existing Signatures to Use
```text
docs/auth/connections.md:1  "# Delegated OAuth2 connections"  (occurrences: 1)
docs/integrations/office365-oauth2.md, google-oauth2.md — existing style references
```

### Does NOT Exist
- ~~A vault purge command~~ — do not document one.
- ~~A legacy-key backup step~~ — §8 Q2 is undecided; do not document one.

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {"path": "docs/integrations/telegram-connections.md", "action": "CREATE"},
    {"path": "docs/auth/connections.md", "action": "MODIFY"}
  ],
  "contract_symbols": []
}
```

---

## Implementation Blueprint

### Steps (in order)
1. Read the merged `connection_commands.py`, `connection_notifier.py`, `post_auth_connection.py`, `legacy_audit.py` — *why*: docs follow code.
2. Write the guide from the outline below.
3. Add the adapter row to `connections.md` (find its adapters/channels table; FILL IN: quote its header row as the anchor).

### `docs/integrations/telegram-connections.md` (CREATE)
```markdown
# Telegram connections

## Commands
## Configuration (`connection_providers`, `post_auth_actions`)
## Linking your Telegram account (/login, /logout)
## Permissions (deploy precondition)
## When a tool needs a connection
## Combined login (staged)
## Legacy cutover runbook
```

### FILL IN checklist
- [ ] Every section written from the merged code
- [ ] `connections.md` row added

---

## Acceptance Criteria

- [ ] AC-15: guide exists and documents the PBAC deploy precondition and the cutover runbook

---

## Validation Commands

- `pytest tests/integration/oauth2/test_e2e_telegram_regression.py -q`

---

## Test Specification

Docs task; the validation command re-runs the Telegram regression suite as a smoke check.

---

## Agent Instructions

1. Work in the feature worktree; confirm TASK-5029, TASK-5030, TASK-5026 are `done`
2. Commit only the listed files; close with `scripts/sdd/close_task.sh TASK-5031 connections-telegram verified`

---

## Completion Note

**Completed by**: sdd-worker; written by native opus, attempt 1, reviewed by the worker
**Date**: 2026-11-01
**Notes**:
- `docs/integrations/telegram-connections.md` (new): commands and aliases, private-chat and plain-text rules, `connection_providers` / `post_auth_actions` config, `/login` link and `/logout` unlink, the `ConnectionAuthorizer` deploy precondition (`integration:list|connect|disconnect`, fails closed), needs-auth prompts, the staged combined login (pending candidate, 10-minute expiry, no link on failure/cancel/expiry, grants stay with the principal) and the audit -> announce -> date -> purge runbook (`--purge --channel --confirm --force`, exit 2 on refusal, Redis only). `docs/auth/connections.md` gains the Telegram adapter row.
- Checked against the code: notifier message texts, `legacy_audit.py` flags, key patterns and date-gate message, `connections.md` sample policy section. The guide correctly says the Office365 aliases register when any provider is connectable or the bot uses the `oauth2` login method (the spec's "only when o365 is registered" does not match the code).
- Left out on purpose: the "LLM instruction" needs-auth item (not in the wrapper code) and any vault purge command (none ships).
- Validation: docs only; `test_e2e_telegram_regression.py` was not changed by this task. Review `0 corrections`.

**Deviations from spec**: Office365 alias wording follows the code.
