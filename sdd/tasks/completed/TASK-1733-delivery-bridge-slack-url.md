# TASK-1733: Delivery bridge: RenderedArtifact → send_notification + Slack URL downgrade

**Feature**: FEAT-273 — A2UI Protocol Integration — Rendering Core (parrot.outputs.a2ui)
**Spec**: sdd/specs/a2ui-implementation.spec.md
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-1728
**Assigned-to**: unassigned

---

## Context

Spec §3 Module 7 (first half): baked A2UI surfaces produce a `RenderedArtifact`
(created by TASK-1728) that must reach users through the EXISTING notification
machinery — `NotificationMixin.send_notification()` — not a new delivery stack
(spec G5). Today the mixin's attachment extraction already handles
EMAIL (full attachments) and TELEGRAM (typed `send_photo`/`send_document`),
but SLACK is text-only and TEAMS lists filenames in text. This task builds the
core-side bridge (`delivery.py`) that maps a `RenderedArtifact` onto
`send_notification(report=…)` so attachments flow through the existing
`report.files` precedence, and adds the Slack public-URL downgrade line.
The Teams Graph upload is the follow-up task (TASK-1734).

Spec anchors: §2 Integration Points (`parrot/notifications/` row), §3 Module 7,
§5 AC **G5**, §7 Known Risks (degraded delivery must never be silent).

---

## Scope

- Implement `packages/ai-parrot/src/parrot/outputs/a2ui/delivery.py`: an async
  delivery bridge that takes a `RenderedArtifact` (+ recipients, provider,
  subject/message) and calls `NotificationMixin.send_notification()` on the
  owning agent, passing the artifact so that its file lands in the
  `report.files` extraction path of `_extract_message_content` (PRIORITY 1:
  `report.files` → PRIORITY 2: `report.documents` → content blocks with
  `type == "file"`). The bridge must materialize `RenderedArtifact.content`
  (inline bytes) to `RenderedArtifact.path` (temp file) when a file path is
  required by the provider, honoring the model's content-XOR-path convention.
- Implement per-provider delivery policy in the bridge:
  - **EMAIL**: full attachment via `report.files` (works today — no mixin change).
  - **TELEGRAM**: attachment via `report.files` → typed `send_document`/`send_photo`
    (works today — no mixin change).
  - **SLACK**: modify `_send_slack` in
    `packages/ai-parrot/src/parrot/notifications/__init__.py` (currently
    TEXT-ONLY, :525) so that when the delivery carries a `RenderedArtifact`
    with an `ArtifactStore`-persisted envelope/artifact, a public artifact URL
    line (via `ArtifactStore.get_public_url`, `storage/artifacts.py:177`) is
    appended to the outgoing message text. No Slack file upload (spec Non-Goal).
  - **TEAMS**: route through the existing `_send_teams` behavior unchanged
    (filenames-in-text) — Graph upload is TASK-1734's scope.
- Emit a **degraded-delivery log line** (via `self.logger`) whenever a provider
  cannot deliver the real file and the bridge downgrades to a URL or
  filenames-in-text. Degradation must NEVER be silent (spec §7 risk table).
- Write unit tests: `test_rendered_artifact_notification_bridge`,
  `test_slack_public_url_downgrade` (spec §4 unit-test table, Module 7 rows).

**NOT in scope**:
- Teams Graph-API file upload and `_send_teams` changes → TASK-1734.
- Deep-link minting / `DeepLinkService` → TASK-1735 (this bridge only carries
  `RenderedArtifact.deep_links` opaquely if present).
- `RenderedArtifact` / `DeepLink` model definitions themselves → TASK-1728.
- ArtifactStore persistence of envelopes (save path) → TASK-1728; this task
  only CONSUMES `get_public_url`.
- Any change to `AIMessage` or `OutputMode` → TASK-1738.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/outputs/a2ui/delivery.py` | CREATE | Delivery bridge: `RenderedArtifact` → `send_notification` with per-provider policy |
| `packages/ai-parrot/src/parrot/notifications/__init__.py` | MODIFY | `_send_slack` gains public-artifact-URL line + degraded-delivery log |
| `packages/ai-parrot/tests/outputs/a2ui/test_delivery.py` | CREATE | Unit tests (mocked notify providers / ArtifactStore) |

---

## Codebase Contract (Anti-Hallucination)

> **CRITICAL**: This section contains VERIFIED code references from the actual codebase.
> The implementing agent MUST use these exact imports, class names, and method signatures.
> **DO NOT** invent, guess, or assume any import, attribute, or method not listed here.
> If you need something not listed, VERIFY it exists first with `grep` or `read`.

### Verified Imports
```python
from parrot.notifications import NotificationMixin, NotificationProvider  # notifications/__init__.py:56/:23
from parrot.storage.artifacts import ArtifactStore  # storage/artifacts.py:27
```

### Existing Signatures to Use
```python
# packages/ai-parrot/src/parrot/notifications/__init__.py
class NotificationProvider(Enum):  # :23
    EMAIL = "email"; SLACK = "slack"; TELEGRAM = "telegram"; TEAMS = "teams"

class NotificationMixin:  # :56
    async def send_notification(  # :131
        self, message, recipients,
        provider: Union[str, NotificationProvider] = NotificationProvider.EMAIL,
        subject=None, report=None, template=None, with_attachments: bool = True,
        provider_options=None, **kwargs
    ) -> Dict[str, Any]
    def _extract_message_content(self, message, report=None) -> tuple[str, List[Path]]  # :256
        # PRIORITY 1: report.files → PRIORITY 2: report.documents → content blocks (type=="file")
    async def _send_slack(self, notify_args: Dict[str, Any]) -> Any  # :525 — TEXT-ONLY today
        # body: `from notify.providers.slack import Slack` → `await conn.send(**notify_args)`
    async def _send_telegram(...)  # :533 — typed send_photo (:567) / send_document (:619)
    async def _send_teams(self, notify_args, files: Optional[List[Path]] = None) -> Any  # :655
        # today: appends "**Attached Files:**" filename list into message text ONLY

# packages/ai-parrot/src/parrot/bots/agent.py:29
class BasicAgent(Chatbot, NotificationMixin):  # send_notification surface lives HERE

# packages/ai-parrot/src/parrot/storage/artifacts.py
class ArtifactStore:  # :27
    async def save_artifact(...)  # :46
    async def get_public_url(  # :177
        self, user_id: Union[str, int], agent_id: str, session_id: str,
        artifact_id: str, *, format: Literal["html", "json"] = "html",
    ) -> str  # presigned S3 URL, max 7 days, no auth required

# packages/ai-parrot/src/parrot/outputs/a2ui/artifacts.py — from TASK-1728 (spec §2 Data Models)
class RenderedArtifact(BaseModel):
    artifact_id: str; mime_type: str
    content: Optional[bytes]   # inline, XOR path
    path: Optional[Path]       # temp file for attachments
    filename: str; title: str; surface: str
    source_envelope_ref: Optional[str]
    deep_links: List[DeepLink] = []
    metadata: Dict[str, Any] = {}
```

### Does NOT Exist
- ~~`Agent.notification()` / `Agent.notify()`~~ — the surface is
  `NotificationMixin.send_notification` on `BasicAgent` only (NOT `AbstractBot`).
- ~~Real file attachments for Slack notifications~~ — `_send_slack` is
  text-only today; this task adds a URL line, NOT an upload (Slack upload is a
  spec Non-Goal).
- ~~Real file attachments for Teams~~ — `_send_teams` lists filenames in text
  today; fixed by TASK-1734, not here.
- ~~`RenderedArtifact` before TASK-1728 lands~~ — verify
  `parrot/outputs/a2ui/artifacts.py` exists and matches the shape above before
  starting; update this contract if fields drifted.

---

## Implementation Notes

### Pattern to Follow
- The bridge is a thin adapter: build (or wrap) an object whose `.files`
  attribute contains the artifact's file path so `_extract_message_content`
  picks it up via the PRIORITY 1 branch — do NOT reimplement attachment
  extraction, and do NOT add a new provider dispatch parallel to
  `send_notification`.
- `_send_slack` modification stays minimal: message-text enrichment before the
  existing `conn.send(**notify_args)` call, mirroring how `_send_teams` (:655)
  enriches `notify_args["message"]` today.
- One-way import rule (spec G8): `parrot.outputs.a2ui.delivery` must NOT import
  agents, DatasetManager, or LLM clients. It receives the mixin-bearing owner
  (or the bound `send_notification` callable) as a parameter.

### Key Constraints
- Async throughout; Pydantic v2 for any new config/result model; Google-style
  docstrings; `self.logger` (no prints).
- Degraded delivery (Slack URL line, Teams filenames-in-text) MUST log a
  clearly greppable warning naming provider + artifact_id — never silent.
- `get_public_url` requires `user_id`/`agent_id`/`session_id`/`artifact_id` —
  the bridge must take these as explicit delivery-context parameters; if the
  artifact was never persisted (`source_envelope_ref is None`) the Slack path
  logs the degradation and sends text only.
- Temp files written for inline `content` must be cleaned up after send
  (no filesystem side-effects outside explicit artifact paths — spec §7).
- Core `ai-parrot` gains zero new dependencies (G8).

### References in Codebase
- `packages/ai-parrot/src/parrot/notifications/__init__.py` — the entire
  delivery surface this task bridges into.
- `packages/ai-parrot/src/parrot/storage/artifacts.py` — `get_public_url`
  semantics (presigned S3, 7-day max).
- Spec §4 unit-test row `test_rendered_artifact_notification_bridge`.

---

## Acceptance Criteria

- [ ] Implementation complete per scope
- [ ] All tests pass: `pytest packages/ai-parrot/tests/outputs/a2ui/test_delivery.py -v`
- [ ] No linting errors: `ruff check packages/ai-parrot/src/parrot/outputs/a2ui/delivery.py packages/ai-parrot/src/parrot/notifications/__init__.py`
- [ ] Imports work: `from parrot.outputs.a2ui.delivery import <bridge entry point>`
- [ ] EMAIL and TELEGRAM paths deliver the artifact file through the unmodified `report.files` precedence (proven by test with mocked providers)
- [ ] SLACK path appends exactly one public-URL line via `ArtifactStore.get_public_url` and emits a degraded-delivery log record
- [ ] No degradation path is silent (log assertions in tests)
- [ ] Existing notification tests remain green (G7): `pytest packages/ai-parrot/tests -k notification -v`
- [ ] No `exec(`/`eval(` introduced (G1)

---

## Test Specification

> Minimal test scaffold. The agent must make these pass.
> Add more tests as needed. Names below are mandated by spec §4.

```python
# packages/ai-parrot/tests/outputs/a2ui/test_delivery.py

class TestRenderedArtifactNotificationBridge:
    async def test_rendered_artifact_notification_bridge(self):
        """RenderedArtifact maps onto send_notification so its file is
        extracted via the report.files PRIORITY-1 branch of
        _extract_message_content (EMAIL provider, mocked)."""

    async def test_telegram_attachment_flows_as_document(self):
        """TELEGRAM delivery routes the artifact file through the existing
        typed send_document path (mocked provider)."""

    async def test_slack_public_url_downgrade(self):
        """SLACK delivery appends the ArtifactStore.get_public_url line to the
        message text and emits a degraded-delivery warning log."""

    async def test_slack_unpersisted_artifact_logs_and_sends_text(self):
        """SLACK delivery of an artifact with no persisted envelope ref sends
        text only and logs the degradation (never raises, never silent)."""

    async def test_inline_content_materialized_and_cleaned(self):
        """content-only RenderedArtifact is written to a temp file for
        attachment providers and the temp file is removed after send."""
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
7. **Move this file** to `tasks/completed/TASK-1733-delivery-bridge-slack-url.md`
8. **Update index** → `"done"`
9. **Fill in the Completion Note** below

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**: sdd-worker (Claude)
**Date**: 2026-07-11
**Notes**: Created `parrot/outputs/a2ui/delivery.py` — `deliver_artifact(owner, artifact,
*, recipients, provider, message, subject, artifact_store, user_id, agent_id,
session_id)`. EMAIL/TELEGRAM/TEAMS materialize inline `content` to a temp file (cleaned
in `finally`; a pre-existing `artifact.path` is never deleted) and deliver via a
`_DeliveryReport.files` object that hits the mixin's `report.files` PRIORITY-1
extraction — no new provider dispatch. SLACK computes `ArtifactStore.get_public_url`
(when the artifact is persisted + context supplied) and passes it as an
`a2ui_artifact_url` kwarg; `_send_slack` (notifications/__init__.py) was modified to pop
that kwarg, append a public-URL line to the message, and log a degraded-delivery warning
(mirrors `_send_teams` text enrichment). Every degraded path (Slack URL, Slack text-only,
Teams filenames) logs a greppable warning — never silent. 7 tests pass; delivery.py ruff
clean; no exec/eval; zero new core deps.

**Deviations from spec**: The bridge does NOT import `NotificationProvider` from
`parrot.notifications` (the task's contract listed that import). Reason: under the
monorepo's many editable installs, importing `parrot.notifications` at a2ui-module load
resolves `parrot` as a namespace package inconsistently under pytest ("unknown location"
collection error), and it also better honors G8 (a2ui core must not import the
notifications subsystem). The provider is accepted as a string matching the
`NotificationProvider` enum *values* (`email`/`slack`/`telegram`/`teams`) and forwarded
verbatim to `owner.send_notification`. Pre-existing `F401` lint in
`notifications/__init__.py` (unused `TeamsCard`, present on dev) was left untouched
(no-scope-creep); my `_send_slack` change is lint-clean.
