---
id: F008
query_id: Q010,Q011,Q013
type: grep
intent: Find scheduling, Google Calendar, and Excel ingestion support for reminders and bank-statement import
executed_at: 2026-08-23T09:29:00Z
depth: 0
parent_id: null
---

# F008 — Scheduler and Excel exist; Google Calendar is auth-only (no calendar tools), O365 has real event tools

## Summary

Three separate answers:

**Scheduling — exists, but only in `ai-parrot-server`.** An APScheduler-based
`parrot/scheduler/manager.py` with a `BaseSchedulerCallback` extension point and
concrete callbacks (`SendEmailReportCallback`, `SendNotifyReportCallback`,
`CreateFileCallback`, `SaveDataCallback`), plus HTTP handlers
(`SchedulerJobsHandler`, `SchedulerCallbacksHandler`) and an autonomous
orchestrator/scheduler pair. Recurring tax-deadline reminders are therefore a
new *callback*, not new scheduling machinery — but they require running the
server distribution, not just the core library.

**Excel — exists twice.** `parrot_tools/excel.py` (an
`AbstractDocumentTool`-based agent tool) and `parrot_loaders/excel.py`
(`ExcelLoader`, with per-sheet and per-row document modes, factory-registered).

**Google Calendar — partial.** `parrot/interfaces/google.py` is a Google
Services client that declares calendar OAuth scopes and can hand back a calendar
service config, but there are **no calendar agent tools** (no create_event /
list_events). By contrast `parrot_tools/o365/events.py` plus
`o365/oauth_toolkit.py` provide real per-user-OAuth calendar event tools for
Office 365. So Google Calendar event tooling is genuinely net-new work; O365 is
an off-the-shelf alternative if the user is willing to switch calendars.

## Citations

- path: `packages/ai-parrot-server/src/parrot/scheduler/manager.py`
  lines: 277
  symbol: `_SchedulerNotification`

- path: `packages/ai-parrot-server/src/parrot/scheduler/functions/__init__.py`
  lines: 16-168
  symbol: `BaseSchedulerCallback` and subclasses
  excerpt: |
    class BaseSchedulerCallback(NotificationMixin):     # 16
    class SendEmailReportCallback(BaseSchedulerCallback)   # 68
    class CreateFileCallback(BaseSchedulerCallback)        # 116
    class SaveDataCallback(BaseSchedulerCallback)          # 130
    class SendNotifyReportCallback(BaseSchedulerCallback)  # 168

- path: `packages/ai-parrot-server/src/parrot/handlers/scheduler.py`
  lines: 14-52
  symbol: `SchedulerCatalogHelper`, `SchedulerCallbacksHandler`, `SchedulerJobsHandler`

- path: `packages/ai-parrot-server/src/parrot/autonomous/scheduler.py`
  lines: 1-1
  symbol: "autonomous scheduler"

- path: `packages/ai-parrot-tools/src/parrot_tools/excel.py`
  lines: 1-1
  symbol: "MS Excel Tool migrated to use AbstractDocumentTool framework."

- path: `packages/ai-parrot-loaders/src/parrot_loaders/excel.py`
  lines: 1-1
  symbol: `ExcelLoader`

- path: `packages/ai-parrot/src/parrot/interfaces/google.py`
  lines: 57-61, 688-762
  symbol: `GoogleClient` calendar support
  excerpt: |
    'calendar': ['https://www.googleapis.com/auth/calendar',
                 'https://www.googleapis.com/auth/calendar.readonly',
                 'https://www.googleapis.com/auth/calendar.events']
    'calendar': 'v3',                                       # line 720
    async def get_calendar_client(self, version: str = 'v3') -> Dict[str, Any]:
        """Get Google Calendar client config."""
        return {'service': 'calendar', 'version': version}   # line 762

- path: `packages/ai-parrot-tools/src/parrot_tools/o365/events.py`
  lines: 1-1
  symbol: "Office365 calendar event tools"

- path: `packages/ai-parrot-tools/src/parrot_tools/o365/oauth_toolkit.py`
  lines: 1-1
  symbol: "Office 365 toolkit with per-user OAuth 2.0 (delegated / 3LO) auth."

## Notes

`get_calendar_client` returning a dict of config rather than a live service
object is the tell: nothing downstream consumes it as a calendar client today.
Treat "Google Calendar tools" as a distinct, self-contained deliverable that
could be deferred out of a first release without blocking the Hooba automation.
