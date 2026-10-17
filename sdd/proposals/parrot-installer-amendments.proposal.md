---
id: FEAT-633
amends: FEAT-633
title: FEAT-633 amendments — portability safeguards carried over from FEAT-583
slug: parrot-installer-amendments
type: feature
mode: enrichment
status: accepted
source: Review of FEAT-583 (portable-sdd-flow) against FEAT-633 (parrot-installer), 2026-09-25 → 2026-10-14
overall_confidence: high
base_branch: dev
projects: [ai-parrot, sdd-tooling, dev-loop, docs, ci]
tags: [installer, sdd-packaging, portability, publication-safety, amendment]
research_state: sdd/state/FEAT-633/
created: 2026-10-14
updated: 2026-10-17
---

# FEAT-633 — Amendments: portability safeguards carried over from FEAT-583

> Amends `sdd/specs/parrot-installer.spec.md` (FEAT-633, approved 2026-10-05).
> Proposed **before any FEAT-633 task has started** (0/28 done on 2026-10-14).
> This document reserves no new FEAT-ID: it changes an existing feature.

---

## 0. Origin

- **Source**: a review of FEAT-583 (`portable-sdd-flow`) carried out over several
  rounds (2026-09-25, 2026-10-02, 2026-10-13), then re-checked against FEAT-633.
- **FEAT-583 status**: marked `superseded by FEAT-633` in commit `2ed09515e`. TASK-4095's
  stamping step is therefore already done.
- **Selection of amendments**: Arturo Martinez chose C2–C6, C8, and C9–C15. C7 is a
  discussion item for Arturo and Jesus (see §6).
- **Mode**: enrichment of an approved feature. It does not reopen FEAT-633's core
  design (launcher, managed venv, `parrot self`, `--portable`, store gate, wheel matrix).

---

## 1. Synthesis Summary

FEAT-633 rejected FEAT-583's **packaging shape** (satellite package, `sdd` binary,
manifest, symlinks), not its **safeguards**. Several of those safeguards are missing
from FEAT-633. Each one below was checked against FEAT-633's 28 task files, not only
its spec:

- **Already covered by FEAT-633 tasks:** C1 and most of C9 (§2.1). They are not
  re-proposed here.
- **13 amendments remain.** Four of them change an approved FEAT-633 decision and were
  marked ⚖️: **C4, C6, C10, C12**. All four were approved by Jesus Lara on 2026-10-14
  (§5), C6 with a reduced scope.
- **One new open question**, now resolved. How installed commands call helpers in a
  global-only install (**Q1**): through `parrot sdd run <helper>` (§3, Q1 resolution).
  C3's test proves it.
- **C16 was added later** (2026-10-17, rev 0.4), after C12's sweep was found to have a
  blind spot: it looked for `scripts/sdd` references only, and missed a shipped reference
  to a path inside the monorepo **source tree**.

| # | Amendment | Amends | ⚖️ | Effort |
|---|---|---|---|---|
| C2 | One copy of each agent prompt | TASK-4090, `_subagent_defs.py` | — | S |
| C3 | Prove the install from the built wheel, in a clean foreign repo | TASK-4091, TASK-4094 | — | M |
| C4 | Upgrades that keep local edits | TASK-4091 | ⚖️ | M |
| C5 | `--dry-run` for `parrot sdd install` / `uninstall` | TASK-4091 | — | S |
| C6 | One repo config, read by the commands | new M6 task | ⚖️ | M |
| C8 | One source for branch policy in core | new task (or TASK-4085) | — | S |
| C9 | Classify the one unpackaged reference (`second-opinion`) | TASK-4090 | — | S |
| C10 | Ship a conventions seed, not ai-parrot's rulebook | TASK-4090, TASK-4091 | ⚖️ | S |
| C11 | Publication safety: no org or repo data ships | TASK-4070, 4089, 4090 | — | M |
| C12 | No shipped reference to monorepo-only helpers | TASK-4089, TASK-4086 | ⚖️ | S |
| C13 | One install guide, kept true by CI | TASK-4095 | — | M |
| C14 | Explain every install command and gate the install | TASK-4074, 4075, 4095 | — | S |
| C15 | SDD readiness checks in `parrot self doctor` | TASK-4080, TASK-4091 | — | S |
| Q1 | `parrot sdd run <helper>` replaces `python -m parrot.sdd.scripts.<name>` | spec M6, TASK-4089, TASK-4091 | ⚖️ | S |
| C16 | No shipped reference to a monorepo source path (`worktree_environment`) | TASK-4085, 4072, 4089, 4090, 4091 | ⚖️ | M |

---

## 2. Codebase Findings

All facts were verified on `dev` at `2ed09515e`, 2026-10-14.

### 2.1 Already covered by FEAT-633 tasks (no amendment needed)

- **Templates ignore trap (was C1).** TASK-4090 places templates under `sdd/sdd_templates/`,
  which avoids the `.gitignore:273` `templates/` rule. `check_asset_sync.py --wheel` proves
  every manifest entry is present in the built wheel.
- **Host mapping (most of C9).** TASK-4090's `_assets/manifest.json` gives each of its
  77 entries a `hosts` field, covering Claude, Codex and Google.
- **Hook classification.** Only `.claude/hooks/sdd-worker-format.sh` ships.
  `dangerous-actions-blocker.sh` and `e2e-teardown.sh` stay in the repo.
- **ID-ledger seed.** TASK-4091 seeds `sdd/tasks/.id_ledger.json` when it is absent.
- **`.claude/worktrees/` ignore.** TASK-4091 adds a managed `.gitignore` block.
- **Missing-tool report.** TASK-4091 runs the S5 audit over installed files and warns.
- **Edits never silently overwritten.** TASK-4091's conflict rule skips any file that differs and warns, unless `--force` is given.
- **Helpers that import core.** These move into core `parrot.sdd.scripts`
  (TASK-4085–4088), so `finalize_task` may import `sdd_coder`.
- **Windows.** The shell helpers are ported to Python (TASK-4087).

### 2.2 Constraints discovered (evidence for the amendments)

1. **The prompt-parity test is failing on `dev`.**
   `packages/ai-parrot/tests/flows/dev_loop/test_subagent_parity.py::test_prompt_parity[sdd-worker]`
   fails (re-run 2026-10-14 on `a6e51614b`: 1 failed, 9 passed, 1 skipped).
   `.claude/agents/sdd-worker.md` lists `Monitor, TaskStop` in its `tools:` line;
   `_subagent_data/sdd-worker.md:26` does not. FEAT-633 adds a third copy under `_assets/`,
   and TASK-4090 records that no sync tool for `_subagent_data/` exists.
2. **Helpers can't be found in a global-only install.**
   - The global install puts only `parrot`, `wikitoolkit` and `bookstore` on PATH
     (`~/.parrot/bin`; spec §1 Goals and M2).
   - Installed markdown calls `python -m parrot.sdd.scripts.<name>` (spec M6, TASK-4089).
   - In a repo whose own venv lacks ai-parrot, `python` cannot import `parrot`.
3. **Upgrades can't tell an upstream change from a local edit.** TASK-4091 compares a
   file only against the current package ("no hash manifest — spec non-goal", task line
   210). An untouched file from an older release and a locally edited file look the
   same: both are skipped without `--force`, and `--force` overwrites both.
4. **No preview.** `parrot sdd install` and `uninstall` have no `--dry-run`, while the
   bootstrap scripts keep a complete one (TASK-4074).
5. **No repo configuration.**
   - Branch names and the issue tracker are literals in the shipped text.
   - The dev-loop keeps hardcoded copies of the branch policy: `_LONG_LIVED_BRANCHES`
     (`flows/dev_loop/nodes/base.py:44`) and `_parse_flow_frontmatter`, defined twice
     (`nodes/research.py:159` and `nodes/feature_handoff.py:69`, with an `or "dev"`
     fallback at `:391`).
   - **Correction (review 2026-10-14).** There is a third copy, and it is the one core
     already treats as authoritative: `KNOWN_BRANCHES` in
     `parrot/knowledge/wiki/ledger/sdd_meta.py:30`. The same module hardcodes the
     policy in `WORK_KIND_FLOW` (`:35-38`), in `parse()`'s default
     `FlowMeta(type="feature", base_branch="dev")` (`:152`) and in the
     `_hotfix_implies_main` validator (`:106`), which requires `base_branch == "main"`
     for hotfixes. `resolve_flow()` also exists (`:263`) and has an independent
     `"dev"` fallback (`:310`); it must participate in config-driven resolution.
     The API includes `resolve_flow()` / `parse()` / `emit()` / `FlowMeta`.
     TASK-4085 re-exports this module as
     `parrot.sdd.scripts.sdd_meta` (`scripts/sdd/sdd_meta.py` is already a wrapper).
6. **ai-parrot's code rulebook ships everywhere.** TASK-4090 ships `codebase-conventions.md`
   (aiohttp only, navigator-api, uv) as an always-loaded rule to all three hosts
   (`.claude/rules/` and `.agent/rules/`).
7. **Org data in shipped files, and the scanner can't see it.**
   - Across hosts: `trocglobal.atlassian.net` 11 times in 5 files, real `NAV-` ticket
     keys 102 times in 10 files, and the `agy` reviewer ban 3 times.
   - TASK-4070's six finding kinds detect none of these.
8. **Shipped references to monorepo-only helpers.** TASK-4089 keeps them on purpose
   (`scripts.sdd.review_checkpoint` at `.claude/agents/sdd-worker.md:588,607`), and
   its new test allows them. Those lines fail outside this monorepo.
   **Correction (review 2026-10-14).** The earlier draft also listed `lint_new`,
   `token_audit` and `codex_hook`. A grep over `.claude/`, `.agent/`, `.agents/` and
   `sdd/templates/` finds **no** reference to `lint_new` or `token_audit` in any file
   TASK-4090 packages; `codex_hook` appears only in `.codex/hooks.json:9`, which is not
   packaged. `review_checkpoint` is therefore the only non-moved helper a shipped file
   references.
9. **One unpackaged skill.** Shipped files reference the `second-opinion` skill 5 times,
   but it isn't among TASK-4090's sources.
10. **Four install documents, one verified.** FEAT-586's CI-verified
    `docs/getting-started.md` is not touched. TASK-4095 adds
    `docs/install/global-runtime.md` plus sections in `INSTALL.md` and `docs/INSTALL.md`.
11. **The bootstrap runs downloaded content.** The `--global` bootstrap uses a raw-URL
    script and downloads a pinned uv binary from GitHub. That is exactly the case
    FEAT-586's AC8 requires explaining: what it touches, and a non-piped alternative.
12. **Doctor doesn't check SDD readiness.** `parrot self doctor` (TASK-4080) checks the
    runtime and host configs only.

---

## 3. Probable Scope — the amendments

Each amendment lists the problem (pointing to §2.2), the change, the task it amends, a
"done when" check, and a ⚖️ flag where it reverses an approved FEAT-633 decision.

### C2 — One copy of each agent prompt
- **Problem**: §2.2-1. Two copies already drift, and FEAT-633 would add a third.
- **Change**:
  - `load_subagent_definition()` (`flows/dev_loop/_subagent_defs.py:95`) reads the
    packaged copy under `parrot/sdd/_assets/`, stripping the frontmatter as it does
    today. The frontmatter is the only part that differs between hosts.
  - Delete the `_subagent_data/` copies of shipped prompts, both dev-loop and dev-flow
    `sdd-ideation`. `sdd-codereview` has no `.claude` twin and stays core-only.
  - Fix today's failing parity test in the same change.
- **Amends**: TASK-4090 and `_subagent_defs.py`. It also shortens TASK-4089's twin list.
- **Done when**: each shipped prompt has exactly one source; the asset sync check
  replaces the parity test; `load_subagent_definition` returns the packaged body.

### C3 — Prove the install from the built wheel, in a clean foreign repo
- **Problem**: §2.2-2. The planned foreign-repo test runs inside the test's own venv,
  where `parrot` always imports.
- **Change**: an integration test that:
  1. builds the wheel;
  2. creates a managed layout (a temporary `PARROT_HOME`) with ai-parrot installed
     from that wheel and its declared runtime dependencies, without an editable install;
  3. creates an unrelated, non-Python git repo;
  4. runs `parrot sdd install`;
  5. runs **every helper invocation in the installed markdown using its documented
     command and flags**, substituting fixture values for placeholders and supplying
     each invocation's required state (including a local bare `origin`, committed
     ledger, task files and evidence where needed). Each scenario uses isolated state;
  6. sets PATH to `$PARROT_HOME/bin` plus a fixture directory exposing an explicit
     allowlist of required system tools (`git`, and shell utilities such as `bash` or
     `jq` where an invocation requires them). Project/test venv bins are excluded;
     `PYTHONPATH`, `PYTHONHOME`, `VIRTUAL_ENV`, `PARROT_VENV` and project-root override
     variables are unset. Assert that `parrot` and its helper interpreter resolve to
     the temporary managed installation. The helper implementations are not mocked.
- **Amends**: TASK-4091 (test) and TASK-4094 (release smoke test).
- **Done when**: it passes on Linux in CI after Q1 is implemented, covers every
  documented helper invocation with fixture inputs, and proves that system prerequisites
  remain available while ai-parrot is loaded exclusively from the built wheel.

### C4 — Upgrades that keep local edits ⚖️
- **Problem**: §2.2-3. Today every upgrade needs `--force`, and `--force` also
  overwrites a team's customizations.
- **Change**:
  - Record the SHA-256 of the bytes the installer wrote. Use a small committed record,
    `sdd/.sdd-installed.json`. It lives in the committed `sdd/` tree, not `.parrot/`,
    which `.gitignore:411` ignores entirely. It is used rather than per-file comments
    because JSON and TOML assets can't all carry one.
  - On reinstall:
    - file matches the record → upgrade it;
    - file differs → it was edited, so skip and warn (unless `--force`);
    - file not in the record → it isn't ours, so skip.
  - `parrot sdd status` reports each file as missing, current, outdated or edited.
  - The record also stores the ai-parrot version that wrote it, so `status` can name
    the release an outdated file came from.
- **Amends**: TASK-4091, including its line 51, which today lists an install receipt as
  out of scope.
- **⚖️ Reverses**: the "no hash manifest" non-goal (spec §1, TASK-4091 line 210).
  **Why it's worth it**: without a record, the installer can't upgrade safely.
  **Decision note (Jesus Lara, 2026-10-14)**: the spec non-goal rejected FEAT-583's
  *packaging* manifest and symlinks, not an install receipt. The receipt is a different
  mechanism and the non-goal wording in spec revision 0.2 should say so.
- **Done when**: tests cover upgrading an untouched file, keeping an edited file, and
  `--force`.

### C5 — `--dry-run` for `parrot sdd install` / `uninstall`
- **Problem**: §2.2-4.
- **Change**: `--dry-run` prints the exact plan and changes nothing. The plan lists
  write, skip, upgrade or remove for each path, plus the `.gitignore` block, the ledger
  seed and the config seeds.
- **Amends**: TASK-4091.
- **Done when**: a test shows the directory tree is byte-for-byte unchanged after a dry run.

### C6 — One repo config, read by the commands ⚖️
- **Problem**: §2.2-5. Commands are hardwired to ai-parrot's branches and Jira.
- **Change**:
  - Add a committed `sdd/config.json`, owned by the team and validated with Pydantic.
    v1 fields: `base_branch`, `staging_branch` (optional), `hotfix_base`,
    `issue_tracker` (`jira | none`), `jira_host` (optional), `reviewer`
    (`codex | none`, used by C9) and `test_command` (used by C7 option C).
    `sync_down` is dropped from v1: the Action is ai-parrot's, and nothing shipped
    reads the value.
  - **No rendered `sdd/CONFIG.md`** (decision 2026-10-14). The shipped commands are
    markdown read by an LLM, which reads `sdd/config.json` directly; a second generated
    file would only add something to drift. Shipped commands say "the base branch in
    `sdd/config.json`" instead of literals. Command files therefore stay byte-identical
    across repos and FEAT-633's sync rule holds; only `config.json` differs.
  - ai-parrot's own `sdd/config.json` sets `dev`/`staging`/`main` and Jira, so
    ai-parrot's behaviour is unchanged.
  - Validation keeps today's lane rules: features never base on the hotfix branch, and
    hotfixes always base on it.
  - The branch-policy API in `parrot/knowledge/wiki/ledger/sdd_meta.py` takes its
    defaults from the config: `resolve_flow()` (`:263`), `parse()` and `FlowMeta`,
    including `WORK_KIND_FLOW` (`:35-38`), `parse()`'s default (`:152`),
    `resolve_flow()`'s independent `"dev"` fallback (`:310`) and the
    `_hotfix_implies_main` validator (`:106`). Use `base_branch` / `hotfix_base`
    from the config, with today's values as the fallback when no config exists.
    Preserve resolution precedence: explicit overrides, document frontmatter,
    work-kind mapping, then configured defaults; apply lane validation to the result.
- **Amends**: a new M6 task, after TASK-4085 (which moves `sdd_meta`) and before
  TASK-4089 (the markdown rewrite). It depends on C8.
- **⚖️ Adds**: a configuration FEAT-633 doesn't have.
  **Decision note (Jesus Lara, 2026-10-14)**: approved with the reduced field set above
  and without `CONFIG.md`.
- **Done when**: a foreign repo using `main` plus `develop` can run the flow by editing
  only `sdd/config.json`. Tests cover `resolve_flow()` with no document and no work
  kind, an unknown work kind, mapped work kinds, frontmatter and explicit overrides;
  configured defaults apply on fallback, and absent config preserves current defaults.

### C8 — One source for branch policy in core
- **Problem**: §2.2-5. After C6, hardcoded copies would silently ignore the config.
- **Change**:
  - Replace `_LONG_LIVED_BRANCHES`, both `_parse_flow_frontmatter` copies **and**
    `KNOWN_BRANCHES` in `knowledge/wiki/ledger/sdd_meta.py:30` (§2.2-5 correction) with
    one set of `sdd_meta` functions, using FEAT-583's
    `read_declared_base_branch(path) -> str | None`. The surviving definition lives in
    `knowledge/wiki/ledger/sdd_meta.py`, since TASK-4085 already makes it the module
    `parrot.sdd.scripts.sdd_meta` re-exports.
  - Keep the distinction the two callers rely on: `None` when no branch is declared,
    versus a `"dev"` default.
- **Amends**: a new task that is a prerequisite of C6, or fold it into TASK-4085.
- **Done when**: there is a single definition, with parity tests for the
  missing-frontmatter and invalid-frontmatter cases.

### C9 — Classify the one unpackaged reference
- **Problem**: §2.2-9.
- **Change**: either package `second-opinion` for each host, using C6's `reviewer`
  setting, or rewrite its 5 references as conditional ("if a reviewer skill is installed").
- **Amends**: TASK-4090.
- **Done when**: no shipped file references an unshipped skill.

### C10 — Ship a conventions seed, not ai-parrot's rulebook ⚖️
- **Problem**: §2.2-6. A Django or Node repo would be told to use aiohttp.
- **Change**:
  - Drop `codebase-conventions.md` from `_assets` for every host.
  - Ship `sdd/CONVENTIONS.md` as a **seed**: created once, owned by the team, and never
    overwritten or removed afterwards, even with `--force`. Shipped references point at it.
  - ai-parrot keeps its own `codebase-conventions.md` rules as repo files.
  - `worktree-management.md` keeps shipping, since it is SDD guidance, once C11 removes
    its ai-parrot paths.
- **Amends**: TASK-4090 (manifest) and TASK-4091 (seed handling).
- **⚖️ Reverses**: the "2 rules" packaged in spec M6 (TASK-4090 manifest rows at
  lines 267-270 ship `codebase-conventions.md` to claude and to codex/google).
  **Decision note (Jesus Lara, 2026-10-14)**: approved. The dev-loop coder seats keep
  using `flows/_rules_data/` (FEAT-553), which is untouched. `worktree-management.md`
  today cites the shared `.venv`, Bubblewrap and ai-parrot paths, so it ships only
  after C11's rewrite.
- **Done when**: no shipped file mandates a language, framework or package manager.

### C11 — Publication safety: no org or repo data ships
- **Problem**: §2.2-7. The files now go into the **public core wheel**.
- **Change**:
  - a. Add finding kinds to TASK-4070's scanner:
    - `org-data`: Atlassian hosts other than a placeholder, and real ticket keys outside
      placeholders;
    - `claude-md-ref`: references to `CLAUDE.md` sections;
    - `branch-literal`: hardcoded branch names where C6's config applies.
  - b. TASK-4089's rewrite:
    - uses placeholders (`https://your-org.atlassian.net`, `PROJ-123`);
    - keeps the `agy` reviewer history only in ai-parrot's `CLAUDE.md`, where it
      already lives.
  - c. CI fails if any shipped file has these findings.
  - d. The wheel check (TASK-4090 `--wheel`) also checks what must **not** ship:
    - a deny-list: `sdd/references/`, `sdd/state/`, `.parrot/`, `*.jsonl`, `*.db`,
      ledger files;
    - a content scan, on top of the completeness check.
- **Amends**: TASK-4070, TASK-4089 and TASK-4090.
- **Done when**: the scanner reports zero findings over `_assets/`, and the wheel check
  fails on a planted forbidden file.

### C12 — No shipped reference to monorepo-only helpers ⚖️
- **Problem**: §2.2-8.
- **Change**:
  - Every helper a shipped file references either moves into `parrot.sdd.scripts`, or
    its step is guarded ("ai-parrot only — skip when unavailable").
  - `review_checkpoint` can move now: it imports only
    `parrot.flows.dev_loop.sdd_coder.{checkpoint,evidence,optimization_models,telemetry}`,
    all in core (verified 2026-10-14).
  - `codex_hook` stays repo-only; it is referenced only by `.codex/hooks.json`, which is
    not packaged.
  - **Scope after the §2.2-8 correction**: `review_checkpoint` is the only non-moved
    helper any shipped file references, so C12 is one module move plus the extended
    test. `lint_new` and `token_audit` need no guard.
  - Extend TASK-4089's `test_no_repo_script_refs` to fail on **any** `scripts.sdd.*` or
    `scripts/sdd/*` reference in shipped files. Historical `sdd/specs/` and `sdd/tasks/`
    are excluded.
- **Amends**: TASK-4089, plus a TASK-4086 entry for `review_checkpoint`.
- **⚖️ Reverses**: TASK-4089's "references to non-moved helpers stay untouched"
  (lines 54-56, 218, 725, 742).
  **Decision note (Jesus Lara, 2026-10-14)**: approved; cost is one module.
- **Done when**: the extended test passes.

### C13 — One install guide, kept true by CI
- **Problem**: §2.2-10.
- **Change**:
  - FEAT-586's `docs/getting-started.md` becomes the **canonical** install and
    first-use guide. It gains the `--global` path, `parrot self`, `parrot sdd install`,
    and a "Use the SDD flow in your repo" section, each with claim anchors.
  - The claim harness gains `cli-verb` and `flag` kinds, checked against the real Click
    commands.
  - `docs/install/global-runtime.md` holds the reference detail; `INSTALL.md` and
    `docs/INSTALL.md` become short pointers.
- **Amends**: TASK-4095, merging `test_global_runtime_docs.py` into the claim harness.
- **Done when**: every documented command and flag is verified by CI.

### C14 — Explain every install command, and gate the install
- **Problem**: §2.2-11, plus "the install script should check dependencies to prevent a
  bad install".
- **Change**:
  - a. **Transparency** (FEAT-586 AC8). Every documented install command states what it
    downloads, where it writes, how it is verified (checksum), and a non-piped
    alternative: download, inspect, verify the checksum, then run. This covers the
    raw-URL bootstrap and the pinned-uv download.
  - b. **Gating, merged with C15.** The full check list lives once, in
    `parrot self doctor`. Doctor can't run before ai-parrot exists, so the script keeps
    only a **pre-install gate**: the conditions that must hold before anything is written.
    - The platform is in the supported wheel matrix (spike S1).
    - A download tool and a checksum tool are available.
    - `PARROT_HOME` is writable, with free disk space.
    - GitHub and PyPI are reachable.
    - `git` is present.

    After installing, the script runs `parrot self doctor --runtime-only` against
    the newly installed managed runtime (without launcher redirection to a project
    venv). This scope checks only managed uv, Python, runtime entry points and PATH;
    it excludes repository readiness, host configuration and optional-component checks.
    A runtime failure triggers
    TASK-4074's existing rollback, which removes only what this run created, and prints
    doctor's suggested fixes.
- **Amends**: TASK-4074, TASK-4075 and TASK-4095.
- **Done when**: tests show that each failed gate exits before any write, and that a
  failed post-install runtime check rolls back. A successful runtime install must
  remain installed when the invoking repo has unauthenticated `gh`, an uncommitted
  ledger or outdated SDD assets; cover these cases in bootstrap tests for both scripts.

### C15 — SDD readiness checks in `parrot self doctor`
- **Problem**: §2.2-12.
- **Change**: extend TASK-4080's check list. Doctor still only reports and suggests a
  fix; it never changes anything. New checks:
  - the repo has an `origin` remote;
  - the configured base branch (C6; default `dev`) exists on `origin`;
  - `sdd/tasks/.id_ledger.json` is committed;
  - `.claude/worktrees/` is ignored;
  - `gh` is present and authenticated (needed for PR steps);
  - `jq` is present, while any shipped file still uses it;
  - the installed SDD files are current, using C4's status;
  - the host CLI (`claude` / `codex` / `agy`) is present for each installed host
    (informational).

  These checks run when an `sdd/` tree exists, or with `--sdd`, except in the new
  `--runtime-only` scope used by bootstrap (C14). `--runtime-only` and `--sdd` are
  mutually exclusive. The normal doctor command retains runtime/host/component
  diagnostics and adds applicable SDD checks. Exit 1 only when a non-informational
  check in the selected scope fails; informational host-CLI checks do not fail it.
- **Amends**: TASK-4080, and TASK-4091 for the status hook.
- **Done when**: a fixture repo missing each prerequisite gets the matching check
  failing, with its fix. Tests prove `--runtime-only` excludes repository, host and
  optional-component failures, normal/`--sdd` checks still report readiness failures,
  and mutually exclusive scope flags are rejected.

### Q1 resolution — `parrot sdd run <helper>` ⚖️
- **Problem**: §2.2-2. `python -m parrot.sdd.scripts.<name>` runs whatever `python` is
  first on PATH; in a repo whose venv lacks ai-parrot, that import fails.
- **Decision (Jesus Lara, 2026-10-14)**: add `parrot sdd run <helper> [args…]` to the
  `parrot sdd` click group. Everything that enters through `parrot` inherits M1's venv
  resolution (`PARROT_VENV` → project venv → `VIRTUAL_ENV` → managed), so the helper
  runs in the same venv the launcher picked for `parrot` itself. The `parrot-python`
  shim was rejected: it would pin the managed venv and, inside ai-parrot, run the wrong
  code.
- **Change**:
  - `parrot sdd run <name> [args…]` sets `sys.argv` and calls
    `runpy.run_module(f"parrot.sdd.scripts.{name}", run_name="__main__")`; unknown
    names fail with the list of available helpers.
  - TASK-4089's rewrite target becomes `parrot sdd run <name>` instead of
    `python -m parrot.sdd.scripts.<name>` (its regex table, lines 550-575, and every
    assertion that greps for the `python -m` form).
  - Spec M6's "single form `python -m parrot.sdd.scripts.<name>`" becomes the single
    form `parrot sdd run <name>`. `python -m` keeps working for direct use; it is no
    longer what shipped markdown says.
- **Amends**: spec M6, TASK-4089, TASK-4091 (the `run` subcommand). Decide before
  TASK-4089 starts.
- **Done when**: C3's wheel-only test runs every helper invocation in the installed
  markdown with C3's fixture inputs and allowlisted system tools, while resolving
  `parrot` and the helper interpreter exclusively from the managed installation.

### C16 — No shipped reference to a monorepo source path ⚖️
- **Problem**: C12 (§2.2-8) swept the shipped set for `scripts.sdd.*` / `scripts/sdd/*`
  and concluded that `review_checkpoint` is "the only non-moved helper any shipped file
  references". The sweep missed a second class of reference: a path into the monorepo
  **source tree**. Two files in TASK-4090's shipped set — `.claude/agents/sdd-coder.md:21`
  and `.claude/agents/sdd-worker.md:32` — carry this in their `PreToolUse` frontmatter:

  ```
  command: 'python3 "$CLAUDE_PROJECT_DIR/packages/ai-parrot/src/parrot/flows/dev_loop/worktree_environment.py" --hook || exit 2'
  ```

  `$CLAUDE_PROJECT_DIR/packages/…` does not exist in a foreign repo. That hook *is* the
  shared-environment guard (`POLICY_MESSAGE`, `protected_argv`, `validate_write_path`), so
  an installed `sdd-coder` / `sdd-worker` would run there with no sandbox at all. C12's
  extended `test_no_repo_script_refs` cannot catch it: the string contains neither
  `scripts.sdd` nor `scripts/sdd`.
- **Why this is not a plain C12 case**: the module already ships inside the wheel. What
  breaks is how it is *addressed* — by filesystem path rather than by command. And the
  path form is deliberate, not sloppy: `parrot/flows/dev_loop/__init__.py` eagerly imports
  the dispatchers, the flow, the runner, the streaming layer and the Pydantic models, so
  `python -m parrot.flows.dev_loop.worktree_environment` would drag the whole dev-loop
  stack into **every** `PreToolUse` call. Running the file by path skips the parent
  package — which is exactly why the module is stdlib-only (L7-16) and invoked this way.
  Any fix must preserve that cost.
- **Change** *(mechanism drafted with Claude, 2026-10-17 — confirm before TASK-4085 starts)*:
  1. **Relocate to a light parent.** `git mv` the module to
     `parrot/sdd/scripts/worktree_environment.py`;
     `parrot/flows/dev_loop/worktree_environment.py` becomes a re-export shim so the three
     in-core importers keep working unchanged (`dispatchers/claude.py:66`,
     `dispatchers/llm.py:58`, `sdd_coder/background.py:49`). `parrot/sdd/__init__.py` and
     `parrot/sdd/scripts/__init__.py` stay import-free — TASK-4085 already specifies the
     latter as "docstring only, no imports" — so the module stays reachable without
     importing anything else.
  2. **PATH-resolved invocation with a fast path.** The hook becomes
     `parrot sdd run worktree_environment --hook` (Q1's single form, so byte-equality
     holds), and `parrot/launcher.py` gains an argv fast path for it — the same shape as
     the `wikitoolkit claude-hook` fast path the spec already mandates (§7, spec:920-921):
     the check happens before Click is imported, behind a single `is_managed()` call.
     Without that fast path the guard pays launcher + Click on every Bash/Write/Edit.
  3. **Stop deriving the command from `__file__`.** `dispatchers/claude.py:625` builds the
     same hook string from `Path(worktree_environment.__file__).resolve()` for programmatic
     `AgentDefinition`s; after (1) that would resolve to the shim. It emits the portable
     command instead.
  4. **Rewrite the two shipped frontmatters.** The `_subagent_data/` copies are already
     retired by C2, so there is one copy of each to change.
  5. **Widen C12's test.** `test_no_repo_script_refs` fails on **any** monorepo source path
     in a shipped file — `packages/`, `scripts/`, `$CLAUDE_PROJECT_DIR/…` — not only
     `scripts/sdd/*`. Historical `sdd/specs/` and `sdd/tasks/` stay excluded.
  6. **Cover it in C3's proof.** `test_wheel_only_foreign_repo` exercises the hook itself,
     not only the helper invocations in the installed markdown: a write that the policy
     denies must still be denied in the foreign repo.
- **Amends**: TASK-4085 (move + shim), TASK-4072 (launcher fast path), TASK-4089 (the two
  frontmatters), TASK-4090 (widened test), TASK-4091 (C3 coverage).
- **⚖️ Reverses**: C12's scope claim that `review_checkpoint` is the only offending
  reference, and TASK-4089's *NOT in scope* clause that its substitution table "matches the
  19 moved names only, by construction".
  **Decision note (Jesus Lara, 2026-10-17)**: approved — `worktree_environment` enters
  FEAT-633's scope.
- **Open**: the latency budget for the fast path (a number for the `--hook` round trip) is
  not fixed here; set it with TASK-4072.
- **Done when**: no shipped file names a monorepo source path; the widened
  `test_no_repo_script_refs` passes; and C3's foreign-repo test shows the guard denying a
  shared-environment write with only `$PARROT_HOME/bin` on PATH.

### What's untouched (non-goals)
- FEAT-633's core design: the launcher, managed venv, `parrot self`, `--portable`, the
  store gate and the wheel matrix.
- No satellite package, no `sdd` binary, no symlinks: FEAT-583's rejected shape stays
  rejected.
- C7 (test-selection policy): option C for v1 (§5, §6). Shipped commands run the
  repo's `test_command` from `sdd/config.json` outside ai-parrot; FEAT-620's policy
  stays ai-parrot code.
- FEAT-586's project-mode install is unchanged.

### Integration risks
- **C6 and C11 change ai-parrot's own command files**, because of byte-equality.
  ai-parrot's `sdd/config.json` must land in the same change, or ai-parrot's own flow
  loses its branch policy.
- **C2 touches how the dev-loop loads prompts**, and shrinks TASK-4089's twin list.
  Coordinate the two.
- **Q1 changes TASK-4089's rewrite target.** Fold it into TASK-4089 and spec M6 before
  that task starts; C3 depends on it.
- **New tasks need IDs** (C6, C8; Q1's `run` subcommand folds into TASK-4091). Reserve
  them with `reserve_ids` and append to FEAT-633's index; never rewrite it.

---

## 4. Confidence Map

| Claim | Confidence | Evidence |
|---|---|---|
| C1 and most of C9 are already covered | high | TASK-4090 text: `sdd_templates/`, manifest `hosts`, `--wheel` |
| Parity test is failing on `dev` | high | Run on `2ed09515e`: 1 failed, 9 passed |
| Helpers fail in a global-only install (Q1) | high | Spec M2 exposes 3 scripts; TASK-4089 uses `python -m` |
| Upgrades can't tell edits apart (C4) | high | TASK-4091 line 210 conflict rule |
| ai-parrot rulebook ships to every host (C10) | high | TASK-4090 manifest rows for `codebase-conventions.md` |
| Org-data counts (C11) | high | grep over all SDD files on `dev` |
| `review_checkpoint` can move to core (C12) | high | Imports verified 2026-10-14: only `parrot.flows.dev_loop.sdd_coder.*`; it is also the only non-moved helper shipped files reference |
| Branch policy includes `resolve_flow()` and its independent fallback, plus `parse()`/`FlowMeta`/`KNOWN_BRANCHES` | high | `knowledge/wiki/ledger/sdd_meta.py:30,35-38,106,152,263,310` |
| Size estimates (S/M) | medium | Judgement |

---

## 5. Open Questions

### Resolved (during this review)
- [x] Is FEAT-583 still a live spec? — *Resolved by Arturo Martinez*: No. It is superseded by FEAT-633 (commit `2ed09515e`).
- [x] Which FEAT-583 and review ideas carry over? — *Resolved by Arturo Martinez*: C2–C6, C8, and C9–C15. C1 and the host mapping part of C9 are already covered by FEAT-633's tasks.
- [x] Does the install script need its own dependency checks (C14 comment)? — *Resolved by Arturo Martinez*: the full check list lives in `parrot self doctor` (C15). The script keeps a minimal pre-install gate. Review refinement: after installing it runs `doctor --runtime-only`; repository readiness failures do not trigger runtime rollback.

### Resolved (review with Jesus Lara, 2026-10-14)
- [x] ⚖️ Approve C4, the installed-hash record that reverses "no hash manifest"? — *Resolved by Jesus Lara*: **Yes.** The spec non-goal rejected FEAT-583's packaging manifest and symlinks, not an install receipt; without a receipt TASK-4091's conflict rule (lines 210-211) cannot tell an untouched older file from an edited one, so every upgrade needs `--force` and `--force` overwrites edits. The receipt also stores the writing ai-parrot version. TASK-4091 line 51 (receipt out of scope) is amended.
- [x] ⚖️ Approve C6, the repo config? — *Resolved by Jesus Lara*: **Yes, reduced.** One committed `sdd/config.json` read directly by the shipped commands; **no generated `sdd/CONFIG.md`** (a second file only adds drift). v1 fields: `base_branch`, `staging_branch`, `hotfix_base`, `issue_tracker`, `jira_host`, `reviewer`, `test_command`; `sync_down` dropped. Review correction: parameterize `resolve_flow()` / `parse()` / `FlowMeta` in `parrot/knowledge/wiki/ledger/sdd_meta.py`, including `WORK_KIND_FLOW` (`:35-38`), `parse()`'s default (`:152`), `_hotfix_implies_main` (`:106`) and `resolve_flow()`'s independent fallback (`:310`). Preserve override/frontmatter precedence and test configured fallback resolution.
- [x] ⚖️ Approve C10, a conventions seed instead of shipping `codebase-conventions.md`? — *Resolved by Jesus Lara*: **Yes.** TASK-4090 lines 267-270 ship ai-parrot's rulebook (aiohttp only, no `requests`/`httpx`, uv) to all three hosts; in a Node or Django repo it is simply wrong. The dev-loop seats keep `flows/_rules_data/` (FEAT-553). `worktree-management.md` ships only after C11 removes its `.venv`/Bubblewrap/ai-parrot paths.
- [x] ⚖️ Approve C12, moving or guarding monorepo-only helpers in shipped files? — *Resolved by Jesus Lara*: **Yes.** Verified scope is smaller than drafted: `scripts.sdd.review_checkpoint` (`sdd-worker.md:588,607`) is the **only** non-moved helper any shipped file references; `lint_new` and `token_audit` appear in no packaged file and `codex_hook` only in the unpackaged `.codex/hooks.json`. `review_checkpoint` imports only `parrot.flows.dev_loop.sdd_coder.*` (core), so it moves via TASK-4086.
- [x] **Q1** — How do installed commands call helpers when ai-parrot is only in the global managed venv? — *Resolved by Jesus Lara*: **`parrot sdd run <helper> [args…]`**, added to the `parrot sdd` group (folds into TASK-4091). It inherits M1's venv resolution, so it works wherever `parrot` works, including inside ai-parrot's own venv. The `parrot-python` shim is rejected: it would pin the managed venv and run the wrong code inside ai-parrot. Spec M6's "single form" and TASK-4089's rewrite target (regex table, lines 550-575) change to `parrot sdd run <name>`; `python -m` remains valid for direct use. Decide-before: TASK-4089. See §3 "Q1 resolution".
- [x] **C7** — Should test selection carry repo-specific policy in other repos? — *Resolved by Jesus Lara*: **Option C for v1.** The policy is `CORE_PATHS` in `parrot/flows/dev_loop/test_scope/policy.py`, written by `scripts/sdd/regen_core_paths.py` into that source file; it is a list of ai-parrot module names with no meaning elsewhere. Option A needs C6 plus retargeting the generator with no evidence yet that a foreign repo gains from escalation; option B can report green with zero tests selected. Shipped commands run `test_command` from `sdd/config.json` outside ai-parrot. The §6 evidence step (two throwaway repos) still runs, as input for revisiting option A in v1.1.

### Unresolved
- None. The amendments are ready to fold into FEAT-633 spec revision 0.2 (§6 step 2).

---

## 6. Recommended Next Step

1. ~~Arturo and Jesus decide the ⚖️ items, Q1 and C7~~ — **done 2026-10-14** (§5).
   The protocol below is kept for the record; only its evidence step still runs.
2. **Fold the accepted amendments into FEAT-633**:
   - a spec revision 0.2 (§3 M3/M6, §4, §5, Revision History);
   - amend TASK-4070, 4074, 4075, 4080, 4086, 4089, 4090, 4091, 4094 and 4095;
   - reserve IDs for the new tasks (C6, C8); Q1 and C7 option C fold into TASK-4091,
     TASK-4089 and spec M6;
   - drop TASK-4095's FEAT-583 stamping step, which is already done.
3. **Then start implementing FEAT-633.** Spikes S1–S6 can start now, because none of
   these amendments touch them.

### Protocol for deciding C7 (test-selection policy)

> **Outcome (2026-10-14)**: option C for v1, decided by Jesus Lara (§5). Step 1 (evidence)
> still runs as input for v1.1; steps 2-3 are no longer needed.

**The question.** `select_tests` and `check_task_graph` ship through `parrot.sdd.scripts`,
but their policy is ai-parrot's: `CORE_PATHS` (generated by FEAT-620), the xdist list and
the markers. What should happen in other repos?

**Options:**
- **A. Repo-supplied policy.** Add a `test_scope` block to `sdd/config.json`
  (`core_paths`, `xdist_safe`, `impact_cap`, `impact_depth`, `core_fanin_threshold`,
  `marker_expression`, `escalate_foreign_dists`), with neutral defaults. FEAT-620's list
  becomes ai-parrot's config value, and `regen_core_paths` writes to the config. This is
  FEAT-583's design, and it **needs C6**.
- **B. Policy stays in ai-parrot code** (FEAT-620). Other repos get an empty policy (no
  escalation, no xdist, no markers) plus FEAT-583's single-package `src/` layout mapping
  (`src/<pkg>/…` → `tests/…`).
- **C. ai-parrot-only in v1.** Shipped commands skip test selection outside ai-parrot
  and run the repo's own test command.

**Criteria:**
- Does a foreign repo actually get value from escalation?
- What does it cost to retarget FEAT-620's generator?
- What is the risk of ai-parrot's policy leaking into other repos?
- How much fits in v1's scope?

**How to decide (about an hour in total):**
1. **Evidence first** (Arturo, about 30 minutes, async). Run today's `select_tests` and
   the task-graph check against two throwaway repos: a single-package `src/` Python
   repo, and a non-Python repo. Record what gets selected and escalated in
   `sdd/state/FEAT-633/discussions/C7-evidence.md`. This turns the debate into observed
   behaviour.
2. **Independent opinion** (Jesus, async). Run the codex design-research seat on a
   neutral brief: the question, the three options and the evidence file, with no
   preferred answer (CLAUDE.md's reviewer rule). Triage each suggestion as CONFIRM,
   REJECT or ESCALATE.
3. **A 30-minute sync with a fixed agenda**:
   - 5 minutes: evidence;
   - 10 minutes: options against the criteria;
   - 10 minutes: decide;
   - 5 minutes: record.

   Use the same session for C4, C6, C10, C12 and Q1. **Decide C6 first**, because
   option A only works if C6 is accepted.
4. **Record the outcome.** Flip each question in §5 to
   `[x] … *Resolved by Jesus Lara & Arturo Martinez*: <decision>`, then fold it into the
   FEAT-633 spec revision. **Timebox**: if C7 is still undecided at the end of the
   session, take option C for v1 (the smallest and easiest to reverse) and revisit it
   in v1.1.

---

## 7. Installer status after the amendments

### What a developer gets, end to end
1. **Reads `docs/getting-started.md`.** Every command is explained, and the facts are
   verified by CI (C13, C14a).
2. **Runs the one-line `--global` bootstrap**, or its non-piped alternative.
   - The pre-install gate stops on an unsupported platform or missing tools before
     anything is written (C14b).
   - uv, Python 3.12 and ai-parrot install into `~/.parrot`, and PATH is set (FEAT-633 M2).
   - The bootstrap finishes by running `parrot self doctor --runtime-only` against
     the new managed runtime; a runtime failure rolls back (C14b). Repository
     readiness is checked separately and does not roll back the runtime.
3. **Previews, then installs, in any repo.**
   `parrot sdd install --host claude|codex|google --dry-run` shows the plan (C5). The
   real install then:
   - deploys that host's commands, agents, skills and templates (FEAT-633's manifest);
   - seeds `sdd/config.json` (C6) and `sdd/CONVENTIONS.md` (C10);
   - seeds the ID ledger and the worktree ignore (TASK-4091).
4. **Sets the branches and tracker in `sdd/config.json`.** The commands follow it.
   ai-parrot's rulebook and org data never arrive (C10, C11).
5. **Checks readiness with `parrot self doctor`** (C15): `origin`, base branch, ledger,
   `gh`/`jq`, host CLIs.
6. **Uses the `/sdd-*` commands.** Helpers run through `parrot sdd run <helper>` (Q1),
   proven by the wheel-only test (C3). Monorepo-only steps are moved or skipped (C12).
7. **Upgrades by running `parrot sdd install` again.** Untouched files upgrade and edited
   ones are kept; `parrot sdd status` shows current, outdated or edited (C4).

### Before and after

| Concern | FEAT-633 today | After amendments |
|---|---|---|
| Platforms | Linux, macOS, Windows (pending spike S1) | Same |
| Helpers in a foreign repo | `python -m …` fails in a global-only install | `parrot sdd run <helper>` (Q1), proven by C3 |
| Codex/Google SDD files | Packaged (77 entries with `hosts`) | Same |
| Repo branches and tracker | ai-parrot's literals | Per-repo config (C6, C8) |
| Org and ai-parrot text | Ships verbatim in the public wheel | Scanned, made generic, blocked by CI (C11) |
| Rules shipped | ai-parrot's code rulebook | A team-owned conventions seed (C10) |
| Monorepo-only helpers | Shipped references fail elsewhere | Moved or guarded (C12) |
| Upgrades | Need `--force`, which overwrites edits | Untouched files upgrade, edits are kept (C4) |
| Preview | None | `--dry-run` (C5) |
| Diagnostics | Runtime and host configs | Plus SDD readiness (C15); bootstrap gates only runtime health with `--runtime-only` (C14) |
| Install safety | Checksums, rollback | Plus a pre-install gate and explained commands (C14) |
| Install docs | Four documents, one verified | One canonical verified guide (C13) |
| Agent prompts | Three copies, parity test failing | One copy (C2) |
| Test selection elsewhere | ai-parrot's policy applies | The repo's `test_command` (C7, option C); policy-driven selection revisited in v1.1 |

### Still open after these amendments
- **Q1 residual (found while folding into the spec, 2026-10-14)**: six inline
  `python -c "from scripts.sdd.sdd_meta import …"` one-liners get a `sdd_meta` CLI
  (TASK-4299) and are rewritten by TASK-4089; the other inline `python -c` blocks in
  `sdd-spec.md` (stdlib JSON edits, `jsonschema`, `reserve_ids.existing_feature_id`) still
  need a system `python` in a foreign repo — ledger `issue:cac5c029bd88`.
  **Resolved 2026-10-15**: TASK-4334 (`scripts/sdd/spec_tools.py`) retired them; the issue is closed.
- **C7 option A** (repo-supplied test-selection policy): deferred to v1.1, pending the
  §6 evidence step.
- **Spike S1**: whether ai-parrot core installs without a compiler on macOS and Windows.
  The whole global install depends on it.
- **Install size**: adopters install the full ai-parrot core, which is heavier than
  FEAT-583's satellite would have been. This was accepted with FEAT-583's supersession.
- **bash/jq**: some shipped markdown still uses them. TASK-4091's audit reports it but
  doesn't remove it.

---

## 7a. Research Audit

Sources, all on `dev` at `2ed09515e`, 2026-10-14:
- the FEAT-633 spec, and task files TASK-4068 to TASK-4095 (index: 0/28 done);
- the FEAT-583 spec and brainstorm;
- `.gitignore`;
- the SDD files under `.claude/`, `.agent/`, `.agents/` and `.codex/`;
- `scripts/sdd/`;
- `flows/dev_loop/nodes/{base,research,feature_handoff}.py` and `_subagent_data/`;
- `test_subagent_parity.py`, which was run;
- FEAT-586's docs, scripts and tests;
- FEAT-620's `regen_core_paths.py`.

**Not done**: no codex second opinion (it isn't available on this machine), and no
FEAT-633 code was exercised, because none exists yet.

**Review 2026-10-14 (Jesus Lara with Claude)**, on `dev` at `a6e51614b`: re-read spec
§1 non-goals, M1, M2, M6; TASK-4070, 4074, 4080, 4085, 4086, 4089, 4090, 4091;
`knowledge/wiki/ledger/sdd_meta.py`; `scripts/sdd/review_checkpoint.py` imports;
`flows/dev_loop/test_scope/policy.py` and `regen_core_paths.py`; grep of helper, Jira
and `CLAUDE.md` references over the packaged file set; `test_subagent_parity.py`
re-run. Three corrections resulted (§2.2-5, §2.2-8, confidence map).

**Follow-up code review, 2026-10-14**, on `dev` at `e8e1ca8b2`: verified
`sdd_meta.resolve_flow()` and its fallback, TASK-4080's doctor exit contract,
TASK-4074's rollback contract, and helpers' `git` subprocess requirements.
Corrected C6's resolver scope, separated bootstrap runtime checks from repository
readiness in C14/C15, and made C3's wheel test retain explicit system prerequisites
with fixture inputs. This corrects the earlier claim that `resolve_flow()` was absent.

## 8. Provenance

| Version | Date | Author | Change |
|---|---|---|---|
| 0.1 | 2026-10-14 | Arturo Martinez + Claude | Initial amendment proposal for FEAT-633 |
| 0.2 | 2026-10-14 | Jesus Lara + Claude | All ⚖️ items, Q1 and C7 resolved; C6 reduced (no `CONFIG.md`, `test_command` added); branch-policy inventory updated (resolver omission corrected in 0.3), `KNOWN_BRANCHES` third copy, `lint_new`/`token_audit` not referenced by shipped files; Q1 resolution section added |
| 0.3 | 2026-10-14 | Codex, requested by Jesus Lara | C14/C15 scope bootstrap doctor to runtime health; C6 includes existing `resolve_flow()` and fallback tests; C3 retains allowlisted system tools and supplies fixture arguments/state; repeated claims reconciled |
| 0.4 | 2026-10-17 | Jesus Lara + Claude | C16 added: C12's sweep covered only `scripts/sdd` references and missed the shipped `sdd-coder`/`sdd-worker` hook, which addresses `worktree_environment.py` by monorepo source path; the module is relocated to `parrot/sdd/scripts/` with a re-export shim, invoked as `parrot sdd run worktree_environment --hook` behind a launcher fast path, and `test_no_repo_script_refs` is widened to any monorepo source path |
