---
id: F048
query_id: F043-f1
type: grep
intent: "Depth-2: FEAT-696 LocalJiraTokenStore file location, permissions and FileTokenCredentialResolver.allowed_channels"
executed_at: 2026-10-30T15:29:44Z
duration_ms: 0
parent_id: F043
depth: 2
---

# F048 — LocalJiraTokenStore: ~/.parrot/jira/settings.local.json, 0600 + lock file; FileTokenCredentialResolver allows channels {cli, local}

## Summary

`parrot_tools/jira_local_auth.py` stores the CLI 3LO token in `~/.parrot/jira/settings.local.json` (`DEFAULT_SETTINGS_PATH`, expanded at :41), written atomically with `os.fchmod(fd, 0o600)` / `os.chmod(path, 0o600)` under a 0600 lock file; `LocalSettings.sites[key]` holds one token per Atlassian site. `FileTokenCredentialResolver(CredentialResolver)` (:155) takes `allowed_channels` defaulting to `{"cli", "local"}` (:172). This is the local-file precedent for a CLI login/token file (U1/U2 option b).

## Citations

- path: `packages/ai-parrot-tools/src/parrot_tools/jira_local_auth.py`
  lines: 24-41
  symbol: `DEFAULT_SETTINGS_PATH / LocalSettings / LocalJiraTokenStore`
  excerpt: |
    DEFAULT_SETTINGS_PATH = Path("~/.parrot/jira/settings.local.json")
    class LocalSettings(BaseModel):
    class LocalJiraTokenStore:
        self.path = Path(self.path).expanduser()
- path: `packages/ai-parrot-tools/src/parrot_tools/jira_local_auth.py`
  lines: 52, 100-106, 121
  symbol: `LocalJiraTokenStore (atomic 0600 write)`
  excerpt: |
    fd = os.open(self.lock_path, os.O_RDWR | os.O_CREAT, 0o600)
    os.fchmod(fd, 0o600) ... os.chmod(self.path, 0o600)
    settings.sites[key] = token.model_dump(mode="json")
- path: `packages/ai-parrot-tools/src/parrot_tools/jira_local_auth.py`
  lines: 155-172
  symbol: `FileTokenCredentialResolver`
  excerpt: |
    class FileTokenCredentialResolver(CredentialResolver):
        allowed_channels: Optional[set[str]] = None,
        self.allowed_channels = allowed_channels or {"cli", "local"}

## Notes

Verified inline by the parent (grep outline). Lives in ai-parrot-tools, so a generic S-4 login file would need a core home (e.g. under `~/.parrot/`) rather than this Jira-specific module.
