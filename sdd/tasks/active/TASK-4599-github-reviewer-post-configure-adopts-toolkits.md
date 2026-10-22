# TASK-4599: GitHubReviewer.post_configure adopts its toolkits

**Feature**: FEAT-721 — Double-`configure()` Is Not a Crash
**Spec**: `sdd/specs/double-configure-agents.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-4596
**Assigned-to**: unassigned

---

## Context

Spec §3 Module 3 — the *silent* variant that `ParrotReviewer` inherits.
`GitHubReviewer.post_configure()` (`github_reviewer.py:956`) builds a new authenticated
`GitToolkit` (`:989`), a new `RepoWikiCache` (`:990`) and a new `JiraToolkit` (`:992`)
on every call. Both toolkits are unprefixed, so a repeat registration used to
warn-and-skip, leaving `self.git_toolkit`/`self.jira_toolkit` pointing at unregistered
clients. After TASK-4596, `register_toolkit()` returns the already-registered tools on
a repeat — so `_attach_toolkit()`'s `self.tools.extend(tools)` (`:1279`) would now append
duplicates. This task adopts the registered toolkits, guards the wiki cache, and
de-duplicates `self.tools`.

---

## Scope

- Adopt `GitToolkit` / `JiraToolkit` via `self.tool_manager.find_registered_toolkit()`;
  call `_build_git_toolkit()` / `_build_jira_toolkit()` only when it returns `None`.
- Build `self._wiki_cache` only when it is still `None`.
- Make `_attach_toolkit()` extend `self.tools` only with names not already present.
- Update both docstrings.
- Append a re-entrancy test class to `packages/ai-parrot/tests/bots/test_github_reviewer.py`.

**NOT in scope**: `_attach_webhook_listener()` (already idempotent, `:1246-1247`);
`_schedule_wiki_warmup()` (already guarded by `_wiki_warmup_task`); the wiki toolkits
(guarded by `_wiki_toolkits_attached`, `:1196`); `_ensure_webhook_subscription()`.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/bots/github_reviewer.py` | MODIFY | adopt-or-build, wiki-cache guard, de-duplicated `self.tools` |
| `packages/ai-parrot/tests/bots/test_github_reviewer.py` | MODIFY | append `TestPostConfigureReentrant` |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
# already imported in github_reviewer.py — do not re-import
from parrot_tools.gittoolkit import GitToolkit       # verified: bots/github_reviewer.py:79-82
from parrot_tools.jiratoolkit import JiraToolkit     # verified: bots/github_reviewer.py:86
# for the test
from parrot.bots.github_reviewer import GitHubReviewer  # verified: bots/github_reviewer.py:495
from parrot.tools.manager import ToolManager            # verified: tools/manager.py:289
```

### Existing Signatures to Use
```python
# packages/ai-parrot/src/parrot/bots/github_reviewer.py
class GitHubReviewer(Agent):                                          # line 495
    self.git_toolkit: Optional[GitToolkit] = None                     # line 828
    self.jira_toolkit: Optional[JiraToolkit] = None                   # line 829
    self._wiki_cache: Optional[RepoWikiCache] = None                  # line 830
    self._wiki_warmup_task: Optional[asyncio.Task[None]] = None       # line 831
    @property
    def management_chat_is_fallback(self) -> bool: ...                # line 938
    async def post_configure(self) -> None:                           # line 956
        # 989 self.git_toolkit = self._build_git_toolkit()
        # 990 self._wiki_cache = self._build_wiki_cache()
        # 991 await self._schedule_wiki_warmup()          (no-op when _wiki_warmup_task is set)
        # 992 self.jira_toolkit = self._build_jira_toolkit()
        # 994-995 self._attach_toolkit(self.git_toolkit, "Git") / (self.jira_toolkit, "Jira")
        # 997-1005 sync_tools(self._llm); 1007 _attach_webhook_listener(); 1008 _ensure_webhook_subscription()
    def _attach_toolkit(self, toolkit: Any, name: str) -> None:       # line 1261
        # 1266 tools = self.tool_manager.register_toolkit(toolkit)  (in try/except Exception → log + return)
        # 1275 if not tools: return
        # 1277-1278 if not hasattr(self, "tools") or self.tools is None: self.tools = []
        # 1279 self.tools.extend(tools)
    def _build_git_toolkit(self) -> Optional[GitToolkit]: ...         # line 1281
    def _build_jira_toolkit(self) -> Optional[JiraToolkit]: ...       # line 1355
    async def _ensure_webhook_subscription(self) -> None: ...         # line 1430

# packages/ai-parrot/src/parrot/tools/manager.py — created by TASK-4596
def find_registered_toolkit(self, toolkit_cls: type, *, tool_prefix: Optional[str] = None) -> Optional[AbstractToolkit]
# keep-first: register_toolkit() of an already-registered toolkit RETURNS its registered tools (non-empty)
```

### Does NOT Exist
- ~~`GitToolkit.tool_prefix` / `JiraToolkit.tool_prefix` with a value~~ — both `None`.
- ~~`GitHubReviewer._git_toolkit_attached`~~ / ~~`_jira_toolkit_attached`~~ — no such flags; adopt via the manager instead of adding them.
- ~~`ParrotReviewer` in the shipped packages~~ — it lives in the gitignored `agents/` tree and inherits this method unchanged; do not look for it.

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {"path": "packages/ai-parrot/src/parrot/bots/github_reviewer.py", "action": "MODIFY"},
    {"path": "packages/ai-parrot/tests/bots/test_github_reviewer.py", "action": "MODIFY"}
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot/src/parrot/bots/github_reviewer.py#GitHubReviewer.post_configure",
    "sym:packages/ai-parrot/src/parrot/bots/github_reviewer.py#GitHubReviewer._attach_toolkit",
    "sym:packages/ai-parrot/src/parrot/bots/github_reviewer.py#GitHubReviewer._build_git_toolkit",
    "sym:packages/ai-parrot/src/parrot/bots/github_reviewer.py#GitHubReviewer._build_jira_toolkit",
    "sym:packages/ai-parrot/src/parrot/bots/github_reviewer.py#GitHubReviewer._build_wiki_cache"
  ]
}
```

---

## Implementation Notes

### Key Constraints
- Explicit `is None` checks, never `a or b`.
- `_build_wiki_cache()` returns `None` when disabled — so on a repeat with the wiki disabled
  it is called again and returns `None` again: harmless. Guard only on `self._wiki_cache is None`.
- De-duplicate by tool **name** (`getattr(t, "name", None)`): `self.tools` holds tool objects
  and names are the registry key.
- Do not touch the `except Exception` in `_attach_toolkit` — a genuine foreign collision must
  still be logged, not raised, in this agent (existing behaviour).

---

## Implementation Blueprint

### Steps (in order)
1. Replace lines 989-992 with adopt-or-build + the wiki-cache guard — *why*: keep-first means the manager's instance wins; a second authenticated client must not be opened.
2. De-duplicate the extend in `_attach_toolkit` — *why*: keep-first now returns live tools on a repeat.
3. Update docstrings; append the test class; run the Validation Commands.

### `packages/ai-parrot/src/parrot/bots/github_reviewer.py` (MODIFY) — `post_configure`
```python
# occurrences: 1 each (verified: grep -cF '        self.git_toolkit = self._build_git_toolkit()' /
#                       '        self._wiki_cache = self._build_wiki_cache()' /
#                       '        self.jira_toolkit = self._build_jira_toolkit()' github_reviewer.py)
# REPLACE lines 989-992 with:
        git_toolkit = self.tool_manager.find_registered_toolkit(GitToolkit)
        if git_toolkit is None:
            git_toolkit = self._build_git_toolkit()
        self.git_toolkit = git_toolkit
        if self._wiki_cache is None:
            self._wiki_cache = self._build_wiki_cache()
        await self._schedule_wiki_warmup()
        jira_toolkit = self.tool_manager.find_registered_toolkit(JiraToolkit)
        if jira_toolkit is None:
            jira_toolkit = self._build_jira_toolkit()
        self.jira_toolkit = jira_toolkit
```
Append to the `post_configure` docstring: *"Re-entrant (FEAT-721): toolkits already served by
the ToolManager are adopted, so a second pass opens no second authenticated client and
``self.git_toolkit``/``self.jira_toolkit`` always name the registered instances."*

### `packages/ai-parrot/src/parrot/bots/github_reviewer.py` (MODIFY) — `_attach_toolkit`
```python
# occurrences: 1 (verified: grep -cF '        self.tools.extend(tools)' github_reviewer.py)
# REPLACE `        self.tools.extend(tools)` (verified: github_reviewer.py:1279) with:
        present = {getattr(tool, "name", None) for tool in self.tools}
        self.tools.extend(tool for tool in tools if getattr(tool, "name", None) not in present)
```
Docstring becomes: `"""Register ``toolkit`` and extend ``self.tools`` with exports not already present."""`

### `packages/ai-parrot/tests/bots/test_github_reviewer.py` (MODIFY — append at end of file)
```python
class TestPostConfigureReentrant:
    """FEAT-721 — a second post_configure() adopts instead of rebuilding."""

    async def test_github_reviewer_post_configure_twice_adopts(self, monkeypatch: pytest.MonkeyPatch) -> None:
        reviewer = GitHubReviewer.__new__(GitHubReviewer)
        # FILL IN: stub exactly what post_configure() reads (lines 956-1008):
        #   logger, public_channel_id, management_chat_id (management_chat_is_fallback is a property
        #   over them, :938), tool_manager = ToolManager(include_search_tool=False), tools = [],
        #   _llm = None, _wiki_cache = None, _wiki_warmup_task = None, app = None, name.
        # FILL IN: build ONE toolkit object per builder that `find_registered_toolkit` can match by
        #   EXACT class — e.g. GitToolkit.__new__(GitToolkit) / JiraToolkit.__new__(JiraToolkit) only if
        #   register_toolkit() can generate their tools without __init__ state; otherwise construct them
        #   offline (read their __init__ first — `packages/ai-parrot-tools/src/parrot_tools/jiratoolkit.py:874`). Count builder calls with a
        #   MagicMock(side_effect=[...]) patched over _build_git_toolkit / _build_jira_toolkit.
        # FILL IN: patch _build_wiki_cache → None, _attach_webhook_listener / _ensure_webhook_subscription → AsyncMock().
        await reviewer.post_configure()
        await reviewer.post_configure()
        # FILL IN: assert each builder called once; reviewer.git_toolkit is
        #   reviewer.tool_manager.find_registered_toolkit(GitToolkit); no duplicate names in reviewer.tools
```
**Why**: the file already imports `GitHubReviewer`, `MagicMock`, `pytest` and uses
`asyncio_mode = "auto"` (`packages/ai-parrot/pyproject.toml:1048`) — check the file header and add
only the missing imports (`ToolManager`, `GitToolkit`, `JiraToolkit`). If a real toolkit cannot be built
offline, it is acceptable to register a minimal subclass-free stand-in ONLY if `find_registered_toolkit`
is patched accordingly — say so in the Completion Note.

### FILL IN checklist
- [ ] reviewer stub attributes for `post_configure()`
- [ ] offline toolkit construction strategy (record it in the Completion Note)
- [ ] builder-call and duplicate-name assertions

---

## Acceptance Criteria

- [ ] Two `post_configure()` passes raise nothing; `_build_git_toolkit` / `_build_jira_toolkit` are each called once.
- [ ] `reviewer.git_toolkit` / `reviewer.jira_toolkit` are the instances the ToolManager serves.
- [ ] `reviewer.tools` contains no duplicate tool names after two passes.
- [ ] The existing `test_github_reviewer.py` suite stays green.
- [ ] `ruff check packages/ai-parrot/src/parrot/bots/github_reviewer.py packages/ai-parrot/tests/bots/test_github_reviewer.py` clean.

---

## Validation Commands

- `pytest packages/ai-parrot/tests/bots/test_github_reviewer.py -q`

---

## Test Specification

One appended test class (above).

---

## Agent Instructions

1. **Work in the feature worktree** — never on `dev`
   (`python -m scripts.sdd.ensure_worktree --slug double-configure-agents --feature-id FEAT-721`).
2. **Read the spec** (§2 Overview, §3 M3, §7 Known Risks).
3. **Check dependencies** — TASK-4596 must be `"done"` in `sdd/tasks/index/double-configure-agents.json`.
4. **Verify the Codebase Contract** — re-run every `grep -cF` above; 0 means drift: stop and report.
5. **Update status** → `"in-progress"`; commit only the index file.
6. **Implement** from the blueprint; complete every `# FILL IN:`.
7. **Verify** — Validation Commands with `PYTHONPATH=packages/ai-parrot/src:packages/ai-parrot-tools/src`.
8. **Commit the code** — only the files this task lists.
9. **Close** with `scripts/sdd/close_task.sh TASK-4599 double-configure-agents verified`.
10. **Fill in the Completion Note**, commit the SDD state.

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**: <session or agent ID>
**Date**: YYYY-MM-DD
**Notes**:

**Deviations from spec**: none
