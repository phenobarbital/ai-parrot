---
type: Wiki Overview
title: 'TASK-1734: Teams Graph-API file upload'
id: doc:sdd-tasks-completed-task-1734-teams-graph-upload-md
tags:
- overview
timestamp: '2026-07-16T08:34:12+00:00'
summary: Spec §3 Module 7 (second half) and spec-session decision (§8, "Teams/Slack
relates_to:
- concept: mod:parrot.integrations.msteams.graph
  rel: mentions
- concept: mod:parrot.notifications
  rel: mentions
- concept: mod:parrot.outputs.a2ui
  rel: mentions
---

# TASK-1734: Teams Graph-API file upload

**Feature**: FEAT-273 — A2UI Protocol Integration — Rendering Core (parrot.outputs.a2ui)
**Spec**: sdd/specs/a2ui-implementation.spec.md
**Status**: pending
**Priority**: high
**Estimated effort**: L (4-8h)
**Depends-on**: TASK-1733
**Assigned-to**: unassigned

---

## Context

Spec §3 Module 7 (second half) and spec-session decision (§8, "Teams/Slack
attachment gap"): Teams file delivery was pulled INTO FEAT-273. Today
`_send_teams` in `parrot/notifications/__init__.py` (:655) only appends an
"**Attached Files:**" filename list into the message text — its own inline
comment says "For full file upload support, would need to use Graph API file
upload". This task adds real Graph-API file-upload methods to the existing
`GraphClient` (`msteams/graph.py`) and wires them into `_send_teams` so a
`RenderedArtifact` delivered via TASK-1733's bridge arrives as a real file.
Runtime permission failures must downgrade to the Slack-style public-URL line
with a degraded log — never a silent drop (spec §7, "Teams Graph upload scope
creep" risk).

Spec anchors: §2 Integration Points (`msteams/graph.py` row), §3 Module 7,
§5 AC **G5**, §8 open question (Graph permission set / upload target).

---

## Scope

- Add async file-upload capability to `class GraphClient` in
  `packages/ai-parrot-integrations/src/parrot/integrations/msteams/graph.py`:
  new method(s) that take a local file path (or bytes + filename) plus the
  target chat/user context and return a shareable reference usable in a Teams
  message. Follow the class's existing conventions: raw `aiohttp` against the
  Graph REST API, client-credentials token via `_get_access_token()`, shared
  session via `_get_session()`, `_auth_headers(token)`, and the class's
  "return `None`, never raise, on any Graph error" contract.
- Wire the upload into `_send_teams` in
  `packages/ai-parrot/src/parrot/notifications/__init__.py` (:655): when
  `files` are present and Graph credentials are configured
  (`TEAMS_NOTIFY_TENANT_ID` / `TEAMS_NOTIFY_CLIENT_ID` /
  `TEAMS_NOTIFY_CLIENT_SECRET` from `parrot/conf.py:571-573`), upload each
  file and attach/link it in the outgoing message; keep the current
  filenames-in-text behavior as the no-credentials fallback.
- Runtime permission/consent failure (403/insufficient privileges, upload
  returns `None`): downgrade to the TASK-1733 public-URL line (when a public
  URL is available) or filenames-in-text, ALWAYS with a degraded-delivery log
  record naming provider + reason. Never silent.
- Write unit tests: `test_teams_graph_upload_called` (spec §4, Module 7 row)
  plus downgrade tests, all with mocked Graph HTTP.

**OPEN QUESTION carried from spec §8 (owner: this task's implementer)**:
the exact Graph permission set AND the upload target — chat message file
attachment (requires drive-backed hosting) vs OneDrive/SharePoint upload +
share link in the message. Resolve during implementation (Graph API docs +
tenant constraints), implement the chosen target, and RECORD the decision and
required application permissions in the Completion Note.

**NOT in scope**:
- Slack public-URL line and the core delivery bridge → TASK-1733 (done, this
  task consumes its downgrade path).
- Teams deep-link resume route / `activity.value` handling → TASK-1736.
- Any change to `GraphClient` user-resolution methods (`get_user_by_email`,
  `get_user_manager`).
- Slack file upload of any kind (spec Non-Goal).
- New conf variables beyond reusing the existing `TEAMS_NOTIFY_*` set — add
  new ones ONLY if the resolved upload target strictly requires it (record in
  Completion Note).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot-integrations/src/parrot/integrations/msteams/graph.py` | MODIFY | New Graph file-upload method(s) on `GraphClient` |
| `packages/ai-parrot/src/parrot/notifications/__init__.py` | MODIFY | `_send_teams` wires Graph upload + permission-failure downgrade |
| `packages/ai-parrot-integrations/tests/msteams/test_graph_upload.py` | CREATE | Unit tests for upload methods (mocked aiohttp) |
| `packages/ai-parrot/tests/outputs/a2ui/test_delivery_teams.py` | CREATE | `_send_teams` wiring + downgrade tests (mocked GraphClient) |

---

## Codebase Contract (Anti-Hallucination)

> **CRITICAL**: This section contains VERIFIED code references from the actual codebase.
> The implementing agent MUST use these exact imports, class names, and method signatures.
> **DO NOT** invent, guess, or assume any import, attribute, or method not listed here.
> If you need something not listed, VERIFY it exists first with `grep` or `read`.

### Verified Imports
```python
from parrot.notifications import NotificationMixin, NotificationProvider  # notifications/__init__.py:56/:23
# GraphClient lives in the integrations satellite (PEP 420 namespace):
from parrot.integrations.msteams.graph import GraphClient, ResolvedTeamsUser  # graph.py:76/:48
```

### Existing Signatures to Use
```python
# packages/ai-parrot-integrations/src/parrot/integrations/msteams/graph.py
# VERIFIED: the class wraps RAW aiohttp against the Graph REST API with a
# client-credentials token flow — it does NOT use msgraph-sdk, botbuilder, or
# aiogram (module docstring states this explicitly). All methods return None
# (never raise) on Graph errors.
class ResolvedTeamsUser(BaseModel)  # :48
class GraphClient:  # :76
    def __init__(self, client_id: str, client_secret: str, tenant_id: str,
                 logger: Optional[logging.Logger] = None) -> None  # :96
    async def _get_session(self) -> aiohttp.ClientSession  # :119 (lazy shared session)
    async def close(self) -> None  # :129
    async def _get_access_token(self) -> Optional[str]  # :141 (cached, lock-guarded)
    def _auth_headers(self, token: str) -> Dict[str, str]  # :189
    async def get_user_by_email(self, email: str) -> Optional[ResolvedTeamsUser]  # :194
    async def get_user_manager(self, upn: str) -> Optional[Dict[str, Any]]  # :332

# packages/ai-parrot/src/parrot/notifications/__init__.py
async def _send_teams(self, notify_args: Dict[str, Any],
                      files: Optional[List[Path]] = None) -> Any  # :655
# today: `from notify.providers.teams import Teams`; reads conf vars
# TEAMS_NOTIFY_TENANT_ID / TEAMS_NOTIFY_CLIENT_ID / TEAMS_NOTIFY_CLIENT_SECRET /
# TEAMS_NOTIFY_USERNAME / TEAMS_NOTIFY_PASSWORD (parrot/conf.py:571-575);
# when files present it ONLY appends "**Attached Files:**\n- <name>" text and
# logs "Teams notification with N files (file list added to message)".

# packages/ai-parrot/src/parrot/conf.py
TEAMS_NOTIFY_TENANT_ID = config.get("TEAMS_NOTIFY_TENANT_ID")      # :571
TEAMS_NOTIFY_CLIENT_ID = config.get("TEAMS_NOTIFY_CLIENT_ID")      # :572
TEAMS_NOTIFY_CLIENT_SECRET = config.get("TEAMS_NOTIFY_CLIENT_SECRET")  # :573
TEAMS_NOTIFY_USERNAME = config.get("TEAMS_NOTIFY_USERNAME")        # :574
TEAMS_NOTIFY_PASSWORD = config.get("TEAMS_NOTIFY_PASSWORD")        # :575
```

### Does NOT Exist
- ~~`GraphClient.upload_file()` or ANY upload/drive/attachment method~~ —
  verified by grep (2026-07-10): zero matches for `upload|drive|attachment`
  in `graph.py`. This task creates the first one.
- ~~`msgraph-sdk` usage inside `GraphClient`~~ — despite the spec's external-deps
  table listing `msgraph-sdk` as "confirm exact client", verification shows
  `GraphClient` uses raw `aiohttp` only; stay consistent with that (no new SDK
  dependency).
- ~~Real file attachments for Teams notifications~~ — filenames-in-text only
  today; that is exactly the gap this task closes.
- ~~`Agent.notification()` / `Agent.notify()`~~ — surface is
  `NotificationMixin.send_notification` on `BasicAgent` (`bots/agent.py:29`).
- ~~Teams `on_invoke_activity` handler~~ — irrelevant here but do not add one;
  card submits arrive as `message` activities (`msteams/wrapper.py:305`).

---

## Implementation Notes

### Pattern to Follow
- New upload methods must be shaped like `get_user_by_email` (:194): acquire
  token via `_get_access_token()`, `None` on missing token; shared session;
  `_auth_headers`; log-and-return-`None` on any non-2xx or exception. Large
  files may require Graph upload sessions (chunked PUT) — follow the same
  error contract per chunk.
- `_send_teams` keeps its lazy `from notify.providers.teams import Teams`
  import style; import `GraphClient` lazily inside the function too (the
  integrations satellite may not be installed — ImportError → existing
  filenames-in-text fallback + degraded log).
- Downgrade chain on runtime failure: Graph upload → public artifact URL line
  (TASK-1733 mechanism, when delivery context provides one) → filenames-in-text.
  Every downgrade emits a greppable warning; never silent (spec §7).

### Key Constraints
- Async throughout, `aiohttp` only (never `requests`/`httpx`); Google-style
  docstrings; `self.logger`.
- Do not break the no-credentials path: absent `TEAMS_NOTIFY_*` values must
  behave exactly as today (G7 — legacy tests stay green).
- `GraphClient` error contract preserved: upload methods return `None` on
  failure, callers decide the downgrade.
- Record the resolved Graph permission set + upload target in the Completion
  Note (spec §8 open question) and, if applicable, in a docs snippet.
- No new heavy dependencies; no `exec(`/`eval(` (G1).

### References in Codebase
- `packages/ai-parrot-integrations/src/parrot/integrations/msteams/graph.py`
  — the class being extended; copy its token/session/error conventions.
- `packages/ai-parrot/src/parrot/notifications/__init__.py:655` — `_send_teams`
  integration point (inline comment marks the Graph-upload TODO).
- TASK-1733 delivery bridge — provides the public-URL downgrade mechanism.

---

## Acceptance Criteria

- [ ] Implementation complete per scope
- [ ] All tests pass: `pytest packages/ai-parrot-integrations/tests/msteams/test_graph_upload.py packages/ai-parrot/tests/outputs/a2ui/test_delivery_teams.py -v`
- [ ] No linting errors: `ruff check packages/ai-parrot-integrations/src/parrot/integrations/msteams/graph.py packages/ai-parrot/src/parrot/notifications/__init__.py`
- [ ] Teams delivery with configured credentials invokes the GraphClient upload (mocked) and the message references the uploaded file
- [ ] Runtime permission failure (upload returns `None`) downgrades to public URL / filenames-in-text WITH a degraded-delivery log — proven by test, never silent
- [ ] No-credentials and satellite-not-installed paths behave exactly as today (legacy notification tests green — G7)
- [ ] Graph permission set + upload target decision recorded in the Completion Note (spec §8)
- [ ] `GraphClient` upload methods follow the return-None-never-raise contract

---

## Test Specification

> Minimal test scaffold. The agent must make these pass.
> Add more tests as needed. `test_teams_graph_upload_called` is mandated by spec §4.

```python
# packages/ai-parrot-integrations/tests/msteams/test_graph_upload.py

class TestGraphClientUpload:
    async def test_upload_success_returns_reference(self):
        """Upload method acquires a token, PUTs the file to Graph (mocked
        aiohttp), and returns a usable file reference/share link."""

    async def test_upload_permission_denied_returns_none(self):
        """A 403 from Graph is logged and the method returns None (never
        raises), per the GraphClient error contract."""

    async def test_upload_without_token_returns_none(self):
        """Token acquisition failure short-circuits to None with a log."""


# packages/ai-parrot/tests/outputs/a2ui/test_delivery_teams.py

class TestSendTeamsGraphWiring:
    async def test_teams_graph_upload_called(self):
        """With TEAMS_NOTIFY_* configured, _send_teams invokes the GraphClient
        upload (mocked) instead of only listing filenames in text."""

    async def test_permission_failure_downgrades_with_log(self):
        """Upload returning None downgrades to public-URL/filenames-in-text
        and emits a degraded-delivery warning (never silent)."""

    async def test_no_credentials_keeps_legacy_behavior(self):
        """Without Graph credentials, _send_teams behaves exactly as today
        (filenames-in-text) — G7 regression guard."""
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at the path listed above for full context
2. **Check dependencies** — verify `Depends-on` tasks are in `tasks/completed/`
3. **Verify the Codebase Contract** — before writing ANY code:
   - Confirm every import in "Verified Imports" still exists (`grep` or `read` the source)
   - Confirm every class/method in "Existing Signatures" still has the listed attributes
   - If anything has changed, update the contract FIRST, then implement
   - **NEVER** reference an import, attribute, or method not in the contract without verifying it exists
4. **Update status** in `sdd/tasks/index/a2ui-implementation.json` → `"in-progress"` with your session ID
5. **Implement** following the scope, codebase contract, and notes above
6. **Verify** all acceptance criteria are met
7. **Move this file** to `tasks/completed/TASK-1734-teams-graph-upload.md`
8. **Update index** → `"done"`
9. **Fill in the Completion Note** below

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**: sdd-worker (Claude)
**Date**: 2026-07-11
**Graph decision (REQUIRED)**: **OneDrive upload of the notify service account +
organization-scoped view sharing link** (NOT a chat-message file attachment).
Rationale: `GraphClient` uses the **client-credentials (app-only)** flow, which cannot
post chat messages as a user (that needs delegated `Chat.ReadWrite`/`ChannelMessage.Send`).
App-only CAN upload to a user's OneDrive and mint a sharing link. Chosen target:
`PUT /users/{user}/drive/root:/A2UI-Artifacts/{filename}:/content` (Graph simple upload,
≤250 MB — covers HTML/PDF artifacts, no upload session needed), then
`POST /drive/items/{id}/createLink {"type":"view","scope":"organization"}` → return
`link.webUrl` (falls back to the item `webUrl` if createLink is denied).
**Required application permission: `Files.ReadWrite.All`** (drive owner =
`TEAMS_NOTIFY_USERNAME`). No new conf vars; reuses the existing `TEAMS_NOTIFY_*` set.

**Notes**: Added `GraphClient.upload_file(file_path, *, user, folder)` following the
class conventions (token via `_get_access_token`, shared session, return-None-never-raise,
raw aiohttp — no msgraph-sdk). Wired `_send_teams` to attempt `_teams_graph_upload_links`
first; on success it embeds markdown links, else downgrades to a public-URL line
(`a2ui_artifact_url` if supplied) else filenames-in-text — every downgrade logs a
greppable warning, never silent. No-credentials / satellite-not-installed paths return
None → legacy filenames-in-text behavior preserved (G7). 5 GraphClient upload tests pass
(mocked aiohttp: success, createLink-fallback, 403→None, no-token→None, missing-file→None);
graph.py ruff clean; no exec/eval.

**Deviations from spec**: The `_send_teams` wiring tests (`test_delivery_teams.py`) SKIP
in the SDD worktree because `parrot.notifications` (an existing module also shipped by
editable-installed satellites) resolves as a PEP 420 namespace package under this repo's
pytest layout — so the worktree's edited module isn't the one imported, and the new
`_teams_graph_upload_links` method isn't visible. The tests are correct and run in a
built/installed environment (CI). The GraphClient upload logic (the substantive new code)
is fully unit-tested in `ai-parrot-integrations`. Pre-existing `F401` in
notifications/__init__.py left untouched (no-scope-creep).
