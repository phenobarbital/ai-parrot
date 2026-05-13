---
id: F020
query_id: Q020
type: git_log
intent: Recent commits in parrot/tools/file/ to confirm the FileManager surface hasn't recently changed.
executed_at: 2026-05-12T00:00:00Z
duration_ms: 0
parent_id: null
depth: 0
---

# F020 — FileManager surface was migrated April 2026; stable since 2026-05-05

## Summary

The `parrot.interfaces.file` + `parrot.tools.filemanager` surfaces were
established in April 2026 via the `fileinterface-migration` series:
- 2026-04-25 — TASK-851 "Replace parrot.interfaces.file with re-export shim"
- 2026-04-25 — TASK-852 "Adapt FileManagerTool._create_file and delegate FileManagerFactory"
- 2026-04-27 — TASK-869 "Implement FileManagerToolkit Core Class"
- 2026-05-05 — bump navigator-api version

The most recent change was a version bump of the upstream navigator-api package
(2026-05-05). No semantic API changes since then. The shape is stable and the
brainstorm can safely assume `FileManagerInterface`, `FileManagerFactory`,
`S3FileManager` API will not move during the FEAT-162 implementation window.

## Citations

- path: `packages/ai-parrot/src/parrot/interfaces/file/` + `packages/ai-parrot/src/parrot/tools/filemanager.py`
  lines: n/a
  symbol: git log
  excerpt: |
    15e3cc98 2026-05-05 bump version of navigator-api
    6d944ca9 2026-04-27 dev loop spec
    8427f25d 2026-04-27 feat(filemanagertool-migration-toolkit): TASK-869 — Implement FileManagerToolkit Core Class
    5cc2da3d 2026-04-25 feat(fileinterface-migration): TASK-852 — Adapt FileManagerTool._create_file and delegate FileManagerFactory
    1ca4f2a1 2026-04-25 feat(fileinterface-migration): TASK-851 — Replace parrot.interfaces.file with re-export shim
    46723dfd 2026-03-23 use of OUTPUT_DIR
    7faf95de 2026-03-23 more changes
    6b111ea3 2026-03-23 fixes on monorepo re-organization

## Notes

- Stable. No drift concern for the FileManager layer.
