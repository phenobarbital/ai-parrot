# TASK-5492: Stale detection knows agent sections

**Feature**: FEAT-877 — Agent as a local stdio MCP server
**Spec**: `sdd/specs/agent-local-mcp.spec.md`
**Status**: done
**Priority**: medium
**Estimated effort**: S (< 2h)
**Depends-on**: TASK-5486
**Assigned-to**: unassigned

---

## Context

`find_stale_mcp_entries` reports any `parrot-<name>` host entry whose `<name>` has no
packaged template as `retired-toolkit`, and `parrot sdd` doctor / cleanup remove those
entries (callers: `parrot/sdd/cli.py:198-201`, `parrot/sdd/installer.py:1748,2021`).
Agent sections never have a template, so without this task every installed agent would be
reported and deleted. This task implements spec §3 **Module 5** (G7, AC-10).

---

## Scope

- In `find_stale_mcp_entries`, compute `agent_sections = {name for name, s in cfg.toolkits.items() if is_agent_section(s)}`
  when the config loads, and pass `templates | agent_sections` to `_reason` (its signature
  is unchanged).
- When the config is unreadable (the existing `except ValueError` branch), treat every
  name starting with `AGENT_SECTION_PREFIX` as known — never report or remove an agent
  entry on uncertainty.
- For **global-scope** files (`item.scope == "global"`, e.g. Antigravity's user config),
  also treat every `agent-*` name as known: such an entry may belong to another repository,
  whose config this run cannot see; its dead-pin case is still caught by the existing
  `missing-repo` rule. (Task-time refinement of spec M5 — it implements G7 "an installed
  agent section is never reported as retired" for agents installed from another checkout.)
- An agent section that was uninstalled from THIS repo (repo-scope file, readable config,
  section absent) is still reported `retired-toolkit`.
- Append the tests to `test_toolkit_stale.py`.

**NOT in scope**: changing `_reason`'s signature or precedence; `remove_stale_mcp_entries`;
the doctor/cleanup callers.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/mcp/toolkit_stale.py` | MODIFY | Known-name union for agent sections |
| `packages/ai-parrot/tests/mcp/test_toolkit_stale.py` | MODIFY | Agent-section tests |

---

## Codebase Contract (Anti-Hallucination)

> Verified against `origin/dev` at `41df674d50` (2026-11-11).

### Verified Imports
```python
from parrot.mcp.toolkit_config import load_toolkits_config               # verified: toolkit_stale.py:19
from parrot.mcp.toolkit_config import AGENT_SECTION_PREFIX, is_agent_section  # created by TASK-5486
from parrot.mcp.toolkit_seed import available_templates                  # verified: toolkit_stale.py:20
# tests (already imported in test_toolkit_stale.py lines 9-16):
from parrot.mcp.toolkit_seed import seed_toolkit_sections, set_section_enabled
from parrot.mcp.toolkit_stale import StaleMcpEntry, find_stale_mcp_entries, is_parrot_toolkit_entry, remove_stale_mcp_entries
from parrot.mcp.toolkit_seed import seed_agent_sections                  # created by TASK-5490 — NOT a dependency here:
#   write the agent section with plain text in the tests instead (see blueprint), so this task needs only TASK-5486
```

### Existing Signatures to Use
```python
# packages/ai-parrot/src/parrot/mcp/toolkit_stale.py
class _McpFile:                       # line ~40 — path, display, fmt json|toml, scope: Literal["repo", "global"] (line 46)
def _reason(root, item, name, args, templates: set[str], enabled: set[str] | None) -> tuple[...] | None   # line 116
    #   `if name not in templates: return "retired-toolkit", ...` (lines 120-121); repo scope then checks foreign-repo and
    #   undeclared (`enabled is not None and name not in enabled`); global scope checks missing-repo
def find_stale_mcp_entries(root, hosts, *, gemini_config=None) -> list[StaleMcpEntry]   # line 140
    #   templates = set(available_templates())                        (line 159)
    #   try: cfg = load_toolkits_config(root); enabled = {...enabled sections}   (lines 160-162)
    #   except ValueError as exc: logger.warning(...); enabled = None   (lines 163-165)
    #   for item in _mcp_files(...): ... name = key[len("parrot-"):]
    #       stale_reason = _reason(root, item, name, entry["args"], templates, enabled)   (line 176)

# packages/ai-parrot/tests/mcp/test_toolkit_stale.py
def _entry(name: str, config: str) -> dict[str, object]              # line 20 — {"command": "/venv/bin/parrot", "args": ["mcp-local", name, "--config", config]}
def _write_servers(path: Path, servers: dict[str, object]) -> None   # line 24
@pytest.fixture def repo(tmp_path) -> Path                            # line 30 — browsing enabled, scraping disabled
@pytest.fixture def gemini(tmp_path) -> Path                          # line 40 — isolated global Gemini config
def test_codex_unremovable_layout_reported_not_claimed(repo: Path, gemini: Path) -> None   # line 329 (last test)
```

### Does NOT Exist
- ~~`_reason(..., agent_sections=...)`~~ — `_reason` keeps its signature; pass the union as `templates`.
- ~~a `retired-agent` reason~~ — the reason literals are unchanged.
- ~~importing `parrot.mcp.agent_toolkit` / `parrot.registry` here~~ — stale detection stays registry-free.

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {"path": "packages/ai-parrot/src/parrot/mcp/toolkit_stale.py", "action": "MODIFY"},
    {"path": "packages/ai-parrot/tests/mcp/test_toolkit_stale.py", "action": "MODIFY"}
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot/src/parrot/mcp/toolkit_stale.py#find_stale_mcp_entries",
    "sym:packages/ai-parrot/src/parrot/mcp/toolkit_stale.py#_reason",
    "sym:packages/ai-parrot/src/parrot/mcp/toolkit_config.py#load_toolkits_config"
  ]
}
```

---

## Implementation Notes

### Key Constraints
- Agent entries of THIS repo also pass `_reason`'s later repo-scope checks: a disabled
  agent section is reported `undeclared` exactly like a disabled template section — that is
  the existing semantics, keep it.
- Keep the known-name computation outside the per-entry loop except for the global-scope
  `agent-*` rule, which depends on `item.scope` and `name`.

---

## Implementation Blueprint

### Steps (in order)
1. Extend the `toolkit_config` import — *why*: the rule needs `is_agent_section` and the prefix.
2. Compute `agent_sections` in the existing try/except — *why*: the unreadable branch must not crash and must keep agent entries.
3. Build the per-entry known set and pass it to `_reason` — *why*: G7 / AC-10.
4. Append the tests; run the Validation Commands.

### `packages/ai-parrot/src/parrot/mcp/toolkit_stale.py` (MODIFY) — import
```python
# occurrences: 1 (verified: grep -cx 'from parrot.mcp.toolkit_config import load_toolkits_config' toolkit_stale.py → line 19)
# REPLACE with:
from parrot.mcp.toolkit_config import AGENT_SECTION_PREFIX, is_agent_section, load_toolkits_config
```

### `toolkit_stale.py` (MODIFY) — known names
```python
# occurrences: 1 (verified: grep -c '    templates = set(available_templates())' toolkit_stale.py → line 159)
# REPLACE the block (verified: toolkit_stale.py:159-165)
#     templates = set(available_templates())
#     try:
#         cfg = load_toolkits_config(root)
#         enabled: set[str] | None = {name for name, section in cfg.toolkits.items() if section.enabled}
#     except ValueError as exc:
#         logger.warning("toolkit config unreadable (%s); `undeclared` entries are not reported", exc)
#         enabled = None
# WITH
    templates = set(available_templates())
    agent_sections: set[str] = set()
    config_readable = True
    try:
        cfg = load_toolkits_config(root)
        enabled: set[str] | None = {name for name, section in cfg.toolkits.items() if section.enabled}
        agent_sections = {name for name, section in cfg.toolkits.items() if is_agent_section(section)}
    except ValueError as exc:
        logger.warning("toolkit config unreadable (%s); `undeclared` entries are not reported", exc)
        enabled = None
        config_readable = False
    known = templates | agent_sections

# occurrences: 1 (verified: grep -c 'stale_reason = _reason(root, item, name, entry\["args"\], templates, enabled)' → line 176)
# REPLACE that line with:
            item_known = known
            # FILL IN: when name.startswith(AGENT_SECTION_PREFIX) and (not config_readable or item.scope == "global"),
            #   item_known = known | {name} — bounded by spec §3 M5 and the Scope refinement above
            stale_reason = _reason(root, item, name, entry["args"], item_known, enabled)
```

### `packages/ai-parrot/tests/mcp/test_toolkit_stale.py` (MODIFY) — append
```python
# AFTER — append below the last test `def test_codex_unremovable_layout_reported_not_claimed(...)` (verified: line 329)

_AGENT_SECTION = (
    "  agent-finance:\n"
    "    class: parrot.mcp.agent_toolkit.AgentToolkit\n"
    "    kwargs:\n"
    "      agent: finance\n"
    "    env: {}\n"
)


def _add_agent_section(root: Path) -> None:
    """Append an agent section the way seed_agent_sections lays it out (two-space indent under toolkits:)."""
    path = root / ".parrot" / "mcp-toolkits.yaml"
    path.write_text(path.read_text(encoding="utf-8") + _AGENT_SECTION, encoding="utf-8")


def test_agent_section_not_retired(repo: Path, gemini: Path) -> None:
    # FILL IN: _add_agent_section(repo); .mcp.json with "parrot-agent-finance" → find_stale_mcp_entries == [] (AC-10)
    ...


def test_unreadable_config_keeps_agent_entries(repo: Path, gemini: Path) -> None:
    # FILL IN: corrupt .parrot/mcp-toolkits.yaml; .mcp.json with "parrot-agent-finance" and "parrot-oldkit" →
    #   only parrot-oldkit reported (retired-toolkit) (AC-10)
    ...


def test_removed_agent_section_is_retired(repo: Path, gemini: Path) -> None:
    # FILL IN: no agent section in the readable config; .mcp.json "parrot-agent-finance" → reason "retired-toolkit"
    ...


def test_global_agent_entry_from_other_repo_not_retired(repo: Path, gemini: Path, tmp_path: Path) -> None:
    # FILL IN: other = tmp_path / "other" with .parrot/ dir; gemini entry "parrot-agent-hr" whose --config is
    #   other/.parrot/mcp-toolkits.yaml → not reported; same entry pinned to a deleted repo → "missing-repo"
    ...
```

### FILL IN checklist
- [ ] per-entry `item_known` rule — spec §3 M5 + Scope refinement.
- [ ] every `...` test body.

---

## Acceptance Criteria

- [ ] An installed agent entry is never reported or removed as stale, even when the config is unreadable (AC-10).
- [ ] An agent entry in a global host config that belongs to another repository is not reported `retired-toolkit`.
- [ ] An uninstalled agent section (repo scope, readable config) is reported `retired-toolkit` (AC-10).
- [ ] Every existing stale test stays green.
- [ ] `ruff check` clean on both files.

---

## Validation Commands

- `pytest packages/ai-parrot/tests/mcp/test_toolkit_stale.py -q`

---

## Test Specification

See the MODIFY block above: spec §4 Module 5 rows `test_agent_section_not_retired`,
`test_unreadable_config_keeps_agent_entries`, `test_removed_agent_section_is_retired`,
plus `test_global_agent_entry_from_other_repo_not_retired`.

---

## Agent Instructions

When you pick up this task:

1. **Work in the feature worktree** — never on `base_branch`
   (`parrot sdd worktree ensure --slug agent-local-mcp --feature-id FEAT-877`)
2. **Read the spec** at the path listed above for full context
3. **Check dependencies** — every `Depends-on` task must be `"done"` in
   `sdd/tasks/index/agent-local-mcp.json`
4. **Verify the Codebase Contract** before writing code; if anything changed, update the contract first
5. **Update status** in the per-spec index → `"in-progress"` (set `started_at`) and commit only that file
6. **Implement** from the Implementation Blueprint; complete every `# FILL IN:` marker
7. **Verify** the acceptance criteria — run the Validation Commands with `PYTHONPATH=packages/ai-parrot/src`
8. **Commit the code** — stage only the files this task lists
9. **Close the task** with `parrot sdd task close TASK-5492 agent-local-mcp verified`
10. **Fill in the Completion Note** below, then commit the staged SDD state

---

## Completion Note


- Task: TASK-5492
- Feature: agent-local-mcp
- Implementation SHA: 6be06f17097bdd4d54da566b87995e438c6a7ca2
- Closed at (UTC): 2026-11-11T00:21:03+00:00
- Fix commits: none

| Metric | Value |
|---|---|
| validation_refs | 1 |
| fix_commits | 0 |
| seat_summary | Seat: gpt-5.6-luna · Backend: codex · Model: gpt-5.6-luna · Attempts: 1 · Duration: 86s · Tokens: n/a |
