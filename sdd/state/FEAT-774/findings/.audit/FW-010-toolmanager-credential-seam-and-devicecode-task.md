---
id: FW-010
query_id: Q006
type: wiki_page
intent: "Depth-2 from Q006: TASK-1685 (CLI device-code bootstrap) — the ToolManager credential seam a CLI must feed, and the broker build in AbstractBot.configure."
executed_at: 2026-10-30T15:24:30Z
duration_ms: 1200
parent_id: FW-002
depth: 2
---

# FW-010 — The CLI feeds identity through `PermissionContext` → `ToolManager` (`_broker`, `_cred_channel`, `_cred_user_id`) → tool seam; the broker is built in `AbstractBot.configure()` from `self._credentials`

## Summary

TASK-1685 (FEAT-266) documents, with verified anchors of its time, the propagation seam S-4 must reuse rather than re-implement: `ToolManager.set_broker(broker)` (manager.py ~:320); `exec_kwargs['_broker'] = self._broker` (~:1306); `exec_kwargs.setdefault('_cred_channel', getattr(permission_context, 'channel', 'unknown'))` (~:1308-1312) and `'_cred_user_id', getattr(permission_context, 'user_id', None)` (~:1313-1316); the broker is built once in `AbstractBot.configure()` via `CredentialBroker.from_config(self._credentials, **_broker_deps)` then `self.tool_manager.set_broker(broker)` (abstract.py ~:1401-1402). The task's chosen entry point was the existing agent-run path (no `parrot o365 login` command); the device-code resolver fires inline on first use and persists to `VaultTokenSync` `o365:*`, proven consumable by `WorkIQOBOCredentialResolver`. For S-4: a CLI `PrincipalResolver` output must land in `permission_context.user_id`; stdio MCP servers never run `AbstractBot.configure()` (FW-004), so they have no broker at all today.

## Citations

- path: `sdd/tasks/completed/TASK-1685-cli-devicecode-bootstrap.md`
  symbol: Codebase Contract
  excerpt: |
    # parrot/tools/manager.py
    #   self._broker set via ToolManager.set_broker(broker)                    # line 320
    #   exec_kwargs['_broker'] = self._broker                                  # line 1306
    #   exec_kwargs.setdefault('_cred_channel', getattr(permission_context, 'channel', 'unknown'))   # line 1308-1312
    #   exec_kwargs.setdefault('_cred_user_id', getattr(permission_context, 'user_id', None))        # line 1313-1316
    # parrot/bots/abstract.py
    #   broker = CredentialBroker.from_config(self._credentials, **_broker_deps)   # line 1401
    #   self.tool_manager.set_broker(broker)                                       # line 1402

- path: `packages/ai-parrot/src/parrot/tools/manager.py`
  lines: 1305-1316
  symbol: `ToolManager` credential propagation
  excerpt: |
    (as cited by TASK-1685; line numbers are from 2026-05 and MUST be re-verified)

- path: `packages/ai-parrot/src/parrot/bots/abstract.py`
  lines: 1389-1402
  symbol: `AbstractBot.configure`
  excerpt: |
    broker = CredentialBroker.from_config(self._credentials, **_broker_deps)
    self.tool_manager.set_broker(broker)

- path: `packages/ai-parrot/src/parrot/auth/identity.py`
  lines: 57-75
  symbol: `CanonicalIdentityMapper.to_canonical`
  excerpt: |
    def to_canonical(raw_identity: Dict[str, Any]) -> Optional[str]: ...   # OID → email → None

## Notes

Wiki: `file:sdd/tasks/completed/TASK-1685-cli-devicecode-bootstrap.md` (0.66 on Q006). The task doc's "Does NOT Exist" recorded: no dedicated `parrot o365 login` command; no pre-existing `channel="cli"` context before FEAT-266. Also surfaced: `sdd/specs/o365-auth-homologation.spec.md` (FEAT-266) — device-code is the `device_code` broker kind; S-1 keeps `VaultTokenSync` for device-code.
[cross-lane: type=grep, intent=re-verify `_cred_channel|_cred_user_id|set_broker` line numbers in parrot/tools/manager.py and `from_config` in bots/abstract.py (plan Q015 covers mcp/cli/agentd only — extend to tools/manager.py)]
