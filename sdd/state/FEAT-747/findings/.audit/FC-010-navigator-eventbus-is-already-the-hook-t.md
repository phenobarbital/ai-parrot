---
id: FC-010
query_id: Q031
type: grep
intent: "Find eventbus usage in parrot (default carrier): which package, which API (publish/subscribe/topics)."
executed_at: 2026-10-26T00:20:00Z
duration_ms: 0
parent_id: null
depth: 0
---

# FC-010 — navigator-eventbus is already the hook/telemetry bus across parrot

## Summary

`eventbus|EventBus|navigator_eventbus|navigator\.eventbus` matches ~70 source files (plus duplicated `build/lib*` copies, which are stale artifacts). Clusters: (1) `parrot/core/hooks/*` — every inbound hook (`matrix`, `messaging` Telegram/WhatsApp/MSTeams, `jira_webhook`, `github_webhook`, `imap`, `postgres`, `sharepoint`, `file_upload`) subclasses `navigator_eventbus.hooks.base.BaseHook`; (2) `parrot/core/events/lifecycle/*` + `observability/fanout.py`/`bootstrap.py` — lifecycle telemetry fan-out; (3) `ai-parrot-server/parrot/autonomous/{evb,orchestrator,webhooks}.py` — autonomous orchestrator listens on the bus; (4) `integrations/matrix/hook.py` — `MatrixHook(BaseHook)` registered in `HookRegistry`. The bus is used for hooks and telemetry, not yet as an agent-to-agent carrier.

## Citations

- path: `packages/ai-parrot-integrations/src/parrot/integrations/matrix/hook.py`
  lines: 1-27
  symbol: `MatrixHook`
  excerpt: |
    Concrete implementation of :class:`~navigator_eventbus.hooks.base.BaseHook`
    from navigator_eventbus.hooks.base import BaseHook, HookRegistry
    from navigator_eventbus.hooks.models import HookType, MatrixHookConfig
    class MatrixHook(BaseHook):

- path: `packages/ai-parrot/src/parrot/core/hooks/messaging.py`
  lines: 21-70
  symbol: `_MessagingHookBase / TelegramHook`
  excerpt: |
    class _MessagingHookBase(BaseHook): ...  class TelegramHook(_MessagingHookBase):

- path: `packages/ai-parrot/src/parrot/observability/fanout.py`
  lines: 1
  symbol: `module`
  excerpt: |
    eventbus fan-out of lifecycle events (FEAT-710)

- path: `packages/ai-parrot-server/src/parrot/autonomous/evb.py`
  lines: 1
  symbol: `module`
  excerpt: |
    autonomous orchestrator event-bus adapter


## Notes

Representative tests: `tests/core/hooks/test_hookmanager_eventbus.py`, `tests/core/hooks/test_hookmanager_route_to_bus.py`, `ai-parrot-server/tests/test_orchestrator_eventbus_listener.py`, `ai-parrot-integrations/tests/test_matrix_hook.py`. `[cross-lane: type=wiki_page, intent=navigator-eventbus API surface (publish/subscribe/topics/reply_to) — FW-008 may cover]`
