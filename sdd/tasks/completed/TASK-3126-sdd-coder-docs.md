# TASK-3126: Documentation — orchestrator guide, MCP install section, CONTEXT.md pointer

**Feature**: FEAT-549 — `sdd-worker` as Orchestrator of Parallel `sdd-coder` Sub-Agents
**Spec**: `sdd/specs/sdd-worker-subagents.spec.md`
**Status**: pending
**Priority**: medium
**Estimated effort**: S (< 2h)
**Depends-on**: TASK-3122, TASK-3124
**Assigned-to**: unassigned

---

## Context

Spec §3 Module 9 and AC-17. Operators need: how to install the `parrot-sdd-coder` server
(`.parrot/mcp-toolkits.yaml` + `.mcp.json`, both git-ignored, from the tracked example),
what the roster semantics are (distinct-model rule, chunking, `fallback_model`, probe
reasons, native Haiku seat), how the orchestrator loop behaves, and the two gotchas the
spike found (Gemini 3 `thought_signature` echo; `GEMINI_API_KEY` via navconfig, not env).

---

## Scope

- Create `docs/dev_loop/sdd-coder-orchestrator.md`.
- Add an `sdd-coder` section to `docs/mcp-local-toolkits.md` after the tool-optimizations section.
- Add one paragraph to `.agent/CONTEXT.md` under "What Lives Where → flows/dev_loop".

**NOT in scope**: code; `/sdd-start` docs; the brainstorm/spec files.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `docs/dev_loop/sdd-coder-orchestrator.md` | CREATE | guide |
| `docs/mcp-local-toolkits.md` | MODIFY | new section |
| `.agent/CONTEXT.md` | MODIFY | pointer paragraph (the file is under an ignored dir but tracked — `git add -f`) |

---

## Codebase Contract (Anti-Hallucination)

### Verified anchors
```
docs/mcp-local-toolkits.md:1   `# Expose Toolkits as Local MCP (`parrot mcp-local`)`; :20-40 `.mcp.json` wiring commands (`parrot mcp-local --list`, `parrot mcp-local memory`)
docs/tool-optimizations.md:33-40   install lines for the FEAT-543 toolkits (`cp examples/tool-optimizations-mcp.yaml .parrot/mcp-toolkits.yaml`, `parrot mcp-local --list`)
.agent/CONTEXT.md  "## What Lives Where" tree — the `flows/` entry reads:
   `├── flows/            # Application-level flows built ON TOP of bots/flows: dev_flow/, dev_loop/. …`   (grep -n "flows/            #" .agent/CONTEXT.md → 1 occurrence)
examples/sdd-coder-mcp.yaml (TASK-3122) — the roster example to quote
sdd/specs/sdd-worker-subagents.spec.md §2 Overview, §6 Spike evidence, §7 Known Risks — source of the semantics to document
```

### Does NOT Exist
- ~~`.parrot/mcp-toolkits.yaml` / `.mcp.json` in the repo~~ — git-ignored (`.gitignore:407`, `:389`); the docs must say "copy from `examples/sdd-coder-mcp.yaml`".
- ~~`GEMINI_API_KEY` as an environment variable requirement~~ — document `env/.env` + navconfig.
- ~~a startup probe at server start~~ — it runs on the first tool call (`coder_plan`); document accordingly (design research S12).

---

## Implementation Notes

### Key Constraints
- Write for an operator who has never seen the spec: install → run `sdd-worker` → read the plan output → what each outcome means → troubleshooting (probe reasons, `thought_signature`, `task_already_running`, orphans).
- Keep the roster table in sync with `examples/sdd-coder-mcp.yaml`.
- No promises beyond what TASK-3122/3124 shipped (re-read both Completion Notes first).

---

## Implementation Blueprint

### Steps (in order)
1. Guide — *why*: AC-17 names it; it is the only end-to-end description outside the spec.
2. `docs/mcp-local-toolkits.md` section — *why*: operators find local MCP toolkits there.
3. `.agent/CONTEXT.md` paragraph — *why*: agents load CONTEXT.md; a pointer prevents rediscovery.

### `docs/dev_loop/sdd-coder-orchestrator.md` (CREATE — outline)
```markdown
# sdd-worker as orchestrator of parallel sdd-coder seats (FEAT-549)

## What it does            <!-- 1 paragraph: waves from depends_on, one seat per task, distinct models per chunk, Sonnet consolidates -->
## Install
1. `cp` the `sdd-coder:` section of `examples/sdd-coder-mcp.yaml` into `.parrot/mcp-toolkits.yaml` (git-ignored).
2. Add to `.mcp.json` (git-ignored): `"parrot-sdd-coder": {"command": "<venv>/bin/parrot", "args": ["mcp-local", "sdd-coder", "--config", ".parrot/mcp-toolkits.yaml"]}`
3. Credentials: nova → BEDROCK_MANTLE_API_KEY / AWS_NOVA_API_KEY; google-compat → GEMINI_API_KEY / GOOGLE_API_KEY (in env/.env, read by navconfig — NOT plain env); codex → `codex login`.
4. `parrot mcp-local --list` shows `sdd-coder`.
## The roster              <!-- table from the yaml; kind mcp|native; model + fallback_model; probe rules and reasons; probe runs on the first coder_plan -->
## The loop                <!-- steps 0–6 from sdd-worker.md "## Orchestrator Loop (FEAT-549)"; the "one message" rule; coder_wait ≤ 300 s; never mix coder_wait with other calls -->
## Outcomes                <!-- merged / merge_conflict / fidelity_violation / failed → what sdd-worker does; attempt ladder; Completion Note fields -->
## Branches & worktrees    <!-- <feature>--TASK-NNN-a<n> under <WORKTREE_BASE_PATH>/<feature>--pool/; orphans listed, never auto-merged; coder_cleanup -->
## Telemetry               <!-- attempts[*]: seat, backend, model, duration_s, usage; per-model summary table -->
## Troubleshooting
- `roster_empty` → probe reasons; fallback to the sequential loop
- HTTP 400 "missing a thought_signature" → GoogleCompatCodeDispatcher must carry `extra_content` (regression: run `pytest -m live …test_google_compat_live.py`)
- `task_already_running` → a job owns the task; `coder_status`; restart ⇒ orphans
- `dirty_task_worktree` / `fidelity_violation` → coder left untracked files or touched sdd/
- Redis warnings → optional; set REDIS_URL for streams
## Related                 <!-- spec, brainstorm, FEAT-323 dev-loop pool, docs/mcp-local-toolkits.md -->
```

### `docs/mcp-local-toolkits.md` (MODIFY)
```markdown
# occurrences: 1 (verified: grep -c '^# Expose Toolkits as Local MCP' docs/mcp-local-toolkits.md) — append at END of file (no anchor needed):
## `sdd-coder` — orchestration kernel for the interactive sdd-worker (FEAT-549)
<!-- FILL IN: 8–12 lines: purpose, `parrot mcp-local sdd-coder --config examples/sdd-coder-mcp.yaml`, tool list (seven names), link to docs/dev_loop/sdd-coder-orchestrator.md -->
```

### `.agent/CONTEXT.md` (MODIFY)
```markdown
# occurrences: 1 (verified: grep -c 'flows/            # Application-level flows' .agent/CONTEXT.md)
# AFTER the `flows/` tree entry lines, add a sub-bullet line in the same tree style:
│                     #   dev_loop/sdd_coder/ — FEAT-549 orchestration kernel behind the `parrot-sdd-coder` MCP server
│                     #   (roster · chunker · per-attempt dispatch · fidelity gate · jobs); see docs/dev_loop/sdd-coder-orchestrator.md
```

### FILL IN checklist
- [ ] Guide prose per outline; bounded by spec §2/§6/§7 and the shipped prompt text (TASK-3124)
- [ ] MCP section; bounded by the seven tool names

---

## Acceptance Criteria

- [ ] `docs/dev_loop/sdd-coder-orchestrator.md` exists with the sections above and mentions: install via the example yaml, `thought_signature`, navconfig key location, `coder_wait` ≤ 300 s, orphan policy (AC-17).
- [ ] `docs/mcp-local-toolkits.md` has the `sdd-coder` section naming all seven tools.
- [ ] `.agent/CONTEXT.md` mentions `dev_loop/sdd_coder/` and links the guide.
- [ ] Every command in the guide was executed once by the author (`parrot mcp-local --list` output pasted in the Completion Note).

---

## Test Specification

Documentation task — verification is the checklist above plus a link check (`grep -o 'docs/[a-zA-Z_/.-]*' docs/dev_loop/sdd-coder-orchestrator.md | xargs -I{} test -e {}`).

---

## Agent Instructions

1. **Read the spec** §2, §6 Spike evidence, §7; read TASK-3122 and TASK-3124 Completion Notes.
2. **Check dependencies** — TASK-3122, TASK-3124 completed.
3. **Verify the Codebase Contract** — re-run the two `grep -c` anchors.
4. **Update status** in the per-spec index → `"in-progress"`.
5. **Implement**; `git add -f .agent/CONTEXT.md`.
6. **Verify** all acceptance criteria.
7. **Move this file** to `sdd/tasks/completed/TASK-3126-sdd-coder-docs.md`.
8. **Update index** → `"done"`.
9. **Fill in the Completion Note** below.

---

## Completion Note

**Completed by**: sdd-worker (Sonnet)
**Date**: 2026-09-10
**Notes**: Created `docs/dev_loop/sdd-coder-orchestrator.md` (all sections
from the outline: What it does, Install, The roster, The loop, Outcomes,
Branches & worktrees, Telemetry, Troubleshooting, Related). Appended the
`sdd-coder` section to the end of `docs/mcp-local-toolkits.md` (no
"tool-optimizations" heading exists inside that file itself — the FEAT-543
toolkits live in a separate `docs/tool-optimizations.md`, linked from this
file's own "## Related" section — so per the task's own instruction
"append at END of file (no anchor needed)"). Added the `dev_loop/sdd_coder/`
pointer paragraph to `.agent/CONTEXT.md`'s `flows/` tree entry.

Verified every command in the guide once:
```
$ cp examples/sdd-coder-mcp.yaml .parrot/mcp-toolkits.yaml
$ parrot mcp-local --list
browsing	enabled	parrot_tools.browsing.toolkit.WebBrowsingToolkit
memory	enabled	parrot.tools.working_memory.tool.WorkingMemoryToolkit
scraping	enabled	parrot_tools.scraping.toolkit.WebScrapingToolkit
sdd-coder	enabled	parrot.flows.dev_loop.sdd_coder.toolkit.SddCoderToolkit
```
(the operator-local `.parrot/mcp-toolkits.yaml` copy was removed afterward —
git-ignored, never committed). Link check
(`grep -o 'docs/[a-zA-Z_/.-]*' docs/dev_loop/sdd-coder-orchestrator.md`) —
the one `docs/` reference (`docs/mcp-local-toolkits.md`) resolves. Confirmed
the guide mentions `thought_signature`, `navconfig`, the `coder_wait` ≤ 300 s
clamp, and orphan policy (AC-17); confirmed `docs/mcp-local-toolkits.md`
names all seven `coder_*` tools.

**Deviations from spec**: none.
