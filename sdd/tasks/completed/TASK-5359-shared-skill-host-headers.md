# TASK-5359: Host-aware adaptation-contract headers in the shared SDD skills

**Feature**: FEAT-847 — SDD Antigravity CLI (AGY) Operational Compatibility
**Spec**: `sdd/specs/sdd-agy-compatibility.spec.md`
**Status**: done
**Priority**: medium
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-5358
**Assigned-to**: unassigned

---

## Context

Spec §3 Module 5, items 5 and 6. The skills under `.agents/skills/` are shared by Codex and agy, but their header
only sends the agent to the Codex contract:

```
## Full procedure and Codex adaptations

Before executing, read the [full sdd-task procedure](../../../.claude/commands/sdd-task.md)
and the [Codex adaptation contract](../../../docs/sdd/CODEX.md#codex-adaptation-contract).
```

This task makes every such header name both contracts — Codex keeps `CODEX.md`, agy gets `AGY.md`
(TASK-5358) — and checks that no skill relies on a previous shell's `cd`/`WT` (today they already use `<wt>`
placeholders with `git -C <wt>`; keep it that way).

**Files in scope (verified):** the header link line occurs exactly once in each of 15 repo skills —
`remove-worktree`, `sdd-brainstorm`, `sdd-brief`, `sdd-codereview`, `sdd-done` (line 14), `sdd-explain`,
`sdd-fromjira`, `sdd-insight`, `sdd-next`, `sdd-proposal`, `sdd-spec`, `sdd-start`, `sdd-status`, `sdd-task`,
`sdd-tojira` (line 11 unless noted). `sdd-fix` has no such header (it gets a new one, before `## Usage`, line 18).
`sdd-insight` is not packaged (`EXCLUDED_TARGETS`) but is read by Codex/agy in this repository, so its repo copy is
updated too. The packaged copies under `_assets/agents/skills/` (15 files, no `sdd-insight`) are regenerated.

---

## Scope

- Edit the 16 repo `SKILL.md` files (15 header rewrites + 1 new header in `sdd-fix`).
- Regenerate the 15 packaged copies with `python scripts/sdd/check_asset_sync.py --write --root .`.
- Tests in `test_installer.py`.

**NOT in scope**: skill bodies beyond the header; the `.claude/commands/*` procedures; `AGY.md` content (TASK-5358).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `.agents/skills/remove-worktree/SKILL.md` | MODIFY | host-aware header |
| `.agents/skills/sdd-brainstorm/SKILL.md` | MODIFY | host-aware header |
| `.agents/skills/sdd-brief/SKILL.md` | MODIFY | host-aware header |
| `.agents/skills/sdd-codereview/SKILL.md` | MODIFY | host-aware header |
| `.agents/skills/sdd-done/SKILL.md` | MODIFY | host-aware header |
| `.agents/skills/sdd-explain/SKILL.md` | MODIFY | host-aware header |
| `.agents/skills/sdd-fix/SKILL.md` | MODIFY | new host-aware header before `## Usage` |
| `.agents/skills/sdd-fromjira/SKILL.md` | MODIFY | host-aware header |
| `.agents/skills/sdd-insight/SKILL.md` | MODIFY | host-aware header (repo only, not packaged) |
| `.agents/skills/sdd-next/SKILL.md` | MODIFY | host-aware header |
| `.agents/skills/sdd-proposal/SKILL.md` | MODIFY | host-aware header |
| `.agents/skills/sdd-spec/SKILL.md` | MODIFY | host-aware header |
| `.agents/skills/sdd-start/SKILL.md` | MODIFY | host-aware header |
| `.agents/skills/sdd-status/SKILL.md` | MODIFY | host-aware header |
| `.agents/skills/sdd-task/SKILL.md` | MODIFY | host-aware header |
| `.agents/skills/sdd-tojira/SKILL.md` | MODIFY | host-aware header |
| `packages/ai-parrot/src/parrot/sdd/_assets/agents/skills/remove-worktree/SKILL.md` | MODIFY | regenerated |
| `packages/ai-parrot/src/parrot/sdd/_assets/agents/skills/sdd-brainstorm/SKILL.md` | MODIFY | regenerated |
| `packages/ai-parrot/src/parrot/sdd/_assets/agents/skills/sdd-brief/SKILL.md` | MODIFY | regenerated |
| `packages/ai-parrot/src/parrot/sdd/_assets/agents/skills/sdd-codereview/SKILL.md` | MODIFY | regenerated |
| `packages/ai-parrot/src/parrot/sdd/_assets/agents/skills/sdd-done/SKILL.md` | MODIFY | regenerated |
| `packages/ai-parrot/src/parrot/sdd/_assets/agents/skills/sdd-explain/SKILL.md` | MODIFY | regenerated |
| `packages/ai-parrot/src/parrot/sdd/_assets/agents/skills/sdd-fix/SKILL.md` | MODIFY | regenerated |
| `packages/ai-parrot/src/parrot/sdd/_assets/agents/skills/sdd-fromjira/SKILL.md` | MODIFY | regenerated |
| `packages/ai-parrot/src/parrot/sdd/_assets/agents/skills/sdd-next/SKILL.md` | MODIFY | regenerated |
| `packages/ai-parrot/src/parrot/sdd/_assets/agents/skills/sdd-proposal/SKILL.md` | MODIFY | regenerated |
| `packages/ai-parrot/src/parrot/sdd/_assets/agents/skills/sdd-spec/SKILL.md` | MODIFY | regenerated |
| `packages/ai-parrot/src/parrot/sdd/_assets/agents/skills/sdd-start/SKILL.md` | MODIFY | regenerated |
| `packages/ai-parrot/src/parrot/sdd/_assets/agents/skills/sdd-status/SKILL.md` | MODIFY | regenerated |
| `packages/ai-parrot/src/parrot/sdd/_assets/agents/skills/sdd-task/SKILL.md` | MODIFY | regenerated |
| `packages/ai-parrot/src/parrot/sdd/_assets/agents/skills/sdd-tojira/SKILL.md` | MODIFY | regenerated |
| `packages/ai-parrot/tests/sdd/test_installer.py` | MODIFY | header / parity / fresh-shell tests |

---

## Codebase Contract (Anti-Hallucination)

> Verified on `dev` @ `ae3b48c7f3` (2026-11-09).

### Verified Imports
```python
# test_installer.py: install_sdd_integration, load_manifest (lines 19-28); _LINK_RE (line 471)
```

### Existing Signatures to Use
```text
Header heading line (1 per file in the 15 skills):   ## Full procedure and Codex adaptations
Header link line (1 per file; verified: grep -c):    and the [Codex adaptation contract](../../../docs/sdd/CODEX.md#codex-adaptation-contract).
  NOTE: in some skills the next line continues the sentence differently (two variants exist) — only the
  heading line and this link line are rewritten.
.agents/skills/sdd-fix/SKILL.md: `## Usage` (occurrences: 1, line 18)
scripts/sdd/check_asset_sync.py: EXCLUDED_TARGETS includes ".agents/skills/sdd-insight/SKILL.md" (not packaged)
docs/sdd/AGY.md anchor: #antigravity-adaptation-contract (TASK-5358)
packages/ai-parrot/tests/sdd/test_installer.py:475 test_non_claude_host_skills_have_every_file_they_read — link check
```

### Does NOT Exist
- ~~Host-specific copies of the skills~~ — one shared file per skill for Codex and agy; the header names both contracts.
- ~~`$WT` uses in the shared skills~~ — 0 today; do not introduce cross-call variables.

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {"path": ".agents/skills/remove-worktree/SKILL.md", "action": "MODIFY"},
    {"path": ".agents/skills/sdd-brainstorm/SKILL.md", "action": "MODIFY"},
    {"path": ".agents/skills/sdd-brief/SKILL.md", "action": "MODIFY"},
    {"path": ".agents/skills/sdd-codereview/SKILL.md", "action": "MODIFY"},
    {"path": ".agents/skills/sdd-done/SKILL.md", "action": "MODIFY"},
    {"path": ".agents/skills/sdd-explain/SKILL.md", "action": "MODIFY"},
    {"path": ".agents/skills/sdd-fix/SKILL.md", "action": "MODIFY"},
    {"path": ".agents/skills/sdd-fromjira/SKILL.md", "action": "MODIFY"},
    {"path": ".agents/skills/sdd-insight/SKILL.md", "action": "MODIFY"},
    {"path": ".agents/skills/sdd-next/SKILL.md", "action": "MODIFY"},
    {"path": ".agents/skills/sdd-proposal/SKILL.md", "action": "MODIFY"},
    {"path": ".agents/skills/sdd-spec/SKILL.md", "action": "MODIFY"},
    {"path": ".agents/skills/sdd-start/SKILL.md", "action": "MODIFY"},
    {"path": ".agents/skills/sdd-status/SKILL.md", "action": "MODIFY"},
    {"path": ".agents/skills/sdd-task/SKILL.md", "action": "MODIFY"},
    {"path": ".agents/skills/sdd-tojira/SKILL.md", "action": "MODIFY"},
    {"path": "packages/ai-parrot/src/parrot/sdd/_assets/agents/skills/remove-worktree/SKILL.md", "action": "MODIFY"},
    {"path": "packages/ai-parrot/src/parrot/sdd/_assets/agents/skills/sdd-brainstorm/SKILL.md", "action": "MODIFY"},
    {"path": "packages/ai-parrot/src/parrot/sdd/_assets/agents/skills/sdd-brief/SKILL.md", "action": "MODIFY"},
    {"path": "packages/ai-parrot/src/parrot/sdd/_assets/agents/skills/sdd-codereview/SKILL.md", "action": "MODIFY"},
    {"path": "packages/ai-parrot/src/parrot/sdd/_assets/agents/skills/sdd-done/SKILL.md", "action": "MODIFY"},
    {"path": "packages/ai-parrot/src/parrot/sdd/_assets/agents/skills/sdd-explain/SKILL.md", "action": "MODIFY"},
    {"path": "packages/ai-parrot/src/parrot/sdd/_assets/agents/skills/sdd-fix/SKILL.md", "action": "MODIFY"},
    {"path": "packages/ai-parrot/src/parrot/sdd/_assets/agents/skills/sdd-fromjira/SKILL.md", "action": "MODIFY"},
    {"path": "packages/ai-parrot/src/parrot/sdd/_assets/agents/skills/sdd-next/SKILL.md", "action": "MODIFY"},
    {"path": "packages/ai-parrot/src/parrot/sdd/_assets/agents/skills/sdd-proposal/SKILL.md", "action": "MODIFY"},
    {"path": "packages/ai-parrot/src/parrot/sdd/_assets/agents/skills/sdd-spec/SKILL.md", "action": "MODIFY"},
    {"path": "packages/ai-parrot/src/parrot/sdd/_assets/agents/skills/sdd-start/SKILL.md", "action": "MODIFY"},
    {"path": "packages/ai-parrot/src/parrot/sdd/_assets/agents/skills/sdd-status/SKILL.md", "action": "MODIFY"},
    {"path": "packages/ai-parrot/src/parrot/sdd/_assets/agents/skills/sdd-task/SKILL.md", "action": "MODIFY"},
    {"path": "packages/ai-parrot/src/parrot/sdd/_assets/agents/skills/sdd-tojira/SKILL.md", "action": "MODIFY"},
    {"path": "packages/ai-parrot/tests/sdd/test_installer.py", "action": "MODIFY"}
  ],
  "contract_symbols": []
}
```

---

## Implementation Blueprint

### Steps (in order)
1. Rewrite the two header lines in the 15 skills with one literal replacement each (Python script or `sed` with
   fixed strings) — *why*: the anchors occur exactly once per file; a mechanical edit avoids drift between skills.
2. Insert the new header block into `sdd-fix` above `## Usage` — *why*: it has no adaptation header today.
3. Regenerate the packaged copies (`check_asset_sync.py --write`) — *why*: byte parity is a CI gate.
4. Write the tests.

### The 15 skills (MODIFY) — replace exactly these two lines
```markdown
<!-- occurrences per file: 1 (verified: grep -c '^## Full procedure and Codex adaptations' <file>) -->
## Full procedure and host adaptations
<!-- occurrences per file: 1 (verified: grep -c 'and the \[Codex adaptation contract\](../../../docs/sdd/CODEX.md#codex-adaptation-contract).' <file>) -->
and your host's adaptation contract: the [Codex adaptation contract](../../../docs/sdd/CODEX.md#codex-adaptation-contract)
on Codex, or the [Antigravity adaptation contract](../../../docs/sdd/AGY.md#antigravity-adaptation-contract) on Google Antigravity (`agy`).
```

### `.agents/skills/sdd-fix/SKILL.md` (MODIFY)
```markdown
<!-- occurrences: 1 (verified: grep -c '^## Usage' .agents/skills/sdd-fix/SKILL.md) — line 18 -->
<!-- BEFORE — insert above `## Usage`: -->
## Full procedure and host adaptations

Before executing, read the [full sdd-fix procedure](../../../.claude/commands/sdd-fix.md)
and your host's adaptation contract: the [Codex adaptation contract](../../../docs/sdd/CODEX.md#codex-adaptation-contract)
on Codex, or the [Antigravity adaptation contract](../../../docs/sdd/AGY.md#antigravity-adaptation-contract) on Google Antigravity (`agy`).

<!-- FILL IN: confirm `.claude/commands/sdd-fix.md` ships for codex/google (manifest `.claude/commands/sdd-*.md` glob)
     so the link check passes — bounded by test_non_claude_host_skills_have_every_file_they_read. -->
```

### `packages/ai-parrot/tests/sdd/test_installer.py` (MODIFY)
```python
# AFTER — append at end of file
_CODEX_LINK = "../../../docs/sdd/CODEX.md#codex-adaptation-contract"
_AGY_LINK = "../../../docs/sdd/AGY.md#antigravity-adaptation-contract"


@pytest.mark.parametrize("host", ["codex", "google"])
def test_shared_skill_headers_name_both_host_contracts(empty_repo: Path, host: str) -> None:
    install_sdd_integration(empty_repo, hosts=(host,))
    skills = sorted((empty_repo / ".agents/skills").glob("*/SKILL.md"))
    assert skills
    for skill in skills:
        text = skill.read_text(encoding="utf-8")
        assert _CODEX_LINK in text and _AGY_LINK in text, skill


# FILL IN tests:
#  - packaged skill copies match the repo: for every manifest entry whose target starts with ".agents/skills/",
#    bytes of _assets/<source> == bytes of <repo>/<target>
#  - fresh-shell rule: no line of any repo .agents/skills/*/SKILL.md uses "$WT" without assigning "WT=" on that line
```

### FILL IN checklist
- [ ] `sdd-fix` link target confirmation
- [ ] remaining tests

---

## Acceptance Criteria

- [ ] All 16 repo skills (and the 15 packaged ones) link both the Codex and the Antigravity contract; Codex keeps its contract.
- [ ] `test_non_claude_host_skills_have_every_file_they_read` passes for codex and google.
- [ ] Packaged skills are byte-identical to the repo; no skill relies on a previous shell's `WT`/`cd`.

---

## Validation Commands

- `pytest packages/ai-parrot/tests/sdd/test_installer.py -q`
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
9. **Close the task** with `parrot sdd task close TASK-5359 sdd-agy-compatibility verified`
10. **Fill in the Completion Note** below, then commit the staged SDD state

---

## Completion Note

**Completed by**: sdd-worker orchestrator; seat mistral (nova), 1 attempt
**Date**: 2026-11-09
**Notes**: Host-aware adaptation-contract headers on the shared skills, packaged copies regenerated, tests added. Not line-by-line reviewed beyond validation. Merge-tier validation green (102 passed).

**Deviations from spec**: none
