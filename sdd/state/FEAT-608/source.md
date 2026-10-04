---
kind: inline
jira_key: null
fetched_at: 2026-09-25T22:51:43Z
summary_oneline: Google Drive FileManager (FileManagerInterface over Drive v3) modeled on FEAT-603 SharePoint/OneDrive managers, wired into FileManagerToolkit
---

# Source (inline)

> google-drive-interface -- use the FEAT-603 feat-FEAT-603-sharepoint-filemanager
> as example for a Google Drive File Manager interface and integration with toolkit

## Interpretation notes (not part of the source)

- `google-drive-interface` is the requested feature slug / name.
- "FEAT-603 feat-FEAT-603-sharepoint-filemanager" points at both the spec
  `sdd/specs/sharepoint-filemanager.spec.md` and the worktree
  `.claude/worktrees/feat-FEAT-603-sharepoint-filemanager`, i.e. the
  reference implementation to mirror.
- "integration with toolkit" reads as: registration in `FileManagerFactory` /
  `FileManagerTool` / `FileManagerToolkit` (`manager_type="gdrive"`), plus
  the agent-facing Google Workspace tools (`parrot_tools.google`) using the
  manager — the same two integration seams FEAT-603 covers for O365.
