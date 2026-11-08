# TASK-5356: Port the Google `sdd-autopilot` agent from `claude` to `agy` invocations

**Feature**: FEAT-847 — SDD Antigravity CLI (AGY) Operational Compatibility
**Spec**: `sdd/specs/sdd-agy-compatibility.spec.md`
**Status**: pending
**Priority**: medium
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-5355
**Assigned-to**: unassigned

---

## Context

Spec §3 Module 5, item 4. `.agents/agents/sdd-autopilot/agent.md` (820 lines, Google host) still shells out to
Claude Code: 21 lines mention `claude`, e.g. `claude --agent sdd-worker --setting-sources project,local …`,
`claude --agent code-reviewer …`, `claude --agent qa-runner …`, `claude -p "/pr-review …"`. On agy those must be
`agy --agent <name> …` / `agy -p …`, and every agent it dispatches must exist under `.agents/agents/`
(`code-reviewer` and `qa-runner` are shipped by TASK-5355).

**Spec drift:** spec §6 quotes the anchor `# SDD Autopilot — Autonomous Spec-to-PR Pipeline Orchestrator` at
`agent.md:9`; the real H1 is `# SDD Multi-Agent Orchestration — Design Document` at line 10.

---

## Scope

- Rewrite every `claude` shell invocation in `.agents/agents/sdd-autopilot/agent.md` for `agy`:
  `claude --agent X` → `agy --agent X`; `claude -p "…"` → `agy -p "…"`; drop Claude-only flags
  (`--setting-sources project,local`, `--verbose` where agy has no equivalent); unattended stages add
  `--dangerously-skip-permissions`; never add `--mode auto`.
- Update the prose that describes "a Claude Code process" accordingly; keep the pipeline logic unchanged.
- Regenerate the packaged copy with `scripts/sdd/check_asset_sync.py --write`.
- Add tests to `test_agy_agents.py` (created by TASK-5355).

**NOT in scope**: the Claude `sdd-autopilot` (`.claude/agents/sdd-autopilot.md`); the `sdd-worker` port (TASK-5357).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `.agents/agents/sdd-autopilot/agent.md` | MODIFY | `claude` → `agy` invocations and prose |
| `packages/ai-parrot/src/parrot/sdd/_assets/agents/agents/sdd-autopilot/agent.md` | MODIFY | regenerated copy |
| `packages/ai-parrot/tests/sdd/test_agy_agents.py` | MODIFY | dispatched agents resolve; no Claude CLI left |

---

## Codebase Contract (Anti-Hallucination)

> Verified on `dev` @ `ae3b48c7f3` (2026-11-09).

### Verified Imports
```python
from parrot.sdd.installer import install_sdd_integration   # used by test_agy_agents.py (TASK-5355)
```

### Existing Signatures to Use
```text
.agents/agents/sdd-autopilot/agent.md — Claude CLI call sites (grep -n "claude --agent\|claude -p"):
  31, 280, 295, 335, 352, 371, 389, 407, 413, 448, 716, 730, 742   (21 lines mention "claude" in total)
  frontmatter lines 1-8 (name: sdd-autopilot, subagent: true, mainAgent: false, model: inherit) — keep
packages/ai-parrot/tests/sdd/test_installer.py:489 — the Claude twin of the resolution test:
  names = set(re.findall(r"claude --agent ([a-z][a-z-]*)", text)); assert {"code-reviewer", "qa-runner"} <= names
packages/ai-parrot/tests/sdd/test_agy_agents.py — google_repo fixture, REPO_ROOT (TASK-5355)
agy CLI (agy --help, 1.5.3): --agent, -p/--print, -i/--prompt-interactive, --dangerously-skip-permissions,
  --effort, --mode (accept-edits|auto|plan), --model, --output-format, --json-schema, --sandbox, --settings
```

### Does NOT Exist
- ~~`agy --setting-sources`~~ — Claude-only flag.
- ~~`agy --mode auto` as a default~~ — account-gated; never pass it.
- ~~`claude --agent` in the Google autopilot after this task~~ — the test forbids it.

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {"path": ".agents/agents/sdd-autopilot/agent.md", "action": "MODIFY"},
    {"path": "packages/ai-parrot/src/parrot/sdd/_assets/agents/agents/sdd-autopilot/agent.md", "action": "MODIFY"},
    {"path": "packages/ai-parrot/tests/sdd/test_agy_agents.py", "action": "MODIFY"}
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot/src/parrot/sdd/installer.py#install_sdd_integration"
  ]
}
```

---

## Implementation Notes

### Key Constraints
- Shipped asset: no `packages/`, `scripts/`, `PYTHONPATH=`, `CLAUDE.md`, branch literals (`origin/dev`) or
  non-SDD ticket keys (asset gates; see TASK-5355 Context).
- Each shell snippet stays self-contained (absolute worktree path or same-command `WT=` assignment).
- Approval: the worker stage is unattended → `--dangerously-skip-permissions`; mention that only
  `parrot sdd launch worker --host google` sets the unattended guard (`PARROT_SDD_AGY_UNATTENDED=1`), so prefer it
  over a raw `agy --agent sdd-worker` call where the autopilot launches the worker.

---

## Implementation Blueprint

### Steps (in order)
1. Rewrite the 13 call-site lines and the surrounding prose — *why*: spec M5 item 4.
2. Run `python scripts/sdd/check_asset_sync.py --write --root .` — *why*: regenerates the packaged copy.
3. Extend `test_agy_agents.py` — *why*: guards against regressions to `claude`.

### `.agents/agents/sdd-autopilot/agent.md` (MODIFY)
```markdown
<!-- occurrences: 1 (verified: grep -c '^# SDD Multi-Agent Orchestration — Design Document' .agents/agents/sdd-autopilot/agent.md) — line 10 -->
<!-- FILL IN: for each call site listed in the Codebase Contract, rewrite `claude --agent <name> [flags]` as
     `agy --agent <name> [agy flags]` and `claude -p "<prompt>"` as `agy -p "<prompt>"`, dropping
     `--setting-sources project,local`; where the worker is launched, prefer
     `parrot sdd launch worker <FEAT-ID> --host google`; never add `--mode auto` — bounded by spec §3 M3/M5. -->
<!-- FILL IN: update the prose at lines ~31 and ~295 ("Claude Code process") to describe agy processes. -->
```

### `packages/ai-parrot/tests/sdd/test_agy_agents.py` (MODIFY)
```python
# AFTER — append at end of file
def test_agents_dispatched_by_google_autopilot_are_installed(google_repo: Path) -> None:
    """Every `agy --agent <name>` the shipped Google autopilot runs resolves to a shipped Google agent."""
    text = (google_repo / ".agents/agents/sdd-autopilot/agent.md").read_text(encoding="utf-8")
    names = set(re.findall(r"agy --agent ([a-z][a-z-]*)", text))
    assert {"code-reviewer", "qa-runner"} <= names
    missing = sorted(n for n in names if not (google_repo / ".agents/agents" / n / "agent.md").is_file())
    assert not missing, missing


# FILL IN tests:
#  - the Google autopilot contains no "claude --agent", "claude -p" or "--setting-sources"
#  - it never contains "--mode auto"
```

### FILL IN checklist
- [ ] call-site rewrites; bounded by spec §3 M3/M5
- [ ] prose update
- [ ] remaining tests

---

## Acceptance Criteria

- [ ] `.agents/agents/sdd-autopilot/agent.md` invokes `agy`, never `claude`; no `--setting-sources`, no `--mode auto`.
- [ ] Every `agy --agent <name>` resolves to a shipped `.agents/agents/<name>/agent.md` after a Google install.
- [ ] `python scripts/sdd/check_asset_sync.py --check --root .` exits 0.

---

## Validation Commands

- `pytest packages/ai-parrot/tests/sdd/test_agy_agents.py -q`
- `pytest tests/sdd_scripts/test_check_asset_sync.py -q`

---

## Test Specification

See the test block in the Implementation Blueprint.

---

## Agent Instructions

When you pick up this task:

1. **Work in the feature worktree** — never on `base_branch`
   (`parrot sdd worktree ensure --slug sdd-agy-compatibility --feature-id FEAT-847`)
2. **Read the spec** at the path listed above for full context
3. **Check dependencies** — every `Depends-on` task must be `"done"` in `sdd/tasks/index/sdd-agy-compatibility.json`
4. **Verify the Codebase Contract** before writing any code; fix stale entries first
5. **Update status** in the per-spec index → `"in-progress"` (set `started_at`) and commit only that index file
6. **Implement** from the Implementation Blueprint, completing every `# FILL IN:` marker
7. **Verify** all acceptance criteria — run the Validation Commands (prefix `PYTHONPATH=packages/ai-parrot/src` in a worktree)
8. **Commit the code** — stage only the files this task lists
9. **Close the task** with `parrot sdd task close TASK-5356 sdd-agy-compatibility verified`
10. **Fill in the Completion Note** below, then commit the staged SDD state

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**: <session or agent ID>
**Date**: YYYY-MM-DD
**Notes**: What was implemented, any deviations from scope, issues encountered.

**Deviations from spec**: none | describe if any
