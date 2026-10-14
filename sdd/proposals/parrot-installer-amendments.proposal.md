---
id: FEAT-633
amends: FEAT-633
title: FEAT-633 amendments — portability safeguards carried over from FEAT-583
slug: parrot-installer-amendments
type: feature
mode: enrichment
status: discussion
source: Review of FEAT-583 (portable-sdd-flow) against FEAT-633 (parrot-installer), 2026-09-25 → 2026-10-14
overall_confidence: high
base_branch: dev
projects: [ai-parrot, sdd-tooling, dev-loop, docs, ci]
tags: [installer, sdd-packaging, portability, publication-safety, amendment]
research_state: sdd/state/FEAT-633/
created: 2026-10-14
updated: 2026-10-14
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
- **13 amendments remain.** Four of them change an approved FEAT-633 decision and need
  Jesus's sign-off: **C4, C6, C10, C12**, marked ⚖️.
- **One new open question.** How installed commands call helpers in a global-only
  install (**Q1**). C3's test will expose it.

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
   fails. `.claude/agents/sdd-worker.md` lists `Monitor, TaskStop` in its `tools:` line;
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
6. **ai-parrot's code rulebook ships everywhere.** TASK-4090 ships `codebase-conventions.md`
   (aiohttp only, navigator-api, uv) as an always-loaded rule to all three hosts
   (`.claude/rules/` and `.agent/rules/`).
7. **Org data in shipped files, and the scanner can't see it.**
   - Across hosts: `trocglobal.atlassian.net` 11 times in 5 files, real `NAV-` ticket
     keys 102 times in 10 files, and the `agy` reviewer ban 3 times.
   - TASK-4070's six finding kinds detect none of these.
8. **Shipped references to monorepo-only helpers.** TASK-4089 keeps them on purpose
   (`scripts.sdd.review_checkpoint` at `.claude/agents/sdd-worker.md:588,607`, plus
   `lint_new`, `token_audit` and `codex_hook`), and its new test allows them. Those
   lines fail outside this monorepo.
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
  2. creates a managed layout (a temporary `PARROT_HOME`) containing only that wheel;
  3. creates an unrelated, non-Python git repo;
  4. runs `parrot sdd install`;
  5. runs **every helper invocation in the installed markdown, exactly as written**,
     with only `$PARROT_HOME/bin` on PATH and no repo `PYTHONPATH`.
- **Amends**: TASK-4091 (test) and TASK-4094 (release smoke test).
- **Done when**: it passes on Linux in CI. **It fails until Q1 is resolved, by design.**

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
- **Amends**: TASK-4091.
- **⚖️ Reverses**: the "no hash manifest" non-goal (spec §1, TASK-4091 line 210).
  **Why it's worth it**: without a record, the installer can't upgrade safely.
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
  - Add a committed `sdd/config.json`, owned by the team and validated with Pydantic:
    `base_branch`, `staging_branch` (optional), `hotfix_base`, `sync_down`
    (`action | manual | none`), `issue_tracker` (`jira | none`), `jira_host` (optional),
    `reviewer` (`codex | none`).
  - The installer renders it into a committed `sdd/CONFIG.md`.
  - Shipped commands say "the base branch in `sdd/CONFIG.md`" instead of literals.
    Command files therefore stay byte-identical across repos and FEAT-633's sync rule
    holds; only `CONFIG.md` differs.
  - ai-parrot's own `sdd/config.json` sets `dev`/`staging`/`main` and Jira, so
    ai-parrot's behaviour is unchanged.
  - Validation keeps today's lane rules: features never base on the hotfix branch, and
    hotfixes always base on it.
  - `sdd_meta.resolve_flow` takes its defaults from the config.
- **Amends**: a new M6 task, after TASK-4085 (which moves `sdd_meta`) and before
  TASK-4089 (the markdown rewrite). It depends on C8.
- **⚖️ Adds**: a configuration FEAT-633 doesn't have.
- **Done when**: a foreign repo using `main` plus `develop` can run the flow by editing
  only `sdd/config.json`.

### C8 — One source for branch policy in core
- **Problem**: §2.2-5. After C6, hardcoded copies would silently ignore the config.
- **Change**:
  - Replace `_LONG_LIVED_BRANCHES` and both `_parse_flow_frontmatter` copies with
    `sdd_meta` functions, using FEAT-583's `read_declared_base_branch(path) -> str | None`.
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
- **⚖️ Reverses**: the "2 rules" packaged in spec M6.
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
  - `review_checkpoint` can move now: it imports only core `sdd_coder`, which is in core.
  - `codex_hook` stays repo-only and out of shipped files.
  - Extend TASK-4089's `test_no_repo_script_refs` to fail on **any** `scripts.sdd.*` or
    `scripts/sdd/*` reference in shipped files. Historical `sdd/specs/` and `sdd/tasks/`
    are excluded.
- **Amends**: TASK-4089, plus a TASK-4086 entry for `review_checkpoint`.
- **⚖️ Reverses**: TASK-4089's "references to non-moved helpers stay untouched".
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

    After installing, the script runs `parrot self doctor`. A failure triggers
    TASK-4074's existing rollback, which removes only what this run created, and prints
    doctor's suggested fixes.
- **Amends**: TASK-4074, TASK-4075 and TASK-4095.
- **Done when**: tests show that each failed gate exits before any write, and that a
  failed post-install doctor run rolls back.

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

  These checks run when an `sdd/` tree exists, or with `--sdd`.
- **Amends**: TASK-4080, and TASK-4091 for the status hook.
- **Done when**: a fixture repo missing each prerequisite gets the matching check
  failing, with its fix.

### What's untouched (non-goals)
- FEAT-633's core design: the launcher, managed venv, `parrot self`, `--portable`, the
  store gate and the wheel matrix.
- No satellite package, no `sdd` binary, no symlinks: FEAT-583's rejected shape stays
  rejected.
- C7 (test-selection policy) is a discussion item, not an amendment.
- FEAT-586's project-mode install is unchanged.

### Integration risks
- **C6 and C11 change ai-parrot's own command files**, because of byte-equality.
  ai-parrot's `sdd/config.json` must land in the same change, or ai-parrot's own flow
  loses its branch policy.
- **C2 touches how the dev-loop loads prompts**, and shrinks TASK-4089's twin list.
  Coordinate the two.
- **C3 fails until Q1 is resolved.** Settle Q1 before TASK-4091 starts.
- **New tasks need IDs** (C6, C8, and Q1 if accepted). Reserve them with `reserve_ids`
  and append to FEAT-633's index; never rewrite it.

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
| `review_checkpoint` can move to core (C12) | medium | Imports only core `sdd_coder`; not test-verified |
| Size estimates (S/M) | medium | Judgement |

---

## 5. Open Questions

### Resolved (during this review)
- [x] Is FEAT-583 still a live spec? — *Resolved by Arturo Martinez*: No. It is superseded by FEAT-633 (commit `2ed09515e`).
- [x] Which FEAT-583 and review ideas carry over? — *Resolved by Arturo Martinez*: C2–C6, C8, and C9–C15. C1 and the host mapping part of C9 are already covered by FEAT-633's tasks.
- [x] Does the install script need its own dependency checks (C14 comment)? — *Resolved by Arturo Martinez*: the full check list lives in `parrot self doctor` (C15). The script keeps a minimal pre-install gate and runs doctor after installing.

### Unresolved (need a decision before FEAT-633 implementation)
- [ ] ⚖️ Approve C4, the installed-hash record that reverses "no hash manifest"? — *Owner: Jesus Lara*
- [ ] ⚖️ Approve C6, the repo config (`sdd/config.json` plus a generated `sdd/CONFIG.md`)? — *Owner: Jesus Lara*
- [ ] ⚖️ Approve C10, a conventions seed instead of shipping `codebase-conventions.md`? — *Owner: Jesus Lara*
- [ ] ⚖️ Approve C12, moving or guarding monorepo-only helpers in shipped files? — *Owner: Jesus Lara*
- [ ] **Q1** — How do installed commands call helpers when ai-parrot is only in the global managed venv? Recommended: a launcher-fronted `parrot sdd run <helper> [args]`. Alternative: a `parrot-python` shim in `~/.parrot/bin`. Both reverse FEAT-633's "single form `python -m parrot.sdd.scripts.<name>`". This blocks C3. — *Owner: Jesus Lara + Arturo Martinez*
- [ ] **C7** — Should test selection carry repo-specific policy in other repos, and where does ai-parrot's own policy live? See §6. — *Owner: Jesus Lara + Arturo Martinez*

---

## 6. Recommended Next Step

1. **Arturo and Jesus decide the ⚖️ items, Q1 and C7** in one session, using the
   protocol below.
2. **Fold the accepted amendments into FEAT-633**:
   - a spec revision 0.2 (§3 M3/M6, §4, §5, Revision History);
   - amend TASK-4070, 4074, 4075, 4080, 4086, 4089, 4090, 4091, 4094 and 4095;
   - reserve IDs for the new tasks (C6, C8, and Q1 if accepted);
   - drop TASK-4095's FEAT-583 stamping step, which is already done.
3. **Then start implementing FEAT-633.** Spikes S1–S6 can start now, because none of
   these amendments touch them.

### Protocol for deciding C7 (test-selection policy)

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
   - The bootstrap finishes by running `parrot self doctor`; a failure rolls back (C14b).
3. **Previews, then installs, in any repo.**
   `parrot sdd install --host claude|codex|google --dry-run` shows the plan (C5). The
   real install then:
   - deploys that host's commands, agents, skills and templates (FEAT-633's manifest);
   - seeds `sdd/config.json`, renders `sdd/CONFIG.md` (C6) and seeds `sdd/CONVENTIONS.md`
     (C10);
   - seeds the ID ledger and the worktree ignore (TASK-4091).
4. **Sets the branches and tracker in `sdd/config.json`.** The commands follow it.
   ai-parrot's rulebook and org data never arrive (C10, C11).
5. **Checks readiness with `parrot self doctor`** (C15): `origin`, base branch, ledger,
   `gh`/`jq`, host CLIs.
6. **Uses the `/sdd-*` commands.** Helpers run through the launcher (Q1), proven by the
   wheel-only test (C3). Monorepo-only steps are moved or skipped (C12).
7. **Upgrades by running `parrot sdd install` again.** Untouched files upgrade and edited
   ones are kept; `parrot sdd status` shows current, outdated or edited (C4).

### Before and after

| Concern | FEAT-633 today | After amendments |
|---|---|---|
| Platforms | Linux, macOS, Windows (pending spike S1) | Same |
| Helpers in a foreign repo | `python -m …` fails in a global-only install | Run through the launcher (Q1), proven by C3 |
| Codex/Google SDD files | Packaged (77 entries with `hosts`) | Same |
| Repo branches and tracker | ai-parrot's literals | Per-repo config (C6, C8) |
| Org and ai-parrot text | Ships verbatim in the public wheel | Scanned, made generic, blocked by CI (C11) |
| Rules shipped | ai-parrot's code rulebook | A team-owned conventions seed (C10) |
| Monorepo-only helpers | Shipped references fail elsewhere | Moved or guarded (C12) |
| Upgrades | Need `--force`, which overwrites edits | Untouched files upgrade, edits are kept (C4) |
| Preview | None | `--dry-run` (C5) |
| Diagnostics | Runtime and host configs | Plus SDD readiness (C15), run automatically after install (C14) |
| Install safety | Checksums, rollback | Plus a pre-install gate and explained commands (C14) |
| Install docs | Four documents, one verified | One canonical verified guide (C13) |
| Agent prompts | Three copies, parity test failing | One copy (C2) |
| Test selection elsewhere | ai-parrot's policy applies | Pending C7 |

### Still open after these amendments
- **The decisions**: C7, and Q1 (which blocks C3).
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

## 8. Provenance

| Version | Date | Author | Change |
|---|---|---|---|
| 0.1 | 2026-10-14 | Arturo Martinez + Claude | Initial amendment proposal for FEAT-633 |
