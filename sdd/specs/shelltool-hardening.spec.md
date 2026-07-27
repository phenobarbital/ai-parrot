---
# SDD flow type and base branch (FEAT-145).
# - type: feature  (default)  → base_branch: dev (or any non-main branch)
# - type: hotfix              → base_branch MUST be: main
type: feature
base_branch: dev
---

# Feature Specification: ShellTool Hardening — rtk Integration with Anti-Bypass Guard

**Feature ID**: FEAT-380
**Date**: 2026-07-27
**Author**: Jesus Lara (with Claude)
**Status**: draft
**Target version**: next minor
**Brainstorm**: `sdd/proposals/shelltool-hardening.brainstorm.md` (Recommended Option: B)

> **Origin**: capability `shell-rtk-integration` split out of
> `sdd/proposals/sandbox-hardening.brainstorm.md` by user decision
> (2026-07-27). The persistent REPL worker stays in that document; this
> spec covers **only** the `ShellTool` surface.

---

## 1. Motivation & Business Requirements

### Problem Statement

`ShellTool` (`packages/ai-parrot-tools/src/parrot_tools/shell_tool/tool.py`)
executes development commands whose stdout is returned **verbatim** to the
LLM. Routine commands — `pytest`, `npm install`, builds, linters — produce
thousands of tokens of output of which the agent uses a fraction: the final
summary, the error lines, the exit code. That volume inflates context,
makes every turn more expensive, and buries the signal.

The ecosystem has already validated the solution: **RTK** (`rtk-ai/rtk`,
Apache-2.0, Rust) demonstrates 60–90% reductions on known development
command output, with a `tee` mechanism that preserves full output when the
command fails (prior analysis in
`sdd/proposals/brainstorm-tool-result-compression.md:37-67`). RTK is a
**binary crate**, not a linkable library: the correct integration is
invoking it as a command prefix (`rtk test pytest ...`), not via FFI.

**The security requirement that shapes everything**: `rtk <any-command>`
is a **universal execution wrapper**. The `ShellTool` sanitizer validates
the **base command** against an allowlist (`_check_command_access`,
`parrot/security/command_sanitizer.py:827-856`) — if `rtk` entered that
allowlist, the sanitizer would validate `rtk` and **never see what rtk is
about to execute**. A single prefix would nullify the entire allowlist,
including per-pipe-segment validation (`_check_pipe_segments`, `:858-885`).

The current code order is correct and is the basis of the solution:
`assert_command_safe()` validates the original command at `tool.py:146`
(command mode) and `:254` (plan mode), **before**
`_make_action_from_cmdobj` (`:167-198`) builds the action. Inserting the
prefix after validation guarantees the sanitizer always sees the real
command.

### Goals

- **G1 (S1)** — rtk is a hard dependency, on by default, no escape hatch:
  `ShellTool.__init__` fails if the `rtk` binary is unavailable. No flag
  disables wrapping. Never a silent passthrough.
- **G2 (S2)** — The failure surfaces at init, not on the first command:
  probe via `shutil.which("rtk")` + version check in the constructor.
- **G3 (S3)** — Minimum version verified at init: fail below the pinned
  minimum; **warn** (not fail) on newer untested versions.
- **G4 (S4)** — Known-command map only: commands present in a maintained
  `command → rtk subcommand` map are wrapped; everything else runs
  unwrapped. No universal `rtk proxy`.
- **G5 (S5, refined 2026-07-27)** — Debugging fidelity on failure: on
  exit ≠ 0 the agent receives rtk's failure output **plus the tee-file
  pointer** to the complete unfiltered output
  (`~/.local/share/rtk/tee/...`), which the agent can read on demand.
- **G6 (S6)** — `rtk` is rejected as input: it never enters any default
  allowlist and the core sanitizer **denies** it explicitly as an
  agent/user-written command. Only the tool adds the prefix, after
  validation. No strip-and-revalidate.
- **G7 (S7)** — Prefix-pure rewrite: the transformation is strictly
  `cmd` → `rtk <subcmd> cmd`. Never a rewrite that could reintroduce
  something the sanitizer rejected.
- **G8 (S8)** — Output contract intact: `_result_to_dict()`
  (`tool.py:200-212`) keeps its shape; wrapping is transparent except for
  added metadata (`rtk_wrapped`).

### Non-Goals (explicitly out of scope)

- The persistent REPL worker (`sandbox-hardening.brainstorm.md`) — zero
  shared files; parallel feature.
- rtk integration with `ClaudeAgentClient` (`rtk init` in the `claude`
  CLI sub-agent environment) — remains the independent follow-up
  `rtk-subprocess-filter` noted in
  `brainstorm-tool-result-compression.md:458`. **User decision: stays out.**
- Filtering arbitrary REPL output — RTK filters known development
  commands, not arbitrary stdout.
- Native Python reimplementation of per-command filtering was rejected in
  brainstorm (Option A — buys permanent parser maintenance upstream
  already does; builds on a frozen pipeline). A PATH shim directory was
  rejected too (Option C — invisible/magical, evadible via
  `CommandObject.env`). See `proposals/shelltool-hardening.brainstorm.md`.

---

## 2. Architectural Design

### Overview

Option B from the brainstorm: insert the rtk prefix in
`_make_action_from_cmdobj` (`tool.py:167-198`) — validation has already
run on the real command (`:146`, `:254`), and that method is where the
action type is decided. A maintained map `base command → rtk subcommand`
decides whether `RunCommand` receives `cmd` or `rtk <subcmd> cmd`. In
parallel, `rtk` is added to the core sanitizer's denied commands
(`parrot/security/command_sanitizer.py:170`) so no agent can write it
directly. The validate-then-prefix order already exists in the code — no
reordering needed (G7 comes almost free).

Key resolved behaviors (see §8 for the decision trail):

- **Hard dependency**: `__init__` probes the binary once (G1/G2); absence
  or insufficient version → `RuntimeError` with actionable install
  instructions; newer-than-tested version → log warning, continue (G3).
  The probe result is cached on the instance.
- **Version pin decided at implementation time**: the implementing task
  installs the latest stable rtk at implementation start (v0.44.0 as of
  2026-07-26; releases land every few days), verifies the real CLI
  surface against it, and writes the exact pin into a code constant
  (`RTK_MIN_VERSION`) plus docs. The spec deliberately does not hardcode
  a number that would be stale by implementation day.
- **Failure output (G5, refined)**: rtk's tee saves the **full unfiltered
  output to a file** (`~/.local/share/rtk/tee/{ts}_{cmd}.log`, tee mode
  `failures` is the default) and prints a filtered summary plus a pointer
  line to stdout. Decision: keep rtk's output **as-is** (filtered +
  pointer). `ShellTool` does NOT parse or re-read the tee file; the agent
  reads it on demand (`cat` is in `_MODERATE_SAFE_DEFAULTS`). No parsing
  fragility, no double execution.
- **Wrappability rules**: only `RunCommand` candidates without shell
  operators (no `|`, `;`, `&&`) are wrappable — a wrapped pipe would break
  the prefix-pure guarantee about which process receives what. `ExecFile`
  and `ListFiles` are never wrapped.
- **Telemetry (v1)**: per-result metadata `rtk_wrapped: bool` (+
  `rtk_original_cmd` when wrapped), and an aggregate savings helper
  `ShellTool.rtk_savings()` that invokes `rtk gain --format json` and
  returns the parsed report. Exact `rtk gain` flags verified against the
  pinned release at implementation time.

### Component Diagram

```
  agent → ShellTool._execute()
             │
             ├ _run_commands / _run_plan
             │     └ assert_command_safe(real_command)      ← sanitizer ALWAYS sees the real command
             │           └ deny: rtk                         ← guard G6 (core sanitizer)
             │
             └ _make_action_from_cmdobj(spec)
                   ├ base_cmd ∈ RTK_COMMAND_MAP and no shell operators?
                   │     yes → cmd = "rtk <subcmd> " + cmd   ← single insertion point (G7)
                   │     no  → cmd unchanged
                   └ RunCommand(cmd, ...)                    ← /bin/sh -lc, unchanged

  ShellTool.__init__:
     probe rtk (shutil.which + rtk --version)
        ├ missing            → RuntimeError w/ install instructions (G1/G2)
        ├ < RTK_MIN_VERSION  → RuntimeError (G3)
        └ > tested version   → log warning, continue (G3)

  On wrapped-command failure (exit ≠ 0):
     stdout = rtk filtered summary + "[full output: ~/.local/share/rtk/tee/....log]"
     agent reads the tee file on demand (G5)
```

### Integration Points

| Existing Component | Integration Type | Notes |
|---|---|---|
| `packages/ai-parrot-tools/src/parrot_tools/shell_tool/tool.py` | modifies | Probe in `__init__` (`:50-64`); map + prefix in `_make_action_from_cmdobj` (`:167-198`) |
| `parrot/security/command_sanitizer.py` | modifies | `rtk` → `_DEFAULT_DENIED_COMMANDS` (`:170`) + tests |
| `packages/ai-parrot-tools/src/parrot_tools/shell_tool/models.py` | depends on | `BaseAction` executes the already-wrapped `cmd` via `/bin/sh -lc`; no changes expected |
| `packages/ai-parrot-tools/tests/shell_tool/` | extends | Tests for probe, map, guard, failure passthrough, plan mode |
| Docker images / CI / deployment docs | extends | **Operational breaking change**: provisioning rtk becomes mandatory wherever `ShellTool` is used |
| `parrot/clients/claude_agent.py` (`ClaudeAgentClient`) | unchanged | Out of scope by user decision — remains follow-up `rtk-subprocess-filter` |
| `sandbox-hardening.brainstorm.md` (REPL worker) | unchanged | Zero shared files; parallel features |

**Breaking changes**: none in the Python API of `ShellTool`. One
deliberate operational one: **`ShellTool.__init__` fails without rtk
installed** (G1, no escape hatch). Announce in CHANGELOG and migration
guide before merging.

### Data Models

```python
# New module-level constants in tool.py (or a sibling rtk.py module)

RTK_MIN_VERSION: str  # exact pin written at implementation time (see §8)

# Maintained map: base command → rtk subcommand prefix.
# Initial contents (user decision 2026-07-27). Exact rtk subcommand per
# entry MUST be verified against the pinned release at implementation time.
RTK_COMMAND_MAP: dict[str, str] = {
    "pytest": "test",     # rtk test pytest ...
    "npm":    ...,        # npm test/install — verify subcommand routing
    "git":    ...,        # git status/log/diff — verify
    "cargo":  ...,        # cargo test/build/clippy — verify
    "ruff":   "lint",     # verify
    "uv":     ...,        # uv run support landed in rtk v0.44.0 — verify
}
```

```python
# Result metadata additions (inside ActionResult.metadata — dict, no schema change)
{
    "rtk_wrapped": bool,           # always present for RunCommand results
    "rtk_original_cmd": str,       # only when rtk_wrapped is True
}
```

### New Public Interfaces

```python
class ShellTool(SecureShellMixin, AbstractTool):
    def __init__(self, security_policy: Any = _NO_POLICY, **kwargs: Any) -> None:
        """Existing signature unchanged. Now raises RuntimeError when the
        rtk binary is missing or older than RTK_MIN_VERSION (G1/G2/G3)."""

    async def rtk_savings(self) -> Dict[str, Any]:
        """Return the parsed `rtk gain` JSON report (token-savings telemetry).

        Raises a clear error if the report cannot be produced; never
        interferes with command execution."""
```

Internal (non-public) helpers, names indicative:

```python
def _probe_rtk(self) -> str: ...        # returns detected version; raises RuntimeError
def _wrap_with_rtk(self, raw: str) -> tuple[str, bool]: ...  # (possibly-prefixed cmd, wrapped?)
```

---

## 3. Module Breakdown

> Order is normative: Module 1 (guard) MUST merge before or together with
> Module 3 (prefix insertion), never after.

### Module 1: `sanitizer-rtk-guard` (core)
- **Path**: `packages/ai-parrot/src/parrot/security/command_sanitizer.py`
- **Responsibility**: add `"rtk"` to `_DEFAULT_DENIED_COMMANDS` (`:170`)
  with an inline comment referencing this spec (universal execution
  wrapper — allowlisting it would bypass the entire allowlist). Applies
  to all three levels (RESTRICTIVE/MODERATE/PERMISSIVE) and to every
  consumer of `CommandSanitizer`, not just `ShellTool`.
- **Depends on**: nothing.

### Module 2: rtk init probe (hard dependency)
- **Path**: `packages/ai-parrot-tools/src/parrot_tools/shell_tool/tool.py`
- **Responsibility**: `_probe_rtk()` called from `__init__` following the
  existing `set_security_policy()` configuration pattern (`:59-64`):
  `shutil.which("rtk")` + `rtk --version` parse; missing → `RuntimeError`
  with install instructions (pointing at `scripts/install-rtk.sh` and the
  pinned version); `< RTK_MIN_VERSION` → `RuntimeError`; newer → warning
  via `self.logger`. Result cached on the instance. Defines
  `RTK_MIN_VERSION` (exact value written at implementation time).
- **Depends on**: Module 5 (script name referenced in the error message —
  name can be agreed upfront; script itself can land in parallel).

### Module 3: command map + prefix-pure insertion
- **Path**: `packages/ai-parrot-tools/src/parrot_tools/shell_tool/tool.py`
- **Responsibility**: `RTK_COMMAND_MAP` (initial entries: `pytest`, `npm`,
  `git`, `cargo`, `ruff`, `uv`); `_wrap_with_rtk()` consulted inside
  `_make_action_from_cmdobj` only for the `RunCommand` branch
  (`:197-198`), only when the command contains no shell operators
  (`|`, `;`, `&&`). Sets metadata `rtk_wrapped` / `rtk_original_cmd`.
  Plan mode gets the same treatment for free (validation at `:254`
  precedes `_make_action_from_cmdobj`; note `:258` forces
  `action.type_name = step.type` — metadata must survive that).
- **Depends on**: Module 1 (guard must exist first), Module 2 (probe).

### Module 4: savings telemetry
- **Path**: `packages/ai-parrot-tools/src/parrot_tools/shell_tool/tool.py`
- **Responsibility**: `ShellTool.rtk_savings()` invoking
  `rtk gain --format json` (exact flags verified against pinned release)
  via the existing async subprocess machinery; parsed dict returned.
- **Depends on**: Module 2.

### Module 5: provisioning & docs
- **Paths**: `scripts/install-rtk.sh`, `docs/migration/feat-380-rtk.md`,
  `CHANGELOG` entry, reference Dockerfile snippet in the migration doc.
- **Responsibility**: pinned-version installer (curl installer or cargo
  install, idempotent, verifies `rtk --version` post-install); deployment
  and migration documentation declaring the operational breaking change;
  CI provisioning note.
- **Depends on**: Module 2 (pin value).

---

## 4. Test Specification

### Unit Tests

| Test | Module | Description |
|---|---|---|
| `test_rtk_denied_all_levels` | 1 | `rtk ...` → `CommandSecurityError` under RESTRICTIVE, MODERATE, PERMISSIVE |
| `test_rtk_denied_with_path` | 1 | `/usr/local/bin/rtk ...` denied — `_extract_base_command` (`:770`) normalizes the path |
| `test_rtk_denied_as_pipe_segment` | 1 | `echo x \| rtk proxy cat` denied via `_check_pipe_segments` (`:858-885`) |
| `test_rtk_not_in_moderate_defaults` | 1 | `rtk` ∉ `_MODERATE_SAFE_DEFAULTS` and ∉ any default allowlist |
| `test_init_fails_without_rtk` | 2 | `shutil.which` mocked to `None` → `RuntimeError` with install instructions |
| `test_init_fails_below_min_version` | 2 | mocked `rtk --version` below pin → `RuntimeError` |
| `test_init_warns_newer_version` | 2 | newer version → warning logged, init succeeds |
| `test_probe_cached` | 2 | probe subprocess runs once per instance |
| `test_mapped_command_wrapped` | 3 | `pytest -q` → action cmd `rtk test pytest -q`; `rtk_wrapped=True`, `rtk_original_cmd` set |
| `test_unmapped_command_unwrapped` | 3 | `echo hi` runs unchanged; `rtk_wrapped=False` |
| `test_pipe_never_wrapped` | 3 | `pytest \| tail` NOT wrapped even though base is mapped |
| `test_execfile_listfiles_never_wrapped` | 3 | `./run.sh`, `ls -la` never receive the prefix |
| `test_plan_mode_wrapped` | 3 | plan step `run_command` with mapped base gets wrapped; validation still on real command |
| `test_sanitizer_sees_real_command` | 3 | spy on `assert_command_safe`: receives the original, never the prefixed string |
| `test_result_contract_unchanged` | 3 | `_result_to_dict()` keys identical to today + metadata additions only |
| `test_rtk_savings_parses_json` | 4 | mocked `rtk gain` output → parsed dict |

### Integration Tests

| Test | Description |
|---|---|
| `test_wrapped_failure_emits_tee_pointer` | (`skipif` rtk missing) failing wrapped command → exit code preserved, stdout contains the tee-file pointer line, tee file exists and holds full output |
| `test_wrapped_success_reduced_output` | (`skipif` rtk missing) successful `rtk test pytest` output smaller than raw run |
| `test_exit_code_passthrough` | (`skipif` rtk missing) wrapped command exit code equals unwrapped exit code (success and failure) |
| `test_install_script_idempotent` | `scripts/install-rtk.sh` run twice → same pinned version, zero diff |

### Test Data / Fixtures

```python
@pytest.fixture
def mock_rtk_probe(monkeypatch):
    """Make ShellTool() constructible on machines without rtk:
    patch shutil.which → '/usr/bin/rtk' and the version subprocess →
    RTK_MIN_VERSION. Unit tests for Modules 1/3/4 use this; integration
    tests use the real binary behind pytest.mark.skipif."""
```

---

## 5. Acceptance Criteria

> This feature is complete when ALL of the following are true:

- [ ] `ShellTool()` on a machine without `rtk` raises `RuntimeError` at
      construction with actionable install instructions (G1/G2 — never a
      silent passthrough, no disable flag exists).
- [ ] `rtk --version` below `RTK_MIN_VERSION` fails init; a newer version
      logs a warning and continues (G3).
- [ ] `RTK_MIN_VERSION` holds an exact tested release, written at
      implementation time, and `scripts/install-rtk.sh` installs exactly
      that version idempotently.
- [ ] Only commands whose base is in `RTK_COMMAND_MAP` (initial entries:
      `pytest`, `npm`, `git`, `cargo`, `ruff`, `uv`) and that contain no
      shell operators are wrapped; everything else runs byte-identical to
      today (G4). `ExecFile`/`ListFiles` are never wrapped.
- [ ] The sanitizer always validates the original command; the prefix is
      inserted only afterwards, in `_make_action_from_cmdobj`, as a pure
      prefix (G7). A spy test proves `assert_command_safe` never sees
      `rtk`-prefixed input.
- [ ] `rtk` (bare or path-qualified, standalone or as a pipe segment) is
      denied by the core sanitizer at all three security levels (G6), and
      `rtk` appears in no default allowlist.
- [ ] On wrapped-command failure the exit code is preserved and stdout
      carries rtk's failure summary plus the tee-file pointer to the full
      unfiltered output (G5, refined). ShellTool does not parse or inline
      the tee file.
- [ ] `_result_to_dict()` output shape is unchanged except for the new
      metadata keys `rtk_wrapped` (+ `rtk_original_cmd` when wrapped) (G8).
- [ ] `ShellTool.rtk_savings()` returns the parsed `rtk gain` JSON report.
- [ ] Plan mode (`_run_plan`) wraps mapped commands identically to
      command mode.
- [ ] With `security_policy=None` the G6 guard does not apply (documented
      pre-existing "everything allowed" mode) but the tool-side prefix
      still applies — covered by a test and a docs note.
- [ ] Migration doc (`docs/migration/feat-380-rtk.md`) + CHANGELOG entry
      declare the operational breaking change with Dockerfile/CI guidance.
- [ ] All new and existing shell_tool + sanitizer tests pass:
      `pytest packages/ai-parrot-tools/tests/shell_tool/ packages/ai-parrot/tests/ -v`
      (scope the core run to the sanitizer suite as appropriate).
- [ ] No breaking changes to the Python API of `ShellTool`.

---

## 6. Codebase Contract

> **CRITICAL — Anti-Hallucination Anchor**
> This section is the single source of truth for what exists in the codebase.
> Implementation agents MUST NOT reference imports, attributes, or methods
> not listed here without first verifying they exist via `grep` or `read`.
>
> ✅ Re-verified against `dev` HEAD on 2026-07-27 (this session).
> ⚠️ Path correction inherited from the sandbox-hardening brainstorm: the
> `parrot/tools/shell/*` paths in that document do NOT exist. The real
> location is `packages/ai-parrot-tools/src/parrot_tools/shell_tool/`
> (satellite package, `parrot_tools` namespace).

### Verified Imports

```python
# Both verified 2026-07-27:
from parrot_tools.shell_tool.security import SecurityPolicy, SecureShellMixin
# security.py is a re-export shim (FEAT-252) over core:
from parrot.security.command_sanitizer import (   # security.py:17-25
    CommandSanitizer, SecurityPolicy, CommandSecurityError, CommandVerdict,
)
```

### Existing Class Signatures

```python
# packages/ai-parrot-tools/src/parrot_tools/shell_tool/tool.py
class ShellTool(SecureShellMixin, AbstractTool):                     # :33
    name: str = "shell"                                              # :46
    args_schema = ShellToolArgs                                      # :48
    def __init__(self, security_policy: Any = _NO_POLICY, **kwargs): # :50
        # _NO_POLICY → SecurityPolicy.moderate(); explicit None → no sanitizer  # :60-64
        # ← INSERTION POINT for the rtk probe (Module 2)

    def _make_action_from_cmdobj(self, spec: CommandObject, ...) -> BaseAction:  # :167
        raw = spec.command.strip()                                   # :186
        # ← INSERTION POINT for the rtk prefix (Module 3); assert_command_safe
        #   already ran at :146 (command mode) / :254 (plan mode)
        # dispatch: ls→ListFiles | .sh|./|/→ExecFile | rest→RunCommand  # :193-198

    def _result_to_dict(self, r: ActionResult) -> Dict[str, Any]:    # :200-212
        # keys: type, cmd, work_dir, ok, exit_code, timed_out, duration,
        #       stdout, stderr, metadata  ← metadata is where rtk_wrapped goes
```

```python
# packages/ai-parrot-tools/src/parrot_tools/shell_tool/security.py
class SecureShellMixin:                                              # :45
    _sanitizer: Optional[CommandSanitizer] = None                    # :68  (None → ALL allowed)
    def set_security_policy(self, policy: SecurityPolicy) -> None:   # :70
    def validate_command(self, command: str) -> ValidationResult:    # :78  (None → ALLOWED)
    def assert_command_safe(self, command: str) -> None:             # :97  (NEEDS_REVIEW ⇒ denied)
```

```python
# packages/ai-parrot/src/parrot/security/command_sanitizer.py (core, FEAT-252)
class CommandVerdict(str, Enum):                                     # :49
class CommandSecurityError(Exception):                               # :140
_DEFAULT_DENIED_COMMANDS: Set[str] = { ... }                         # :170  ← guard G6 target
_MODERATE_SAFE_DEFAULTS: Set[str] = { ... }                          # :210  (rtk NOT present — verified;
                                                                     #  includes cat → agent can read tee files)
class SecurityPolicy:                                                # :327
    denied_commands: Set[str] = field(                               # :368
        default_factory=lambda: _DEFAULT_DENIED_COMMANDS.copy())
    @classmethod
    def moderate(cls, allowed_commands=None, sandbox_dir=None): ...  # :434 (merges _MODERATE_SAFE_DEFAULTS :452,
                                                                     #  denied=_DEFAULT_DENIED_COMMANDS.copy() :458)
class CommandSanitizer:                                              # :570
    def _extract_base_command(self, token: str) -> str: ...          # :770  (normalizes /usr/bin/rtk → rtk)
    def _check_command_access(self, base_cmd: str): ...              # :827-856  (per-level allowlist)
    def _check_pipe_segments(self, command: str): ...                # :858-885  (validates every pipe segment)
```

```python
# packages/ai-parrot-tools/src/parrot_tools/shell_tool/actions.py
class RunCommand(BaseAction):                                        # :10
    # argv = ["/bin/sh", "-lc", self.cmd]                            # :14  ← wrapped cmd runs here
class ExecFile(BaseAction):                                          # :17
    # argv = ["/bin/sh", self.cmd]                                   # :21  ← NEVER wrapped
class ListFiles(BaseAction):                                         # :24  ← NEVER wrapped
```

### Integration Points

| New Component | Connects To | Via | Verified At |
|---|---|---|---|
| rtk probe (`_probe_rtk`) | `ShellTool.__init__` | called after `set_security_policy` pattern | `tool.py:59-64` |
| `RTK_COMMAND_MAP` lookup | `_make_action_from_cmdobj` | prefix on the `RunCommand` branch only | `tool.py:197-198` |
| guard G6 | `_DEFAULT_DENIED_COMMANDS` | new set entry `"rtk"` | `command_sanitizer.py:170` |
| metadata `rtk_wrapped` | `ActionResult.metadata` | via `_result_to_dict` passthrough | `tool.py:211` |
| plan-mode wrapping | `_run_plan` → `_make_action_from_cmdobj` | validation precedes at `:254`; note `action.type_name` override at `:258` | `tool.py:246-258` |

### Key Attributes & Constants

- `ShellTool._sanitizer` → `Optional[CommandSanitizer]`; `None` means
  **everything allowed** (`security.py:68`, `tool.py:64`).
- `assert_command_safe()` invoked at `tool.py:146` (command mode) and
  `:254` (plan mode), **before** actions are built.
- `CommandObject.env` → per-command env (`tool.py:180-181`) — the reason
  Option C (PATH shim) was rejected as evadable.
- `_DEFAULT_DENIED_COMMANDS` currently spans destructive, privilege-
  escalation, network, interpreter, sysadmin, package-manager, and
  container categories (`command_sanitizer.py:170-206`) — `rtk` joins as
  a new "universal execution wrapper" entry.
- Existing test suites to anchor new tests:
  `packages/ai-parrot-tools/tests/shell_tool/` — includes
  `test_command_sanitizer.py`, `test_secure_shell_mixin.py`,
  `test_security_levels.py`, `test_shell_tool_security.py` (verified).

### Does NOT Exist (Anti-Hallucination)

- ~~`rtk` binary installed on the dev machine~~ — `which rtk` empty
  (verified 2026-07-27). It is a deployment dependency to provision;
  unit tests MUST mock the probe (see §4 fixture).
- ~~Any reference to `rtk` in Python code under `parrot/` or
  `parrot_tools/`~~ — zero occurrences; everything existing is brainstorm
  mentions under `sdd/proposals/`.
- ~~`rtk` as a linkable library / `rtk::filter()`~~ — it is a **binary**
  crate (Clap `Commands` enum in `src/main.rs`).
- ~~`parrot/tools/shell/tool.py`~~ — path from the sandbox-hardening
  brainstorm; does not exist. Real:
  `packages/ai-parrot-tools/src/parrot_tools/shell_tool/tool.py`.
- ~~Any wrapping/output-filtering mechanism in `ShellTool` today~~ —
  built from scratch by this feature.
- ~~Verified rtk subcommand surface~~ — `rtk test/err/lint/proxy/gain`
  and per-command routing were confirmed only against the upstream README
  (web, 2026-07-27), NOT against a pinned binary. Implementation MUST
  verify the exact surface, `rtk gain` JSON flags, tee pointer format,
  and exit-code passthrough against the release it pins (§8).
- ~~`RTK_MIN_VERSION`, `RTK_COMMAND_MAP`, `_probe_rtk`, `_wrap_with_rtk`,
  `rtk_savings`, `scripts/install-rtk.sh`,
  `docs/migration/feat-380-rtk.md`~~ — all created by this feature.

---

## 7. Implementation Notes & Constraints

### Patterns to Follow

- Probe in `__init__` follows the existing configuration pattern of
  `set_security_policy()` at `tool.py:59-64` — fail loud at construction,
  cache on the instance.
- Logging via `self.logger` (never print); the newer-version warning goes
  through `self.logger.warning`.
- Keep the rewrite prefix-pure (G7): a single string concatenation
  `f"rtk {subcmd} {raw}"` — no shlex re-quoting, no argument reordering.
- Google-style docstrings + strict type hints on every new function.
- The guard entry in `_DEFAULT_DENIED_COMMANDS` carries an inline comment
  referencing this spec (mirrors how FEAT-252 documents category intent).

### Known Risks / Gotchas

- **rtk CLI surface churns every few days** (v0.44.0 on 2026-07-26; RCs
  daily). Mitigation: exact pin (`RTK_MIN_VERSION`) + install script +
  warn-don't-fail on newer versions; the command map and gain flags are
  verified against the pin, not against "latest".
- **Tee-file readability**: G5 relies on the agent reading
  `~/.local/share/rtk/tee/*.log`. Under a `sandbox_dir`-confined policy,
  path checks may deny reads outside the sandbox — verify during
  implementation and document the interaction (worst case: the pointer is
  still visible and the operator can read the file).
- **Exit-code passthrough is asserted upstream but not documented
  precisely** — distinguish "rtk itself failed" from "wrapped command
  failed" against the pinned release; integration test
  `test_exit_code_passthrough` covers it.
- **`security_policy=None` instances**: no sanitizer → guard G6 does not
  apply there (pre-existing "everything allowed" mode, documented). The
  tool-side prefix still applies.
- **Plan mode forces `action.type_name = step.type`** (`tool.py:258`) —
  make sure wrapping metadata survives that override.
- **Never wrap commands containing shell operators** even when the base
  command is mapped — `/bin/sh -lc` would give rtk only the first
  pipeline stage's semantics, breaking the prefix-pure guarantee.
- **Concurrent edits to `command_sanitizer.py`**: it is core and shared —
  check for other in-flight features touching it before merging Module 1.

### External Dependencies

| Package | Version | Reason |
|---|---|---|
| `rtk` (binary, `rtk-ai/rtk`) | exact pin written at implementation time (latest stable was v0.44.0 on 2026-07-26) | per-command output filtering, tee-on-failure, gain telemetry. Apache-2.0, Rust binary crate — NOT a Python dependency; provisioned via `scripts/install-rtk.sh` |
| `shutil.which` | stdlib | availability probe |

---

## 8. Open Questions

> Decision trail. Resolved items are settled — do not re-open during
> implementation.

- [x] What happens if rtk is not installed? — *Resolved in brainstorm*:
      **Hard dependency: `ShellTool.__init__` fails with an explicit
      error. On by default, no escape hatch. Never silent passthrough.**
- [x] When does the missing-rtk failure surface? — *Resolved in
      brainstorm*: **At init (probe `shutil.which` + version), not on the
      first command.**
- [x] rtk version policy? — *Resolved in brainstorm*: **Tested minimum
      enforced at init; warning (not failure) on newer versions; the
      documented install pins the tested release.**
- [x] Which commands get wrapped and how? — *Resolved in brainstorm*:
      **Maintained command→rtk-subcommand map; unmapped commands run
      unwrapped. No universal `rtk proxy`.**
- [x] Output on wrapped-command failure? — *Resolved in brainstorm, refined
      2026-07-27 (spec session) against rtk's real tee behavior*: full
      output goes to a tee **file**, not stdout. **Decision: keep rtk's
      failure output as-is (filtered summary + tee-file pointer);
      ShellTool does not parse or inline the tee file; the agent reads it
      on demand.** Rejected alternatives: tool inlines tee file (parsing
      fragility), re-run unwrapped (double execution of side effects).
- [x] How is `rtk` neutralized as an allowlist bypass? — *Resolved in
      brainstorm*: **Direct denial in the core sanitizer; only the tool
      adds the prefix, after validation; prefix-pure rewrite. No
      strip-and-revalidate.**
- [x] Is `ClaudeAgentClient` rtk integration included? — *Resolved in
      brainstorm*: **No — remains the independent follow-up
      `rtk-subprocess-filter`.**
- [x] Pin the minimum rtk release? — *Resolved 2026-07-27 (spec session)*:
      **Pinned at implementation time**: the implementing task installs
      the latest stable at implementation start, verifies the CLI surface
      (subcommands, `rtk gain --format json` flags, tee pointer format,
      exit-code passthrough), and writes the exact pin into
      `RTK_MIN_VERSION` + install script + docs.
- [x] Initial command→subcommand map contents? — *Resolved 2026-07-27
      (spec session)*: **`pytest`, `npm`, `git`, `cargo`, `ruff`, `uv`** —
      exact rtk subcommand per entry verified against the pinned release.
- [x] Provisioning deliverables? — *Resolved 2026-07-27 (spec session)*:
      **`scripts/install-rtk.sh` + migration doc with reference
      Dockerfile/CI guidance + CHANGELOG entry, all in v1.**
- [x] Savings telemetry in v1? — *Resolved 2026-07-27 (spec session)*:
      **Yes — `rtk_wrapped`/`rtk_original_cmd` result metadata plus
      `ShellTool.rtk_savings()` (`rtk gain` JSON) in v1.**
- [ ] Verify tee-file readability under `sandbox_dir`-confined policies
      (does a confined MODERATE policy allow `cat
      ~/.local/share/rtk/tee/...`?) — during implementation, with the
      pinned binary. — *Owner: implementing agent*
- [ ] Confirm rtk's exit-code passthrough semantics and how to
      distinguish rtk's own failures from the wrapped command's — during
      implementation, against the pinned release. — *Owner: implementing
      agent*

---

## Worktree Strategy

- **Default isolation unit**: per-spec — one worktree, sequential tasks.
- **Ordering constraint (normative)**: Module 1 (sanitizer guard) merges
  before or together with Module 3 (prefix insertion), never after.
- **Parallelizable**: Module 5 (install script + docs) can proceed in
  parallel once the pin is fixed by Module 2; everything else is serial.
- **Worktree note**: the surface is two source files plus tests — per the
  "When NOT to Use Worktrees" policy this feature may be implemented
  directly on a short-lived feature branch if the task count stays small.
- **Cross-feature dependencies**: none blocking. Watch
  `packages/ai-parrot/src/parrot/security/command_sanitizer.py` for
  concurrent in-flight edits (core, shared since FEAT-252). Fully
  independent of the REPL sandbox worker and the frozen ToolResult
  compression pipeline.

---

## Revision History

| Version | Date | Author | Change |
|---|---|---|---|
| 0.1 | 2026-07-27 | Jesus Lara (with Claude) | Initial draft from shelltool-hardening brainstorm (Option B) + spec-session resolutions (tee behavior, version pin policy, command map, v1 scope) |
