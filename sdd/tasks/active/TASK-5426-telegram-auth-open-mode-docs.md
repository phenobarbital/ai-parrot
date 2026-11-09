# TASK-5426: Documentation — `wiki/integrations/telegram-auth-open-mode.md`

**Feature**: FEAT-854 — Telegram Auth Open Mode (webview | browser)
**Spec**: `sdd/specs/telegram-auth-open-mode.spec.md`
**Status**: pending
**Priority**: medium
**Estimated effort**: S (< 2h)
**Depends-on**: TASK-5419, TASK-5421, TASK-5424, TASK-5425
**Assigned-to**: unassigned

---

## Context

Spec §3 Module 7 and §10 (`docs.policy: required`, page
`wiki/integrations/telegram-auth-open-mode.md`, API module
`parrot.integrations.telegram.browser_login`). This task documents what the other nine
tasks built, so it runs last. Document what landed in the code, not the spec's plan;
where they differ, the code wins and the Completion Note says so.

---

## Scope

- Create the wiki page from `sdd/templates/techwiki-page.md` (sections: Purpose, Public
  API, Configuration & Parameters, Usage Examples, Gotchas, Related).
- Append a content test to `test_browser_login.py` that pins the facts operators need.

The page must cover:
1. **Why**: Telegram Desktop's WebKitGTK webview crashes or renders blank on Linux/Wayland;
   embedded webviews also block WebAuthn/PassKey.
2. **Configuration**: `auth_open_mode: webview | browser` (default `webview`) and
   `public_base_url` (required in browser mode, absolute http(s)); a YAML example.
3. **Both flows** (diagrams in text/mermaid): webview (WebApp button → `sendData` →
   `handle_web_app_data`) and browser (inline URL button → system browser →
   `GET /oauth2/callback` or `POST /api/auth/telegram/browser-complete` →
   `_complete_auth_payload` → proactive chat message → `https://t.me/<bot>` deep link).
4. **Identity verification**: the `BrowserIdentityVerifier` contract,
   `VerifiedBrowserIdentity`, the app map
   `app["telegram_browser_identity_verifiers"][bot_id][method]`, the default
   `NavigatorJWTVerifier` (needs `AUTH_SECRET_KEY` or `OAUTH_JWT_KEYS` shared with the
   Navigator issuer, checks signature, algorithm allowlist, expiry, issuer, no `aud`,
   tenant, method), the startup error when a page method has no verifier, and HTTP
   401 vs 503 semantics.
5. **State routing**: `browser.` + 32-byte state, single-use, 600 s TTL; prefixed misses
   → 410; unprefixed states keep the legacy callback page.
6. **Login pages**: `return_mode`/`state`/`complete_url` continuity through Azure/Google
   SSO, the `parrot-browser-complete-origins` meta tag deployers must set when the pages
   are hosted on another origin, fail-closed behavior.
7. **Gotchas**: single-process registry (multi-worker gunicorn not supported, spec §8 Q1);
   endpoints and bot must share the aiohttp app; Navigator `AUTH_TRUSTED_DOMAINS` must allow
   the login-page host for Azure; navigator-auth's Google backend does not keep the caller's
   `redirect_uri` yet (Google browser SSO needs a navigator-auth fix); basic browser logins
   have no display name/email unless the token carries them; the inline button stays in
   the chat history.
8. **Related / follow-ups**: PassKey login, OAuth2 for MCP tools, Redis-backed state,
   profile enrichment via `GET /api/v1/user/session`.

**NOT in scope**: code changes; README edits.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `wiki/integrations/telegram-auth-open-mode.md` | CREATE | Techwiki page |
| `packages/ai-parrot-integrations/tests/integrations/telegram/test_browser_login.py` | MODIFY | Append `test_wiki_page_documents_browser_mode` |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from pathlib import Path   # stdlib
```

### Existing Signatures to Use
- Template: `sdd/templates/techwiki-page.md` (frontmatter `title`, `summary`; sections listed above).
- Frontmatter precedent: `wiki/integrations/google-oauth2.md:1-3`.
- Section index: `wiki/_index.yaml` already has `- id: integrations` (line 25) — no index edit needed.
- Checker: `parrot sdd techwiki check --spec sdd/specs/telegram-auth-open-mode.spec.md --root .`
- Symbols to document (created by TASK-5417..5425): `TelegramAgentConfig.auth_open_mode`,
  `TelegramAgentConfig.public_base_url`, `parrot.integrations.telegram.browser_login`
  (`BrowserLoginRegistry`, `BrowserIdentityVerifier`, `VerifiedBrowserIdentity`,
  `BROWSER_COMPLETE_PATH`, `setup_browser_auth_routes`),
  `parrot.integrations.telegram.browser_verifiers.NavigatorJWTVerifier`,
  `TelegramAgentWrapper._complete_auth_payload`. Re-check each name in the code before citing it.

### Does NOT Exist
- ~~`wiki/integrations/telegram-auth-open-mode.md`~~ — created by THIS task.
- ~~A docs build step for this page~~ — the techwiki check validates it; no site build here.

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {"path": "wiki/integrations/telegram-auth-open-mode.md", "action": "CREATE"},
    {"path": "packages/ai-parrot-integrations/tests/integrations/telegram/test_browser_login.py", "action": "MODIFY"}
  ],
  "contract_symbols": []
}
```

---

## Implementation Blueprint

### Steps (in order)
1. Read the merged code for every symbol above — *why*: the page documents what shipped.
2. Write the page from the template — *why*: `techwiki check` validates the structure.
3. Append the content test; run it and the techwiki check.

### `wiki/integrations/telegram-auth-open-mode.md` (CREATE)
```markdown
---
title: Telegram Auth Open Mode (webview | browser)
summary: Open Telegram bot logins in the system browser and complete them server-side.
---

# Telegram Auth Open Mode (webview | browser)

## Purpose
<!-- FILL IN: item 1 of Scope -->

## Public API
<!-- FILL IN: links/names for parrot.integrations.telegram.browser_login and browser_verifiers -->

## Configuration & Parameters
<!-- FILL IN: item 2 (+ YAML example) and item 4 (verifier wiring, key material, startup error) -->

## Usage Examples
<!-- FILL IN: items 3 and 5 (both flows, state routing, status codes) and item 6 (pages + meta tag) -->

## Gotchas
<!-- FILL IN: item 7 -->

## Related
<!-- FILL IN: item 8; link wiki/integrations/google-oauth2.md and the spec -->
```

### `test_browser_login.py` (MODIFY — append)
```python
from pathlib import Path

_WIKI_PAGE = Path(__file__).resolve().parents[5] / "wiki/integrations/telegram-auth-open-mode.md"


def test_wiki_page_documents_browser_mode():
    """The operator page names every knob and failure mode of browser mode."""
    text = _WIKI_PAGE.read_text(encoding="utf-8")
    for needle in (
        "auth_open_mode",
        "public_base_url",
        "/api/auth/telegram/browser-complete",
        "telegram_browser_identity_verifiers",
        "AUTH_SECRET_KEY",
        "parrot-browser-complete-origins",
        "browser.",
        "410",
        "Wayland",
    ):
        assert needle in text, needle
```
`parents[5]` is the repository (or worktree) root: test_browser_login.py →
telegram → integrations → tests → ai-parrot-integrations → packages → root.

### FILL IN checklist
- [ ] Six page sections with the eight Scope items
- [ ] Content test green; techwiki check clean

---

## Acceptance Criteria

- [ ] Page exists with frontmatter and the template sections.
- [ ] `parrot sdd techwiki check --spec sdd/specs/telegram-auth-open-mode.spec.md --root .` passes (run it; paste the output in the Completion Note).
- [ ] Content test passes.
- [ ] Every symbol cited exists in the merged code.

---

## Validation Commands

- `pytest packages/ai-parrot-integrations/tests/integrations/telegram/test_browser_login.py::test_wiki_page_documents_browser_mode -q`

---

## Test Specification

See the content test above.

---

## Agent Instructions

When you pick up this task:

1. **Work in the feature worktree** — never on `base_branch`
   (`parrot sdd worktree ensure --slug telegram-auth-open-mode --feature-id FEAT-854`)
2. **Read the spec** at the path listed above for full context
3. **Check dependencies** — every `Depends-on` task must be `"done"` in
   `sdd/tasks/index/telegram-auth-open-mode.json`
4. **Verify the Codebase Contract** before writing any code; fix stale entries first
5. **Update status** in the per-spec index → `"in-progress"` (set `started_at`) and commit only that index file
6. **Implement** from the Implementation Blueprint; complete every `# FILL IN:` marker
7. **Verify** all acceptance criteria — run the Validation Commands with
   `PYTHONPATH=packages/ai-parrot-integrations/src`
8. **Commit the code** — stage only the files this task lists
9. **Close the task** with `parrot sdd task close TASK-5426 telegram-auth-open-mode verified`
10. **Fill in the Completion Note** below, then commit the staged SDD state

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**: <session or agent ID>
**Date**: YYYY-MM-DD
**Notes**: What was implemented, any deviations from scope, issues encountered.

**Deviations from spec**: none | describe if any
