# TASK-5136: Document `--stalled` / `--keep` and `parrot sdd worktree list|remove`

**Feature**: FEAT-795 — `parrot sdd uninstall --stalled` — remove stale and hand-copied SDD files
**Spec**: `sdd/specs/parrot-sdd-install-remove.spec.md`
**Status**: pending
**Priority**: medium
**Estimated effort**: S (< 2h)
**Depends-on**: TASK-5135
**Assigned-to**: unassigned

---

## Context

Spec §3 Module 4 and §7 Known Risks (CI still calling `scripts/sdd/*`, team-made `sdd-*` commands). The
"SDD flow in any repository" section of `docs/install/global-runtime.md` is verified by
`packages/ai-parrot/tests/docs/test_getting_started_claims.py`: every `<!-- verify: flag=… -->` and
`<!-- verify: cli-verb=… -->` marker must resolve against the real CLI, so this task runs after the flags exist
(TASK-5135, which itself follows TASK-5133's `worktree list|remove`).

---

## Scope

- In `docs/install/global-runtime.md` § "The SDD flow in any repository":
  - add `<!-- verify: flag=sdd uninstall:--stalled -->`, `<!-- verify: flag=sdd uninstall:--keep -->`,
    `<!-- verify: cli-verb=sdd worktree list -->` and `<!-- verify: cli-verb=sdd worktree remove -->` right after
    the `<!-- verify: flag=sdd uninstall:--dry-run -->` marker;
  - add `parrot sdd uninstall --stalled --dry-run` to the example block after `parrot sdd uninstall --dry-run`;
  - add a short subsection "Cleaning up stale SDD files" covering: the three file reasons (`receipt-orphan`,
    `retired`, `sdd-orphan`) and the four MCP reasons (`retired-toolkit`, `undeclared`, `foreign-repo`,
    `missing-repo`); all hosts by default, `--host` narrows; `--keep GLOB` and the `<file>#<key>` form for MCP
    entries; `--dry-run` first; the `install` note and `status` lines; the source-checkout refusal (files only);
    the `sdd-` prefix being parrot-owned (team `sdd-*` commands are removed unless `--keep`); CI that still runs
    `scripts/sdd/<x>.py` must switch to `parrot sdd <noun> <verb>` (or `--keep 'scripts/sdd/<file>'`); the global
    Gemini file is shared, so only `retired-toolkit`/`missing-repo` apply there; re-register with
    `parrot toolkits install <name>`.
  - one paragraph on `/remove-worktree` = `parrot sdd worktree list|remove`, now shipped to all three hosts.

**NOT in scope**: any code; other docs files; `docs/sdd/WORKFLOW.md` (already lists `/remove-worktree`).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `docs/install/global-runtime.md` | MODIFY | Markers, example line, cleanup subsection |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
None (documentation).

### Existing Signatures to Use
```text
docs/install/global-runtime.md
  line 207: "## The SDD flow in any repository"
  line 215: <!-- verify: flag=sdd uninstall:--dry-run -->      (occurrences: 1)
  line 224: parrot sdd uninstall --dry-run                       (last line of the example block)
packages/ai-parrot/tests/docs/test_getting_started_claims.py
  GLOBAL_RUNTIME = REPO_ROOT / "docs" / "install" / "global-runtime.md"   # line 199
  test_cited_cli_verbs_exist (line 237) — `cli-verb=<group sub …>` walks the real lazy CLI
  test_cited_flags_exist (line 245)     — `flag=<verb>:<--flag>` must be one of that command's option strings
```
Options added by TASK-5135: `--stalled` (secondary `--stale`), `--keep`. Verbs added by TASK-5133:
`parrot sdd worktree list`, `parrot sdd worktree remove`.

### Does NOT Exist
- ~~`parrot sdd clean`~~, ~~`parrot sdd stale`~~ — not commands; cite only `parrot sdd uninstall --stalled`.
- ~~a `--gemini-config` option~~ — not exposed on the CLI.

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {"path": "docs/install/global-runtime.md", "action": "MODIFY"}
  ],
  "contract_symbols": []
}
```

---

## Implementation Notes

### Key Constraints
- Plain, short sentences; no marketing. Match the surrounding section's style (bullets, backticked commands).
- Every command the text cites must exist; add a `verify:` marker for each new verb/flag you name.

---

## Implementation Blueprint

### Steps (in order)
1. Add the four markers after line 215 — *why*: the docs test verifies them against the CLI.
2. Add the example line after `parrot sdd uninstall --dry-run` — *why*: spec M4.
3. Write the subsection after the bullet list that follows the example block — *why*: spec §7 risks must be documented.

### `docs/install/global-runtime.md` (MODIFY)
```markdown
<!-- occurrences: 1 (verified: grep -c '<!-- verify: flag=sdd uninstall:--dry-run -->' docs/install/global-runtime.md) -->
<!-- AFTER line 215: -->
<!-- verify: flag=sdd uninstall:--stalled -->
<!-- verify: flag=sdd uninstall:--keep -->
<!-- verify: cli-verb=sdd worktree list -->
<!-- verify: cli-verb=sdd worktree remove -->

<!-- AFTER `parrot sdd uninstall --dry-run` inside the bash block (line 224): -->
parrot sdd uninstall --stalled --dry-run    # stale files + stale MCP entries, all hosts

### Cleaning up stale SDD files

<!-- FILL IN: the subsection per Scope — reasons tables or bullets, --keep forms, risks, /remove-worktree paragraph. -->
```

### FILL IN checklist
- [ ] subsection text covering every Scope bullet.

---

## Acceptance Criteria

- [ ] AC-1: the four new `verify:` markers resolve (`test_cited_flags_exist`, `test_cited_cli_verbs_exist` pass).
- [ ] AC-2: the doc names all seven reasons, `--keep` (both forms), the source-checkout refusal, the CI risk and
      the `parrot toolkits install` re-registration.

---

## Validation Commands

- `pytest packages/ai-parrot/tests/docs/test_getting_started_claims.py -q`

---

## Test Specification

No new tests; the existing docs-claims harness verifies the markers.

---

## Agent Instructions

When you pick up this task:

1. **Work in the feature worktree** — never on `base_branch`
   (`parrot sdd worktree ensure --slug parrot-sdd-install-remove --feature-id FEAT-795`)
2. **Read the spec** at the path listed above for full context
3. **Check dependencies** — every `Depends-on` task must be `"done"` in `sdd/tasks/index/parrot-sdd-install-remove.json`
4. **Verify the Codebase Contract** before writing any code; fix the contract first if anything moved
5. **Update status** in the per-spec index → `"in-progress"` (set `started_at`) and commit only that index file
6. **Implement** from the blueprint; complete every `# FILL IN:`; never change a signature or path it fixes
7. **Verify** — run the Validation Commands with `PYTHONPATH=packages/ai-parrot/src`
8. **Commit the code** — stage only the files this task lists
9. **Close the task** with `parrot sdd task close TASK-5136 parrot-sdd-install-remove verified`
10. **Fill in the Completion Note**, then commit the staged SDD state

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**: <session or agent ID>
**Date**: YYYY-MM-DD
**Notes**:

**Deviations from spec**: none
