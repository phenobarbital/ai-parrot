# TASK-4574: Human-confirmed Jira tickets: approval protocol, template, backlink

**Feature**: FEAT-715 — FirefliesInsightsAgent
**Spec**: `sdd/specs/fireflies-insights-agent.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: L (4-8h)
**Depends-on**: TASK-4572, TASK-4573
**Assigned-to**: unassigned

---

## Context

Spec §3 **Module 7** (code half), **C8**, design-research **S7** and **S8**. A ticket is
created only after an explicit Telegram confirmation; a replayed confirmation returns the
existing key; a stale or foreign confirmation is refused with an explicit reason.

**What the Telegram wrapper actually provides** (verified at task time,
`integrations/telegram/wrapper.py:780-800`): the command handler checks
`self._is_authorized(chat_id)` and runs the method inside
`telegram_chat_scope(chat_id)`, so `get_current_telegram_chat_id()` returns the invoking
chat. **No user id is propagated.** `PendingApproval.user_id` therefore stays `None`, and
authorization is *chat match + expiry* (plus the wrapper's own allowlist). This is
consistent with the spec ("the user must match **when known**") — it is never known.

**Durable state — decided here**: one JSON file,
`<FIREFLIES_REGISTRY_DIR>/fireflies_insights_state.json`, shape
`{"approvals": {insight_id: PendingApproval}, "insights": {meeting_id: MeetingInsights}}`,
written atomically (temp + `os.replace`). Insights are stored because `PendingApproval`
carries only `fireflies_id` + `action_index`. TTL: **72 h** (`APPROVAL_TTL`), bounded by AC24.

---

## Scope

- State helpers: `_state_path`, `_load_state()`, `_save_state()` (atomic, via `asyncio.to_thread`).
- `_register_approvals(insights, chat_id) -> list[PendingApproval]` with a **stable**
  `insight_id = sha256(f"{meeting_id}:{index}:{title}")[:12]`, so re-reporting the same
  meeting reuses ids instead of minting new ones.
- Extend `notify_insights`: register approvals for `public_channel_id`, append one escaped
  line per action item: `/fireflies_ticket <insight_id> — <title>`.
- `@telegram_command("fireflies_ticket", ..., parse_mode="raw") cmd_create_ticket(text)`.
- `_authorize(approval, chat_id, user_id) -> bool`, `_create_ticket(insights, item) -> dict`,
  `_wiki_backlink(fireflies_id) -> str | None`.
- **Ordering (S8, binding)**: write `created_ticket` to the state file **before** returning
  the reply, so a crash after Jira answered cannot cause a second ticket on retry.

**NOT in scope**: the template file (TASK-4573 — consume its ten-key contract verbatim);
integration tests (TASK-4575); docs (TASK-4576).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/bots/fireflies_insights.py` | MODIFY | Durable approvals, `/fireflies_ticket`, templated ticket, best-effort backlink |
| `packages/ai-parrot/tests/bots/test_fireflies_insights.py` | MODIFY | Authorization / idempotence / expiry / backlink tests |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
import hashlib, json                                                          # stdlib
from datetime import datetime, timedelta, timezone                           # stdlib
from parrot.integrations.telegram.context import get_current_telegram_chat_id  # verified: integrations/telegram/context.py (also lazy-exported, telegram/__init__.py:45)
```

### Existing Signatures to Use
```python
# packages/ai-parrot-tools/src/parrot_tools/jiratoolkit.py:2608
async def jira_create_issue(self, project: Optional[str] = None, summary: str = "", issuetype: Optional[str] = None,
                            description: Optional[str] = None, assignee: Optional[str] = None,
                            priority: Optional[str] = None, labels: Optional[List[str]] = None,
                            components: Optional[List[str]] = None, due_date: Optional[str] = None,
                            parent: Optional[str] = None, original_estimate: Optional[str] = None,
                            fields: Optional[Dict[str, Any]] = None, template: Optional[str] = None,
                            template_params: Optional[Dict[str, Any]] = None) -> Dict[str, Any]
#   success → {"ok": True, "id": ..., "key": ..., "issue": {...}}   (packages/ai-parrot-tools/src/parrot_tools/jiratoolkit.py:2795)
#   an unknown template or a missing variable fails BEFORE any Jira request (packages/ai-parrot-tools/src/parrot_tools/jiratoolkit.py:~2692)
#   project / issuetype fall back to JIRA_DEFAULT_PROJECT / JIRA_DEFAULT_ISSUE_TYPE (packages/ai-parrot-tools/src/parrot_tools/jiratoolkit.py:945-946)
# packages/ai-parrot/src/parrot/agents/meeting_registry.py:236  async def lookup(self, fireflies_id: str) -> MeetingRecord | None
# packages/ai-parrot/src/parrot/agents/meeting_registry.py:110  MeetingRecord.wiki_ingested_at: str | None
# telegram/context.py  def get_current_telegram_chat_id() -> Optional[str]
```

### Does NOT Exist
- ~~a Telegram user id in command context~~ — only the chat id is scoped.
- ~~`MeetingRegistry.mark_wiki_ingested()` returning a page path~~ — it returns an `int`
  row count (packages/ai-parrot/src/parrot/agents/meeting_registry.py:560); it cannot resolve a backlink.
- ~~a public "find wiki page by external id" helper~~ — **(unverified — check before
  use)**: the inbox processor resolves a known source by external id privately
  (`inbox/processor.py:254 _existing_doc_id`). `_wiki_backlink` must locate an equivalent
  public `SourceCollectionManager` lookup and verify it exists before calling it; if none
  exists, it returns `None` (best-effort is still met, AC14) and says so in the Completion Note.

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {
      "path": "packages/ai-parrot/src/parrot/bots/fireflies_insights.py",
      "action": "MODIFY"
    },
    {
      "path": "packages/ai-parrot/tests/bots/test_fireflies_insights.py",
      "action": "MODIFY"
    }
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot-tools/src/parrot_tools/jiratoolkit.py#JiraToolkit.jira_create_issue",
    "sym:packages/ai-parrot/src/parrot/agents/meeting_registry.py#MeetingRegistry.lookup"
  ]
}
```

---

## Implementation Blueprint

### Steps (in order)
1. Add imports and the state helpers — *why*: S8 durability.
2. Extend `notify_insights` — *why*: users need the id to confirm.
3. Add `cmd_create_ticket`, `_authorize`, `_create_ticket`, `_wiki_backlink`.
4. Tests.

### `packages/ai-parrot/src/parrot/bots/fireflies_insights.py` (MODIFY — methods appended to `FirefliesInsightsAgent`)
```python
    APPROVAL_TTL = timedelta(hours=72)
    JIRA_TEMPLATE = "fireflies/action_item"

    @property
    def _state_path(self) -> Path:
        return Path(FIREFLIES_REGISTRY_DIR).expanduser() / "fireflies_insights_state.json"

    def _load_state(self) -> dict[str, Any]:
        """{"approvals": {...}, "insights": {...}}; a missing or corrupt file is an empty state."""
        # FILL IN: json.loads, tolerate FileNotFoundError / JSONDecodeError (log WARNING)
        raise NotImplementedError

    def _save_state(self, state: dict[str, Any]) -> None:
        """Atomic: write <dir>/.<name>.tmp then os.replace()."""
        # FILL IN: mkdir parents; json.dumps(state, indent=2, default=str)
        raise NotImplementedError

    async def _register_approvals(self, insights: MeetingInsights, chat_id: str) -> list[PendingApproval]:
        """Stable insight ids; persists insights + approvals; keeps an existing created_ticket."""
        # FILL IN: id = hashlib.sha256(f"{insights.meeting_id}:{i}:{item.title}".encode()).hexdigest()[:12];
        #   expires_at = now(UTC) + APPROVAL_TTL; never overwrite an approval whose created_ticket is set
        raise NotImplementedError

    @telegram_command("fireflies_ticket", description="Create a Jira ticket from a reported action item", parse_mode="raw")
    async def cmd_create_ticket(self, text: str = "") -> str:
        """Human confirmation gate (C8). Idempotent: a replay returns the existing key (AC13)."""
        insight_id = text.strip()
        state = await asyncio.to_thread(self._load_state)
        raw = state.get("approvals", {}).get(insight_id)
        if raw is None:
            return f"Unknown insight id: {insight_id or '(none)'}"
        approval = PendingApproval.model_validate(raw)
        if approval.created_ticket:
            return f"Already created: {approval.created_ticket}"
        chat_id = get_current_telegram_chat_id()
        if not await self._authorize(approval, chat_id, None):
            # FILL IN: explicit reason — "expired" vs "not the reporting chat" (AC23, AC24)
            raise NotImplementedError
        # FILL IN: insights = MeetingInsights.model_validate(state["insights"][approval.fireflies_id]);
        #   item = insights.action_items[approval.action_index]; result = await self._create_ticket(insights, item);
        #   not result.get("ok") -> return the error, do NOT mark created;
        #   approval.created_ticket = result["key"]; persist via _save_state BEFORE returning (S8);
        #   return f"Created {result['key']}"
        raise NotImplementedError

    async def _authorize(self, approval: PendingApproval, chat_id: str | None, user_id: str | None) -> bool:
        """Chat must match, not expired; user must match only when both are known (never today)."""
        # FILL IN: compare str(chat_id) == approval.chat_id; datetime.fromisoformat(approval.expires_at) > now(UTC);
        #   approval.user_id and user_id -> must be equal
        raise NotImplementedError

    async def _create_ticket(self, insights: MeetingInsights, item: ActionItem) -> dict[str, Any]:
        """JiraToolkit.jira_create_issue with the TASK-4573 ten-key template contract."""
        if self.jira_toolkit is None:
            return {"ok": False, "error": "Jira is not configured"}
        params = {
            "meeting_title": insights.meeting_title, "meeting_date": insights.meeting_date,
            "meeting_id": insights.meeting_id, "action_title": item.title, "owner": item.owner,
            "due_date": item.due_date, "evidence": item.evidence, "decisions": insights.decisions,
            "risks": insights.risks, "wiki_url": await self._wiki_backlink(insights.meeting_id),
        }
        return await self.jira_toolkit.jira_create_issue(
            summary=f"[{insights.meeting_title}] {item.title}"[:250],
            template=self.JIRA_TEMPLATE,
            template_params=params,
            labels=["fireflies", f"meeting-{insights.meeting_id}"],
        )

    async def _wiki_backlink(self, fireflies_id: str) -> str | None:
        """Best-effort (C8, AC14): None unless ingestion already produced a page. NEVER raises or waits."""
        try:
            # FILL IN: resolve the wiki page for external id f"fireflies:{fireflies_id}" — see the
            #   (unverified) note in Does NOT Exist; return a link string or None
            return None
        except Exception as exc:  # noqa: BLE001
            self.logger.debug("FirefliesInsights: backlink for %s unavailable: %s", fireflies_id, exc)
            return None
```

### `packages/ai-parrot/src/parrot/bots/fireflies_insights.py` (MODIFY — ticket footer inside `notify_insights`)
```python
# occurrences: 1 (verified at task time: grep -cF '        text = self._format_insights_message(insights)' packages/ai-parrot/src/parrot/bots/fireflies_insights.py — written by TASK-4572)
# AFTER — insert directly below that line
        approvals = await self._register_approvals(insights, str(self.public_channel_id))
        if approvals:
            lines = [
                f"/fireflies_ticket {a.insight_id} — {html.escape(insights.action_items[a.action_index].title)}"
                for a in approvals
            ]
            text = text + "\n\n<b>Open a Jira ticket</b>\n" + "\n".join(lines)
```
**Why**: the approval is bound to the channel the insight was reported in — the same
value `_authorize` compares against `get_current_telegram_chat_id()`.

### FILL IN checklist
- [ ] state helpers (corrupt file tolerated; atomic write).
- [ ] `_register_approvals` (stable ids; never clobber `created_ticket`).
- [ ] `cmd_create_ticket` refusal reasons + persist-before-reply.
- [ ] `_authorize`.
- [ ] `_wiki_backlink` — verify a public lookup first, else stay `None`.
- [ ] `packages/ai-parrot/tests/bots/test_fireflies_insights.py` tests below.

---

## Acceptance Criteria

- [ ] **AC12** No `jira_create_issue` call happens without a `/fireflies_ticket` confirmation.
- [ ] **AC13** A second confirmation of the same id returns the existing key; Jira is called once.
- [ ] **AC14** With no wiki page, the ticket is created with `wiki_url=None` and the call succeeds.
- [ ] **AC23** A confirmation from another chat is refused.
- [ ] **AC24** A confirmation after `expires_at` is refused with an explicit "expired" reason.
- [ ] A failed Jira call leaves `created_ticket` unset so a retry can succeed.

---

## Validation Commands

> File-level pytest only — no directories, no package roots.

- `pytest packages/ai-parrot/tests/bots/test_fireflies_insights.py -q`

---

## Test Specification

```python
# packages/ai-parrot/tests/bots/test_fireflies_insights.py  (append) — FIREFLIES_REGISTRY_DIR → tmp_path (monkeypatch the module attribute)
async def test_ticket_requires_known_id(): ...
async def test_replayed_confirmation_is_idempotent(): ...        # fake jira_toolkit counts calls
async def test_foreign_chat_is_refused(): ...                    # telegram_chat_scope("other")
async def test_expired_approval_is_refused(): ...
async def test_failed_jira_call_does_not_mark_created(): ...
async def test_ticket_without_wiki_page_omits_backlink(): ...
async def test_insight_ids_are_stable_across_reports(): ...
```
> Use `from parrot.integrations.telegram.context import telegram_chat_scope` to set the
> invoking chat in tests — the same mechanism the real wrapper uses.

---

## Agent Instructions

When you pick up this task:

1. **Work in the feature worktree** — never on `dev`
   (`python -m scripts.sdd.ensure_worktree --slug fireflies-insights-agent --feature-id FEAT-715`).
2. **Read the spec** `sdd/specs/fireflies-insights-agent.spec.md` — §3 (the module this task implements) and §6.
3. **Check dependencies** — every `Depends-on` task must be `"done"` in
   `sdd/tasks/index/fireflies-insights-agent.json`.
4. **Verify the Codebase Contract** before writing code. Anchors were verified at
   `f6a4dbfca`; re-run every `grep -c` in the blueprint and use the fresh count.
   A count of `0` means the anchor moved — stop and report, never invent one.
5. **Update status** in the per-spec index → `"in-progress"` (set `started_at`)
   and commit only that index file.
6. **Implement** from the Implementation Blueprint; complete every `# FILL IN:`
   marker; never change a signature, class name or path the blueprint fixes.
7. **Run** the Validation Commands with `PYTHONPATH=packages/ai-parrot/src`
   (plus `packages/ai-parrot-tools/src:packages/ai-parrot-integrations/src`
   when the task imports them) — the shared venv is installed against the main
   checkout. Then `ruff check --fix` on every file you touched.
8. **Commit** only the files this task lists (never `git add .` / `-A`):
   `feat(fireflies-insights-agent): TASK-4574 — <title>`.
9. **Close** with `scripts/sdd/close_task.sh TASK-4574 fireflies-insights-agent verified` — never move
   the file by hand.
10. **Fill in the Completion Note** below, then commit the staged SDD state.

---

## Completion Note

**Completed by**: gpt-5.6-terra (codex seat) via sdd-worker orchestrator
**Date**: 2026-10-22
**Notes**: Implemented durable approval state (JSON, atomic os.replace), stable
insight_id via sha256(meeting_id:index:title)[:12], /fireflies_ticket command
with chat-bound authorization + 72h TTL, idempotent replay (returns existing key),
templated Jira ticket creation via fireflies/action_item template, and best-effort
wiki backlink via SourceCollectionManager.find_by_external_id. Extended notify_insights
to append confirmation lines. 7 new tests: unknown id, idempotent replay, foreign chat
refusal, expired approval, failed Jira, backlink omission, stable insight ids.
Seat: gpt-5.6-terra (codex), 1 attempt, 313s, merge-tier 111 passed.

**Deviations from spec**: none
