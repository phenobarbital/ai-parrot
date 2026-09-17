---
type: feature
base_branch: dev
---

# Feature Specification: Scoped Test Selection for the SDD Cycle

**Feature ID**: FEAT-563
**Date**: 2026-09-17
**Author**: Jesus Lara (with Claude Opus 5)
**Status**: draft
**Target version**: n/a (dev-loop / SDD tooling, no package version bump)
**Input**: `sdd/proposals/scoped-test-selection.brainstorm.md` (Option B)
**Hard prerequisite**: FEAT-562 (`ci-test-failures-root-cause-remediation`) merged into `dev` before `/sdd-task` runs — see Worktree Strategy.

---

## 1. Motivation & Business Requirements

### Problem Statement

The monorepo has ~2,900 `test_*.py` modules spread over the repo-root `tests/`
(490) and `packages/<dist>/tests` (ai-parrot 1,450; tools 276; formdesigner 226;
integrations 181; server 142; …). Inside the SDD cycle
(`sdd-worker` → `sdd-coder` seat → merge → QA → `/sdd-done`) nothing
*deterministically* bounds what pytest runs:

- `sdd-coder` is only *told* to "Run THIS task's acceptance-criteria tests"
  (`.claude/agents/sdd-coder.md:164`). A seat that is unsure runs
  `pytest packages/ai-parrot/tests` (~9 min) or a bare `pytest`.
- `qa-runner` runs a full-suite "sanity" pass on every feature
  (`.claude/agents/qa-runner.md:67`); `sdd-autopilot.md:568` does the same.
- The only deterministic scoping — `QANode._pytest_targets` — is private to the
  dev-loop `QANode` and falls back to a bare `pytest` when nothing maps
  (`nodes/qa.py:579`).
- `validation_commands` exists only inside the optional `DelegationPacket` and
  is never executed.
- No `integration`/`e2e` directory marking, no xdist usage, no per-tier policy.

Validation wall-clock dominates attempts, retries multiply it, and huge pytest
outputs burn seat tokens.

### Goals

- G1 — A **deterministic test-scope kernel** that turns (changed files, worktree,
  tier, policy) into per-distribution pytest invocations. No LLM involved.
- G2 — A **test pyramid by phase**: `task` → `merge` → `feature` → CI. Full suite
  and e2e run **only in CI**.
- G3 — Task-tier validation of a typical 1–4 file task finishes in **< 60 s**.
- G4 — **Enforcement at the exec point** of every seat that allows it: over-broad
  pytest is **rewritten** to the scoped plan (MCP seats, native Claude seat);
  **denied with the exact scoped command** where rewriting is impossible (codex).
  When the scoped plan is empty the command is **blocked** with guidance.
- G5 — A **mandatory, file-level `## Validation Commands`** section in every task
  file produced by `/sdd-task`, linted by `check_task_graph.py`.
- G6 — Directory-based `integration`/`e2e` markers, excluded **only in
  agent-issued commands**; humans and CI keep seeing everything.
- G7 — Merge-tier **import-impact selection** from an own AST import scanner over
  the worktree, with a per-distribution cap that escalates to the package suite.
- G7b — **Core-change escalation**: a change to a *core* source module (transitive
  source fan-in ≥ threshold, default **50**, or listed in `CORE_PATHS`) escalates to
  the full suites of **every distribution whose source imports it**, at the merge and
  feature tiers — **paid once per feature** (deduplicated by content hash of the core
  files), never at the task tier.
- G8 — `pytest -n auto` only for distributions on an explicit xdist-safe allowlist.
- G9 — **Guiding principle: cost proportional to blast radius.** A leaf change pays
  the mirror of directories (today's `QANode` granularity); a core change pays the
  suites of the affected distributions — once. Package suites are never the default
  of any tier; they appear only through core escalation or the impact cap.

### Non-Goals (explicitly out of scope)

- Changing CI selections (`.github/workflows/ci.yml`) — FEAT-562 owns CI. The
  CI gap (`test-core` runs only root `tests/`; most `packages/*/tests` never run
  in CI) is **out of scope** and becomes a separate feature.
- Changing `pytest.ini` / pyproject `addopts` for humans (no global marker exclusion).
- Coverage-based selection (`pytest-testmon`) — rejected in brainstorm (Option D).
- An env-driven `pytest_ignore_collect` plugin (brainstorm Option C) — not built;
  codex stays deny-only.
- `--ignore-user-config` in the `/sdd-spec` §3b design-research seat and in the
  codex *review* profiles — unchanged; only development dispatches drop it.
- wikitoolkit blast radius as a selection source (optional signal at most; not wired).
- Enforcement for `sdd-worker`'s own sequential fallback implementation (no
  per-attempt context exists there — it uses the CLI by instruction only).

---

## 2. Architectural Design

### Overview

**Test-scope kernel** — a new package `parrot/flows/dev_loop/test_scope/` whose
core is **stdlib-only** (dataclasses, `ast`, `shlex`, `pathlib`, `subprocess`)
so the native Claude hook — which runs under the *system* `python3`
(`worktree_environment.py --hook`, stdlib-only imports L7-16) — can import it by
path. Pydantic models live in a separate `test_scope/models.py` used only at the
boundaries (QANode, CLI JSON); `test_scope/__init__.py` MUST NOT import it. This
is a documented exception to "Pydantic for all structured data" (resolved at spec time — §8).

Kernel parts:

1. **Mirror selector** — the existing `QANode._pytest_targets` family moved
   verbatim (behaviour-preserving); `QANode` keeps thin delegating classmethods
   so its 17 existing tests keep passing.
2. **Import-impact selector** — AST scan of every test module's `import` /
   `from … import` statements into a reverse index `dotted module → test files`.
   Changed source files map to dotted modules via `packages/<dist>/src/<top>/…`
   (plus the `parrot.tools.<x>` → `parrot_tools.<x>` redirect). Default depth
   **1 hop** through source modules. Cache keyed by the worktree `HEAD` tree id
   in the per-worktree git admin dir. Used at the `merge` tier only.
2b. **Core detector** — the same AST pass also builds the **source** reverse
   import graph (`src` module → `src` modules importing it). A changed module is
   *core* when its **transitive** source fan-in ≥ `core_fanin_threshold`
   (default **50**) or it matches `CORE_PATHS`. Escalation targets = the package
   suite of the module's own distribution **plus** every distribution whose
   source imports it (e.g. `parrot.clients.base` → `ai-parrot`, `ai-parrot-tools`,
   `ai-parrot-server`, `ai-parrot-integrations`, … as measured). Test-module
   counts are **not** the core signal: tests import concrete classes, not bases
   (measured: `clients/base.py` has 182 source importers but only 37 direct test
   importers; `bots/abstract.py` 146 vs 13 — a test-count cap would never fire).
2c. **Escalation ledger** — `parrot-test-scope-escalations.json` in the
   per-worktree git admin dir maps `distribution → {core file path → blob hash}`
   of the last **green** escalated run. A later merge/feature plan skips an
   escalation whose core files still have the same blob hashes; any content
   change (or a red run) re-arms it.
3. **Policy** — per tier: selectors, marker expression
   `not e2e and not real_llm and not integration`, core escalation (threshold
   **50**, `CORE_PATHS`, ledger dedupe), per-distribution impacted-test cap
   (default **150**) as a secondary escalation trigger,
   xdist allowlist (initially **empty**; populated by a spike), fixed flags
   `-q --tb=short -p no:cacheprovider -o log_cli=false`.
4. **Planner** — groups targets **per distribution** (root `tests/` is its own
   group) and emits one `PytestInvocation` per group; never one invocation that
   spans distributions (config discovery differs: root `pytest.ini` vs
   `packages/<dist>/pyproject.toml`).
5. **Guard core** — detects an over-broad pytest (`pytest` / `python -m pytest`
   / `python3 -m pytest` with no path operand, or an operand equal to `.`,
   `tests`, `packages/<dist>/tests`, or a parent of those) and builds the
   replacement from the task-tier plan.
6. **Attempt context** — a JSON file `parrot-test-scope.json` in the attempt
   sub-worktree's **per-worktree git admin dir** (never the checkout, never the
   common dir, so parallel attempts cannot collide and nothing becomes an
   untracked file). Written by the `sdd-coder` engine for every attempt (MCP
   seats in `_run_attempt`, native seats in `prepare_native`). **The guard is
   active only when this file exists**; outside `sdd-coder` attempts every
   command runs untouched.

**Tiers**

| Tier | Where | Selection | Markers excluded | xdist |
|---|---|---|---|---|
| `task` | every `sdd-coder` attempt (guard) | task `## Validation Commands` targets ∪ mirror of the attempt's changed files — **never escalates** (< 60 s) | yes | no |
| `merge` | `sdd-worker` after each `coder_merge` (CLI) | mirror ∪ import-impact of the merge's changed files; **core change → suites of every importing distribution** (skipped if the ledger shows the same core content already green); impacted tests over cap → package suite | yes | allowlisted dists |
| `feature` | `qa-runner`, `QANode._default_criteria`, `/sdd-done` (CLI / kernel) | **mirror of directories** over every file the feature changed vs its base ∪ the `## Validation Commands` of the feature's tasks (today's `QANode` granularity; no import-impact) ∪ **core escalation** with the same ledger dedupe — so a core change already paid green at merge is not paid again | yes | allowlisted dists |
| `ci` | GitHub Actions | unchanged | no | unchanged |

**User-facing behaviour**

- Task attempts validate in under a minute; merge / feature QA reports list
  which tests ran and why (`declared` / `mirror` / `import` / `core` / `escalated`),
  including which core module triggered an escalation and which escalations were
  skipped because the ledger already had them green.
- MCP seats see the rewrite in the `run_command` tool result `hint`; native
  seats see the rewritten command in their transcript.
- An over-broad pytest with an empty plan is refused: "no scoped tests for this
  attempt — add test paths to the task's `## Validation Commands` or run a
  specific test file".
- Codex seats get a deny whose reason is the exact scoped command to run.
- `/sdd-task` output fails `check_task_graph` without file-level validation commands.
- Humans running pytest and CI are unaffected.

### Component Diagram

```
                      ┌────────────────── test_scope (stdlib core) ─────────────────┐
 changed files ──→    │ mirror ──┐                                                 │
 (git diff + report)  │ impact ──┼──→ policy(tier) ──→ planner ──→ ScopePlan        │
 task.md ──→ contract │──────────┘                        │                        │
 attempt context ──→  │ context                            └──→ guard (broad→rewrite)│
                      └────────────────────────────────────────────────────────────┘
        │                    │                     │                     │
   QANode (feature)   scripts/sdd/select_tests  LLMCodeDispatcher     worktree_environment
   via models.py      CLI (merge/feature,       ._tool_run_command    .hook_response
                      qa-runner, sdd-worker,    (MCP rewrite)         (native rewrite)
                      sdd-done)                                              │
                                                                 tool_optimizations.hooks
   SddCoderEngine._run_attempt / prepare_native ──→ writes context   (codex deny)
   check_task_graph ──→ contract lint
```

### Integration Points

| Existing Component | Integration Type | Notes |
|---|---|---|
| `QANode._default_criteria` / `_pytest_targets` family (`nodes/qa.py:529-717`) | modifies | delegates to kernel; feature tier; **no bare `pytest` fallback** |
| `LLMCodeDispatcher._tool_run_command` (`dispatchers/llm.py:1893`) | modifies | guard rewrite after allowlist/path checks, before `command_policy_error` (L1943) |
| `worktree_environment.hook_response` (`worktree_environment.py:158`) | modifies | guard rewrite of the Bash string before `protected_argv` |
| `tool_optimizations.hooks.main` / `evaluate_shell` (`hooks.py:549`, `:400`) | extends | codex/claude Bash: deny with scoped command |
| `SddCoderEngine._run_attempt` (`engine.py:1897`) / `prepare_native` (`engine.py:1225`) | modifies | write attempt context after sub-worktree creation |
| `CodexCodeDispatchProfile.ignore_user_config` (`models/codex.py:23`) / `CodexCodeDispatcher._build_command` (`dispatchers/codex.py:341`, flag at L379-380 and L442-443) | modifies | development dispatches stop passing `--ignore-user-config` (default → `False`); review profiles keep `True` explicitly |
| `.gitignore:363-366`, `.codex/hooks.json` | modifies | `.codex/hooks.json` becomes tracked (`!.codex/hooks.json`) with a portable launcher command, so every worktree carries the codex hook |
| `scripts/sdd/check_task_graph.py` (`check_graph` L176, `Finding` L50) | extends | contract lint codes |
| `sdd/templates/task.md`, `.claude/commands/sdd-task.md`, `.agent/workflows/sdd-task.md` | modifies | mandatory `## Validation Commands` |
| `.claude/agents/{sdd-coder,sdd-worker,qa-runner,sdd-autopilot}.md`, `.claude/commands/sdd-done.md`, `.agent/workflows/sdd-done.md` | modifies | tier CLI replaces prose and full-suite passes |
| `tests/conftest.py`, `packages/*/tests/conftest.py`, `pytest.ini`, per-dist `[tool.pytest.ini_options]` | extends | directory markers + `e2e` registration, on top of FEAT-562 registrations |

### Data Models

```python
# test_scope/core types — stdlib dataclasses (importable from the system-python hook)
@dataclass(frozen=True)
class TestTarget:
    path: str            # repo-relative file, dir or node id
    distribution: str    # "<dist>" or "root"
    reason: str          # "declared" | "mirror" | "import" | "core" | "escalated"

@dataclass(frozen=True)
class PytestInvocation:
    distribution: str
    argv: tuple[str, ...]        # full argv starting with "pytest"
    targets: tuple[TestTarget, ...]

@dataclass(frozen=True)
class ScopePlan:
    tier: str                    # "task" | "merge" | "feature"
    invocations: tuple[PytestInvocation, ...]
    escalated: tuple[str, ...]   # distributions escalated (core or cap)
    core_hits: tuple["CoreHit", ...]   # core modules that triggered escalation
    skipped_escalations: tuple[str, ...]  # distributions skipped: ledger already green for same content
    notes: tuple[str, ...]       # index-build skips, missing declared paths, …

@dataclass(frozen=True)
class CoreHit:
    path: str                    # changed core source file
    module: str                  # dotted name
    fanin: int                   # transitive source importers
    forced: bool                 # matched CORE_PATHS
    distributions: tuple[str, ...]   # escalation targets

@dataclass(frozen=True)
class LedgerEntry:
    distribution: str
    core_blobs: dict[str, str]   # core file path → git blob hash of the last green escalated run

@dataclass(frozen=True)
class AttemptContext:
    tier: str                    # always "task" for sdd-coder attempts
    task_id: str
    task_file: str               # repo-relative
    base_ref: str                # feature branch the attempt diffs against

# test_scope/models.py — Pydantic mirrors for boundaries (QANode, CLI --json)
class TestTargetModel(BaseModel): ...
class PytestInvocationModel(BaseModel): ...
class ScopePlanModel(BaseModel):
    @classmethod
    def from_plan(cls, plan: ScopePlan) -> "ScopePlanModel": ...
```

### New Public Interfaces

```python
# parrot/flows/dev_loop/test_scope/__init__.py (stdlib only)
def plan_tests(*, worktree: Path, changed_files: Sequence[str], tier: str,
               declared: Sequence[Sequence[str]] = (), policy: ScopePolicy | None = None) -> ScopePlan: ...
def rewrite_broad_pytest(argv: Sequence[str], *, worktree: Path) -> GuardOutcome: ...
def parse_validation_commands(task_md: str) -> list[list[str]]: ...
```

```bash
# CLI for markdown agents
python -m scripts.sdd.select_tests --tier {task,merge,feature} [--base origin/dev] \
    [--task-file sdd/tasks/active/TASK-NNN-x.md] [--run] [--json]
```

---

## 3. Module Breakdown

#### Delegation-eligible modules

| Module | Eligible? | Decided patterns / exact contracts | Why not (if no) |
|---|---|---|---|
| M1: kernel core (mirror, policy, planner, contract parser) | yes | skeleton below; mirror logic moved verbatim from `qa.py:588-717` | — |
| M2: import-impact selector | no | — | index/cache format and `parrot.tools` redirect handling need judgment |
| M3: guard core + attempt context | no | — | argv/bash-segment rewrite edge cases |
| M4: Pydantic boundary models + CLI | yes | skeleton below; `argparse`, exit codes 0/1/2 | — |
| M5: QANode integration | yes | delegate + replace bare fallback; update `test_package_without_tests_is_not_a_target` | — |
| M6: MCP seat adapter + engine context writer | no | — | touches hot engine paths; attempt-context timing |
| M7: native hook adapter | no | — | bash string segment rewrite under system python |
| M8: codex deny adapter | no | — | portable hook launcher + verification that codex loads the tracked project hook (S1) |
| M9: task validation contract (template, commands, lint) | yes | section format + lint codes below | — |
| M10: directory markers | yes | directory names + registration list below | — |
| M11: agent/command markdown | yes | exact CLI lines below | — |

### Module 1: Test-scope kernel core
- **Path**: `packages/ai-parrot/src/parrot/flows/dev_loop/test_scope/{__init__.py,mirror.py,policy.py,planner.py,contract.py}`
- **Responsibility**: stdlib-only selection primitives: mirror targets, tier policy, per-distribution planning, `## Validation Commands` parsing. Relative imports only (package must import both as `parrot.flows.dev_loop.test_scope` and, from the hook, as top-level `test_scope`).
- **Depends on**: existing `QANode` helpers (moved)
- **Interface Skeleton**:
  ```python
  # test_scope/mirror.py  (new; logic moved from nodes/qa.py:588-717)
  def pytest_targets(files: Sequence[str], worktree_path: str) -> list[str]:
      """Map changed files to the narrowest existing test targets (moved from QANode._pytest_targets, qa.py:588)."""
  def pytest_target_for(path: str, worktree_path: str) -> str | None:  # verified: qa.py:633
      """Resolve one changed path to its narrowest existing test target."""
  def deepest_existing_dir(tests_root: str, subdirs: tuple[str, ...], worktree_path: str) -> str:  # verified: qa.py:679
      """Walk tests_root/subdirs upwards to the first existing directory."""
  def prune_nested(targets: set[str]) -> list[str]:  # verified: qa.py:703
      """Drop targets already covered by a broader target; sorted."""
  def distribution_of(path: str) -> str:
      """'<dist>' for packages/<dist>/…, 'root' for tests/…; raises ValueError otherwise."""

  # test_scope/policy.py  (new)
  AGENT_MARKER_EXPRESSION: str = "not e2e and not real_llm and not integration"
  AGENT_FLAGS: tuple[str, ...] = ("-q", "--tb=short", "-p", "no:cacheprovider", "-o", "log_cli=false")
  DEFAULT_IMPACT_CAP: int = 150
  DEFAULT_IMPACT_DEPTH: int = 1
  DEFAULT_CORE_FANIN_THRESHOLD: int = 50
  CORE_PATHS: tuple[str, ...] = (  # seed; final list written from spike S4 measurement; always escalate
      "packages/ai-parrot/src/parrot/clients/base.py",     # 182 source importers (measured 2026-09-17)
      "packages/ai-parrot/src/parrot/bots/abstract.py",    # 146 source importers (measured 2026-09-17)
  )
  XDIST_SAFE_DISTRIBUTIONS: frozenset[str] = frozenset()
  TIERS: tuple[str, ...] = ("task", "merge", "feature")

  @dataclass(frozen=True)
  class ScopePolicy:
      """Per-tier knobs; defaults above."""
      impact_cap: int = DEFAULT_IMPACT_CAP
      impact_depth: int = DEFAULT_IMPACT_DEPTH
      core_fanin_threshold: int = DEFAULT_CORE_FANIN_THRESHOLD
      core_paths: tuple[str, ...] = CORE_PATHS
      xdist_safe: frozenset[str] = XDIST_SAFE_DISTRIBUTIONS
      marker_expression: str = AGENT_MARKER_EXPRESSION

  # test_scope/planner.py  (new)
  def build_plan(targets: Sequence[TestTarget], *, tier: str, worktree: Path, policy: ScopePolicy,
                 escalated: Sequence[str] = (), core_hits: Sequence[CoreHit] = (),
                 skipped_escalations: Sequence[str] = (), notes: Sequence[str] = ()) -> ScopePlan:
      """Group by distribution, prune nested, add flags/markers/xdist → one PytestInvocation per group."""

  # test_scope/contract.py  (new)
  VALIDATION_HEADING: str = "## Validation Commands"
  def parse_validation_commands(task_md: str) -> list[list[str]]:
      """Backticked commands under '## Validation Commands' (bullets), shlex-split; [] when absent."""
  def is_broad_pytest(argv: Sequence[str]) -> bool:
      """True for pytest with no path operand or an operand in {., tests, packages/<dist>/tests} or a parent."""

  # test_scope/__init__.py  (new) — stdlib-only re-exports
  def plan_tests(*, worktree: Path, changed_files: Sequence[str], tier: str,
                 declared: Sequence[Sequence[str]] = (), policy: ScopePolicy | None = None) -> ScopePlan:
      """Tier entry point: task=declared∪mirror (no escalation); merge=mirror∪impact∪core escalation (cap→escalate); feature=declared(all tasks)∪mirror∪core escalation; escalations deduped by the ledger."""
  def changed_files(worktree: Path, base_ref: str) -> list[str]:
      """git diff --name-only --diff-filter=d <base>...HEAD ∪ untracked/uncommitted (sync subprocess)."""
  ```

### Module 2: Import-impact selector + core detector
- **Path**: `packages/ai-parrot/src/parrot/flows/dev_loop/test_scope/impact.py`
- **Responsibility**: one AST pass over the worktree builds (a) the reverse import index test-module side and (b) the **source** reverse import graph; maps changed source modules (depth-limited) to test files; computes **transitive source fan-in** and the set of importing distributions per changed module; classifies core (fan-in ≥ threshold or `CORE_PATHS`); cache by `HEAD` tree id in the per-worktree git admin dir; syntax errors → skip module and add a plan note.
- **Depends on**: Module 1
- **Interface Skeleton**:
  ```python
  # test_scope/impact.py  (new)
  def module_name_for(path: str) -> str | None:
      """packages/<dist>/src/<top>/a/b.py → '<top>.a.b'; parrot/tools/<x> also yields 'parrot_tools.<x>' alias."""
  @dataclass
  class ImportIndex:
      """Reverse index: dotted module → repo-relative test files importing it (or a submodule of it)."""
      by_module: dict[str, set[str]]          # module → test files
      src_importers: dict[str, set[str]]      # module → source modules importing it
      module_dist: dict[str, str]             # source module → distribution
      skipped: list[str]
      @classmethod
      def build(cls, worktree: Path) -> "ImportIndex": ...
      @classmethod
      def load_or_build(cls, worktree: Path) -> "ImportIndex":
          """Reuse cache keyed by `git rev-parse HEAD^{tree}` when present."""
  def impacted_tests(index: ImportIndex, changed: Sequence[str], *, worktree: Path, depth: int) -> list[str]:
      """Test files importing a changed module directly, or via ≤ depth source-module hops."""
  def source_fanin(index: ImportIndex, module: str) -> tuple[int, frozenset[str]]:
      """Transitive count of source modules importing `module`, and the distributions they belong to."""
  def detect_core(index: ImportIndex, changed: Sequence[str], *, policy: ScopePolicy) -> list[CoreHit]:
      """CoreHit per changed source file with fan-in ≥ policy.core_fanin_threshold or in policy.core_paths."""
  ```

### Module 3: Guard core + attempt context
- **Path**: `packages/ai-parrot/src/parrot/flows/dev_loop/test_scope/{guard.py,context.py}`
- **Responsibility**: argv guard (rewrite/block), bash-string guard (rewrite only the pytest segment of a parseable command; unparseable → untouched + note), attempt-context and **escalation-ledger** read/write in the per-worktree git admin dir.
- **Depends on**: Module 1
- **Interface Skeleton**:
  ```python
  # test_scope/context.py  (new)
  CONTEXT_FILENAME: str = "parrot-test-scope.json"
  def worktree_git_dir(worktree: Path) -> Path | None:
      """Per-worktree admin dir (the `gitdir:` target, NOT commondir); None outside git."""
  def write_attempt_context(worktree: Path, ctx: AttemptContext) -> Path: ...
  def read_attempt_context(worktree: Path) -> AttemptContext | None:
      """None when absent or malformed — the guard is then inactive."""
  LEDGER_FILENAME: str = "parrot-test-scope-escalations.json"
  def read_ledger(worktree: Path) -> dict[str, LedgerEntry]:
      """Empty when absent or malformed (→ escalations re-run; never silently skipped)."""
  def record_green_escalation(worktree: Path, hit_dists: Sequence[str], core_files: Sequence[str]) -> None:
      """Store current blob hashes (`git hash-object`) of core_files for each distribution after a green run."""
  def pending_escalations(worktree: Path, hits: Sequence[CoreHit]) -> tuple[list[str], list[str]]:
      """(distributions to run, distributions skipped because ledger blobs match current content)."""

  # test_scope/guard.py  (new)
  @dataclass(frozen=True)
  class GuardOutcome:
      action: str                          # "allow" | "rewrite" | "block"
      argvs: tuple[tuple[str, ...], ...]   # replacement invocations when action == "rewrite"
      message: str                         # shown to the seat (hint / deny reason)
  def guard_argv(argv: Sequence[str], *, worktree: Path) -> GuardOutcome:
      """allow when no attempt context or not broad; else task-tier plan → rewrite, or block when empty."""
  def guard_bash(command: str, *, worktree: Path) -> tuple[GuardOutcome, str | None]:
      """Same decision for a bash string; returns the rewritten command (subshell aggregating exit codes) or None."""
  ```

### Module 4: Pydantic boundary models + CLI
- **Path**: `packages/ai-parrot/src/parrot/flows/dev_loop/test_scope/models.py`, `scripts/sdd/select_tests.py`
- **Responsibility**: Pydantic mirrors of `ScopePlan` for QANode/JSON; CLI printing either shell-ready commands or `--json`; `--run` executes invocations sequentially, exits non-zero if any fails, and **records green escalated invocations in the ledger**; exit 2 on usage errors / empty task-tier plan.
- **Depends on**: Modules 1, 2, 3
- **Interface Skeleton**:
  ```python
  # test_scope/models.py  (new — the ONLY test_scope module importing pydantic)
  class TestTargetModel(BaseModel):
      path: str; distribution: str; reason: Literal["declared", "mirror", "import", "core", "escalated"]
  class PytestInvocationModel(BaseModel):
      distribution: str; argv: list[str]; targets: list[TestTargetModel]
  class ScopePlanModel(BaseModel):
      tier: Literal["task", "merge", "feature"]; invocations: list[PytestInvocationModel]
      escalated: list[str] = Field(default_factory=list); notes: list[str] = Field(default_factory=list)
      core_hits: list[CoreHitModel] = Field(default_factory=list); skipped_escalations: list[str] = Field(default_factory=list)
  class CoreHitModel(BaseModel):
      path: str; module: str; fanin: int; forced: bool; distributions: list[str]
      @classmethod
      def from_plan(cls, plan: ScopePlan) -> "ScopePlanModel": ...

  # scripts/sdd/select_tests.py  (new)
  def main(argv: list[str] | None = None) -> int:
      """--tier, --base (default origin/dev), --task-file, --worktree (default cwd), --run, --json."""
  ```

### Module 5: QANode integration
- **Path**: `packages/ai-parrot/src/parrot/flows/dev_loop/nodes/qa.py` (modifies L529-717)
- **Responsibility**: `_default_criteria` builds a `feature`-tier plan — **the same mirror-of-directories selection it computes today**, plus **core escalation** (suites of importing distributions, deduped by the ledger), split per distribution and carrying agent flags/markers — and emits one `ShellCriterion` per invocation; after the `QAReport` returns, escalated criteria that passed are recorded in the ledger; an empty plan yields **no** criterion (log warning) instead of bare `pytest`. `_pytest_targets` & co. become one-line delegations to `test_scope.mirror`.
- **Depends on**: Modules 1, 2, 3, 4
- **Interface Skeleton**:
  ```python
  # nodes/qa.py  (modifies)
  async def _default_criteria(self, shared: Dict[str, Any], research: ResearchOutput) -> List[AcceptanceCriterion]:  # verified: qa.py:529
      """Feature-tier ScopePlan → one ShellCriterion per PytestInvocation; [] when the plan is empty."""
  @classmethod
  def _pytest_targets(cls, files: List[str], worktree_path: str) -> List[str]:  # verified: qa.py:588
      """Delegates to test_scope.mirror.pytest_targets (kept for existing tests)."""
  ```
  `test_package_without_tests_is_not_a_target` (`test_qa_default_criteria.py:95-109`, asserts `== "pytest"`) is updated to assert no pytest criterion.

### Module 6: MCP seat adapter + engine context writer
- **Path**: `dispatchers/llm.py` (modifies `_tool_run_command` L1893-1950), `sdd_coder/engine.py` (modifies `_run_attempt` L1897 after `manager.create`, ~L2036)
- **Responsibility**: engine writes `AttemptContext(tier="task", task_id, task_file, base_ref=<feature branch>)` for every MCP attempt right after the sub-worktree exists; `_tool_run_command` calls `guard_argv` after the allowlist + `_validate_command_paths` checks and before `command_policy_error`; `rewrite` → run each replacement invocation sequentially via `_run_argv`, concatenate output, `exit_code` = first non-zero, `hint` = guard message; `block` → `{"ok": False, "stderr": message}` without executing.
- **Depends on**: Module 3
- **Interface Skeleton**:
  ```python
  # dispatchers/llm.py  (modifies)
  async def _tool_run_command(self, cwd: str, args: Dict[str, Any], profile: LLMCodeDispatchProfile) -> Dict[str, Any]:  # verified: llm.py:1893
      """…existing checks… → guard_argv(argv, worktree=Path(run_cwd)) → rewrite/block/allow → _run_argv."""
  async def _run_guarded_invocations(self, argvs: Sequence[Sequence[str]], *, cwd: str, timeout: int, hint: str) -> Dict[str, Any]:
      """Run replacement invocations in order; merged stdout/stderr; first non-zero exit wins."""
  ```

### Module 7: Native hook adapter
- **Path**: `worktree_environment.py` (modifies `hook_response` L158-180), `sdd_coder/engine.py` (modifies `prepare_native` L1225)
- **Responsibility**: `prepare_native` writes the attempt context into the native sub-worktree; `hook_response` imports `test_scope` via its own directory on `sys.path` (stdlib only), calls `guard_bash(command, worktree=cwd)` **before** `protected_argv`; `rewrite` → wrap the rewritten command; `block` → `permissionDecision: deny` with the message; import failure of `test_scope` → guard skipped (never breaks the sandbox wrapper).
- **Depends on**: Module 3
- **Interface Skeleton**:
  ```python
  # worktree_environment.py  (modifies)
  def hook_response(payload: dict[str, Any]) -> dict[str, Any]:  # verified: worktree_environment.py:158
      """Bash: guard_bash → (deny | rewritten command) → protected_argv wrap (L169-171). File tools unchanged."""
  def _scope_guard(command: str, cwd: Path) -> tuple[str, str | None]:
      """('allow'|'rewrite'|'block', rewritten-or-message); swallows ImportError → ('allow', None)."""
  ```

### Module 8: Codex deny adapter
- **Path**: `packages/ai-parrot-tools/src/parrot_tools/tool_optimizations/hooks.py` (extends `main` L549 Bash branch), `.gitignore` (L363-366), `.codex/hooks.json` (becomes tracked), `scripts/sdd/codex_hook.sh` (new launcher), `packages/ai-parrot/src/parrot/flows/dev_loop/models/codex.py` (`ignore_user_config` default), `CodexCodeReviewProfile` / `CodexAdversarialReviewProfile` (explicit `True`)
- **Responsibility**:
  1. In the Bash branch, when an attempt context exists and the command contains an over-broad pytest, produce a deny `GuardDecision` whose reason is the exact scoped command (joined invocations).
  2. **Track `.codex/hooks.json`**: add `!.codex/hooks.json` after `.codex/*` in `.gitignore`, and replace the machine-specific absolute interpreter path (`/home/<user>/…/.venv/bin/python`) with a tracked, portable launcher `scripts/sdd/codex_hook.sh` that resolves the main checkout via `git rev-parse --path-format=absolute --git-common-dir` and execs `<main-checkout>/.venv/bin/python -m parrot_tools.tool_optimizations.hooks --host codex`; a missing venv → exit 0 silently (never break codex).
  3. **Drop `--ignore-user-config` for development dispatches**: `CodexCodeDispatchProfile.ignore_user_config` default becomes `False` (field kept, still honoured at `codex.py:379-380` / `:442-443`); the review profiles set `ignore_user_config: bool = True` explicitly so reviewers keep an isolated config. `--model`, sandbox and approval policy are already passed explicitly (`codex.py:432`, `:372-373`), so the operator config cannot swap them.
  4. Spike S1 verifies with a real `codex exec --cd <attempt sub-worktree>` that the tracked project hook fires and denies.
- **Depends on**: Module 3
- **Interface Skeleton**:
  ```python
  # tool_optimizations/hooks.py  (extends)
  def evaluate_scope(command: str, cwd: Path) -> Optional[GuardDecision]:
      """Deny over-broad pytest inside an sdd-coder attempt; reason = scoped command; None otherwise."""
  # main(): Bash branch → evaluate_scope first, then evaluate_shell (verified: hooks.py:577-578)

  # models/codex.py  (modifies)
  class CodexCodeDispatchProfile(BaseModel):  # verified: models/codex.py:10
      ignore_user_config: bool = Field(default=False, ...)  # was True (L23)
  class CodexCodeReviewProfile(CodexCodeDispatchProfile):  # verified: models/codex.py:38
      ignore_user_config: bool = True  # explicit — reviewers stay isolated
  ```
  ```json
  // .codex/hooks.json  (tracked)
  {"hooks": {"PreToolUse": [{"matcher": "Bash", "hooks": [{"type": "command", "command": "sh scripts/sdd/codex_hook.sh", "timeout": 10}]}]}}
  ```
  Tests to update: `test_codex_dispatcher.py:177`, `test_codex_command_variants.py:74` (assert flag absent by default), `test_models.py:150` (`is False`), plus review-profile assertions (`is True`).

### Module 9: Task validation contract
- **Path**: `sdd/templates/task.md`, `.claude/commands/sdd-task.md`, `.agent/workflows/sdd-task.md`, `scripts/sdd/check_task_graph.py`, `sdd/templates/*` index header docs
- **Responsibility**: new mandatory section placed right after `## Acceptance Criteria` (template L266):
  ```markdown
  ## Validation Commands
  - `pytest packages/ai-parrot/tests/flows/dev_loop/test_test_scope_mirror.py -q`
  - `pytest tests/sdd_scripts/test_select_tests.py::test_task_tier -q`
  ```
  Only `pytest` commands whose operands are files or node ids. `/sdd-task` writes
  `"validation_contract": "required"` into new index headers. Lint codes:
  `missing-validation-commands` (error when header requires it, warning otherwise),
  `broad-validation-command` (error — `is_broad_pytest`), `directory-validation-target`
  (error — operand is a directory), `validation-path-unknown` (warning — path neither
  exists nor is declared in `## Files to Create / Modify`).
- **Depends on**: Module 1 (`parse_validation_commands`, `is_broad_pytest`)
- **Interface Skeleton**:
  ```python
  # scripts/sdd/check_task_graph.py  (extends)
  VALIDATION_CONTRACT: str = "required"
  def _check_validation_contract(tasks: dict[str, _Task], root: Path, required: bool) -> list[Finding]:  # Finding verified: check_task_graph.py:50
      """Emit the four validation-contract findings per task."""
  ```

### Module 10: Directory markers
- **Path**: `tests/conftest.py`, `packages/{ai-parrot,parrot-formdesigner,ai-parrot-server}/tests/conftest.py`, `pytest.ini`, affected `packages/<dist>/pyproject.toml` `[tool.pytest.ini_options]`
- **Responsibility**: `pytest_collection_modifyitems` adds `integration` to items under a path segment named exactly `integration`, and `e2e` under `e2e`. **`integrations/` directories are NOT marked** (they hold unit tests of integration packages, e.g. `packages/ai-parrot-integrations/tests/integrations`, 87 modules). Register `e2e` (and `integration` where missing) wherever strict markers apply, extending — never duplicating — FEAT-562's registrations.
- **Depends on**: none (FEAT-562 merged)
- **Interface Skeleton**:
  ```python
  # <dist>/tests/conftest.py  (extends; hook may already exist, e.g. packages/ai-parrot/tests/conftest.py:15)
  def pytest_collection_modifyitems(config: pytest.Config, items: list[pytest.Item]) -> None:
      """Existing marker-skip logic + directory auto-marking (integration/, e2e/)."""
  ```

### Module 11: Agent & command markdown
- **Path**: `.claude/agents/{sdd-coder,sdd-worker,qa-runner,sdd-autopilot}.md`, `.claude/commands/sdd-done.md`, `.agent/workflows/sdd-done.md`
- **Responsibility**:
  - `qa-runner.md:61-67` — delete the full-suite pass; step becomes `python -m scripts.sdd.select_tests --tier feature --base origin/dev --run`.
  - `sdd-autopilot.md:567-568` — delete "`pytest --tb=short` for a quick full-suite sanity check".
  - `sdd-coder.md:164` — "Run the commands under your task's `## Validation Commands`; broad pytest is rewritten/blocked by the harness."
  - `sdd-worker.md` (after each `coder_merge`, and its fallback lane) — `python -m scripts.sdd.select_tests --tier merge --base <feature-branch-merge-base> --run`.
  - `sdd-done` — touched-module step uses `--tier feature --run`.
- **Depends on**: Module 4 (CLI exists). The full-suite deletions have no dependency and may land first.

---

## 4. Test Specification

### Unit Tests
| Test | Module | Description |
|---|---|---|
| `test_mirror_parity_with_qanode_fixtures` | M1 | the 17 `test_qa_default_criteria.py` scenarios produce identical targets via `test_scope.mirror` |
| `test_plan_groups_per_distribution` | M1 | targets in two dists + root → three invocations, never one spanning dists |
| `test_plan_flags_and_marker_expression` | M1 | every argv carries `AGENT_FLAGS` and `-m AGENT_MARKER_EXPRESSION` |
| `test_xdist_only_for_allowlisted_dist` | M1 | `-n auto` present iff dist ∈ `xdist_safe` |
| `test_parse_validation_commands` | M1 | bullets with backticks parsed; absent section → `[]` |
| `test_is_broad_pytest_matrix` | M1 | bare, `.`, `tests`, `packages/x/tests`, `python -m pytest` broad; files/node ids/subdirs not |
| `test_core_is_stdlib_only` | M1/M3 | importing `test_scope` in a subprocess with `-I -S`-style isolated path (no site-packages) succeeds |
| `test_module_name_for_src_layout_and_tools_redirect` | M2 | path → dotted name, `parrot.tools.x` alias |
| `test_impacted_tests_direct_and_one_hop` | M2 | direct importer found; 2-hop importer excluded at depth 1 |
| `test_cap_escalates_to_package_suite` | M2/M1 | > cap impacted files → dist escalated, plan note |
| `test_core_detected_by_source_fanin_not_test_count` | M2 | module with fan-in ≥ threshold but few test importers → CoreHit |
| `test_core_paths_force_escalation` | M2 | low fan-in file listed in `CORE_PATHS` → CoreHit(forced=True) |
| `test_core_escalates_every_importing_distribution` | M2/M1 | core module imported from dists a,b → package suites for a and b |
| `test_task_tier_never_escalates` | M1 | core change at task tier → declared ∪ mirror only |
| `test_ledger_skips_green_same_content` | M3 | green escalation recorded; unchanged blobs → skipped at next merge/feature plan |
| `test_ledger_rearms_on_content_change_or_red` | M3 | changed blob or failed run → escalation planned again |
| `test_qanode_records_green_escalations` | M5 | passed escalated criteria written to the ledger |
| `test_index_skips_syntax_errors` | M2 | broken test module skipped, listed in notes |
| `test_context_in_per_worktree_gitdir` | M3 | written under `gitdir:` target, not commondir, not checkout |
| `test_guard_inactive_without_context` | M3 | broad pytest allowed when no context file |
| `test_guard_rewrites_to_declared_and_mirror` | M3 | broad pytest → declared ∪ mirror invocations |
| `test_guard_blocks_empty_plan` | M3 | broad pytest, nothing declared/mapped → `block` |
| `test_guard_bash_compound_and_unparseable` | M3 | `cd x && pytest` rewritten segment; heredoc/unparseable → allow + note |
| `test_cli_json_and_exit_codes` | M4 | `--json` validates as `ScopePlanModel`; `--run` exit code propagation; empty task plan exit 2 |
| `test_empty_feature_plan_derives_no_criterion` | M5 | replaces bare `pytest` assertion |
| `test_run_command_rewrites_broad_pytest` | M6 | `_tool_run_command` runs replacement invocations, `hint` set |
| `test_run_command_blocks_without_exec` | M6 | block returns `ok: False`, `_run_argv` not awaited |
| `test_engine_writes_attempt_context` | M6/M7 | `_run_attempt` and `prepare_native` write context with task_file/base_ref |
| `test_hook_response_rewrites_before_sandbox` | M7 | `updatedInput.command` wraps the rewritten command |
| `test_hook_response_import_failure_is_allow` | M7 | missing `test_scope` → unchanged behaviour |
| `test_codex_hook_denies_broad_pytest_with_scoped_reason` | M8 | deny reason contains the scoped command |
| `test_codex_dev_profile_drops_ignore_user_config` | M8 | dev dispatch argv has no `--ignore-user-config`; review profiles still pass it |
| `test_codex_hooks_json_is_tracked_and_portable` | M8 | `git check-ignore .codex/hooks.json` fails; command contains no absolute `/home/` path |
| `test_feature_tier_equals_mirror_selection` | M1/M5 | feature plan targets == `mirror.pytest_targets` ∪ declared; never a `packages/<dist>/tests` root unless mirror itself fell back to it |
| `test_validation_contract_findings` | M9 | four lint codes, required vs legacy header |
| `test_directory_auto_marking` | M10 | `integration/` and `e2e/` marked; `integrations/` not |

Test locations: `packages/ai-parrot/tests/flows/dev_loop/test_scope/` (M1–M3, M5–M7), `packages/ai-parrot/tests/flows/dev_loop/test_llm_code_dispatcher.py` (M6), `packages/ai-parrot/tests/flows/dev_loop/test_worktree_environment.py` (M7), `packages/ai-parrot/tests/flows/dev_loop/sdd_coder/test_engine_dispatch.py` (M6/M7 context), `packages/ai-parrot-tools/tests/tool_optimizations/test_hooks.py` (M8), `tests/sdd_scripts/test_check_task_graph.py` + `tests/sdd_scripts/test_select_tests.py` (M4, M9).

### Integration Tests
| Test | Description |
|---|---|
| `test_select_tests_on_fixture_monorepo` | tmp git repo with two fake dists + root tests; commit a change; `--tier task/merge/feature` plans match expectations and `--run` executes |
| `test_mcp_attempt_end_to_end_rewrite` | fake LLM seat issues `pytest packages/<dist>/tests` inside an attempt sub-worktree with context → scoped invocations executed |

### Test Data / Fixtures
```python
@pytest.fixture
def fixture_monorepo(tmp_path: Path) -> Path:
    """git-initialised tree: packages/a/{src/pa/x.py,tests/test_x.py}, packages/b/…, tests/test_root.py, pytest.ini."""
```

---

## 5. Acceptance Criteria

- [ ] AC1 — `qa-runner.md` and `sdd-autopilot.md` contain no full-suite pytest invocation (grep for `pytest -q --tb=line` and "full-suite sanity" returns nothing).
- [ ] AC2 — All agent-issued plans carry `-o log_cli=false -p no:cacheprovider -q --tb=short` and `-m "not e2e and not real_llm and not integration"`; `pytest.ini` and pyproject `addopts` are unchanged by this feature.
- [ ] AC3 — `test_scope` core imports with the standard library only (`test_core_is_stdlib_only` passes); only `test_scope/models.py` imports pydantic.
- [ ] AC4 — The 17 existing tests in `test_qa_default_criteria.py` pass (with the single updated fallback assertion); `QANode` never emits a bare `pytest` criterion.
- [ ] AC5 — Inside an `sdd-coder` attempt, an over-broad pytest from an MCP seat or the native seat is **rewritten** to the task-tier plan; with an empty plan it is **blocked**; outside attempts (no context file) commands are untouched.
- [ ] AC6 — Codex seats inside an attempt receive a **deny** whose reason contains the scoped command; `.codex/hooks.json` is tracked with a portable launcher; development codex dispatches no longer pass `--ignore-user-config` (review profiles still do); the hook is verified active in a codex attempt sub-worktree (spike S1 evidence in `artifacts/logs/`).
- [ ] AC7 — `/sdd-task` emits `## Validation Commands` with file-level pytest commands for every task and `"validation_contract": "required"` in the index header; `check_task_graph.py` reports the four new codes as specified, and legacy indexes only warn.
- [ ] AC8 — `integration/` and `e2e/` test directories are auto-marked; `integrations/` directories are not; `pytest --strict-markers` collection succeeds in every touched distribution.
- [ ] AC9 — Merge tier unions mirror and import-impact targets; a distribution over the impacted-test cap (default 150 modules) is escalated to its package suite and listed in `escalated`.
- [ ] AC9b — **Core escalation**: at merge and feature tiers, a change to a module with transitive source fan-in ≥ 50 or listed in `CORE_PATHS` escalates to the suites of every distribution whose source imports it; verified with `bots/abstract.py` and `clients/base.py` on the real tree (plan `--json` saved to `artifacts/logs/feat-563-core-escalation.json`). The task tier never escalates.
- [ ] AC9c — **Paid once**: after a green escalated run, a later merge or feature plan with identical core-file blob hashes lists the distribution under `skipped_escalations` and does not run it; any content change or red run re-arms it.
- [ ] AC10 — `-n auto` appears only for distributions in `XDIST_SAFE_DISTRIBUTIONS`; the allowlist ships with the distributions proven safe by spike S3 (may be empty).
- [ ] AC11 — Plans never contain one invocation spanning two distributions.
- [ ] AC11b — For a change with **no core hit**, the `feature` tier (QANode, qa-runner, `/sdd-done`) selects by mirror of directories ∪ declared validation commands only, and QANode's selected test set is never larger than before this feature (parity test). Package suites appear only through core escalation.
- [ ] AC12 — **Budget**: on a representative 1–4 file task in `packages/ai-parrot`, task-tier validation wall-clock < 60 s (measured, log in `artifacts/logs/feat-563-task-tier-budget.log`).
- [ ] AC13 — All new/changed unit tests pass: `pytest packages/ai-parrot/tests/flows/dev_loop/test_scope/ packages/ai-parrot/tests/flows/dev_loop/test_qa_default_criteria.py packages/ai-parrot/tests/flows/dev_loop/test_worktree_environment.py packages/ai-parrot/tests/flows/dev_loop/test_llm_code_dispatcher.py -q`, `pytest packages/ai-parrot-tools/tests/tool_optimizations/test_hooks.py -q`, `pytest tests/sdd_scripts/test_check_task_graph.py tests/sdd_scripts/test_select_tests.py -q`.
- [ ] AC14 — `ruff check` clean on changed files; `docs/dev_loop/sdd-coder-orchestrator.md` documents tiers, guard behaviour and the CLI.

---

## 6. Codebase Contract

> Re-verified 2026-09-17 against `dev` @ post-brainstorm. **Must be re-verified
> again after FEAT-562 merges** (it changes `pytest.ini`, conftests, marker
> registration and `ci.yml`) before `/sdd-task`.

### Verified Imports
```python
from parrot.flows.dev_loop.nodes.qa import QANode                                  # verified: nodes/qa.py:139
from parrot.flows.dev_loop.models.base import TaskScopedBrief                      # verified: models/base.py:468
from parrot.flows.dev_loop.models.llm import LLMCodeDispatchProfile                # verified: models/llm.py:10
from parrot.flows.dev_loop.models.codex import CodexCodeDispatchProfile            # verified: models/codex.py:10
from parrot.flows.dev_loop.sdd_coder.models import PlannedTask, NativePrep         # verified: sdd_coder/models.py:209, :325
from parrot.flows.dev_loop.sdd_coder.fidelity import parse_task_files              # verified: sdd_coder/fidelity.py:29
from parrot_tools.tool_optimizations.hooks import GuardDecision, render_output     # verified: hooks.py:111, :469
from parrot_tools.tool_optimizations.models import DelegationPacket                # verified: models.py:285
```
(Paths relative to `packages/ai-parrot/src/parrot/flows/dev_loop/` and `packages/ai-parrot-tools/src/parrot_tools/tool_optimizations/`.)

### Existing Class Signatures
```python
# nodes/qa.py
async def _default_criteria(self, shared: Dict[str, Any], research: ResearchOutput) -> List[AcceptanceCriterion]:  # L529; called at L244
    reported = [f for f in (getattr(development, "files_changed", None) or []) if f.endswith(".py")]  # L568
    diffed = await self._get_changed_files(worktree)                                                  # L569
    command = "pytest " + " ".join(shlex.quote(t) for t in targets) if targets else "pytest"          # L579
    return [ShellCriterion(name="pytest (derived: changed scopes)", command=command)]                 # L585
@classmethod
def _pytest_targets(cls, files: List[str], worktree_path: str) -> List[str]:                          # L588
@classmethod
def _pytest_target_for(cls, path: str, worktree_path: str) -> Optional[str]:                          # L633
@staticmethod
def _deepest_existing_dir(tests_root: str, subdirs: Tuple[str, ...], worktree_path: str) -> str:      # L679
@staticmethod
def _prune_nested(targets: set) -> List[str]:                                                         # L703
@staticmethod
async def _get_changed_files(worktree_path: str) -> List[str]:                                        # L724

# dispatchers/llm.py
class LLMCodeDispatcher:                                                                              # L66 (Nova nova.py:66, GoogleCompat google_compat.py:19, Grok grok.py:20 subclass it)
    async def dispatch(self, ...):                                                                    # L128
    async def _tool_run_command(self, cwd: str, args: Dict[str, Any], profile: LLMCodeDispatchProfile) -> Dict[str, Any]:  # L1893
        argv = args.get("argv")                                                                       # L1899
        command = os.path.basename(argv[0])                                                           # L1902
        if command not in set(profile.allowed_commands): ...                                          # L1903
        if policy_error := command_policy_error(Path(run_cwd), argv): ...                             # L1943
        result = await self._run_argv(argv, cwd=run_cwd, timeout=timeout)                             # L1945
    def _validate_command_paths(...) -> Optional[str]:                                                # L2017
    async def _run_argv(self, argv, *, cwd, timeout, stdin=None): ...                                 # L2124

# models/llm.py
class LLMCodeDispatchProfile(BaseModel):                                                              # L10
    allowed_commands: List[str]  # L51 default includes "git","uv","pytest","python","python3","rg","grep","ls",…

# worktree_environment.py — stdlib-only imports (L7-16)
def repository_paths(cwd: Path) -> tuple[Path, Path | None]:   # L26 — returns COMMON git dir (follows commondir L38-40)
def command_policy_error(cwd: Path, argv: Sequence[str]) -> str | None:  # L73
def protected_argv(cwd: Path, argv: Sequence[str]) -> list[str]:         # L109
def hook_response(payload: dict[str, Any]) -> dict[str, Any]:            # L158
    wrapped = protected_argv(cwd, ["/bin/bash", "-c", command])          # L169
    output["updatedInput"] = {**tool_input, "command": shlex.join(wrapped)}  # L171
def main() -> None:                                                      # L182 — reads JSON stdin, explicit deny on exception

# sdd_coder/engine.py
async def prepare_native(self, feature: str, worktree: str, task_id: str, execution_id: Optional[str] = None) -> NativePrep:  # L1225
async def merge(self, feature: str, worktree: str, task_id: str, execution_id: Optional[str] = None) -> TaskResult:          # L1615
async def _run_attempt(self, ctx: _FeatureCtx, task: PlannedTask, seat: RosterSeat, *, attempt: int, job_id: str,
                       execution_id: Optional[str] = None, pool: Optional["ExecutionPool"] = None) -> Tuple[...]:           # L1897
    await manager.create(self._worker_id(task.task_id, attempt, execution_id))                        # L2036
    profile = profile.model_copy(update={"subagent": "sdd-coder"})                                    # L2043
    output = await dispatcher.dispatch(brief=TaskScopedBrief(research=…, task_id=…, task_file=task.task_file, …), …)  # L2046

# models/base.py
class TaskScopedBrief(BaseModel):  # L468
    research: ResearchOutput; task_id: str; coder_feedback: str = ""; task_file: str = ""  # L476-481

# sdd_coder/models.py
class PlannedTask(BaseModel):  # L209 — task_id, task_file, title, seat_label, native, backend, model, assessment_id
class NativePrep(BaseModel):   # L325 — task_id, task_file, branch, worktree_path, seat_label, model, attempt_uid, coder_feedback, assessment_id

# sdd_coder/fidelity.py
_HEADING = re.compile(r"^## Files to Create ?/ ?Modify\s*$", re.M)  # L13
_NEXT_HEADING = re.compile(r"^## ", re.M)                           # L14
def parse_task_files(task_md: str) -> List[str]:                    # L29

# dispatchers/codex.py / models/codex.py
class CodexCodeDispatcher: ...                    # codex.py:136 — `codex exec --json --cd … --sandbox …`
class CodexCodeDispatchProfile(BaseModel):        # models/codex.py:10 — no allowed_commands; ignore_user_config: bool = True

# parrot_tools/tool_optimizations/hooks.py
@dataclass
class GuardDecision:  # L111 — deny: bool=False, reason: str="", path, lines, size, coverage: str="not_applicable"
def parse_shell_subset(command: str) -> Optional[list[list[str]]]:  # L250
def evaluate_shell(command: str, cwd: Path, policy: GuardPolicy) -> GuardDecision:  # L400
DENY_VALUE = {"claude": "deny", "codex": "deny"}  # L466
def render_output(decision: Optional[GuardDecision], host: str) -> Optional[str]:  # L469
def main(argv=None, stdin=None, stdout=None) -> int:  # L549; Bash branch L577-578; never raises

# parrot_tools/tool_optimizations/models.py / contracts.py
class DelegationPacket(_StrictModel):  # models.py:285 — validation_commands: List[List[ShortStr]] (L314), optional contract
ALLOWED_VALIDATION_PROGRAMS = frozenset({"pytest", "ruff", "black", "mypy", "python", "python3"})  # contracts.py:65

# scripts/sdd/check_task_graph.py
PARALLEL_SEMANTICS = "exclusive"                                      # L41
class Finding(BaseModel): level: str; code: str; tasks: list[str]; message: str  # L50
class GraphReport(BaseModel): ... findings: list[Finding]             # L59
def check_graph(index_path: Path, root: Path) -> GraphReport:         # L176; legacy-semantics pattern L200-206
```

### Configuration References
```ini
# pytest.ini (repo root) — shadows root pyproject [tool.pytest.ini_options] (pyproject.toml:230-249: --strict-markers, log_cli DEBUG, filterwarnings=error)
[pytest]
asyncio_mode = auto
markers = integration, live, real_llm, slow
filterwarnings = ignore::DeprecationWarning
```
- Per-dist pytest sections: `packages/ai-parrot/pyproject.toml:997` (markers `real_llm`, `network`, `live`), `ai-parrot-server:118`, `ai-parrot-integrations:143`, `parrot-formdesigner:93`.
- `.venv`: pytest 9.1.1, pytest-xdist 3.3.1 (root `pyproject.toml:64`), pytest-asyncio 1.4.0.
- `.gitignore:363-366` — `.codex/*` ignored except `.codex/agents/*.toml`; `.codex/hooks.json` is local-only today (`git check-ignore -v` → `.gitignore:363`) and its command hard-codes `/home/jesuslara/proyectos/ai-parrot/.venv/bin/python` — M8 tracks it with a portable launcher.
- Measured source fan-in (grep of `parrot.<m> import` + relative forms over `packages/*/src`, 2026-09-17): `parrot.clients.base` 182 source importers / 37 direct test importers; `parrot.bots.abstract` 146 / 13. Spike S4 re-measures transitively with the M2 index.
- Codex command build: `_build_command` `dispatchers/codex.py:341`; `--ignore-user-config` appended at L379-380 and L442-443; `--model` at L432; `-c approval_policy=…` at L372-373. `CodexCodeReviewProfile` `models/codex.py:38`, `CodexAdversarialReviewProfile` follows it.
- Native seat hook wiring: `.claude/agents/sdd-coder.md:16-22` / `sdd-worker.md:27-33` → `python3 "$CLAUDE_PROJECT_DIR/packages/ai-parrot/src/parrot/flows/dev_loop/worktree_environment.py" --hook || exit 2`; SDK path `dispatchers/claude.py:620-640`.
- Template sections: `sdd/templates/task.md` — `## Acceptance Criteria` L266, `## Test Specification` L276, `## Delegation Contract` L110.

### Integration Points
| New Component | Connects To | Via | Verified At |
|---|---|---|---|
| `test_scope.mirror.*` | `QANode._pytest_targets` family | delegation | `nodes/qa.py:588-717` |
| `test_scope.plan_tests` | `QANode._default_criteria` | call, replaces L578-585 | `nodes/qa.py:529` |
| `test_scope.guard.guard_argv` | `LLMCodeDispatcher._tool_run_command` | call before `command_policy_error` | `dispatchers/llm.py:1943` |
| `test_scope.guard.guard_bash` | `worktree_environment.hook_response` | call before `protected_argv` | `worktree_environment.py:169` |
| `test_scope.context.write_attempt_context` | `SddCoderEngine._run_attempt` / `prepare_native` | call after `manager.create` | `engine.py:2036`, `engine.py:1225` |
| `hooks.evaluate_scope` | `hooks.main` Bash branch | call before `evaluate_shell` | `hooks.py:577-578` |
| `test_scope.contract.parse_validation_commands` | `check_graph` | new finding pass | `check_task_graph.py:176` |

### Does NOT Exist (Anti-Hallucination)
- ~~a module-level pytest/command allowlist constant in dev_loop~~ — it is the field `LLMCodeDispatchProfile.allowed_commands`
- ~~any executor of `validation_commands`~~ — nothing in the engine, fidelity gate, chunker, `sdd-start` or `sdd-worker` runs them
- ~~`validation_commands` on `PlannedTask`, `NativePrep`, `TaskScopedBrief` or index task entries~~
- ~~`## Validation Commands` section in `sdd/templates/task.md`~~ — new in M9
- ~~`e2e` marker~~ — not registered anywhere today
- ~~directory-based auto-marking in any conftest~~ — existing hooks only skip by marker (`packages/ai-parrot/tests/conftest.py:15`, `benchmarks/conftest.py:13`, `ai-parrot-tools/tests/research/conftest.py:20`, `company_info/conftest.py:21`)
- ~~pytest-timeout~~; ~~any `-n`/`--dist`/`xdist_group`/`worker_id` usage~~
- ~~an `imports` relation in wikitoolkit blast radius~~ — calls/extends/implements/references/contains only; test→`Class.method(...)` produces no edge
- ~~argv interception for codex~~ — codex executes its own commands
- ~~a tracked `.codex/hooks.json`~~ — git-ignored, absent from worktrees (tracked by M8)
- ~~`scripts/sdd/codex_hook.sh`~~ — new in M8
- ~~a pytest run in the sdd_coder engine~~ — `fidelity.py:86` runs only ruff TID251
- ~~a per-worktree git dir helper~~ — `repository_paths` returns the *common* dir; M3 adds `worktree_git_dir`
- ~~`scripts/sdd/select_tests.py`~~, ~~`parrot.flows.dev_loop.test_scope`~~ — new in this spec
- ~~effective `log_cli=DEBUG` on root runs~~ — shadowed by `pytest.ini`

---

## 7. Implementation Notes & Constraints

### Patterns to Follow
- Kernel core: stdlib only, `@dataclass(frozen=True)`, relative imports, Google docstrings, type hints. Pydantic only in `test_scope/models.py`.
- Sync `subprocess.run` is acceptable inside the kernel (it is called from a hook process and a CLI); async callers (`QANode`, `LLMCodeDispatcher`) must call planning via `asyncio.to_thread`.
- Follow `check_task_graph.py`'s header-flag pattern (`parallel_semantics` → `legacy-semantics`, L200-206) for `validation_contract`.
- Follow `hooks.py`'s "never break the host session" rule: any guard exception → allow (MCP/native) / silence (codex).
- Mirror logic is **moved**, not rewritten; parity test guards it.

### Known Risks / Gotchas
- **R1 — Cross-distribution runs**: MCP `run_command` returns one result; replacement invocations run sequentially, output concatenated, first non-zero exit wins. Native rewrite uses a subshell that runs every invocation and exits with the OR of exit codes.
- **R2 — Compound bash** (`cd x && pytest …`, `| tail`, env prefixes, heredocs): rewrite only a parseable pytest segment; unparseable → allow + note. Never break a command.
- **R3 — Codex hook reachability** (*decided*): `.codex/hooks.json` becomes tracked and development dispatches drop `--ignore-user-config`, so every attempt sub-worktree carries the project hook. Residual: the tracked command must be portable (launcher, no absolute user path), and S1 must confirm codex loads a project-level hook under `codex exec --cd`.
- **R3b — Operator config now inherited by codex dev seats**: without `--ignore-user-config`, `~/.codex/config.toml` (MCP servers, profiles, extra hooks) applies to development dispatches. Model, sandbox and approval policy stay pinned by explicit flags; review profiles keep the flag. Document in `docs/dev_loop/sdd-coder-orchestrator.md`.
- **R4 — Rewrite empty** → block (brainstorm decision); exit 5 (no tests collected) from a plan is a scoping miss, reported, never green.
- **R5 — Static import blind spots** (dynamic imports, fixtures in `conftest.py`, meta_path redirects other than `parrot.tools`): covered by feature tier and CI.
- **R6 — conftest loading when rooted at `packages/<dist>/`**: if the root `conftest.py` (worktree source precedence) does not load, worktree runs import main-checkout code. Spike S2 decides whether invocations need `--rootdir`/`-c`/`--confcutdir`.
- **R7 — xdist-unsafe tests**: navconfig `os.chdir` on import, 34 `chdir` hits in tests, ~60 session/module fixtures, fixed ports, shared sqlite/redis. Allowlist starts empty; a dist is only added with a clean `-n auto` run as evidence; no automatic serial retry.
- **R8 — `integrations/` ≠ `integration/`**: marking `integrations/` would silently drop ~120 unit-test modules from agent runs.
- **R9 — Hot files**: `dispatchers/llm.py` and `sdd_coder/engine.py` are under active development (FEAT-549/559/561); rebase before each task.
- **R10 — Timeout budget**: a task-tier plan exceeding the attempt's `command_timeout_seconds` is a failed attempt with the plan attached, not retried broader.
- **R11 — FEAT-562 drift**: §6 config references must be re-verified after FEAT-562 merges.
- **R12 — Feature tier granularity** (*decided*): the brainstorm's "package suites of touched distributions" as the feature-tier default is **dropped**; the default is the mirror of directories (today's QANode granularity, avoiding the ~9 min full `ai-parrot` suite recorded in `qa.py:591-594`) ∪ declared validation commands. Package suites run only for core changes (G7b, G9).
- **R13 — Core escalation cost**: `clients/base.py` escalates across `ai-parrot` (1,450 modules, ~9 min) and every satellite importing it. Mitigations: never at task tier; ledger pays it once per feature content; spike S3 prioritises making `ai-parrot` xdist-safe, since that suite dominates escalation cost.
- **R14 — Ledger trust**: the ledger lives in the per-worktree git admin dir, so it disappears with the worktree (correct: a new worktree re-pays). A malformed ledger reads as empty (re-run, never skip). Only runs executed by the kernel (CLI `--run`, QANode criteria) write it.
- **R15 — Fan-in blind spots**: dynamic imports and the `parrot.tools` meta_path redirect can under-count fan-in; `CORE_PATHS` is the manual override.

### Spikes (first tasks, evidence to `artifacts/logs/`)
- **S1** — confirm the tracked `.codex/hooks.json` fires under `codex exec --cd <attempt sub-worktree>` without `--ignore-user-config` (R3).
- **S2** — conftest/rootdir behaviour for `pytest packages/<dist>/tests/...` from a worktree (R6).
- **S3** — xdist safety per distribution, **`ai-parrot` first** (it dominates core-escalation cost, R13), then satellites (R7) → initial `XDIST_SAFE_DISTRIBUTIONS`.
- **S4** — measure transitive source fan-in for all source modules with the M2 index and write `CORE_PATHS` from that measurement: every module with fan-in ≥ 50 (threshold confirmed) plus any module the measurement shows under-counted by dynamic imports / the `parrot.tools` redirect (R15). The measurement is authoritative — no extra sign-off (evidence `artifacts/logs/feat-563-core-fanin.tsv`).

### External Dependencies
| Package | Version | Reason |
|---|---|---|
| `pytest` | 9.1.1 (installed) | runner |
| `pytest-xdist` | ==3.3.1 (already pinned, root `pyproject.toml:64`) | `-n auto` for allowlisted dists |
| stdlib `ast`, `shlex`, `dataclasses`, `subprocess` | — | kernel core |

No new dependencies.

---

## 8. Open Questions

- [x] Flow type / base branch — *Resolved in brainstorm*: feature → dev
- [x] Task-tier time budget — *Resolved in brainstorm*: < 60 s for a typical 1–4 file task
- [x] Overflow policy when impact selection exceeds the cap — *Resolved in brainstorm*: escalate to package suite + xdist (if allowlisted)
- [x] Core changes (e.g. `clients/base.py`, `bots/abstract.py`) — *Owner: Jesus Lara*: pay the full suites of every importing distribution, detected by transitive source fan-in ≥ 50 or `CORE_PATHS`; at merge and feature tiers only, once per feature via a blob-hash ledger; G9 reworded to "cost proportional to blast radius"
- [x] Guard mode for over-broad pytest — *Resolved in brainstorm*: rewrite automatically
- [x] Guard behaviour when the rewrite would be empty — *Resolved in brainstorm*: block with guidance
- [x] Where marker exclusion applies — *Resolved in brainstorm*: only in agent-issued commands
- [x] Impact source — *Resolved in brainstorm*: own AST import scanner (wikitoolkit optional signal only)
- [x] xdist policy — *Resolved in brainstorm*: opt-in per distribution allowlist
- [x] Sequencing with FEAT-562 — *Resolved in brainstorm*: FEAT-562 goes first; this feature bases on `dev` after FEAT-562 is merged and builds on its marker registration and CI selections
- [x] SSOT for `validation_commands` — *Owner: Jesus Lara*: a new mandatory `## Validation Commands` section in the task file (parsed like `parse_task_files`, linted by `check_task_graph`)
- [x] Kernel home — *Owner: Jesus Lara*: `parrot/flows/dev_loop/test_scope/` with a stdlib-only core and Pydantic models in a separate `models.py` (documented exception)
- [x] Codex seat — *Owner: Jesus Lara*: deny with the exact scoped command (reachability verified by spike S1)
- [x] Codex hook reachability — *Owner: Jesus Lara*: take `.codex/hooks.json` out of `.gitignore` (tracked, portable launcher) and stop passing `--ignore-user-config` for development dispatches
- [x] CI `packages/*/tests` gap — *Owner: Jesus Lara*: out of scope — non-goal here, separate feature
- [ ] Cap and depth defaults (150 modules / 1 hop) — confirm or tune after measuring on real merges — *Owner: Jesus Lara*
- [x] Final `CORE_PATHS` list and fan-in threshold — *Owner: Jesus Lara*: threshold **50** confirmed; `CORE_PATHS` is set from the spike S4 measurement (no further sign-off required)
- [ ] Root conftest loading when rooted at `packages/<dist>/` (spike S2) — *Owner: implementer*
- [ ] Initial xdist allowlist (spike S3) — *Owner: implementer*
- [x] Feature tier for `QANode` / qa-runner / `/sdd-done` — *Owner: Jesus Lara*: mirror of directories (∪ declared validation commands), never package suites — the goal is to cut time, not to raise test volume
- [ ] Dead root `pyproject.toml [tool.pytest.ini_options]` (shadowed by `pytest.ini`): clean up here or leave to FEAT-562 — *Owner: Jesus Lara*

---

## 9. Design Research Cross-Check

> Model: `gpt-5.6-luna` · Status: skipped (exploration document status is `exploration`, not `accepted`) · Transcript: —

| # | Suggestion (kind) | Disposition | Reason | Landed in |
|---|---|---|---|---|

Summary: **0** confirmed · **0** rejected · **0** escalated.

---

## Worktree Strategy

- **Isolation**: one feature worktree `feat-FEAT-563-scoped-test-selection` from `origin/dev`, created by the implementing lane **after FEAT-562 is merged**; the `sdd-coder` engine gives each task its own sub-worktree.
- **Module dependency graph** (evidence = imported symbols):
  - M2 → M1 (`TestTarget`, `ScopePolicy`, `build_plan`)
  - M3 → M1 (`plan_tests`, `is_broad_pytest`, `parse_validation_commands`)
  - M4 → M1, M2, M3 (`ScopePlan`, `ImportIndex`, `record_green_escalation`)
  - M5 → M1, M2, M3, M4 (`mirror.*`, `plan_tests`, `detect_core`, `record_green_escalation`)
  - M6 → M3 (`guard_argv`, `write_attempt_context`)
  - M7 → M3 (`guard_bash`, `write_attempt_context`)
  - M8 → M3 (`read_attempt_context`, `guard_bash`)
  - M9 → M1 (`parse_validation_commands`, `is_broad_pytest`)
  - M11 → M4 (CLI) — except the two full-suite deletions (no dependency)
  - M10 — no edges
- **Concurrency**: after M1: {M2, M3, M9, M10} in parallel; after M3: {M6, M7, M8} in parallel; M4 after M2 and M3; M5/M11 after M4. Spikes S1–S3 have no code edges and run first/in parallel; S4 runs after M2 (it uses the index).
- **Shared files**: `sdd_coder/engine.py` (M6 `_run_attempt`, M7 `prepare_native`) → serialize M6/M7 engine edits or assign the context writer to M6 and have M7 depend on it; `packages/ai-parrot/tests/flows/dev_loop/sdd_coder/test_engine_dispatch.py` (M6, M7).
- **Exclusive resources**: none (no lockfile, migration or extension rebuild). M8 touches `.gitignore` and `models/codex.py` (shared with no other module). Spikes S1 (codex CLI run) may be `parallel: false` if it needs a real codex session.
- **Cross-feature dependencies**: **FEAT-562 must be merged into `dev` first**. Active edits in `dispatchers/llm.py` / `sdd_coder/engine.py` (FEAT-549/559/561) → rebase before M6/M7.

---

## Revision History

| Version | Date | Author | Change |
|---|---|---|---|
| 0.1 | 2026-09-17 | Jesus Lara / Claude Opus 5 | Initial draft from `scoped-test-selection.brainstorm.md` (Option B) + 4 spec-time decisions |
| 0.2 | 2026-09-17 | Jesus Lara / Claude Opus 5 | R3: track `.codex/hooks.json` + drop `--ignore-user-config` for dev dispatches; R12: feature tier = mirror of directories, never package suites (G9) |
| 0.4 | 2026-09-17 | Jesus Lara / Claude Opus 5 | Threshold 50 confirmed; `CORE_PATHS` set by spike S4 measurement |
| 0.3 | 2026-09-17 | Jesus Lara / Claude Opus 5 | G9 → cost proportional to blast radius; G7b core escalation by transitive source fan-in ≥ 50 / `CORE_PATHS` across importing distributions, merge+feature tiers only, deduped by blob-hash ledger; spikes S3 (ai-parrot first) and S4 |
