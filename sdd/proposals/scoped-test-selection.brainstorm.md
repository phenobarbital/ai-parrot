---
# SDD flow type and base branch (FEAT-145).
# - type: feature  (default)  → base_branch: dev (or any non-main branch)
# - type: hotfix              → base_branch MUST be: main
type: feature
base_branch: dev
---

# Brainstorm: Scoped Test Selection for the SDD Cycle

**Date**: 2026-09-17
**Author**: Jesus Lara (with Claude Opus 5)
**Status**: exploration
**Recommended Option**: B

---

## Problem Statement

The monorepo has ~2,900 `test_*.py` modules spread over the repo-root `tests/`
(490) and `packages/<dist>/tests` (ai-parrot 1,450; tools 276; formdesigner 226;
integrations 181; server 142; …). Inside the SDD cycle
(`sdd-worker` → `sdd-coder` seat → merge → QA → `/sdd-done`) nothing
*deterministically* bounds what pytest runs:

- `sdd-coder` is only *told* to "Run THIS task's acceptance-criteria tests"
  (`.claude/agents/sdd-coder.md:164`). A seat that is unsure runs
  `pytest packages/ai-parrot/tests` (~9 min, per the `QANode._pytest_targets`
  docstring) or a bare `pytest`.
- `qa-runner` runs a full-suite "sanity" pass on every feature
  (`.claude/agents/qa-runner.md:67`, `pytest -q --tb=line`); `sdd-autopilot.md:568`
  does the same.
- The only deterministic scoping that exists — `QANode._pytest_targets`
  (mirror a changed source path to the deepest existing `tests/` sub-directory) —
  is private to the dev-loop `QANode` and falls back to a bare `pytest` when no
  target maps (`nodes/qa.py:579`).
- `validation_commands` exists only inside the *optional* `DelegationPacket`
  (2 task files use it) and is never executed by anything.
- No `integration`/`e2e` directory marking, no xdist usage, no per-tier policy.

Result: validation wall-clock dominates attempts, retries multiply it, and huge
pytest outputs burn seat tokens. Affected: every SDD lane (native Haiku seat,
nova / google-compat / grok MCP seats, codex seat, dev-loop QANode, qa-runner).

## Constraints & Requirements

- **Budget**: task-level validation for a typical 1–4 file task must finish in
  **< 60 s**.
- **Test pyramid by phase** — each phase pays only for what it can break:
  task → merge → feature → CI. Full suite and e2e run **only in CI**.
- **Guard mode = rewrite**: an over-broad `pytest` from a seat is rewritten to
  the scoped targets, not blocked. **Exception**: when the rewrite would be
  empty (no declared targets and nothing derivable), the command is **blocked**
  with a message telling the seat to declare/point at tests.
- **Marker exclusion only in agent-issued commands** (`-m "not e2e and not
  real_llm and not integration"`); `pytest.ini` / pyproject `addopts` stay
  unchanged, so humans and CI keep seeing everything.
- **Impact source = own AST import scanner** reading the *worktree* files;
  wikitoolkit blast radius is not the source of truth (its plane is the main
  checkout's, and it misses test→`Class.method(...)` edges — see Code Context).
- **xdist is opt-in per distribution** (allowlist of verified xdist-safe
  packages); everything else runs serially.
- **Overflow** (impact selection larger than a cap, e.g. a change in
  `clients/base.py`): escalate those distributions to the feature tier
  (package suite + markers excluded + xdist if allowlisted).
- Deterministic and testable: selection is a pure function of (changed files,
  worktree tree, policy); no LLM in the loop.
- The native Claude hook (`worktree_environment.py --hook`) runs under
  **system `python3` with stdlib-only imports** — whatever it calls must stay
  stdlib-only or be a subprocess.
- Must not reintroduce the worktree import gotcha: pytest in a worktree must
  keep the root `conftest.py` source-precedence behaviour.
- `pytest-testmon` is **out** (coverage DB fragile with worktrees + shared
  editable venv).

---

## Options Explored

### Option A: Prompt-and-docs tightening (per-consumer, no shared kernel)

Edit the agent/command markdown (`sdd-coder`, `sdd-worker`, `qa-runner`,
`sdd-autopilot`, `sdd-done`, `/sdd-task`) to spell out exact scoped commands,
delete the full-suite sanity passes, add directory markers, and leave
`QANode._pytest_targets` where it is.

✅ **Pros:**
- Near-zero code; ships in a day.
- No new module, no hook changes.

❌ **Cons:**
- Non-deterministic: relies on each model obeying prose — the current failure mode.
- No enforcement for MCP seats or codex; no overflow policy; no impact analysis.
- Scoping logic stays duplicated/private.

📊 **Effort:** Low

📦 **Libraries / Tools:**
| Package | Purpose | Notes |
|---|---|---|
| — | — | markdown only |

🔗 **Existing Code to Reuse:**
- `.claude/agents/*.md`, `.claude/commands/sdd-task.md`

---

### Option B: Shared test-scope kernel + enforcement adapters per seat

One deterministic **test-scope kernel** owns selection and policy; thin adapters
enforce it at every place pytest is launched.

1. **Kernel** (stdlib-only core, pydantic at the boundaries):
   - *mirror selector* — `QANode._pytest_targets` / `_pytest_target_for` /
     `_deepest_existing_dir` / `_prune_nested` moved out of `QANode` unchanged
     in behaviour (its 17 existing tests move with it);
   - *import-impact selector* — AST scan of test modules' `import` / `from`
     statements → reverse index `module → test modules`; changed source files
     are mapped to dotted modules via the `packages/<dist>/src/` layout
     (including the `parrot.tools.<x>` → `parrot_tools.<x>` redirect);
   - *policy* — tier (`task` | `merge` | `feature`), marker exclusion, module
     cap with escalation to package suites, xdist allowlist, fixed flags
     (`-q --tb=short -p no:cacheprovider -o log_cli=false`);
   - *planner output* — a list of **per-distribution pytest invocations**
     (never one invocation spanning distributions, because config discovery
     differs: root `pytest.ini` vs `packages/<dist>/pyproject.toml`).
   - CLI entry for markdown agents, e.g. `python -m scripts.sdd.select_tests
     --tier merge --base origin/dev [--json]`.
2. **Adapters**:
   - MCP seats (nova / google-compat / grok): in
     `LLMCodeDispatcher._tool_run_command`, after the allowlist + path checks
     and before `command_policy_error` / `_run_argv`, rewrite an over-broad
     `pytest` argv; report the rewrite in the tool result `hint`.
   - Native Haiku seat: in `worktree_environment.hook_response`, before
     `protected_argv`, detect an over-broad pytest in the bash string and
     rewrite it (kernel core must be stdlib-importable by path).
   - Codex seat: cannot rewrite (codex runs its own commands); deny-only via the
     existing `.codex/hooks.json` → `parrot_tools.tool_optimizations.hooks
     --host codex`, with a message containing the scoped command to run instead.
   - `QANode._default_criteria`: use the kernel (`feature` tier) and never fall
     back to a bare `pytest`.
   - `qa-runner` / `sdd-autopilot` / `sdd-worker` / `sdd-done`: replace prose and
     full-suite passes with the kernel CLI for their tier.
3. **Task contract**: `/sdd-task` must emit a mandatory, file-level
   `validation_commands` block per task; `check_task_graph.py` lints it
   (missing, bare `pytest`, directory == `tests/` or `packages/<dist>/tests`).
4. **Markers**: directory-based auto-marking (`integration`, `e2e`) in the
   conftest layer; `e2e` registered where missing (`integration`, `live`,
   `real_llm`, `slow` already exist in root `pytest.ini`).

✅ **Pros:**
- Deterministic enforcement at the actual exec points of every seat that allows it.
- One implementation, reused by QANode, engine adapters, and markdown agents.
- Impact analysis reads the worktree, not a possibly-stale plane.
- Tier/policy is data, so budgets can be tuned without touching adapters.

❌ **Cons:**
- Touches several hot files (`dispatchers/llm.py`, `worktree_environment.py`,
  `nodes/qa.py`, agent markdown).
- Bash-string parsing for the native hook is heuristic (pipes, `&&`, `cd`, env
  prefixes, `python -m pytest`).
- Codex remains deny-only.
- Static imports miss dynamic imports / fixtures from `conftest.py` / meta_path
  redirects beyond the known one; mitigated by mirror ∪ import and by the tiers above.

📊 **Effort:** Medium–High

📦 **Libraries / Tools:**
| Package | Purpose | Notes |
|---|---|---|
| `ast` (stdlib) | import scanning | no new dependency |
| `shlex` (stdlib) | argv / bash-string tokenizing | already used in `worktree_environment.py` |
| `pytest-xdist` | `-n auto` for allowlisted dists | already pinned `==3.3.1` (root `pyproject.toml:64`), installed |
| `pytest` | runner | 9.1.1 in `.venv` |

🔗 **Existing Code to Reuse:**
- `packages/ai-parrot/src/parrot/flows/dev_loop/nodes/qa.py` — `_pytest_targets` family + `_get_changed_files`
- `packages/ai-parrot/src/parrot/flows/dev_loop/dispatchers/llm.py` — `_tool_run_command` exec path
- `packages/ai-parrot/src/parrot/flows/dev_loop/worktree_environment.py` — the only `updatedInput` producer in the repo
- `packages/ai-parrot-tools/src/parrot_tools/tool_optimizations/hooks.py` — codex/claude deny hook
- `scripts/sdd/check_task_graph.py` — deterministic task-graph lint to extend
- `packages/ai-parrot/tests/flows/dev_loop/test_qa_default_criteria.py` — tests to migrate

---

### Option C: In-pytest scoping plugin (`pytest_ignore_collect` driven by env)

A pytest plugin activated by an environment variable
(`PARROT_TEST_SCOPE=task|merge|feature`, plus base ref). At collection time it
computes the same selection (mirror ∪ AST imports) and skips every non-selected
file via `pytest_ignore_collect` — *before import*, so collection stays cheap.
Seats can type any `pytest` they like; the plugin narrows it. The dispatcher /
hook / codex process env only has to carry the variable.

✅ **Pros:**
- Seat-agnostic, including codex (env is inherited by the codex process).
- No argv or bash-string parsing at all.
- Transparent to humans when the variable is unset.

❌ **Cons:**
- "Magic": a leaked env var silently hides tests from a human run.
- Plugin must load for *every* rootdir (root `pytest.ini` and each
  `packages/<dist>/pyproject.toml`): either a `pytest11` entry point (needs a
  reinstall into the shared editable venv — the `uv sync` hazard) or `-p` on
  every command (back to argv control).
- Cannot split a cross-distribution run into per-dist invocations — it only filters.
- Selection errors surface as "no tests ran" (exit 5) rather than an explicit rewrite.

📊 **Effort:** Medium

📦 **Libraries / Tools:**
| Package | Purpose | Notes |
|---|---|---|
| `pytest` hook API | `pytest_ignore_collect`, `pytest_configure` | stable |
| `ast` (stdlib) | import scanning | shared with Option B's kernel |

🔗 **Existing Code to Reuse:**
- Root `conftest.py` (worktree source precedence) as a possible loading point
- `packages/ai-parrot/tests/conftest.py:15` — existing `pytest_collection_modifyitems` pattern

---

### Option D (rejected): Coverage-based selection with `pytest-testmon`

Most precise selection (per-test coverage DB). Rejected by the user: the
`.testmondata` DB keyed to file paths is fragile across `.claude/worktrees/*`
and a shared venv editable-installed against the main checkout; recorded here
only so it is not re-proposed.

---

## Recommendation

**Option B** is recommended because:

- The problem is that prose is not enforcement (Option A is today's state).
- B enforces at the real exec points (`_tool_run_command`, the native Bash hook)
  and makes the selection an explicit, logged rewrite, which matches the chosen
  guard mode. C filters silently and needs plugin loading across several rootdirs
  in a shared editable venv — the same class of hazard that already broke
  sessions (`uv sync` repointing `.pth`).
- B's kernel is the prerequisite for C anyway: if codex deny-only turns out to
  be insufficient, a later C-style plugin can reuse the kernel for codex alone.
- Trade-off accepted: more touched files and a heuristic bash-string parser for
  the native seat, in exchange for deterministic, testable, per-tier behaviour.

Rollout order inside the feature (maps to the original 6 steps):
1. Remove full-suite passes (`qa-runner`, `sdd-autopilot`); fixed agent flags.
2. Extract the kernel (mirror selector) from `QANode`; QANode consumes it.
3. Guard adapters: MCP rewrite, native hook rewrite, codex deny.
4. Mandatory file-level `validation_commands` in `/sdd-task` + lint.
5. Directory markers + agent-only exclusion + per-dist xdist allowlist.
6. AST import-impact selector with cap → escalation.

---

## Feature Description

### User-Facing Behavior

- Operators see task attempts validate in under a minute; merge and feature
  QA report *which* tests ran and *why* (mirror / import / escalation).
- Seat transcripts show an explicit note when a pytest command was rewritten,
  e.g. "rewritten `pytest packages/ai-parrot/tests` → `pytest
  packages/ai-parrot/tests/flows/dev_loop/test_qa.py …` (tier=task)".
- A seat that issues a broad pytest with nothing to scope to gets a blocked
  command with guidance ("declare validation_commands / point at test files").
- Codex seats get a denied command with the scoped command to run instead.
- `/sdd-task` refuses (lint error) tasks without file-level `validation_commands`.
- Humans running `pytest` by hand and CI are unaffected.

### Internal Behavior

**Tiers**

| Tier | Where | Selection | Markers | xdist |
|---|---|---|---|---|
| `task` | sdd-coder attempt (all seats) | task `validation_commands` ∪ mirror of the attempt's changed files | excluded | no |
| `merge` | sdd-worker after `coder_merge` | mirror ∪ AST import-impact of the merge's changed files; cap → escalate | excluded | allowlisted dists |
| `feature` | qa-runner, QANode default criteria, `/sdd-done` | package suites of touched dists | excluded | allowlisted dists |
| `ci` | GitHub Actions | unchanged (full + e2e) | all | unchanged |

**Kernel flow**

1. Collect changed files: union of reported `files_changed` and
   `git diff --name-only <base>...HEAD` (+ uncommitted), as `QANode` already does.
2. Mirror selector → candidate targets.
3. (merge tier) Import-impact selector: build or load a reverse index for the
   worktree (cache keyed by HEAD tree), map changed source modules → test
   modules importing them (depth configurable, default 1 hop through source
   modules).
4. Apply cap per distribution; over cap → replace that distribution's targets
   by its package suite (feature-tier treatment).
5. Group targets **per distribution**, prune nested, emit one invocation per
   group with fixed flags, marker expression, and `-n auto` only if the dist is
   on the xdist allowlist.
6. Adapters either return the plan (CLI/QANode) or rewrite/deny the
   intercepted command.

**Over-broad detection** (guard): `pytest` / `python -m pytest` with no path
arguments, or any path argument equal to `tests`, `packages/<dist>/tests`, `.`,
or a parent of those. Node ids and specific files/sub-directories are left
alone (a seat pointing at `tests/flows/dev_loop/` is already scoped).

### Edge Cases & Error Handling

- **Rewrite would be empty** (e.g. only `scripts/` or docs changed, no declared
  targets) → block with guidance (user decision).
- **Cross-distribution targets** → multiple invocations; the MCP adapter can
  only return one exec result, so it runs them sequentially and concatenates
  output/exit codes (first non-zero wins).
- **Deleted modules** → existing fallback rules of `_pytest_target_for`.
- **Compound bash commands** in the native hook (`cd x && pytest …`,
  `… | tail`, env prefixes) → rewrite only the pytest segment; if it cannot
  be parsed safely, leave it untouched and log (never break a command).
- **Import-index build failure / syntax errors in test files** → skip that
  module in the index, fall back to mirror-only, record it in the plan.
- **Selected run exits 5 (no tests collected)** → treated as a scoping miss,
  reported, not silently green.
- **Dynamic imports, fixtures in `conftest.py`, meta_path redirects** → known
  blind spots of static analysis; covered by the feature tier and CI.
- **xdist-unsafe tests** in an allowlisted dist (navconfig `os.chdir` on import,
  34 `chdir` hits in tests, ~60 session/module fixtures, fixed ports, shared
  sqlite/redis) → the dist is removed from the allowlist; no automatic serial retry.
- **Timeout budget** exceeded at task tier → reported as a failed attempt with
  the plan attached, not retried with a broader scope.

---

## Capabilities

### New Capabilities
- `test-scope-kernel`: deterministic per-tier test selection (mirror + AST import impact + policy) producing per-distribution pytest plans.
- `test-scope-guard`: rewrite/deny adapters for over-broad pytest in MCP seats, the native Claude hook, and codex.
- `test-scope-cli`: `scripts.sdd` entry point exposing the kernel to markdown agents/commands.
- `task-validation-contract`: mandatory file-level `validation_commands` per task + lint.
- `test-directory-markers`: directory-based `integration` / `e2e` auto-marking with agent-only exclusion.

### Modified Capabilities
- `dev-loop-qa` (QANode default criteria) — consumes the kernel, no bare `pytest` fallback.
- `sdd-coder-engine` / LLM dispatchers — pytest argv rewrite before exec.
- `worktree-environment` hook — pytest rewrite before sandbox wrapping.
- `sdd-task` command, `check_task_graph` lint.
- Agents: `sdd-coder`, `sdd-worker`, `qa-runner`, `sdd-autopilot`, `/sdd-done`.

---

## Impact & Integration

| Affected Component | Impact Type | Notes |
|---|---|---|
| `flows/dev_loop/nodes/qa.py` (`QANode._default_criteria`, `_pytest_targets` family) | modifies | helpers extracted; tests migrate |
| `flows/dev_loop/dispatchers/llm.py` (`_tool_run_command`) | modifies | rewrite hook point ~L1942 |
| `flows/dev_loop/worktree_environment.py` (`hook_response`) | modifies | stdlib-only constraint |
| `parrot_tools/tool_optimizations/hooks.py` (`--host codex`) | extends | deny with scoped suggestion |
| `.codex/hooks.json` | depends on | already wired to the hook above |
| `scripts/sdd/check_task_graph.py` | extends | new lint codes |
| `.claude/commands/sdd-task.md`, `.agent/workflows/sdd-task.md`, `sdd/templates/task.md` | modifies | mandatory validation block |
| `.claude/agents/{sdd-coder,sdd-worker,qa-runner,sdd-autopilot}.md`, `sdd-done` | modifies | tier CLI instead of prose / full suite |
| conftest layer (root `conftest.py` or `tests/conftest.py` + `packages/*/tests/conftest.py`) | extends | directory auto-marking |
| `pytest.ini`, per-package `[tool.pytest.ini_options]` | modifies | register `e2e` where missing (strict markers) |
| `.github/workflows/ci.yml` | none | CI keeps full selections |
| FEAT-562 (`ci-test-failures-root-cause-remediation`) | overlap | also registers markers / touches CI selections |

No new runtime dependencies; no public API change.

---

## Code Context

### User-Provided Code
None — the design was given as a numbered plan (steps 1–6) in conversation.

### Verified Codebase References

#### Classes & Signatures
```python
# packages/ai-parrot/src/parrot/flows/dev_loop/nodes/qa.py
async def _default_criteria(self, shared: Dict[str, Any], research: ResearchOutput) -> List[AcceptanceCriterion]:  # L529
    command = "pytest " + " ".join(shlex.quote(t) for t in targets) if targets else "pytest"  # L579 (bare fallback)
@classmethod
def _pytest_targets(cls, files: List[str], worktree_path: str) -> List[str]:  # L588
@classmethod
def _pytest_target_for(cls, path: str, worktree_path: str) -> Optional[str]:  # L633
@staticmethod
def _deepest_existing_dir(tests_root: str, subdirs: Tuple[str, ...], worktree_path: str) -> str:  # L679
@staticmethod
def _prune_nested(targets: set) -> List[str]:  # L703
@staticmethod
async def _get_changed_files(worktree_path: str) -> List[str]:  # L724 (git diff origin/dev...HEAD, fallback origin/main)

# packages/ai-parrot/src/parrot/flows/dev_loop/dispatchers/llm.py
class LLMCodeDispatcher: ...  # L66 — base of Nova (nova.py:66), GoogleCompat (google_compat.py:19), Grok (grok.py:20)
def _run_tool(self, *, tool_name, tool_args, cwd, profile): ...  # L1473, "run_command" at L1494
async def _tool_run_command(self, cwd: str, args: Dict[str, Any], profile: LLMCodeDispatchProfile) -> Dict[str, Any]:  # L1893
    # argv list → allowlist (basename(argv[0]) in profile.allowed_commands) → _validate_command_paths (L2017)
    # → timeout → command_policy_error(Path(run_cwd), argv) (L1943) → _run_argv(argv, cwd=, timeout=) (L1945)

# packages/ai-parrot/src/parrot/flows/dev_loop/models/llm.py
class LLMCodeDispatchProfile:
    allowed_commands: List[str]  # L51, default includes "git","uv","pytest","python","python3",...
    restrict_command_paths: bool = True  # L40
    command_timeout_seconds: ...  # L26

# packages/ai-parrot/src/parrot/flows/dev_loop/worktree_environment.py  (stdlib-only imports, L7-16)
def command_policy_error(cwd: Path, argv: Sequence[str]) -> str | None:  # L73
def protected_argv(cwd: Path, argv: Sequence[str]) -> list[str]:  # L109 (bwrap)
def hook_response(payload: dict[str, Any]) -> dict[str, Any]:  # L158
    output["updatedInput"] = {**tool_input, "command": shlex.join(wrapped)}  # L171

# packages/ai-parrot/src/parrot/flows/dev_loop/dispatchers/codex.py
class CodexCodeDispatcher: ...  # L136 — `codex exec --json --cd … --sandbox …`; no argv interception
# models/codex.py:10 CodexCodeDispatchProfile — no allowed_commands

# packages/ai-parrot-tools/src/parrot_tools/tool_optimizations/models.py
class DelegationPacket(_StrictModel):  # L285 (optional contract)
    validation_commands: List[List[ShortStr]] = Field(default_factory=list)  # L314
# packages/ai-parrot-tools/src/parrot_tools/tool_optimizations/contracts.py
ALLOWED_VALIDATION_PROGRAMS = frozenset({"pytest", "ruff", "black", "mypy", "python", "python3"})  # L65

# packages/ai-parrot/src/parrot/flows/dev_loop/sdd_coder/models.py
class PlannedTask(BaseModel):  # L209 — task_id, task_file, title, seat_label, native, backend, model, assessment_id
# packages/ai-parrot/src/parrot/flows/dev_loop/sdd_coder/fidelity.py
def parse_task_files(task_md: str) -> List[str]:  # L29 — pattern for parsing a task-file section

# packages/ai-parrot/src/parrot/knowledge/wiki/structural/service.py
async def blast_radius(self, symbol, *, relations=None, depth=2, include_inferred=True, include_tests=True) -> BlastRadiusOutput:  # L287
```

#### Verified Configuration
```ini
# pytest.ini (repo root) — takes precedence over root pyproject [tool.pytest.ini_options]
[pytest]
asyncio_mode = auto
markers = integration, live, real_llm, slow
filterwarnings = ignore::DeprecationWarning
```
- Root `pyproject.toml:230-249` `[tool.pytest.ini_options]` (`--strict-markers`,
  `log_cli_level="DEBUG"`, `filterwarnings=error`) is shadowed by `pytest.ini`
  for root-level runs; runs rooted in `packages/<dist>/` pick that dist's
  pyproject section (ai-parrot L997: `asyncio_mode`, markers `real_llm`,
  `network`, `live`; server L118; integrations L143; formdesigner L93).
- `pytest_collection_modifyitems` exists only for marker-based skipping:
  `packages/ai-parrot/tests/conftest.py:15`, `packages/ai-parrot/tests/benchmarks/conftest.py:13`,
  `packages/ai-parrot-tools/tests/research/conftest.py:20`, `.../company_info/conftest.py:21`.
- `.venv`: pytest 9.1.1, pytest-xdist 3.3.1, pytest-asyncio 1.4.0.
- CI `test-core`: `uv run pytest tests/ -q --tb=short --ignore=tests/tools --continue-on-collection-errors`
  (`.github/workflows/ci.yml:147`); a few package selections run elsewhere
  (e.g. `packages/ai-parrot-tools/tests/tool_optimizations`, L443).

#### Key Attributes & Constants
- `LLMCodeDispatchProfile.allowed_commands` → `List[str]` (models/llm.py:51); duplicated in `models/grok.py:41`
- `_BLAST_RADIUS_NODE_CAP = 500` (structural/service.py:40); default relations `calls`, `extends`, `implements`
- Integration-ish test dirs (module counts): `packages/ai-parrot-integrations/tests/integrations` 87,
  `packages/ai-parrot/tests/integration` 43, `packages/parrot-formdesigner/tests/integration` 22,
  `tests/integrations` 21, `tests/integration` 13, `packages/ai-parrot/tests/flows/dev_loop/integration` 11,
  `packages/ai-parrot-server/tests/integration` 9, `tests/e2e` 4
- Existing kernel tests to migrate: `packages/ai-parrot/tests/flows/dev_loop/test_qa_default_criteria.py`
  (17 tests, e.g. `test_source_file_maps_to_mirrored_test_subtree`, `test_target_covered_by_an_ancestor_is_pruned`)

### Does NOT Exist (Anti-Hallucination)
- ~~a module-level pytest/command allowlist constant in dev_loop~~ — it is the pydantic field `allowed_commands`
- ~~any executor of `validation_commands`~~ — not referenced by the sdd_coder engine, fidelity gate, chunker, `sdd-start`, or `sdd-worker`
- ~~`validation_commands` on `PlannedTask` or in the per-spec index task entries~~ — not present
- ~~`e2e` marker~~ — not registered anywhere (`integration`, `live`, `real_llm`, `slow` are, in root `pytest.ini`)
- ~~directory-based auto-marking in any conftest~~ — none
- ~~pytest-timeout~~ — not installed; ~~any `-n` / `--dist` / `xdist_group` / `worker_id` usage~~ — none
- ~~an `imports` relation in wikitoolkit blast radius~~ — only calls/extends/implements/references/contains; test→`Class.method(...)` calls produce no edge (e.g. `QANode._pytest_targets` blast at depth 2 returns 0 test files although `test_qa_default_criteria.py` calls it)
- ~~argv interception for codex seats~~ — codex CLI executes its own commands; only `.codex/hooks.json` deny is available
- ~~a pytest run in the sdd_coder engine~~ — `fidelity.py:86` runs only `ruff` TID251
- ~~`log_cli=DEBUG` effect on root runs~~ — shadowed by `pytest.ini` (defensive `-o log_cli=false` only)

---

## Parallelism Assessment

- **Internal parallelism**: moderate. After the kernel extraction (step 2) lands,
  the adapters (MCP rewrite, native hook, codex deny), the markers/conftest work,
  and the `/sdd-task` contract + lint touch disjoint files and can run in parallel.
  Step 1 (markdown-only) is independent from the start. The import-impact
  selector (step 6) depends on the kernel.
- **Cross-feature independence**: FEAT-562 (`ci-test-failures-root-cause-remediation`,
  approved, TASK-3296..3301 pending) registers markers and changes CI selections →
  potential conflict on `pytest.ini` / conftest / marker registration. The
  `dev_loop` dispatcher and QA node areas are active (FEAT-549 sdd-coder,
  complexity routing TASK-3291) → rebase risk on `dispatchers/llm.py`.
- **Recommended isolation**: `mixed`
- **Rationale**: the kernel is a hard dependency hub, but once it exists the
  enforcement adapters, marker work and task contract are file-disjoint and
  benefit from concurrent seats.

---

## Open Questions

- [x] Flow type / base branch — *Owner: Jesus Lara*: feature → dev
- [x] Task-tier time budget — *Owner: Jesus Lara*: < 60 s for a typical 1–4 file task
- [x] Overflow policy when impact selection exceeds the cap — *Owner: Jesus Lara*: escalate to package suite + xdist (if allowlisted)
- [x] Guard mode for over-broad pytest — *Owner: Jesus Lara*: rewrite automatically
- [x] Guard behaviour when the rewrite would be empty — *Owner: Jesus Lara*: block with guidance
- [x] Where marker exclusion applies — *Owner: Jesus Lara*: only in agent-issued commands
- [x] Impact source — *Owner: Jesus Lara*: own AST import scanner (wikitoolkit optional signal only)
- [x] xdist policy — *Owner: Jesus Lara*: opt-in per distribution allowlist
- [ ] SSOT for `validation_commands`: a new mandatory task-file section (parsed like `parse_task_files`) vs. a field in the per-spec index task entry vs. the existing `DelegationPacket` — *Owner: Jesus Lara*
- [ ] Kernel home: `parrot/flows/dev_loop/test_scope/` (core, importable by path from the stdlib-only hook) vs. `scripts/sdd/` — and how to reconcile "Pydantic for all structured data" with the stdlib-only hook constraint — *Owner: Jesus Lara*
- [ ] Cap value for import-impact selection per distribution (proposed starting point: 150 modules) and import depth (proposed: 1 hop) — *Owner: Jesus Lara*
- [ ] Codex: is deny-with-suggestion acceptable, or should codex attempts get a C-style env-driven plugin later? Also unverified whether `codex exec --cd <worktree>` loads the repo's `.codex/hooks.json` — *Owner: Jesus Lara*
- [ ] Verify conftest loading when pytest is rooted at `packages/<dist>/pyproject.toml`: does the root `conftest.py` (worktree source precedence) still load? Determines whether per-dist invocations need `--rootdir`/`-c` — *Owner: implementer (spike)*
- [ ] Initial xdist allowlist — which distributions are verified xdist-safe (candidates: small client packages, loaders, embeddings) — *Owner: implementer (spike)*
- [ ] Sequencing with FEAT-562 marker/CI changes (land after FEAT-562, or coordinate `e2e` registration there) — *Owner: Jesus Lara*
- [ ] Should the dead root `pyproject.toml [tool.pytest.ini_options]` (shadowed by `pytest.ini`) be merged/removed here or left to FEAT-562 — *Owner: Jesus Lara*
- [ ] CI coverage gap: `test-core` runs only root `tests/`; most `packages/*/tests` never run in CI, which weakens "full suite only in CI" — in scope here or a separate feature? — *Owner: Jesus Lara*
