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
updated: 2026-10-21
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
| C25 | The installed guard hook resolves without the managed launcher (project-venv installs) | TASK-4091, TASK-4080 | — | S |

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

### C17 — Ship `/sdd-brief` (FEAT-698) through the installer
- **Problem**: FEAT-698 (`sdd-brief-hotfix-flow`, merged into `dev` on 2026-10-17 as PR
  #1715) landed after spec rev 0.3. It added a 15th shipped command
  (`.claude/commands/sdd-brief.md` + its Codex twin `.agents/skills/sdd-brief/SKILL.md`),
  a 14th template (`sdd/templates/brief.md`), a new repo-local helper
  (`scripts/sdd/brief_meta.py`, imported by `scripts/sdd/ensure_worktree.py:20`) and the
  `ensure_worktree --brief-key` input. `/sdd-spec` no longer scaffolds hotfixes; `/sdd-brief`
  is the hotfix lane every installed flow needs. Verified on `925b0f1a2`:
  - The TASK-4090 packaging globs (`.claude/commands/sdd-*.md`, `.agents/skills/sdd-*/SKILL.md`,
    `sdd/templates/*`) pick the command, the skill and the template up by themselves, but
    every count the tasks and the spec carry (14 commands, 12/13 templates, 77 manifest
    entries) is stale.
  - There is **no Google twin**: `.agent/workflows/sdd-brief.md` does not exist (FEAT-698
    shipped Claude + Codex only), so a `--host google` install would lack the hotfix lane and
    the `.agent/workflows/sdd-*.md` row would ship 14 while the other hosts ship 15.
  - `brief_meta` is in no move task. After TASK-4085 moves `ensure_worktree`, the moved
    module would still `from scripts.sdd.brief_meta import brief_worktree_plan` — a monorepo
    import that fails in a foreign repo and that `test_no_repo_script_refs` (C12) and the
    wheel-only test (C3) both catch. `brief_meta` also has no `main()`, and the shipped
    command tells the agent to "build the per-brief index with
    `scripts.sdd.brief_meta.write_brief_index`" — a Python symbol an installed flow cannot
    import.
  - `sdd-brief.md` carries four helper invocations TASK-4089's enumeration (made on
    `6c4ca5482`, before FEAT-698) does not list: `python -m scripts.sdd.ensure_worktree`
    (`:18`, `:132`), `scripts.sdd.brief_meta.write_brief_index` (`:151`) and
    `python -m scripts.sdd.check_task_graph` (`:154`); the Codex twin repeats three of them
    (`SKILL.md:39-40`). The TASK-4070 helper map has no `sdd-brief` row.
- **Decision** (Jesus Lara, 2026-10-18): fold `/sdd-brief` into the existing tasks; no new
  task id.
  - **TASK-4085** moves `brief_meta.py` with the other worktree helpers (`git mv`, one
    import rewrite `scripts.sdd.sdd_meta` → `parrot.sdd.scripts.sdd_meta`, alias shim left
    behind; `ensure_worktree.py` now gets two import rewrites). `tests/sdd_scripts/
    test_brief_meta.py` keeps importing through the shim, unmodified.
  - **TASK-4299** gives `parrot/sdd/scripts/brief_meta.py` an argparse `main()` in the
    `sdd_meta` style: `plan --slug <slug> --key <KEY> --base-branch <base>` (prints the
    `WorktreePlan` JSON) and `write-index <brief.md> --tasks <tasks.json> --worktree-root
    <dir>` (writes the per-brief index, prints its path).
  - **TASK-4089** creates `.agent/workflows/sdd-brief.md` (the `description:` frontmatter
    plus the byte-identical body of `.claude/commands/sdd-brief.md`, as every other Google
    twin) *before* its rewrite, adds the three `sdd-brief` files to the rewrite table,
    rewrites the prose `write_brief_index` reference to `parrot sdd run brief_meta
    write-index …`, and extends the twin parity test to `sdd-brief`.
  - **TASK-4070** adds the `sdd-brief` row to the pre-seeded helper map
    (`brief_meta`, `check_task_graph`, `ensure_worktree`) and the new files to the inventory.
  - **TASK-4090** updates the asset counts (15 commands per host, 13 tracked templates,
    **81** manifest entries); the globs themselves do not change.
  - **TASK-4091** adds the C3 scenarios for `ensure_worktree --brief-key` and
    `brief_meta write-index`, and its `--host google` check expects `agent/workflows/sdd-brief.md`.
- **Done when**: `parrot sdd install --host claude|codex|google` deploys `/sdd-brief` and
  `sdd/templates/brief.md` on every host; the installed `sdd-brief.md` references only
  `parrot sdd run …` forms, each with a C3 scenario; `import scripts.sdd.brief_meta` still
  works in the monorepo; `check_asset_sync.py` reports 81 entries.

### C18 — Complete the helper inventory
- **Problem**: the 2026-10-19 readiness review (`sdd/state/FEAT-633/readiness-checkpoint-2026-10-19.md`)
  found four helpers that shipped markdown calls but no move task covered:
  - `cache_test_contract` (`sdd-task.md:369` and twins; FEAT-699)
  - `test_report` (`sdd-done.md:257,277` and twins; 2026-10-16)
  - `check_e2e_closeout` (`sdd-done.md:206`; FEAT-703)
  - `close_resolved_issues` (`sdd-done.md:414` and twins; 2026-10-16)

  Two of them find `test_scope` through a monorepo `_KERNEL_PARENT`. C12's premise, that
  `review_checkpoint` was the only one left, no longer holds.
- **Change**:
  - Move all four with new task **TASK-4508** (move D, depends on TASK-4085); TASK-4089
    depends on it.
  - Every `_KERNEL_PARENT`-style path loader becomes package-relative
    (`parents[2] / "flows" / "dev_loop"`), the same rewrite TASK-4086/4088 already apply.
  - M6's helper list becomes every module that moves: 26 plus `__init__`.
  - `nightly_red_set` stays repo-local: only CI calls it.
- **Amends**: TASK-4070 (helper map), TASK-4089 (`MOVED`), TASK-4091 (C3 scenarios). Adds TASK-4508.
- **Decision note**: TASK-4508 was approved with PR #1741 (merged 2026-10-19).
- **Done when**: no shipped file invokes a helper that is not in `parrot.sdd.scripts`.

### C19 — C16 move mechanics
- **Problem**: moving `worktree_environment` (C16) breaks three things the spec did not cover:
  - **Kernel lookup.** `_load_guard_bash` (`worktree_environment.py:294-307`) imports
    `test_scope` relative to its own package, or from its own directory when run as a
    script. Neither path resolves from `parrot/sdd/scripts/`. `_scope_guard` (`:336-340`) turns
    that ImportError into "allow", so FEAT-563's over-broad-pytest guard would switch off
    silently.
  - **Hooks during the transition.** Until TASK-4089 rewrites the frontmatter, the live
    hooks run the **old** path with a bare `python3`.
  - **Programmatic hook command.** `dispatchers/claude.py:625` derives the command from
    `__file__`.
- **Change**:
  1. In both module and script mode, `_load_guard_bash` puts the package-relative kernel
     parent (`parents[2] / "flows" / "dev_loop"`) on `sys.path` and imports
     `test_scope.guard`. It never imports `parrot.flows.dev_loop`, whose `__init__` loads
     the whole dev-loop stack.
  2. The old path stays a re-export shim for importers. Run as a script, it executes the
     moved file by package-relative path through `runpy.run_path`, using only the stdlib.
     A bare `python3` therefore keeps working.
  3. The programmatic hook command (TASK-4509) is
     `shlex.join([sys.executable, "-m", "parrot.sdd.scripts.worktree_environment", "--hook"]) + " || exit 2"`.
     It does not depend on `PATH`, and `parrot/sdd/__init__.py` and
     `parrot/sdd/scripts/__init__.py` are import-free, so it stays cheap. The shipped
     frontmatter keeps `parrot sdd run worktree_environment --hook` (Q1 single form).
  4. The launcher fast path lives in **TASK-4509**, split out of TASK-4072. Its latency
     budget reuses S4's targets: median delta ≤ 5 ms non-managed, ≤ 50 ms managed→project.
- **Amends**: TASK-4085 (C16 rows ungated), TASK-4509 (form and budget fixed). Adds TASK-4509.
- **Decision note** (Jesus Lara, 2026-10-19): "the test scope was settled in a spec newer
  than FEAT-633". That is FEAT-563/FEAT-699's guard. This clause only keeps that guard
  working across FEAT-633's own move, which those specs predate. Items 1–3 are mechanical
  and need confirmation in review.
- **Done when**: `test_worktree_environment.py` passes against the moved module, and the
  old path still answers `--hook` when run with a bare interpreter.

### C20 — `wikitoolkit mcp` on a core-only install
- **Problem**: the managed runtime installs only `ai-parrot`. The MCP server base is
  already core (FEAT-403: `parrot/mcp/{server_base,local_server,adapter}.py`). But FEAT-540
  (`fae0b33b9`) moved the wiki tool wrappers to `parrot_tools.wiki` (ai-parrot-tools), and
  `build_framework_tools` (`mcp_server.py:362-399`) imports them eagerly. So `wikitoolkit mcp`
  fails before `initialize` on a core-only install. The SDK fallback works only with mcp 1.x
  (`:471`).
- **Change** (interim for v1):
  - The managed runtime installs `ai-parrot-tools` at the same version pin as `ai-parrot`:
    bootstrap `--global` (TASK-4074/4075), S1 and its install matrix (TASK-4068), the release
    smoke legs (TASK-4094, which already builds `build-tools`).
  - `parrot self` treats it as part of the base runtime (TASK-4079).
  - `doctor` checks that `parrot_tools.wiki` imports (TASK-4080).
  - S1 also records whether ai-parrot-tools' dependencies (PyGithub → cryptography/pynacl,
    ruamel-yaml) install without a compiler on every leg.
- **Follow-up, outside FEAT-633**: a core-only fallback. `_resolve_transport` treats a
  missing `parrot_tools.wiki` as "framework unavailable", and the server registers the
  wiki descriptors on the core `StdioMCPServer`. That changes a contract FEAT-540 tested
  on purpose (`test_mcp_transport_selector.py:159`), so it needs that owner's agreement.
  Also: fold `ai-parrot-server`'s older duplicate `transports/stdio.StdioMCPServer` into the
  core one.
- **Amends**: TASK-4068, 4074, 4075, 4079, 4080, 4094.
- **Decision note** (Jesus Lara, 2026-10-19): "the MCP base (abstract base + stdio) lives in
  ai-parrot-tools + server; the idea would be to move that foundational base into core."
  Verified on `dev` `0263f0724`: the base is already in core. What is missing on a core-only
  install is the wiki tool wrappers, so the interim above, plus the follow-up, implements
  the intent without undoing FEAT-540.
- **Follow-up decision note** (Jesus Lara, 2026-10-20 11:58): "the MCP abstract + the stdio
  transport must be migrated to core, leaving the rest (the other MCP transports) in
  ai-parrot-server." Verified on `dev` `4a06b88ab`:
  - **Already in core** (FEAT-403, TASK-2077/2078, 2026-08-03): `parrot/mcp/server_base.py`
    (`MCPServerBase`) and `parrot/mcp/local_server.py` (`LocalMCPServerBase`, `StdioMCPServer`).
  - **Already in `ai-parrot-server`**: the other transports (`transports/{http,sse,streamable_http,
    websocket,unix,quic}.py` on `RemoteMCPServerBase`).
  - **Still to do:** ai-parrot-server keeps an older duplicate `transports/stdio.py`
    (`StdioMCPServer` + the `StdioMCPSession` client), used by `server.py:20` and
    `simple_server.py:12`. That is `issue:7a366d6004de`.
  - **Not part of the request:** the blocker for a core-only `wikitoolkit mcp` is the wiki tool
    wrappers in `parrot_tools.wiki` (FEAT-540), not the MCP base (`issue:2c263fd19a1a`).

  Still open: is the stdio consolidation a FEAT-633 task or a separate fix-lane item? The C20
  interim (ai-parrot-tools in the managed runtime) does not depend on it.
- **Done when**: S1 shows `wikitoolkit mcp` answering `initialize` from the managed runtime
  on every leg.

### C21 — Test steps in a foreign repository (C7 follow-through)
- **Problem**: C7 option C ("outside ai-parrot, run the repo's `test_command`") predates
  FEAT-699/695. Those added three steps C7 never covered:
  - `cache_test_contract`: exits 2 when the spec has no Validation Contract.
  - `select_tests`: its fallback is dead outside `packages/*/src`.
  - `test_report`: renders **"Gate: ✅ no new reds"** for a run that selected zero tests,
    the exact failure option B was rejected for.

  FEAT-633's own spec also lacks the contract.
- **Change**:
  1. `sdd/config.json` `test_command` is the switch. When it is set, the shipped `/sdd-done`
     feature tier, sdd-worker's merge step, qa-runner and sdd-autopilot run it once from the
     repo root instead of `select_tests`/`test_report`. They record the command, exit code
     and output tail; a non-zero exit blocks the merge.
  2. When it is null (ai-parrot), the FEAT-699 path is unchanged.
  3. A tier that ran no tests is reported "⚠️ not run — no tests selected", never ✅.
  4. The spec template and the `/sdd-spec` hint say: "repos with `test_command` set: write
     `none — fallback`". `/sdd-task` continues past a missing section only when
     `test_command` is set. `cache_test_contract` stays strict.
  5. `parrot sdd install` warns when `test_command` is null.
  6. C3 pins each step's outcome.
  7. FEAT-633's spec gains a §4 Validation Contract, and its index is re-cached.
- **Deferred to v1.1** (with C7 option A): a real foreign-repo validation phase. That
  covers layout-aware selection, a provisioned worktree venv, the baseline `PYTHONPATH`,
  and a zero-test gate inside `report.py`.
- **Amends**: TASK-4089 (prose; adds `sdd/templates/spec.md`), TASK-4299 (`test_command`
  semantics: shell string, cwd = repo root, non-blank), TASK-4091 (install warning, C3
  outcomes).
- **Decision note** (Jesus Lara, 2026-10-19): "the installer would need a validation phase,
  but like Claude I can't picture how to manage it in another repo; it could be simulated
  in a worktree, but it still depends on a virtualenv that already has everything."
  Therefore v1 degrades safely and the validation phase is deferred.
- **Done when**: in a foreign repo with `test_command`, every shipped test step runs that
  command or reports ⚠️; none reports ✅ on zero tests.

### C22 — Monorepo-specific text in shipped files (C16 residuals)
- **Problem**: once the helper rewrites are applied, the C16 regex still matches 39 shipped
  lines. These are `packages/` paths (sub-packages keep growing), one hook line and bare
  `scripts/`. A further set it does not match also ties shipped text to ai-parrot:
  `tests/sdd_scripts/…` citations, `PYTHONPATH=`, `source .venv/bin/activate`, navconfig
  `python -c` one-liners, and CI file names.
- **Change** (one rule per category; TASK-4089 applies them to all twins in the same pass):
  - **A — examples**: real paths become fixed placeholders (`<src>/<pkg>/module.py`,
    `<tests>/test_module.py::test_case`, `sym:<src>/<pkg>/module.py#ClassName`). Nothing in
    this category is allowlisted.
  - **B — layout and environment**: shipped text points to `sdd/CONVENTIONS.md` instead of
    describing the layout, venv activation, `PYTHONPATH` or the `projects` vocabulary.
    ai-parrot's own rules move to `.claude/rules/codebase-conventions.md` and its twin
    `.agent/rules/codebase-conventions.md` (not shipped). The seed gains `## Repository
    layout` and `## Project areas`. `SddConfig` gains `projects: list[str] | None`, which
    replaces `KNOWN_PROJECTS` when set; when it is not set, unknown values warn and never
    fail.
  - **C — this repo's tests or CI cited as evidence**: delete the citation and keep the
    behaviour statement. CI facts become conditions ("if your repo runs a sync-down
    Action…").
  - **D — portable**: allowlist with a reason. Only `.claude/hooks/sdd-worker-format.sh:76`
    (`${CLAUDE_PROJECT_DIR:-}/.venv/bin`, the target repo's own venv).
  - **E — repo code through `python`**: navconfig one-liners become a precondition
    ("export `JIRA_INSTANCE`, `JIRA_USERNAME`, `JIRA_API_TOKEN`; see `sdd/CONVENTIONS.md`").
    The `sdd-start` evidence reference lists its fields inline.
  - **`/sdd-insight` does not ship in v1.** It depends on unshipped
    `reference/sdd-insight/` and `.claude/workflows/sdd-insight.js`. Dropping it brings the
    asset count from 81 to **78**.
  - Both C16 gates (TASK-4089 test, TASK-4090 `--check`/`--wheel`) add a second pattern:
    `tests/sdd_scripts/|\bfrom navconfig\b|PYTHONPATH=|reference/sdd-insight/`.
- **Amends**: TASK-4089, 4090 (allowlist, second pattern, seed sections, 78 assets), 4091
  (no `sdd-insight` scenarios), 4299 (`projects`).
- **Decision note** (Jesus Lara, 2026-10-19): "the number of sub-packages under `packages/`
  has grown a lot." The category rules, the `projects` key and dropping `/sdd-insight` are
  the review's recommendations, adopted for v1; confirm in review.
- **Done when**: both C16 gates pass with the single allowlisted line.

### C23 — Foreign repos get the shared ledger
- **Problem**: FEAT-694's sync depends on a `.gitattributes` `merge=union` entry and four
  git hooks. `parrot claude install` is the only thing that installs those hooks
  (`claude_code/installer.py:973`), and nothing writes `.gitattributes` in another repo.
  Yet the shipped `/sdd-done` step 9.1 calls `export-log`/`rotate-log`.
- **Change**: `parrot sdd install` (any host):
  - writes a marker-delimited `.gitattributes` block for `sdd/ledger/events.jsonl` and
    `sdd/ledger/archive/*.jsonl` (`merge=union`) and records it in the receipt;
  - installs the four ledger hooks through the same installer function.

  `parrot self doctor --sdd` checks both.
- **Amends**: TASK-4091, TASK-4080.
- **Decision note**: review recommendation adopted; confirm in review.
- **Done when**: C3's foreign repo has the block and the hooks after `parrot sdd install --host codex`.

### C24 — Host and store follow-through
- **Windows** (M5): `git_hook_block`/`ledger_hook_block` quote the binary path and write it
  with forward slashes (`claude_code/assets.py:206-207,236`; today `sh` strips the
  backslashes). `_is_wikitoolkit_entry` matches on the script basename, so `.exe` counts
  (`installer.py:762`). (TASK-4081, 4082)
- **`--remote` × `--portable`**: `--remote` decides only the `wikitoolkit` key. When that
  entry is http, url-only, absent or foreign, the mode is inferred from the managed
  `parrot-*` entries. (TASK-4082, 4083)
- **Store** (M7):
  - The plane is stamped at creation (`_ensure_schema`) as well as in `_migrate`.
  - A stored `schema_version` greater than `SCHEMA_VERSION`, compared as integers, raises
    `WikiStoreVersionError` instead of being migrated and re-stamped downward. This fixes
    ledger `issue:f249c19e8a4d`. That schema comparison is the whole gate: `min_runtime_version`
    is stamped at creation and at migration but only quoted in the error, never compared
    (owner, 2026-10-20: comparing release numbers was too strict).
  - Lock or backup creation failing with any `OSError` other than `FileExistsError` raises
    a clear error that names the directory; migration is never silently skipped.
  - `SourceCollectionManager._connect` opening `wiki.db` directly stays a known bypass, outside scope
    (filed as `SourceRegistry`, a name that does not exist):
    ledger `issue:1555e747bcb9`. (TASK-4092, 4093)
- **SDD**:
  - TASK-4089 ports the E2E gate to the Google `/sdd-done` twin.
  - `brief_meta` and `ensure_worktree` read `SddConfig` instead of branch literals (TASK-4299).
  - S5 scans `.agents/` and `.agent/` too (TASK-4070).
- **Toolkits and doctor**:
  - `bounded-source.yaml` and `targeted-writer.yaml` declare `requires_dist: parrot_tools`
    and `requires_pip: ai-parrot-tools` (TASK-4077).
  - `doctor` checks both Gemini MCP config files, but checks cross-repo collisions only on
    the user-global one (TASK-4080).
- **Launcher and release**:
  - The launcher's `.git` walk-up stops at the system temp directory, mirroring
    `wiki.project._is_temp_root` (TASK-4071).
  - `install-matrix` gains a linux-aarch64 leg (TASK-4094).
  - `mcp/local_cli.py` is in TASK-4083's scope; the contradictory exclusions are dropped.
- **Decision note** (Jesus Lara, 2026-10-19): on the store, "I hope an issue tracker was
  created for that error". Both issues are filed (above). Everything else in C24 is the
  review's recommendation, adopted for v1; confirm in review.

### C25 — The installed guard hook must resolve without the managed launcher
- **Problem**: C16 makes the shipped `sdd-coder` / `sdd-worker` frontmatter run the bare
  `parrot sdd run worktree_environment --hook || exit 2`, and C3 proves it only with
  `$PARROT_HOME/bin` on PATH. That covers the `--global` install, not the other supported
  setup: ai-parrot installed **only** into the target repo's own `.venv` (FEAT-586 project
  mode, `uv pip install ai-parrot ai-parrot-tools` + `parrot claude install`). There, the
  bare `parrot` in the hook resolves to whatever is first on the Claude Code process's
  PATH:
  - **nothing**, when the venv is not activated (an `sdd-worker` launched in tmux, or from
    a worktree): `parrot: command not found` → `|| exit 2` → every Bash / Write / Edit of
    the seat is denied. The guard fails closed, so it is not a security hole, but it makes
    the seat unusable;
  - **another repo's venv**, when that one happens to be on PATH. The launcher re-execs only
    from the managed venv (M1), so a non-managed `parrot` runs the guard with that venv's
    code. `shared_environments` (`worktree_environment.py:74-92`) still protects
    `<root>/.venv` and the main checkout's `.venv`, so protection holds, but the guard
    version is not the repo's.
  Observed 2026-10-21 in navigator-eventbus (project-venv install, no `~/.parrot/bin`):
  the user hand-patched both agent files to
  `<root>/.venv/bin/python3 -I <root>/.venv/lib/python3.11/site-packages/parrot/flows/dev_loop/worktree_environment.py --hook`,
  which hardcodes the repo path **and** the Python minor version and breaks on any venv
  rebuild. `parrot claude install` does not manage these files, so nothing re-renders them.
  `parrot self doctor` checks that `~/.parrot/bin` is on PATH, not that the installed hook
  command resolves.
- **Change**:
  1. **The installer renders the hook command; the asset stays canonical.** The packaged
     copy (and `.claude/` in the monorepo) keep the bare form, so the C2/C16 byte-equality
     sync check is untouched. `parrot sdd install` renders the one line when it writes a
     Claude agent target that carries it, choosing:
     - **bare** `parrot sdd run worktree_environment --hook || exit 2` when `--portable` is
       given, or when `shutil.which("parrot")` resolves under `parrot_home()` (the managed
       launcher, which re-execs into the project venv);
     - **baked** `<quoted script_path(Path(sys.prefix), "parrot")> sdd run worktree_environment --hook || exit 2`
       otherwise: the `parrot` console script of the venv running the install. No Python
       version, no `site-packages`, no source path; the M1 launcher's script-path helper
       gives the Windows form; quoting follows C24 (forward slashes + `shlex.quote`), then
       YAML single-quote escaping (`'` → `''`).
     When the baked venv is neither `<root>/.venv` nor the main checkout's `.venv`, the
     install adds a `warning:` naming it.
  2. **Classification compares the rendered bytes.** `classify_entry` and `_apply_asset`
     use the rendered payload instead of the raw packaged bytes, and the receipt records its
     SHA. A venv rebuild, a move to the global launcher, or adding `--portable` therefore
     shows as `outdated`, and a re-run upgrades it without `--force`.
  3. **`parrot sdd install --portable`** forces the bare form, for teams that commit
     `.claude/agents/` and give every member the global launcher. It means the same as the
     host installers' `--portable` (M5): committable, with the launcher on PATH assumed.
  4. **Status and doctor.** `sdd_status` reports
     `"guard_hook": {"form": "bare" | "baked" | "other" | None, "command": str | None,
     "targets": [...], "resolvable": bool}`, read from the agent files on disk (installed
     or foreign). `parrot self doctor --sdd` adds `sdd: guard hook`: it fails when the
     command does not resolve (bare: `shutil.which("parrot")`; baked: the path exists) or
     is `"other"` (a hand-patched command such as the navigator-eventbus one). The fix line
     says to re-run `parrot sdd install`, or to install the global launcher and use
     `--portable`. Doctor sees the shell's PATH, not the Claude Code process's, and says so
     in the detail for the bare form.
  5. **Hand-copied agents.** Files copied by hand from ai-parrot (navigator-eventbus,
     commit `1c50c53`) are `foreign` under C4 and are never overwritten, even with
     `--force`. Doctor's guard check names them; the documented fix is to delete the two
     files and re-run `parrot sdd install`. There is no adopt-foreign path in v1.
- **Unchanged**: the programmatic hook command (`sys.executable -m
  parrot.sdd.scripts.worktree_environment --hook`, C19), which never depended on PATH; the
  TASK-4509 fast path, which also serves the baked absolute path (a non-managed launcher,
  ≤ 5 ms budget); C3's managed-PATH proof.
- **Amends**: TASK-4091 (rendering, `--portable`, `sdd_status["guard_hook"]`, tests),
  TASK-4080 (`sdd: guard hook` check). No new task, no new IDs.
- **Decision note** (Jesus Lara, 2026-10-21): approved: "prepara el cambio en FEAT-633 del
  instalador", after the navigator-eventbus finding.
- **Done when**: in a foreign repo with ai-parrot only in `<root>/.venv` and neither
  `$PARROT_HOME/bin` nor the venv's `bin` on PATH, the installed hook denies a
  shared-environment write (`test_installed_hook_project_venv_only`); the baked command
  contains neither `python3.` nor `site-packages`; re-rendering after a mode change is an
  `outdated` → upgrade; doctor fails on an unresolvable or hand-patched hook.

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

### Resolved (readiness review with Jesus Lara, 2026-10-19)
- [x] Readiness decisions D1–D18 (`sdd/state/FEAT-633/readiness-checkpoint-2026-10-19.md`):
  - D1 → C20
  - D2 → C21
  - D3 and D18 → C22
  - D4 and D17 → C19
  - D5 → C23
  - D6–D16 → C24

  Jesus answered D1, D2, D3, D4 and D8 directly (quoted in each clause). The rest adopt
  the review's recommendations and are confirmed in the PR review.

### Resolved (PR #1746 review, 2026-10-20)
- [x] **Codex review findings** on TASK-4091:
  - **P1** — validate an existing `sdd/config.json` before any write; a malformed file aborts the
    install and leaves the repo untouched.
  - **P2** — ledger hooks on uninstall. Adopted with a correction: removing them unconditionally
    would break `parrot claude install`, which owns the same blocks. The receipt therefore records
    which hooks this integration created, and uninstall removes only those when no `parrot-wiki`
    block shows the integration is shared.
- [x] **The ~20 "Note for implementer" items the readiness pass left** are resolved in the tasks:
  - Lockstep `ai-parrot-tools` on an unpinned update (4079).
  - `parrot_tools.wiki` in `--runtime-only`, and `.gitattributes` checked by its lines (4080).
  - Forward slashes plus `shlex.quote` for hook paths (4081).
  - Mixed `parrot-*` entries resolve to portable if any is portable (4082/4083).
  - A relative `--config` resolves against the project root (4083).
  - The shim uses the alias form (4085).
  - qa-runner edited; zero tests always reported ⚠️; the third `codebase-conventions.md` twin edited
    within budget; Google twin added to `_DOC_SURFACES` (4089).
  - Final seed wording (4090).
  - Receipt `blocks`/`ledger_hooks` (4091).
  - `WikiStoreVersionError.newer_schema` message; a non-integer `schema_version` is never refused (4092).
  - `WikiStoreMigrationError`, with backup `OperationalError` wrapped (4093).
  - Hosted `ubuntu-24.04-arm` runner, since the repo is public (4094).
  - `projects` and `brief_meta` get the config through `_config_for` and pydantic validation context (4299).
- One item stays deliberately evidence-gated, with an explicit default: TASK-4083's Codex project pin
  waits for spike S3 (TASK-4069). With no evidence of variable expansion, nothing is added.

### Unresolved
- C20 follow-up (Jesus Lara, 2026-10-20): the stdio consolidation (`issue:7a366d6004de`) as a FEAT-633
  task or a fix-lane item. It does not block any FEAT-633 task (see C20).
- Otherwise none. Rev 0.6 folds into FEAT-633 spec revision 0.5; the PR #1746 review resolutions are recorded in the spec with `[PR #1746 review]` tags.
  Rev 0.7 (C25) folds into spec revision 0.6.

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
| 0.6 | 2026-10-20 | Arturo Martinez + Claude, decisions by Jesus Lara; PR #1746 review resolutions (Codex P1/P2 + implementer notes) | C18–C24 added from the 2026-10-19 readiness review against `dev` `9f51c7735`/`0263f0724`: helper inventory completed (TASK-4508); C16 move mechanics (kernel lookup, by-path shim, programmatic hook command, TASK-4509); `wikitoolkit mcp` needs ai-parrot-tools on a core-only install (interim + follow-up); test steps in foreign repos (C7 follow-through, own Validation Contract, validation phase deferred to v1.1); monorepo-specific text rules (78 assets, `/sdd-insight` not shipped); shared ledger in foreign repos; host/store follow-through (ledger `issue:f249c19e8a4d`, `issue:1555e747bcb9`) |
| 0.5 | 2026-10-18 | Jesus Lara + Claude | C17 added: `/sdd-brief` (FEAT-698, merged after rev 0.3) ships through the installer — `brief_meta` joins TASK-4085's move and gets a CLI in TASK-4299, TASK-4089 creates the missing Google twin `.agent/workflows/sdd-brief.md`, counts updated (15 commands per host, 13 tracked templates, 81 manifest entries), C3 scenarios for `ensure_worktree --brief-key` / `brief_meta write-index` |
| 0.7 | 2026-10-21 | Jesus Lara + Claude | C25 added after the navigator-eventbus finding: the bare `parrot sdd run worktree_environment --hook` in the installed `sdd-coder`/`sdd-worker` frontmatter fails closed when ai-parrot lives only in the repo's `.venv`; `parrot sdd install` renders the line (bare when the managed launcher is on PATH or `--portable`, else the absolute `parrot` script of the installing venv; no Python version), classification compares rendered bytes, `sdd_status["guard_hook"]` + doctor `sdd: guard hook` (amends TASK-4091, TASK-4080) |
