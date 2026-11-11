# TASK-5491: Install orchestration and agent inventory

**Feature**: FEAT-877 — Agent as a local stdio MCP server
**Spec**: `sdd/specs/agent-local-mcp.spec.md`
**Status**: done
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-5490, TASK-5488, TASK-5486
**Assigned-to**: unassigned

---

## Context

`parrot toolkits install --agent X` must resolve every requested agent first (any error
leaves every file untouched), seed the `agent-<slug>` sections, then run the SAME host
reconciliation `install_toolkits` runs — which already derives one `parrot-<section>`
entry per enabled section for Claude Code, Codex and Antigravity. This task implements the
install half of spec §3 **Module 4** in `toolkit_install.py`: `install_agent_toolkits()`
and `agent_inventory()` (the rows `parrot toolkits list --agents` prints). `uninstall`,
`enable` and `disable` already work by section name — this task proves it with a test
(AC-7) and changes none of them.

---

## Scope

- Add `install_agent_toolkits(root, agents, hosts, *, portable=None) -> ActionReport`
  before `uninstall_toolkits`: resolve all → refuse shared section names → parse the
  existing config → seed → `_reconcile_all` → Claude approvals (the order of
  `install_toolkits`).
- Add `agent_inventory(root, hosts=None) -> list[ToolkitRow]`: one row per exposable agent,
  plus one row per installed agent section whose agent no longer resolves
  (`drift=["agent not exposable: <reason>"]`).
- Append install/inventory/uninstall/disable tests to `test_agent_toolkit_install.py`.

**NOT in scope**: CLI options (TASK-5493); stale detection (TASK-5492); any change to
`install_toolkits`, `uninstall_toolkits`, `set_toolkits_enabled`, `inventory` or the host
adapters.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/mcp/toolkit_install.py` | MODIFY | `install_agent_toolkits`, `agent_inventory` |
| `packages/ai-parrot/tests/mcp/test_agent_toolkit_install.py` | MODIFY | Install, inventory, uninstall/disable tests |

---

## Codebase Contract (Anti-Hallucination)

> Verified against `origin/dev` at `41df674d50` (2026-11-11).

### Verified Imports
```python
# toolkit_install.py today (lines 7-30): from __future__ import annotations; importlib.util; Enum; Path; Sequence;
#   yaml; BaseModel, Field; from parrot.mcp.hosts import HostEntryState, HostKind, detect_hosts, get_adapter (line 18);
#   from parrot.mcp.toolkit_config import load_toolkits_config (line 19);
#   from parrot.mcp.toolkit_seed import (REPO_ROOT_PLACEHOLDER, available_templates, load_template, preflight_seed,
#       remove_section, seed_toolkit_sections, set_section_enabled, template_drift) (lines 20-29)
from parrot.mcp.toolkit_config import AGENT_TOOLKIT_CLASS_PATH, agent_section_name, is_agent_section  # TASK-5486
from parrot.mcp.toolkit_seed import seed_agent_sections                                               # TASK-5490
# lazy, inside function bodies only (keeps `parrot toolkits list` import-free):
from parrot.mcp.agent_toolkit import AgentExposureError, list_exposable_agents, resolve_exposable_agent, _tool_names  # TASK-5487/5488
# tests:
from parrot.mcp.hosts import HostKind                                   # verified: test_toolkit_install.py:10
from parrot.mcp.toolkit_install import set_toolkits_enabled, uninstall_toolkits, ToolkitState  # verified: toolkit_install.py
from parrot.registry.registry import AgentRegistry                      # verified: registry.py:302
```

### Existing Signatures to Use
```python
# packages/ai-parrot/src/parrot/mcp/toolkit_install.py
class ToolkitState(str, Enum): NOT_INSTALLED, ENABLED, DISABLED          # line 32
class ToolkitRow(BaseModel):                                              # line 38 — name, summary, class_path, state
    #   (required); requires_llm, requires_dist, dist_available, requires_pip, post_install, requires_env,
    #   drift: list[str], hosts: list[HostEntryState] (defaults)
class ActionReport(BaseModel):                                            # line 55 — actions, warnings, failed_hosts
def _resolve_hosts(root: Path, hosts: Sequence[HostKind] | None) -> list[HostKind]   # line 79 (explicit else detected)
def inventory(root, hosts=None) -> list[ToolkitRow]                       # line 97 — host_states via
    #   get_adapter(kind).inspect(root, names) → dict[name, HostEntryState]; row_hosts list comprehension (line 124)
def _reconcile_all(root, hosts, report, *, portable=None) -> None         # line 145
def install_toolkits(root, names, hosts, *, portable=None) -> ActionReport   # line 163 — order: preflight → seed →
    #   report lines → _reconcile_all → `if HostKind.CLAUDE in resolved_hosts: message =
    #   get_adapter(HostKind.CLAUDE).sync_approvals(root)` (lines 186-189)
def uninstall_toolkits(root: Path, names: Sequence[str], hosts: Sequence[HostKind]) -> ActionReport   # line 194
def set_toolkits_enabled(root, names, enabled, hosts, *, portable=None) -> ActionReport               # line 229

# packages/ai-parrot/src/parrot/knowledge/wiki/claude_code/installer.py — reconcile derives one entry per enabled
#   section (lines 423-427 `for name, section in sorted(cfg.toolkits.items())`) → "parrot-<section>" running
#   `parrot mcp-local <section>`: no host-side change is needed.
```

### Does NOT Exist
- ~~`install_toolkits(..., agents=...)`~~ — agents get their own function; `install_toolkits` is untouched.
- ~~a `registry` parameter on `install_agent_toolkits` / `agent_inventory`~~ — the spec signatures use the
  global registry. Tests isolate by `monkeypatch.setattr("parrot.mcp.agent_toolkit.agent_registry", <isolated>)`,
  which `discover_agents(None)` reads at call time.
- ~~`ToolkitRow.kind`~~ — an agent row is recognised by `class_path == AGENT_TOOLKIT_CLASS_PATH`.

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {"path": "packages/ai-parrot/src/parrot/mcp/toolkit_install.py", "action": "MODIFY"},
    {"path": "packages/ai-parrot/tests/mcp/test_agent_toolkit_install.py", "action": "MODIFY"}
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot/src/parrot/mcp/toolkit_install.py#ToolkitRow",
    "sym:packages/ai-parrot/src/parrot/mcp/toolkit_install.py#ActionReport",
    "sym:packages/ai-parrot/src/parrot/mcp/toolkit_install.py#_reconcile_all",
    "sym:packages/ai-parrot/src/parrot/mcp/toolkit_install.py#_resolve_hosts",
    "sym:packages/ai-parrot/src/parrot/mcp/toolkit_install.py#install_toolkits",
    "sym:packages/ai-parrot/src/parrot/mcp/toolkit_install.py#uninstall_toolkits",
    "sym:packages/ai-parrot/src/parrot/mcp/toolkit_install.py#set_toolkits_enabled"
  ]
}
```

---

## Implementation Notes

### Report strings (spec §3 M4 — tests assert them)
- action: `<agent> — seeded as <section> (tools: a, b)`
- warning: `<agent> — already installed as <section>`
- two requested agents sharing a section: `ValueError` naming both agents and the section.

### Key Constraints
- All-or-nothing: every `resolve_exposable_agent` call, the section-name check and the
  existing-config parse happen BEFORE `seed_agent_sections` writes (AC-6).
- Collect every `AgentExposureError` and raise ONE `ValueError` joining them, so the CLI
  shows all bad names at once.
- Import `parrot.mcp.agent_toolkit` lazily inside both functions — `toolkit_install` is
  imported by `parrot toolkits list`, which must stay cheap when `--agents` is not given.

---

## Implementation Blueprint

### Steps (in order)
1. Extend the two import statements — *why*: the new functions need the section helpers and the seeder.
2. Insert both functions above `uninstall_toolkits` — *why*: spec §3 M4 fixes the location.
3. Append the tests; run the Validation Commands.

### `packages/ai-parrot/src/parrot/mcp/toolkit_install.py` (MODIFY) — imports
```python
# occurrences: 1 (verified: grep -cx 'from parrot.mcp.toolkit_config import load_toolkits_config' toolkit_install.py → line 19)
# REPLACE with:
from parrot.mcp.toolkit_config import AGENT_TOOLKIT_CLASS_PATH, agent_section_name, is_agent_section, load_toolkits_config

# occurrences: 1 (verified: grep -cx '    seed_toolkit_sections,' toolkit_install.py → line 26)
# BEFORE — insert above `    seed_toolkit_sections,` inside the toolkit_seed import list:
    seed_agent_sections,
```

### `toolkit_install.py` (MODIFY) — new functions
```python
# occurrences: 1 (verified: grep -c 'def uninstall_toolkits(root: Path, names: Sequence\[str\], hosts: Sequence\[HostKind\]) -> ActionReport:' toolkit_install.py)
# BEFORE — insert above `def uninstall_toolkits(...)` (verified: toolkit_install.py:194)
def install_agent_toolkits(
    root: Path, agents: Sequence[str], hosts: Sequence[HostKind], *, portable: bool | None = None
) -> ActionReport:
    """Resolve → seed → reconcile → approvals for agent sections (FEAT-877). All-or-nothing before the first write.

    Raises:
        ValueError: an agent cannot be exposed, two agents share a section name, or the config is malformed.
    """
    from parrot.mcp.agent_toolkit import AgentExposureError, _tool_names, resolve_exposable_agent  # noqa: PLC0415

    root = Path(root)
    resolved = []
    errors: list[str] = []
    for name in dict.fromkeys(agents):
        try:
            resolved.append(resolve_exposable_agent(name))
        except AgentExposureError as exc:
            errors.append(str(exc))
    if errors:
        raise ValueError("; ".join(errors))
    sections: dict[str, str] = {}
    # FILL IN: for each resolved agent: section = agent_section_name(agent.name); a section already in
    #   `sections` → ValueError naming both agents and the section; else sections[section] = agent.name
    load_toolkits_config(root)  # malformed existing config → ValueError before any write
    report = ActionReport()
    seed_result = seed_agent_sections(root, sections)
    tools = {agent_section_name(a.name): ", ".join(_tool_names(a.methods, a.name)) for a in resolved}
    report.actions.extend(f"{sections[s]} — seeded as {s} (tools: {tools[s]})" for s in seed_result.added)
    report.warnings.extend(f"{sections[s]} — already installed as {s}" for s in seed_result.skipped)
    resolved_hosts = list(hosts)
    _reconcile_all(root, resolved_hosts, report, portable=portable)
    # FILL IN: Claude approvals exactly as install_toolkits lines 186-189; return report


def agent_inventory(root: Path, hosts: Sequence[HostKind] | None = None) -> list[ToolkitRow]:
    """One row per exposable agent and per orphaned agent section. Runs agent discovery (imports agent modules)."""
    from parrot.mcp.agent_toolkit import AgentExposureError, list_exposable_agents, resolve_exposable_agent  # noqa: PLC0415

    root = Path(root)
    resolved_hosts = _resolve_hosts(root, hosts)
    declared = load_toolkits_config(root)
    exposable = list_exposable_agents()
    installed = {name: s for name, s in declared.toolkits.items() if is_agent_section(s)}
    names = sorted({a.section_name for a in exposable} | set(installed))
    host_states = {kind: get_adapter(kind).inspect(root, names) for kind in resolved_hosts}

    def _state(section_name: str) -> ToolkitState:
        section = declared.toolkits.get(section_name)
        if section is None:
            return ToolkitState.NOT_INSTALLED
        return ToolkitState.ENABLED if section.enabled else ToolkitState.DISABLED

    def _hosts(section_name: str) -> list:
        return [host_states[k][section_name] for k in resolved_hosts if section_name in host_states[k]]

    rows = [
        ToolkitRow(name=a.section_name, summary=f"agent {a.name}: {', '.join(a.tools)}",
                   class_path=AGENT_TOOLKIT_CLASS_PATH, state=_state(a.section_name), hosts=_hosts(a.section_name))
        for a in exposable
    ]
    listed = {a.section_name for a in exposable}
    for section_name, section in installed.items():
        if section_name in listed:
            continue
        agent = str(section.kwargs.get("agent", ""))
        # FILL IN: reason = str(exc) from resolve_exposable_agent(agent) raising AgentExposureError; when it
        #   resolves, reason = f"installed as {section_name}, expected {agent_section_name(agent)}";
        #   append ToolkitRow(name=section_name, summary=f"agent {agent}", class_path=AGENT_TOOLKIT_CLASS_PATH,
        #   state=_state(section_name), drift=[f"agent not exposable: {reason}"], hosts=_hosts(section_name))
    return rows
```
**Why this shape**: reusing `_reconcile_all` and the Claude approval step is what makes
every host get `parrot-agent-<slug>` with zero adapter changes (G5, AC-9).

### `packages/ai-parrot/tests/mcp/test_agent_toolkit_install.py` (MODIFY) — append
```python
# AFTER — append at end of file (created by TASK-5490); add imports: `import json`,
#   `from parrot.bots.agent import Agent`, `from parrot.mcp.hosts import HostKind`,
#   `from parrot.mcp.toolkit_install import ToolkitState, agent_inventory, install_agent_toolkits,
#    set_toolkits_enabled, uninstall_toolkits`, `from parrot.registry.registry import AgentRegistry`


class FinanceAgent(Agent):
    async def forecast(self, months: int) -> dict:
        """Forecast cash for the next `months` months."""
        return {"months": months}


@pytest.fixture
def repo(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """A project root plus an isolated registry with `finance` declared, patched in as the global one."""
    registry = AgentRegistry(agents_dir=tmp_path / "agents")
    registry.register_bot_decorator(name="finance", mcp_local=True)(FinanceAgent)
    monkeypatch.setattr("parrot.mcp.agent_toolkit.agent_registry", registry)
    root = tmp_path / "repo"
    root.mkdir()
    return root


def test_install_agent_all_or_nothing(repo: Path) -> None:
    # FILL IN: install_agent_toolkits(repo, ["finance", "nope"], [HostKind.CLAUDE]) raises ValueError naming "nope";
    #   neither .parrot/mcp-toolkits.yaml nor .mcp.json exists afterwards (AC-6)
    ...


def test_install_agent_reconciles_hosts(repo: Path) -> None:
    # FILL IN: report = install_agent_toolkits(repo, ["finance"], [HostKind.CLAUDE]); "finance — seeded as agent-finance
    #   (tools: forecast)" in report.actions; .mcp.json mcpServers["parrot-agent-finance"]["args"] contains "mcp-local"
    #   and "agent-finance"; a second install → warning "finance — already installed as agent-finance" (AC-6)
    ...


def test_agent_inventory_rows(repo: Path) -> None:
    # FILL IN: before install → one row agent-finance NOT_INSTALLED with summary "agent finance: forecast"; after
    #   install → ENABLED; a hand-seeded section {"agent-ghost": "ghost"} (seed_agent_sections) → orphan row with
    #   drift[0].startswith("agent not exposable: ")
    ...


def test_uninstall_and_disable_agent_section(repo: Path) -> None:
    # FILL IN: install; set_toolkits_enabled(repo, ["agent-finance"], False, [HostKind.CLAUDE]) → .mcp.json lacks
    #   "parrot-agent-finance" and the section is kept disabled; enable → entry back; uninstall_toolkits(...) → section
    #   and entry gone (AC-7)
    ...
```

### FILL IN checklist
- [ ] section-name collision check — spec §3 M4.
- [ ] Claude approvals step — mirror `install_toolkits`.
- [ ] orphan-row reason — spec §3 M4 `agent_inventory`.
- [ ] every `...` test body.

---

## Acceptance Criteria

- [ ] `install_agent_toolkits` writes the `agent-<slug>` section and a `parrot-agent-<slug>` entry per selected host; one invalid agent leaves every file byte-identical (AC-6).
- [ ] `uninstall_toolkits` / `set_toolkits_enabled` remove / toggle the agent section and its host entry with no code change (AC-7).
- [ ] `agent_inventory` lists exposable agents and orphaned agent sections with drift.
- [ ] Existing install tests stay green.
- [ ] `ruff check` clean on both files.

---

## Validation Commands

- `pytest packages/ai-parrot/tests/mcp/test_agent_toolkit_install.py -q`
- `pytest packages/ai-parrot/tests/mcp/test_toolkit_install.py -q`

---

## Test Specification

See the MODIFY block above: spec §4 Module 4 rows `test_install_agent_all_or_nothing`,
`test_install_agent_reconciles_hosts`, `test_agent_inventory_rows`, and the integration
test `test_uninstall_and_disable_agent_section`.

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
9. **Close the task** with `parrot sdd task close TASK-5491 agent-local-mcp verified`
10. **Fill in the Completion Note** below, then commit the staged SDD state

---

## Completion Note

**Completed by**: sdd-worker (seat gpt-5.6-sol · codex · 1 attempt, 137s)
**Date**: 2026-11-11
**Notes**: `install_agent_toolkits` and `agent_inventory` implemented in `toolkit_install.py` with tests in `test_agent_toolkit_install.py`. Merge-tier validation green (42 passed, evidence recorded via coder_record_review: coder-review:1a395f8b74dcf0ea3b39a2d3). Closed with `parrot sdd task close` because `parrot sdd task finalize` rejected it with a fidelity error: the unrelated TASK-5489 commits in the same range were flagged as unexpected files.

**Deviations from spec**: none
