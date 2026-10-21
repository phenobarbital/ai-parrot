# TASK-4570: FirefliesInsightsAgent core: registration, configure, toolkits, MCP fetch

**Feature**: FEAT-715 — FirefliesInsightsAgent
**Spec**: `sdd/specs/fireflies-insights-agent.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-4569
**Assigned-to**: unassigned

---

## Context

Spec §3 **Module 5**, first half: the agent class and everything it needs *before* a
meeting is processed — registration, inbox-dir resolution, file-only skills
(design-research **S6**), `WorkingMemoryToolkit` + `JiraToolkit` wiring, and the
Fireflies MCP fetch helpers (**S2**: the agent owns its own fetch).

**Two corrections to the spec §3 M5 skeleton, made at task time with evidence:**

1. **Skills activation.** The skeleton set `enable_skill_registry=False` and assumed the
   file registry still loads. It does not: `_configure_skill_registry()` returns at
   `packages/ai-parrot/src/parrot/skills/mixin.py:315` when the flag is False, so `_configure_skill_file_registry()` (called at
   `:344`) is never reached — and nothing in core calls the mixin automatically. **This
   task calls `await self._configure_skill_file_registry()` explicitly in `configure()`**,
   keeping `enable_skill_registry = False` so no DB registry is ever built (AC25).
2. **`skill_paths` must be absolute.** The skeleton's `Path("agents/fireflies_insights/skills/")`
   resolves against the process CWD. Use `AGENTS_DIR / "fireflies_insights" / "skills"`
   (`parrot/conf.py:181`) so discovery works from any launch directory.

---

## Scope

- Append `FirefliesInsightsAgent(SkillRegistryMixin, Agent)` to `packages/ai-parrot/src/parrot/bots/fireflies_insights.py`, decorated
  `@register_agent(name="fireflies_insights")` (**keyword form** — positional raises `TypeError`).
- `__init__`, `configure()`, `post_configure()`, `_build_jira_toolkit()`,
  `_ensure_fireflies_mcp()`, `_call_fireflies_tool()`, `_fetch_listing()`,
  `_fetch_transcript()`, `_fetch_summary()` exactly as the blueprint fixes.
- Tests for configure (AC15, AC25), listing pagination, and summary failure → `None`.

**NOT in scope**: writing to the inbox, `MeetingRegistry` gating, `sync_meetings`
(TASK-4571); insights / Telegram (TASK-4572); approvals / tickets (TASK-4574);
the skills/templates directories themselves (TASK-4573).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/bots/fireflies_insights.py` | MODIFY | Add `FirefliesInsightsAgent`: registration, configure, toolkits, Fireflies MCP fetch |
| `packages/ai-parrot/tests/bots/test_fireflies_insights.py` | MODIFY | Configure / skills / fetch tests |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from parrot.agents.conf import FIREFLIES_REGISTRY_DIR, FIREFLIES_SYNC_OVERLAP_DAYS  # verified: agents/conf.py:174, :182
from parrot.agents.meeting_registry import MeetingRegistry                         # verified: packages/ai-parrot/src/parrot/agents/meeting_registry.py:167
from parrot.agents.obsidian import FirefliesObsidianAgent                          # verified: packages/ai-parrot/src/parrot/agents/obsidian.py:163 (reuse its staticmethod only)
from parrot.bots.agent import Agent                                                # verified: bots/agent.py:1562
from parrot.conf import AGENTS_DIR                                                 # verified: parrot/conf.py:181
from parrot.knowledge.wiki.project import find_project_root, load_effective_config # verified: packages/ai-parrot/src/parrot/knowledge/wiki/project.py:1034, :1259
from parrot.registry import register_agent                                         # verified: registry/__init__.py:12 (ASSIGNMENT, not a def)
from parrot.skills.mixin import SkillRegistryMixin                                 # verified: packages/ai-parrot/src/parrot/skills/mixin.py:47
from parrot.tools.working_memory import WorkingMemoryToolkit                       # verified: tools/working_memory/__init__.py:3
from parrot_tools.jiratoolkit import JiraToolkit                                   # verified: packages/ai-parrot-tools/src/parrot_tools/jiratoolkit.py:772
```

### Existing Signatures to Use
```python
# bots/agent.py:179 / bots/abstract.py:1767
async def configure(self, app=None) -> None: ...
async def post_configure(self) -> None: ...
# parrot/mcp/integration.py:1448 (MCPEnabledMixin, available on Agent)
async def add_fireflies_mcp_server(self, api_key: Optional[str] = None, **kwargs) -> List[str]: ...
# packages/ai-parrot/src/parrot/agents/obsidian.py:320-343  _ensure_fireflies_mcp — token: arg → config.get("FIREFLIES_API_KEY") → ValueError
# packages/ai-parrot/src/parrot/agents/obsidian.py:1243-1268 _call_fireflies_tool — full_name = f"mcp_fireflies_{tool_name}"; tool = self.tool_manager.get_tool(full_name); await tool.execute(**args)
# packages/ai-parrot/src/parrot/agents/obsidian.py:1158 @staticmethod _parse_fireflies_response(response_text: str) -> List[Dict[str, Any]]
#   listing keys: id, title, date, participants, duration
# packages/ai-parrot/src/parrot/agents/obsidian.py:~462-479 pagination: "fireflies_get_transcripts" {**filter_args, "limit": page_limit, "skip": skip};
#   stop when not tool_result or not tool_result.success, or len(page) < page_limit; ≤50 per call;
#   filter_args["fromDate"] = suggested   (obsidian.py:~451)
# packages/ai-parrot/src/parrot/agents/obsidian.py:645-668 transcript: "fireflies_get_transcript" {"transcriptId": tid}; summary: "fireflies_get_summary"
#   text = result.result if hasattr(result, "result") else str(result)
# packages/ai-parrot/src/parrot/agents/meeting_registry.py:184
class MeetingRegistry:
    def __init__(self, registry_dir: Path, *, manager: SourceCollectionManager | None = None) -> None: ...
# packages/ai-parrot/src/parrot/skills/mixin.py:384  async def _configure_skill_file_registry(self) -> None   — idempotent; registers SkillFileToolkit
#            when skill_paths is non-empty (:465-517); a missing skills dir yields 0 skills (parsers.py:203)
# packages/ai-parrot/src/parrot/skills/mixin.py:313  async def _configure_skill_registry(self) -> None        — returns at :315 when enable_skill_registry is False
# tools/working_memory/tool.py:60  WorkingMemoryToolkit.__init__(self, session_id: Optional[str] = None, ...)
# packages/ai-parrot/src/parrot/bots/github_reviewer.py:1287 GitHubReviewer._build_jira_toolkit(self) -> Optional[JiraToolkit]   — the auth pattern to mirror
# packages/ai-parrot/src/parrot/bots/github_reviewer.py:1198 self.tool_manager.register_toolkit(toolkit)                         — how toolkits are attached
# packages/ai-parrot/src/parrot/knowledge/wiki/project.py:1259 load_effective_config(root: Path, env: str | None = None) -> WikiEffectiveConfig  (.config → WikiProjectConfig)
# packages/ai-parrot/src/parrot/knowledge/wiki/project.py:770  WikiProjectConfig.inbox_path(self, root: Path) -> Path
```

### Does NOT Exist
- ~~`FirefliesWikiAgent`~~ / ~~`parrot/agents/fireflies_wiki.py`~~ — not on `dev` (FEAT-481's unmerged branch only).
- ~~`FirefliesObsidianAgent` as a base class~~ — it is a `BasicAgent` reference; only its
  `@staticmethod _parse_fireflies_response` is reused.
- ~~`sync_fireflies_transcripts()` returning transcripts~~ — it returns a report dict
  (`report["synced"]`, `report["errors"]`, `report["from_date"]`); the agent owns its fetch (S2).
- ~~`SkillRegistryMixin` activating itself in `configure()`~~ — **nothing in core calls
  it automatically** (only `bots/mixins/narrative.py:127` calls `_configure_skill_registry`).
  The agent must call `_configure_skill_file_registry()` itself.
- ~~`ChatId` importable from `github_reviewer`~~ — local alias; this module defines its own (TASK-4569).

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {
      "path": "packages/ai-parrot/src/parrot/bots/fireflies_insights.py",
      "action": "MODIFY"
    },
    {
      "path": "packages/ai-parrot/tests/bots/test_fireflies_insights.py",
      "action": "MODIFY"
    }
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot/src/parrot/skills/mixin.py#SkillRegistryMixin",
    "sym:packages/ai-parrot/src/parrot/skills/mixin.py#SkillRegistryMixin._configure_skill_file_registry",
    "sym:packages/ai-parrot/src/parrot/agents/meeting_registry.py#MeetingRegistry",
    "sym:packages/ai-parrot/src/parrot/agents/obsidian.py#FirefliesObsidianAgent._parse_fireflies_response",
    "sym:packages/ai-parrot-tools/src/parrot_tools/jiratoolkit.py#JiraToolkit",
    "sym:packages/ai-parrot/src/parrot/knowledge/wiki/project.py#load_effective_config",
    "sym:packages/ai-parrot/src/parrot/knowledge/wiki/project.py#find_project_root"
  ]
}
```

---

## Implementation Notes

### Key Constraints
- `_fetch_summary` never raises: a missing summary is `None` (the insight path still runs
  on the transcript alone).
- Jira auth mirrors `GitHubReviewer._build_jira_toolkit` (packages/ai-parrot/src/parrot/bots/github_reviewer.py:1287): basic-auth
  fallback, never per-user OAuth (there is no caller). Pass
  `templates_dir=self.jira_templates_dir` and `default_project=self.jira_project`.
  A construction failure logs ERROR and returns `None` — the agent still runs without Jira.
- Use `X | None` annotations (repo ruff config rejects `Optional[...]`).

---

## Implementation Blueprint

### Steps (in order)
1. Add the imports at the top of `packages/ai-parrot/src/parrot/bots/fireflies_insights.py` (below the pydantic import) — *why*: Verified Imports only.
2. Append the class — *why*: fixes the names TASK-4571..4574 extend.
3. Fill the FILL INs — *why*: they carry the only judgement in this task.
4. Extend `packages/ai-parrot/tests/bots/test_fireflies_insights.py`.

### `packages/ai-parrot/src/parrot/bots/fireflies_insights.py` (MODIFY — append after `class InsightRunReport`)
```python
@register_agent(name="fireflies_insights")
class FirefliesInsightsAgent(SkillRegistryMixin, Agent):
    """Fireflies meetings → wiki inbox + insights → Telegram → Jira (FEAT-715)."""

    #: S6 — never build the DB-backed registry at AGENTS_DIR/{agent_id}/skills.
    enable_skill_registry: bool = False
    #: Absolute, so discovery does not depend on the launch directory.
    skill_paths: list[Path] = [AGENTS_DIR / "fireflies_insights" / "skills"]

    def __init__(
        self,
        name: str = "FirefliesInsights",
        *,
        fireflies_token: str | None = None,
        wiki_root: str | Path | None = None,
        public_channel_id: ChatId | None = None,
        jira_templates_dir: str | Path | None = None,
        jira_project: str | None = None,
        **kwargs: Any,
    ) -> None:
        """Bind configuration; nothing touches the network until configure()."""
        super().__init__(name=name, **kwargs)
        self.fireflies_token = fireflies_token
        self.wiki_root = Path(wiki_root).expanduser() if wiki_root else None
        self.public_channel_id = public_channel_id
        self.jira_templates_dir = (
            Path(jira_templates_dir).expanduser() if jira_templates_dir else AGENTS_DIR / "fireflies_insights" / "templates"
        )
        self.jira_project = jira_project
        self.inbox_dir: Path | None = None
        self.registry = MeetingRegistry(Path(FIREFLIES_REGISTRY_DIR).expanduser())
        self.working_memory: WorkingMemoryToolkit | None = None
        self.jira_toolkit: JiraToolkit | None = None
        self._wrapper: Any = None
        self._mcp_fireflies_initialized = False

    async def configure(self, app=None) -> None:
        """Resolve the inbox dir and load file-only skills (S6)."""
        await super().configure(app)
        await self._configure_skill_file_registry()
        root = self.wiki_root or find_project_root()
        # FILL IN: root is None -> raise ValueError("FirefliesInsightsAgent needs wiki_root= or a configured wiki project");
        #   config = load_effective_config(root).config; self.inbox_dir = config.inbox_path(root);
        #   create it with mkdir(parents=True, exist_ok=True); self.wiki_root = root
        #   — bounded by spec C6 (the drop target IS the wiki's configured inbox)

    async def post_configure(self) -> None:
        """Wire WorkingMemoryToolkit and JiraToolkit once self.app exists."""
        await super().post_configure()
        self.working_memory = WorkingMemoryToolkit(session_id=f"{self.name}-meetings")
        self.jira_toolkit = self._build_jira_toolkit()
        for toolkit in (self.working_memory, self.jira_toolkit):
            if toolkit is not None:
                self.tool_manager.register_toolkit(toolkit)

    def _build_jira_toolkit(self) -> JiraToolkit | None:
        """Build JiraToolkit like GitHubReviewer does; None (logged) on failure."""
        # FILL IN: mirror packages/ai-parrot/src/parrot/bots/github_reviewer.py:1287-1320 auth selection; pass templates_dir / default_project
        raise NotImplementedError

    async def _ensure_fireflies_mcp(self) -> None:
        """Lazy MCP init; api_key → FIREFLIES_API_KEY → ValueError (copy packages/ai-parrot/src/parrot/agents/obsidian.py:320-343)."""
        # FILL IN: copy the obsidian logic, setting self._mcp_fireflies_initialized
        raise NotImplementedError

    async def _call_fireflies_tool(self, tool_name: str, args: dict[str, Any]) -> Any:
        """Call mcp_fireflies_<tool_name> through the tool manager (packages/ai-parrot/src/parrot/agents/obsidian.py:1243)."""
        tool = self.tool_manager.get_tool(f"mcp_fireflies_{tool_name}")
        if not tool:
            raise ValueError(f"Tool not found: mcp_fireflies_{tool_name}")
        return await tool.execute(**args)

    async def _fetch_listing(self, limit: int, from_date: str | None = None) -> list[dict[str, Any]]:
        """Page through fireflies_get_transcripts; `limit` is a TOTAL, ≤50 per call."""
        # FILL IN: loop skip=0,50,...; args = {"limit": min(50, remaining), "skip": skip} (+ "fromDate": from_date);
        #   page = FirefliesObsidianAgent._parse_fireflies_response(result.result);
        #   stop on falsy/unsuccessful result or short page — bounded by packages/ai-parrot/src/parrot/agents/obsidian.py:357 and :462-482
        raise NotImplementedError

    async def _fetch_transcript(self, fireflies_id: str) -> str:
        """Full transcript text for one meeting."""
        result = await self._call_fireflies_tool("fireflies_get_transcript", {"transcriptId": fireflies_id})
        return result.result if hasattr(result, "result") else str(result)

    async def _fetch_summary(self, fireflies_id: str) -> str | None:
        """Fireflies' native summary, or None — never raises."""
        # FILL IN: "fireflies_get_summary"; unsuccessful result or any exception -> log WARNING, return None
        raise NotImplementedError
```
**Why this shape**: `__init__` does no I/O so the registry/test harness can construct the
agent cheaply. Do not rename any method — TASK-4571 calls `_fetch_listing`,
`_fetch_transcript` and `_fetch_summary` by these names.

### FILL IN checklist
- [ ] `configure` — inbox resolution; bounded by C6.
- [ ] `_build_jira_toolkit` — mirror the reviewer; never raise.
- [ ] `_ensure_fireflies_mcp` — obsidian logic.
- [ ] `_fetch_listing` — pagination rule.
- [ ] `_fetch_summary` — never raises.
- [ ] `packages/ai-parrot/tests/bots/test_fireflies_insights.py` tests below.

---

## Acceptance Criteria

- [ ] **AC25** After `configure()`, `agent._skill_registry is None` (no DB registry) and
  `agent._skill_file_registry` is set.
- [ ] **AC15** A skill under the configured `skill_paths` is listed by the file registry.
- [ ] `_fetch_listing(limit=120)` issues 3 calls (50, 50, 20) and stops early on a short page.
- [ ] `_fetch_summary` returns `None` when the tool fails or raises.
- [ ] `ruff check packages/ai-parrot/src/parrot/bots/fireflies_insights.py packages/ai-parrot/tests/bots/test_fireflies_insights.py` clean.

---

## Validation Commands

> File-level pytest only — no directories, no package roots.

- `pytest packages/ai-parrot/tests/bots/test_fireflies_insights.py -q`

---

## Test Specification

```python
# packages/ai-parrot/tests/bots/test_fireflies_insights.py  (append)
# Build the agent without a live LLM: patch Agent.configure/post_configure to no-ops,
# point skill_paths at tmp_path, wiki_root at a tmp dir holding a minimal project.
async def test_configure_uses_file_skills_only(tmp_path, monkeypatch): ...   # AC25 + AC15
async def test_fetch_listing_paginates(monkeypatch): ...                     # fake _call_fireflies_tool
async def test_fetch_summary_failure_is_none(monkeypatch): ...
```
> FILL IN: bodies. If constructing `Agent` requires an LLM, construct with
> `FirefliesInsightsAgent.__new__(FirefliesInsightsAgent)` and set only the attributes
> under test — the established pattern for Agent unit tests in this repo.

---

## Agent Instructions

When you pick up this task:

1. **Work in the feature worktree** — never on `dev`
   (`python -m scripts.sdd.ensure_worktree --slug fireflies-insights-agent --feature-id FEAT-715`).
2. **Read the spec** `sdd/specs/fireflies-insights-agent.spec.md` — §3 (the module this task implements) and §6.
3. **Check dependencies** — every `Depends-on` task must be `"done"` in
   `sdd/tasks/index/fireflies-insights-agent.json`.
4. **Verify the Codebase Contract** before writing code. Anchors were verified at
   `f6a4dbfca`; re-run every `grep -c` in the blueprint and use the fresh count.
   A count of `0` means the anchor moved — stop and report, never invent one.
5. **Update status** in the per-spec index → `"in-progress"` (set `started_at`)
   and commit only that index file.
6. **Implement** from the Implementation Blueprint; complete every `# FILL IN:`
   marker; never change a signature, class name or path the blueprint fixes.
7. **Run** the Validation Commands with `PYTHONPATH=packages/ai-parrot/src`
   (plus `packages/ai-parrot-tools/src:packages/ai-parrot-integrations/src`
   when the task imports them) — the shared venv is installed against the main
   checkout. Then `ruff check --fix` on every file you touched.
8. **Commit** only the files this task lists (never `git add .` / `-A`):
   `feat(fireflies-insights-agent): TASK-4570 — <title>`.
9. **Close** with `scripts/sdd/close_task.sh TASK-4570 fireflies-insights-agent verified` — never move
   the file by hand.
10. **Fill in the Completion Note** below, then commit the staged SDD state.

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**: <session or agent ID>
**Date**: YYYY-MM-DD
**Notes**: What was implemented, any deviations from scope, issues encountered.

**Deviations from spec**: none | describe if any
