# TASK-4576: Documentation: inbox watch mode and FirefliesInsightsAgent guide

**Feature**: FEAT-715 — FirefliesInsightsAgent
**Spec**: `sdd/specs/fireflies-insights-agent.spec.md`
**Status**: pending
**Priority**: medium
**Estimated effort**: S (< 2h)
**Depends-on**: TASK-4567, TASK-4574
**Assigned-to**: unassigned

---

## Context

Spec §3 **Module 8**, **AC21**. Two operator-facing facts are easy to get wrong and must
be written down: (1) `--watch` needs the `filesystem-transport-full` extra (§8 Q1 route a);
(2) `InboxConfig.stage_git` defaults to `True`, chosen for occasional manual runs — under a
long-running watcher it keeps `git add`-ing into the wiki project's repo, and the watcher
deliberately never overrides it (C15). Operators who do not want that set it `false`.

---

## Scope

- `docs/wiki/inbox.md`: insert a `## Watch mode` section **before** `## Exit codes and concurrency`,
  covering: install (`ai-parrot[filesystem-transport-full]`), `wikitoolkit inbox --watch`,
  incompatibility with `--limit` / `--dry-run`, the stability window
  (`inbox.stability_window` / `inbox.stability_poll_interval`, whole-inbox rule: a run
  starts only when every candidate is stable), dot-prefixed temp files are ignored, the
  `stage_git` caveat (AC21), and that Ctrl-C drains the in-flight run.
- `docs/agents/fireflies-insights.md`: create the guide — what the agent does; configuration (`fireflies_token` /
  `FIREFLIES_API_KEY`, `wiki_root`, `public_channel_id`, `jira_project`,
  `jira_templates_dir`, `FIREFLIES_REGISTRY_DIR`); commands `/fireflies_sync [N]` and
  `/fireflies_ticket <id>`; approval TTL 72 h and chat-only authorization; skills in
  `agents/fireflies_insights/skills/`; the ten-key Jira template contract; and why
  ingestion and insights are independent.

**NOT in scope**: code; README changes elsewhere.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `docs/wiki/inbox.md` | MODIFY | Add a `## Watch mode` section incl. the `stage_git` caveat and the extra |
| `docs/agents/fireflies-insights.md` | CREATE | Operator guide for FirefliesInsightsAgent |

---

## Codebase Contract (Anti-Hallucination)

### Existing Signatures to Use
```text
docs/wiki/inbox.md:228   ## Exit codes and concurrency    (occurrences: 1)
docs/wiki/inbox.md:90    ## Configuration                 (existing section — link to it, do not duplicate it)
```

### Does NOT Exist
- ~~`docs/agents/`~~ — the directory does not exist yet; this task creates it with `docs/agents/fireflies-insights.md`.
- ~~a `wikitoolkit watch` command~~ — it is `wikitoolkit inbox --watch`.

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {
      "path": "docs/wiki/inbox.md",
      "action": "MODIFY"
    },
    {
      "path": "docs/agents/fireflies-insights.md",
      "action": "CREATE"
    }
  ],
  "contract_symbols": []
}
```

---

## Implementation Blueprint

### Steps (in order)
1. Insert the section in `docs/wiki/inbox.md` — *why*: AC21.
2. Write `docs/agents/fireflies-insights.md` — *why*: the only operator entry point for the agent.

### `docs/wiki/inbox.md` (MODIFY)
```markdown
<!-- occurrences: 1 (verified: grep -cF '## Exit codes and concurrency' docs/wiki/inbox.md) -->
<!-- BEFORE — insert directly above `## Exit codes and concurrency` (verified: docs/wiki/inbox.md:228) -->
## Watch mode

<!-- FILL IN: the bullets from Scope, in prose; include a fenced example:
       uv pip install "ai-parrot[filesystem-transport-full]"
       wikitoolkit inbox --watch
     and a > **Warning** callout for stage_git (AC21). -->
```

### `docs/agents/fireflies-insights.md` (CREATE)
```markdown
# FirefliesInsightsAgent

<!-- FILL IN: the sections from Scope. Cite the real names only: FirefliesInsightsAgent,
     sync_meetings, /fireflies_sync, /fireflies_ticket, fireflies/action_item. -->
```

### FILL IN checklist
- [ ] `## Watch mode` section with the `stage_git` warning.
- [ ] the agent guide.

---

## Acceptance Criteria

- [ ] **AC21** `docs/wiki/inbox.md` documents `--watch`, the extra, and the `stage_git` caveat.
- [ ] `docs/agents/fireflies-insights.md` documents configuration, both commands, the TTL and the template contract.
- [ ] Every command, setting and file name in the docs exists in the code as merged.

---

## Validation Commands

> File-level pytest only — no directories, no package roots. Docs have no unit tests;
> the gate is the CLI test that exercises the documented flag.

- `pytest packages/ai-parrot/tests/knowledge/wiki/inbox/test_cli_inbox.py -q`

---

## Test Specification

Docs task — validated by the CLI test above and by review against the merged code.

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
   `feat(fireflies-insights-agent): TASK-4576 — <title>`.
9. **Close** with `scripts/sdd/close_task.sh TASK-4576 fireflies-insights-agent verified` — never move
   the file by hand.
10. **Fill in the Completion Note** below, then commit the staged SDD state.

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**: <session or agent ID>
**Date**: YYYY-MM-DD
**Notes**: What was implemented, any deviations from scope, issues encountered.

**Deviations from spec**: none | describe if any
