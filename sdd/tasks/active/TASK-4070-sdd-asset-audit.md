# TASK-4070: Spike S5: SDD asset assumption audit scanner (parrot.sdd.audit)

**Feature**: FEAT-633 — Parrot Bootstrap Installer
**Spec**: `sdd/specs/parrot-installer.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: none
**Assigned-to**: unassigned

---

## Context

Spec §3 Module 0 defines spike **S5**, an SDD portability dry-run that produces the
assumption inventory for the markdown rewrite. Spec §3 Module 6 says it is "partial"
because "markdown rewrite needs spike S5's assumption inventory". Spec §9 S9 (CONFIRM)
adds: "Audit installed commands for shell/jq/non-Windows assumptions; installer reports
unavailable tooling". That part is folded into S5 here and into M6's install-time report.

This task turns S5 into a **reusable, stdlib-only scanner**, `parrot.sdd.audit`, instead
of a one-off grep. Three consumers use it:

1. **This task** runs it over the SDD markdown/hook assets and commits the inventory to
   `sdd/state/FEAT-633/spikes/S5-sdd-assumptions.md`.
2. **TASK-4089** (markdown rewrite) uses the report's "Helper reference map" as its
   rewrite list. Every `scripts/sdd/<name>` / `scripts.sdd.<name>` becomes
   `parrot sdd run <name>` (rev 0.2 Q1).
3. **TASK-4091** (`parrot sdd install`) imports `scan_paths` + `missing_tools` at install
   time to warn about tooling the target machine lacks (`jq`, `gh`, `tmux`, …).
4. **TASK-4090** (asset packaging, C11c) runs the scanner over `parrot/sdd/_assets/` in CI
   with `--fail-on org-data,claude-md-ref,branch-literal`, so no organisation data,
   `CLAUDE.md` reference or hardcoded flow branch ever reaches the public wheel.

The task also creates the `parrot.sdd` package root (`__init__.py`, docstring only) that
TASK-4085/4088 build `parrot.sdd.scripts` under, and the `packages/ai-parrot/tests/sdd/`
test package (brief: `tests/sdd/` ownership belongs to this task).

**Pre-seeded reference map.** Re-verified 2026-10-19 on dev `9f51c7735` with
`grep -oE 'scripts[./]sdd[./][A-Za-z_][A-Za-z0-9_]*'` over every file of `DEFAULT_GLOBS`. The
generated report must reproduce it (it is the scanner's acceptance oracle). Helpers marked
¹ are moved by TASK-4508 (move D):

| Asset | Helpers referenced |
|---|---|
| `.claude/commands/sdd-done.md` | check_e2e_closeout¹, check_task_state, close_resolved_issues¹, close_task, heal_orphans, sdd_meta, select_tests, test_report¹ |
| `.claude/commands/sdd-fix.md` | ensure_worktree, reserve_ids |
| `.claude/commands/sdd-insight.md` — not shipped (C22) | insight (invoked as `python3 scripts/sdd/insight.py`, lines 51/85) |
| `.claude/commands/sdd-next.md`, `sdd-status.md` | doc_taxonomy, worktree_status |
| `.claude/commands/sdd-spec.md` | reserve_ids, sdd_meta, spec_tools |
| `.claude/commands/sdd-start.md` | close_task, ensure_worktree, finalize_task, sdd_meta |
| `.claude/commands/sdd-task.md` | cache_test_contract¹, check_task_graph, reserve_ids, sdd_meta |
| `.claude/commands/sdd-brief.md` *(rev 0.4 C17 — FEAT-698)* | brief_meta, check_task_graph, ensure_worktree |
| `.claude/commands/sdd-brainstorm.md`, `sdd-proposal.md`, `sdd-tojira.md` | sdd_meta *(not in the original brief map — found by the verification grep)* |
| `.claude/commands/sdd-codereview.md`, `sdd-explain.md`, `sdd-fromjira.md` | none |
| `.claude/agents/sdd-autopilot.md` | ensure_worktree, select_tests |
| `.claude/agents/sdd-ideation.md` | sdd_meta |
| `.claude/agents/sdd-planner.md` | ensure_worktree, sdd_meta |
| `.claude/agents/sdd-research.md` | ensure_worktree |
| `.claude/agents/sdd-worker.md` | close_task, ensure_worktree, finalize_task, review_checkpoint, sdd_meta, select_tests |
| `.claude/agents/sdd-coder.md`, `sdd-feedback.md`, `sdd-qa.md`, `sdd-secondopinion.md` | none |
| `.claude/rules/worktree-management.md` | ensure_worktree, sdd_meta |
| `.claude/rules/codebase-conventions.md`, `.claude/hooks/sdd-worker-format.sh` | none |
| `sdd/templates/intake.procedure.md` | reserve_ids |
| `sdd/templates/task.md` | close_task, ensure_worktree |
| `sdd/templates/*` (the other 11) | none |
| `sdd/WORKFLOW.md` | backfill_taxonomy, check_id_collisions, close_task, doc_taxonomy, ensure_worktree, id_ledger, install_hooks, migrate_index, reserve_ids |

*(rev 0.5 C24)* Codex/Google twins, same grep, re-verified 2026-10-20 on `db7277048` (dev `0263f0724` +
spec rev 0.5). They differ from their `.claude/` sources until TASK-4089 rewrites them:

| Asset | Helpers referenced |
|---|---|
| `.agents/skills/sdd-done/SKILL.md` | check_e2e_closeout¹, close_resolved_issues¹, close_task, heal_orphans, sdd_meta, select_tests, test_report¹ |
| `.agent/workflows/sdd-done.md` | check_task_state, close_resolved_issues¹, close_task, heal_orphans, sdd_meta, select_tests, test_report¹ |
| `.agents/skills/sdd-task/SKILL.md`, `.agent/workflows/sdd-task.md` | cache_test_contract¹, check_task_graph, reserve_ids, sdd_meta |
| `.agents/skills/sdd-spec/SKILL.md` | reserve_ids, sdd_meta |
| `.agent/workflows/sdd-spec.md` | reserve_ids, sdd_meta, spec_tools |
| `.agents/skills/sdd-start/SKILL.md` | ensure_worktree, finalize_task |
| `.agent/workflows/sdd-start.md` | close_task, ensure_worktree, finalize_task, sdd_meta |
| `.agents/skills/sdd-brief/SKILL.md` *(no Google twin yet — TASK-4089)* | brief_meta, check_task_graph, ensure_worktree |
| `.agents/skills/sdd-fix/SKILL.md`, `.agent/workflows/sdd-fix.md` | ensure_worktree, reserve_ids |
| `.agents/skills/sdd-{next,status}/SKILL.md`, `.agent/workflows/sdd-{next,status}.md` | doc_taxonomy, worktree_status |
| `.agents/skills/sdd-insight/SKILL.md`, `.agent/workflows/sdd-insight.md` — not shipped (C22) | insight |
| `.agents/skills/sdd-{brainstorm,fromjira,proposal}/SKILL.md`, `.agent/workflows/sdd-{brainstorm,proposal,tojira}.md` | sdd_meta |
| `.agents/skills/sdd-{codereview,explain,tojira}/SKILL.md`, `.agent/workflows/sdd-{codereview,explain,fromjira}.md` | none |
| `.agents/agents/sdd-worker/agent.md` | close_task, ensure_worktree, sdd_meta |
| `.agent/agents/sdd-worker/agent.md` | close_task, ensure_worktree, finalize_task, sdd_meta, select_tests |
| `.agent/agents/sdd-autopilot/agent.md` | select_tests |
| `.agents/agents/sdd-ideation/agent.md`, `.agent/agents/sdd-ideation/agent.md` | sdd_meta |
| `.agents/agents/sdd-research/agent.md`, `.agent/agents/sdd-research/agent.md` | ensure_worktree |
| `.agents/agents/sdd-{autopilot,feedback,planner,qa,secondopinion}/agent.md`, `.agent/agents/sdd-{feedback,planner,qa,secondopinion}/agent.md` | none |

External-tool sample (files containing the token, same asset set): `jq` 9, `gh` 34,
`tmux` 1, `codex` 9, `git-lfs` 0, `source .venv` 3, `.venv/bin` 4, `uv run` 3, `/tmp/` 2,
`packages/ai-parrot` 8, `.claude/worktrees` 9 *(counts from 2026-10-05; not re-counted)*.
Example: `sdd-done.md:184` uses `TASK_FILES=$(jq -r '.tasks[].file' …)`.

Publication-safety sample (C11, verified 2026-10-14 over the TASK-4090 asset set): 11 files
contain `trocglobal.atlassian.net` or a real `NAV-<n>` ticket key; 14 files reference
`CLAUDE.md`. None of the original six kinds detects any of these.

---

## Amendments — spec rev 0.2 (2026-10-14)

Folded in from `sdd/proposals/parrot-installer-amendments.proposal.md` (§3 C11a, §5;
decisions by Jesus Lara, 2026-10-14). Every section below is already edited to match.

- **C11a — three publication-safety finding kinds.** `KINDS` grows from six to **nine**:
  `org-data` (Atlassian hosts other than the placeholder `your-org.atlassian.net`; real
  ticket keys other than the placeholder `PROJ-<n>` and SDD's own `FEAT-`/`TASK-` ids),
  `claude-md-ref` (any `CLAUDE.md` reference, with or without a section anchor) and
  `branch-literal` (`dev` / `staging` / `main` used as a flow base in a git or SDD operator
  position). Each has fixed regexes, documented false-positive exclusions and test fixtures
  for the placeholders.
- **`--fail-on <kind,…>`** on the CLI: exit 1 when any finding of a listed kind exists (CI
  gate for TASK-4090). Default behaviour (report only, exit 0) is unchanged.
- The S5 report's Summary table gains the three rows automatically; its "Conclusions" adds a
  fourth bullet: the org-data / `CLAUDE.md` / branch-literal lines TASK-4089 must rewrite with
  placeholders (`https://your-org.atlassian.net`, `PROJ-123`) and `sdd/config.json` wording.

---

## Amendments — spec rev 0.4 (2026-10-18)

Folded in from `sdd/proposals/parrot-installer-amendments.proposal.md` §3 C17 (decision by
Jesus Lara, 2026-10-18). Every section below is already edited to match.

- **C17 — `/sdd-brief` (FEAT-698) is a shipped asset.** The pre-seeded helper map gains the
  `sdd-brief.md` row (`brief_meta`, `check_task_graph`, `ensure_worktree`; verified on
  `925b0f1a2`: `sdd-brief.md:18,132` ensure_worktree, `:151` brief_meta, `:154`
  check_task_graph), the asset inventory counts 15 commands and 14 templates
  (`sdd/templates/brief.md`), and AC-4 checks the new row. The scanner itself does not
  change — it globs `.claude/commands/sdd-*.md`.

---

## Readiness review — 2026-10-19 (dev 9f51c7735)
- Refreshed against dev 9f51c7735: helper-reference map regenerated over the full
  `DEFAULT_GLOBS` set (agent/rule/template rows added; `sdd-done` gains `check_e2e_closeout`,
  `close_resolved_issues`, `test_report`, `sdd-task` gains `cache_test_contract` — all four
  moved by TASK-4508; `sdd-spec` gains `spec_tools`); templates are 13 (`research_plan.schema.json`
  does not exist — also supersedes the "14 templates" count in the rev 0.4 bullet above);
  anchors `sdd-done.md:172`→`:184`, the `E2E_STATUS … jq` lines are gone (0af88638e),
  `pyproject.toml:960-963`→`:965-968`; move-list wording updated.
- Resolved by spec rev 0.5 (2026-10-20):
  - C24 — S5 also scans `.agents/` and `.agent/`: `DEFAULT_GLOBS` gains `.agents/skills/sdd-*/SKILL.md`,
    `.agents/agents/sdd-*/agent.md`, `.agent/workflows/sdd-*.md` and `.agent/agents/sdd-*/agent.md`;
    the asset inventory, the reference map (twin table) and AC-4 cover them; a test pins the globs.
  - C22 — `/sdd-insight` is not shipped in v1; its rows stay in the map, marked "not shipped (C22)".

---

## Scope

- Create the `parrot.sdd` package root. `__init__.py` holds a module docstring only and
  **no imports**, so `python -m parrot.sdd.scripts.<x>` and `python -m parrot.sdd.audit`
  stay as light as `import parrot` (stdlib + `parrot.version`).
- Implement `parrot/sdd/audit.py`. It is **stdlib-only** and contains:
  - the frozen dataclass `AssumptionFinding`;
  - `scan_text`, `scan_paths`, `missing_tools` and `main`;
  - nine finding kinds: `repo-script`, `venv-path`, `uv-run`, `external-tool`,
    `posix-shell`, `monorepo-path`, and (C11a) `org-data`, `claude-md-ref`, `branch-literal`;
  - a `--fail-on <kind,…>` CLI option that exits 1 when any finding of a listed kind exists
    (TASK-4090's CI gate);
  - a markdown report renderer that includes a per-asset "Helper reference map" and a
    "Rewrite list".
- Generate and commit `sdd/state/FEAT-633/spikes/S5-sdd-assumptions.md` by running the
  scanner over the asset set listed below.
- Create the `packages/ai-parrot/tests/sdd/` package (`__init__.py`) and
  `test_audit.py`.

**NOT in scope**:
- Rewriting any markdown (TASK-4089).
- Moving any `scripts/sdd/*` helper (TASK-4085/4086/4087/4088).
- `parrot sdd install` and its warnings (TASK-4091). This task only exposes the
  functions that task calls.
- `parrot/sdd/cli.py`, `installer.py`, `scripts/`, `_assets/` (other M6 tasks).
- `pyproject.toml` package-data. `[tool.setuptools.packages.find] include = ["parrot*"]`
  (`packages/ai-parrot/pyproject.toml:965-968`, re-verified 2026-10-19) already picks up the
  new `parrot.sdd` package.
- Fixing the org-data / `CLAUDE.md` / branch-literal findings in the markdown (TASK-4089) and
  gating CI on them (TASK-4090). This task only detects and reports them.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/sdd/__init__.py` | CREATE | Package root; docstring only, no imports |
| `packages/ai-parrot/src/parrot/sdd/audit.py` | CREATE | Stdlib-only assumption scanner + markdown report CLI |
| `packages/ai-parrot/tests/sdd/__init__.py` | CREATE | Test package marker (repo convention) |
| `packages/ai-parrot/tests/sdd/test_audit.py` | CREATE | Unit tests for the scanner |
| `sdd/state/FEAT-633/spikes/S5-sdd-assumptions.md` | CREATE | Generated S5 inventory (output of `python -m parrot.sdd.audit`) |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
# stdlib only — this module must never import parrot.* or a third-party package
import argparse, re, shutil, sys
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from pathlib import Path
```

### Existing Signatures to Use
```python
# packages/ai-parrot/pyproject.toml:965-968 (re-verified 2026-10-19) — package discovery already covers parrot.sdd
# [tool.setuptools.packages.find] where = ["src"]; include = ["parrot*"]; namespaces = true

# Publication-safety samples (C11a, verified 2026-10-14 by grep over the TASK-4090 asset set):
#   .claude/commands/sdd-done.md, sdd-fromjira.md, sdd-proposal.md, sdd-tojira.md, sdd/templates/proposal.md,
#   .claude/agents/sdd-autopilot.md …   → `trocglobal.atlassian.net` / `NAV-<n>` (11 files)
#   .claude/skills/second-opinion/SKILL.md:8  "live in `CLAUDE.md` § Adversarial Second Opinion" (claude-md-ref)
#   14 files in the asset set reference `CLAUDE.md`

# Importing `parrot` is cheap: verified 2026-10-05 that `import parrot` loads only
# ['parrot', 'parrot.version'].

# Asset set to scan (all verified to exist 2026-10-05):
#   .claude/commands/sdd-*.md   (15 files: brainstorm, brief [rev 0.4 C17], codereview, done, explain,
#                                fix, fromjira, insight, next, proposal, spec, start, status, task, tojira)
#   .claude/agents/sdd-*.md     (9 files: autopilot, coder, feedback, ideation, planner, qa,
#                                research, secondopinion, worker)
#   .claude/rules/*.md          (codebase-conventions.md, worktree-management.md)
#   .claude/hooks/sdd-worker-format.sh
#   sdd/templates/*             (13 files, re-verified 2026-10-19: brainstorm.md, brief.md [rev 0.4 C17],
#                                design_research.prompt.md, design_research.schema.json, finding.md,
#                                intake.procedure.md, intake.schema.json, proposal.md, research_plan.prompt.md,
#                                spec.md, state.schema.json, synthesis.prompt.md, task.md)
#   sdd/WORKFLOW.md
#   rev 0.5 C24 — the Codex/Google twins (verified 2026-10-20 on db7277048):
#   .agents/skills/sdd-*/SKILL.md     (15: the .claude/commands set, incl. brief and insight)
#   .agents/agents/sdd-*/agent.md     (8: autopilot, feedback, ideation, planner, qa, research, secondopinion, worker)
#   .agent/workflows/sdd-*.md         (14: no sdd-brief.md yet — TASK-4089 creates it)
#   .agent/agents/sdd-*/agent.md      (8: same names as .agents/agents/)
#   /sdd-insight (command + both twins) is not shipped in v1 (C22) but is still scanned.

# Verified sample references (line numbers):
#   .claude/commands/sdd-insight.md:51,85   python3 scripts/sdd/insight.py \
#   .claude/commands/sdd-done.md:184        TASK_FILES=$(jq -r '.tasks[].file' "sdd/tasks/index/<feature-slug>.json");
#   .claude/commands/sdd-done.md:356        STATUS=$(jq -r --arg id "$TASK_ID" '.tasks[] | select(.id == $id) | .status' …)
#   .claude/commands/sdd-done.md:206        GATE_JSON=$(python -m scripts.sdd.check_e2e_closeout \   (TASK-4462, 0af88638e —
#                                            replaced the former E2E_STATUS jq lines)
#   .claude/hooks/sdd-worker-format.sh:1    #!/usr/bin/env bash
```

### Does NOT Exist
- ~~`parrot.sdd` package~~ — created by this task (spec §6 "Does NOT Exist").
- ~~`packages/ai-parrot/tests/sdd/`~~ — created by this task. Note that the repo-root
  `tests/sdd/` (e.g. `tests/sdd/test_close_task_ledger.py`) is a DIFFERENT directory,
  has no `__init__.py`, and is not touched here.
- ~~`sdd/state/FEAT-633/spikes/`~~ — only `sdd/state/FEAT-633/design_research` exists
  today; create the `spikes/` dir (other spike tasks add sibling reports).
- ~~`parrot.sdd.scripts`~~ — TASK-4085 creates it; do NOT create it here.
- ~~`parrot.sdd.installer` / `parrot.sdd.cli`~~ — later M6 tasks.
- ~~a `jq`/`gh` Python binding~~ — tool presence is checked only with `shutil.which`.
- ~~`ORG_HOST_RE`, `TICKET_KEY_RE`, `TICKET_KEY_ALLOW`, `CLAUDE_MD_RE`, `BRANCH_LITERAL_RE`, `--fail-on`~~ —
  new in this task (C11a). No placeholder convention exists in the repo today; `your-org.atlassian.net`
  and `PROJ-<n>` are fixed here and reused by TASK-4089's rewrite.

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {"path": "packages/ai-parrot/src/parrot/sdd/__init__.py", "action": "CREATE"},
    {"path": "packages/ai-parrot/src/parrot/sdd/audit.py", "action": "CREATE"},
    {"path": "packages/ai-parrot/tests/sdd/__init__.py", "action": "CREATE"},
    {"path": "packages/ai-parrot/tests/sdd/test_audit.py", "action": "CREATE"},
    {"path": "sdd/state/FEAT-633/spikes/S5-sdd-assumptions.md", "action": "CREATE"}
  ],
  "contract_symbols": []
}
```

---

## Implementation Notes

### Pattern to Follow
```python
# Stdlib-only, light-import precedent: the launcher (spec §3 M1) and
# packages/ai-parrot/src/parrot/flows/dev_loop/test_scope/ (imported by path, never via
# `import parrot`) — keep audit.py importable with zero parrot/third-party modules loaded.
```

### Key Constraints
- **Stdlib only.** TASK-4091 imports this module from the installer, and the
  `parrot.sdd` package must stay cheap. Add no `logging.basicConfig`. Write CLI output
  with `sys.stdout.write`, never `print()`; diagnostics go to `sys.stderr.write`.
- The scanner is **line-based and deterministic**. Sort findings by
  `(path, line, kind)`. Each line can yield one finding per kind, never duplicates of the
  same kind.
- `path` in a finding is the string the caller passed, made repo-relative where
  possible. The committed report must contain **no absolute paths**, because it is
  committed and must be byte-stable across machines.
- `missing_tools` depends on the machine. The committed report includes it in a clearly
  labelled section whose header names the host OS, but the S5 conclusion must not depend
  on it.
- 120 columns, Google docstrings, strict type hints.

### References in Codebase
- `.claude/commands/sdd-*.md`, `sdd/WORKFLOW.md` — scan targets (see contract).
- `scripts/sdd/` — the helper names the `repo-script` kind resolves (`close_task.sh`,
  `heal_orphans.sh`, `*.py`).

---

## Implementation Blueprint

### Steps (in order)
1. Create `packages/ai-parrot/src/parrot/sdd/__init__.py` with only a docstring. *Why*:
   `python -m parrot.sdd.*` must not pay for imports, and TASK-4085 nests `scripts/`
   under it.
2. Write `audit.py`: dataclass, regex table, `scan_text`, `scan_paths`, `missing_tools`,
   `render_report`, `main`. *Why*: these names are fixed for TASK-4089/4091.
3. Write `tests/sdd/__init__.py` (empty) and `test_audit.py`, then make them pass.
   *Why*: the repo convention requires test packages.
4. From the worktree root, run
   `PYTHONPATH=packages/ai-parrot/src python -m parrot.sdd.audit --root . --output sdd/state/FEAT-633/spikes/S5-sdd-assumptions.md`,
   then hand-append the "Conclusions" section. *Why*: the report is the S5 deliverable
   and drives TASK-4089/4091.
5. Diff the report's Helper reference map against the pre-seeded map in Context. Any
   mismatch is a scanner bug: fix the scanner, not the table. *Why*: the map is the
   acceptance oracle.

### `packages/ai-parrot/src/parrot/sdd/__init__.py` (CREATE)
```python
"""SDD (Spec-Driven Development) flow support shipped inside ai-parrot (FEAT-633).

Subpackages/modules: ``audit`` (asset assumption scanner), ``scripts`` (helpers invocable as
``python -m parrot.sdd.scripts.<name>``). Intentionally import-free: keep this file docstring-only.
"""
```

### `packages/ai-parrot/src/parrot/sdd/audit.py` (CREATE)
```python
"""Scan SDD markdown/hook assets for assumptions that break outside the ai-parrot monorepo (FEAT-633 S5).

Usage:
    python -m parrot.sdd.audit [PATH ...] [--root DIR] [--output FILE]

Stdlib-only by contract: imported by ``parrot sdd install`` (TASK-4091) to warn about missing tooling.
"""
from __future__ import annotations

import argparse
import re
import shutil
import sys
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from pathlib import Path

KINDS: tuple[str, ...] = (
    "repo-script", "venv-path", "uv-run", "external-tool", "posix-shell", "monorepo-path",
    "org-data", "claude-md-ref", "branch-literal",            # C11a — publication safety
)
EXTERNAL_TOOLS: tuple[str, ...] = ("jq", "gh", "tmux", "codex", "git-lfs", "agy", "black", "pylint")
#: Placeholders shipped files MUST use instead of real organisation data (TASK-4089 rewrites to these).
PLACEHOLDER_ATLASSIAN_HOST = "your-org.atlassian.net"
PLACEHOLDER_TICKET_PREFIX = "PROJ"
# org-data (a): any *.atlassian.net host that is not the placeholder.
ORG_HOST_RE = re.compile(r"(?<![\w-])(?!your-org\.atlassian\.net\b)[a-z0-9][a-z0-9-]*\.atlassian\.net\b")
# org-data (b): a Jira-style ticket key. Allow-listed prefixes are SDD's own ids and common non-ticket tokens.
TICKET_KEY_ALLOW: tuple[str, ...] = (PLACEHOLDER_TICKET_PREFIX, "FEAT", "TASK", "AC", "SHA", "UTF", "ISO", "RFC", "PEP", "CVE")
TICKET_KEY_RE = re.compile(r"(?<![\w-])(?!(?:" + "|".join(TICKET_KEY_ALLOW) + r")-)[A-Z][A-Z0-9]{1,9}-\d+\b")
# claude-md-ref: any reference to CLAUDE.md, with or without a section anchor (`CLAUDE.md § …`, `CLAUDE.md#…`).
CLAUDE_MD_RE = re.compile(r"\bCLAUDE\.md\b")
# branch-literal: dev|staging|main ONLY in an operator position — git ref (`origin/dev`), git verb
# (`checkout dev`, `checkout -b x dev`, `pull origin dev`, `merge dev`, `rebase dev`, `push origin dev`),
# an SDD flag (`--base dev`, `--base-branch=dev`) or frontmatter (`base_branch: dev`). Prose words
# ("the main checkout", "dev-loop", "staging area") never match because they lack the operator prefix.
BRANCH_LITERAL_RE = re.compile(
    r"(?:\borigin/|--base(?:-branch)?[ =]|\bbase_branch:\s*|\b(?:checkout|switch)\s+(?:-b\s+\S+\s+)?"
    r"|\bpull\s+origin\s+|\bpush\s+(?:-u\s+)?origin\s+|\bmerge\s+(?:--no-ff\s+)?|\brebase\s+(?:-i\s+)?)"
    r"(?P<branch>dev|staging|main)\b(?![-_/])"
)
DEFAULT_GLOBS: tuple[str, ...] = (
    ".claude/commands/sdd-*.md",
    ".claude/agents/sdd-*.md",
    ".claude/rules/*.md",
    ".claude/hooks/sdd-worker-format.sh",
    "sdd/templates/*",
    "sdd/WORKFLOW.md",
    ".agents/skills/sdd-*/SKILL.md",      # rev 0.5 C24 — Codex/Google twins
    ".agents/agents/sdd-*/agent.md",
    ".agent/workflows/sdd-*.md",
    ".agent/agents/sdd-*/agent.md",
)
REPO_SCRIPT_RE = re.compile(r"scripts[./]sdd[./](?P<name>[A-Za-z_][A-Za-z0-9_]*)(?:\.py|\.sh)?")
# Command position only (line start, backtick, `$(`, pipe, `&&`, `;`) so prose like "ask codex for…" never matches.
EXTERNAL_TOOL_RE = re.compile(
    r"(?:^\s*|`|\$\(|\|\s*|&&\s*|;\s*)(?P<tool>" + "|".join(map(re.escape, EXTERNAL_TOOLS)) + r")\s+[-\w'\"./]"
)
# FILL IN: final regexes for the four remaining original kinds — bounded by the kind definitions below and test_audit.py
#   venv-path:     .venv/bin, `source .venv/bin/activate`
#   uv-run:        `uv run`
#   posix-shell:   `source ` at command position, `$(...)`, `/tmp/`, heredocs, `set -euo pipefail`, `#!/usr/bin/env bash`
#   monorepo-path: `packages/ai-parrot...`, `.claude/worktrees/`
# The three C11a kinds are FIXED above; `org-data` is the union of ORG_HOST_RE and TICKET_KEY_RE (one finding per line).
_ORG_DATA_RE = re.compile("|".join((ORG_HOST_RE.pattern, TICKET_KEY_RE.pattern)))
_KIND_PATTERNS: dict[str, re.Pattern[str]] = {
    "repo-script": REPO_SCRIPT_RE,
    "external-tool": EXTERNAL_TOOL_RE,
    "org-data": _ORG_DATA_RE,
    "claude-md-ref": CLAUDE_MD_RE,
    "branch-literal": BRANCH_LITERAL_RE,
}


@dataclass(frozen=True)
class AssumptionFinding:
    """One line of an asset that encodes a non-portable assumption."""

    path: str
    line: int
    kind: str
    snippet: str


def scan_text(text: str, path: str) -> list[AssumptionFinding]:
    """Scan ``text`` line by line; at most one finding per (line, kind); snippet = stripped line, max 160 chars."""
    findings: list[AssumptionFinding] = []
    for lineno, raw in enumerate(text.splitlines(), start=1):
        for kind in KINDS:
            pattern = _KIND_PATTERNS.get(kind)
            if pattern is not None and pattern.search(raw):
                findings.append(AssumptionFinding(path, lineno, kind, raw.strip()[:160]))
    return findings


def scan_paths(paths: Iterable[Path]) -> list[AssumptionFinding]:
    """Read each existing file as UTF-8 (errors="replace") and return all findings sorted by (path, line, kind)."""
    # FILL IN: skip directories/missing files silently; path string = as given (posix) — bounded by "no absolute paths"
    raise NotImplementedError


def missing_tools(findings: Sequence[AssumptionFinding]) -> list[str]:
    """Sorted unique external tools named by ``external-tool`` findings that ``shutil.which`` cannot find."""
    names = {m.group("tool") for f in findings if f.kind == "external-tool" for m in EXTERNAL_TOOL_RE.finditer(f.snippet)}
    return sorted(name for name in names if shutil.which(name) is None)


def helper_map(findings: Sequence[AssumptionFinding]) -> dict[str, list[str]]:
    """Map each path to the sorted unique ``scripts/sdd`` helper names it references (repo-script findings)."""
    # FILL IN: group REPO_SCRIPT_RE names per path — bounded by the pre-seeded reference map (Context)
    raise NotImplementedError


def render_report(findings: Sequence[AssumptionFinding], *, scanned: Sequence[str]) -> str:
    """Markdown: summary counts per kind, Helper reference map, Rewrite list, findings per file, Missing tools."""
    # FILL IN: section order/headings as in the S5 report block below — bounded by byte-stable output (no abs paths)
    raise NotImplementedError


def main(argv: Sequence[str] | None = None) -> int:
    """CLI: scan PATHs (default: DEFAULT_GLOBS under --root) and write the report.

    Exit codes: 0 ok; 1 a finding of a ``--fail-on`` kind exists (C11c CI gate); 2 nothing to scan.
    A PATH that is a directory is scanned recursively (every regular file, sorted).
    """
    parser = argparse.ArgumentParser(prog="python -m parrot.sdd.audit", description=__doc__.splitlines()[0])
    parser.add_argument("paths", nargs="*", type=Path)
    parser.add_argument("--root", type=Path, default=Path.cwd())
    parser.add_argument("--output", type=Path, default=None)
    parser.add_argument(
        "--fail-on", default="", metavar="KIND[,KIND...]",
        help="exit 1 when any finding of these kinds exists (e.g. org-data,claude-md-ref,branch-literal)",
    )
    args = parser.parse_args(argv)
    # FILL IN: expand DEFAULT_GLOBS relative to --root (sorted) when no PATH given; expand directory PATHs
    #          (rglob, files only, sorted); relativize paths to --root; scan; render; write to --output or
    #          sys.stdout; sys.stderr.write + return 2 when no file matched; parse --fail-on (comma list,
    #          each must be in KINDS else argparse error), write one "<path>:<line>: [<kind>] <snippet>" line
    #          per matching finding to stderr and return 1 — bounded by AC-3 and AC-8
    raise NotImplementedError


if __name__ == "__main__":
    raise SystemExit(main())
```
**Why this shape**: names and signatures are fixed by this task's brief and consumed by
TASK-4089/4090/4091. Keep `_KIND_PATTERNS` covering all nine `KINDS`; the FILL IN adds the
four original entries still missing (the three C11a patterns are fixed above). `missing_tools`
re-derives tool names from snippets because the dataclass fields are fixed (no extra `tool`
field). The C11a regexes are deliberately narrow: a false positive here blocks CI for
TASK-4090, so `branch-literal` requires an operator prefix and `org-data` allow-lists SDD's
own ids and common `WORD-<n>` tokens (`SHA-256`, `UTF-8`, `ISO-8601`, `AC-1`).

### `packages/ai-parrot/tests/sdd/__init__.py` (CREATE)
```python
```
(Empty file, which is the repo convention for test packages.)

### `packages/ai-parrot/tests/sdd/test_audit.py` (CREATE)
See **Test Specification** below. That block is the starting file.

### `sdd/state/FEAT-633/spikes/S5-sdd-assumptions.md` (CREATE)
```markdown
# S5 — SDD asset assumption inventory (FEAT-633)

> Generated by `python -m parrot.sdd.audit --root . --output sdd/state/FEAT-633/spikes/S5-sdd-assumptions.md`
> on <commit sha> — regenerate, never hand-edit sections above "Conclusions".

## Summary
| Kind | Findings | Files |
|---|---|---|
<generated rows, one per kind>

## Helper reference map
| Asset | Helpers |
|---|---|
<generated rows — must match the TASK-4070 Context table>

## Rewrite list (drives TASK-4089)
<generated: `scripts/sdd/<name>` / `scripts.sdd.<name>` → `parrot sdd run <name>`>

## Findings by file
<generated: ### <path> then `L<n> [kind] snippet` bullets>

## Missing tools on the generating host (<os>)
<generated>

## Conclusions
<hand-written: (1) helpers not in the TASK-4085–4088 + TASK-4508 move list, if any; (2) external tools TASK-4091 must
warn about; (3) POSIX-only constructs that cannot be made portable and must be documented as POSIX-first;
(4) C11a: the org-data / claude-md-ref / branch-literal lines TASK-4089 must rewrite — placeholders
`https://your-org.atlassian.net` and `PROJ-123`, no `CLAUDE.md` references, branch names read from
`sdd/config.json` (TASK-4299) instead of literals>
```
**Why**: S5's deliverable (spec §3 M0) is a committed report. The angle-bracket lines
are generator output, not literal text.

### FILL IN checklist
- [ ] `audit.py::_KIND_PATTERNS`: regexes for `venv-path`, `uv-run`, `posix-shell`,
  `monorepo-path`. Bounded by the kind definitions and `test_audit.py`. `EXTERNAL_TOOL_RE`
  is fixed: it matches command position only, so prose mentions of "codex" never count.
- [ ] `audit.py::scan_paths`: file reading and sorting. Bounded by "no absolute paths".
- [ ] `audit.py::helper_map`: bounded by the pre-seeded reference map.
- [ ] `audit.py::render_report`: section layout per the S5 block. Bounded by byte-stable
  output.
- [ ] `audit.py::main`: glob/directory expansion, `--fail-on` and exit codes. Bounded by AC-3 and AC-8.
- [ ] The S5 report's "Conclusions": hand-written, four bullets as outlined.

---

## Acceptance Criteria

- [ ] AC-1: `import parrot.sdd.audit` loads no third-party module and no `parrot.*`
  module other than `parrot`, `parrot.version`, `parrot.sdd`, `parrot.sdd.audit`
  (enforced by a test).
- [ ] AC-2: `scan_text` emits each of the nine kinds on a representative line and emits
  nothing on a plain prose line.
- [ ] AC-7 (C11a): `org-data` does NOT fire on `https://your-org.atlassian.net`, `PROJ-123`,
  `FEAT-633`, `TASK-4070`, `SHA-256`, `UTF-8`, `ISO-8601`, `AC-1`; it DOES fire on
  `trocglobal.atlassian.net` and `NAV-1234`. `branch-literal` does NOT fire on "the main
  checkout", "dev-loop", "staging area", `origin/<base_branch>`; it DOES fire on
  `origin/dev`, `--base dev`, `base_branch: main`, `git checkout staging`.
  `claude-md-ref` fires on `CLAUDE.md` with and without a section anchor.
- [ ] AC-8 (C11c): `python -m parrot.sdd.audit <dir> --fail-on org-data` exits 1 and names
  the offending `<path>:<line>` on stderr when a finding of that kind exists, exits 0 when
  none does; an unknown kind in `--fail-on` is an argparse error (exit 2).
- [ ] AC-3: `python -m parrot.sdd.audit --root <empty dir>` exits 2. Over the repo it
  exits 0 and the report contains no absolute path.
- [ ] AC-4: The Helper reference map generated over the real assets matches the Context
  table. At minimum, `sdd-spec.md` maps to {reserve_ids, sdd_meta, spec_tools}, `sdd-done.md` to
  {check_e2e_closeout, check_task_state, close_resolved_issues, close_task, heal_orphans, sdd_meta,
  select_tests, test_report}, `sdd-task.md` to {cache_test_contract, check_task_graph, reserve_ids,
  sdd_meta} (`check_e2e_closeout`, `close_resolved_issues`, `test_report`, `cache_test_contract`:
  moved by TASK-4508), and `sdd-brief.md` to {brief_meta, check_task_graph, ensure_worktree}
  *(rev 0.4 C17)*. *(rev 0.5 C24)* The twin rows match the second Context table (e.g.
  `.agents/skills/sdd-done/SKILL.md` and `.agent/workflows/sdd-done.md` each include `test_report` and
  `close_resolved_issues`); `/sdd-insight` rows are kept and labelled "not shipped (C22)".
- [ ] AC-5: `missing_tools` returns only tools `shutil.which` cannot resolve (tested with
  monkeypatch).
- [ ] AC-6: `sdd/state/FEAT-633/spikes/S5-sdd-assumptions.md` is committed, generated by
  the scanner, and has a filled "Conclusions" section.
- [ ] `ruff check packages/ai-parrot/src/parrot/sdd packages/ai-parrot/tests/sdd` is clean.
- [ ] Supports spec §5 bullet "`parrot sdd install` deploys the flow … every helper
  referenced by installed markdown is invoked as `parrot sdd run <name>`" (rev 0.2)
  (the inventory side).

---

## Validation Commands

Run from the feature worktree with `PYTHONPATH=packages/ai-parrot/src` (the shared venv is
editable-installed against the main checkout).

- `pytest packages/ai-parrot/tests/sdd/test_audit.py -q`

---

## Test Specification

```python
# packages/ai-parrot/tests/sdd/test_audit.py
"""Tests for parrot.sdd.audit (FEAT-633 spike S5)."""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

from parrot.sdd import audit
from parrot.sdd.audit import AssumptionFinding, missing_tools, scan_paths, scan_text

REPO_ROOT = Path(__file__).resolve().parents[4]


@pytest.mark.parametrize(
    ("line", "kind"),
    [
        ("python -m scripts.sdd.reserve_ids --kind task", "repo-script"),
        ("scripts/sdd/close_task.sh TASK-1 slug verified", "repo-script"),
        ("source .venv/bin/activate", "venv-path"),
        ("uv run --no-sync pytest", "uv-run"),
        ("TASK_FILES=$(jq -r '.tasks[].file' idx.json)", "external-tool"),
        ("TASK_FILES=$(jq -r '.tasks[].file' idx.json)", "posix-shell"),
        ("cd .claude/worktrees/feat-FEAT-1-x", "monorepo-path"),
        ("Open https://trocglobal.atlassian.net/browse/NAV-1234 first", "org-data"),      # C11a
        ("Resolves NAV-1234 and NAV-77", "org-data"),                                      # C11a
        ("See CLAUDE.md § Adversarial Second Opinion", "claude-md-ref"),                   # C11a
        ("Follow CLAUDE.md throughout.", "claude-md-ref"),                                 # C11a
        ("git fetch origin && git rebase origin/dev", "branch-literal"),                   # C11a
        ("python -m scripts.sdd.reserve_ids --base-branch dev --count 1", "branch-literal"),  # C11a
        ("base_branch: main", "branch-literal"),                                           # C11a
        ("git checkout staging", "branch-literal"),                                        # C11a
    ],
)
def test_scan_text_kinds(line: str, kind: str) -> None:
    assert kind in {f.kind for f in scan_text(line, "x.md")}


def test_scan_text_prose_is_clean() -> None:
    assert scan_text("Ask codex for a second opinion about the design.", "x.md") == []


@pytest.mark.parametrize(
    ("line", "kind"),
    [
        ("Tracker: https://your-org.atlassian.net/browse/PROJ-123", "org-data"),   # placeholders
        ("FEAT-633 decomposes into TASK-4070 … TASK-4095", "org-data"),            # SDD's own ids
        ("checksum SHA-256, encoding UTF-8, dates ISO-8601, criterion AC-1", "org-data"),
        ("the main checkout, the dev-loop and the staging area", "branch-literal"),  # prose words
        ("git fetch origin/<base_branch>; --base <base_branch>", "branch-literal"),  # placeholders
        ("development on the dev branch is described in the handbook", "branch-literal"),
    ],
)
def test_c11a_kinds_skip_placeholders_and_prose(line: str, kind: str) -> None:
    assert kind not in {f.kind for f in scan_text(line, "x.md")}


def test_main_fail_on_exits_1_and_names_the_line(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    (tmp_path / "a.md").write_text("ok line\nticket NAV-1 here\n", encoding="utf-8")
    assert audit.main([str(tmp_path), "--root", str(tmp_path), "--fail-on", "org-data"]) == 1
    assert "a.md:2: [org-data]" in capsys.readouterr().err
    assert audit.main([str(tmp_path), "--root", str(tmp_path), "--fail-on", "claude-md-ref"]) == 0


def test_main_fail_on_rejects_unknown_kind(tmp_path: Path) -> None:
    with pytest.raises(SystemExit) as exc:
        audit.main([str(tmp_path), "--root", str(tmp_path), "--fail-on", "no-such-kind"])
    assert exc.value.code == 2


def test_missing_tools_uses_which(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(audit.shutil, "which", lambda name: None if name == "jq" else f"/usr/bin/{name}")
    findings = [AssumptionFinding("a.md", 1, "external-tool", "jq -r .x f && gh pr view")]
    assert missing_tools(findings) == ["jq"]


def test_import_is_stdlib_only() -> None:
    code = "import sys, parrot.sdd.audit; print(sorted(m for m in sys.modules if m.startswith('parrot')))"
    out = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, check=True).stdout
    assert out.strip() == "['parrot', 'parrot.sdd', 'parrot.sdd.audit', 'parrot.version']"


def test_real_assets_reference_map() -> None:
    findings = scan_paths([REPO_ROOT / ".claude/commands/sdd-spec.md"])
    names = {m.group("name") for f in findings if f.kind == "repo-script" for m in audit.REPO_SCRIPT_RE.finditer(f.snippet)}
    assert {"reserve_ids", "sdd_meta"} <= names


def test_default_globs_cover_codex_and_google_twins() -> None:  # rev 0.5 C24
    assert {
        ".agents/skills/sdd-*/SKILL.md", ".agents/agents/sdd-*/agent.md",
        ".agent/workflows/sdd-*.md", ".agent/agents/sdd-*/agent.md",
    } <= set(audit.DEFAULT_GLOBS)


def test_main_empty_root_exits_2(tmp_path: Path) -> None:
    assert audit.main(["--root", str(tmp_path)]) == 2


def test_main_report_has_no_absolute_paths(tmp_path: Path) -> None:
    out = tmp_path / "report.md"
    assert audit.main(["--root", str(REPO_ROOT), "--output", str(out)]) == 0
    assert str(REPO_ROOT) not in out.read_text(encoding="utf-8")
```

---

## Agent Instructions

When you pick up this task:

1. **Work in the feature worktree**. Never work on `base_branch`.
   (`python -m scripts.sdd.ensure_worktree --slug parrot-installer --feature-id FEAT-633`)
2. **Read the spec** at the path listed above for full context.
3. **Check dependencies**: every `Depends-on` task must be `"done"` in the per-spec index
   `sdd/tasks/index/parrot-installer.json`.
4. **Verify the Codebase Contract** before writing ANY code:
   - Confirm every import in "Verified Imports" still exists (`grep` or `read` the source).
   - Confirm every class/method in "Existing Signatures" still has the listed attributes.
   - If anything has changed, update the contract FIRST, then implement.
   - **NEVER** reference an import, attribute, or method not in the contract without
     verifying it exists.
5. **Update status** in `sdd/tasks/index/parrot-installer.json` to `"in-progress"` (set
   `started_at`) and commit only that index file.
6. **Implement**. Start from the Implementation Blueprint blocks, complete every
   `# FILL IN:` marker, and never change a signature or path the blueprint fixes.
7. **Verify** that all acceptance criteria are met by running the Validation Commands.
8. **Commit the code**. Stage only the files this task lists (never `git add .` / `-A`).
9. **Close the task** with `scripts/sdd/close_task.sh TASK-4070 parrot-installer verified`.
   It moves this file to `sdd/tasks/completed/` and marks it `"done"` in the index. Never
   move or copy the file by hand.
10. **Fill in the Completion Note** below, then commit the staged SDD state.

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**: <session or agent ID>
**Date**: YYYY-MM-DD
**Notes**: What was implemented, any deviations from scope, issues encountered.

**Deviations from spec**: none | describe if any
