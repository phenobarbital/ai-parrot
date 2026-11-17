---
kind: inline
jira_key: null
fetched_at: 2026-10-30T15:16:24Z
summary_oneline: "S-4 of FEAT-773: CLI-based agents and MCP-based tools in a CLI consuming delegated-auth connections"
---

# Source (inline)

S-4 of FEAT-773: CLI-based agents (AgentREPL, agent daemon) and MCP-based tools in a CLI
(parrot mcp-local stdio servers for Claude Code / Codex) consuming delegated-auth connections.
See sdd/specs/delegated-auth-connections.spec.md §1 Non-Goals S-4 bullet and
sdd/proposals/delegated-auth-connections.proposal.md §6 S-4 row.

## Context carried from the parent feature (FEAT-773, S-1 spec rev 0.2)

The S-1 spec declares S-4 as a consumer sub-spec with three gaps S-1 does not close:

1. A CLI `PrincipalResolver` that maps a local login to a Navigator `user_id` (today
   `parrot/cli/identity.py` builds a `channel="cli"` `PermissionContext` from the
   `O365_PRINCIPAL` environment variable — Entra-keyed and device-code only).
2. An out-of-process connect flow for CLI agents: print / open the authorize URL and learn
   completion by polling `/api/v1/connections` or from the `connection.*` bus.
3. A remote `CredentialStore` backend so out-of-process MCP tools (stdio servers running
   inside Claude Code / Codex) resolve connections through the server instead of reaching
   the Identity Vault directly. Device-code where the provider supports it.

S-1 keeps the seams open: `channel="cli"` is a valid `Principal.channel`, `start_connect` is
channel-agnostic, `CredentialStore` is a Protocol. S-4 depends on FEAT-773 being merged.
