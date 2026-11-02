---
id: F031
query_id: Q045
type: read
intent: "expose-toolkits-as-local-mcp spec design"
executed_at: 2026-10-30T15:23:31Z
duration_ms: 0
parent_id: null
depth: 0
merged_from: [FC-031]
---

# F031 — FEAT-485 spec: stdio servers never import ai-parrot-server/aiohttp/navconfig; secrets via env; HITL is the host's prompt

## Summary

The FEAT-485 spec (approved) fixes constraints S-4 inherits: one process per toolkit; `parrot mcp-local <name>`; config `.parrot/mcp-toolkits.yaml`; 'Lean startup: … never imports ai-parrot-server/aiohttp/navconfig; stdout stays a pure JSON-RPC channel'; `ToolkitSection.env` 'written into the installer entry'; 'Any parrot-side HITL machinery for confirming tools' is a non-goal (host permission prompt is the human gate). Installer assets build `toolkit_mcp_json_entry(root, name, section)`.

## Citations

- path: `sdd/specs/expose-toolkits-as-local-mcp.spec.md`
  lines: 41-55, 57-70, 160-179, 219-220
  symbol: `Goals / Non-Goals / Data Models / assets`
  excerpt: |
    - Lean startup: works with a bare `ai-parrot` install ...; never imports
      ai-parrot-server/aiohttp/navconfig; stdout stays a pure JSON-RPC channel.
    - Any parrot-side HITL machinery for confirming tools — Claude Code's / Codex's own permission prompt is the human gate.
        env: dict[str, str] = Field(default_factory=dict)  # written into the installer entry
    def toolkit_mcp_json_entry(root: Path, name: str, section: ToolkitSection) -> dict:

## Notes

Hard constraint for S-4's remote CredentialStore: it must be aiohttp-client-only (parrot core), no server imports; identity must arrive via env/file, and any connect prompt must go to stderr or be returned as an MCP tool result (AuthRequiredPayload) for the host to show.
