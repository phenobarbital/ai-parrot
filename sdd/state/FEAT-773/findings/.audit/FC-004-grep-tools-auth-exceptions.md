---
id: FC-004
query_id: Q023
type: grep
intent: "R2: locate ToolManager / AbstractTool handling of AuthorizationRequired and CredentialRequired."
executed_at: 2026-10-30T12:24:35Z
duration_ms: 0
parent_id: null
depth: 0
---

# FC-004 — ToolManager.execute_tool catches AuthorizationRequired → ToolResult(status='authorization_required'); AbstractTool.execute hosts the FEAT-264 CredentialRequired seam

## Summary

29 matches in `parrot/tools/`. Clusters: `tools/manager.py:19` imports `AuthorizationRequired`, `:2273-2290` catches it → `ToolResult(success=False, status="authorization_required", metadata={auth_url, provider, scopes, tool_name})`. `tools/abstract.py:1024-1045` is the broker seam raising `CredentialRequired`; `:1182-1197` re-raises both exceptions so they bubble. `tools/toolkit.py:321-331` documents `credential_provider`. `tools/jira_connect_tool.py:81` emits `status="authorization_required"` from a placeholder tool. `working_memory/task_memory/adapters.py:114` treats `authorization_required` as NOT_EXECUTED. Other producers: `databasequery/tool.py:752`, `dataset_manager/sources/authorizing.py:112,135` (PBAC denials reuse the same exception).

## Citations

- path: `packages/ai-parrot/src/parrot/tools/manager.py`
  lines: 2273-2290
  symbol: `ToolManager.execute_tool`
  excerpt: |
    except AuthorizationRequired as auth_exc:
        return ToolResult(success=False, status="authorization_required", result=None, error=auth_exc.message,
            metadata={"auth_url": auth_exc.auth_url, "provider": auth_exc.provider, "scopes": list(auth_exc.scopes), "tool_name": auth_exc.tool_name})
- path: `packages/ai-parrot/src/parrot/tools/abstract.py`
  lines: 1182-1197
  symbol: `AbstractTool.execute`
  excerpt: |
    from ..auth.exceptions import AuthorizationRequired
    if isinstance(e, AuthorizationRequired): raise
    from ..auth.credentials import CredentialRequired as _CR
    if isinstance(e, _CR): raise
- path: `packages/ai-parrot/src/parrot/tools/jira_connect_tool.py`
  lines: 81
  symbol: `JiraConnectTool._execute`
  excerpt: |
    status="authorization_required"
- path: `packages/ai-parrot/src/parrot/tools/working_memory/task_memory/adapters.py`
  lines: 114
  symbol: `NOT_EXECUTED_STATUSES`
  excerpt: |
    NOT_EXECUTED_STATUSES = frozenset({"not_found", "authorization_required"})

## Notes

Status literal confirmed: `authorization_required`; metadata shape `{auth_url, provider, scopes, tool_name}` (brainstorm §5 item 6 matches). `CredentialRequired` is NOT converted to a ToolResult — it bubbles to the surface. See FC-041 for excerpts.
