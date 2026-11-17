<!--
  sdd/templates/design_research.prompt.md — neutral design-research brief (FEAT-545).
  Rendered by /sdd-spec section 3b and piped to `codex exec ... --output-schema
  design_research.schema.json`.
  FORBIDDEN INPUTS: never paste the spec draft, the spec author's reasoning, a preferred
  conclusion, or any text written by the model that will author the spec. The brief carries
  ONLY the accepted exploration document (brainstorm/proposal) and verified code anchors.
  Placeholders (double-curly-brace tokens, deliberately NOT written with literal braces in
  this comment — a renderer that does a naive whole-document string replace must not also
  rewrite this sentence): problem_statement, constraints_and_goals,
  recommended_option_or_scope, code_context_paths, open_questions, question.
-->
# Independent design review — read-only

You are an independent design reviewer for **ai-parrot**, an async-first Python
framework for AI agents (aiohttp, Pydantic v2).
You have read-only access to the repository in your working directory.

## Rules
1. Read the code you cite. Every `affected_paths` entry must be a repo-relative
   path you actually opened; suggestions with unverifiable paths are discarded.
2. Judge the design intent below against what exists in the repository: what is
   missing, what is risky, what would be simpler, what the codebase already
   provides that the intent re-invents.
3. Do not restate the intent, do not praise it, do not write code. Propose at
   most 12 concrete, falsifiable suggestions, each tagged with a kind
   (`architecture` | `api` | `testing` | `risk` | `alternative`), a risk level and
   your confidence.
4. Output exactly ONE JSON object conforming to the schema you were given — no
   markdown fences, no prose before or after.

## Accepted design intent (verbatim from the exploration document)

### Problem statement
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

### Constraints and goals
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

### Recommended option / probable scope
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

Decisions already taken by the project owner:

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

### Resolved (during `/sdd-spec`, 2026-11-05)

- [x] **Where do runner settings live?** — *Resolved*: "Bloque runners en sdd/config.json
  (Recomendado)" — committed with the rest of the configuration; the TOML stays as a fallback and for the
  Python extensions, so ai-parrot does not change.
  *Resolves claims*: C6
- [x] **Can a detected profile be overridden or scoped by path?** — *Resolved*: "Detección + override
  opcional (Recomendado)" — detection at the repository root and at each configured runner `cwd`; an
  optional `toolchain` block in `sdd/config.json` adds roots or replaces a command.
  *Resolves claims*: C11
- [x] **When does the setup command re-run, and does its failure block?** — *Resolved*: "Al crear y si
  cambia el lockfile; el fallo bloquea (Recomendado)" — it re-runs on reuse only when the declared input
  files changed; a failure ends `ensure` with an error and the command's output; `--no-setup` skips it.
  *Resolves claims*: C12
- [x] **Is the proposal accepted?** — *Resolved*: "Aceptar y ejecutar codex (Recomendado)" — status set
  to `accepted`; the independent design review runs over this document.

### Verified code anchors (paths only — open them yourself)
packages/ai-parrot/src/parrot/sdd/config.py
packages/ai-parrot/src/parrot/sdd/scripts/native_claude_sandbox.py
packages/ai-parrot/src/parrot/sdd/launch_cli.py
packages/ai-parrot/src/parrot/flows/dev_loop/native_artifacts.py
packages/ai-parrot/src/parrot/knowledge/wiki/claude_code/welcome.py
packages/ai-parrot/src/parrot/sdd/scripts/ensure_worktree.py
packages/ai-parrot/src/parrot/sdd/installer.py
packages/ai-parrot/src/parrot/flows/dev_loop/test_scope/runners/registry.py
packages/ai-parrot/src/parrot/flows/dev_loop/test_scope/runners/vitest.py
packages/ai-parrot/src/parrot/flows/dev_loop/test_scope/planner.py
packages/ai-parrot/src/parrot/flows/dev_loop/test_scope/guard.py
packages/ai-parrot/src/parrot/sdd/scripts/select_tests.py
packages/ai-parrot/src/parrot/flows/dev_loop/sdd_coder/lint.py
packages/ai-parrot/src/parrot/sdd/audit.py
packages/ai-parrot/src/parrot/sdd/_assets/claude/agents/sdd-qa.md
packages/ai-parrot/src/parrot/sdd/_assets/claude/agents/sdd-contract-probe.md
packages/ai-parrot/src/parrot/sdd/_assets/claude/commands/sdd-done.md
packages/ai-parrot/src/parrot/sdd/_assets/claude/agents/qa-runner.md
packages/ai-parrot/src/parrot/sdd/_assets/claude/hooks/sdd-worker-format.sh
packages/ai-parrot/src/parrot/sdd/_assets/sdd/sdd_templates/task.md
packages/ai-parrot/src/parrot/sdd/_assets/sdd/sdd_templates/brief.md
packages/ai-parrot/src/parrot/sdd/_assets/sdd/sdd_templates/design_research.prompt.md

### Questions still open in the exploration document
### Unresolved (defer to spec / implementation)

- [ ] **How does the contract probe become language-aware?** — *Owner*: tbd (phase 3, not in the first
  spec)
  *Blocks claims*: C14, C19
  *Plausible answers*: a) a command table keyed by file extension inside the probe prompt ·
  b) delegate `symbol` / `outline` to `wikitoolkit symbols`, which already scans JS / TS / Svelte

---

## Question
Given this accepted design intent and these verified code anchors, how would you build it? What is missing, risky, or better done another way?
