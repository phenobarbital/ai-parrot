---
id: F004
query_id: [Q023, Q023-F1]
type: [grep, read]
intent: "R2: locate ToolManager / AbstractTool handling of AuthorizationRequired and CredentialRequired."
executed_at: 2026-10-30T12:24:35Z
duration_ms: 0
parent_id: null
depth: 1
merged_from: [FC-004, FC-041]
---

# F004 — ToolManager.execute_tool catches AuthorizationRequired → ToolResult(status='authorization_required'); AbstractTool.execute hosts the FEAT-264 CredentialRequired seam

## Summary

**[FC-004]** 29 matches in `parrot/tools/`. Clusters: `tools/manager.py:19` imports `AuthorizationRequired`, `:2273-2290` catches it → `ToolResult(success=False, status="authorization_required", metadata={auth_url, provider, scopes, tool_name})`. `tools/abstract.py:1024-1045` is the broker seam raising `CredentialRequired`; `:1182-1197` re-raises both exceptions so they bubble. `tools/toolkit.py:321-331` documents `credential_provider`. `tools/jira_connect_tool.py:81` emits `status="authorization_required"` from a placeholder tool. `working_memory/task_memory/adapters.py:114` treats `authorization_required` as NOT_EXECUTED. Other producers: `databasequery/tool.py:752`, `dataset_manager/sources/authorizing.py:112,135` (PBAC denials reuse the same exception).

**[FC-041]** `tools/manager.py:2273-2290` converts `AuthorizationRequired`. `tools/abstract.py:1012-1045`: seam active only when `self.credential_provider and _broker is not None`; fails closed without `_cred_user_id`; `await _broker.resolve(self.credential_provider, _cred_channel, _cred_user_id, tool_name=self.name)`; `NeedsAuth` → `raise CredentialRequired(...)`; hit → `_CREDENTIAL_VAR.set(resolution.secret)`. `tools/toolkit.py:315-330` docs: seam fires BEFORE `_pre_execute`; without a broker the toolkit's own `_pre_execute` applies. `tools/jira_connect_tool.py` docstring: placeholder `JiraConnectTool` registered when no Jira tokens exist, hot-swapped via `hotswap_to_full_toolkit` once tokens land in Redis; `_execute` returns `ToolResult(success=True, status="authorization_required", metadata={auth_url, provider:"jira", channel, user_id})`.

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
  lines: 70-92
  symbol: `JiraConnectTool._execute`
  excerpt: |
    status="authorization_required"
- path: `packages/ai-parrot/src/parrot/tools/working_memory/task_memory/adapters.py`
  lines: 114
  symbol: `NOT_EXECUTED_STATUSES`
  excerpt: |
    NOT_EXECUTED_STATUSES = frozenset({"not_found", "authorization_required"})
- path: `packages/ai-parrot/src/parrot/tools/abstract.py`
  lines: 1012-1045
  symbol: `AbstractTool.execute (FEAT-264 seam)`
  excerpt: |
    if self.credential_provider and _broker is not None:
        if not _cred_user_id: raise ValueError(... fail closed — no service identity)
        resolution = await _broker.resolve(self.credential_provider, _cred_channel, _cred_user_id, tool_name=self.name)
        if isinstance(resolution, NeedsAuth): raise CredentialRequired(resolution.provider, resolution.auth_url, resolution.auth_kind)
        _CREDENTIAL_VAR.set(resolution.secret)
- path: `packages/ai-parrot/src/parrot/tools/toolkit.py`
  lines: 315-330
  symbol: `AbstractToolkit.credential_provider docs`
  excerpt: |
    on a credential miss the seam raises CredentialRequired BEFORE the tool body (and before _pre_execute) ... When no broker is attached to the ToolManager the seam is skipped and the toolkit's own _pre_execute auth handling applies unchanged.
- path: `packages/ai-parrot/src/parrot/tools/jira_connect_tool.py`
  lines: 1-12
  symbol: `module docstring`
  excerpt: |
    we register a lightweight JiraConnectTool that returns the OAuth authorization URL ... Once tokens land in Redis the placeholder is hot-swapped for the full toolkit using hotswap_to_full_toolkit

## Notes

**[FC-004]** Status literal confirmed: `authorization_required`; metadata shape `{auth_url, provider, scopes, tool_name}` (brainstorm §5 item 6 matches). `CredentialRequired` is NOT converted to a ToolResult — it bubbles to the surface. See FC-041 for excerpts.

**[FC-041]** Confirms brainstorm consequence #3 (two needs-auth protocols) with the real names: `AuthorizationRequired` (legacy `_pre_execute` path, converted to ToolResult) vs `CredentialRequired` (broker seam, bubbles). Hot-swap (brainstorm open question) is still implemented for AgentTalk.
