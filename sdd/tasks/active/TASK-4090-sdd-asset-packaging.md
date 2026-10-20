# TASK-4090: SDD asset packaging: _assets sync tool, package-data, MANIFEST.in, CI checks, single-copy prompts

**Feature**: FEAT-633 — Parrot Bootstrap Installer
**Spec**: `sdd/specs/parrot-installer.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: L (4-8h)
**Depends-on**: TASK-4070, TASK-4072, TASK-4076, TASK-4089
**Assigned-to**: unassigned

---

## Context

Spec §3 Module 6: the SDD flow's markdown assets must ship **inside the core wheel** under
`packages/ai-parrot/src/parrot/sdd/_assets/` so `parrot sdd install` (TASK-4091) can deploy
them into any repository without a monorepo checkout. The repo's `.claude/` (+ the codex /
google twins and `sdd/templates/`) stays the **source of truth** (owner decision); the
packaged copies are generated, and `scripts/sdd/check_asset_sync.py` fails CI on any
divergence (FEAT-553 `_rules_data` precedent). Packaging is a **verified build artifact**
(codex S8): `MANIFEST.in` grows the asset tree and CI proves the built wheel contains the
full set.

This task runs after TASK-4089 (the markdown is already rewritten to the installable helper
form, so the copies are installable), after TASK-4070 (the scanner used by the publication
check), and is serialized after TASK-4072 (`pyproject.toml`) and TASK-4076 (`ci.yml`).

---

## Amendments — spec rev 0.2 (2026-10-14)

Folded in from `sdd/proposals/parrot-installer-amendments.proposal.md` (§3, §5; decisions by
Jesus Lara, 2026-10-14). Every section below is already edited to match; this list is the
delta for reviewers.

- **C10 — no rulebook ships.** `codebase-conventions.md` is removed from the asset set for
  every host (both the `.claude/rules/` row and the `.agent/rules/` row). The only shipped
  rule is `.claude/rules/worktree-management.md`. A neutral, team-owned seed
  `sdd/CONVENTIONS.md` is added to the repo and packaged with `seed: true` in the manifest;
  TASK-4091 creates it once and never overwrites or removes it. ai-parrot's own rules files
  stay as repo files; `flows/_rules_data/` (FEAT-553, dev-loop coder seats) is untouched.
- **C9 — no unshipped skill.** `.claude/skills/second-opinion/SKILL.md` is packaged for the
  claude host (`hosts: ["claude"]`). Codex and Google have no equivalent skill under
  `.agents/skills/` or `.agent/skills/`, so it ships for claude only.
- **C2 — one copy of each agent prompt.** `load_subagent_definition()` in
  `flows/dev_loop/_subagent_defs.py` and `flows/dev_flow/_subagent_defs.py` reads the packaged
  copy under `parrot/sdd/_assets/claude/agents/<name>.md` (frontmatter stripped as today).
  The nine `_subagent_data/` copies that have a `.claude/agents/` twin are deleted
  (`sdd-codereview.md` has no twin and stays in `dev_loop/_subagent_data/`). The failing
  `test_subagent_parity.py::test_prompt_parity[sdd-worker]` is removed: the asset-sync check
  is the parity gate now. The former "no sync tool for `_subagent_data/`" note is gone.
- **C11c/C11d — publication safety.** `check_asset_sync.py --wheel` also rejects a deny-list of
  paths that must never ship; CI scans `_assets/` with TASK-4070's scanner and fails on any
  `org-data`, `claude-md-ref` or `branch-literal` finding; a planted forbidden file fails the
  wheel check (test).

---

## Amendments — spec rev 0.4 (2026-10-18)

Folded in from `sdd/proposals/parrot-installer-amendments.proposal.md` §3 C17 (decision by
Jesus Lara, 2026-10-18). Every section below is already edited to match.

- **C17 — `/sdd-brief` (FEAT-698) is in the asset set.** No glob changes: `ASSET_SOURCES`
  already matches `.claude/commands/sdd-brief.md`, `.agents/skills/sdd-brief/SKILL.md`,
  `.agent/workflows/sdd-brief.md` (created by TASK-4089, a dependency) and
  `sdd/templates/brief.md`. The counts change: 15 commands per host, 13 git-tracked
  templates, **81** manifest entries *(superseded by spec rev 0.5 C22: 14 commands per host,
  **78** entries — `/sdd-insight` is excluded)*. Re-count against `git ls-files` at run time — the
  numbers in this file are the expected values of the sync check, not inputs to it.
  *(Superseded by rev 0.5 C22: `/sdd-insight` leaves every host — 14 commands per host, **78** entries.)*

---

## Amendments — spec rev 0.3 C16 (folded in 2026-10-19)

From `sdd/proposals/parrot-installer-amendments.proposal.md` §3 C16 (approved by Jesus Lara,
2026-10-17; it lists TASK-4090 for "the widened test"). Every section below is edited to match.

- **C16 — no shipped monorepo source path.** The packaging gates widen past C12's `scripts/sdd`
  sweep: `check_asset_sync.py --check` and `--wheel` report every shipped line naming a monorepo
  source path — `packages/`, `scripts/`, `$CLAUDE_PROJECT_DIR/…` — as `monorepo-path`, with the
  same pattern as TASK-4089's `test_no_repo_script_refs` and an exemption set that rev 0.5 C22 fixes
  to the single `sdd-worker-format.sh:76` line (see the Readiness review). The two agent-frontmatter
  hooks are rewritten by TASK-4089 (rule 7); this task only gates.

---

## Readiness review — 2026-10-19 (dev 9f51c7735)
- Refreshed against dev 9f51c7735: asset counts re-verified (81 = 15+9+1+1+1+15+1+15+8+13+1+1), "77 files" → 81 everywhere; three more tests that read `_subagent_data/` added as MODIFY rows; pyproject anchors updated (package-data `:970`, `parrot.flows` `:983`, `dev_loop` `:984`, FEAT-412 comment `:985-986`, `dev_flow` `:987`); stale `test_prompt_parity` note corrected (copies are byte-identical on 9f51c7735); C16 `monorepo-path` gate folded in.
- Resolved by spec rev 0.5 (2026-10-20):
  - C22 (C16 gate vs existing paths) — TASK-4089 rewrites the lines by categories A–E; `MONOREPO_PATH_ALLOWLIST` holds only `.claude/hooks/sdd-worker-format.sh:76` (category D); `--check` / `--wheel` add the second pattern `tests/sdd_scripts/|\bfrom navconfig\b|PYTHONPATH=|reference/sdd-insight/`; `/sdd-insight` is excluded on every host, so 81 → **78** assets (14 commands per host); the `sdd/CONVENTIONS.md` seed gains `## Repository layout` and `## Project areas`.

## Scope

- Create the stdlib-only `scripts/sdd/check_asset_sync.py` (`--write` regenerates `_assets/` +
  `manifest.json`; default / `--check` exits 1 listing diverging, missing and extra files;
  `--wheel <path>` verifies a built wheel contains `manifest.json` and every manifest entry
  **and** contains nothing matching the publication deny-list — C11d; both `--check` and
  `--wheel` also report every shipped line naming a monorepo source path — C16 — or matching
  C22's second pattern, except the single allowlisted line).
- Create the neutral seed `sdd/CONVENTIONS.md` in the repo (C10); it is packaged like any
  other asset and flagged `seed: true` in the manifest. *(rev 0.5 C22 B)* It carries
  `## Repository layout` and `## Project areas` sections, which the shipped text now points to.
- Generate `packages/ai-parrot/src/parrot/sdd/_assets/` (78 files + `manifest.json`; rev 0.5 C22: no
  `/sdd-insight` on any host) with `--write`.
- Declare the asset tree in `[tool.setuptools.package-data]` and in `MANIFEST.in`.
- Add the sync-check step, the publication scan step (C11c) and a wheel-content job to
  `.github/workflows/ci.yml`.
- Point both `load_subagent_definition()` loaders at `parrot/sdd/_assets/claude/agents/`
  and delete the nine duplicated `_subagent_data/` prompts (C2); adapt the tests that read
  `_subagent_data/` by path; remove the parity test that the sync check replaces.
- Write `tests/sdd_scripts/test_check_asset_sync.py`.

**NOT in scope**:
- `parrot/sdd/installer.py`, `parrot/sdd/cli.py`, lazy `sdd` registration, creating
  `sdd/CONVENTIONS.md` in a *target* repo and the never-overwrite rule for seeds (TASK-4091).
- Rewriting markdown references (TASK-4089 — already done when this starts). This includes
  making shipped files point at `sdd/CONVENTIONS.md` instead of `codebase-conventions.md`,
  and the content fixes that make the publication scan pass (placeholders, no `CLAUDE.md`
  references, no branch literals). This task only *gates* on them.
- `parrot/sdd/__init__.py`, `parrot/sdd/audit.py` and its finding kinds (TASK-4070) and
  `parrot/sdd/scripts/` (TASK-4085..4088).
- Wiring the SDD hook into `.claude/settings.json` of a target repo — this task only packages
  `.claude/hooks/sdd-worker-format.sh`; registration is TASK-4091's concern.
- `flows/_rules_data/` and `test_rules_parity.py` (FEAT-553): untouched.
- Deleting `dev_loop/_subagent_data/sdd-codereview.md`: it has no `.claude/agents/` twin and
  stays core-only, loaded from `_subagent_data/` as today.
- `release.yml` / `[tool.cibuildwheel]` (the M8 wheel-matrix task).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `scripts/sdd/check_asset_sync.py` | CREATE | Stdlib sync/check/wheel-verify tool; owns the source→asset mapping |
| `packages/ai-parrot/src/parrot/sdd/_assets/` | CREATE | Generated asset tree (78 files) — produced ONLY by `check_asset_sync.py --write` |
| `packages/ai-parrot/src/parrot/sdd/_assets/manifest.json` | CREATE | Generated manifest (`schema_version: 1`, one entry per asset) |
| `packages/ai-parrot/pyproject.toml` | MODIFY | `"parrot.sdd"` package-data with explicit per-subdir patterns |
| `packages/ai-parrot/MANIFEST.in` | MODIFY | `graft src/parrot/sdd/_assets` so the sdist (and wheel-from-sdist) carry the tree |
| `.github/workflows/ci.yml` | MODIFY | Asset-sync check step + publication scan step + `sdd-assets-wheel` job (build sdist→wheel, verify contents + deny-list) |
| `tests/sdd_scripts/test_check_asset_sync.py` | CREATE | Unit tests for write/check/extra/missing/diverge/wheel/deny-list/seed + package-data coverage + publication scan |
| `sdd/CONVENTIONS.md` | CREATE | Neutral team-conventions seed (C10); repo source of the packaged `sdd/CONVENTIONS.md` asset |
| `packages/ai-parrot/src/parrot/flows/dev_loop/_subagent_defs.py` | MODIFY | `load_subagent_definition` reads `parrot/sdd/_assets/claude/agents/<name>.md`; `sdd-codereview` keeps `_subagent_data/` |
| `packages/ai-parrot/src/parrot/flows/dev_flow/_subagent_defs.py` | MODIFY | `load_subagent_definition("sdd-ideation")` reads the packaged asset |
| `packages/ai-parrot/src/parrot/flows/dev_loop/_subagent_data/sdd-{autopilot,coder,feedback,planner,qa,research,secondopinion,worker}.md` | DELETE | 8 duplicated prompts (C2); `sdd-codereview.md` stays |
| `packages/ai-parrot/src/parrot/flows/dev_flow/_subagent_data/sdd-ideation.md` | DELETE | duplicated prompt (C2); the now-empty `dev_flow/_subagent_data/` dir goes with it |
| `packages/ai-parrot/tests/flows/dev_loop/test_subagent_parity.py` | MODIFY | Drop `test_prompt_parity` + `_NO_REPO_TWIN`/`_package_prompts` helpers; keep the two body tests |
| `packages/ai-parrot/tests/flows/dev_flow/test_subagent_defs.py` | MODIFY | Parity assertions (lines 54, 267-271) now compare `.claude/agents/sdd-ideation.md` with the packaged asset |
| `packages/ai-parrot/tests/flows/dev_flow/test_base_branch_threading.py` | MODIFY | Line 77 reads the packaged asset path |
| `packages/ai-parrot/tests/flows/dev_loop/test_planner_node.py` | MODIFY | Line 23 path → packaged asset |
| `packages/ai-parrot/tests/flows/dev_loop/test_pool_wiring.py` | MODIFY | Line 82 path → packaged asset |
| `packages/ai-parrot/tests/flows/dev_loop/test_secondopinion_brief.py` | MODIFY | Lines 30, 52 path → packaged asset |
| `packages/ai-parrot/tests/flows/dev_loop/sdd_coder/test_review_handoff_contract.py` | MODIFY | Line 107 reads the packaged asset |
| `packages/ai-parrot/tests/flows/dev_loop/sdd_coder/test_execution_pool_integration.py` | MODIFY | Lines 1223, 1247 path/docstring → packaged asset |
| `packages/ai-parrot/tests/flows/dev_loop/sdd_coder/test_done_optimization_contract.py` | MODIFY | Line 132 (`test_sdd_worker_twins_pass_report_task`) path → `packages/ai-parrot/src/parrot/sdd/_assets/claude/agents/sdd-worker.md` (reads with no skip — would raise `FileNotFoundError`) |
| `tests/sdd_scripts/test_feat699_doc_contract.py` | MODIFY | `SUBAGENT` (:9, used at :15, :21, :58, :64) → `packages/ai-parrot/src/parrot/sdd/_assets/claude/agents` (reads with no skip — would raise `FileNotFoundError`) |
| `tests/sdd_scripts/test_command_contracts.py` | MODIFY | `_UNATTENDED_SPEC_CALLERS` (:64-65) → `packages/ai-parrot/src/parrot/sdd/_assets/claude/agents/sdd-{research,planner}.md` (`_read` would otherwise skip silently and lose the FEAT-577 coverage) |

The source → `_assets/` → target mapping is decided in Implementation Notes › Asset mapping.
The test paths above were verified with `grep -rn _subagent_data packages/ai-parrot/tests tests`
on 2026-10-14 and re-verified on `9f51c7735` (2026-10-19, which added the last three rows);
re-run it before editing — the line numbers drift.


---

## Codebase Contract (Anti-Hallucination)

> **CRITICAL**: This section contains VERIFIED code references from the actual codebase.
> The implementing agent MUST use these exact imports, class names, and method signatures.
> **DO NOT** invent, guess, or assume any import, attribute, or method not listed here.
> If you need something not listed, VERIFY it exists first with `grep` or `read`.

### Verified Imports
```python
# check_asset_sync.py is STDLIB-ONLY (runs in CI with a bare `python`, before/without uv sync):
import argparse, json, re, shutil, subprocess, sys, zipfile   # re: C16 monorepo-path pattern
from dataclasses import dataclass
from pathlib import Path
# tests:
import pytest
import tomllib                                   # stdlib (Python >= 3.11; core requires-python is >=3.11)
from scripts.sdd import check_asset_sync         # pattern verified: tests/sdd_scripts/test_check_task_state.py:6
                                                 # (`from scripts.sdd.check_task_state import ...`; testpaths=["tests"], root pyproject.toml:252 — re-verified 2026-10-14)
from parrot.sdd.audit import scan_paths, KINDS   # TASK-4070 (publication scan test only; the script itself never imports parrot)
# loaders (C2):
from importlib.resources import files            # already used: flows/dev_loop/_subagent_defs.py, flows/dev_flow/_subagent_defs.py
```

### Existing Signatures to Use
```python
# packages/ai-parrot/pyproject.toml
[build-system] requires = ["setuptools>=77.0.0", "Cython==3.0.11", "wheel>=0.44.0"]   # lines 1-7 (local setuptools 84.0.0)
[tool.setuptools.packages.find] where = ["src"]; include = ["parrot*"]; namespaces = true   # lines 965-968
[tool.setuptools.package-data]                                                         # line 970 (re-verified on 9f51c7735)
parrot = ["py.typed", "templates/*.tpl", "**/*.pyx", "**/*.pxd"]                       # line 971 (`**` already used)
"parrot.flows" = ["_rules_data/*.md"]                                                  # line 983 — anchor, grep -c == 1
"parrot.flows.dev_loop" = ["_subagent_data/*.md"]                                      # line 984 — KEEP (sdd-codereview.md stays)
# FEAT-412: dev_flow ships its own prompt set (sdd-ideation); the loader …           # lines 985-986 (comment) — REMOVE with the line below
"parrot.flows.dev_flow" = ["_subagent_data/*.md"]                                      # line 987 — REMOVE (dir deleted by C2)

# packages/ai-parrot/src/parrot/flows/dev_loop/_subagent_defs.py
def _strip_frontmatter(text: str) -> str:                                              # line 70 — reuse unchanged
def load_subagent_definition(name: str) -> str:                                        # line 95
    data_dir = files("parrot.flows.dev_loop") / "_subagent_data"                       # line 114 — the edit site
_VALID_NAMES  # module-level frozenset of the 9 dev-loop names (incl. sdd-codereview)
# packages/ai-parrot/src/parrot/flows/dev_flow/_subagent_defs.py
_VALID_NAMES: frozenset[str] = frozenset({"sdd-ideation"})                            # line 31
def load_subagent_definition(name: str) -> str:                                        # line 65
    data_dir = files("parrot.flows.dev_flow") / "_subagent_data"                       # line 86 — the edit site

# Prompt inventory (verified 2026-10-14; re-verified on 9f51c7735 — the 8 dev_loop copies and the
# dev_flow sdd-ideation copy are byte-identical to their .claude/agents/ twins, so test_prompt_parity passes there):
#   .claude/agents/sdd-*.md (9): autopilot, coder, feedback, ideation, planner, qa, research, secondopinion, worker
#   dev_loop/_subagent_data/ (9): the 8 above minus ideation, plus sdd-codereview (NO .claude twin)
#   dev_flow/_subagent_data/ (1): sdd-ideation
# .claude/skills/second-opinion/SKILL.md — single-file composite skill (git ls-files: only SKILL.md); no twin under .agents/ or .agent/

# packages/ai-parrot/MANIFEST.in (2 lines today)
recursive-include src *.pyx *.pxd      # line 1
include setup.py                       # line 2 — anchor, grep -c == 1

# packages/ai-parrot/setup.py — two Cython extensions (parrot.utils.types C++, parrot.utils.parsers.toml C), lines 13-24

# .github/workflows/ci.yml
#   job `lint-and-registry:` line 10 (ubuntu-latest, Python 3.12, astral-sh/setup-uv@v10.2.0, `uv sync --all-packages`)
#   step "Check stalled SDD task files" lines 104-107; last line:
            --baseline scripts/sdd/.task_state_baseline.json     # line 107 — anchor, grep -c == 1
#   job `install-guide:` line 113 (comment block for it starts line 109)
# .github/workflows/release.yml:100-102 — `uv build --out-dir ../../dist` precedent

# scripts/generate_tool_registry.py — `--check` CI precedent: "CI mode: exit 1 if stale" (line 11, 362, 447-449)
# packages/ai-parrot/tests/flows/dev_loop/test_rules_parity.py — FEAT-553 precedent: byte parity via
#   `read_bytes() == read_bytes()` (lines 22-39); there is NO sync script for _rules_data (test-only) — untouched here
# packages/ai-parrot/src/parrot/sdd/audit.py (TASK-4070) — `scan_paths(paths) -> list[AssumptionFinding]`,
#   `KINDS` incl. "org-data", "claude-md-ref", "branch-literal"; CLI `python -m parrot.sdd.audit PATH... --fail-on <kinds>`
```

### Does NOT Exist
- ~~`scripts/sdd/check_asset_sync.py`, `parrot/sdd/_assets/`~~ — new in this task.
- ~~a sync/regeneration tool for `_rules_data/`~~ — FEAT-553 keeps parity tests only and is
  untouched; this task introduces the first `--write` generator (mirrors
  `generate_tool_registry.py --check`), and for the agent prompts it is the ONLY copy mechanism
  (C2): `_subagent_data/` holds nothing that has a `.claude/agents/` twin after this task.
- ~~`sdd/CONVENTIONS.md`, a `seed` manifest key, `SEED_TARGETS`, `DENY_PATTERNS`~~ — new in this task (C10, C11d).
- ~~`_assets/claude/skills/`~~ — new in this task (C9).
- ~~any wheel-content check in `ci.yml`~~ — `ci.yml` builds no wheel today (`grep -n "uv build" ci.yml` → none).
- ~~`MANIFEST.in` data entries~~ — Cython sources + `setup.py` only.
- ~~`sdd/templates/research_plan.schema.json` in git~~ — on disk but untracked; never package it.
- ~~`_assets/.claude/...` dot-dir layout~~ — rejected (see mapping rationale).
- ~~`.agents/skills/second-opinion/`, `.agent/skills/second-opinion/`~~ — no codex/google twin of the skill exists.
- ~~`.claude/agents/sdd-codereview.md`~~ — never existed (`git log --all` empty); the prompt is core-only.

---

## Complexity Contract

> **MANDATORY.** Declares the measurable targets and contract symbols used for
> deterministic complexity routing (FEAT-561) before any coder is dispatched.
> This is a declaration, not a hand-authored score — the evaluator computes
> classification from measured evidence, never from this section's prose.

```json
{
  "schema_version": 1,
  "targets": [
    {"path": "scripts/sdd/check_asset_sync.py", "action": "CREATE"},
    {"path": "packages/ai-parrot/src/parrot/sdd/_assets/", "action": "CREATE"},
    {"path": "packages/ai-parrot/src/parrot/sdd/_assets/manifest.json", "action": "CREATE"},
    {"path": "packages/ai-parrot/pyproject.toml", "action": "MODIFY"},
    {"path": "packages/ai-parrot/MANIFEST.in", "action": "MODIFY"},
    {"path": ".github/workflows/ci.yml", "action": "MODIFY"},
    {"path": "tests/sdd_scripts/test_check_asset_sync.py", "action": "CREATE"},
    {"path": "sdd/CONVENTIONS.md", "action": "CREATE"},
    {"path": "packages/ai-parrot/src/parrot/flows/dev_loop/_subagent_defs.py", "action": "MODIFY"},
    {"path": "packages/ai-parrot/src/parrot/flows/dev_flow/_subagent_defs.py", "action": "MODIFY"},
    {"path": "packages/ai-parrot/tests/flows/dev_loop/test_subagent_parity.py", "action": "MODIFY"},
    {"path": "packages/ai-parrot/tests/flows/dev_flow/test_subagent_defs.py", "action": "MODIFY"},
    {"path": "packages/ai-parrot/tests/flows/dev_loop/sdd_coder/test_done_optimization_contract.py", "action": "MODIFY"},
    {"path": "tests/sdd_scripts/test_feat699_doc_contract.py", "action": "MODIFY"},
    {"path": "tests/sdd_scripts/test_command_contracts.py", "action": "MODIFY"}
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot/tests/flows/dev_loop/test_rules_parity.py#test_claude_rules_twin_is_identical",
    "sym:packages/ai-parrot/src/parrot/flows/dev_loop/_subagent_defs.py#load_subagent_definition",
    "sym:packages/ai-parrot/src/parrot/flows/dev_flow/_subagent_defs.py#load_subagent_definition",
    "sym:packages/ai-parrot/src/parrot/sdd/audit.py#scan_paths"
  ]
}
```

---

## Implementation Notes

### Asset mapping (DECIDED — read from what each host actually loads)

Evidence: `sdd/WORKFLOW.md:404-405` — *Codex*: "Repository skills in `.agents/skills/sdd-*` …
and agent `.codex/agents/sdd-worker.toml`"; *Antigravity (Google Gemini)*: "Slash command
workflows in `.agent/workflows/sdd-*.md` …, skills in `.agents/skills/sdd-*`, and subagents in
`.agents/agents/`". Both the codex and google wiki installers render project conventions from
`.agent/rules/` (`knowledge/wiki/codex/assets.py:143`, `knowledge/wiki/google/assets.py:139`).

| Host(s) | Repo source = install target (git-tracked only) | Count | `_assets/` source |
|---|---|---|---|
| claude | `.claude/commands/sdd-*.md` | 14 *(rev 0.4 C17: + `sdd-brief`; rev 0.5 C22: − `sdd-insight`)* | `claude/commands/` |
| claude | `.claude/agents/sdd-*.md` | 9 | `claude/agents/` |
| claude | `.claude/hooks/sdd-worker-format.sh` | 1 | `claude/hooks/` |
| claude | `.claude/rules/worktree-management.md` | 1 | `claude/rules/` |
| claude | `.claude/skills/second-opinion/SKILL.md` (C9) | 1 | `claude/skills/second-opinion/` |
| codex, google | `.agents/skills/sdd-*/SKILL.md` | 14 *(rev 0.4 C17; rev 0.5 C22: − `sdd-insight`)* | `agents/skills/<n>/` |
| codex | `.codex/agents/sdd-worker.toml` | 1 | `codex/agents/` |
| google | `.agent/workflows/sdd-*.md` | 14 *(rev 0.4 C17: TASK-4089 creates `sdd-brief.md`; rev 0.5 C22: − `sdd-insight`)* | `agent/workflows/` |
| google | `.agents/agents/sdd-*/agent.md` | 8 | `agents/agents/<n>/` |
| claude, codex, google | `sdd/templates/*` (git-tracked: 13 — `research_plan.schema.json` is untracked and excluded; `brief.md` came in with FEAT-698, rev 0.4 C17) | 13 | `sdd/sdd_templates/` |
| claude, codex, google | `sdd/WORKFLOW.md` | 1 | `sdd/WORKFLOW.md` |
| claude, codex, google | `sdd/CONVENTIONS.md` — **seed** (`seed: true`; C10) | 1 | `sdd/CONVENTIONS.md` |

**Total: 78 assets** = 14+9+1+1+1+14+1+14+8+13+1+1 (the two `codebase-conventions.md` rows left; the skill and the seed
came in; *rev 0.4 C17*: `sdd-brief` on three hosts and `sdd/templates/brief.md` came in; *rev 0.5 C22*:
`/sdd-insight` left on all three hosts — `.claude/commands/sdd-insight.md`, `.agents/skills/sdd-insight/SKILL.md`,
`.agent/workflows/sdd-insight.md` — because it depends on unshipped `reference/sdd-insight/` and
`.claude/workflows/sdd-insight.js`). Excluded on purpose: `.claude/rules/codebase-conventions.md` and
`.agent/rules/codebase-conventions.md` (C10 — ai-parrot's rulebook never ships; the codex and
google wiki installers keep rendering `.agent/rules/` from the *repo*, which is untouched),
`.agent/agents/sdd-*/agent.md` (no host doc names `.agent/agents/` — Antigravity's subagent dir
is `.agents/agents/`), `.agent/skills/worktree-management/` (not an SDD-named skill on any host
list), `.claude/agents/qa-runner.md` (not `sdd-*`).

**Seed semantics (C10).** A manifest entry with `"seed": true` is written by TASK-4091 only
when the target is absent and is never overwritten, diffed or removed afterwards, `--force`
included. The repo's `sdd/CONVENTIONS.md` IS the seed text — neutral placeholders only
("describe your stack, package manager, lint / format / test commands, forbidden libraries");
ai-parrot's real conventions stay in `.claude/rules/codebase-conventions.md`, which Claude Code
loads from the repo as today. Keep the seed byte-identical to what ships: the sync check
treats it like any other asset.

**Publication deny-list (C11d).** Nothing under these patterns may appear in the wheel's
`parrot/sdd/_assets/` tree: `sdd/references/`, `sdd/state/`, `sdd/ledger/`, `.parrot/`,
`*.jsonl`, `*.db`, `sdd/tasks/.id_ledger.json`, any `.id_ledger*`. `check_wheel` fails on a
match even when the manifest is complete.

**Why `_assets/` does NOT mirror dot-dirs** (verified, not assumed): setuptools 84's
`setuptools.glob` *does* match dot-dirs (checked: `_assets/**/*.md` returned
`_assets/.claude/commands/a.md`), so packaging is not the blocker. The blockers are:
(1) a nested `packages/ai-parrot/src/parrot/sdd/_assets/.claude/` would be picked up by Claude
Code's nested-directory discovery when working under `packages/ai-parrot/`, loading every SDD
command/agent/rule twice; (2) `.gitignore:273` (`templates/`) ignores any `templates/` dir
(`git check-ignore` confirms `_assets/sdd/templates/spec.md` is ignored). Hence the explicit
prefix map `.claude/→claude/`, `.agents/→agents/`, `.agent/→agent/`, `.codex/→codex/`,
`sdd/templates/→sdd/sdd_templates/`, `sdd/→sdd/`, and every manifest entry carries its
explicit `target`. Because the target IS the repo source path, the sync check is driven by
the manifest alone.

### Pattern to Follow
- `scripts/generate_tool_registry.py` — a repo script with a write mode and a `--check` CI
  mode that exits 1 when the generated artifact is stale.
- `test_rules_parity.py` — byte comparison (`read_bytes()`), never text normalization.

### Key Constraints
- **Stdlib only** in `check_asset_sync.py` (no pydantic, no parrot import): the wheel job runs
  it with a bare `python` before any sync, and it must never import the package it verifies.
- **Bytes, not text**: copy with `shutil.copyfile` and compare `read_bytes()`; no newline or
  encoding normalization (the installer's "identical → skip" rule depends on exact bytes).
- **Git-tracked sources only** (`git ls-files`): an untracked local file must never leak into
  the wheel, and CI and dev machines must produce the same manifest.
- **Deterministic manifest**: entries sorted by `target`, `hosts` in the fixed order
  `claude, codex, google`, `json.dumps(..., indent=2) + "\n"`.
- Executable bit: `.sh` assets keep `0o755` in the tree (`shutil.copymode`); TASK-4091 must
  still `chmod` on install because wheels do not reliably preserve modes.
- Never hand-edit `_assets/`: it is regenerated wholesale by `--write` (extra files removed).

### References in Codebase
- `sdd/WORKFLOW.md:404-405` — per-host asset locations (mapping evidence).
- `.gitignore:273` — global `templates/` ignore (why `sdd_templates/`).
- `.github/workflows/release.yml:100-102` — `uv build` precedent.

---

## Implementation Blueprint

> **CRITICAL — Executor-ready starting point.** Write each block below to its declared
> path nearly verbatim, then complete every `# FILL IN:` marker. Never change a signature,
> class name, or file path the blueprint fixes.

### Steps (in order)
0. Create `sdd/CONVENTIONS.md` (seed block below) and commit it — *why*: it must be git-tracked
   before `--write` can package it.
1. Write `scripts/sdd/check_asset_sync.py` — *why*: it owns the mapping; the tree is generated from it.
2. Run `python scripts/sdd/check_asset_sync.py --write`, then `--check` (expect exit 0, 78 assets;
   the C16/C22 `monorepo-path` pass is green once TASK-4089's category A–E rewrite has landed)
   — *why*: `_assets/` and `manifest.json` must never be hand-written.
2b. Edit both `_subagent_defs.py` loaders, `git rm` the nine duplicated `_subagent_data/` prompts,
   drop the `parrot.flows.dev_flow` package-data line, adapt the tests listed in the Files table
   — *why*: the packaged asset is now the only copy (C2); do this right after step 2 so the
   loaders have something to read.
3. `git add -f` is NOT needed (no ignored path in the tree) — verify with
   `git status --porcelain -uall packages/ai-parrot/src/parrot/sdd/_assets | wc -l` == 79 — *why*: a silently
   ignored asset would ship nowhere.
4. Add the package-data block and the `MANIFEST.in` graft — *why*: wheel and sdist must both carry the tree.
5. Locally: `uv build --package ai-parrot --out-dir /tmp/<scratch>/dist` then
   `python scripts/sdd/check_asset_sync.py --wheel <wheel>` — *why*: proves the CI job before pushing.
6. Add the CI step + job; write the tests; run the Validation Commands.

### `scripts/sdd/check_asset_sync.py` (CREATE)
```python
"""Keep ``parrot/sdd/_assets/`` byte-identical to its repo sources (FEAT-633 M6).

Modes: ``--write`` regenerate _assets/ + manifest.json; ``--check`` (default) exit 1 on divergence;
``--wheel <whl>`` verify a built wheel carries every manifest entry. ``--check`` and ``--wheel`` also
report any shipped line naming a monorepo source path (C16) or other monorepo-specific text (C22).
Stdlib only — never import parrot.
"""

from __future__ import annotations

import argparse
import json
import re
import shutil
import subprocess
import sys
import zipfile
from dataclasses import dataclass
from pathlib import Path

ASSETS_DIR = Path("packages/ai-parrot/src/parrot/sdd/_assets")
MANIFEST_NAME = "manifest.json"
SCHEMA_VERSION = 1
WHEEL_PREFIX = "parrot/sdd/_assets/"
HOST_ORDER: tuple[str, ...] = ("claude", "codex", "google")

#: (git pathspec glob relative to the repo root, hosts) — see the task's mapping table.
#: NEVER list `codebase-conventions.md` here (C10: ai-parrot's rulebook does not ship).
ASSET_SOURCES: tuple[tuple[str, tuple[str, ...]], ...] = (
    (".claude/commands/sdd-*.md", ("claude",)),
    (".claude/agents/sdd-*.md", ("claude",)),
    (".claude/hooks/sdd-worker-format.sh", ("claude",)),
    (".claude/rules/worktree-management.md", ("claude",)),
    (".claude/skills/second-opinion/SKILL.md", ("claude",)),          # C9 — claude only; no codex/google twin
    (".agents/skills/sdd-*/SKILL.md", ("codex", "google")),
    (".codex/agents/sdd-worker.toml", ("codex",)),
    (".agent/workflows/sdd-*.md", ("google",)),
    (".agents/agents/sdd-*/agent.md", ("google",)),
    ("sdd/templates/*", HOST_ORDER),
    ("sdd/WORKFLOW.md", HOST_ORDER),
    ("sdd/CONVENTIONS.md", HOST_ORDER),                               # C10 — seed, see SEED_TARGETS
)
#: rev 0.5 C22 — `/sdd-insight` does not ship on any host (it depends on unshipped `reference/sdd-insight/`
#: and `.claude/workflows/sdd-insight.js`); these targets match the globs above and are dropped.
EXCLUDED_TARGETS: frozenset[str] = frozenset({
    ".claude/commands/sdd-insight.md", ".agents/skills/sdd-insight/SKILL.md", ".agent/workflows/sdd-insight.md",
})
#: Targets written once by the installer and never overwritten/removed (manifest `"seed": true`).
SEED_TARGETS: frozenset[str] = frozenset({"sdd/CONVENTIONS.md"})
#: Wheel paths (relative to WHEEL_PREFIX) that must never ship — C11d. fnmatch on the posix path.
DENY_PATTERNS: tuple[str, ...] = (
    "sdd/references/*", "sdd/state/*", "sdd/ledger/*", ".parrot/*", "*/.parrot/*",
    "*.jsonl", "*.db", "*.id_ledger*", "sdd/tasks/*",
)
#: C16 — a monorepo source path in shipped content (`packages/…`, `scripts/…`, `$CLAUDE_PROJECT_DIR/…`);
#: the same pattern as TASK-4089's `test_no_repo_script_refs._MONOREPO_PATH`.
MONOREPO_PATH_RE = re.compile(r"(?<![\w./-])(?:packages|scripts)/|\$\{?CLAUDE_PROJECT_DIR\b[^/\s]*/")
#: rev 0.5 C22 — the second pattern both C16 gates add (same as TASK-4089's `_MONOREPO_TEXT`).
MONOREPO_TEXT_RE = re.compile(r"tests/sdd_scripts/|\bfrom navconfig\b|PYTHONPATH=|reference/sdd-insight/")
#: (target, stripped line) pairs exempted from both patterns — C22 category D: the ONLY entry
#: (`${CLAUDE_PROJECT_DIR:-}/.venv/bin` is the target repo's own venv). Add nothing else.
MONOREPO_PATH_ALLOWLIST: frozenset[tuple[str, str]] = frozenset({
    (".claude/hooks/sdd-worker-format.sh", 'for candidate in "$CWD/.venv/bin" "${CLAUDE_PROJECT_DIR:-}/.venv/bin" \\'),
})
#: target prefix -> asset prefix. No dot-dirs (nested .claude/ discovery) and no `templates/` (.gitignore:273).
PREFIX_MAP: tuple[tuple[str, str], ...] = (
    (".claude/", "claude/"),
    (".agents/", "agents/"),
    (".agent/", "agent/"),
    (".codex/", "codex/"),
    ("sdd/templates/", "sdd/sdd_templates/"),
    ("sdd/", "sdd/"),
)


@dataclass(frozen=True)
class AssetEntry:
    """One packaged asset: where it lives under ``_assets/`` and where it installs."""

    source: str
    target: str
    hosts: tuple[str, ...]
    seed: bool = False

    def as_json(self) -> dict[str, object]:
        """Manifest form (key order fixed: source, target, hosts[, seed]); ``seed`` only when true."""
        payload: dict[str, object] = {"source": self.source, "target": self.target, "hosts": list(self.hosts)}
        if self.seed:
            payload["seed"] = True
        return payload


def asset_source_for(target: str) -> str:
    """Map a repo-relative install target to its path under ``_assets/``.

    Raises:
        ValueError: ``target`` matches no prefix in ``PREFIX_MAP``.
    """
    for prefix, replacement in PREFIX_MAP:
        if target.startswith(prefix):
            return replacement + target[len(prefix):]
    raise ValueError(f"no _assets/ prefix mapping for {target!r}")


def expected_entries(root: Path) -> list[AssetEntry]:
    """Resolve ``ASSET_SOURCES`` against the git-tracked files of ``root``, sorted by target."""
    # FILL IN: one `git -C root ls-files -z -- <pathspecs>` call, glob-match each tracked path to the
    #          FIRST matching ASSET_SOURCES row (fnmatch on the posix path), merge hosts if a target
    #          matches twice (keep HOST_ORDER), seed=(target in SEED_TARGETS), skip any target in
    #          EXCLUDED_TARGETS (C22) — bounded by "git-tracked only" + deterministic order + 78 entries
    raise NotImplementedError


def build_manifest(entries: list[AssetEntry]) -> str:
    """Serialize the manifest exactly as committed (sorted, indent=2, trailing newline)."""
    payload = {"schema_version": SCHEMA_VERSION, "assets": [e.as_json() for e in entries]}
    return json.dumps(payload, indent=2) + "\n"


def monorepo_path_problems(target: str, data: bytes) -> list[str]:
    """C16 + C22: one ``monorepo-path: <target>:<line>: <text>`` per shipped line matching ``MONOREPO_PATH_RE``
    or ``MONOREPO_TEXT_RE``."""
    # FILL IN: decode utf-8 (undecodable bytes → no finding), enumerate lines from 1, test both patterns, skip
    #          pairs in MONOREPO_PATH_ALLOWLIST (target, line.strip()) — bounded by test_monorepo_path_is_reported
    raise NotImplementedError


def find_problems(root: Path, assets_dir: Path) -> list[str]:
    """Compare ``assets_dir`` with the repo sources; return human-readable problems (empty = in sync).

    Problem kinds: ``missing`` (expected asset absent), ``diverged`` (bytes differ from the repo
    source), ``extra`` (file under ``assets_dir`` not in the expected set), ``manifest`` (committed
    ``manifest.json`` differs from ``build_manifest``), ``monorepo-path`` (C16/C22, a shipped source line
    names a monorepo source path or other monorepo-specific text).
    """
    # FILL IN: byte comparison per entry (read_bytes), rglob for extras (ignore manifest.json),
    #          manifest text equality, then monorepo_path_problems(entry.target, source bytes) per entry —
    #          bounded by AC "lists diverging/missing/extra files" and test_monorepo_path_is_reported
    raise NotImplementedError


def write_assets(root: Path, assets_dir: Path) -> list[AssetEntry]:
    """Regenerate ``assets_dir`` from scratch (copy bytes + mode) and write ``manifest.json``."""
    # FILL IN: remove files under assets_dir not in the expected set (only inside assets_dir!), copy each
    #          source with shutil.copyfile + shutil.copymode, write build_manifest() — bounded by idempotency
    #          (a second --write produces no git diff)
    raise NotImplementedError


def check_wheel(wheel: Path) -> list[str]:
    """Verify ``wheel`` contains ``parrot/sdd/_assets/manifest.json`` and every entry it lists,
    nothing under ``WHEEL_PREFIX`` that matches ``DENY_PATTERNS`` (C11d), and no monorepo source path
    in any entry it ships (C16)."""
    # FILL IN: zipfile.ZipFile(wheel).namelist(); read the manifest FROM THE WHEEL (not the checkout);
    #          one "missing in wheel: <WHEEL_PREFIX><source>" per absent entry; flag an empty asset list;
    #          then for every name under WHEEL_PREFIX, fnmatch against DENY_PATTERNS →
    #          "forbidden in wheel: <name>" (also when the name is NOT in the manifest); then
    #          monorepo_path_problems(entry["target"], <bytes read from the wheel>) per present entry —
    #          bounded by codex S8 (prove the shipped artifact), test_check_wheel_reports_missing_entry,
    #          test_check_wheel_rejects_forbidden_paths and test_check_wheel_reports_monorepo_path
    raise NotImplementedError


def main(argv: list[str] | None = None) -> int:
    """CLI entry point; returns the process exit code (0 ok, 1 problems found)."""
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--write", action="store_true", help="regenerate _assets/ and manifest.json")
    mode.add_argument("--check", action="store_true", help="exit 1 on divergence (default)")
    mode.add_argument("--wheel", type=Path, help="verify a built wheel carries every manifest entry")
    parser.add_argument("--root", type=Path, default=Path.cwd(), help="repo root (default: cwd)")
    parser.add_argument("--assets-dir", type=Path, default=None, help="override (tests); default <root>/" + str(ASSETS_DIR))
    args = parser.parse_args(argv)
    root = args.root.resolve()
    assets_dir = args.assets_dir or root / ASSETS_DIR
    if args.wheel:
        problems = check_wheel(args.wheel)
    elif args.write:
        entries = write_assets(root, assets_dir)
        sys.stdout.write(f"wrote {len(entries)} assets + {MANIFEST_NAME} to {assets_dir}\n")
        return 0
    else:
        problems = find_problems(root, assets_dir)
    for problem in problems:
        sys.stderr.write(f"{problem}\n")
    if problems:
        sys.stderr.write("SDD assets out of sync — run: python scripts/sdd/check_asset_sync.py --write\n")
    return 1 if problems else 0


if __name__ == "__main__":
    raise SystemExit(main())
```
**Why this shape**: the mapping lives in one place (`ASSET_SOURCES` + `PREFIX_MAP`); `manifest.json`
is a pure function of git-tracked sources, so `--check` is a regeneration diff. `check_wheel`
reads the manifest *from the wheel* so it proves the shipped artifact, not the checkout (codex S8).
`sys.stdout/stderr.write` instead of `print` (stdlib script convention in the brief).

### `packages/ai-parrot/src/parrot/sdd/_assets/` (CREATE) and `_assets/manifest.json` (CREATE)
```text
# GENERATED — never hand-write. Produced by: python scripts/sdd/check_asset_sync.py --write
_assets/
  manifest.json                      {"schema_version": 1, "assets": [{"source": "claude/commands/sdd-spec.md",
                                       "target": ".claude/commands/sdd-spec.md", "hosts": ["claude"]}, ...,
                                       {"source": "sdd/CONVENTIONS.md", "target": "sdd/CONVENTIONS.md",
                                        "hosts": ["claude", "codex", "google"], "seed": true}]}  (78 entries)
  claude/{commands,agents,hooks,rules}/...
  claude/skills/second-opinion/SKILL.md
  agents/skills/sdd-*/SKILL.md       agents/agents/sdd-*/agent.md
  agent/workflows/sdd-*.md
  codex/agents/sdd-worker.toml
  sdd/sdd_templates/*                sdd/WORKFLOW.md                sdd/CONVENTIONS.md
```
**Why**: the manifest format is fixed by the FEAT-633 brief; TASK-4091 reads it via `importlib.resources`.
`seed` is an optional key (absent ⇒ false), so `schema_version` stays 1 and TASK-4091 reads it
with `entry.get("seed", False)`. No `agent/rules/` subtree exists any more (C10).

### `sdd/CONVENTIONS.md` (CREATE — the seed, C10)
```markdown
# Team conventions

> Seeded by `parrot sdd install`. This file belongs to your team: edit it freely — the
> installer never overwrites or removes it. The SDD commands and agents read it before
> writing code.

## Stack
<!-- Languages, frameworks, runtime versions. -->

## Repository layout
<!-- Where source, tests and docs live; how the repository is split into packages or modules. -->

## Project areas
<!-- The area names SDD documents use in their `projects:` frontmatter (mirror them in
     `projects` in sdd/config.json to have them validated). -->

## Package manager and environment
<!-- How dependencies are declared and installed; how a shell is prepared. -->

## Format, lint and test commands
<!-- The exact commands an agent must run before committing. -->

## Forbidden libraries and patterns
<!-- What must never be imported or done, and what to use instead. -->

## Style
<!-- Naming, docstrings, line length, logging, error handling. -->
```
**Why**: shipped files no longer mandate a language, framework or package manager (C10); the
team describes its own. The text is neutral on purpose — it ships verbatim to every host and
must produce zero scanner findings. *(rev 0.5 C22 B)* `## Repository layout` and `## Project areas`
are where TASK-4089's rewritten text sends layout, environment and `projects` questions.
Note for implementer: C22 gives only the two headings; the comment text under them is a placeholder — confirm wording in review.

### `flows/dev_loop/_subagent_defs.py` and `flows/dev_flow/_subagent_defs.py` (MODIFY — C2)
```python
# dev_loop/_subagent_defs.py — replace line 114 (`data_dir = files("parrot.flows.dev_loop") / "_subagent_data"`):
_CORE_ONLY: frozenset[str] = frozenset({"sdd-codereview"})   # no .claude/agents/ twin — stays in _subagent_data/

    if name in _CORE_ONLY:
        target = files("parrot.flows.dev_loop") / "_subagent_data" / f"{name}.md"
    else:
        # FEAT-633 C2: the packaged SDD asset is the ONLY copy of a prompt that Claude Code also loads.
        target = files("parrot.sdd") / "_assets" / "claude" / "agents" / f"{name}.md"
    text = target.read_text(encoding="utf-8")
    return _strip_frontmatter(text)

# dev_flow/_subagent_defs.py — replace line 86 (`data_dir = files("parrot.flows.dev_flow") / "_subagent_data"`):
    target = files("parrot.sdd") / "_assets" / "claude" / "agents" / f"{name}.md"
    text = target.read_text(encoding="utf-8")
    return _strip_frontmatter(text)
```
**Why**: the frontmatter is the only host-specific part and both loaders already strip it;
reading the packaged asset removes the drift that broke `test_prompt_parity[sdd-worker]`
(`.claude/agents/sdd-worker.md` lists `Monitor, TaskStop` in `tools:`, the `_subagent_data`
copy did not). Update both module docstrings (dev_loop lines 25-45, dev_flow lines 19-23)
to say where the prompt lives now. `git rm` the nine duplicated files; remove the
`"parrot.flows.dev_flow"` package-data line (and its FEAT-412 comment) because the directory
is gone; keep the `dev_loop` line for `sdd-codereview.md`.

### `packages/ai-parrot/pyproject.toml` (MODIFY)
```toml
# occurrences: 1 (verified: grep -c '"parrot.flows" = \["_rules_data/\*.md"\]' packages/ai-parrot/pyproject.toml)
# AFTER — insert below `"parrot.flows" = ["_rules_data/*.md"]` (verified: packages/ai-parrot/pyproject.toml:983, re-verified on 9f51c7735)
# FEAT-633: packaged SDD flow assets deployed by `parrot sdd install`, read via importlib.resources.
# Explicit per-subdir patterns (one per _assets/ subtree); test_check_asset_sync asserts they cover
# every manifest entry, so a new subtree fails CI instead of silently missing from the wheel.
"parrot.sdd" = [
    "_assets/manifest.json",
    "_assets/claude/commands/*.md",
    "_assets/claude/agents/*.md",
    "_assets/claude/hooks/*.sh",
    "_assets/claude/rules/*.md",
    "_assets/claude/skills/*/SKILL.md",
    "_assets/agents/skills/*/SKILL.md",
    "_assets/agents/agents/*/agent.md",
    "_assets/agent/workflows/*.md",
    "_assets/codex/agents/*.toml",
    "_assets/sdd/sdd_templates/*",
    "_assets/sdd/WORKFLOW.md",
    "_assets/sdd/CONVENTIONS.md",
]
# ALSO (C2): delete lines 985-987 — the FEAT-412 comment and `"parrot.flows.dev_flow" = ["_subagent_data/*.md"]`;
# the directory no longer exists. Keep line 984 (`"parrot.flows.dev_loop"`): sdd-codereview.md stays there.
```
**Why**: setuptools here (≥77, local 84) supports `**`, but explicit globs keep the wheel's
content reviewable and the coverage test makes drift loud. Insert after line 983, so
TASK-4072's `[project.scripts]` edit (:199) never collides. There is no `agent/rules/` glob:
nothing ships there any more (C10).

### `packages/ai-parrot/MANIFEST.in` (MODIFY)
```text
# occurrences: 1 (verified: grep -c 'include setup.py' packages/ai-parrot/MANIFEST.in)
# AFTER — insert below `include setup.py` (verified: packages/ai-parrot/MANIFEST.in:2)
graft src/parrot/sdd/_assets
```
**Why**: `uv build` makes the wheel FROM the sdist; without the graft the sdist (and thus the
wheel) could lose the tree (spec §3 M6, codex S8).

### `.github/workflows/ci.yml` (MODIFY)
```yaml
# occurrences: 1 (verified: grep -c '            --baseline scripts/sdd/.task_state_baseline.json' .github/workflows/ci.yml)
# AFTER — insert below `            --baseline scripts/sdd/.task_state_baseline.json` (verified: .github/workflows/ci.yml:107)

      # FEAT-633: parrot/sdd/_assets/ is a generated copy of the SDD sources (.claude/, .agents/,
      # .agent/, .codex/, sdd/); fail on any byte divergence. Fix: python scripts/sdd/check_asset_sync.py --write
      # C16/C22: also fails on a shipped line naming a monorepo source path (packages/, scripts/,
      # $CLAUDE_PROJECT_DIR/…) or monorepo-specific text (tests/sdd_scripts/, from navconfig,
      # PYTHONPATH=, reference/sdd-insight/). Fix: edit the SOURCE file, then --write.
      - name: Check packaged SDD assets are in sync (FEAT-633)
        run: python scripts/sdd/check_asset_sync.py --check

      # FEAT-633 C11c: the asset tree goes into the PUBLIC wheel. Fail on any organisation data,
      # CLAUDE.md reference or hardcoded flow branch in a shipped file (kinds from TASK-4070).
      # Fix: edit the SOURCE file (.claude/, .agents/, …), then `check_asset_sync.py --write`.
      - name: Scan packaged SDD assets for publication-unsafe content (FEAT-633)
        run: >
          uv run --no-sync python -m parrot.sdd.audit
          packages/ai-parrot/src/parrot/sdd/_assets
          --root packages/ai-parrot/src/parrot/sdd/_assets
          --fail-on org-data,claude-md-ref,branch-literal

  # FEAT-633 (codex S8): prove the BUILT wheel carries the SDD asset tree. `uv build` builds the
  # sdist first and the wheel from it, so this also proves MANIFEST.in. g++ is preinstalled on
  # ubuntu-latest for the two Cython extensions; no uv sync / test deps needed.
  sdd-assets-wheel:
    name: SDD assets ship in the ai-parrot wheel
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v6

      - name: Set up Python
        uses: actions/setup-python@v6
        with:
          python-version: "3.12"

      - name: Install uv
        uses: astral-sh/setup-uv@v10.2.0
        with:
          version: "latest"

      - name: Build ai-parrot sdist + wheel
        run: uv build --package ai-parrot --out-dir dist

      - name: Verify wheel contains manifest.json, every manifest entry, nothing on the deny-list and no monorepo path
        run: python scripts/sdd/check_asset_sync.py --wheel dist/ai_parrot-*.whl
```
**Why**: the sync step is stdlib, so it needs no environment; the publication scan runs in
`lint-and-registry`, which already has the synced venv (`uv sync --all-packages`, line 10 block);
the wheel job is the cheapest reliable proof — one build (sdist→wheel, ~2 min incl. Cython) and
a zip listing, now also matched against `DENY_PATTERNS`.
Rejected cheaper options: `setup.py build_py` (skips sdist/MANIFEST.in, not the shipped artifact);
reusing `release.yml` (tag-only, codex S8 wants PR-time proof).

### `tests/sdd_scripts/test_check_asset_sync.py` (CREATE)
```python
"""Tests for scripts/sdd/check_asset_sync.py (FEAT-633 M6, spec §4 test_asset_sync_check)."""

from __future__ import annotations

import json
import subprocess
import tomllib
import zipfile
from pathlib import Path

import pytest

from scripts.sdd import check_asset_sync as cas

_REPO_ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture
def mini_repo(tmp_path: Path) -> Path:
    """A git repo with one source per host family, committed (sources must be git-tracked)."""
    for rel in (".claude/commands/sdd-spec.md", ".agents/skills/sdd-spec/SKILL.md",
                ".agent/workflows/sdd-spec.md", "sdd/templates/task.md", "sdd/WORKFLOW.md"):
        path = tmp_path / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(f"# {rel}\n", encoding="utf-8")
    subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True)
    subprocess.run(["git", "add", "-A"], cwd=tmp_path, check=True)
    return tmp_path


def _run(repo: Path, *flags: str) -> int:
    return cas.main([*flags, "--root", str(repo), "--assets-dir", str(repo / "assets")])


def test_write_then_check_is_clean(mini_repo: Path) -> None:
    assert _run(mini_repo, "--write") == 0
    assert _run(mini_repo, "--check") == 0
    manifest = json.loads((mini_repo / "assets" / "manifest.json").read_text())
    assert manifest["schema_version"] == 1
    assert {"source": "sdd/sdd_templates/task.md", "target": "sdd/templates/task.md",
            "hosts": ["claude", "codex", "google"]} in manifest["assets"]


def test_divergence_missing_and_extra_fail(mini_repo: Path, capsys: pytest.CaptureFixture[str]) -> None:
    _run(mini_repo, "--write")
    (mini_repo / ".claude/commands/sdd-spec.md").write_text("changed\n")      # diverged
    (mini_repo / "assets/agent/workflows/sdd-spec.md").unlink()                 # missing
    (mini_repo / "assets/claude/stray.md").write_text("x")                       # extra
    assert _run(mini_repo, "--check") == 1
    err = capsys.readouterr().err
    # FILL IN: assert each of the three paths is named with its problem kind — bounded by find_problems' wording


def test_untracked_source_is_not_packaged(mini_repo: Path) -> None:
    (mini_repo / "sdd/templates/untracked.json").write_text("{}")
    _run(mini_repo, "--write")
    assert not (mini_repo / "assets/sdd/sdd_templates/untracked.json").exists()


def test_check_wheel_reports_missing_entry(tmp_path: Path) -> None:
    wheel = tmp_path / "ai_parrot-0-py3-none-any.whl"
    manifest = {"schema_version": 1, "assets": [{"source": "claude/commands/a.md", "target": ".claude/commands/a.md", "hosts": ["claude"]}]}
    with zipfile.ZipFile(wheel, "w") as zf:
        zf.writestr(cas.WHEEL_PREFIX + "manifest.json", json.dumps(manifest))
    assert cas.check_wheel(wheel) == [f"missing in wheel: {cas.WHEEL_PREFIX}claude/commands/a.md"]


@pytest.mark.parametrize("planted", ["sdd/state/FEAT-1/notes.md", "sdd/ledger/issues.jsonl", ".parrot/wiki.db",
                                     "sdd/tasks/.id_ledger.json", "sdd/references/x.md"])
def test_check_wheel_rejects_forbidden_paths(tmp_path: Path, planted: str) -> None:
    """C11d: a complete manifest does not excuse a forbidden file in the asset tree."""
    wheel = tmp_path / "ai_parrot-0-py3-none-any.whl"
    manifest = {"schema_version": 1, "assets": [{"source": "sdd/WORKFLOW.md", "target": "sdd/WORKFLOW.md", "hosts": ["claude"]}]}
    with zipfile.ZipFile(wheel, "w") as zf:
        zf.writestr(cas.WHEEL_PREFIX + "manifest.json", json.dumps(manifest))
        zf.writestr(cas.WHEEL_PREFIX + "sdd/WORKFLOW.md", "# ok\n")
        zf.writestr(cas.WHEEL_PREFIX + planted, "secret\n")
    assert cas.check_wheel(wheel) == [f"forbidden in wheel: {cas.WHEEL_PREFIX}{planted}"]


@pytest.mark.parametrize(
    "line",
    [
        "run packages/ai-parrot/src/x.py",  # C16
        "see tests/sdd_scripts/test_x.py",  # C22 second pattern
        'eval "$(python -c "from navconfig import config")"',
        "PYTHONPATH=src pytest",
        "read reference/sdd-insight/x.md",
    ],
)
def test_monorepo_path_is_reported(mini_repo: Path, capsys: pytest.CaptureFixture[str], line: str) -> None:
    """C16 + C22: a shipped source line matching either pattern fails --check."""
    (mini_repo / "sdd/WORKFLOW.md").write_text(line + "\n", encoding="utf-8")
    subprocess.run(["git", "add", "-A"], cwd=mini_repo, check=True)
    _run(mini_repo, "--write")
    assert _run(mini_repo, "--check") == 1
    assert f"monorepo-path: sdd/WORKFLOW.md:1: {line}" in capsys.readouterr().err


def test_allowlisted_hook_line_passes_and_insight_never_ships(mini_repo: Path) -> None:
    """C22 D: the single allowlisted hook line is not a finding; C22: /sdd-insight is never packaged."""
    (target, text), = cas.MONOREPO_PATH_ALLOWLIST
    for rel, body in ((target, text + "\n"), (".claude/commands/sdd-insight.md", "# insight\n")):
        (mini_repo / rel).parent.mkdir(parents=True, exist_ok=True)
        (mini_repo / rel).write_text(body, encoding="utf-8")
    subprocess.run(["git", "add", "-A"], cwd=mini_repo, check=True)
    assert _run(mini_repo, "--write") == 0
    assert _run(mini_repo, "--check") == 0
    targets = {e["target"] for e in json.loads((mini_repo / "assets" / "manifest.json").read_text())["assets"]}
    assert target in targets and ".claude/commands/sdd-insight.md" not in targets


def test_check_wheel_reports_monorepo_path(tmp_path: Path) -> None:
    """C16: the wheel check reads each shipped entry FROM THE WHEEL and flags a monorepo source path."""
    wheel = tmp_path / "ai_parrot-0-py3-none-any.whl"
    manifest = {"schema_version": 1, "assets": [{"source": "sdd/WORKFLOW.md", "target": "sdd/WORKFLOW.md", "hosts": ["claude"]}]}
    hook = 'command: python3 "$CLAUDE_PROJECT_DIR/packages/x.py" --hook'
    with zipfile.ZipFile(wheel, "w") as zf:
        zf.writestr(cas.WHEEL_PREFIX + "manifest.json", json.dumps(manifest))
        zf.writestr(cas.WHEEL_PREFIX + "sdd/WORKFLOW.md", hook + "\n")
    assert cas.check_wheel(wheel) == [f"monorepo-path: sdd/WORKFLOW.md:1: {hook}"]


def test_seed_entry_is_flagged(mini_repo: Path) -> None:
    """C10: sdd/CONVENTIONS.md carries `"seed": true`; nothing else carries the key."""
    (mini_repo / "sdd/CONVENTIONS.md").write_text("# Team conventions\n", encoding="utf-8")
    subprocess.run(["git", "add", "-A"], cwd=mini_repo, check=True)
    _run(mini_repo, "--write")
    manifest = json.loads((mini_repo / "assets" / "manifest.json").read_text())
    by_target = {e["target"]: e for e in manifest["assets"]}
    assert by_target["sdd/CONVENTIONS.md"]["seed"] is True
    assert all("seed" not in e for t, e in by_target.items() if t != "sdd/CONVENTIONS.md")


def test_no_rulebook_and_no_dot_rules_ship() -> None:
    """C10: codebase-conventions.md is packaged for no host; the only rule asset is worktree-management."""
    manifest = json.loads((_REPO_ROOT / "packages/ai-parrot/src/parrot/sdd/_assets/manifest.json").read_text())
    targets = {e["target"] for e in manifest["assets"]}
    assert not any(t.endswith("codebase-conventions.md") for t in targets)
    assert ".claude/rules/worktree-management.md" in targets
    assert ".claude/skills/second-opinion/SKILL.md" in targets          # C9
    assert "sdd/CONVENTIONS.md" in targets                              # C10
    assert not any("sdd-insight" in t for t in targets)                  # rev 0.5 C22
    assert len(targets) == 78                                           # rev 0.5 C22


def test_assets_have_no_publication_findings() -> None:
    """C11c: the committed asset tree has zero org-data / claude-md-ref / branch-literal findings."""
    from parrot.sdd.audit import scan_paths  # TASK-4070

    assets_dir = _REPO_ROOT / "packages/ai-parrot/src/parrot/sdd/_assets"
    findings = scan_paths(sorted(p for p in assets_dir.rglob("*") if p.is_file() and p.name != "manifest.json"))
    bad = [f for f in findings if f.kind in {"org-data", "claude-md-ref", "branch-literal"}]
    assert not bad, [(f.path, f.line, f.kind, f.snippet) for f in bad]


def test_dev_loop_prompts_load_from_packaged_assets() -> None:
    """C2: every dual-sourced prompt is read from parrot/sdd/_assets/claude/agents/; sdd-codereview stays core-only."""
    from importlib.resources import files

    from parrot.flows.dev_flow._subagent_defs import load_subagent_definition as load_flow
    from parrot.flows.dev_loop._subagent_defs import load_subagent_definition as load_loop

    agents = files("parrot.sdd") / "_assets" / "claude" / "agents"
    for name in ("sdd-worker", "sdd-planner", "sdd-secondopinion"):
        body = load_loop(name)
        assert body and body in (agents / f"{name}.md").read_text(encoding="utf-8")
    ideation = load_flow("sdd-ideation")
    assert ideation and ideation in (agents / "sdd-ideation.md").read_text(encoding="utf-8")
    assert load_loop("sdd-codereview")                                   # still served from _subagent_data/
    data_dir = files("parrot.flows.dev_loop") / "_subagent_data"
    assert sorted(p.name for p in data_dir.iterdir() if p.name.endswith(".md")) == ["sdd-codereview.md"]


def test_repo_assets_in_sync() -> None:
    """The committed _assets/ tree matches the monorepo sources (the CI gate, as a test)."""
    assert cas.main(["--check", "--root", str(_REPO_ROOT)]) == 0


def test_package_data_covers_every_manifest_entry() -> None:
    """Every manifest source matches one `"parrot.sdd"` package-data glob in pyproject.toml."""
    pyproject = tomllib.loads((_REPO_ROOT / "packages/ai-parrot/pyproject.toml").read_text())
    patterns = pyproject["tool"]["setuptools"]["package-data"]["parrot.sdd"]
    pkg_dir = _REPO_ROOT / "packages/ai-parrot/src/parrot/sdd"
    covered = {p.relative_to(pkg_dir).as_posix() for pat in patterns for p in pkg_dir.glob(pat) if p.is_file()}
    manifest = json.loads((pkg_dir / "_assets/manifest.json").read_text())
    missing = [e["source"] for e in manifest["assets"] if f"_assets/{e['source']}" not in covered]
    assert not missing, missing
```
**Why**: covers spec §4 `test_asset_sync_check` (divergence fails) plus the packaging
guarantees this task adds (git-tracked only, package-data coverage, deny-list, seed flag, zero
publication findings, single-copy prompts). The last three tests import `parrot.*` — fine in
`tests/`, forbidden in the script.

### Test edits for the moved prompts (C2)
- `tests/flows/dev_loop/test_subagent_parity.py`: delete `test_prompt_parity`, `_NO_REPO_TWIN`,
  `_repo_agents_dir`, `_package_prompts` and the `resources`/`pytest` imports they needed; keep
  `test_research_prompt_has_wiki_block` and `test_worker_prompt_has_per_spec_index_instructions`
  unchanged (they go through `load_subagent_definition`). Rewrite the module docstring: parity
  is now `scripts/sdd/check_asset_sync.py --check` (CI) + `test_repo_assets_in_sync`.
- `tests/flows/dev_flow/test_subagent_defs.py` lines 54 and 267-271: the packaged copy is
  `resources.files("parrot.sdd") / "_assets" / "claude" / "agents" / "sdd-ideation.md"`; the
  assertion message says `_assets/` instead of `_subagent_data/`.
- Every other test that builds a `_subagent_data/<name>.md` path by hand (Files table) points
  at `packages/ai-parrot/src/parrot/sdd/_assets/claude/agents/<name>.md` instead. Behaviour
  asserted by those tests does not change.
- `tests/flows/dev_loop/test_subagent_codereview.py`, `test_subagent_defs.py`,
  `test_subagent_defs_conventions.py`: unchanged (they call the loader).

### FILL IN checklist
- [ ] `check_asset_sync.py::expected_entries` — git ls-files + first-match glob + `seed` + `EXCLUDED_TARGETS` (C22); bounded by "git-tracked only", deterministic order, 78 entries on the repo.
- [ ] `check_asset_sync.py::find_problems` — byte compare, extras, manifest text; bounded by AC-2.
- [ ] `check_asset_sync.py::write_assets` — wholesale regeneration, idempotent; bounded by AC-1.
- [ ] `check_asset_sync.py::check_wheel` — deny-list pass after the completeness pass; bounded by `test_check_wheel_rejects_forbidden_paths`.
- [ ] `check_asset_sync.py::monorepo_path_problems` (C16/C22) — line scan over both patterns + allowlist; bounded by `test_monorepo_path_is_reported` / `test_check_wheel_reports_monorepo_path` / `test_allowlisted_hook_line_passes_and_insight_never_ships`. `MONOREPO_PATH_ALLOWLIST` is fixed by C22 D (the one hook line); add nothing else.
- [ ] `test_divergence_missing_and_extra_fail` — final stderr assertions.
- [ ] Both `load_subagent_definition` edits + module docstrings; bounded by `test_dev_loop_prompts_load_from_packaged_assets`.

---

## Acceptance Criteria

- [ ] `python scripts/sdd/check_asset_sync.py --write` produces `_assets/` with 78 assets +
      `manifest.json` (rev 0.5 C22: no `/sdd-insight` on any host; 14 commands per host); a second
      `--write` leaves `git status` clean (idempotent).
- [ ] *(C16 / rev 0.5 C22)* `--check` and `--wheel` report every shipped line matching
      `MONOREPO_PATH_RE` or the second pattern `tests/sdd_scripts/|\bfrom navconfig\b|PYTHONPATH=|reference/sdd-insight/`
      (`monorepo-path: <target>:<line>: …`), and pass on the repo with the single allowlisted line
      (`.claude/hooks/sdd-worker-format.sh:76`) once TASK-4089's category A–E rewrite has landed.
- [ ] *(rev 0.5 C22 B)* The `sdd/CONVENTIONS.md` seed has `## Repository layout` and `## Project areas`.
- [ ] `python scripts/sdd/check_asset_sync.py` (default `--check`) exits 0 on the repo and exits 1
      naming every diverging / missing / extra file otherwise (spec §5: "`check_asset_sync.py` gates
      CI on `.claude/` ↔ `_assets/` divergence").
- [ ] `manifest.json` matches the brief's format (`schema_version: 1`, `source`/`target`/`hosts`), sorted by target.
- [ ] `uv build --package ai-parrot` produces a wheel for which `check_asset_sync.py --wheel` exits 0
      (codex S8 — installed runtime never depends on a monorepo checkout), and planting any
      deny-listed path in the asset tree makes it exit 1 naming the file (C11d).
- [ ] `ci.yml` runs the sync check, the publication scan (`--fail-on org-data,claude-md-ref,branch-literal`)
      in `lint-and-registry`, and the new `sdd-assets-wheel` job (C11c).
- [ ] No manifest target ends with `codebase-conventions.md`; `sdd/CONVENTIONS.md` is in the manifest
      with `"seed": true` and no other entry carries the key; `.claude/skills/second-opinion/SKILL.md`
      is in the manifest with `hosts == ["claude"]` (C9, C10).
- [ ] `sdd/CONVENTIONS.md` exists in the repo, neutral (names no language, framework or package
      manager) and yields zero scanner findings.
- [ ] `dev_loop/_subagent_data/` contains only `sdd-codereview.md`; `dev_flow/_subagent_data/` is gone;
      both `load_subagent_definition` read `parrot/sdd/_assets/claude/agents/<name>.md`;
      `test_prompt_parity` no longer exists and the full `tests/flows/dev_loop` + `tests/flows/dev_flow`
      suites pass (C2).
- [ ] Ledger `issue:ace18bef4e6e` ("sdd-worker prompt twins drifted: test_prompt_parity[sdd-worker]
      fails on dev (and CI does not run it)") is closed with
      `wikitoolkit ledger close issue:ace18bef4e6e --resolved-by task:TASK-4090 --reason "asset-sync CI
      gate replaces test_prompt_parity"`. The drift itself was re-synced before this task (the `tools:`
      line of the `_subagent_data/` copy). The issue stays open until this task's CI-gated
      `check_asset_sync.py` replaces the parity test that CI never ran.
- [ ] No new runtime dependency; `check_asset_sync.py` imports stdlib only.
- [ ] `ruff check scripts/sdd/check_asset_sync.py tests/sdd_scripts/test_check_asset_sync.py packages/ai-parrot/src/parrot/flows/dev_loop/_subagent_defs.py packages/ai-parrot/src/parrot/flows/dev_flow/_subagent_defs.py` passes.

---

## Validation Commands

Run from the feature worktree with `PYTHONPATH=packages/ai-parrot/src` (the shared venv is
editable-installed against the main checkout).

- `pytest tests/sdd_scripts/test_check_asset_sync.py -q`
- `pytest packages/ai-parrot/tests/flows/dev_loop/test_rules_parity.py -q`
- `pytest packages/ai-parrot/tests/flows/dev_loop/sdd_coder/test_execution_pool_integration.py -q`
- `pytest packages/ai-parrot/tests/flows/dev_loop/sdd_coder/test_review_handoff_contract.py -q`
- `pytest packages/ai-parrot/tests/flows/dev_loop/test_planner_node.py -q`
- `pytest packages/ai-parrot/tests/flows/dev_loop/test_pool_wiring.py -q`
- `pytest packages/ai-parrot/tests/flows/dev_loop/test_secondopinion_brief.py -q`
- `pytest packages/ai-parrot/tests/flows/dev_loop/test_subagent_codereview.py -q`
- `pytest packages/ai-parrot/tests/flows/dev_loop/test_subagent_defs_conventions.py -q`
- `pytest packages/ai-parrot/tests/flows/dev_loop/test_subagent_defs.py -q`
- `pytest packages/ai-parrot/tests/flows/dev_loop/test_subagent_parity.py -q`
- `pytest packages/ai-parrot/tests/flows/dev_flow/test_subagent_defs.py -q`
- `pytest packages/ai-parrot/tests/flows/dev_loop/sdd_coder/test_done_optimization_contract.py -q`
- `pytest tests/sdd_scripts/test_feat699_doc_contract.py tests/sdd_scripts/test_command_contracts.py -q`
Also, outside the pytest contract (the CI gate of C11c): `python -m parrot.sdd.audit packages/ai-parrot/src/parrot/sdd/_assets --root packages/ai-parrot/src/parrot/sdd/_assets --fail-on org-data,claude-md-ref,branch-literal` exits 0.

---

## Test Specification

> Minimal test scaffold. The agent must make these pass.

```python
# tests/sdd_scripts/test_check_asset_sync.py — see the CREATE block above:
#   test_write_then_check_is_clean                 write → check == 0; manifest shape
#   test_divergence_missing_and_extra_fail         spec §4 test_asset_sync_check
#   test_untracked_source_is_not_packaged          git-tracked only
#   test_check_wheel_reports_missing_entry         wheel verifier
#   test_check_wheel_rejects_forbidden_paths       C11d deny-list (parametrized over 5 planted paths)
#   test_monorepo_path_is_reported                 C16 + C22 second pattern in --check (parametrized over 5 lines)
#   test_check_wheel_reports_monorepo_path         C16 monorepo-path in --wheel
#   test_allowlisted_hook_line_passes_and_insight_never_ships  C22 D allowlist + /sdd-insight exclusion
#   test_seed_entry_is_flagged                     C10 `seed: true` only on sdd/CONVENTIONS.md
#   test_no_rulebook_and_no_dot_rules_ship         C9/C10 manifest content
#   test_assets_have_no_publication_findings       C11c zero org-data/claude-md-ref/branch-literal
#   test_dev_loop_prompts_load_from_packaged_assets C2 loaders + _subagent_data/ holds only sdd-codereview.md
#   test_repo_assets_in_sync                       committed tree == sources
#   test_package_data_covers_every_manifest_entry  pyproject globs ⊇ manifest
```

---

## Agent Instructions

When you pick up this task:

1. **Work in the feature worktree** — never on `base_branch`
   (`python -m scripts.sdd.ensure_worktree --slug parrot-installer --feature-id FEAT-633`)
2. **Read the spec** at the path listed above for full context
3. **Check dependencies** — every `Depends-on` task must be `"done"` in the
   per-spec index `sdd/tasks/index/parrot-installer.json`
4. **Verify the Codebase Contract** — before writing ANY code:
   - Confirm every import in "Verified Imports" still exists (`grep` or `read` the source)
   - Confirm every class/method in "Existing Signatures" still has the listed attributes
   - If anything has changed, update the contract FIRST, then implement
   - **NEVER** reference an import, attribute, or method not in the contract without verifying it exists
5. **Update status** in `sdd/tasks/index/parrot-installer.json` → `"in-progress"`
   (set `started_at`) and commit only that index file
6. **Implement** — start from the Implementation Blueprint blocks, complete every
   `# FILL IN:` marker, and never change a signature or path the blueprint fixes
7. **Verify** all acceptance criteria are met — run the Validation Commands
8. **Commit the code** — stage only the files this task lists (never `git add .` / `-A`)
9. **Close the task** with `scripts/sdd/close_task.sh TASK-4090 parrot-installer verified`
   — it moves this file to `sdd/tasks/completed/` and marks it `"done"` in the
   index; never move or copy the file by hand
10. **Fill in the Completion Note** below, then commit the staged SDD state

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**: <session or agent ID>
**Date**: YYYY-MM-DD
**Notes**: What was implemented, any deviations from scope, issues encountered.

**Deviations from spec**: none | describe if any
