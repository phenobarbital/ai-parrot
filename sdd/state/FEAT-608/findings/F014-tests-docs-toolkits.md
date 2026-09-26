---
id: F014
query_id: Q018
type: glob
intent: Existing Google tool tests/docs, FEAT-603 test harness and docs, Google toolkits (Q018 + Q023)
executed_at: 2026-09-25T22:54:30Z
duration_ms: 600
parent_id: null
depth: 0
---

# F014 — FEAT-603 leaves a fake-client harness + live suite + doc page to mirror; Google tools have two toolkits and two test files

## Summary

FEAT-603 worktree tests: `packages/ai-parrot/tests/interfaces/_graph_fakes.py`,
`test_graph_fakes.py`, `test_graph_filemanager.py`, `test_graph_filemanager_live.py`,
`test_sharepoint_filemanager.py`, `test_onedrive_filemanager.py`,
`test_onedrive_client_user_drive.py`, plus
`packages/ai-parrot/tests/tools/test_filemanager_batch_ops.py`; docs at
`docs/interfaces/graph-filemanager.md` and an updated
`docs/integrations/office365-oauth2.md`. Google side today:
`packages/ai-parrot-tools/tests/google/{test_calendar.py,test_places.py}`,
toolkits `GoogleCalendarToolkit(AbstractToolkit)` (`calendar.py:74`) and
`LyriaToolkit` (`lyria.py:35`); `parrot_tools/google/__init__.py` exports
tools + `GoogleBaseTool` + `LyriaToolkit` (no Drive names). No
`docs/integrations/*google*` page exists.

## Citations

- path: `.claude/worktrees/feat-FEAT-603-sharepoint-filemanager/packages/ai-parrot/tests/interfaces/_graph_fakes.py`
  symbol: `FakeGraphClient / FakeAiohttpSession / make_sharepoint_client`
  excerpt: |
    (harness listed in spec M0; file present in worktree)

- path: `.claude/worktrees/feat-FEAT-603-sharepoint-filemanager/packages/ai-parrot/tests/interfaces/test_graph_filemanager_live.py`
  symbol: live suite
  excerpt: |
    @pytest.mark.live suite gated on env vars (spec M10 / AC18)

- path: `.claude/worktrees/feat-FEAT-603-sharepoint-filemanager/packages/ai-parrot/tests/tools/test_filemanager_batch_ops.py`
  symbol: toolkit batch tests
  excerpt: |
    (fs_find_files / fs_batch_upload / fs_batch_download coverage, AC12)

- path: `.claude/worktrees/feat-FEAT-603-sharepoint-filemanager/docs/interfaces/graph-filemanager.md`
  symbol: doc page
  excerpt: |
    (AC16 / AC22 — manager docs incl. serving_max_bytes)

- path: `packages/ai-parrot-tools/src/parrot_tools/google/calendar.py`
  lines: 74
  symbol: `GoogleCalendarToolkit`
  excerpt: |
    class GoogleCalendarToolkit(AbstractToolkit):

- path: `packages/ai-parrot-tools/src/parrot_tools/google/__init__.py`
  lines: 1-24
  symbol: `__all__`
  excerpt: |
    __all__ = ("GoogleSearchTool", "GoogleSiteSearchTool", "GoogleLocationTool", "GoogleRoutesTool",
               "GoogleReviewsTool", "GoogleTrafficTool", "GoogleBusinessTool", "GoogleBaseTool", "LyriaToolkit")

- path: `packages/ai-parrot-tools/tests/google/test_calendar.py`
  symbol: tests
  excerpt: |
    (existing Google tool test layout: packages/ai-parrot-tools/tests/google/)
