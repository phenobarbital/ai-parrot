# TASK-4299: Per-repo SDD configuration — sdd/config.json read by the branch policy

**Feature**: FEAT-633 — Parrot Bootstrap Installer
**Spec**: `sdd/specs/parrot-installer.spec.md` (rev 0.2, §3 M6 amendment **C6**; rev 0.5 **C21**, **C22**, **C24**)
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-4298, TASK-4085
**Assigned-to**: unassigned

---

## Context

Amendment C6 of `sdd/proposals/parrot-installer-amendments.proposal.md` (§2.2-5, §3 C6, §5;
approved 2026-10-14, reduced scope). The shipped SDD commands are hardwired to ai-parrot's
branches (`dev`/`staging`/`main`) and its Jira. A foreign repo using `main` + `develop`
cannot run the flow. The decision: **one** committed, team-owned `sdd/config.json`,
validated with Pydantic, read directly by the shipped commands (they are markdown read by
an LLM) and by the core branch policy. There is **no** generated `sdd/CONFIG.md`.

After TASK-4298 the branch policy has exactly one definition
(`parrot/knowledge/wiki/ledger/sdd_meta.py`: `DEFAULT_FEATURE_BASE`, `DEFAULT_HOTFIX_BASE`,
`WORK_KIND_FLOW`, `FlowMeta._hotfix_implies_main`, `parse()`, `resolve_flow()`). This task
makes that definition read its defaults from the config, keeping today's values as the
fallback when no config exists, and commits ai-parrot's own `sdd/config.json` in the same
change so the monorepo's behaviour does not change.

Downstream consumers (not this task): TASK-4089 rewrites shipped markdown to say "the base
branch in `sdd/config.json`"; TASK-4091 seeds the file on `parrot sdd install`; TASK-4080's
doctor reads `base_branch`; C7 option C / rev 0.5 C21 use `test_command` (TASK-4089 prose,
TASK-4091 install warning); C9 uses `reviewer`; rev 0.5 C22 uses `projects` (TASK-4089/4090 seed).

---

## Amendments — spec rev 0.4 (2026-10-18)

Folded in from `sdd/proposals/parrot-installer-amendments.proposal.md` §3 C17 (decision by
Jesus Lara, 2026-10-18). Every section below is already edited to match.

- **C17 — `brief_meta` CLI.** The shipped `/sdd-brief` (FEAT-698) tells the agent to build
  the per-brief index with `scripts.sdd.brief_meta.write_brief_index` — a Python symbol an
  installed flow cannot import. In the same style as the `sdd_meta` CLI above, give
  `parrot/sdd/scripts/brief_meta.py` (moved by TASK-4085) an argparse `main()` with two
  subcommands: `plan --slug <slug> --key <KEY> --base-branch <base>` → prints
  `brief_worktree_plan(...)` as JSON; `write-index <brief.md> --tasks <tasks.json>
  --worktree-root <dir>` → `parse_brief()` + `write_brief_index()`, prints the written path.
  Add `if __name__ == "__main__": raise SystemExit(main())`. TASK-4089 rewrites the prose
  reference to `parrot sdd run brief_meta write-index …`.

---

## Readiness review — 2026-10-19 (dev 9f51c7735)
- Refreshed against dev 9f51c7735: `sdd_meta` anchors (`resolve_flow` fallback `:309-310`, warning
  `:312-317`), `ensure_worktree.py:21` for the `sdd_meta` import, the six `sdd_meta` one-liners
  (`sdd-task.md:55`, `sdd-done.md:71`, `agents/sdd-worker.md:152`; `parse_taxonomy` at
  `sdd-spec.md:523` and `sdd-tojira.md:145`; `resolve_flow` at `sdd-spec.md:175`); Complexity
  Contract gains the `parrot/sdd/scripts/brief_meta.py` MODIFY target; the C17 AC now names the real
  `WorktreePlan` fields (`name`, `path`, `base_ref`; `sdd_meta.py:328-333`). `sdd/config.json`,
  `parrot/sdd/config.py` and the new names still do not exist on dev.
- Resolved by spec rev 0.5 (2026-10-20):
  - C24 — scope extended: `brief_meta` and `ensure_worktree` (as moved by TASK-4085) read `SddConfig`
    instead of the branch literals TASK-4298 handed over (`brief_meta.py:28,74,98,166`,
    `ensure_worktree.py:304,318`); Scope, Files, Contract, ACs, tests and validation updated.
  - C21 — `test_command` semantics fixed: a shell string, run once with cwd = repo root by its
    consumers (TASK-4089/4091, not this task), non-blank when set; validator, AC and tests added.
  - C22 — `SddConfig.projects: list[str] | None` added: replaces `KNOWN_PROJECTS` when set; unset keeps
    today's warn-never-fail behaviour (`sdd_meta.py:198-199`); field, AC and tests added.

---

## Scope

- Create `packages/ai-parrot/src/parrot/sdd/config.py`:
  - `CONFIG_PATH = Path("sdd/config.json")` (repo-relative).
  - `class SddConfig(BaseModel)` — fields and defaults:
    `base_branch: str = "dev"`, `staging_branch: str | None = None`,
    `hotfix_base: str = "main"`, `issue_tracker: Literal["jira", "none"] = "none"`,
    `jira_host: str | None = None`, `reviewer: Literal["codex", "none"] = "none"`,
    `test_command: str | None = None`, `projects: list[str] | None = None` *(rev 0.5 C22)*.
    `model_config = ConfigDict(extra="forbid")`.
    Validators: every branch name non-blank and without whitespace; `base_branch !=
    hotfix_base`; `staging_branch` differs from both when set; `issue_tracker == "jira"`
    requires `jira_host`; `jira_host` is a bare hostname (no scheme, no path);
    *(rev 0.5 C21)* `test_command`, when set, is non-blank.
  - *(rev 0.5 C21)* `test_command` semantics (field docstring): a shell string that its consumers
    run once with cwd = the repo root. This task only stores and validates it; running it is
    TASK-4089 (shipped prose) and TASK-4091 (install warning when null).
  - *(rev 0.5 C22)* `projects`: when set, it replaces `KNOWN_PROJECTS` as the vocabulary
    `normalize_project` checks; when unset, `KNOWN_PROJECTS` applies and unknown values warn and
    never fail (today's behaviour, `sdd_meta.py:198-199`).
    Resolved (PR #1746 review, 2026-10-20), the same `_config_for` pattern as `resolve_flow`:
    - `normalize_project(raw, *, known: frozenset[str] | None = None)`, where `None` means `KNOWN_PROJECTS`.
    - `parse_taxonomy(doc_path, *, config: SddConfig | None = None)` resolves `cfg = _config_for(doc_path,
      config)` and `known = frozenset(cfg.projects) if cfg.projects else KNOWN_PROJECTS`. It validates with
      `DocTaxonomy.model_validate(data, context={"known_projects": known})`.
    - `DocTaxonomy._norm_projects(cls, value, info: ValidationInfo)` passes
      `(info.context or {}).get("known_projects")` to `normalize_project`.
    - A value outside the configured list **warns, never fails**, exactly like today's `KNOWN_PROJECTS`
      rule (`sdd_meta.py:198-199`).
  - `default_sdd_config() -> SddConfig`.
  - `find_repo_root(start: Path | None = None) -> Path | None`: walk up from `start`
    (default `Path.cwd()`) to the first directory containing `.git` (dir **or** file —
    linked worktrees have a `.git` file).
  - `load_sdd_config(root: Path | None = None) -> SddConfig`: `root or find_repo_root()`;
    file absent → `default_sdd_config()`; present → parse + validate; invalid JSON or
    validation error → raise `SddConfigError(ValueError)` naming the path and the problem.
  - `write_default_config(root: Path) -> Path`: writes `default_sdd_config()` as
    indented JSON with a trailing newline; refuses to overwrite (used by TASK-4091's seed).
- Wire the branch policy (`knowledge/wiki/ledger/sdd_meta.py`):
  - `parse(doc_path, *, config: SddConfig | None = None)` — the no-frontmatter default
    becomes `FlowMeta(type="feature", base_branch=(config or load_sdd_config()).base_branch)`.
  - `resolve_flow(..., config: SddConfig | None = None)` — level 4 default and
    `WORK_KIND_FLOW` bases come from the config (`hotfix_base` for `"bug"`, `base_branch`
    otherwise); precedence (overrides → frontmatter → kind → configured default) unchanged.
  - `FlowMeta` gains `hotfix_base: str = Field(default=DEFAULT_HOTFIX_BASE, exclude=True)`;
    `_hotfix_implies_main` compares `base_branch` with `self.hotfix_base`. `parse()` /
    `resolve_flow()` pass the configured value in; `emit()` never writes it.
  - `KNOWN_BRANCHES` soft warning: the configured branches count as known
    (`known = KNOWN_BRANCHES | {cfg.base_branch, cfg.hotfix_base, cfg.staging_branch}`).
- `plan_worktree()` is unchanged (`origin/<meta.base_branch>` already follows the meta).
- *(rev 0.5 C24)* **Brief and worktree helpers read `SddConfig`** instead of branch literals, in the
  files TASK-4085 moved to `packages/ai-parrot/src/parrot/sdd/scripts/` (line numbers below are
  today's `scripts/sdd/` ones; the move changes only import lines):
  - `brief_meta.py:28` `BRIEF_BASE_BRANCHES = frozenset({"main", "dev", "staging"})` (enforced by
    `_check_base_branch`, `:45-55`) → the configured `{hotfix_base, base_branch, staging_branch}`
    (`staging_branch` only when set);
  - `brief_meta.py:74` `BriefMeta.base_branch: str = "main"` → default `hotfix_base`;
  - `brief_meta.py:98` ledger-sourced brief requires `"dev"` → requires `base_branch`;
  - `brief_meta.py:166` `"hotfix"` prefix iff base is `"main"` → iff base is `hotfix_base`;
  - `ensure_worktree.py:304` `--brief-key` default `"main"` and `:318` `--jira-key` ⇒ `"main"` →
    `hotfix_base`.
  With ai-parrot's config (or no config) every value equals today's literal, so behaviour and the
  `ensure_worktree` CLI (flags, help, output) are unchanged.
  Resolved (PR #1746 review, 2026-10-20):
  - `brief_worktree_plan(*, slug, key, base_branch, config: SddConfig | None = None)`, where `None` means
    `load_sdd_config()` from the current repository root.
  - `BriefMeta` gets its config through pydantic's validation context:
    `BriefMeta.model_validate(data, context={"sdd_config": cfg})`. A `model_validator(mode="before")`
    fills a missing `base_branch` with `cfg.hotfix_base`, replacing the `"main"` field default at `:74`.
    The `base_branch` validator checks membership in the config-derived set.
  - `ensure_worktree.main()` loads the config **once** from the root it already uses (`Path.cwd()`,
    `:343`) and passes `config=cfg` both to `brief_worktree_plan` and to the `--brief-key` / `--jira-key`
    defaults (`:304`, `:318`).
- **Q1 residual — a CLI for `sdd_meta`.** Six shipped one-liners import `sdd_meta` inline
  (`python -c "from scripts.sdd.sdd_meta import parse …"` ×3 in `sdd-task.md:55`,
  `sdd-done.md:71` and `agents/sdd-worker.md:152`, `parse_taxonomy` ×2 at `sdd-spec.md:523` and
  `sdd-tojira.md:145`, `resolve_flow` ×1 at `sdd-spec.md:175` — re-verified 2026-10-19). They
  cannot go through `parrot sdd run` because the module has no
  `main()`. Give `parrot/sdd/scripts/sdd_meta.py` (TASK-4085's re-export module) an
  argparse `main()` with three subcommands, output designed for the shell callers:
  - `parse <doc>` → prints `<type> <base_branch>` on one line (what `sdd-task.md:55-57`
    awk-splits today);
  - `taxonomy <doc>` → prints `{"projects": [...], "tags": [...]}` as JSON;
  - `resolve-flow [--kind K] [--doc PATH] [--type T] [--base B]` → prints
    `{"type": …, "base_branch": …}` as JSON (calls `resolve_flow(config=None)`).
  Add `if __name__ == "__main__": raise SystemExit(main())`. TASK-4089 rewrites the six
  one-liners to `parrot sdd run sdd_meta parse|taxonomy|resolve-flow …`.
- `scripts/sdd/sdd_meta.py` and `parrot/sdd/scripts/sdd_meta.py` (TASK-4085): no new
  names to re-export; verify they still import.
- Commit ai-parrot's own `sdd/config.json`:
  `{"base_branch": "dev", "staging_branch": "staging", "hotfix_base": "main",
  "issue_tracker": "jira", "jira_host": "trocglobal.atlassian.net", "reviewer": "codex",
  "test_command": null}`. `projects` stays unset, so `KNOWN_PROJECTS` keeps applying (C22).
- Tests (see Test Specification).

**NOT in scope**:
- Rewriting any markdown under `.claude/`, `.agent/`, `sdd/` (TASK-4089).
- Seeding the config on install, `--dry-run` listing, status (TASK-4091).
- Doctor checks (TASK-4080), test-selection behaviour (C7 lives in TASK-4089's wording of
  the shipped commands), the `second-opinion` conditional (TASK-4089/4090).
- A `sync_down` field or any rendered `sdd/CONFIG.md` (rejected, proposal §5).
- Reading environment variables for any field (secrets stay out of this file by design:
  `jira_host` is a hostname, not a credential).
- Running `test_command` or switching any test step on it (C21: TASK-4089, TASK-4091).
- The `sdd/CONVENTIONS.md` `## Project areas` seed section (C22: TASK-4089/4090).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/sdd/config.py` | CREATE | `SddConfig`, `SddConfigError`, `CONFIG_PATH`, `default_sdd_config`, `find_repo_root`, `load_sdd_config`, `write_default_config` |
| `packages/ai-parrot/src/parrot/knowledge/wiki/ledger/sdd_meta.py` | MODIFY | `config` keyword on `parse`/`resolve_flow`; `FlowMeta.hotfix_base`; configured defaults; configured `projects` vocabulary (rev 0.5 C22) |
| `packages/ai-parrot/src/parrot/sdd/scripts/sdd_meta.py` | MODIFY | add argparse `main()` (`parse` / `taxonomy` / `resolve-flow`) to the TASK-4085 re-export module |
| `packages/ai-parrot/src/parrot/sdd/scripts/brief_meta.py` | MODIFY | add argparse `main()` (`plan` / `write-index`) to the module TASK-4085 moved (rev 0.4 C17); branch literals → `SddConfig` (rev 0.5 C24) |
| `packages/ai-parrot/src/parrot/sdd/scripts/ensure_worktree.py` | MODIFY | `--brief-key` / `--jira-key` `"main"` defaults → `SddConfig.hotfix_base` (rev 0.5 C24; module moved by TASK-4085) |
| `sdd/config.json` | CREATE | ai-parrot's own configuration (values above) |
| `packages/ai-parrot/tests/sdd/test_config.py` | CREATE | model, loader, root discovery, writer |
| `tests/sdd_scripts/test_sdd_meta_config_defaults.py` | CREATE | policy follows the config; absent config keeps today's behaviour |

---

## Codebase Contract (Anti-Hallucination)

Verified on `dev` @ `ad54fde59` (2026-10-14), re-verified on `dev` @ `9f51c7735` (2026-10-19);
TASK-4298 additions assumed landed.

### Verified Imports
```python
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator   # pydantic v2 (sdd_meta.py:21 already uses BaseModel/Field/field_validator/model_validator)
from parrot.knowledge.wiki.ledger.sdd_meta import (
    KNOWN_BRANCHES, WORK_KIND_FLOW, FlowMeta, parse, resolve_flow, plan_worktree,   # :30, :35, :99, :129, :263, :336
    DEFAULT_FEATURE_BASE, DEFAULT_HOTFIX_BASE, read_declared_base_branch,           # TASK-4298
)
```

### Existing Signatures
```python
class FlowMeta(BaseModel):                       # sdd_meta.py:99
    type: Literal["feature", "hotfix"]
    base_branch: str
    @model_validator(mode="after")
    def _hotfix_implies_main(self) -> "FlowMeta": # :106 — raises ValueError when hotfix and base != "main"
def parse(doc_path: Path) -> FlowMeta:           # :129 — default at :152
def emit(meta: FlowMeta) -> str:                 # :156 — renders `type:` and `base_branch:` only
def resolve_flow(*, kind=None, doc_path=None, type_override=None, base_branch_override=None) -> FlowMeta:  # :263
#   final_type = type_override or resolved_type or "feature"; final_base = ... or "dev"  (:309-310)
#   warning when final_base not in KNOWN_BRANCHES (:312-317)
KNOWN_PROJECTS: frozenset[str] = frozenset(...)  # :45 (rev 0.5 C22: replaced by SddConfig.projects when set)
def normalize_project(raw: str) -> str:          # :188 — warns (never raises) when not in KNOWN_PROJECTS (:198-199)
# parrot/sdd/__init__.py — docstring-only package root (TASK-4070); parrot/sdd/scripts/ (TASK-4085)

# rev 0.5 C24 — branch literals to replace (re-verified 2026-10-20 on dev 0263f0724; moved by TASK-4085
# to packages/ai-parrot/src/parrot/sdd/scripts/, import lines only):
# scripts/sdd/brief_meta.py
BRIEF_BASE_BRANCHES: frozenset[str] = frozenset({"main", "dev", "staging"})          # :28
def _check_base_branch(base_branch: str) -> str:                                     # :45-55 — raises outside the set
class BriefMeta(BaseModel): ... base_branch: str = "main"                            # :68, :74
    def _ledger_implies_dev(self) -> "BriefMeta": ... != "dev"                       # :95-100 (literal :98)
def brief_worktree_plan(*, slug: str, key: str, base_branch: str) -> WorktreePlan:   # :150 — prefix "hotfix" iff "main" :166
def plan_brief_worktree(meta: BriefMeta) -> WorktreePlan:                            # :175
# scripts/sdd/ensure_worktree.py
#   :301-305  brief_worktree_plan(slug=..., key=args.brief_key, base_branch=args.base_branch or "main")   (literal :304)
#   :315-318  if args.jira_key and not type_override: type_override = "hotfix"; base_branch_override = "main" (:318)
#   :343      repo_root = Path.cwd()
```

### Callers that must keep working (behaviour identical with ai-parrot's config)
- `scripts/sdd/ensure_worktree.py:21` — `resolve_flow`, `plan_worktree` (moved to
  `parrot/sdd/scripts/ensure_worktree.py` by TASK-4085).
- `scripts/sdd/worktree_status.py:21`, `scripts/sdd/doc_taxonomy.py:21`, `scripts/sdd/backfill_taxonomy.py:19`.
- `packages/ai-parrot/src/parrot/knowledge/wiki/ledger/sdd_ingest.py:20-21` — `parse` as `parse_spec_meta`.
- `flows/dev_loop/nodes/{research,feature_handoff,base}.py` — via TASK-4298's names.
- Tests: `tests/sdd_scripts/test_sdd_meta_resolve_flow.py` (kind mapping, missing doc, precedence, `hotfix_off_main_is_rejected`, `unknown_branch_warns_but_succeeds`), `test_worktree_plan.py`, `test_command_contracts.py`, `test_ensure_worktree.py`; *(rev 0.5 C24)* `test_brief_meta.py`, `test_brief_scaffold_integration.py`, `test_brief_template_contract.py`.

### Does NOT Exist (create here)
- ~~`parrot/sdd/config.py`, `SddConfig`, `load_sdd_config`, `find_repo_root`, `sdd/config.json`~~ — new in this task.
- ~~`FlowMeta.hotfix_base`, a `config` parameter on `parse`/`resolve_flow`~~ — new in this task.
- ~~`SddConfig.projects`~~ — new in this task (rev 0.5 C22).
- ~~`sdd/CONFIG.md`, `sync_down`~~ — rejected; never create.
- ~~`sdd_meta.resolve_flow` "does not exist"~~ — it exists (`:263`); an early amendment draft said otherwise and was corrected.

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {"path": "packages/ai-parrot/src/parrot/sdd/config.py", "action": "CREATE"},
    {"path": "packages/ai-parrot/src/parrot/knowledge/wiki/ledger/sdd_meta.py", "action": "MODIFY"},
    {"path": "sdd/config.json", "action": "CREATE"},
    {"path": "packages/ai-parrot/src/parrot/sdd/scripts/sdd_meta.py", "action": "MODIFY"},
    {"path": "packages/ai-parrot/src/parrot/sdd/scripts/brief_meta.py", "action": "MODIFY"},
    {"path": "packages/ai-parrot/src/parrot/sdd/scripts/ensure_worktree.py", "action": "MODIFY"},
    {"path": "packages/ai-parrot/tests/sdd/test_config.py", "action": "CREATE"},
    {"path": "tests/sdd_scripts/test_sdd_meta_config_defaults.py", "action": "CREATE"}
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot/src/parrot/knowledge/wiki/ledger/sdd_meta.py#FlowMeta",
    "sym:packages/ai-parrot/src/parrot/knowledge/wiki/ledger/sdd_meta.py#parse",
    "sym:packages/ai-parrot/src/parrot/knowledge/wiki/ledger/sdd_meta.py#emit",
    "sym:packages/ai-parrot/src/parrot/knowledge/wiki/ledger/sdd_meta.py#resolve_flow",
    "sym:packages/ai-parrot/src/parrot/knowledge/wiki/ledger/sdd_meta.py#plan_worktree",
    "sym:packages/ai-parrot/src/parrot/knowledge/wiki/ledger/sdd_meta.py#KNOWN_BRANCHES",
    "sym:packages/ai-parrot/src/parrot/knowledge/wiki/ledger/sdd_meta.py#WORK_KIND_FLOW",
    "sym:scripts/sdd/ensure_worktree.py#main",
    "sym:packages/ai-parrot/src/parrot/knowledge/wiki/ledger/sdd_ingest.py#parse_spec_meta",
    "sym:packages/ai-parrot/src/parrot/knowledge/wiki/ledger/sdd_meta.py#normalize_project",
    "sym:scripts/sdd/brief_meta.py#BriefMeta",
    "sym:scripts/sdd/brief_meta.py#brief_worktree_plan"
  ]
}
```

---

## Implementation Notes

- **Import direction**: `parrot.sdd.config` imports stdlib + pydantic only. `sdd_meta`
  imports `parrot.sdd.config` at module level (both core; `parrot/sdd/__init__.py` has no
  imports, so no cycle). Never import `sdd_meta` from `config.py`.
- **Loading is lazy and cheap**: `parse()` / `resolve_flow()` call `load_sdd_config()` only
  when `config is None`; a missing file costs one `stat` per call — acceptable; do not add
  module-level caching (tests monkeypatch cwd).
- **Root discovery vs `doc_path`**: when `doc_path` is given, discover the root from
  `doc_path.parent`, else from `cwd`. This is what makes `resolve_flow(doc_path=…)` work
  from a worktree whose config is the worktree's own committed copy.
- **Errors are loud**: a malformed `sdd/config.json` raises `SddConfigError`; callers that
  are CLIs (`ensure_worktree`) already surface exceptions. Absence is never an error.
- **`emit()` stays symmetric**: it must not render `hotfix_base`; round-trip tests in
  `tests/sdd_scripts/` assert the exact frontmatter text.
- **Warnings**: `resolve_flow`'s "not one of the canonical branches" warning must not fire
  for a foreign repo's configured branches (`main`/`develop`) — extend the known set with the
  configured values.
- **ai-parrot's config lands here**, in the same commit as the policy change (spec §7
  integration risk); without it the monorepo's flow would still work (defaults equal
  today's values) but the "one source" claim would be false.
- Follow `.claude/rules/codebase-conventions.md` (Google docstrings, strict hints, 120 cols,
  Pydantic v2, no `print`).

---

## Implementation Blueprint

```python
# packages/ai-parrot/src/parrot/sdd/config.py
"""Per-repository SDD configuration (`sdd/config.json`) — FEAT-633 rev 0.2, amendment C6."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, ValidationError, field_validator, model_validator

CONFIG_PATH = Path("sdd/config.json")
_BRANCH_FIELDS = ("base_branch", "staging_branch", "hotfix_base")


class SddConfigError(ValueError):
    """Raised when ``sdd/config.json`` exists but cannot be used."""


class SddConfig(BaseModel):
    """Team-owned SDD settings. Secrets never belong here."""

    model_config = ConfigDict(extra="forbid")

    base_branch: str = "dev"
    staging_branch: str | None = None
    hotfix_base: str = "main"
    issue_tracker: Literal["jira", "none"] = "none"
    jira_host: str | None = None
    reviewer: Literal["codex", "none"] = "none"
    test_command: str | None = None          # rev 0.5 C21: shell string, run once with cwd = repo root (by TASK-4089/4091 consumers)
    projects: list[str] | None = None        # rev 0.5 C22: replaces sdd_meta.KNOWN_PROJECTS when set

    @field_validator("test_command")
    @classmethod
    def _non_blank_command(cls, value: str | None) -> str | None:
        # FILL IN: None passes; reject a blank / whitespace-only string (rev 0.5 C21); keep the value otherwise
        ...

    @field_validator(*_BRANCH_FIELDS)
    @classmethod
    def _branch_name(cls, value: str | None) -> str | None:
        # FILL IN: None passes; otherwise strip, reject blank / whitespace / leading "origin/"
        ...

    @field_validator("jira_host")
    @classmethod
    def _bare_hostname(cls, value: str | None) -> str | None:
        # FILL IN: reject "://", "/", whitespace; lower-case
        ...

    @model_validator(mode="after")
    def _lanes(self) -> "SddConfig":
        # FILL IN: base_branch != hotfix_base; staging_branch not in {base_branch, hotfix_base};
        #          issue_tracker == "jira" requires jira_host
        return self


def default_sdd_config() -> SddConfig: ...
def find_repo_root(start: Path | None = None) -> Path | None: ...   # walk up; `.git` dir OR file
def load_sdd_config(root: Path | None = None) -> SddConfig: ...     # absent → defaults; bad → SddConfigError
def write_default_config(root: Path) -> Path: ...                   # refuses to overwrite
```

```python
# knowledge/wiki/ledger/sdd_meta.py — deltas
from parrot.sdd.config import SddConfig, load_sdd_config

class FlowMeta(BaseModel):
    type: Literal["feature", "hotfix"]
    base_branch: str
    hotfix_base: str = Field(default=DEFAULT_HOTFIX_BASE, exclude=True)

    @model_validator(mode="after")
    def _hotfix_implies_main(self) -> "FlowMeta":
        if self.type == "hotfix" and self.base_branch != self.hotfix_base:
            raise ValueError(f"type='hotfix' requires base_branch={self.hotfix_base!r} (got base_branch={self.base_branch!r})")
        return self

def _config_for(doc_path: Path | None, config: SddConfig | None) -> SddConfig:
    if config is not None:
        return config
    return load_sdd_config(find_repo_root(doc_path.parent) if doc_path is not None else None)

def parse(doc_path: Path, *, config: SddConfig | None = None) -> FlowMeta:
    cfg = _config_for(doc_path, config)
    block = _read_frontmatter(doc_path)
    if block is None:
        return FlowMeta(type="feature", base_branch=cfg.base_branch, hotfix_base=cfg.hotfix_base)
    return FlowMeta(**block, hotfix_base=cfg.hotfix_base)

def resolve_flow(*, kind=None, doc_path=None, type_override=None, base_branch_override=None,
                 config: SddConfig | None = None) -> FlowMeta:
    cfg = _config_for(doc_path, config)
    # ... as today, but:
    #   kind mapping → (flow_type, cfg.hotfix_base if flow_type == "hotfix" else cfg.base_branch)
    #   final_base = base_branch_override or resolved_base or cfg.base_branch
    #   known = KNOWN_BRANCHES | {b for b in (cfg.base_branch, cfg.hotfix_base, cfg.staging_branch) if b}
    #   return FlowMeta(type=final_type, base_branch=final_base, hotfix_base=cfg.hotfix_base)

# rev 0.5 C22 — normalize_project's vocabulary: cfg.projects when set, else KNOWN_PROJECTS; warning only.
#   normalize_project(raw, *, known=None); parse_taxonomy(doc_path, *, config=None) → _config_for → known set →
#   DocTaxonomy.model_validate(data, context={"known_projects": known}); _norm_projects reads info.context.
#   Outside the configured list → warning only (PR #1746 review).
```

```python
# rev 0.5 C24 — parrot/sdd/scripts/brief_meta.py and ensure_worktree.py (after TASK-4085's move), literal → SddConfig:
#   brief_meta :28  BRIEF_BASE_BRANCHES           → {cfg.hotfix_base, cfg.base_branch} | ({cfg.staging_branch} if set)
#   brief_meta :74  BriefMeta.base_branch = "main" → cfg.hotfix_base
#   brief_meta :98  ledger brief != "dev"          → != cfg.base_branch
#   brief_meta :166 "hotfix" iff == "main"         → iff == cfg.hotfix_base (else "fix")
#   ensure_worktree :304 / :318 "main"             → cfg.hotfix_base
#   brief_worktree_plan(*, slug, key, base_branch, config=None) (None → load_sdd_config());
#   BriefMeta.model_validate(data, context={"sdd_config": cfg}) + model_validator(mode="before") default for
#   base_branch; ensure_worktree.main() loads cfg once from its root (Path.cwd(), :343) and passes it down.
```

---

## Acceptance Criteria

- [ ] `SddConfig()` equals today's policy (`dev`/`main`, no tracker, no reviewer); `extra="forbid"` rejects unknown keys; `base_branch == hotfix_base` and `issue_tracker: jira` without `jira_host` are rejected with clear messages.
- [ ] `load_sdd_config(tmp_repo)` with no file → defaults; with a valid file → values; with invalid JSON or a validation error → `SddConfigError` naming the file.
- [ ] `find_repo_root` finds a `.git` directory and a `.git` *file* (linked worktree); returns `None` outside any repo.
- [ ] With `sdd/config.json` = `{"base_branch": "develop", "hotfix_base": "main"}`: `resolve_flow(kind="enhancement")` → `develop`; `resolve_flow(kind="bug")` → `("hotfix", "main")`; `resolve_flow()` → `develop`; `parse(doc_without_frontmatter)` → `develop`; no "not canonical" warning for `develop`; `FlowMeta(type="hotfix", base_branch="develop", hotfix_base="main")` raises.
- [ ] With `hotfix_base: "release"`: a hotfix doc declaring `base_branch: release` parses; one declaring `main` is rejected.
- [ ] Absent config: every test in `tests/sdd_scripts/` passes unmodified; `emit()` output is byte-identical to today.
- [ ] `sdd/config.json` for ai-parrot is committed and `load_sdd_config(Path("."))` from the repo root returns `dev`/`staging`/`main`, `jira`, `trocglobal.atlassian.net`, `codex`.
- [ ] `python -m parrot.sdd.scripts.sdd_meta parse sdd/specs/parrot-installer.spec.md` prints `feature dev`; `taxonomy` prints the spec's projects/tags JSON; `resolve-flow --kind bug` prints `{"type": "hotfix", "base_branch": "main"}`; the re-export names are unchanged.
- [ ] `ruff check` passes; no cyclic import (`python -c "import parrot.sdd.config, parrot.knowledge.wiki.ledger.sdd_meta"`).
- [ ] *(rev 0.4 C17)* `python -m parrot.sdd.scripts.brief_meta plan --slug crew-guards --key NAV-1 --base-branch main`
      prints the `WorktreePlan` JSON (`name` = `hotfix-NAV-1-crew-guards`, `path` =
      `.claude/worktrees/hotfix-NAV-1-crew-guards`, `base_ref` = `origin/main`); `write-index <brief.md>
      --tasks <tasks.json> --worktree-root <dir>` writes the per-brief index and prints its path;
      `--help` exits 0 from a foreign cwd; an unknown subcommand exits 2; the module's existing names are unchanged.
- [ ] *(rev 0.5 C21)* `SddConfig(test_command="")` and `SddConfig(test_command="   ")` are rejected; a set
      value (e.g. `"make test && echo ok"`) is stored unchanged; `None` is the default.
- [ ] *(rev 0.5 C22)* `SddConfig().projects is None`; with `projects` unset, an unknown project warns and does
      not fail (as today); with `projects: ["billing"]` set, `billing` (not in `KNOWN_PROJECTS`) is accepted
      without a warning.
- [ ] *(rev 0.5 C24)* With `{"base_branch": "develop", "hotfix_base": "main"}`: `brief_worktree_plan(...,
      base_branch="develop")` is accepted and planned as `fix-<KEY>-<slug>` on `origin/develop`; a ledger-sourced
      brief requires `develop`; `BriefMeta` defaults `base_branch` to `main`; `ensure_worktree --brief-key K`
      without `--base-branch` (and `--jira-key K` without `--type`) plans on `origin/main`. With
      `hotfix_base: "release"`, the brief default and both `ensure_worktree` defaults are `release`. Absent
      config: `test_brief_meta.py`, `test_brief_scaffold_integration.py`, `test_brief_template_contract.py`
      and `test_ensure_worktree.py` pass unmodified.

---

## Validation Commands

Run from the feature worktree with `PYTHONPATH=packages/ai-parrot/src` (the shared venv is
editable-installed against the main checkout).

- `pytest packages/ai-parrot/tests/sdd/test_config.py -q`
- `pytest tests/sdd_scripts/test_sdd_meta_config_defaults.py -q`
- `pytest tests/sdd_scripts/test_sdd_meta_resolve_flow.py -q`
- `pytest tests/sdd_scripts/test_sdd_meta_branch_policy.py -q`
- `pytest tests/sdd_scripts/test_worktree_plan.py -q`
- `pytest tests/sdd_scripts/test_command_contracts.py -q`
- `pytest tests/sdd_scripts/test_ensure_worktree.py -q`
- `pytest tests/sdd_scripts/test_brief_meta.py -q` (rev 0.5 C24)
- `pytest tests/sdd_scripts/test_brief_scaffold_integration.py -q` (rev 0.5 C24)
- `pytest tests/sdd_scripts/test_brief_template_contract.py -q` (rev 0.5 C24)

Also, outside the pytest contract: `ruff check packages/ai-parrot/src/parrot/sdd/config.py packages/ai-parrot/src/parrot/knowledge/wiki/ledger/sdd_meta.py`;
`python -c "from parrot.sdd.config import load_sdd_config; from pathlib import Path; print(load_sdd_config(Path('.')).model_dump())"`
prints ai-parrot's values; `python -m scripts.sdd.ensure_worktree --help` still works; and
`python -m parrot.sdd.scripts.sdd_meta parse sdd/specs/parrot-installer.spec.md` prints `feature dev`.

---

## Test Specification

### `packages/ai-parrot/tests/sdd/test_config.py` (CREATE)
- `test_defaults_match_today`, `test_extra_keys_rejected`, `test_base_equals_hotfix_rejected`,
  `test_staging_collides_rejected`, `test_jira_requires_host`, `test_jira_host_bare_hostname`
  (`https://x.atlassian.net` rejected, `x.atlassian.net` accepted), `test_branch_blank_rejected`.
- *(rev 0.5 C21/C22)* `test_test_command_blank_rejected` (`""`, `"   "`), `test_test_command_kept_verbatim`,
  `test_projects_default_none`, `test_projects_list_accepted`.
- `test_load_absent_is_default`, `test_load_valid`, `test_load_invalid_json_raises`,
  `test_load_validation_error_raises` (message contains the path).
- `test_find_repo_root_git_dir`, `test_find_repo_root_git_file` (write a `.git` file with
  `gitdir: …`), `test_find_repo_root_none` (`tmp_path` without `.git`).
- `test_write_default_config_refuses_overwrite`.
- CLI (`parrot.sdd.scripts.sdd_meta.main`, via `capsys`): `test_cli_parse_prints_type_and_base`,
  `test_cli_taxonomy_json`, `test_cli_resolve_flow_json`, `test_cli_unknown_subcommand_exits_2`.
- CLI (`parrot.sdd.scripts.brief_meta.main`, via `capsys` + `tmp_path`; rev 0.4 C17):
  `test_brief_cli_plan_json`, `test_brief_cli_write_index_writes_file`,
  `test_brief_cli_unknown_subcommand_exits_2`.

### `tests/sdd_scripts/test_sdd_meta_config_defaults.py` (CREATE)
Fixture `foreign_repo(tmp_path, monkeypatch)`: `.git/` dir, `sdd/config.json` with
`develop`/`main`, `monkeypatch.chdir`. Cases: the four `resolve_flow` bullets of the
Acceptance Criteria, `parse` default, explicit `config=` beats discovery, `hotfix_base:
release` both ways, `caplog` has no "canonical branches" warning for `develop`, and
`emit(resolve_flow(...))` contains no `hotfix_base` line.
*(rev 0.5 C22)* `parse_taxonomy` with `projects: ["billing"]` → no "Unknown SDD project" warning for
`billing`; without `projects` → the warning fires and nothing raises.
*(rev 0.5 C24)* the `brief_meta` / `ensure_worktree` bullets of the Acceptance Criteria (call
`ensure_worktree.main([... "--dry-run", "--json", "--no-sync"])` in the fixture repo).

---

## Agent Instructions

1. TASK-4298 must be `done` (its constants and `read_declared_base_branch` exist); confirm in
   the index before starting.
2. Create `config.py` with its tests first; keep it stdlib + pydantic.
3. Wire `sdd_meta` (blueprint); run `tests/sdd_scripts` without any `sdd/config.json` present
   in `tmp` fixtures — they must pass unmodified.
4. Add `sdd/config.json` for ai-parrot (exact values above; 2-space JSON, trailing newline).
5. Run the Validation Commands; `ruff check --fix` touched files.
6. Commit only the listed files: `feat(parrot-installer): TASK-4299 — per-repo SDD configuration (sdd/config.json)`.
7. Close with `scripts/sdd/close_task.sh TASK-4299 parrot-installer verified`.

---

## Completion Note

**Completed by**: sdd-worker (claude-sonnet-5-5)
**Date**: 2026-10-26
**Notes**: Implemented SddConfig/loader/writer, wired sdd_meta (parse/resolve_flow/parse_taxonomy config kw, FlowMeta.hotfix_base, normalize_project known=), brief_meta + ensure_worktree read config, argparse CLIs for sdd_meta and brief_meta, committed sdd/config.json. All 10 validation test files pass (29+9 new tests); ruff clean on .py files; CLI acceptance outputs verified. Unverified: ruff on sdd/config.json is meaningless (JSON).

**Deviations from spec**: none
