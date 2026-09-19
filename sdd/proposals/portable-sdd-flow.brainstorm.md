---
title: "Portable SDD Flow"
slug: portable-sdd-flow
type: feature
status: accepted
created: 2026-09-19
---

# Portable SDD Flow — Brainstorm

## Problem

The SDD scripts live at `scripts/sdd/` (repo root) rather than in a proper
Python package. When the SDD flow needs to be reused in another repository,
one must manually copy `scripts/sdd/`, the `.claude/commands/sdd-*.md` files,
`.claude/agents/sdd-*.md`, `sdd/templates/`, and assorted rules/workflows —
with no installer, no manifest, and no way to keep them in sync with upstream.

The ask: `sdd claude install` (and `sdd codex install`, `sdd google install`)
copies the SDD flow into any repo from an installed Python package, while
ai-parrot itself uses symlinks so the package *is* the source of truth.

---

## Section 1: Architecture & module layout

### New distribution: `ai-parrot-sdd` → top-level `parrot_sdd`

Dependencies: `pydantic`, `pyyaml`. It does **not** depend on `ai-parrot`;
the dependency runs the other way, and only ever as a lazy, optional import.

```
packages/ai-parrot-sdd/
  pyproject.toml                    deps: pydantic, pyyaml
  src/parrot_sdd/
    meta.py                         <- MOVED from parrot.knowledge.wiki.ledger.sdd_meta
    scripts/                        <- MOVED from scripts/sdd/ (18 modules)
      ensure_worktree.py  reserve_ids.py  id_ledger.py  check_id_collisions.py
      check_task_graph.py lint_new.py     select_tests.py worktree_status.py
      insight.py          doc_taxonomy.py backfill_taxonomy.py migrate_index.py
      tag_yaml_fixtures.py
      sh/                           close_task.sh heal_orphans.sh codex_hook.sh
    assets/
      generic/    commands/ agents/ rules/ templates/ workflows/
      templated/
      seeds/
    config.py                       .parrot/sdd.json load/validate (pydantic)
    install.py                      install_sdd(root, config) -> list[str]
    cli.py                          Click CLI: sdd claude/codex/google install
  tests/                            <- MOVED from tests/sdd_scripts/
```

### Three dependency seams, all one-directional

| Edge | Mechanism | Failure mode |
|---|---|---|
| core `ledger/sdd_ingest.py` → `parrot_sdd.meta` | lazy import | SDD doc ingest degrades to skip; a repo with no `sdd/` tree loses nothing |
| `parrot_sdd` → `ai-parrot` | **none** | — |

### Two things deliberately do *not* move

- `scripts/sdd/calibrate_rlimit_as.py` — it imports `parrot.tools.repl_worker`
  and `sys.path`-hacks into `packages/ai-parrot/src`. It's an rlimit-tuning
  tool, not SDD lane. Stays at `scripts/` root.
- `scripts/sdd/.collision_baseline.json` — repo-specific data, stays next to
  the `sdd/` tree.

### CLI surface — three surfaces, one implementation

```
                 sdd claude install          ← satellite's own binary
                 sdd codex  install          ← per-host variant
                 sdd google install          ← per-host variant
                          │
                          └──► parrot_sdd.install.install_sdd(root, host, config) -> list[str]
```

| Surface | Ships in | Use |
|---|---|---|
| `sdd claude …` | `ai-parrot-sdd` `[project.scripts]` | daily driver, also works standalone |
| `sdd codex …` | same package | installs codex-specific assets |
| `sdd google …` | same package | installs google/agy-specific assets |
| `sdd status` | same package | show installed manifest |
| `sdd uninstall` | same package | remove installed files |

**Decision**: Core `ai-parrot` has **zero** SDD awareness at the CLI level.
`parrot claude install` handles wiki + hooks only. The satellite owns the
`sdd` binary exclusively.

### Invocation changes

`python -m scripts.sdd.X` → `python -m parrot_sdd.scripts.X`, which works
from **any** CWD in **any** repo — fixing the current PEP-420 namespace trick
that silently requires CWD = repo root.

---

## Section 2: Install contract & templating

### CLI verbs

```
sdd claude install [--path .] [--dry-run] [--force]
sdd codex  install
sdd google install
sdd status | uninstall
```

Each host installs **shared tier + that host's tier**. `install_sdd(root,
host, config) -> list[str]` is the single implementation; the CLI is a thin
shell over it.

### Idempotency & ownership

Install writes `.parrot/sdd-manifest.json` — every file it created, with a
content hash. `uninstall` removes only files whose hash still matches and
*reports* locally-modified ones instead of deleting them; re-`install` skips
unchanged files and needs `--force` to overwrite a modified one.

### No jinja2

Substitution is scalar-only, so a ~30-line regex renderer keeps deps at
`pydantic` + `pyyaml`.

### Asset tiers

| Tier | Install action | Count |
|---|---|---|
| `generic/` | verbatim copy (or symlink in ai-parrot) | ~29 files |
| `templated/` | render `{{base_branch}}` etc. from config | ~15 files |
| `seeds/` | skeleton + TODO (rewrite per repo) | ~1 file |

### Config: one generated file, not fifteen templated ones

Instead of scattering `{{base_branch}}` through 15 command files, generate
**one** config asset per repo. All commands reference it.

```
.parrot/sdd.json   (user authors)           sdd/CONFIG.md   (generated, 1 file)
{ "base_branch": "dev",             ──►     | setting     | value |
  "hotfix_base":  "main",                   | base branch | dev   |
  "source_roots": ["packages/…"],           | hotfix base | main  |
  "test_command": "pytest",                 | source root | …     |
  "issue_tracker": "jira" }                 | tracker     | jira  |
```

This matches how ai-parrot already works — `CLAUDE.md` § Git Configuration
holds branch policy and the commands defer to it. One generated file per repo
instead of fifteen; the symlink model survives intact.

### In ai-parrot itself: symlinks

```
.claude/commands/sdd-spec.md
   -> ../../packages/ai-parrot-sdd/src/parrot_sdd/assets/commands/sdd-spec.md
```

`vim .claude/commands/sdd-spec.md` edits the real file in the package.
Other repos get real copies via `sdd claude install`.

---

## Section 3: Migration, phasing & testing

### Scope boundary

281 tracked files reference `scripts.sdd`, but **1,038 live in `sdd/specs/`
and `sdd/tasks/`** — historical records. Those are **not** rewritten.
The live surface is ≈250 refs:

| Area | refs | action |
|---|---|---|
| `tests/` | 62 | move to `packages/ai-parrot-sdd/tests/` |
| `.claude/` | 51 | symlink + rewrite invocations |
| `.agent/` + `.agents/` | 70 | symlink + rewrite invocations |
| `scripts/` | 36 | the move itself |
| `packages/` (core) | 32 | core call sites + the 3 logic forks |
| `docs/` | 21 | rewrite |
| `.github/`, `.codex/`, `CLAUDE.md`, `examples/` | 11 | rewrite |
| `sdd/specs/`, `sdd/tasks/` | 1038 | **left alone — historical** |

### Six waves, each independently green

1. **Skeleton + spine.** Create `packages/ai-parrot-sdd/`; move
   `ledger/sdd_meta.py` → `parrot_sdd/meta.py`; `sdd_ingest.py` gets the
   lazy import. Smallest wave, unblocks the rest.
2. **Scripts hard-cut.** Move 18 modules + 3 shell scripts; rewrite all ≈250
   live call sites; delete `scripts/sdd/`. No compatibility shims — per the
   standing "hard cuts OK, no external consumers" rule.
3. **Collapse the forks.** `base.py`/`research.py` import from
   `parrot_sdd.meta` instead of their local copies; `qa.py:820`'s
   `python -m scripts.sdd.lint_new` shell-out becomes
   `python -m parrot_sdd.scripts.lint_new`. Retires the three stale-comment
   duplications.
4. **Assets + symlinks.** Move 45 assets into
   `parrot_sdd/assets/{shared,claude,codex,google}/`; replace the originals
   with **relative** symlinks; collapse the 9 `_subagent_data` twins into
   the same files.
5. **Config + install.** `parrot_sdd.config`, `sdd/CONFIG.md` generation,
   de-specify inline `dev` / `packages/ai-parrot` references into CONFIG.md
   deferrals, `install.py` + manifest, the `sdd` CLI with
   `claude`/`codex`/`google`.
6. **Release plumbing.** `pyproject` package-data, CI job paths,
   `scripts/release.py` + `pypi_paced_publish.py`, docs, CHANGELOG.

### Tests — five new guards

```python
test_no_core_dependency   # parrot_sdd imports must never touch `parrot` (AST scan)
test_asset_tiers          # every asset in exactly one tier; generic tier has no "ai-parrot"
test_symlink_integrity    # every .claude/commands/sdd-*.md resolves into the package
test_install_roundtrip    # install -> uninstall into tmp repo; manifest honored,
                          #   locally-modified files reported not deleted
test_no_legacy_callsites  # no `scripts.sdd` outside sdd/specs/ and sdd/tasks/
```

### Four risks

1. **Relative symlinks are mandatory.** `.claude/worktrees/feat-*/` are full
   checkouts; a relative `../../packages/ai-parrot-sdd/...` resolves inside
   the worktree correctly, an absolute one silently points at the main
   checkout. Single easiest way to break every worktree at once.
2. **`sdd/templates/` and the global gitignore.** `.gitignore:245` ignores
   `templates/`; those 8 files are tracked only by grandfathering. Replacing
   them with symlinks is a delete + add, and the add needs `git add -f` or
   they vanish.
3. **New PyPI project under the rate limit.** `ai-parrot-sdd` is a 10th
   distribution; PyPI caps new projects at 4/24h, which the 0.29.0
   satellite bootstrap is already pacing around.
4. **CI workflow edits need the SSH remote** — the `gh` OAuth token lacks
   `workflow` scope, so wave 6 pushes over `git@github.com`.

### Not in scope

- Folding the 18 scripts into the CLI as `sdd worktree-status` etc.
- Migrating `calibrate_rlimit_as.py`.
- Rewriting historical `sdd/` documents.

---

## User Decisions (captured during brainstorm)

| Question | Decision |
|---|---|
| Deliverable scope | Whole SDD flow installable, not just scripts |
| Script distribution model | Import from installed package, don't copy Python to consuming repo |
| Which distribution owns it | New satellite: `ai-parrot-sdd` (`parrot_sdd`) |
| Asset authoring in ai-parrot | Package is source, repo has symlinks in |
| Asset adaptation for other repos | Tier the assets + render a config |
| Core SDD awareness | `sdd` CLI only — core knows nothing |
| Config model | One generated config asset (`sdd/CONFIG.md`) from `.parrot/sdd.json` |
| Script name | `sdd` (satellite's own binary) |
| Host variants | `sdd claude install`, `sdd codex install`, `sdd google install` |
