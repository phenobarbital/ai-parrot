---
id: FC-041
query_id: Q023-F1
type: read
intent: "Follow-up: read ToolManager catch, AbstractTool broker seam, toolkit credential_provider docs and JiraConnectTool placeholder."
executed_at: 2026-10-30T12:24:35Z
duration_ms: 0
parent_id: FC-004
depth: 1
---

# FC-041 — Two auth protocols in the tool loop: AuthorizationRequired -> ToolResult(authorization_required) in ToolManager; CredentialRequired raised by the FEAT-264 seam in AbstractTool.execute and bubbled to the surface; JiraConnectTool placeholder + hotswap still exist for AgentTalk

## Summary

`tools/manager.py:2273-2290` converts `AuthorizationRequired`. `tools/abstract.py:1012-1045`: seam active only when `self.credential_provider and _broker is not None`; fails closed without `_cred_user_id`; `await _broker.resolve(self.credential_provider, _cred_channel, _cred_user_id, tool_name=self.name)`; `NeedsAuth` → `raise CredentialRequired(...)`; hit → `_CREDENTIAL_VAR.set(resolution.secret)`. `tools/toolkit.py:315-330` docs: seam fires BEFORE `_pre_execute`; without a broker the toolkit's own `_pre_execute` applies. `tools/jira_connect_tool.py` docstring: placeholder `JiraConnectTool` registered when no Jira tokens exist, hot-swapped via `hotswap_to_full_toolkit` once tokens land in Redis; `_execute` returns `ToolResult(success=True, status="authorization_required", metadata={auth_url, provider:"jira", channel, user_id})`.

## Citations

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
- path: `packages/ai-parrot/src/parrot/tools/jira_connect_tool.py`
  lines: 70-92
  symbol: `JiraConnectTool._execute`
  excerpt: |
    return ToolResult(success=True, status="authorization_required", result=..., metadata={"auth_url": auth_url, "provider": "jira", "channel": self._channel, "user_id": self._user_id})

## Notes

Confirms brainstorm consequence #3 (two needs-auth protocols) with the real names: `AuthorizationRequired` (legacy `_pre_execute` path, converted to ToolResult) vs `CredentialRequired` (broker seam, bubbles). Hot-swap (brainstorm open question) is still implemented for AgentTalk.
