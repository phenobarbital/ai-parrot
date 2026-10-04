---
id: F016
query_id: Q022
type: read
intent: FEAT-603 spec §3 modules, §5 acceptance criteria and task decomposition — the shape to mirror (Q019 + Q022)
executed_at: 2026-09-25T22:55:00Z
duration_ms: 900
parent_id: null
depth: 0
---

# F016 — FEAT-603 = 11 modules (M0 harness … M10 live gate), 24 ACs, 21 tasks; the Drive feature maps 1:1 minus the two Microsoft-only modules

## Summary

`sdd/specs/sharepoint-filemanager.spec.md` breaks into M0 Graph test
harness, M1 base manager, M2 client port, M3/M4 thin managers, M5
registration, M6 agent ops (`find`/`batch_*`), M7/M8 O365 tool refactors,
M9 packaging+docs, M10 live suite; ACs cover interface parity (AC1),
subclass minimality (AC2), one token acquisition per manager (AC3),
threshold-routed uploads (AC5), streaming downloads (AC6), sharing-link
semantics (AC7), batch semantics (AC8), pagination to exhaustion (AC20),
outbound-URL validation (AC21), 413 serving guard (AC22), lazy shim /
no SDK leak (AC10), factory keys (AC11), toolkit ops (AC12), packaging
(AC14), TID251 lint (AC15), docs (AC16), test command (AC17), live gate
(AC18), signature snapshot (AC19). Task files TASK-3748..3768 follow that
module order. Drive has no "client port" (M2) and no pre-existing tools to
refactor (M7/M8) — but M6 is already done by FEAT-603.

## Citations

- path: `sdd/specs/sharepoint-filemanager.spec.md`
  lines: 374-389
  symbol: "Delegation-eligible modules" table
  excerpt: |
    M0 harness | M1 GraphDriveFileManager | M2 _resolve_user_drive port | M3 SharePoint | M4 OneDrive |
    M5 Registration | M6 find/batch ops | M7/M8 O365 tool refactors | M9 Packaging+docs | M10 Live gate

- path: `sdd/specs/sharepoint-filemanager.spec.md`
  lines: 941-964
  symbol: "## 5. Acceptance Criteria"
  excerpt: |
    AC1 interface parity (inspect.signature) · AC2 subclass overrides only 4 names · AC3 one token acquisition
    AC5 SMALL_FILE_THRESHOLD routing · AC6 streaming download · AC7 get_file_url wraps create_sharing_link
    AC8 batch never raises per item · AC10 no SDK leak on import · AC11 factory ValueError lists all keys
    AC12 toolkit find/batch ops · AC14 extra + `all` · AC15 TID251 · AC17 test command · AC18 live gate · AC19 signature snapshot

- path: `sdd/specs/sharepoint-filemanager.spec.md`
  lines: 968-1000
  symbol: "## 6. Codebase Contract / Verified Imports"
  excerpt: |
    from navigator.utils.file import FileManagerInterface, FileMetadata, FileManagerFactory, FileServingExtension
    from parrot.tools.filemanager import FileManagerFactory, FileManagerTool, FileManagerToolkit

- path: `sdd/tasks/active/`
  symbol: TASK-3748..TASK-3768
  excerpt: |
    3748 graph-test-harness · 3749 core-models-paths · 3750 lifecycle-retry-urls · 3751 read-ops · 3752 write-ops
    3753 copy-links-folders · 3754 batch-serving · 3755 onedrive-user-drive · 3756/3757 managers · 3758 registration
    3759/3760 toolkit+tool find/batch · 3761-3764 O365 tools · 3765 msgraph-extra · 3766 docs · 3767 live-suite · 3768 feature-guards
