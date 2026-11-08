---
type: feature
base_branch: dev
projects: [sdd-tooling, dev-loop, ai-parrot]
tags: [sdd, non-python, sdd-config, toolchain-profiles, worktree, test-runners, installer]
---

# Feature Specification: SDD flow in non-Python repositories — configuration, runners, toolchain profiles, worktree setup

**Feature ID**: FEAT-805
**Date**: 2026-11-05
**Author**: Jesus Lara (with Claude)
**Status**: draft
**Target version**: 2.1.0

Source: `sdd/proposals/sdd-non-python-repos.proposal.md` (accepted), phases 1 and 2. Phases 3
(language-neutral prompts, templates and contract probe) and 4 (migrating `navigator-frontend-next`)
are follow-up specs.

---

## 1. Motivation & Business Requirements

### Problem Statement

The packaged SDD flow (`parrot sdd install`, FEAT-633) installs into a repository that has no Python
project, but what it needs afterwards assumes one:

1. **Configuration lives only in `pyproject.toml`.** The sdd-worker sandbox mode
   (`resolve_sandbox_mode`), its network policy (`load_launch_config`: `sandbox_allowed_domains`,
   `gh_token`) and the worktree artifact manifest (`load_manifest`) are read only from
   `[tool.parrot.sdd]` / `[tool.parrot.worktree]`. A repository without `pyproject.toml` can only pass
   flags or environment variables on every launch, and the Claude welcome wizard creates a stray
   `pyproject.toml` there to store its choice.
2. **Test runners are unreachable outside ai-parrot.** Runner settings are read from
   `.parrot/test_runners.toml`, which the installer git-ignores and never seeds. The vitest adapter
   indexes `settings["cwd"]` with no default, always runs `pnpm exec`, and labels its distribution
   `admin-ui`. The broad-test guard rewrites a command to `python scripts/sdd/select_tests.py`, a path
   that exists only in the ai-parrot monorepo. `select_tests --run` ignores a runner's `cwd` and appends
   pytest's `--timeout` flag to every runner.
3. **Lint, format and type-check are fixed to ruff, black and mypy.** The engine lint pass only touches
   `.py` files; `sdd-qa` runs `ruff check .` and `mypy` unconditionally, so QA fails in every repository
   without them; the guarded steps skip themselves, so a TypeScript repository gets no lint or format
   pass at all.
4. **Nothing prepares a worktree's dependencies.** `ensure_worktree` only copies declared native
   artifacts. A fresh worktree of a Node repository has no `node_modules`.

The reference repository, `navigator-frontend-next` (SvelteKit + TypeScript, pnpm, vitest), avoids all
of this with a hand-ported fork of the flow that is not updated with the packaged one. FEAT-802 and
FEAT-804 both list this work as a deferred follow-up.

### Goals

- **G1 — One committed configuration home.** `sdd/config.json` (`SddConfig`) carries the sandbox
  policy, the worktree manifest and setup command, the runner settings and the toolchain overrides.
  `pyproject.toml` `[tool.parrot.*]` and `.parrot/test_runners.toml` stay as fallbacks, so ai-parrot
  needs no migration.
- **G2 — The built-in vitest runner works in a foreign repository** with no runner settings at all
  (`package.json` at the root, any of pnpm / npm / yarn).
- **G3 — The guard and `select_tests` are repository-agnostic**: no monorepo path, no bare `python`,
  no pytest flag on other runners, the runner's `cwd` honoured in every mode.
- **G4 — Toolchain profiles.** Format, lint, type-check and test commands are detected from marker
  files (`pyproject.toml`, `package.json`, `Cargo.toml`), can be overridden in `sdd/config.json`, and are
  reachable from scripts (a library) and from prompts (one CLI noun).
- **G5 — The engine lint pass and the QA / closeout prompts use the profile**, so a TypeScript task
  gets the same mechanical fix-and-format treatment a Python task gets, and a repository with no lint
  tooling is never failed for lacking ruff.
- **G6 — A declared worktree setup command** runs on worktree creation and whenever its declared
  inputs change; a failure stops the launch with the command's output.
- **G7 — Python behaviour is unchanged.** A repository that configures nothing new behaves exactly as
  today, ai-parrot included.

### Non-Goals (explicitly out of scope)

- Language-neutral prompts, templates and `sdd-contract-probe` beyond the four files in Module 10
  (proposal phase 3) and the migration of `navigator-frontend-next` (phase 4). Follow-up specs.
- Re-implementing any parrot tooling outside Python. A target repository still needs `python3`, `jq`
  and the `parrot` CLI on the host.
- Baseline classification and the green cache for non-pytest runners; they stay pytest-scoped and the
  shipped prompts already report them as `n/a`.
- New runner kinds (the registry keeps pytest, vitest, cargo, parrot-e2e) and toolchain profiles for
  languages other than Python, Node (JS / TS / Svelte) and Rust.
- Reading runner settings from the primary checkout instead of the attempt worktree
  (`issue:29e8e7ad138f`). This spec moves the settings to a committed file; where that file is read from
  stays as today and is fixed in that issue's own lane.
- The scopes of FEAT-802 (worktree root under `.parrot/`) and FEAT-804 (portable rule, install root).
- `audit.EXTERNAL_TOOLS`: it scans the *shipped assets* for host-tool assumptions, not the target
  repository, so it is unaffected (the proposal listed it by mistake).

---

## Governing Decisions

<!-- decision-audit: input_digest=sha256:72734d825470b643b09fe45291f1b5d503a7edcd75182e1430705d2727aa338b evaluation_digest=sha256:f92e21013647e9fc1c8a1e4470c91ceb7e4acdd8553a51a7dfb0b4e9cd383d9e rules_version=1 status=pass -->

## 2. Architectural Design

### Overview

**Configuration.** `SddConfig` gains four optional blocks: `sandbox`, `worktree`, `runners`,
`toolchain`. Precedence is the same everywhere: a CLI flag or environment variable, then
`sdd/config.json`, then the legacy file, then the default. The unit that wins is the whole block
(`sandbox`, `worktree`) or the whole runner kind (`runners.<kind>`); keys are never merged across
files, so one file always fully describes a block.

Three readers cannot import `parrot`, by existing design: the test-scope kernel is stdlib-only and
vendored into other repositories, `native_artifacts.py` is loaded by file path so it never depends on
the compiled artifacts it exists to provide, and `native_claude_sandbox.py` also runs as a plain script.
Each therefore reads its own block from `sdd/config.json` with `json`, exactly as it reads its TOML
table today. `SddConfig` is the schema authority: it types every block, `load_sdd_config` rejects a
malformed file at install, doctor and worktree creation, and one parity test feeds the same fixture
through every reader.

Trust rules do not change, and each reader's checkout is explicit:

| Setting | Read from | Why |
|---|---|---|
| `sandbox.allowed_domains`, `sandbox.gh_token` | primary checkout only | the sandboxed session can write its own worktree copy (today's rule) |
| `worktree.setup`, `worktree.native_groups` | main checkout only | the setup command runs on the host |
| `sandbox.mode` | the `repo_root` its caller passes (the worktree root today) | unchanged; `off` / `legacy` are refused from any file (§8 asks whether to move it) |
| `runners`, `toolchain` | the worktree being tested | a branch may legitimately change them; same as the TOML today |

A tampered worktree copy of `sdd/config.json` therefore cannot change the launch policy or the host
command; a test asserts both.

**Runners.** `load_registry` overlays `sdd/config.json` `runners` on the TOML tables per runner kind;
`[extensions]` stays TOML-only. The vitest adapter defaults `cwd` to `"."`, derives its distribution
label from `cwd`, picks the package manager from the `package_manager` setting, then the `packageManager`
field of `package.json`, then the lockfile, rejects a manager it cannot drive, and recognises `.tsx` /
`.jsx` / `.js` / `.mjs` sources. ai-parrot pins `distribution = "admin-ui"` in its own TOML so its report
paths do not move.

**Guard and selection.** `VERDICT_ARGV` points at the packaged `select_tests.py` by absolute path and
runs it with `sys.executable`; a vendored kernel that has no packaged script keeps the legacy value.
In `select_tests`, one helper computes the argv and working directory of an invocation for both the
verdict and the plain `--run` mode, so they cannot drift again: the directory is
`worktree / invocation.cwd` and `--timeout` is appended only for the pytest runner.

**Toolchain profiles.** `parrot/sdd/toolchain.py` detects one profile per marker file at the repository
root, at every configured runner `cwd`, and at every root named in the `toolchain` block. A profile
carries the argv for four steps:

| Step | Scope | Python (when configured) | Node | Rust |
|---|---|---|---|---|
| `fix` | changed files | `ruff check --fix` | `eslint --fix` (or `biome check --write`) | — |
| `format` | changed files | `black` / `ruff format` | `prettier --write` (or `biome format --write`) | `cargo fmt --` |
| `lint` | profile root | `ruff check` (takes files) | the `lint` script | `cargo clippy` |
| `typecheck` | profile root | `mypy` (takes files) | the `check` / `typecheck` script, else `tsc --noEmit` | `cargo check` |

A step a repository does not configure is `None`: it is reported as "not configured" and never fails
anything. An override entry replaces a detected step (`[]` disables it) or adds a profile. Every changed
file maps to at most one profile: the one with the longest root that contains it and whose suffixes
match.

Profiles never run tests. A profile's `test` argv is informational (the installer prints it); test
execution, reports, tiers and timeouts stay with the runner registry and its adapters, so there is one
execution model for tests.

`parrot sdd toolchain show` prints the profiles; `parrot sdd toolchain run <step>` executes a step for
every profile (or for the profiles owning `--files`) and returns one exit code. Prompts call these two
verbs instead of naming tools.

**Engine lint pass.** `run_lint_pass` keeps its legacy Python path for files whose owning Python
profile overrides neither `fix` nor `format`. Files owned by a Python profile that overrides `fix` or
`format` use the profile pass instead, as do non-Python files. Only those two steps route: they are the
only steps the engine pass runs, so a `lint`, `typecheck` or `test` override never moves a file off the
legacy path, which keeps its line-scoped formatting and its ruff error report. An empty argv (`[]`) is
an explicit disable and counts as an override; omitted or null steps retain detection. Each file goes
through exactly one pass. The profile pass runs `fix` then
`format` over the task's changed files of that profile, commits
the result on the attempt branch, and reports tool errors. Each command is bounded by `LINT_TIMEOUT_S`.
Formatting is whole-file in the profile pass; the unchanged legacy Python pass retains line-scoped
formatting. The profile pass reports no residual findings: a Node `lint` script lints the whole project, so residuals are left to the
single full pass in `/sdd-done`. The banned-import gate (`check_banned_imports`) stays Python-only; it
already returns no findings when a task changes no `.py` file, so it never blocks a foreign task.

**Worktree setup.** The `worktree` block declares `setup: {command, cwd, inputs, timeout_s}`.
`run_worktree_setup` runs the command in the worktree unless a fingerprint of (command, cwd, contents of
`inputs`) matches the stamp stored in that worktree's git directory. `ensure_worktree` calls it after the
native sync; so does the sdd-coder pool for each task sub-worktree. A failing command makes `ensure`
exit non-zero without printing the worktree path, and makes the pool raise for that worker.
`--no-setup` and `PARROT_WORKTREE_SETUP=0` skip it.

### Component Diagram

```
sdd/config.json ──► SddConfig (schema authority: install · doctor · ensure_worktree)
   │  sandbox   ──► native_claude_sandbox.resolve_sandbox_mode / load_launch_config ◄── [tool.parrot.sdd]
   │                      ▲ welcome.current_sandbox_mode / write_sandbox_mode
   │  worktree  ──► native_artifacts.load_manifest ◄── [tool.parrot.worktree]
   │                      ├─► sync_native_artifacts        (unchanged)
   │                      └─► run_worktree_setup ──► ensure_worktree · SubWorktreeManager.create
   │  runners   ──► test_scope.runners.registry.load_registry ◄── .parrot/test_runners.toml
   │                      └─► VitestAdapter (cwd default, package manager, distribution)
   └─ toolchain ──► parrot.sdd.toolchain.detect_profiles ◄── pyproject.toml · package.json · Cargo.toml
                          ├─► parrot sdd toolchain show | run   ◄── sdd-qa · qa-runner · sdd-done · format hook
                          ├─► sdd_coder.lint.run_lint_pass (profile pass)
                          └─► installer / doctor (informational lines)

test_scope.guard.VERDICT_ARGV ──► <packaged>/sdd/scripts/select_tests.py --run (cwd, timeout fixed)
```

### Integration Points

| Existing Component | Integration Type | Notes |
|---|---|---|
| `SddConfig` | extends | four optional blocks; defaults unchanged |
| `resolve_sandbox_mode`, `load_launch_config` | modifies | same signatures; new first source |
| `load_manifest`, `NativeManifest` | modifies / extends | new first source; `setup` field |
| `ensure_worktree.main`, `SubWorktreeManager.create` | modifies | call the setup step |
| `load_registry` | modifies | overlays `sdd/config.json` `runners` |
| `VitestAdapter` | modifies | defaults; package manager; suffixes |
| `guard.VERDICT_ARGV`, `select_tests.main` | modifies | packaged path; cwd; timeout |
| `run_lint_pass` | extends | profile pass after the Python pass |
| `sdd/cli.py` `VERBS` | extends | new `toolchain` noun |
| `current_sandbox_mode`, `write_sandbox_mode` | modifies | read and write `sdd/config.json` |
| `install_sdd_integration`, `_check_sdd` | extends | informational toolchain lines |

### Data Models

```python
# parrot/sdd/config.py — new blocks of SddConfig (all extra="forbid")
class SandboxSettings(BaseModel):
    mode: Literal["required", "preferred"] | None = None
    allowed_domains: list[str] = Field(default_factory=list)
    gh_token: bool = False

class WorktreeSetup(BaseModel):
    command: list[str]                                   # argv, no shell
    cwd: str = "."                                       # worktree-relative
    inputs: list[str] = Field(default_factory=list)      # worktree-relative files deciding a re-run
    timeout_s: int = 900

class NativeGroupSettings(BaseModel):
    # Mirror native_artifacts.NativeGroup without importing the path-loaded module.
    model_config = ConfigDict(extra="forbid")
    name: str
    copy_globs: list[str] = Field(default_factory=list)
    pair_sources: list[str] = Field(default_factory=list)
    required: bool = True
    abi_scoped: bool = False
    autobuild: bool = False
    build: list[str] = Field(default_factory=list)
    build_cwd: str = "."
    build_timeout_s: int = 900
    manual_hint: str | None = None

class WorktreeSettings(BaseModel):
    enabled: bool = True
    native_groups: list[NativeGroupSettings] = Field(default_factory=list)
    setup: WorktreeSetup | None = None

class ToolchainOverride(BaseModel):
    kind: Literal["python", "node", "rust"]
    root: str = "."
    fix: list[str] | None = None        # None keeps the detected step; [] disables it
    format: list[str] | None = None
    lint: list[str] | None = None
    typecheck: list[str] | None = None
    test: list[str] | None = None
    # None: an overridden lint / typecheck argv runs verbatim (no paths appended);
    # a step that is not overridden keeps the detected flag. True / False always wins.
    lint_takes_files: bool | None = None
    typecheck_takes_files: bool | None = None

class ToolchainSettings(BaseModel):
    profiles: list[ToolchainOverride] = Field(default_factory=list)
```

```json
// sdd/config.json of a SvelteKit repository (illustrative)
{
  "base_branch": "dev", "hotfix_base": "main",
  "sandbox": {"mode": "required", "allowed_domains": ["api.github.com"], "gh_token": true},
  "worktree": {"setup": {"command": ["pnpm", "install", "--frozen-lockfile"], "inputs": ["pnpm-lock.yaml"]}},
  "runners": {"vitest": {"timeout_s": 120}}
}
```

### New Public Interfaces

```python
# parrot/sdd/toolchain.py
def detect_profiles(repo_root: Path, *, config: SddConfig | None = None) -> list[ToolchainProfile]: ...
def profile_for_path(profiles: Sequence[ToolchainProfile], path: str) -> ToolchainProfile | None: ...
def step_argv(profile: ToolchainProfile, step: str, files: Sequence[str] = ()) -> list[str] | None: ...

# parrot/flows/dev_loop/native_artifacts.py
def run_worktree_setup(*, main_root: Path, target: Path, manifest: NativeManifest | None = None) -> SetupReport: ...

# CLI
#   parrot sdd toolchain show [--path DIR] [--json]
#   parrot sdd toolchain run {fix|format|lint|typecheck} [--path DIR] [--files F ...]
#   parrot sdd worktree ensure ... [--no-setup]
```

---

## 3. Module Breakdown

#### Delegation-eligible modules

| Module | Eligible? | Decided patterns / exact contracts | Why not (if no) |
|---|---|---|---|
| M1: Config blocks | yes | models, field names, defaults and validators fixed in §2 Data Models and the skeleton | — |
| M2: Sandbox readers and wizard | yes | precedence, normalised keys, writer-target rule fixed below | — |
| M3: Worktree manifest source | yes | block shape and precedence fixed | — |
| M4: Worktree setup command | no | — | fingerprint and stamp handling interact with git plumbing and three call sites; needs judgment on failure paths |
| M5: Runner settings and vitest adapter | yes | overlay rule, defaults, argv per package manager fixed | — |
| M6: Guard and `select_tests` | yes | three one-line behaviours fixed | — |
| M7: Toolchain profiles | no | — | detection rules are fixed, but mapping real `package.json` shapes to steps needs judgment |
| M8: `parrot sdd toolchain` CLI | yes | verbs, flags, exit codes and output lines fixed | — |
| M9: Engine profile pass | no | — | restructures `run_lint_pass`; the Python path without a `fix` / `format` override must preserve existing behavior |
| M10: Prompts | yes | exact replacement text per file fixed in the task; twins listed | — |
| M11: Installer and doctor lines | yes | line formats fixed | — |
| M12: Docs and foreign-repo test | yes | file list and assertions fixed | — |

### Module 1: Configuration blocks in `SddConfig`
- **Path**: `packages/ai-parrot/src/parrot/sdd/config.py`
- **Responsibility**: type and validate the four new blocks; nothing else changes in the loader.
- **Depends on**: —
- **Interface Skeleton**:
  ```python
  # packages/ai-parrot/src/parrot/sdd/config.py  (modifies :19 SddConfig; adds models above it)
  class SandboxSettings(BaseModel):
      """`sandbox` block — sdd-worker sandbox policy; replaces `[tool.parrot.sdd]` when present."""
      # validator: every allowed_domains item is a bare hostname (same rule as jira_host, config.py:60-68)

  class WorktreeSetup(BaseModel):
      """`worktree.setup` — the command that prepares a new worktree's dependencies on the host."""
      # validators: command non-empty and no blank items; cwd and every input are relative paths
      # without `..` parts; timeout_s > 0

  class WorktreeSettings(BaseModel):
      """`worktree` block — typed NativeGroupSettings entries and the setup command."""
      # NativeGroupSettings mirrors every NativeGroup field, default and validation rule.
      # Parity tests cover valid and invalid groups, including missing name, unknown keys and wrong types.
      # Keep this mirror local: neither reader imports the other.

  class ToolchainOverride(BaseModel):
      """One `toolchain.profiles[]` entry: replaces detected steps of the profile at (kind, root), or adds it.
      `lint_takes_files` / `typecheck_takes_files` say whether paths are appended to that step's argv:
      null means false for a step this entry overrides and the detected flag for a step it does not."""

  class ToolchainSettings(BaseModel):
      """`toolchain` block."""

  class SddConfig(BaseModel):  # verified: config.py:19
      sandbox: SandboxSettings | None = None
      worktree: WorktreeSettings | None = None
      #: Per-kind runner settings; a kind declared here replaces that kind's `.parrot/test_runners.toml` table.
      #: Settings stay adapter-owned (extensions define their own keys); the model validates only what is
      #: common: a `cwd` value is a relative path without `..` parts.
      runners: dict[str, dict[str, str | int | float | bool | list[str]]] | None = None
      toolchain: ToolchainSettings | None = None
  ```

### Module 2: Sandbox settings readers and the welcome wizard
- **Path**: `packages/ai-parrot/src/parrot/sdd/scripts/native_claude_sandbox.py`,
  `packages/ai-parrot/src/parrot/knowledge/wiki/claude_code/welcome.py`
- **Responsibility**: read the sandbox mode and launch policy from `sdd/config.json` first; make the
  wizard read and write the same place and stop creating `pyproject.toml` in a repository without one.
- **Depends on**: Module 1 (block shape; parity test)
- **Interface Skeleton**:
  ```python
  # native_claude_sandbox.py  (stdlib only — it also runs as a script, see :27-30)
  SDD_CONFIG_PATH: str = "sdd/config.json"

  def _sandbox_block(root: Path) -> tuple[dict[str, Any] | None, str]:
      """Return the sandbox settings of ``root`` and the file they came from.

      `sdd/config.json` `sandbox` when it is an object; else `[tool.parrot.sdd]` of `pyproject.toml`
      normalised to the same keys (`sandbox`→`mode`, `sandbox_allowed_domains`→`allowed_domains`,
      `gh_token`); else ``(None, "default")``.

      Raises:
          ValueError: the chosen file is unreadable or malformed, or the block is not an object/table;
              the message names the file.
      """

  def resolve_sandbox_mode(repo_root: Path) -> str:  # verified: native_claude_sandbox.py:246 — signature unchanged
      """MODE_ENV, else `_sandbox_block(repo_root)["mode"]`, else "required".
      `off`/`legacy` from any file still raise ValueError (verified: :290-296)."""

  def load_launch_config(primary: Path) -> tuple[list[str], bool]:  # verified: :637 — signature unchanged
      """`allowed_domains` (validated by validate_allowed_domains) and `gh_token` from `_sandbox_block(primary)`."""

  # welcome.py
  def current_sandbox_mode(root: Path) -> str | None:  # verified: welcome.py:137 — signature unchanged
      """"legacy" from settings.local.json as today; else "native" when the sandbox block (either file) says "required"."""

  def write_sandbox_mode(root: Path, choice: str) -> str:  # verified: welcome.py:160 — signature unchanged
      """"native" writes `sandbox.mode = "required"` to `sdd/config.json` when that file already has a
      `sandbox` block or the repository has no `pyproject.toml`; otherwise to `[tool.parrot.sdd]` as today."""

  def _set_config_sandbox(root: Path, value: str) -> None:
      """Set `sandbox.mode` in `sdd/config.json`, keeping every other key and the 2-space indent."""
  ```

### Module 3: Worktree manifest from `sdd/config.json`
- **Path**: `packages/ai-parrot/src/parrot/flows/dev_loop/native_artifacts.py`
- **Responsibility**: `load_manifest` reads the `worktree` block first; `NativeManifest` carries `setup`.
- **Depends on**: Module 1 (block shape; parity test)
- **Interface Skeleton**:
  ```python
  # native_artifacts.py  (stdlib + pydantic only — loaded by file path, never `import parrot`; verified: ensure_worktree.py:27-41)
  SDD_CONFIG_PATH: str = "sdd/config.json"

  class SetupSpec(BaseModel):
      """Mirror of `SddConfig.worktree.setup` (this module cannot import parrot.sdd.config)."""
      model_config = ConfigDict(extra="forbid")
      command: list[str]
      cwd: str = "."
      inputs: list[str] = Field(default_factory=list)
      timeout_s: int = 900

  class NativeManifest(BaseModel):  # verified: native_artifacts.py:66
      setup: SetupSpec | None = None

  def load_manifest(repo_root: Path) -> NativeManifest:  # verified: :103 — signature unchanged
      """`sdd/config.json` `worktree` (`native_groups`→`groups`) when it is an object; else
      `[tool.parrot.worktree]` (`native_group`→`groups`, no setup); else an empty manifest.

      Raises:
          ValueError: the chosen block is malformed; the message names the file.
      """
  ```

### Module 4: Worktree setup command
- **Path**: `packages/ai-parrot/src/parrot/flows/dev_loop/native_artifacts.py`,
  `packages/ai-parrot/src/parrot/sdd/scripts/ensure_worktree.py`,
  `packages/ai-parrot/src/parrot/flows/dev_loop/worktree_manager.py`
- **Responsibility**: run the declared setup command when a worktree is created or its inputs changed;
  block on failure.
- **Depends on**: Module 3
- **Interface Skeleton**:
  ```python
  # native_artifacts.py
  SETUP_ENV_VAR: str = "PARROT_WORKTREE_SETUP"          # "0" disables, like SYNC_ENV_VAR (verified: :42)
  SETUP_STAMP_NAME: str = "parrot-worktree-setup.json"  # inside the worktree's own git dir

  class SetupReport(BaseModel):
      """Outcome of one setup attempt. Never an exception carrier (same rule as NativeSyncReport, :87)."""
      model_config = ConfigDict(extra="forbid")
      ran: bool = False
      ok: bool = True
      skipped_reason: str = ""      # "not configured" | "disabled" | "inputs unchanged"
      command: list[str] = Field(default_factory=list)
      returncode: int | None = None
      output_tail: str = ""         # last 40 lines of combined stdout/stderr

  def setup_fingerprint(target: Path, setup: SetupSpec) -> str:
      """sha256 over the command, cwd and the bytes of every input file (a missing input hashes as absent)."""

  def run_worktree_setup(*, main_root: Path, target: Path, manifest: NativeManifest | None = None) -> SetupReport:
      """Run `setup.command` in ``target / setup.cwd`` unless the stamp holds the current fingerprint.

      The declaration is read from ``main_root`` only. The stamp is written after a zero exit and removed
      before a run, so an interrupted or failed run is retried. A non-zero exit, a timeout or a command
      that cannot start returns ``ok=False``; this function does not raise for them.
      """

  # ensure_worktree.py  (modifies main(), verified: :342; native sync block :442-454)
  #   new flag --no-setup, next to --no-autobuild (verified: :377)
  #   after the native sync and OUTSIDE its try/except (:444-451), so a native-sync warning or exception
  #   can never skip or hide the setup step: report = run_worktree_setup(main_root=repo_root, target=path)
  #   ok=False → write the command and output_tail to stderr, print nothing on stdout, return 1
  #   --json gains "setup": report.model_dump()

  # worktree_manager.py
  class SubWorktreeManager:
      async def create(self, worker_id: str, *, base: Optional[str] = None) -> str:  # verified: :146
          """…after `_sync_native_artifacts(path)` (verified: :175) run the setup step.

          Raises:
              SubWorktreeMergeError: also when the setup command fails (stderr = output_tail).
          """
      async def _run_setup(self, path: str) -> None:
          """Thread wrapper around run_worktree_setup; raises SubWorktreeMergeError on ok=False."""
  ```

### Module 5: Runner settings from `sdd/config.json`; repository-agnostic vitest adapter
- **Path**: `packages/ai-parrot/src/parrot/flows/dev_loop/test_scope/runners/registry.py`,
  `packages/ai-parrot/src/parrot/flows/dev_loop/test_scope/runners/vitest.py`, `.parrot/test_runners.toml`
- **Responsibility**: overlay committed runner settings; make vitest work with no settings.
- **Depends on**: Module 1 (block shape; parity test)
- **Interface Skeleton**:
  ```python
  # registry.py  (stdlib only — verified by tests/flows/dev_loop/test_scope/test_stdlib_only.py)
  SDD_CONFIG_PATH: str = "sdd/config.json"

  def _config_runners(worktree: Path) -> dict[str, Any]:
      """`runners` object of `<worktree>/sdd/config.json`, or {} when the file or key is absent.

      Raises:
          ValueError: the file is not valid JSON or `runners` is not an object of objects.
      """

  def load_registry(worktree: Path) -> RunnerRegistry:  # verified: registry.py:133 — signature unchanged
      """TOML `[runners]` / `[extensions]` as today; then every kind in `_config_runners` REPLACES that
      kind's TOML table. Unknown kinds and invalid tiers fail closed with the file name, as today."""

  # vitest.py
  _TEST_SUFFIXES = (".test.ts", ".spec.ts", ".test.tsx", ".spec.tsx", ".test.js", ".spec.js", ".test.jsx", ".spec.jsx")
  _SOURCE_SUFFIXES = (".svelte.ts", ".svelte", ".tsx", ".ts", ".jsx", ".mjs", ".js")
  _LOCKFILES: tuple[tuple[str, str], ...] = (
      ("pnpm-lock.yaml", "pnpm"), ("yarn.lock", "yarn"), ("package-lock.json", "npm"), ("npm-shrinkwrap.json", "npm"),
  )

  _PACKAGE_MANAGERS: frozenset[str] = frozenset({"pnpm", "npm", "yarn"})

  def _package_manager(cwd: Path, settings: Mapping[str, str]) -> str:
      """`settings["package_manager"]`, else the name before `@` in package.json `packageManager`, else
      the first lockfile in ``cwd``, else "pnpm" (today's behaviour). The result may be a manager outside
      `_PACKAGE_MANAGERS`; `validate_settings` reports it."""

  class VitestAdapter:  # verified: vitest.py:16
      binaries = ("pnpm", "npm", "npx", "yarn", "vitest")
      # mirror_targets / invocation / validate_settings: cwd = settings.get("cwd", ".")
      # distribution_of: settings["distribution"], else "vitest" when cwd is ".", else the last part of cwd
      # invocation argv: pnpm → ("pnpm", "exec", "vitest", "run", …); npm → ("npx", "--no-install", "vitest", "run", …);
      #                  yarn → ("yarn", "vitest", "run", …)
      # validate_settings: no "cwd is required" error; package.json must exist in cwd;
      #                    "vitest: unsupported package manager '<name>'" for anything outside _PACKAGE_MANAGERS
  ```
  `.parrot/test_runners.toml` gains `distribution = "admin-ui"` under `[runners.vitest]`.

### Module 6: Guard and `select_tests` are repository-agnostic
- **Path**: `packages/ai-parrot/src/parrot/flows/dev_loop/test_scope/guard.py`,
  `packages/ai-parrot/src/parrot/sdd/scripts/select_tests.py`
- **Responsibility**: fix the three behaviours of Problem Statement item 2.
- **Depends on**: —
- **Interface Skeleton**:
  ```python
  # guard.py  (stdlib only)
  _PACKAGED_SELECT_TESTS: Path = Path(__file__).resolve().parents[3] / "sdd" / "scripts" / "select_tests.py"
  #: The packaged script run by the serving interpreter; a vendored kernel without it keeps the legacy value.
  VERDICT_ARGV: tuple[str, ...]  # verified: guard.py:21
  #   packaged script is a file → (sys.executable, str(_PACKAGED_SELECT_TESTS), "--tier", "task", "--run", "--verdict")
  #   otherwise               → ("python", "scripts/sdd/select_tests.py", "--tier", "task", "--run", "--verdict")

  # select_tests.py
  def _invocation_command(invocation: object, *, worktree: Path, timeout: int | None) -> tuple[list[str], Path]:
      """Argv and working directory for one planned invocation, shared by verdict mode and plain --run.

      The directory is ``worktree / invocation.cwd``. ``--timeout=<n>`` is appended only when
      ``invocation.runner == "pytest"`` and ``timeout`` is not None. Process supervision, deadlines and
      report parsing stay in each mode.
      """
  #   _run_verdict_mode (verified: :191; run_cwd at :248) and the plain --run loop in main()
  #   (verified: :493-521; --timeout at :499, subprocess.run(argv, cwd=worktree) at :521) both call it.
  ```

### Module 7: Toolchain profiles
- **Path**: `packages/ai-parrot/src/parrot/sdd/toolchain.py` (new)
- **Responsibility**: detect profiles and resolve step argv; no command execution.
- **Depends on**: Module 1
- **Interface Skeleton**:
  ```python
  # packages/ai-parrot/src/parrot/sdd/toolchain.py  (new; stdlib + pydantic + parrot.sdd.config)
  STEPS: tuple[str, ...] = ("fix", "format", "lint", "typecheck")
  MARKERS: Mapping[str, tuple[str, ...]] = {
      "python": ("pyproject.toml", "setup.py", "setup.cfg"),   # same set as installer._PYTHON_PROJECT_FILES (:871)
      "node": ("package.json",),
      "rust": ("Cargo.toml",),
  }

  class ToolchainProfile(BaseModel):
      """The tools one sub-tree of a repository uses. Every step is an argv or None (not configured)."""
      model_config = ConfigDict(extra="forbid")
      kind: Literal["python", "node", "rust"]
      root: str                       # repo-relative directory, "." for the repository root
      marker: str                     # repo-relative marker file that produced the profile
      suffixes: tuple[str, ...]
      package_manager: str | None = None
      fix: list[str] | None = None        # argv prefix; changed files (root-relative) are appended
      format: list[str] | None = None     # argv prefix; changed files (root-relative) are appended
      lint: list[str] | None = None
      typecheck: list[str] | None = None
      test: list[str] | None = None       # informational
      lint_takes_files: bool = False
      typecheck_takes_files: bool = False
      source: Literal["detected", "override"] = "detected"
      overridden_steps: tuple[str, ...] = ()  # non-null override fields in STEPS, including [] disables
      # Engine routing reads only "fix" and "format" from overridden_steps (Module 9).

  def detect_package_manager(root: Path) -> str:
      """package.json `packageManager`, else the lockfile, else "pnpm" — the vitest adapter's
      `_package_manager` rule without the runner setting. The kernel cannot import this module, so the
      rule exists twice and a parity test keeps the two aligned."""

  def detect_profiles(repo_root: Path, *, config: SddConfig | None = None) -> list[ToolchainProfile]:
      """Profiles for the repository root, every runner `cwd` (config `runners` and the TOML) and every
      `toolchain.profiles[].root`; then overrides applied by (kind, root). Sorted by (root, kind).
      ``config=None`` loads `sdd/config.json` of ``repo_root``. Never raises for a missing tool."""

  def profile_for_path(profiles: Sequence[ToolchainProfile], path: str) -> ToolchainProfile | None:
      """The profile with the longest root containing ``path`` whose suffixes match it."""

  def step_argv(profile: ToolchainProfile, step: str, files: Sequence[str] = ()) -> list[str] | None:
      """Argv for ``step``: `fix`/`format` append ``files``; `lint`/`typecheck` append them only when the
      profile's `*_takes_files` is true. None when the step is not configured, or when `fix`/`format`
      get no files. For file-taking lint/typecheck steps, an empty files sequence means the full
      profile root: append ".". With explicit files, append only those root-relative files, never ".".
      Commands execute from the profile root. The flags are resolved by `detect_profiles`: a detected
      step keeps its detected flag; an overridden `lint` / `typecheck` argv gets false, so it runs
      verbatim with no path and no "." (`["make", "lint"]` stays `make lint`), unless the override
      sets `lint_takes_files` / `typecheck_takes_files`, which always wins.

      Raises:
          ValueError: ``step`` is not in STEPS.
      """
  ```
  Detection rules (the task blueprint implements exactly these):
  - **python** — `fix = ["ruff","check","--fix","--exit-zero","--quiet"]` and `lint = ["ruff","check"]`
    when ruff is configured (`ruff.toml`, `.ruff.toml` or `[tool.ruff]`); `format` = `["black"]` when
    `[tool.black]`, else `["ruff","format"]` when ruff format settings exist (same rule as
    `detect_formatter`, lint.py:69-90); `typecheck = ["mypy"]` when `mypy.ini`, `.mypy.ini` or
    `[tool.mypy]` exists; `test = ["pytest"]`; both `*_takes_files` true; suffixes `(".py",)`.
    Thus a full-profile typecheck resolves to `["mypy", "."]`, while a scoped check resolves to
    `["mypy", <files...>]`; bare mypy is never emitted.
  - **node** — `PM = detect_package_manager(root)`; `EXEC` is `["pnpm","exec"]`, `["npx","--no-install"]`
    or `["yarn"]`. `fix = EXEC + ["eslint","--fix"]` when `eslint` is a dependency, else
    `EXEC + ["biome","check","--write"]` when `@biomejs/biome` is; `format = EXEC + ["prettier","--write"]`
    when `prettier` is a dependency, else `EXEC + ["biome","format","--write"]` only when
    `@biomejs/biome` is a dependency, else `None`; `lint = [PM,"run","lint"]`
    when `scripts.lint` exists; `typecheck = [PM,"run","check"]` when `scripts.check` exists, else
    `[PM,"run","typecheck"]` only when `scripts.typecheck` exists, else `EXEC + ["tsc","--noEmit"]`
    when `typescript` is a dependency and `tsconfig.json` exists; `test = [PM,"run","test"]` when `scripts.test` exists; suffixes
    `(".ts",".tsx",".js",".jsx",".mjs",".cjs",".svelte",".vue")`.
    Dependencies are checked in both `dependencies` and `devDependencies`. Every detection chain
    ends in `None` when none of its conditions match; an absent script or dependency is never selected.
  - **rust** — `format = ["cargo","fmt","--"]`, `lint = ["cargo","clippy","--","-D","warnings"]`,
    `typecheck = ["cargo","check"]`, `test = ["cargo","test"]`; suffixes `(".rs",)`.

### Module 8: `parrot sdd toolchain` CLI
- **Path**: `packages/ai-parrot/src/parrot/sdd/scripts/toolchain_cmd.py` (new),
  `packages/ai-parrot/src/parrot/sdd/cli.py`
- **Responsibility**: the one surface prompts and hooks use.
- **Depends on**: Module 7
- **Interface Skeleton**:
  ```python
  # packages/ai-parrot/src/parrot/sdd/scripts/toolchain_cmd.py  (new)
  EXIT_OK, EXIT_FAILED, EXIT_CONFIG, EXIT_TOOL_MISSING = 0, 1, 2, 3

  def main(argv: Sequence[str] | None = None) -> int:
      """`show [--path DIR] [--json]` — one line per profile (`<kind> <root> pm=<pm> fix=… format=… lint=…
      typecheck=… test=…`, `-` for a step that is not configured) or the profiles as a JSON list.

      `run <step> [--path DIR] [--files F ...]` — run ``step`` for every profile, or only for the
      profiles owning ``--files``. Prints `<step>: <kind>@<root>: <argv>` before each command and
      `<step>: not configured` when no profile has it. Exit: 0 every command exited 0 or nothing is
      configured; 1 a command failed; 2 `sdd/config.json` is unusable; 3 a configured command could not
      start (its tool is not installed).
      """

  # cli.py — VERBS (verified: cli.py:237; nouns mount from the loop at :370-373)
  #   "toolchain": {
  #       "show": ("toolchain_cmd", ("show",), "Show the detected toolchain profiles."),
  #       "run": ("toolchain_cmd", ("run",), "Run a toolchain step: fix | format | lint | typecheck."),
  #   },
  ```

### Module 9: Engine lint pass for non-Python profiles and Python profiles that override `fix` or `format`
- **Path**: `packages/ai-parrot/src/parrot/flows/dev_loop/sdd_coder/lint.py`
- **Responsibility**: honor `fix` / `format` overrides in the engine while preserving the legacy Python
  path when neither step is overridden. A Python repository without ruff declares a `fix` or `format`
  override to get the profile pass; the legacy pass still reports `ruff not found` there, as today.
- **Depends on**: Module 7
- **Interface Skeleton**:
  ```python
  # lint.py
  async def _run_python_pass(
      cwd: str, changed: List[str], *, config: LintConfig, commit_message: str, diff_base: Optional[str] = None
  ) -> LintReport:
      """Today's body of run_lint_pass, moved unchanged (verified: lint.py:215-…)."""

  async def run_profile_pass(cwd: str, changed: List[str], *, config: LintConfig, commit_message: str) -> LintReport:
      """For non-Python profiles and Python profiles whose overridden_steps contain "fix" or "format":
      when config.autofix is true, run `fix`, then `format` (whole file), then one
      autofix commit of the files the tools touched. Files are selected by the profile's suffixes and
      passed root-relative with the profile root as working directory; each command is bounded by
      LINT_TIMEOUT_S (verified: lint.py:30). A step that is not configured is skipped; a tool that cannot
      start, times out or exits non-zero is recorded in ``tool_error`` and the tree is restored to the
      committed state. ``errors`` and ``residual`` stay empty. Never raises, never blocks."""

  async def run_lint_pass(
      cwd: str, changed: List[str], *, config: LintConfig, commit_message: str, diff_base: Optional[str] = None
  ) -> LintReport:  # verified: lint.py:215 — signature unchanged; sole caller engine.py:77
      """Partition changed files by profile ownership before running either pass. Python files with
      no owning profile, or whose profile overrides neither `fix` nor `format`, go to _run_python_pass;
      other owned files go to run_profile_pass. A `lint`, `typecheck` or `test` override alone never
      changes the route. Never process a file twice or run the legacy formatter on a file routed to
      the profile pass. Reports merged: fixed_files concatenated, the later commit kept, tool errors
      joined with "; ", formatter = the legacy Python formatter when that pass processed files, else
      the first profile formatter's tool name. Python profiles routed to the profile pass leave
      residual lint to the full toolchain lint pass, as non-Python profiles do; the independent
      banned-import gate is unchanged."""
  ```

### Module 10: Prompts use the toolchain verbs
- **Path** (packaged source, then the installed twins re-synced from it):
  `packages/ai-parrot/src/parrot/sdd/_assets/claude/agents/sdd-qa.md`,
  `…/_assets/agents/agents/sdd-qa/agent.md`, `…/_assets/claude/agents/qa-runner.md`,
  `…/_assets/claude/commands/sdd-done.md`, `…/_assets/agent/workflows/sdd-done.md`,
  `…/_assets/agents/skills/sdd-done/SKILL.md`, `…/_assets/claude/hooks/sdd-worker-format.sh`
- **Responsibility**: replace tool names with the verbs; keep the Python wording as the example.
- **Depends on**: Module 8
- **Interface Skeleton** *(text contracts)*:
  - `sdd-qa` step 3 (verified: sdd-qa.md:57-59): run `parrot sdd toolchain run lint` and
    `parrot sdd toolchain run typecheck`; `lint_passed` = both exited 0; exit 3 is reported as
    "configured but not installed" and counts as not passed; "not configured" counts as passed.
  - `qa-runner` step 4 (verified: qa-runner.md:84-89): the two commands with `--files <changed-files>`;
    the "lint: not configured" sentence stays.
  - `sdd-done` §4.5 (verified: sdd-done.md:165-182): the ruff / black block stays for Python files
    whose profile overrides neither `fix` nor `format`; for Python files whose profile overrides one of
    them and for every other changed file run `parrot sdd toolchain run fix --files …` then
    `format --files …`, commit the result in the same style commit, then report `run lint` residuals.
  - `sdd-worker-format.sh` (verified: :69-75): the "no changed Python files" early exit becomes a branch;
    non-Python changed files and Python files whose profile overrides `fix` or `format` go through
    `parrot sdd toolchain run format --files …` when `parrot` is on `PATH`; the black / pylint path
    is retained only for Python files whose profile overrides neither step.
  - Both read the route from `parrot sdd toolchain show --json` (`root`, `suffixes`,
    `overridden_steps`); a `lint`, `typecheck` or `test` override alone never changes it.
  - Parity: every installed twin listed under §6 Edit Sites must be byte-identical to its packaged
    source after the re-sync. `scripts/sdd/check_asset_sync.py` is the existing gate; the task confirms
    it covers all eight twins and extends its parametrisation for any it does not.

### Module 11: Installer and doctor report the toolchain
- **Path**: `packages/ai-parrot/src/parrot/sdd/installer.py`, `packages/ai-parrot/src/parrot/self_/doctor.py`
- **Responsibility**: tell the operator what was detected and where the settings come from.
- **Depends on**: Module 7
- **Interface Skeleton**:
  ```python
  # installer.py
  def _toolchain_notes(root: Path, config: "SddConfig") -> list[str]:
      """`toolchain: <kind> at <root>[ (<pm>)]` per profile, or `toolchain: none detected`; plus, when
      `test_command` is null and a profile has `test`, `note: detected test command: <argv>`."""
  # appended next to _test_command_warning (verified: installer.py:1155)

  # doctor.py — _check_sdd (verified: doctor.py:293): two informational checks
  #   "sdd: toolchain"        detail = the profile lines above
  #   "sdd: settings source"  detail = per block (sandbox, worktree, runners): sdd/config.json | legacy file | default;
  #                           says "shadowed" when both files declare the block
  ```

### Module 12: Documentation and the foreign Node repository scenarios
- **Path**: `docs/sdd/non-python-repositories.md` (new), `docs/dev_loop/claude-native-sandbox.md`,
  `packages/ai-parrot/src/parrot/sdd/_assets/claude/rules/worktree-management.md` (and its twins),
  `packages/ai-parrot/tests/sdd/test_wheel_only_foreign_repo.py`
- **Responsibility**: one guide for a non-Python repository; the resolution order in the sandbox doc; the
  worktree rule names both declaration homes; end-to-end scenarios in the existing wheel-only
  foreign-repository harness, which already installs from the built wheel into a non-Python repository
  and runs every documented helper. No Node installation is needed.
- **Depends on**: Modules 1–11
- **Interface Skeleton** *(test contract)*:
  ```python
  # packages/ai-parrot/tests/sdd/test_wheel_only_foreign_repo.py  (extends; foreign_repo fixture verified: :494)
  @pytest.fixture
  def node_foreign_repo(tmp_path: Path) -> tuple[Path, Path]:
      """`foreign_repo` plus package.json (scripts lint/check/test; prettier + vitest devDependencies),
      pnpm-lock.yaml, src/a.ts + src/a.test.ts and an sdd/config.json with sandbox, worktree.setup and
      runners; a fake `pnpm` in the tools dir records its argv and cwd and exits 0."""

  def test_node_install_reports_toolchain(managed_home, tools_dir, node_foreign_repo): ...
  def test_node_sandbox_policy_comes_from_config_json(managed_home, tools_dir, node_foreign_repo): ...
  def test_node_select_tests_plans_vitest_without_runner_toml(managed_home, tools_dir, node_foreign_repo): ...
  def test_node_guard_verdict_command_is_startable(managed_home, tools_dir, node_foreign_repo): ...
  def test_node_ensure_worktree_setup_runs_reruns_and_blocks(managed_home, tools_dir, node_foreign_repo): ...
  def test_plain_repo_toolchain_lint_is_not_configured(managed_home, tools_dir, foreign_repo): ...
  ```

---

## 4. Test Specification

### Unit Tests

| Test | Module | Description |
|---|---|---|
| `test_config_accepts_new_blocks` / `test_config_rejects_unknown_block_key` | M1 | each block validates; a typo inside a block fails |
| `test_native_group_schema_parity` | M1, M3 | NativeGroupSettings and NativeGroup accept identical valid entries and defaults; both reject missing name, unknown keys and wrong field types |
| `test_setup_rejects_absolute_and_parent_paths` | M1 | `cwd` / `inputs` validators |
| `test_mode_from_config_json_wins_over_pyproject` | M2 | block precedence |
| `test_mode_falls_back_to_pyproject_when_no_block` | M2 | ai-parrot path unchanged |
| `test_config_json_cannot_set_off_or_legacy` | M2 | refusal kept |
| `test_launch_config_reads_primary_config_json` | M2 | domains and `gh_token` |
| `test_wizard_writes_config_json_without_pyproject` | M2 | no `pyproject.toml` is created |
| `test_wizard_keeps_pyproject_when_table_lives_there` | M2 | Python repository unchanged |
| `test_manifest_from_config_json` / `test_manifest_falls_back_to_pyproject` | M3 | both homes |
| `test_setup_runs_then_skips_on_same_fingerprint` | M4 | stamp |
| `test_setup_reruns_when_input_changes` | M4 | fingerprint covers input bytes |
| `test_setup_reruns_when_command_changes` | M4 | fingerprint covers the declaration |
| `test_setup_failure_returns_not_ok_and_clears_stamp` | M4 | retry after failure |
| `test_setup_read_from_main_root_not_target` | M4 | trust rule: a tampered worktree `sdd/config.json` is ignored |
| `test_setup_runs_when_native_sync_raises` | M4 | the setup step is outside the native-sync `try` |
| `test_no_setup_flag_and_env_skip` | M4 | `--no-setup`, `PARROT_WORKTREE_SETUP=0` |
| `test_tampered_worktree_config_cannot_change_launch_policy` | M2 | `load_launch_config` reads the primary only |
| `test_pool_create_raises_on_setup_failure` | M4 | `SubWorktreeMergeError` |
| `test_config_runners_replace_toml_kind` | M5 | per-kind overlay |
| `test_registry_stays_stdlib_only` | M5 | existing `test_stdlib_only.py` still passes |
| `test_vitest_defaults_cwd_to_root` / `test_vitest_package_manager_from_lockfile` | M5 | npm, yarn, pnpm argv |
| `test_vitest_package_manager_field_beats_lockfile` | M5 | `packageManager` wins over a lockfile |
| `test_vitest_rejects_unsupported_package_manager` | M5 | `validate_settings` names it |
| `test_vitest_distribution_default` | M5 | `"vitest"` at root, last path part otherwise |
| `test_config_runner_cwd_must_be_contained` | M1 | `runners.<kind>.cwd` rejects absolute and `..` paths |
| `test_verdict_argv_points_at_packaged_script` | M6 | absolute path, `sys.executable` |
| `test_invocation_command_cwd_and_timeout` | M6 | the shared helper, for pytest, vitest and cargo invocations |
| `test_run_and_verdict_modes_use_same_command` | M6 | both modes call the helper |
| `test_profiles_two_kinds_same_root_map_files_uniquely` | M7 | `pyproject.toml` + `package.json` at one root |
| `test_detect_python_profile_matches_detect_formatter` | M7 | parity with lint.py |
| `test_detect_node_profile_from_scripts_and_dependencies` | M7 | the navigator-frontend-next shape |
| `test_node_missing_tools_are_not_configured` | M7, M8 | no formatter dependency yields format=None; neither check script nor TypeScript+tsconfig yields typecheck=None; run returns 0 without spawning a command |
| `test_node_detection_fallbacks` | M7 | Prettier beats Biome; Biome requires its dependency; check beats typecheck, then TypeScript+tsconfig, then None; cover dependencies and devDependencies |
| `test_python_typecheck_targets` | M7, M8 | full-profile argv is mypy . in the profile root; --files emits only the supplied relative files, including a nested profile root |
| `test_profiles_at_runner_cwd_and_override_root` | M7 | ai-parrot shape: Python root + Svelte UI |
| `test_override_replaces_and_disables_step` | M7 | `[]` disables |
| `test_override_takes_files_resolution` | M7, M8 | Python `lint=["make","lint"]` resolves to `make lint` with and without `--files`; the same override with `lint_takes_files=true` appends "." or the files; a step that is not overridden keeps the detected flag; an explicit false on a detected step stops the appending |
| `test_package_manager_parity_with_vitest_adapter` | M7 | one rule, two implementations |
| `test_toolchain_run_exit_codes` | M8 | 0 / 1 / 2 / 3 and "not configured" |
| `test_toolchain_noun_is_mounted` | M8 | `mounted_modules()` |
| `test_profile_pass_formats_and_commits_ts_files` | M9 | fake formatter binary |
| `test_python_pass_report_unchanged` | M9 | existing no-override `test_lint.py` cases untouched; null overrides preserve the legacy path |
| `test_python_lint_or_typecheck_override_keeps_legacy_route` | M9 | a Python profile overriding only `lint`, `typecheck` or `test` still goes through `_run_python_pass`: line-scoped formatting and the ruff `errors` / `residual` report are identical to the no-override case |
| `test_python_override_engine_cli_parity` | M9 | format=[] never runs Black; custom fix/format argv match CLI resolution; omitted steps retain detection; mixed profile roots process each file once; config.autofix=False runs no mutating steps |
| `test_python_override_prompt_routing` | M10 | closeout and format hook route Python files whose profile overrides `fix` or `format` through toolchain commands without also invoking legacy formatters; a `lint`-only override keeps the black / ruff path |
| `test_installer_prints_toolchain_lines` | M11 | line format |

### Integration Tests

| Test | Description |
|---|---|
| `test_wheel_only_foreign_repo.py` (extended) | the six scenarios of Module 12, installed from the built wheel into a Node-shaped repository |
| `test_config_blocks_parity` | valid and invalid `sdd/config.json` fixtures through `SddConfig`, the sandbox reader, `load_manifest` and `load_registry`; acceptance and rejection agree for each reader's owned block, including native group fields and defaults |

### Validation Contract

tests:
- packages/ai-parrot/tests/sdd/test_config.py
- packages/ai-parrot/tests/sdd/test_sdd_cli.py
- packages/ai-parrot/tests/sdd/test_installer.py
- packages/ai-parrot/tests/flows/dev_loop/test_native_claude_sandbox.py
- packages/ai-parrot/tests/flows/dev_loop/test_native_artifacts.py
- packages/ai-parrot/tests/flows/dev_loop/test_worktree_manager.py
- packages/ai-parrot/tests/flows/dev_loop/sdd_coder/test_lint.py
- packages/ai-parrot/tests/flows/dev_loop/test_scope/test_runners_registry.py
- packages/ai-parrot/tests/flows/dev_loop/test_scope/test_runner_vitest.py
- packages/ai-parrot/tests/flows/dev_loop/test_scope/test_guard.py
- packages/ai-parrot/tests/flows/dev_loop/test_scope/test_planner.py
- packages/ai-parrot/tests/flows/dev_loop/test_scope/test_stdlib_only.py
- packages/ai-parrot/tests/knowledge/wiki/test_welcome.py
- tests/sdd_scripts/test_ensure_worktree.py
- tests/sdd_scripts/test_select_tests.py
- tests/sdd_scripts/test_repo_runner_config.py
- tests/sdd_scripts/test_native_artifact_declaration.py
- tests/sdd_scripts/test_feat722_doc_contract.py
- tests/sdd_scripts/test_command_twin_parity.py
- tests/sdd_scripts/test_check_asset_sync.py
- packages/ai-parrot/tests/flows/dev_loop/test_subagent_parity.py
- packages/ai-parrot/tests/flows/dev_loop/test_rules_parity.py
- packages/ai-parrot/tests/sdd/test_wheel_only_foreign_repo.py
markers: none

The new files (`test_toolchain.py`, `test_toolchain_cmd.py`, `test_config_blocks_parity.py`, all under
`packages/ai-parrot/tests/sdd/`) are added to this list by `/sdd-task` once the tasks that create them
exist. `test_wheel_only_foreign_repo.py` is `integration`-marked and builds a wheel; listed operands
with that marker do run.

### Test Data / Fixtures

```python
# Reuse: empty_repo (packages/ai-parrot/tests/sdd/test_installer.py:31) — a git repository with only README.md.
# Reuse: foreign_repo / managed_home / tools_dir (packages/ai-parrot/tests/sdd/test_wheel_only_foreign_repo.py:494, :674).
@pytest.fixture
def node_foreign_repo(tmp_path):
    """foreign_repo plus package.json, pnpm-lock.yaml, one .ts source and test, sdd/config.json; a fake `pnpm`."""

@pytest.fixture
def full_config():
    """A dict with every new block populated, shared by the parity test and the reader tests."""
```

---

## 5. Acceptance Criteria

- [ ] In a repository with no `pyproject.toml`, `sandbox.mode`, `sandbox.allowed_domains` and
  `sandbox.gh_token` in `sdd/config.json` are honoured by `resolve_sandbox_mode` and
  `load_launch_config`; `off` / `legacy` in that file are refused.
- [ ] The welcome wizard never creates `pyproject.toml` in a repository that has none.
- [ ] `worktree.native_groups` and `worktree.setup` in `sdd/config.json` are honoured; a repository
  with only `[tool.parrot.worktree]` behaves as today.
- [ ] `parrot sdd worktree ensure` runs the setup command on creation, skips it on reuse with unchanged
  inputs, re-runs it when an input file changes, and exits non-zero with the command's output when it
  fails. `--no-setup` and `PARROT_WORKTREE_SETUP=0` skip it. The sdd-coder pool does the same per
  sub-worktree.
- [ ] `runners.<kind>` in `sdd/config.json` replaces that kind's TOML table; `test_stdlib_only.py` passes.
- [ ] With no runner settings at all, `select_tests` plans and runs a vitest contract in a repository
  whose `package.json` is at the root, for pnpm, npm and yarn lockfiles.
- [ ] The guard's verdict command starts in a repository that has no `scripts/sdd/` directory.
- [ ] `select_tests --run` runs a vitest invocation in the runner's `cwd` and never passes `--timeout`
  to it.
- [ ] `parrot sdd toolchain show` lists a Python profile at the root and a Node profile at
  `packages/ai-parrot-server/ui` in ai-parrot, and a Node profile at the root in the fixture repository.
- [ ] `parrot sdd toolchain run lint` exits 0 and prints `lint: not configured` in a repository with no
  lint tooling; `sdd-qa` no longer names ruff or mypy as mandatory.
- [ ] The engine lint pass commits prettier output for a changed `.ts` file and its report for a
  Python-only change whose profile overrides neither `fix` nor `format` is identical to today's.
- [ ] Full-profile Python typechecks run `mypy .` from the profile root; scoped checks pass only the
  selected root-relative files. QA never invokes bare mypy.
- [ ] Node profiles with no formatter dependency or supported typecheck script/tool report those
  steps as not configured and spawn no command; each fallback requires its stated dependency/script.
- [ ] Explicit Python `fix` / `format` overrides, including `[]` disables, are honored by the engine,
  closeout and format hook. No file runs through both the legacy and profile passes; null/omitted
  overrides preserve the legacy route, and `config.autofix=False` prevents all engine mutations.
- [ ] A Python profile that overrides only `lint`, `typecheck` or `test` keeps the legacy engine route:
  line-scoped formatting and the ruff error report are unchanged.
- [ ] An overridden `lint` / `typecheck` argv runs verbatim, with no path appended, unless the override
  sets `lint_takes_files` / `typecheck_takes_files`; a step that is not overridden keeps its detected
  flag.
- [ ] `SddConfig` and `load_manifest` agree on native-group fields, defaults and validation: missing
  names, unknown keys and invalid field types are rejected by both readers.
- [ ] ai-parrot's own vitest report paths keep the `admin-ui` label.
- [ ] A worktree copy of `sdd/config.json` edited by a sandboxed session changes neither the launch
  policy nor the setup command.
- [ ] Every installed prompt twin is byte-identical to its packaged source.
- [ ] Every test in the Validation Contract passes, and the three new test files pass.
- [ ] `docs/sdd/non-python-repositories.md` documents the four blocks, the precedence and the setup
  command; the sandbox doc states the new resolution order.
- [ ] No breaking change: a repository whose `sdd/config.json` has none of the new blocks produces the
  same behaviour as before this feature.

---

## 6. Codebase Contract

### Verified Imports

```python
from parrot.sdd.config import SddConfig, SddConfigError, find_repo_root, load_sdd_config  # verified: sdd/config.py:15,19,93,106
from parrot.sdd.config import CONFIG_PATH                                                 # verified: sdd/config.py:11 (a Path)
from parrot.flows.dev_loop.sdd_coder.lint import run_lint_pass                            # verified: sdd_coder/engine.py:77
from pydantic import BaseModel, ConfigDict, Field                                         # verified: native_artifacts.py:31
# Path-loaded, never imported as parrot.*:
#   native_artifacts.py   — ensure_worktree.py:27-41, test_scope/baseline.py:27-55
#   test_scope kernel     — sdd/scripts/select_tests.py:21-24, worktree_environment.py:322-335
```
All paths below are under `packages/ai-parrot/src/parrot/` unless they start with `packages/`, `tests/`,
`docs/` or `.`.

### Existing Class Signatures

```python
# sdd/config.py
CONFIG_PATH = Path("sdd/config.json")                                   # line 11
class SddConfig(BaseModel):                                             # line 19
    model_config = ConfigDict(extra="forbid")                           # line 22
    base_branch: str = "dev"                                            # line 24
    staging_branch: str | None = None                                   # line 25
    hotfix_base: str = "main"                                           # line 26
    ledger_branch: str | None = None                                    # line 28
    issue_tracker: Literal["jira", "none"] = "none"                     # line 29
    jira_host: str | None = None                                        # line 30
    reviewer: Literal["codex", "none"] = "none"                         # line 31
    test_command: str | None = None                                     # line 33
    projects: list[str] | None = None                                   # line 35
def find_repo_root(start: Path | None = None) -> Path | None            # line 93
def load_sdd_config(root: Path | None = None) -> SddConfig              # line 106 — raises SddConfigError
# pydantic names imported today: BaseModel, ConfigDict, ValidationError, field_validator, model_validator (line 9)

# sdd/scripts/native_claude_sandbox.py  (stdlib only; `if __package__:` dual import at lines 27-30)
MODE_ENV = "PARROT_SDD_SANDBOX_MODE"                                    # line 36
SANDBOX_MODES = ("required", "preferred", "off", "legacy")              # line 38
def _native_roots(cwd: Path) -> tuple[Path, Path, Path]                 # line 138 — (root, git dir, primary)
def resolve_sandbox_mode(repo_root: Path) -> str                        # line 246; callers :452, :856
def load_launch_config(primary: Path) -> tuple[list[str], bool]         # line 637; callers :857, flows/dev_loop/feature_launcher.py:499
# validate_allowed_domains(...) and merge_domains(*groups) exist (used at :671, :678)

# flows/dev_loop/native_artifacts.py  (stdlib + pydantic)
SYNC_ENV_VAR: str = "PARROT_WORKTREE_SYNC_NATIVE"                        # line 42
class NativeGroup(BaseModel):                                           # line 49 — name, copy_globs, pair_sources, required,
                                                                        #   abi_scoped, autobuild, build, build_cwd, build_timeout_s, manual_hint
class NativeManifest(BaseModel):                                        # line 66 — enabled: bool = True; groups: list[NativeGroup]
class NativeSyncReport(BaseModel):                                      # line 87
def env_flag_disabled(name: str) -> bool                                # line 98
def load_manifest(repo_root: Path) -> NativeManifest                    # line 103
def main_checkout_root(worktree: Path) -> Path | None                   # line 134
def sync_native_artifacts(*, main_root: Path, target: Path,
                          manifest: NativeManifest | None = None, autobuild: bool = True) -> NativeSyncReport   # line 331

# sdd/scripts/ensure_worktree.py
from parrot.sdd.config import load_sdd_config                           # line 21
def main(argv: Sequence[str] | None = None) -> int                      # line 342 — returns 0 (:483) or 1 (:487)
#   repo_root = Path.cwd(); cfg = load_sdd_config(repo_root)            # lines 385-386
#   stdout carries ONLY the worktree path (or the --json object); warnings go to stderr (:452-454)

# flows/dev_loop/worktree_manager.py
class SubWorktreeMergeError(Exception)                                  # line 47
    async def create(self, worker_id: str, *, base: Optional[str] = None) -> str      # line 146
    async def _sync_native_artifacts(self, path: str) -> None           # line 178 — never raises

# flows/dev_loop/test_scope/runners/registry.py  (stdlib only)
CONFIG_PATH: str = ".parrot/test_runners.toml"                          # line 14
BUILTIN_MODULES = {"pytest": …, "vitest": …, "cargo": …, "parrot-e2e": …}   # lines 15-20
class RunnerRegistry:                                                   # line 23
    def settings_for(self, kind: str) -> Mapping[str, str]              # line 79
def _settings_from_toml(raw_settings: Mapping[str, Any]) -> dict[str, str]   # line 115 — lists joined with ","
def load_registry(worktree: Path) -> RunnerRegistry                     # line 133

# flows/dev_loop/test_scope/runners/vitest.py  (stdlib only)
class VitestAdapter:                                                    # line 16
    binaries = ("pnpm", "vitest")                                       # line 20
    def mirror_targets(self, changed, *, worktree, settings) -> list[str]            # line 42
    def distribution_of(self, target, *, settings) -> str               # line 64 — default "admin-ui" (:66)
    def invocation(self, targets, *, distribution, worktree, settings, policy, report_path) -> Invocation   # line 68
    def validate_settings(self, settings, *, worktree) -> list[str]     # line 115 — "vitest: cwd is required" (:119)
ADAPTER = VitestAdapter()                                               # line 125

# flows/dev_loop/test_scope/datatypes.py
class Invocation:                                                       # line 23 — distribution, argv, targets, runner="pytest",
                                                                        #   cwd=".", report_path="", report_format="junit", timeout_s=0

# flows/dev_loop/test_scope/guard.py
VERDICT_ARGV: tuple[str, ...] = ("python", "scripts/sdd/select_tests.py", "--tier", "task", "--run", "--verdict")   # line 21
def guard_bash(command: str, *, worktree: Path) -> tuple[GuardOutcome, str | None]   # line 80 — rewrite built at :120-121

# flows/dev_loop/sdd_coder/lint.py
def resolve_bin(name: str) -> Optional[str]                             # line 43
def detect_formatter(cwd: str, configured: str) -> str                  # line 69
def _existing_python_files(cwd: str, changed: List[str]) -> List[str]   # line 119
async def run_lint_pass(cwd, changed, *, config, commit_message, diff_base=None) -> LintReport   # line 215
# flows/dev_loop/sdd_coder/models.py
class LintConfig(BaseModel)                                             # line 189 — autofix, formatter, error_select, format_scope
class LintReport(BaseModel)                                             # line 213 — formatter, fixed_files, commit, errors,
                                                                        #   residual_count, residual, tool_error

# knowledge/wiki/claude_code/welcome.py
def current_sandbox_mode(root: Path) -> str | None                      # line 137
def write_sandbox_mode(root: Path, choice: str) -> str                  # line 160
def _set_pyproject_sandbox(root: Path, value: str) -> None              # line 172 — creates the file when absent (:174-181)
def _set_local_env(root: Path, value: str | None) -> None               # line 208

# sdd/cli.py
VERBS: dict[str, dict[str, tuple[str, tuple[str, ...], str]]]           # line 237 — noun → verb → (scripts module, prefix, help)
def mounted_modules() -> set[str]                                       # line 311
# nouns are mounted by the loop `for _noun, _verbs in VERBS.items():` (lines 370-373)

# sdd/installer.py
_PYTHON_PROJECT_FILES = ("pyproject.toml", "setup.py", "setup.cfg")     # line 871
def _test_command_warning(config: "SddConfig") -> str | None            # line 858
# self_/doctor.py
def _check_sdd(root: Path) -> list[DoctorCheck]                         # line 293
```

### Integration Points

| New Component | Connects To | Via | Verified At |
|---|---|---|---|
| `SddConfig.sandbox` | `resolve_sandbox_mode` / `load_launch_config` | raw `json` read of the same file | `native_claude_sandbox.py:246`, `:637` |
| `SddConfig.worktree` | `load_manifest` | raw `json` read; `NativeManifest.model_validate` | `native_artifacts.py:103-126` |
| `SddConfig.runners` | `load_registry` | raw `json` read; `_settings_from_toml` | `registry.py:115`, `:133` |
| `run_worktree_setup` | `ensure_worktree.main` | call after the native sync | `ensure_worktree.py:442-454` |
| `run_worktree_setup` | `SubWorktreeManager.create` | call after `_sync_native_artifacts` | `worktree_manager.py:175` |
| `detect_profiles` | `run_lint_pass` | import in `lint.py` | `lint.py:215` |
| `toolchain_cmd.main` | `parrot sdd` | `VERBS["toolchain"]` | `cli.py:237`, `:370-373` |
| `_toolchain_notes` | `install_sdd_integration` | appended to `actions` | `installer.py:1155` |

### Does NOT Exist (Anti-Hallucination)

- ~~`parrot.sdd.toolchain`~~, ~~`parrot.sdd.scripts.toolchain_cmd`~~ — created by this spec.
- ~~`parrot.sdd.repo_settings`~~ or any shared settings-reader module — deliberately not created; each
  path-loaded reader reads its own block.
- ~~`SddConfig.sandbox` / `.worktree` / `.runners` / `.toolchain`~~, ~~`SandboxSettings`~~,
  ~~`WorktreeSettings`~~, ~~`WorktreeSetup`~~, ~~`ToolchainOverride`~~, ~~`ToolchainSettings`~~ — created here.
- ~~`run_worktree_setup`~~, ~~`SetupReport`~~, ~~`SetupSpec`~~, ~~`NativeManifest.setup`~~ — created here.
- ~~`parrot sdd worktree ensure --no-setup`~~, ~~`PARROT_WORKTREE_SETUP`~~ — created here.
- ~~a `package_manager` runner setting~~, ~~`ToolchainProfile`~~, ~~`detect_profiles`~~ — created here.
- ~~`parrot sdd toolchain`~~ — no such noun in `VERBS` today.
- ~~a generic shell or `pnpm` runner kind~~ — the registry has only pytest, vitest, cargo, parrot-e2e.
- ~~`parrot sdd install --test-command`~~ — the installer has no such option.
- ~~Python code that executes `SddConfig.test_command`~~ — it is stored and validated only; prompts run it.
- ~~`parrot.sdd.config.worktree_root()`~~ — added by FEAT-802, not on `dev` yet.

### Edit Sites (Blueprint Anchors)

Verified against: `dcc507f013`

| File | Action | Verbatim anchor line | Verified at | Occurrences |
|---|---|---|---|---|
| `packages/ai-parrot/src/parrot/sdd/config.py` | MODIFY | `    projects: list[str] \| None = None` | `config.py:35` | 1 |
| `packages/ai-parrot/src/parrot/sdd/scripts/native_claude_sandbox.py` | MODIFY | `def resolve_sandbox_mode(repo_root: Path) -> str:` | `:246` | 1 |
| `packages/ai-parrot/src/parrot/sdd/scripts/native_claude_sandbox.py` | MODIFY | `def load_launch_config(primary: Path) -> tuple[list[str], bool]:` | `:637` | 1 |
| `packages/ai-parrot/src/parrot/knowledge/wiki/claude_code/welcome.py` | MODIFY | `def current_sandbox_mode(root: Path) -> str \| None:` | `:137` | 1 |
| `packages/ai-parrot/src/parrot/knowledge/wiki/claude_code/welcome.py` | MODIFY | `def write_sandbox_mode(root: Path, choice: str) -> str:` | `:160` | 1 |
| `packages/ai-parrot/src/parrot/flows/dev_loop/native_artifacts.py` | MODIFY | `def load_manifest(repo_root: Path) -> NativeManifest:` | `:103` | 1 |
| `packages/ai-parrot/src/parrot/flows/dev_loop/native_artifacts.py` | MODIFY | `def sync_native_artifacts(` | `:331` | 1 |
| `packages/ai-parrot/src/parrot/sdd/scripts/ensure_worktree.py` | MODIFY | `        "--no-autobuild",` | `:377` | 1 |
| `packages/ai-parrot/src/parrot/sdd/scripts/ensure_worktree.py` | MODIFY | `        native = NativeSyncReport(enabled=False)` | `:442` | 1 |
| `packages/ai-parrot/src/parrot/flows/dev_loop/worktree_manager.py` | MODIFY | `        await self._sync_native_artifacts(path)` | `:175` | 1 |
| `packages/ai-parrot/src/parrot/flows/dev_loop/test_scope/runners/registry.py` | MODIFY | `def load_registry(worktree: Path) -> RunnerRegistry:` | `:133` | 1 |
| `packages/ai-parrot/src/parrot/flows/dev_loop/test_scope/runners/vitest.py` | MODIFY | `        cwd = (worktree / settings["cwd"]).resolve()` | `:44` | 1 |
| `packages/ai-parrot/src/parrot/flows/dev_loop/test_scope/runners/vitest.py` | MODIFY | `            cwd=settings["cwd"],` | `:86` | 1 |
| `.parrot/test_runners.toml` | MODIFY | `[runners.vitest]` | `:7` | 1 |
| `packages/ai-parrot/src/parrot/flows/dev_loop/test_scope/guard.py` | MODIFY | `VERDICT_ARGV: tuple[str, ...] = (` | `:21` | 1 |
| `packages/ai-parrot/src/parrot/sdd/scripts/select_tests.py` | MODIFY | `            argv.append(f"--timeout={args.timeout}")` | `:499` | 1 |
| `packages/ai-parrot/src/parrot/sdd/scripts/select_tests.py` | MODIFY | `            result = subprocess.run(argv, cwd=worktree)` | `:521` | 1 |
| `packages/ai-parrot/src/parrot/sdd/toolchain.py` | CREATE | — | — | — |
| `packages/ai-parrot/src/parrot/sdd/scripts/toolchain_cmd.py` | CREATE | — | — | — |
| `packages/ai-parrot/src/parrot/sdd/cli.py` | MODIFY | `    "hooks": {` | `:300` | 1 |
| `packages/ai-parrot/src/parrot/flows/dev_loop/sdd_coder/lint.py` | MODIFY | `    py_files = await asyncio.to_thread(_existing_python_files, cwd, changed)` | `:234` | 1 |
| `packages/ai-parrot/src/parrot/sdd/_assets/claude/agents/sdd-qa.md` | MODIFY | `3. Run lint: ``ruff check .`` and ``mypy --no-incremental .`` (or the` | `:57` | (unverified count — check before use) |
| `packages/ai-parrot/src/parrot/sdd/_assets/claude/agents/qa-runner.md` | MODIFY | `4. **Lint and type-check the changed files only, with the tools the repository configures:**` | `:84` | (unverified count — check before use) |
| `packages/ai-parrot/src/parrot/sdd/_assets/claude/commands/sdd-done.md` | MODIFY | `configures ruff (`ruff.toml`, `.ruff.toml` or `[tool.ruff]` in `pyproject.toml`);` | `:168` | (unverified count — check before use) |
| `packages/ai-parrot/src/parrot/sdd/_assets/claude/hooks/sdd-worker-format.sh` | MODIFY | `    \| grep -E '\.py$' \` | `:69` | (unverified count — check before use) |
| `packages/ai-parrot/src/parrot/sdd/installer.py` | MODIFY | `    actions.append(_test_command_warning(config) or "")` | `:1155` | 1 |
| `packages/ai-parrot/src/parrot/self_/doctor.py` | MODIFY | `def _check_sdd(root: Path) -> list[DoctorCheck]:` | `:293` | 1 |
| `docs/sdd/non-python-repositories.md` | CREATE | — | — | — |
| `docs/dev_loop/claude-native-sandbox.md` | MODIFY | `Resolution order: `PARROT_SDD_SANDBOX_MODE` (empty or whitespace counts as unset) → `[tool.parrot.sdd]` | `:87` | (unverified count — check before use) |
| `packages/ai-parrot/tests/sdd/test_toolchain.py` | CREATE | — | — | — |
| `packages/ai-parrot/tests/sdd/test_toolchain_cmd.py` | CREATE | — | — | — |
| `packages/ai-parrot/tests/sdd/test_config_blocks_parity.py` | CREATE | — | — | — |
| `packages/ai-parrot/tests/sdd/test_wheel_only_foreign_repo.py` | MODIFY | `def foreign_repo(tmp_path: Path) -> tuple[Path, Path]:` | `:494` | 1 |
| `packages/ai-parrot/src/parrot/sdd/scripts/select_tests.py` | MODIFY | `        run_cwd = worktree / invocation.cwd` | `:248` | (unverified count — check before use) |

Installed twins re-synced from the packaged sources in Module 10 (never hand-edited):
`.claude/agents/sdd-qa.md`, `.claude/agents/qa-runner.md`, `.claude/commands/sdd-done.md`,
`.claude/hooks/sdd-worker-format.sh`, `.agent/agents/sdd-qa/agent.md`, `.agents/agents/sdd-qa/agent.md`,
`.agent/workflows/sdd-done.md`, `.agents/skills/sdd-done/SKILL.md`.

---

## 7. Implementation Notes & Constraints

### Patterns to Follow

- **Whole-block precedence.** A reader picks one file per block and reads the whole block from it.
  Never merge keys of the same block across `sdd/config.json` and the legacy file.
- **Path-loaded modules stay self-contained.** `native_artifacts.py` (stdlib + pydantic), the
  `test_scope` kernel (stdlib) and `native_claude_sandbox.py` (stdlib) must not import `parrot.*`. Each
  reads `sdd/config.json` with `json`.
- **Fail closed with the file name.** A malformed block raises `ValueError` whose message starts with
  the file it came from, as `load_registry` and `load_launch_config` do today.
- **Self-skipping steps print one line** ("lint: not configured"), as `sdd-done` §4.5 does for ruff.
- **Reports, not exceptions**, for anything that runs a subprocess during worktree preparation
  (`NativeSyncReport`, now `SetupReport`); the caller decides severity.
- **Legacy Python path byte-for-byte.** `_run_python_pass` is today's `run_lint_pass` body moved, not
  edited. Only Python files whose profile overrides neither `fix` nor `format` enter it; the others
  use the profile pass. `lint`, `typecheck` and informational `test` overrides alone do not change
  lint-pass routing, because the engine pass runs none of them.

### Known Risks / Gotchas

- **Config version skew.** `SddConfig` forbids unknown keys, so a `sdd/config.json` carrying a new block
  is rejected by an older parrot. The error already names the file and key; the guide says which parrot
  version introduced each block.
- **A host-side command is code execution.** The setup command is read from the main checkout only,
  printed before it runs, uses argv with no shell, and is skipped by `--no-setup` /
  `PARROT_WORKTREE_SETUP=0`. It is never read from the worktree being prepared.
- **Setup under an active sandbox.** `/sdd-start` may call `ensure` from a sandboxed session, where the
  registry is unreachable unless its host is in `sandbox.allowed_domains`. The guide recommends an
  offline-capable command (`pnpm install --frozen-lockfile --prefer-offline`) and the launcher path,
  which creates the worktree on the host.
- **Setup per pool sub-worktree** costs one install per task. With pnpm's content-addressed store this
  is seconds; with npm it is not. The guide says so; `inputs` avoids repeats within one sub-worktree.
- **`enabled: false`** in the `worktree` block disables the native sync and the setup command together.
- **ai-parrot's vitest label.** The adapter's default label changes from `admin-ui` to the last part of
  `cwd`; Module 5 pins `distribution = "admin-ui"` in `.parrot/test_runners.toml` in the same task.
- **Vendored kernels.** Other repositories vendor `test_scope`. The guard therefore keeps the legacy
  `VERDICT_ARGV` when the packaged script is not next to it, and the registry treats a missing
  `sdd/config.json` as "no overlay".
- **Doc-contract tests** pin text about `[tool.parrot.worktree]` and the sandbox resolution order
  (`tests/sdd_scripts/test_feat722_doc_contract.py`, `test_native_artifact_declaration.py`). The tasks
  that change those documents update the pinned text in the same commit.
- **Asset twins.** Prompt edits go to `_assets/` and the installed copies are regenerated; the
  re-sync inside ai-parrot must use the portable form so no absolute path is baked into a shipped file.
- **Script-based lint ignores `--files`.** A Node `lint` script lints its whole project, so
  `qa-runner`'s "changed files only" holds for Python and not for a Node profile; the verb prints the
  argv it actually ran.
- **FEAT-802 and FEAT-804** edit `config.py`, `installer.py`, `doctor.py` and `ensure_worktree.py`.
  Every anchor in §6 must be re-verified by `/sdd-task` after they merge.

### External Dependencies

| Package | Version | Reason |
|---|---|---|
| — | — | none; `json`, `tomllib`, `hashlib` and `subprocess` from the standard library |

---

## Decisions

```yaml
schema_version: 1
document_id: sdd-non-python-repos
entries:
  - id: sdd-config-json-is-the-settings-home
    statement: Repository-level SDD settings (sandbox policy, worktree manifest and setup, runner settings, toolchain overrides) are declared in sdd/config.json; pyproject.toml [tool.parrot.*] and .parrot/test_runners.toml are fallbacks read only when sdd/config.json does not declare the block or runner kind.
    relation: constrains
    about: [sdd-tooling, dev-loop]
    targets: [file:packages/ai-parrot/src/parrot/sdd/config.py, file:packages/ai-parrot/src/parrot/sdd/scripts/native_claude_sandbox.py, file:packages/ai-parrot/src/parrot/flows/dev_loop/native_artifacts.py, file:packages/ai-parrot/src/parrot/flows/dev_loop/test_scope/runners/registry.py]
    contradicts: []
    supersedes: []
    rationale: "A repository without pyproject.toml had no file in which to persist these settings; sdd/config.json is already the committed, language-neutral team file and .parrot/ is git-ignored in target repositories."
    rejected_alternatives: ["a new parrot.toml at the repository root", ".parrot/config.toml (git-ignored by the installer; conflicts with FEAT-802)", "per-key merging across files"]
  - id: path-loaded-readers-do-not-import-parrot
    statement: native_artifacts.py, the test_scope kernel and native_claude_sandbox.py read their sdd/config.json block with the standard library and never import parrot.sdd.config; SddConfig is the schema authority and a parity test keeps the readers aligned with it.
    relation: forbids
    about: [sdd-tooling, dev-loop]
    targets: [file:packages/ai-parrot/src/parrot/flows/dev_loop/native_artifacts.py, file:packages/ai-parrot/src/parrot/flows/dev_loop/test_scope/runners/registry.py, file:packages/ai-parrot/src/parrot/sdd/scripts/native_claude_sandbox.py]
    contradicts: []
    supersedes: []
    rationale: "The kernel is stdlib-only and vendored; native_artifacts is loaded by path so it never depends on the compiled artifacts it provides; the sandbox module also runs as a script."
    rejected_alternatives: ["a shared parrot.sdd.repo_settings module imported by all three"]
  - id: toolchain-steps-come-from-profiles
    statement: Format, lint and type-check commands used by the engine and by shipped prompts are obtained from parrot.sdd.toolchain profiles (detected from marker files, overridable in sdd/config.json); a step a repository does not configure is skipped and never fails a gate.
    relation: constrains
    about: [sdd-tooling, dev-loop]
    targets: [file:packages/ai-parrot/src/parrot/flows/dev_loop/sdd_coder/lint.py]
    contradicts: []
    supersedes: []
    rationale: "Tests were already indirected (test_command, runner registry) while lint, format and type-check named ruff, black and mypy; sdd-qa failed every repository without them."
    rejected_alternatives: ["lint_command / format_command / typecheck_command strings in sdd/config.json", "prompts read sdd/CONVENTIONS.md only"]
  - id: worktree-setup-failure-blocks
    statement: A declared worktree setup command that fails stops worktree creation (ensure exits non-zero; the pool raises for that worker); it is read from the main checkout only and re-runs only when its declared inputs change.
    relation: requires
    about: [sdd-tooling, dev-loop]
    targets: [file:packages/ai-parrot/src/parrot/flows/dev_loop/native_artifacts.py, file:packages/ai-parrot/src/parrot/sdd/scripts/ensure_worktree.py, file:packages/ai-parrot/src/parrot/flows/dev_loop/worktree_manager.py]
    contradicts: []
    supersedes: []
    rationale: "User decision 2026-11-05: a worktree without its dependencies fails later with a less clear error. Unlike the native sync, which never blocks, a setup command is something the repository declared as required."
    rejected_alternatives: ["warn only, like the native artifact sync", "run on create only", "link node_modules from the main checkout"]
```

## Consequences

<!-- decision-audit: input_digest=sha256:72734d825470b643b09fe45291f1b5d503a7edcd75182e1430705d2727aa338b evaluation_digest=sha256:f92e21013647e9fc1c8a1e4470c91ceb7e4acdd8553a51a7dfb0b4e9cd383d9e rules_version=1 status=pass -->

Audit status: `pass` (exit 0)

Findings:
- `potential-conflict` [advisory]; waived_by: not recorded; participants: adr:spec:sdd-non-python-repos#path-loaded-readers-do-not-import-parrot@1, adr:spec:sdd-non-python-repos#sdd-config-json-is-the-settings-home@1; scope: file:packages/ai-parrot/src/parrot/flows/dev_loop/native_artifacts.py, file:packages/ai-parrot/src/parrot/flows/dev_loop/test_scope/runners/registry.py, file:packages/ai-parrot/src/parrot/sdd/scripts/native_claude_sandbox.py; message: adr:spec:sdd-non-python-repos#path-loaded-readers-do-not-import-parrot (forbids) and adr:spec:sdd-non-python-repos#sdd-config-json-is-the-settings-home (constrains) govern overlapping scope
- `potential-conflict` [advisory]; waived_by: not recorded; participants: adr:spec:sdd-non-python-repos#path-loaded-readers-do-not-import-parrot@1, adr:spec:sdd-non-python-repos#worktree-setup-failure-blocks@1; scope: file:packages/ai-parrot/src/parrot/flows/dev_loop/native_artifacts.py; message: adr:spec:sdd-non-python-repos#path-loaded-readers-do-not-import-parrot (forbids) and adr:spec:sdd-non-python-repos#worktree-setup-failure-blocks (requires) govern overlapping scope

Diagnostics:
- none

Coverage:
- Subsystems: bots, clients, config, dev-loop, flows, knowledge-graphindex, knowledge-wiki, memory, sdd-tooling, skills, tools
- Unmapped tags: installer, non-python, sdd-config, test-runners, toolchain-profiles, worktree
- Targets resolved: 7/7
- Impact complete: true
- Inventory complete: true
- Omitted ids: not recorded

```json
{
  "coverage": {
    "impact_complete": true,
    "inventory_complete": true,
    "omitted_ids": [],
    "subsystems": [
      "bots",
      "clients",
      "config",
      "dev-loop",
      "flows",
      "knowledge-graphindex",
      "knowledge-wiki",
      "memory",
      "sdd-tooling",
      "skills",
      "tools"
    ],
    "targets_resolved": 7,
    "targets_total": 7,
    "unmapped_tags": [
      "installer",
      "non-python",
      "sdd-config",
      "test-runners",
      "toolchain-profiles",
      "worktree"
    ]
  },
  "diagnostics": [],
  "evaluation_digest": "sha256:f92e21013647e9fc1c8a1e4470c91ceb7e4acdd8553a51a7dfb0b4e9cd383d9e",
  "exit_code": 0,
  "findings": [
    {
      "blocking": false,
      "fingerprint": "sha256:7c5c055079ccf037756ca737a632aaa1fcfe5086bb02bead0f1199d68240fd5f",
      "kind": "potential-conflict",
      "message": "adr:spec:sdd-non-python-repos#path-loaded-readers-do-not-import-parrot (forbids) and adr:spec:sdd-non-python-repos#sdd-config-json-is-the-settings-home (constrains) govern overlapping scope",
      "participants": [
        {
          "decision_id": "adr:spec:sdd-non-python-repos#path-loaded-readers-do-not-import-parrot",
          "revision": 1
        },
        {
          "decision_id": "adr:spec:sdd-non-python-repos#sdd-config-json-is-the-settings-home",
          "revision": 1
        }
      ],
      "rule_version": 1,
      "scope": [
        "file:packages/ai-parrot/src/parrot/flows/dev_loop/native_artifacts.py",
        "file:packages/ai-parrot/src/parrot/flows/dev_loop/test_scope/runners/registry.py",
        "file:packages/ai-parrot/src/parrot/sdd/scripts/native_claude_sandbox.py"
      ],
      "waived_by": null
    },
    {
      "blocking": false,
      "fingerprint": "sha256:8d9f67ff6e5c498f19a4d5f6aad73b4b1cdca058250213e890cdc4f296e6cbf7",
      "kind": "potential-conflict",
      "message": "adr:spec:sdd-non-python-repos#path-loaded-readers-do-not-import-parrot (forbids) and adr:spec:sdd-non-python-repos#worktree-setup-failure-blocks (requires) govern overlapping scope",
      "participants": [
        {
          "decision_id": "adr:spec:sdd-non-python-repos#path-loaded-readers-do-not-import-parrot",
          "revision": 1
        },
        {
          "decision_id": "adr:spec:sdd-non-python-repos#worktree-setup-failure-blocks",
          "revision": 1
        }
      ],
      "rule_version": 1,
      "scope": [
        "file:packages/ai-parrot/src/parrot/flows/dev_loop/native_artifacts.py"
      ],
      "waived_by": null
    }
  ],
  "input_digest": "sha256:72734d825470b643b09fe45291f1b5d503a7edcd75182e1430705d2727aa338b",
  "snapshot": {
    "approvals_digest": "6e5b5a5fb07d04ec7e7cdbf3afac1a634711ea195aa4061a8261bcf61b19992f",
    "config_digest": "sha256:a6bce9c0800713c30eaa78146ad0c06399f6ec0e9b083129e494abb6fd073343",
    "inventory": {
      "adr:doc:171b17ccd26bdbd2d71040746b22371a335d364d": "b22c79daae2a187f2091ea23449825e8769e2c07",
      "adr:doc:34394c36f5bf140678b8e17d43c3628e3d2c1440": "3fa15352d0e9ed972bd5de7ac1fd60e06906e60b",
      "adr:doc:666d8f740c695673063f76777db7b7b0e9d95a2e": "47f1bebe56724843f6c0981f67bbba72917b4b0b",
      "adr:doc:87781d348dff80cbfb25c253989a8940badd08d1": "49458f64f4bb614a9ff42750b53d9caa806f81a0",
      "adr:doc:89e808b78adee5c727e047ac239817bfd29e5cfe": "9feeb90ec52cb53395d978a3b946323a7b9072ab",
      "adr:doc:96dabb33251cd210186d7ab5c456ded102a4b025": "b537050f62f77a85b651af8c2595f4dc7fd4cebe",
      "adr:doc:c3c29b415ba46e730ee37c6fc520914a1905d022": "0cd9cc9f082b9d988da023e3886d310f8eed8eae",
      "adr:doc:c6b0e17a26d4b1ae2be8569a33db9a3aeedc0fbd": "804496ec336c99570df5502580ff980a38f56bfc",
      "adr:doc:e7c5ae770b06db3b35cdd4cba93001a58bfa7bef": "394f4656c71618a256427d81350fdc32335fa791"
    },
    "rules_version": 1,
    "structural_revision": "sha256:101eab3c4f699fb7088f4eb90d331f845b28d37e44227e470e9065a2f6e8af52",
    "taxonomy_digest": "9887c26aa37a5daa626531f2ef465c9f7ef63adf1a9d890eb248ea33c0053dbd"
  },
  "status": "pass"
}
```

## 8. Open Questions

- [x] Where must the configuration that today lives only in `pyproject.toml` live? — *Resolved in
  proposal*: "sdd/config.json (Recomendado)" — extend `SddConfig`; `pyproject.toml` stays as a fallback.
- [x] What scope should the work cover? — *Resolved in proposal*: "Todo, por fases (Recomendado)". This
  spec is phases 1 and 2.
- [x] How does a non-Python repository declare lint, format and type-check? — *Resolved in proposal*:
  "Perfiles autodetectados".
- [x] How does a new worktree get its dependencies? — *Resolved in proposal*: "Comando de setup
  declarado (Recomendado)".
- [x] Where do runner settings live? — *Resolved during `/sdd-spec`*: "Bloque runners en sdd/config.json
  (Recomendado)".
- [x] Can a detected profile be overridden or scoped by path? — *Resolved during `/sdd-spec`*:
  "Detección + override opcional (Recomendado)".
- [x] When does the setup command re-run, and does its failure block? — *Resolved during `/sdd-spec`*:
  "Al crear y si cambia el lockfile; el fallo bloquea (Recomendado)".
- [ ] How does the contract probe become language-aware? — *Owner: Jesus Lara*. Phase 3; does not block
  this spec. Options: a) a command table keyed by file extension inside the probe prompt; b) delegate to
  `wikitoolkit symbols`; c) a small capability table provided by the toolchain profile (suffixes,
  symbol / outline / absence templates) with fixed, safe command templates and an explicit fallback when
  a profile has no symbol support (design research S11).
- [ ] Should `sandbox.mode` be read from the primary checkout instead of the root its caller passes? —
  *Owner: Jesus Lara*. Today the worktree's `pyproject.toml` is read and only `off` / `legacy` are
  refused, so a sandboxed session can lower `required` to `preferred` for a later launch. This spec keeps
  that behaviour for `sdd/config.json`; moving it is a one-line change at the two call sites
  (`native_claude_sandbox.py:452`, `:856`) (design research S1).
- [ ] Should `parrot sdd install` seed `runners` and `worktree.setup` from the detected profile instead of
  only printing it? — *Owner: Jesus Lara*. Deferred: Module 11 prints; seeding can follow once the
  detection has been used on real repositories.

---

## 9. Design Research Cross-Check

> Independent design opinion from the `codex` seat over the **accepted exploration doc** (never over
> this spec). Model: `gpt-5.6-luna` · Status: completed · Transcript:
> `sdd/state/FEAT-805/design_research/`
> All 26 cited paths passed the containment and existence checks.

| # | Suggestion (kind) | Disposition | Reason | Landed in |
|---|---|---|---|---|
| S1 | Separate primary-checkout configuration from worktree configuration (risk) | CONFIRM | Each reader's checkout is now an explicit table and a tamper test covers launch policy and the setup command. Moving `sandbox.mode` to the primary is a behaviour change left to the owner. | §2 Overview, §4, §8 (mode root) |
| S2 | Version and strongly type the new config blocks (api) | CONFIRM | Typed nested models were already the design; runner `cwd` containment is now validated. The schema-version half is not adopted: every released parrot forbids unknown keys, a version key included, so it cannot help the skew it targets. | §3 M1, §7 |
| S3 | Represent host setup as argv rather than a shell string (risk) | CONFIRM | Same model as `NativeGroup.build`: argv, relative `cwd`, bounded timeout, no shell; `cwd` and `inputs` reject absolute and `..` paths. | §2 Data Models, §3 M1, M4 |
| S4 | Define setup state and failure semantics separately from native sync (architecture) | CONFIRM | Separate `SetupReport` and fingerprint; the step runs outside the native-sync `try`; tests added for command change, native-sync failure and the skip switches. | §3 M4, §4 |
| S5 | Unify normal and verdict test execution paths (testing) | CONFIRM | One helper computes argv and working directory for both modes, with pytest, vitest and cargo regressions. Process supervision, deadlines and report parsing stay per mode: merging them is a larger refactor of gate code than this feature needs. | §2 Overview, §3 M6, §4 |
| S6 | Make profiles feed the runner registry instead of a second execution model (alternative) | CONFIRM | Profiles never run tests; `STEPS` has no `test`; adapters stay the only test execution path. Profiles cover fix / format / lint / typecheck, which the registry does not model. | §2 Overview |
| S7 | Resolve profiles per configured root (architecture) | CONFIRM | Already the design (root, runner `cwd`, override roots); the unique file-to-profile rule is now stated and tested for two kinds at one root. | §2 Overview, §4 |
| S8 | Make the vitest package manager part of the adapter contract (api) | CONFIRM | Precedence changed to setting → `packageManager` → lockfile; an unsupported manager fails `validate_settings`. | §3 M5, M7, §4 |
| S9 | Extend the engine boundary beyond the Python-only lint implementation (architecture) | CONFIRM | The profile pass contract now states suffix selection, bounded commands, commit behaviour and that it reports no residuals. Verified: `check_banned_imports` (`fidelity.py:88-100`) returns nothing without `.py` files, so it does not gate foreign tasks; it stays Python-only. | §2 Overview, §3 M9 |
| S10 | Turn the wheel-only foreign-repository harness into the Node acceptance fixture (testing) | CONFIRM | The scenarios move into `test_wheel_only_foreign_repo.py`; no separate test file. | §3 M12, §4, §6 |
| S11 | Make contract probing consume profile capabilities (architecture) | ESCALATE | The probe is phase 3, outside this spec; recorded as option c) of the open question. | §8 (contract probe) |
| S12 | Expand asset parity checks to every changed host twin (testing) | CONFIRM | `scripts/sdd/check_asset_sync.py` is the gate; the task confirms it covers the eight twins and the parity suites join the Validation Contract. | §3 M10, §4, §5 |

Summary: **11** confirmed · **0** rejected · **1** escalated.

---

## Worktree Strategy

- **Isolation**: one feature worktree for FEAT-805; the `sdd-coder` engine gives each task its own
  sub-worktree inside it.
- **Module dependency graph**:
  - M2 → M1, M3 → M1, M5 → M1: each reader's tests use the typed block and the shared `full_config`
    fixture from M1.
  - M4 → M3: `run_worktree_setup` consumes `NativeManifest.setup`.
  - M7 → M1: `detect_profiles` reads `SddConfig.toolchain` and `SddConfig.runners`.
  - M8 → M7, M9 → M7, M11 → M7: all import `parrot.sdd.toolchain`.
  - M10 → M8: the prompts name the verbs.
  - M12 → M1–M11: the guide and the end-to-end test describe the finished behaviour.
  - M6 has no edge: it can start immediately, in parallel with M1.
- **Shared files**: `native_artifacts.py` (M3, M4 — serialized by their edge); `installer.py` and
  `doctor.py` (M11 only); `select_tests.py` (M6 only).
- **Exclusive resources**: the asset re-sync of installed prompt copies (M10) — `parallel: false`; the
  doc-contract tests touched by M3, M4 and M12.
- **Cross-feature dependencies**: FEAT-802 (`worktree-root-under-parrot`) and FEAT-804
  (`installer-portability-gaps`) must merge first; they edit `config.py`, `installer.py`, `doctor.py` and
  `ensure_worktree.py`, and §6 is re-verified afterwards.

---

## Revision History

| Version | Date | Author | Change |
|---|---|---|---|
| 0.1 | 2026-11-05 | Jesus Lara (with Claude) | Initial draft from the accepted proposal, phases 1 and 2. Design research folded in (11 confirmed, 1 escalated). The decision-audit gate could not be evaluated: `parrot sdd spec consequences` exits 3 with `SNAPSHOT_UNSTABLE: decision inventory changed while reading`, and the same failure reproduces on the already-approved `worktree-root-under-parrot` spec, so "Governing Decisions" and "Consequences" are not rendered and the status stays `draft` until the gate passes. |
| 0.2 | 2026-11-05 | Jesus Lara (with Claude) | Decision-audit gate evaluated: `pass`, two advisory `potential-conflict` findings between this spec's own decisions (they share target files; none contradicts another). The earlier failure was a tool defect, not this spec: nine legacy v1 decision pages in the local wiki plane re-encoded to a different hash; they were re-saved with the current codec. The `toolchain-steps-come-from-profiles` decision no longer targets `sdd/toolchain.py`, which does not exist until Module 7 creates it. |
| 0.3 | 2026-11-06 | Codex | Resolved specification review findings: explicit full-profile mypy targets; guarded Node tool/script fallbacks; Python override routing in the engine and prompts with legacy defaults preserved; typed native groups and positive/negative reader parity. Added regression requirements for all four fixes. |
| 0.4 | 2026-11-06 | Jesus Lara (with Claude) | Review of rev 0.3 against the code; its four fixes are kept. Two corrections: (1) engine and prompt routing for an overridden Python profile is triggered only by a `fix` or `format` override, so a `lint` / `typecheck` / `test` override no longer costs line-scoped formatting and the ruff error report; (2) `ToolchainOverride` gains `lint_takes_files` / `typecheck_takes_files`, and an overridden `lint` / `typecheck` argv runs verbatim unless the override sets the flag, so a path-less command no longer gets "." appended. Tests and acceptance criteria added for both. Decision audit re-rendered. |
