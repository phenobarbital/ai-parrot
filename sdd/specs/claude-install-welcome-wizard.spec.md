---
type: feature
base_branch: dev
projects: [ai-parrot, sdd-tooling]
tags: [installer, sandbox, rich, cli, onboarding, bwrap]
---

# Feature Specification: `parrot claude install` Welcome Wizard

**Feature ID**: FEAT-799
**Date**: 2026-11-04
**Author**: Jesus Lara
**Status**: draft
**Target version**: next

---

## 1. Motivation & Business Requirements

### Problem Statement

After running `parrot claude install`, users on Linux (kernel ≥ 6.5,
Ubuntu 24.04+ with AppArmor) hit opaque `apply-seccomp: write
/proc/self/setgroups (nested userns is capability-restricted)` errors when
launching `parrot sdd launch worker` because Claude Code's native sandbox
uses Bubblewrap internally, and the SDD worktree sandbox also uses Bubblewrap
— requiring **nested user namespaces** that AppArmor blocks by default.

The fix (kernel sysctls + an AppArmor profile for bwrap) is documented in
`docs/sdd/sandbox-setup.md` and detected by `parrot self doctor --sdd`, but:

1. New users don't know to run `doctor` before their first worker launch.
2. The install command prints a bare `click.echo` checklist with no guidance
   about OS prerequisites.
3. There is no interactive way to choose between the native Claude Code
   sandbox and the legacy Bubblewrap wrapper during install — the user must
   know about `PARROT_SDD_SANDBOX_MODE` or the `pyproject.toml` key.

### Goals

- Show a **rich-text welcome message** (via `rich.markdown.Markdown`) at the
  end of `parrot claude install` that includes OS-specific guidance when
  running on Linux with AppArmor.
- **Auto-detect** nested Bubblewrap support (reusing the existing
  `_check_bwrap_sandbox()` logic from `doctor.py`) and, when it fails,
  render the fix steps as copyable fenced code blocks.
- Provide an **interactive sandbox-mode wizard** that lets the user choose
  between native (recommended) and legacy mode, and persists the choice.
- Support **non-interactive** invocation (`--non-interactive`,
  `--sandbox-mode native|legacy`) so CI and automation pipelines skip
  the wizard while still receiving the detection output.
- Ensure the install remains **idempotent** — re-running it with the same
  flags produces the same result.

### Non-Goals (explicitly out of scope)

- Modifying `parrot sdd install` — the wizard lives in `parrot claude install`
  only. `parrot sdd install` continues to deploy SDD assets without an
  interactive step.
- Automatically applying the OS fix (writing to `/etc/apparmor.d/`,
  running `sysctl`) — the wizard shows the commands; the user runs them.
- Supporting non-bwrap sandboxes (Docker, Flatpak, etc.).
- Windows/macOS sandbox detection — bwrap is Linux-only; the wizard is
  skipped silently on other platforms.

---

## Governing Decisions

<!-- decision audit not configured in this repository -->

---

## 2. Architectural Design

### Overview

The feature adds three components wired into the tail of the existing
`parrot claude install` Click command:

1. **`WelcomeRenderer`** — a thin function that composes a `rich.markdown.Markdown`
   document from a Jinja2-like template string, populated with the install
   results and the bwrap diagnostic outcome, and prints it through the
   shared `get_console()`.
2. **`sandbox_mode_wizard()`** — an interactive prompt (using
   `rich.prompt.Prompt` + `rich.prompt.Confirm`) that asks the user to pick
   a sandbox mode (`native` / `legacy` / skip), explains what each means,
   and writes the result to `pyproject.toml [tool.parrot.sdd] sandbox` (the
   key `resolve_sandbox_mode()` already reads).
3. **CLI flag additions** to the existing `install` Click command:
   `--sandbox-mode native|legacy`, `--non-interactive`, `--no-welcome`.

### Component Diagram

```
parrot claude install
  ├── (existing) install_claude_integration()
  ├── (existing) build wiki plane
  ├── NEW: _run_bwrap_diagnostic()
  │        └── reuses _check_bwrap_sandbox() from doctor.py
  ├── NEW: _render_welcome(actions, bwrap_checks, sandbox_mode)
  │        └── rich.markdown.Markdown → get_console().print()
  └── NEW: _sandbox_mode_wizard(root, non_interactive, preset)
           ├── rich.prompt.Prompt (interactive)
           └── _write_sandbox_config(root, mode) → pyproject.toml
```

### Integration Points

| Component | Integrates with | How |
|---|---|---|
| `_run_bwrap_diagnostic()` | `doctor._check_bwrap_sandbox()` | Direct import; the function is already pure (no side effects) |
| `_render_welcome()` | `parrot.cli.console.get_console()` | Shared Rich Console singleton |
| `_sandbox_mode_wizard()` | `resolve_sandbox_mode()` in `native_claude_sandbox.py` | Reads existing mode; writes `pyproject.toml` key that the resolver already reads |
| CLI flags | `cli.py::install()` Click command | New `@click.option` decorators |

---

## 3. Module Breakdown

### M1 — Bwrap Diagnostic Bridge (`welcome.py`)

**Location**: `packages/ai-parrot/src/parrot/knowledge/wiki/claude_code/welcome.py` (new file)

Extracts the bwrap diagnostic from `doctor.py` into a reusable call:

```python
# verified: packages/ai-parrot/src/parrot/self_/doctor.py:221
from parrot.self_.doctor import DoctorCheck, _check_bwrap_sandbox

def run_bwrap_diagnostic() -> list[DoctorCheck]:
    """Run the bwrap nested-userns diagnostic (Linux-only; empty list elsewhere)."""
    return _check_bwrap_sandbox()
```

Note: `_check_bwrap_sandbox` is currently private. M1 will either promote it
to a public name or import the private symbol within the same package boundary.

### M2 — Welcome Renderer (`welcome.py`)

**Location**: same file as M1.

```python
from rich.markdown import Markdown  # rich is already a dependency
from parrot.cli.console import get_console  # verified: packages/ai-parrot/src/parrot/cli/console.py:21

def render_welcome(
    actions: list[str],
    bwrap_checks: list[DoctorCheck],
    sandbox_mode: str | None,
    *,
    non_interactive: bool = False,
) -> None:
    """Print a rich-text post-install welcome with OS guidance."""
```

The renderer builds a markdown string with:
- A header: `# AI-Parrot — Claude Code Integration Installed`
- A summary table of installed components (from `actions`)
- A `## Sandbox Status` section:
  - If all bwrap checks pass: green confirmation
  - If nested bwrap fails: the full fix from `docs/sdd/sandbox-setup.md`
    rendered as fenced code blocks (sysctls + AppArmor profile)
  - If not Linux: omitted
- Current sandbox mode (if set)
- A `## Next Steps` section

### M3 — Sandbox Mode Wizard (`welcome.py`)

**Location**: same file.

```python
from rich.prompt import Prompt

def sandbox_mode_wizard(
    root: Path,
    *,
    non_interactive: bool = False,
    preset: str | None = None,
) -> str | None:
    """Interactive sandbox-mode selection; returns the chosen mode or None (skipped)."""
```

Behavior:
- If `preset` is given (from `--sandbox-mode`), validate it and write immediately.
- If `non_interactive`, skip the prompt, return the current mode (or `None`).
- Otherwise, show:
  ```
  Sandbox mode for SDD sessions:

    1. native (recommended) — Claude Code's built-in sandbox; requires
       nested bwrap (the OS fix above).
    2. legacy — SDD's own Bubblewrap wrapper (no nested namespaces needed,
       but no Claude Code sandbox protection).
    3. skip — keep current setting, decide later.

  Choice [1]:
  ```
- Map `1` → `"required"`, `2` → `"legacy"`, `3` → `None`.
- Write to `pyproject.toml [tool.parrot.sdd] sandbox = "<mode>"`.

### M4 — CLI Wiring (`cli.py` modifications)

**Location**: `packages/ai-parrot/src/parrot/knowledge/wiki/claude_code/cli.py` (existing)

Add three `@click.option` decorators to the `install` command:

```python
@click.option("--sandbox-mode", type=click.Choice(["native", "legacy"]), default=None,
              help="Set the SDD sandbox mode (native or legacy) without prompting.")
@click.option("--non-interactive", is_flag=True, default=False,
              help="Skip interactive prompts; use defaults or --sandbox-mode.")
@click.option("--no-welcome", is_flag=True, default=False,
              help="Suppress the rich welcome message.")
```

At the end of the `install()` function body, after the existing
`click.secho(...)` line (line 214–217), insert:

```python
if not no_welcome:
    from parrot.knowledge.wiki.claude_code.welcome import (
        render_welcome, run_bwrap_diagnostic, sandbox_mode_wizard,
    )
    bwrap_checks = run_bwrap_diagnostic()
    chosen = sandbox_mode_wizard(root, non_interactive=non_interactive, preset=sandbox_mode)
    render_welcome(actions, bwrap_checks, chosen, non_interactive=non_interactive)
```

### Delegation-eligible modules

| Module | Delegation-eligible? | Notes |
|---|---|---|
| M1 | Yes | Thin bridge, mechanical |
| M2 | Yes | String composition + rich print; patterns decided in spec |
| M3 | Yes | Prompt logic + TOML write; exact prompt text in spec |
| M4 | Yes | Click option additions + wiring call; mechanical |

---

## 4. Test Specification

### Unit Tests

All tests in `packages/ai-parrot/tests/knowledge/wiki/test_welcome.py` (new).

| Test | What it verifies |
|---|---|
| `test_bwrap_diagnostic_non_linux` | Returns empty list when `sys.platform != "linux"` |
| `test_bwrap_diagnostic_delegates_to_doctor` | Calls `_check_bwrap_sandbox` and returns its result |
| `test_render_welcome_all_ok` | Prints markdown with green sandbox status when all checks pass |
| `test_render_welcome_bwrap_fails` | Prints markdown with fix instructions when nested bwrap fails |
| `test_render_welcome_no_checks` | Omits sandbox section when checks list is empty (non-Linux) |
| `test_wizard_preset_native` | Writes `required` to pyproject.toml when `preset="native"` |
| `test_wizard_preset_legacy` | Writes `legacy` to pyproject.toml when `preset="legacy"` |
| `test_wizard_non_interactive_skips` | Returns None, writes nothing when `non_interactive=True` and no preset |
| `test_wizard_interactive_choice_1` | Mocks `Prompt.ask` returning "1", writes `required` |
| `test_wizard_interactive_choice_3` | Mocks `Prompt.ask` returning "3", writes nothing |
| `test_wizard_creates_toml_section` | Creates `[tool.parrot.sdd]` section when absent |
| `test_wizard_preserves_existing_toml` | Keeps other pyproject.toml content when writing sandbox key |

### Integration Tests

| Test | What it verifies |
|---|---|
| `test_install_cli_non_interactive_flag` | `parrot claude install --non-interactive --no-build` exits 0, no prompt |
| `test_install_cli_sandbox_mode_flag` | `--sandbox-mode native` writes the config without prompting |

---

## 5. Acceptance Criteria

1. `parrot claude install` on Linux renders a rich-text welcome that includes
   bwrap diagnostic results and the fix commands when nested bwrap fails.
2. `parrot claude install` on macOS/Windows renders the welcome without the
   sandbox section.
3. The interactive wizard presents three choices (native/legacy/skip) and
   writes the selection to `pyproject.toml [tool.parrot.sdd] sandbox`.
4. `--sandbox-mode native` sets `sandbox = "required"` without prompting.
5. `--sandbox-mode legacy` sets `sandbox = "legacy"` without prompting.
6. `--non-interactive` skips the wizard entirely.
7. `--no-welcome` suppresses the rich output (existing `click.echo` lines
   remain).
8. Re-running `parrot claude install` with the same flags is idempotent
   (the TOML key is overwritten, not appended).
9. All existing `parrot claude install` tests continue to pass.
10. The bwrap diagnostic output matches `parrot self doctor --sdd` for the
    `sdd: bwrap` and `sdd: bwrap nested userns` checks.

---

## 6. Codebase Contract

### Verified Imports

| Symbol | Path | Line |
|---|---|---|
| `DoctorCheck` | `packages/ai-parrot/src/parrot/self_/doctor.py` | 40 |
| `_check_bwrap_sandbox` | `packages/ai-parrot/src/parrot/self_/doctor.py` | 221 |
| `get_console` | `packages/ai-parrot/src/parrot/cli/console.py` | 21 |
| `Console` | `rich.console` (third-party) | — |
| `Markdown` | `rich.markdown` (third-party) | — |
| `Prompt` | `rich.prompt` (third-party) | — |
| `install_claude_integration` | `packages/ai-parrot/src/parrot/knowledge/wiki/claude_code/installer.py` | (imported in cli.py:21) |
| `resolve_sandbox_mode` | `packages/ai-parrot/src/parrot/sdd/scripts/native_claude_sandbox.py` | 246 |
| `SANDBOX_MODES` | `packages/ai-parrot/src/parrot/sdd/scripts/native_claude_sandbox.py` | 38 |

### Existing Signatures

| Symbol | Signature | Path:Line |
|---|---|---|
| `_check_bwrap_sandbox()` | `def _check_bwrap_sandbox() -> list[DoctorCheck]` | `doctor.py:221` |
| `get_console()` | `def get_console() -> Console` | `console.py:21` |
| `resolve_sandbox_mode()` | `def resolve_sandbox_mode(repo_root: Path) -> str` | `native_claude_sandbox.py:246` |
| `install()` (Click command) | 14 parameters, returns `None` | `cli.py:132-217` |

### Does NOT Exist

| What was looked for | Result |
|---|---|
| `parrot.knowledge.wiki.claude_code.welcome` | Does NOT exist — M1/M2/M3 create it |
| `--sandbox-mode` option on `install` command | Does NOT exist — M4 adds it |
| `--non-interactive` option on `install` command | Does NOT exist — M4 adds it |
| `--no-welcome` option on `install` command | Does NOT exist — M4 adds it |
| `rich.markdown` import in `claude_code/` | Not currently imported anywhere in this package |
| `[tool.parrot.sdd] sandbox` writer | No existing code writes this key; `resolve_sandbox_mode()` only reads it |

### Edit Sites

Base commit: `179b5bd36b`

| File | Anchor | Line | Count | Action |
|---|---|---|---|---|
| `packages/ai-parrot/src/parrot/knowledge/wiki/claude_code/cli.py` | `def install(` | 132 | 1 | Add new Click options + wizard wiring |
| `packages/ai-parrot/src/parrot/knowledge/wiki/claude_code/cli.py` | `click.secho(` (the final success line) | 214 | 1 | Insert welcome call after this line |
| `packages/ai-parrot/src/parrot/knowledge/wiki/claude_code/welcome.py` | — | — | — | CREATE |
| `packages/ai-parrot/tests/knowledge/wiki/test_welcome.py` | — | — | — | CREATE |

---

## 7. Implementation Notes

### Patterns to Follow

- **Click option style**: follow the existing `--compaction/--no-compaction`
  boolean pattern in `cli.py` for `--no-welcome`. Use `click.Choice` for
  `--sandbox-mode`.
- **Lazy imports**: the welcome module imports `rich.markdown`, `rich.prompt`
  and `parrot.sdd.scripts.native_claude_sandbox` lazily — only when the
  wizard actually runs — to avoid adding startup cost.
- **TOML writing**: use `tomllib` (read) + manual string manipulation or
  `tomli_w` (write) to update `pyproject.toml`. The project already has
  `tomllib` in stdlib. For writing, prefer the minimal approach: read the
  file, find/insert the `[tool.parrot.sdd]` section, set the `sandbox` key.
  Do NOT use `tomlkit` unless already a dependency.
- **`_check_bwrap_sandbox` visibility**: promote to `check_bwrap_sandbox`
  (public) in `doctor.py` to make the cross-package import clean, and alias
  the old `_check_bwrap_sandbox = check_bwrap_sandbox` for compatibility
  within the module.

### Known Risks / Gotchas

- **TOML write ordering**: `tomllib` can read but not write. Writing with
  string manipulation risks corrupting comments or formatting. Mitigate by
  keeping the write minimal: only the `[tool.parrot.sdd]` table and
  `sandbox` key. If `tomli_w` is not available, fall back to appending the
  section.
- **`_check_bwrap_sandbox()` is private**: importing a private function
  across package boundaries is fragile. M1 should promote it or wrap it.
- **Sandbox mode `off`/`legacy` cannot be set from `pyproject.toml`**:
  `resolve_sandbox_mode()` raises `ValueError` for those values in the TOML
  (they require the env var). The wizard must set `legacy` via the env var
  hint, OR the wizard only writes `required`/`preferred` and tells the user
  to set `PARROT_SDD_SANDBOX_MODE=legacy` if they chose legacy. Decision:
  the wizard writes `legacy` to a **separate** config path
  (`.claude/settings.local.json` env block setting
  `PARROT_SDD_SANDBOX_MODE=legacy`) since the pyproject.toml guard is
  intentional security policy.

### External Dependencies

| Library | Already a dependency? | Purpose |
|---|---|---|
| `rich` | Yes | Markdown rendering, Prompt |
| `click` | Yes | CLI framework |
| `tomllib` | Yes (stdlib 3.11+) | Read pyproject.toml |

---

## 8. Open Questions

- [x] Where does the wizard live? — *Resolved*: in `parrot claude install`
  (not `parrot sdd install`), because both SDD and Claude Code need the
  bwrap fix.
- [x] What sandbox modes does the wizard expose? — *Resolved*: "native"
  (maps to `required`) and "legacy" (maps to `PARROT_SDD_SANDBOX_MODE=legacy`
  via env in `.claude/settings.local.json`).
- [ ] Should `tomli_w` be added as a dependency for clean TOML writing, or
  is string manipulation sufficient? — *Owner: implementer*
- [ ] Should `_check_bwrap_sandbox` be promoted to public API or should M1
  duplicate the logic? — *Owner: implementer* (spec recommends promotion)

---

## 9. Design Research Cross-Check

Status: skipped (codex CLI not available in this session)

---

## Worktree Strategy

- **Isolation**: one worktree for FEAT-799.
- **Module dependency graph**: M4 → M1, M2, M3 (M4 imports and calls the
  functions M1/M2/M3 define). M1 is independent. M2 depends on M1 (uses
  diagnostic results). M3 is independent.
- **Shared files**: `cli.py` is modified only by M4.
- **Exclusive resources**: none.
- **Cross-feature dependencies**: none — the bwrap diagnostic and
  `resolve_sandbox_mode()` already exist on `dev`.

### Validation Contract

tests:
- packages/ai-parrot/tests/knowledge/wiki/test_welcome.py
- packages/ai-parrot/tests/self_/test_doctor_bwrap_public.py
markers: none
