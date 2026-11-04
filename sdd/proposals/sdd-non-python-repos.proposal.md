---
id: FEAT-805
title: "Make the packaged SDD flow work in non-Python repositories: configuration out of pyproject.toml, reachable test runners, auto-detected toolchain profiles, worktree setup, language-neutral prompts"
slug: sdd-non-python-repos
type: feature
mode: enrichment
status: discussion
source:
  kind: inline
  jira_key: null
  jira_url: null
  fetched_at: 2026-11-04
  summary_oneline: "Make the SDD flow (commands, agents, scripts, installer, config) work in non-Python repositories such as TypeScript + SvelteKit"
overall_confidence: medium
base_branch: dev
projects: [sdd-tooling, dev-loop, ai-parrot]
tags: [sdd, non-python, sdd-config, toolchain-profiles, worktree, test-runners, installer]
research_state: sdd/state/FEAT-805/
created: 2026-11-05
updated: 2026-11-05
---

# FEAT-805 — Make the packaged SDD flow work in non-Python repositories

> **Mode**: enrichment
> **Confidence**: medium (high for phases 1–2; the prompt inventory behind phase 3 is partly second-hand)
> **Source**: `inline`
> **Audit**: [`sdd/state/FEAT-805/`](../state/FEAT-805/)

---

## 0. Origin

The original request, preserved verbatim. The full source is at `sdd/state/FEAT-805/source.md`.

> El actual flujo SDD está muy enfocado a paquetes python (busca cosas en pyproject.toml, etc) pero hemos
> usado el flujo SDD en otras condiciones, ejemplo proyectos con typescript+svelte como este:
> `/home/jesuslara/proyectos/navigator/navigator-frontend-next`, entonces deberíamos homologar los comandos
> y el flujo sdd para funcionar dentro de repositorios no-python

Clarification, same session:

> lo que señalo es que hay cosas (como el modo nativo, etc) son leídas desde pyproject.toml y ese archivo
> no existiría en un repo no-python

**Initial signals** (extracted, not interpreted):
- Verbs: "homologar" → make one flow behave the same everywhere (enrichment, not a bug report).
- Named entities: `pyproject.toml`, "modo nativo" (the native sandbox), TypeScript + Svelte,
  `navigator-frontend-next`.
- Components / labels: none (inline source).
- Acceptance criteria provided: no. The reference repository is the implied acceptance test.

---

## 1. Synthesis Summary

The packaged SDD flow (`parrot sdd install`, FEAT-633) already installs into a repository that has no
Python project, but several things it needs afterwards can only be declared in `pyproject.toml`: the
sandbox mode (`resolve_sandbox_mode`), the sandbox network policy (`load_launch_config`) and the worktree
artifact manifest (`load_manifest`). Beyond configuration, the test-runner layer is unreachable outside
ai-parrot (settings in a git-ignored file, a vitest adapter with ai-parrot defaults, a guard that rewrites
to a monorepo-only path), lint / format / type-check are fixed to ruff, black and mypy, nothing prepares a
worktree's dependencies, and the contract verifier and templates only understand Python. The reference
repository, `navigator-frontend-next`, sidesteps all of this with a hand-ported fork that has not been
updated since September. This proposal moves the configuration into `sdd/config.json` (`SddConfig`),
makes the runners reachable, adds auto-detected toolchain profiles and a declared worktree setup command,
neutralises the prompts and templates, and uses the migration of the reference repository as the
acceptance test. FEAT-802 and FEAT-804 both list this as a deferred follow-up.

---

## 2. Codebase Findings

> All entries are grounded in the findings at `sdd/state/FEAT-805/findings/`. Paths are relative to the
> repository root; `…/parrot/` abbreviates `packages/ai-parrot/src/parrot/`.

### 2.1 Localization

| # | Path | Symbol | Lines | Role | Evidence |
|---|------|--------|-------|------|----------|
| 1 | `…/parrot/sdd/config.py` | `SddConfig` | 19-35 | committed team config (`extra="forbid"`); gains the new blocks | F004 |
| 2 | `…/parrot/sdd/config.py` | `load_sdd_config` | 106-125 | the loader every new consumer goes through | F004 |
| 3 | `…/parrot/sdd/scripts/native_claude_sandbox.py` | `resolve_sandbox_mode` | 246-290 | reads `[tool.parrot.sdd] sandbox` from `pyproject.toml` only | F001 |
| 4 | `…/parrot/sdd/scripts/native_claude_sandbox.py` | `load_launch_config` | 637-675 | reads `sandbox_allowed_domains` / `gh_token` from the primary checkout's `pyproject.toml` only | F002 |
| 5 | `…/parrot/sdd/launch_cli.py` | — | 21-24 | per-launch flags, today's only alternative | F002 |
| 6 | `…/parrot/flows/dev_loop/native_artifacts.py` | `load_manifest` | 103-126 | reads `[tool.parrot.worktree]` from `pyproject.toml` only | F003 |
| 7 | `…/parrot/flows/dev_loop/native_artifacts.py` | `NativeGroup` | 49-71 | manifest model, reusable unchanged | F003 |
| 8 | `…/parrot/knowledge/wiki/claude_code/welcome.py` | `_set_pyproject_sandbox` | 148-180 | the only writer of `[tool.parrot.sdd]` | F005 |
| 9 | `…/parrot/sdd/scripts/ensure_worktree.py` | `main` | 442-451 | post-create hook point (native sync today) | F003, F011 |
| 10 | `…/parrot/sdd/installer.py` | `GITIGNORE_BLOCK` | 49-54 | git-ignores all of `.parrot/` in the target repository | F006 |
| 11 | `…/parrot/flows/dev_loop/test_scope/runners/registry.py` | `BUILTIN_MODULES` | 14-20 | runner registry; settings path `.parrot/test_runners.toml` | F006 |
| 12 | `…/parrot/flows/dev_loop/test_scope/runners/vitest.py` | `ADAPTER` | 13-86 | mandatory TOML `cwd`, `pnpm exec` only, `admin-ui` default | F007 |
| 13 | `…/parrot/flows/dev_loop/test_scope/planner.py` | — | 99-106 | feeds TOML settings to non-pytest adapters | F007 |
| 14 | `…/parrot/flows/dev_loop/test_scope/guard.py` | `VERDICT_ARGV` | 21 | rewrite target `python scripts/sdd/select_tests.py` | F008 |
| 15 | `…/parrot/sdd/scripts/select_tests.py` | `main` | 497-521 | `--run` ignores `invocation.cwd`; appends `--timeout` to every runner | F009 |
| 16 | `…/parrot/flows/dev_loop/sdd_coder/lint.py` | `detect_formatter` | 69-90 | engine lint pass: formatter from `pyproject.toml` | F010 |
| 17 | `…/parrot/flows/dev_loop/sdd_coder/lint.py` | `_existing_python_files` | 119-121 | engine lint pass: `.py`-only filter | F010 |
| 18 | `…/parrot/sdd/audit.py` | `EXTERNAL_TOOLS` | 27 | tool audit lists `black` / `pylint` for every repository | F017 |
| 19 | `…/parrot/sdd/_assets/claude/agents/sdd-qa.md` | — | 57-60 | unconditional `ruff` + `mypy` gate | F012 |
| 20 | `…/parrot/sdd/_assets/claude/agents/sdd-contract-probe.md` | — | 61-66 | Python-only probe commands | F013 |
| 21 | `…/parrot/sdd/_assets/claude/commands/sdd-done.md` | — | 165-182 | full lint pass, ruff only | F014 |
| 22 | `…/parrot/sdd/_assets/claude/agents/qa-runner.md` | — | 84-89 | lint / type-check step, ruff and mypy only (guarded) | F014 |
| 23 | `…/parrot/sdd/_assets/claude/hooks/sdd-worker-format.sh` | — | 69-93 | format hook: `.py` files, black and pylint | F014 |
| 24 | `…/parrot/sdd/_assets/sdd/sdd_templates/task.md` | — | 53-281 | Python-shaped task template | F014 |
| 25 | `…/parrot/sdd/_assets/sdd/sdd_templates/brief.md` | — | 37 | pytest-only validation guidance | F014 |
| 26 | `…/parrot/sdd/_assets/sdd/sdd_templates/design_research.prompt.md` | — | 15-16 | hard-coded ai-parrot identity | F014 |

### 2.2 Constraints Discovered

- **Trusted reads come from the primary checkout.** `load_launch_config` reads only the primary
  checkout because the sandboxed session can write its own worktree copy, and the modes `off` / `legacy`
  cannot be set from a file at all.
  *Implication*: the `sdd/config.json` reader for sandbox policy, runner settings and the worktree setup
  command must resolve the primary checkout. A command that runs on the host must never be taken from a
  branch a sandboxed session can write.
  *Evidence*: F001, F002

- **`SddConfig` forbids unknown keys, and `ensure_worktree` imports its helpers by file path.**
  *Implication*: every new key is a model change, an older parrot rejects a config that carries one, and
  the shared reader has to stay importable with stdlib + pydantic only.
  *Evidence*: F004, F003

- **ai-parrot uses the pyproject tables and tracks `.parrot/test_runners.toml`.**
  *Implication*: both stay as fallbacks. ai-parrot must keep working with no migration.
  *Evidence*: F002, F003, F006

- **`.parrot/` is git-ignored in target repositories and becomes the worktree root under FEAT-802.**
  *Implication*: committed configuration cannot live there; runner settings need a committed home.
  *Evidence*: F006, F016

- **A sandboxed session cannot reach a package registry or write a user-level package store.**
  *Implication*: dependency setup runs on the host at worktree creation, before the session starts.
  *Evidence*: F002, F011

- **Formatting and auto-fixable lint are engine-owned by design.**
  *Implication*: a toolchain profile has to plug into the engine lint pass, not only into prompt text.
  *Evidence*: F010

- **FEAT-802 and FEAT-804 are approved and edit the installer, the worktree root and the install-root
  resolver.**
  *Implication*: this work sequences after them and rebases on their result.
  *Evidence*: F016

- **Every shipped prompt has host twins** (`claude/`, `agent/`, `agents/`, `codex/`).
  *Implication*: each prompt change lands in all copies and passes the existing asset-sync checks.
  *Evidence*: F012, F014

### 2.3 Recent History (Relevant)

| Commit | When | Message | Relevance |
|--------|------|---------|-----------|
| `c7bf629e48` | 2026-11-04 | sdd: add spec for FEAT-804 — installer-portability-gaps | defers non-Python worktree provisioning to a follow-up spec |
| `62a24634d9` | 2026-11-04 | sdd: reserve 1 feature id(s) for worktree-root-under-parrot | FEAT-802, same deferral in its non-goals |
| `a65d4a32eb` | 2026-11-03 | Merge pull request #1936 from phenobarbital/feat-FEAT-633-parrot-installer | the packaged installer this proposal builds on (54/54 tasks) |

FEAT-709 (`language-agnostic-validation-runners`, 23/23 tasks, closed 2026-10-20) introduced the runner
registry and the vitest and cargo adapters. FEAT-583 (`portable-sdd-flow`) is superseded by FEAT-633.
No proposal, spec or remote branch covers this topic (F016).

---

## 3. Probable Scope

Four phases. Each is shippable on its own; the spec should cut them into separate features.

### Phase 1 — Configuration out of `pyproject.toml`, runners reachable

#### What's New

- **Repository settings in `sdd/config.json`** — `SddConfig` gains three optional blocks: `sandbox`
  (mode, allowed domains, `gh_token`), `worktree` (the existing native-group manifest, plus the setup
  command of phase 2) and runner settings. One resolver gives every consumer the same precedence:
  CLI flag or environment variable → `sdd/config.json` → `pyproject.toml` `[tool.parrot.*]` → default.
- **A foreign-repository end-to-end fixture** — a minimal Node + vitest repository exercised from
  install through `select_tests`, the guard and worktree creation. Today's foreign-repo tests stop at
  install, uninstall and "fails without a traceback" (F017).

#### What Changes

- **`…/parrot/sdd/config.py`::`SddConfig`** — new optional blocks; defaults unchanged. *Evidence*: F004
- **`…/parrot/sdd/scripts/native_claude_sandbox.py`::`resolve_sandbox_mode`** — the new precedence;
  `off` / `legacy` stay flag-or-environment only. *Evidence*: F001
- **`…/parrot/sdd/scripts/native_claude_sandbox.py`::`load_launch_config`** — the new precedence, primary
  checkout only. *Evidence*: F002
- **`…/parrot/flows/dev_loop/native_artifacts.py`::`load_manifest`** — the new precedence; `NativeGroup`
  unchanged. *Evidence*: F003
- **`…/parrot/knowledge/wiki/claude_code/welcome.py`::`_set_pyproject_sandbox`** — write `sdd/config.json`
  when the repository has no `[tool.parrot.sdd]` table to edit. *Evidence*: F005
- **`…/parrot/flows/dev_loop/test_scope/runners/vitest.py`::`ADAPTER`** — default `cwd`, no ai-parrot
  default label, wider source suffixes. *Evidence*: F007
- **`…/parrot/flows/dev_loop/test_scope/guard.py`::`VERDICT_ARGV`** — rewrite to the packaged entry
  point instead of a monorepo path and a bare `python`. *Evidence*: F008
- **`…/parrot/sdd/scripts/select_tests.py`::`main`** — honour `invocation.cwd` in `--run`; append
  `--timeout` only for pytest. *Evidence*: F009
- **`…/parrot/sdd/installer.py`::`GITIGNORE_BLOCK`** — only if runner settings stay in `.parrot/`
  (see §5, Unresolved 1). *Evidence*: F006

### Phase 2 — Toolchain profiles and worktree setup

#### What's New

- **Toolchain profile detection** — one module that maps marker files to a profile: the format, lint,
  type-check and test commands and the file suffixes they apply to. Initial profiles: Python
  (`pyproject.toml`: today's ruff / black / mypy behaviour, unchanged), Node (`package.json`: package
  manager from `packageManager` or the lockfile; commands from its `scripts`, e.g. `format`, `lint`,
  `check`, `test`) and Rust (`Cargo.toml`). A single CLI verb prints the detected profile as JSON, so a
  prompt asks for it instead of naming a tool. *Evidence*: F010, F014, F015, F017
- **Worktree setup command** — a `worktree` setting holding the command `ensure_worktree` runs on the
  host after creating a worktree (e.g. `pnpm install --frozen-lockfile`), with a timeout, a
  `--no-setup` opt-out and its outcome in the JSON report. *Evidence*: F003, F011

#### What Changes

- **`…/parrot/flows/dev_loop/sdd_coder/lint.py`::`detect_formatter`, `_existing_python_files`** — the
  engine pass fixes and formats the changed files of the profile's suffixes with the profile's commands.
  *Evidence*: F010
- **`…/parrot/sdd/scripts/ensure_worktree.py`::`main`** — run the setup command after the native sync.
  *Evidence*: F003, F011
- **`…/parrot/flows/dev_loop/test_scope/runners/vitest.py`::`ADAPTER`** — package manager from the
  profile instead of a fixed `pnpm`. *Evidence*: F007
- **`…/parrot/sdd/audit.py`::`EXTERNAL_TOOLS`** — tool list per detected profile. *Evidence*: F017
- **`…/parrot/sdd/_assets/claude/agents/sdd-qa.md`**, **`qa-runner.md`**, **`commands/sdd-done.md`**,
  **`hooks/sdd-worker-format.sh`** — take lint / format / type-check from the profile; report
  "not configured" and do not gate when the profile has none. *Evidence*: F012, F014

### Phase 3 — Language-neutral prompts, templates and contract probe

#### What Changes

- **`…/parrot/sdd/_assets/claude/agents/sdd-contract-probe.md`** — language-aware probe commands, so a
  TypeScript symbol is found and an "absent" claim is checked in the right files. *Evidence*: F013
- **`…/parrot/sdd/_assets/sdd/sdd_templates/task.md`**, **`brief.md`** and the spec template — neutral
  Codebase Contract, Validation Commands and Test Specification sections; no `from parrot…`, no pytest
  skeleton as the only example. *Evidence*: F014
- **`…/parrot/sdd/_assets/sdd/sdd_templates/design_research.prompt.md`** — project identity from the
  repository's `sdd/CONVENTIONS.md`, not a hard-coded ai-parrot description. *Evidence*: F014
- **Worker and coder prompts** — the `.venv` / `uv` shared-environment policy and the ai-parrot
  specifics (`parrot.utils.types`, Cython `.so`, maturin) become profile-conditional or move to
  ai-parrot's own `sdd/CONVENTIONS.md`. *Evidence*: F014 (audit-lane inventory, medium confidence)

### Phase 4 — Migrate `navigator-frontend-next` (acceptance)

- Run `parrot sdd install` there, fill `sdd/config.json`, retire `scripts/sdd/*.mjs` and the forked
  commands, and take one feature through spec → tasks → worktree → `/sdd-done` with a vitest contract.
  Its ID ledger and per-spec indexes are already schema-compatible. *Evidence*: F015

### What's Untouched (Non-Goals)

- The parrot tooling stays Python. A target repository still needs `python3`, `jq` and the `parrot` CLI
  on the host (F017); nothing is re-implemented in JavaScript.
- Baseline classification and the green cache stay pytest-scoped (F010). The shipped prompts already
  report them as `n/a` for other runners.
- The scopes of FEAT-802 (worktree root) and FEAT-804 (portable rule, install root).
- New test-runner kinds beyond pytest, vitest, cargo and parrot-e2e.
- Profiles for languages other than Python, Node (JS / TS / Svelte) and Rust.

### Patterns to Follow

- Guarded, self-skipping steps that print one line ("lint: ruff not configured"). *Evidence*: F014
- A loader that falls back to defaults and raises a typed error for a malformed file. *Evidence*: F004
- Primary-checkout-only reads for anything a sandboxed session could tamper with. *Evidence*: F002
- Per-launch CLI flags override file configuration. *Evidence*: F002

### Integration Risks

- **Config version skew**: a `sdd/config.json` written by a newer parrot is rejected by an older one
  (`extra="forbid"`). Mitigation: ship the model change before any writer, and say so in the error.
  *Evidence*: F004
- **Host-side command execution**: the setup command is arbitrary code run outside the sandbox.
  Mitigation: read it from the primary checkout only, print it before running, honour `--no-setup`.
  *Evidence*: F002, F011
- **Ambiguous detection in mixed repositories**: ai-parrot itself is Python plus a Svelte UI under
  `packages/ai-parrot-server/ui`. Mitigation: decide path scoping and override in the spec (§5).
  *Evidence*: F010, F015
- **Reference repository has a live worktree under `.claude/worktrees`**, which FEAT-802 makes the
  installer refuse. Mitigation: finish or move that worktree before phase 4. *Evidence*: F015, F016
- **Second-hand inventory**: phase 3's file list beyond the re-read lines comes from an audit lane.
  Mitigation: the spec re-verifies each location before it enters a Codebase Contract. *Evidence*: F014

---

## 4. Confidence Map

| ID | Claim | Evidence | Confidence | Reasoning |
|----|-------|----------|------------|-----------|
| C1 | The sandbox mode can be persisted only in `pyproject.toml` `[tool.parrot.sdd]` | F001 | high | function read; docs agree |
| C2 | `sandbox_allowed_domains` and `gh_token` can be persisted only in the primary checkout's `pyproject.toml`; without it the result is `([], False)` | F002 | high | function read |
| C3 | `[tool.parrot.worktree]` is read only from `pyproject.toml`; an absent file yields an empty manifest | F003 | high | function read |
| C4 | Exactly three modules reference `tool.parrot.*`: two readers and the welcome-wizard writer | F005 | high | grep over `packages/*/src` |
| C5 | `sdd/config.json` is the committed, language-neutral home, and no Python code executes `test_command` | F004 | high | model read; full-tree grep of consumers |
| C6 | Runner settings are read from a file the installer git-ignores and never seeds | F006 | high | `CONFIG_PATH` and `GITIGNORE_BLOCK` read; zero mentions in manifest and installer |
| C7 | The vitest adapter needs a TOML `cwd`, runs `pnpm exec`, and defaults the label to `admin-ui` | F007 | high | lines read |
| C8 | A vitest runner without the TOML fails with `error: 'cwd'`, exit 2 | F007 | medium | follows from the unguarded index; the failure path was reported, not executed |
| C9 | The broad-test guard rewrites to a path that exists only in ai-parrot | F008 | high | constant read; path at the monorepo root, absent from the manifest |
| C10 | `select_tests --run` ignores `invocation.cwd` and appends `--timeout` to every runner | F009 | high | both code paths read |
| C11 | The engine lint pass and the green cache act only on `.py` files | F010 | high | filters read |
| C12 | No SDD or dev-loop code installs dependencies into a worktree | F011 | high | grep over both trees; call site read |
| C13 | `sdd-qa` fails every run in a repository without ruff and mypy | F012 | high | prompt read; the gate is an AND of both exit codes |
| C14 | `sdd-contract-probe` reports every TypeScript symbol as missing or absent | F013 | high | the four fixed commands read |
| C15 | Lint, format and type-check have no indirection in the shipped prompts, and the remaining Python-shaped text is as inventoried | F014 | medium | six locations re-read; the rest comes from the audit lane |
| C16 | `navigator-frontend-next` runs a hand-ported fork with schema-compatible state files, and the installer plans a clean overwrite | F015 | high | files compared; dry-run executed |
| C17 | No other spec, proposal or branch covers this; FEAT-802 and FEAT-804 defer it explicitly | F016 | high | non-goals read on `origin/dev`; documents and branches listed |
| C18 | The installer already succeeds on a non-Python repository and detects no toolchain | F017 | high | dry-run against the reference repository; code and fixture read |
| C19 | wikitoolkit's JS / TS / Svelte scanner can back a language-aware contract probe | F013 | low | the scanner exists; substituting it for the grep commands was not tested |

Distribution: **16** high, **2** medium, **1** low.

The low claim (C19) is not load-bearing: the other probe option (an extension-keyed command table) does
not depend on it.

---

## 5. Open Questions

### Resolved (during proposal phase)

- [x] **Where must the configuration that today lives only in `pyproject.toml` live for a repository
  without one?** — *Resolved*: "sdd/config.json (Recomendado)" — extend `SddConfig`; `pyproject.toml`
  stays as a fallback.
  *Resolves claims*: C1, C2, C3
- [x] **What scope should the proposal cover?** — *Resolved*: "Todo, por fases (Recomendado)" — config and
  runners; lint / format and worktree dependencies; neutral prompts, templates and contract probe;
  migrate `navigator-frontend-next` as the acceptance test.
  *Resolves claims*: C15, C16
- [x] **How does a non-Python repository declare lint, format and type-check?** — *Resolved*: "Perfiles
  autodetectados" — detect `package.json`, `Cargo.toml`, … and pick the tools.
  *Resolves claims*: C11, C15
- [x] **How does a new worktree get its dependencies?** — *Resolved*: "Comando de setup declarado
  (Recomendado)" — a declared command `ensure_worktree` runs on the host at worktree creation.
  *Resolves claims*: C12

### Unresolved (defer to spec / implementation)

- [ ] **Where do runner settings live?** — *Owner*: tbd
  *Blocks claims*: C6
  *Plausible answers*: a) a `runners` block in `sdd/config.json`, read from the primary checkout, which
  also answers ledger issue `issue:29e8e7ad138f` · b) keep `.parrot/test_runners.toml` and un-ignore it
  in the installer's `.gitignore` block (conflicts with FEAT-802 keeping `.parrot/` fully ignored)
- [ ] **How does the contract probe become language-aware?** — *Owner*: tbd
  *Blocks claims*: C14, C19
  *Plausible answers*: a) a command table keyed by file extension inside the probe prompt ·
  b) delegate `symbol` / `outline` to `wikitoolkit symbols`, which already scans JS / TS / Svelte
- [ ] **Can a detected profile be overridden or scoped by path?** — *Owner*: tbd
  *Blocks claims*: C11
  *Plausible answers*: a) detection only, one profile per marker file found, scoped to that file's
  directory · b) detection plus an optional override block in `sdd/config.json`
- [ ] **When does the setup command re-run, and does its failure block?** — *Owner*: tbd
  *Blocks claims*: C12
  *Plausible answers*: a) on create only, failure is a warning · b) on create and whenever the lockfile
  differs from the last run, failure blocks the launch

---

## 6. Recommended Next Step

**`/sdd-spec FEAT-805`** — *Rationale*: localization is high-confidence for phases 1 and 2 (C1–C12) and
the four scope decisions are taken. The remaining choices are bounded and fit the spec's own Q&A. The
spec should cover phases 1 and 2 and leave phases 3 and 4 to follow-up specs, after FEAT-802 and
FEAT-804 land.

### Alternatives

- **`/sdd-brainstorm FEAT-805`** — if the toolchain-profile design deserves a comparison of approaches
  (detection only, detection plus override, per-path profiles) before it is fixed in a spec.
- **Manual review** — of the phase 3 inventory, which is the least verified part of this document.

---

## 7. Research Audit

| Artifact | Path |
|----------|------|
| State checkpoints | `sdd/state/FEAT-805/state.json` |
| Source (raw) | `sdd/state/FEAT-805/source.md` |
| Research plan | `sdd/state/FEAT-805/research_plan.json` |
| Findings (digests) | `sdd/state/FEAT-805/findings/F001-*.md` … `F017-*.md` |
| Synthesis (JSON) | `sdd/state/FEAT-805/synthesis.json` |

**Budget consumed** (estimates — the research ran in the session before `/sdd-proposal` was invoked and
was not metered against a profile):
- Files read: ~95
- Grep calls: ~70
- Git calls: ~9
- Truncated: **no**

The research plan was recorded after the fact from the queries actually executed; there was no plan
gate. Two read-only audit lanes (shipped prompt assets; scripts and installer) produced the inventory,
and every claim rated high in §4 was re-read directly afterwards.

**Mode determination**: `auto` → resolved to `enrichment` (the request asks to extend an existing flow
to new repositories; nothing is reported broken in ai-parrot itself).

---

## 8. Provenance

| Field | Value |
|-------|-------|
| Generated by | `/sdd-proposal v1.0` |
| Synthesis prompt | `sdd/templates/synthesis.prompt.md v1.0` (schema followed; output written directly) |
| Plan prompt | not run — plan recorded after the fact |
| Schema versions | state=1.0, synthesis=1.0, research_plan=1.0 |
| Operator | Jesus Lara (with Claude) |
