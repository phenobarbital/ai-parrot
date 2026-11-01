# TASK-5059: Docs — Connections panel, SSE, Slack linking, retry, one O365 record

**Feature**: FEAT-777 — Connections — Web + Slack
**Spec**: `sdd/specs/connections-web-slack.spec.md`
**Status**: done
**Priority**: low
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-5058
**Assigned-to**: unassigned

---

## Context

Spec Module 7 and AC-13. Document what shipped, from the merged code (not from the spec): the panel and SSE endpoint,
Slack linking and commands, conditional auto-retry, request-independent PBAC for Slack, and the single O365 record.
It also closes the Slack half of the "Known gap" in `docs/auth/jira-credential-ownership.md` and fixes the O365 doc
contradiction (`office365-oauth2.md:10` says navigator-session vault; `:153` says DocumentDB `user_credentials`).
`docs/integrations/slack.md` does not exist, so Slack docs go into a section of `docs/auth/connections.md` (spec M7).

Depends on TASK-5058 only because the end-to-end tests are the last code task; by then every module is merged.

---

## Scope

- `docs/auth/connections.md`: add sections **Connections panel**, **Live updates (SSE)**, **Slack linking**,
  **Slack commands**, **Needs-auth retry**, **PBAC without a request**; mention `CONNECTIONS_LINK_BASE_URL` (required, D5)
  and `CHANNEL_LINK_TTL_SECONDS` (600).
- `docs/auth/jira-credential-ownership.md` "Known gap" (`:65`): state that Slack is now linked through the explicit web
  confirmation and the exclusive claim; keep any part of the gap that still applies to other channels.
- `docs/integrations/office365-oauth2.md`: rewrite the storage paragraph (`:8-11`) and table (`:150-155`) for one
  principal-keyed record (Identity Vault via `CredentialStore`, Redis hot cache), `grant_origin`
  (`authorization_code` | `device_code`), legacy `o365:*` / `oauth2_o365_web_*` migration until `OAUTH2_LEGACY_KEYS_UNTIL`,
  and the D4 canonical-identity lookup the device-code resolver relies on.
- Note the v1 limits: single account per provider, no Slack relinking/transfer (admin action), one Slack bot token
  for notifications, `/enable` status per spec §8.

**NOT in scope**: code changes; API reference generation; the admin UI help text.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `docs/auth/connections.md` | MODIFY | new sections (panel, SSE, Slack, retry, PBAC) |
| `docs/auth/jira-credential-ownership.md` | MODIFY | close the Slack part of "Known gap" |
| `docs/integrations/office365-oauth2.md` | MODIFY | one O365 record; fix :10 vs :153 |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
# Docs-only task — no imports. Every symbol, route, header, config key and frame format you document must be
# grep-verified in the merged code at writing time (see Steps).
```

### Existing Signatures to Use
```text
docs/auth/connections.md headings: "# Delegated OAuth2 connections" :1, "## Principal and key layout" :7,
  "## Adding a provider" :19, "## Durable owner" :31, "## Channel adapters" :38, "## Needs-auth contract" :46,
  "## API" :53, "## Migration window" :67, "## Sample PDP policy" :80, "## Key rotation" :95
docs/auth/jira-credential-ownership.md: "## Known gap" :65 (1 occurrence), "## History" :91
docs/integrations/office365-oauth2.md: storage sentence "are persisted in the navigator-session encrypted vault and hot-cached in" :10 (1 occurrence);
  table row "| Persisted   | DocumentDB `user_credentials` ..." :153 (1 occurrence)
Routes to document (from the merged code): GET /api/v1/connections/events (TASK-5040),
  GET /api/v1/channel-links/{nonce} and POST /api/v1/channel-links/{nonce}/confirm (TASK-5041)
```

### Does NOT Exist
- ~~`docs/integrations/slack.md`~~ — absent; do not create it (spec M7: a Slack section in `connections.md`).
- ~~A WebSocket endpoint for connections~~ — SSE only (D1).
- ~~E-mail auto-linking for Slack~~ — rejected (D2); do not describe it as an option.

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {"path": "docs/auth/connections.md", "action": "MODIFY"},
    {"path": "docs/auth/jira-credential-ownership.md", "action": "MODIFY"},
    {"path": "docs/integrations/office365-oauth2.md", "action": "MODIFY"}
  ],
  "contract_symbols": []
}
```

---

## Implementation Notes

### Key Constraints
- Short, factual sections; no marketing language. Use code spans for routes, headers, config keys.
- Describe the SSE frame exactly as implemented (`event: connection` + `data: <ConnectionEvent JSON>`, `: keep-alive`
  every 25 s, `fetch` streaming with the bearer header — not `EventSource`), and the semantics: the stream is a hint,
  `GET /api/v1/connections` is authoritative.
- Retry: auto-resend only when the server says `retry_safe: true`; otherwise a manual Retry that warns completed
  actions may repeat.

---

## Implementation Blueprint

### Steps (in order)
1. `grep` the merged code for every route, header, config key and model field you will cite — *why*: docs must match code, not the spec.
2. Insert the new `connections.md` sections between "## Needs-auth contract" (:46) and "## API" (:53), and add the two
   new routes to the "## API" list — *why*: readers find the contract next to the existing API.
3. Edit "## Known gap" and the O365 storage text/table.

### `docs/auth/connections.md` (MODIFY)
```markdown
<!-- occurrences: 1 (verified: grep -c '^## API$' docs/auth/connections.md) — heading at :53 -->
<!-- BEFORE — insert above `## API` (verified: connections.md:53) -->
## Connections panel
<!-- FILL IN: /account/connections — columns, actions, one store shared with the per-agent menu -->

## Live updates (SSE)
<!-- FILL IN: route, auth (session principal only), frames, keep-alive, Redis channel parrot:connections:user:{user_id}, semantics -->

## Slack linking
<!-- FILL IN: /login → link → preview → explicit Confirm; 409 conflict / 410 expired; no relinking in v1; CONNECTIONS_LINK_BASE_URL required -->

## Slack commands
<!-- FILL IN: /login, /connect <p>, /disconnect <p>, /connections; /connect_jira etc. aliases; unlinked → /login -->

## Needs-auth retry
<!-- FILL IN: retry_safe server-authored; auto-resend once; manual retry warning -->

## PBAC without a request
<!-- FILL IN: Slack uses the injected NavigatorConnectionAuthorizer; explicit ALLOW only; resource integration:<provider> -->
```
Re-run `grep -c '^## API$' docs/auth/connections.md` before inserting; it must be 1.

### `docs/auth/jira-credential-ownership.md` (MODIFY)
```markdown
<!-- occurrences: 1 (verified: grep -c '## Known gap' docs/auth/jira-credential-ownership.md) — :65 -->
<!-- FILL IN: add a paragraph "Slack (FEAT-777)": Slack users link through /login + web confirmation, which claims the
     team-qualified identity exclusively; the sink can then resolve the owner. Keep the remaining gap text only for
     channels it still applies to — bounded by AC-13 -->
```

### `docs/integrations/office365-oauth2.md` (MODIFY)
```markdown
<!-- occurrences: 1 (verified: grep -c 'are persisted in the navigator-session encrypted vault and hot-cached in' office365-oauth2.md) — :10 -->
<!-- occurrences: 1 (verified: grep -c '| Persisted   | DocumentDB `user_credentials`' office365-oauth2.md) — :153 -->
<!-- FILL IN: replace both with the single principal-keyed record (Identity Vault via CredentialStore + Redis hot cache),
     grant_origin, legacy migration window, device-code principal lookup (D4) — bounded by AC-13 -->
```

### FILL IN checklist
- [ ] Six `connections.md` sections, verified against merged code.
- [ ] "Known gap" Slack paragraph.
- [ ] O365 storage paragraph + table rewritten consistently.

---

## Acceptance Criteria

- [ ] `docs/auth/connections.md`, `docs/auth/jira-credential-ownership.md` and `docs/integrations/office365-oauth2.md` updated (AC-13).
- [ ] `office365-oauth2.md` no longer contradicts itself about where O365 tokens live.
- [ ] Every route/config key cited exists in the merged code.

---

## Validation Commands

- `pytest tests/integration/oauth2/test_e2e_web_connect.py -q`

---

## Test Specification

Docs-only; the validation command is a smoke check that the documented web connect flow still passes.

---

## Agent Instructions

When you pick up this task:

1. **Work in the feature worktree** (`python -m scripts.sdd.ensure_worktree --slug connections-web-slack --feature-id FEAT-777`)
2. **Read the spec** (Module 7; AC-13)
3. **Check dependencies** — TASK-5058 `"done"`
4. **Verify** every cited route/key in the merged code
5. **Update status** → `"in-progress"`; commit only the index
6. **Write** the docs
7. **Verify** — run the Validation Command
8. **Commit** only the listed files
9. **Close** with `scripts/sdd/close_task.sh TASK-5059 connections-web-slack verified`
10. **Completion Note**, then commit the staged SDD state

---

## Completion Note

**Completed by**: sdd-worker orchestrator; seat codex luna (5053, test fixes by orchestrator d8b605fa); 5054 by orchestrator after two empty codex deliveries; 5059 nova glm
**Date**: 2026-10-31
**Notes**: Implemented per task; merged and merge-tier validated (only red: 3 failures that also fail on origin/dev: test_o365_refresh x2, slack test_manager_payload_drives_identity_and_dm).

**Deviations from spec**: none | describe if any
