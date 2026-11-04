# TASK-5157: welcome.py — bwrap diagnostic bridge + rich welcome renderer

**Feature**: FEAT-799 — `parrot claude install` Welcome Wizard
**Spec**: `sdd/specs/claude-install-welcome-wizard.spec.md`
**Status**: done
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-5156
**Assigned-to**: unassigned

---

## Context

Implements spec §3 M1 + M2. Creates `claude_code/welcome.py` with
`run_bwrap_diagnostic()` (thin bridge to `doctor.check_bwrap_sandbox`) and
`render_welcome()` which composes a Markdown document and prints it via the
shared Rich console. When nested bwrap fails, the fix commands from
`docs/sdd/sandbox-setup.md` (Step 1 sysctls + Step 2 AppArmor profile) are
rendered as fenced ```bash blocks so they are copyable.

---

## Scope

- Create `welcome.py` with `run_bwrap_diagnostic()`, `build_welcome_markdown()` (pure,
  returns `str` — testable without a console) and `render_welcome()` (prints it).
- Sandbox section rules: empty checks → section omitted (non-Linux, AC2); all ok →
  "✅ nested Bubblewrap works"; any failed check → list failures (`name: detail`) and
  the two fenced fix blocks + verify command.
- Show the sandbox mode line when `sandbox_mode` is not None
  (`native` → "native (Claude Code sandbox, `required`)", `legacy` → "legacy (SDD Bubblewrap wrapper)").
- Write the tests listed below in `test_welcome.py`.

**NOT in scope**: the interactive wizard (TASK-5158), CLI flags (TASK-5159).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/knowledge/wiki/claude_code/welcome.py` | CREATE | M1 + M2 |
| `packages/ai-parrot/tests/knowledge/wiki/test_welcome.py` | CREATE | renderer + diagnostic tests |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from parrot.self_.doctor import DoctorCheck, check_bwrap_sandbox  # doctor.py:40; check_bwrap_sandbox created by TASK-5156
from parrot.cli.console import get_console, set_console           # verified: cli/console.py:21, :30
from rich.markdown import Markdown                                # third-party, rich already a dependency
from rich.console import Console                                  # tests only: Console(record=True, width=100)
```

### Existing Signatures to Use
```python
# packages/ai-parrot/src/parrot/self_/doctor.py:40
class DoctorCheck(BaseModel):
    name: str; ok: bool; detail: str = ""; fix: str = ""; informational: bool = False
# doctor check names produced (doctor.py:221-286): "sdd: bwrap", "sdd: bwrap nested userns" (and single-userns check)
# packages/ai-parrot/src/parrot/cli/console.py
def get_console() -> Console: ...                       # line 21
def set_console(console: Optional[Console]) -> None: ... # line 30 — tests inject a recording console
```

### Does NOT Exist
- ~~`parrot.knowledge.wiki.claude_code.welcome`~~ — created here
- ~~`rich.markdown` usage anywhere in `claude_code/`~~ — first use
- ~~a Jinja2 template for the welcome~~ — spec says "Jinja2-like"; use a plain f-string/`"\n".join`, NOT jinja2

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {"path": "packages/ai-parrot/src/parrot/knowledge/wiki/claude_code/welcome.py", "action": "CREATE"},
    {"path": "packages/ai-parrot/tests/knowledge/wiki/test_welcome.py", "action": "CREATE"}
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot/src/parrot/self_/doctor.py#DoctorCheck",
    "sym:packages/ai-parrot/src/parrot/cli/console.py#get_console",
    "sym:packages/ai-parrot/src/parrot/cli/console.py#set_console"
  ]
}
```

---

## Implementation Notes

- Import `rich.markdown` lazily inside `render_welcome` (spec §7 "Lazy imports").
- Keep `build_welcome_markdown` pure so tests assert on the string; one test also
  checks `render_welcome` prints through `get_console()` (inject via `set_console`, reset to `None` after).
- Fix text must match `docs/sdd/sandbox-setup.md` Steps 1–2 verbatim (AC10 spirit).

---

## Implementation Blueprint

### Steps (in order)
1. Create `welcome.py` with the block below — *why*: fixes the public surface TASK-5158/5159 import.
2. Fill the markdown body — *why*: content rules in Scope.
3. Write tests; run validation.

### `packages/ai-parrot/src/parrot/knowledge/wiki/claude_code/welcome.py` (CREATE)
```python
"""Post-install welcome and sandbox-mode wizard for ``parrot claude install`` (FEAT-799)."""

from __future__ import annotations

from parrot.self_.doctor import DoctorCheck, check_bwrap_sandbox

SYSCTL_FIX = """sudo sysctl -w kernel.apparmor_restrict_unprivileged_userns=0
sudo sysctl -w kernel.unprivileged_userns_clone=1
cat <<'EOF' | sudo tee /etc/sysctl.d/60-apparmor-namespace.conf
kernel.apparmor_restrict_unprivileged_userns=0
kernel.unprivileged_userns_clone=1
EOF
sudo sysctl --system"""

APPARMOR_FIX = """sudo tee /etc/apparmor.d/bwrap > /dev/null <<'EOF'
abi <abi/4.0>,
include <tunables/global>

profile bwrap /usr/bin/bwrap flags=(unconfined) {
  userns,
  include if exists <local/bwrap>
}
EOF
sudo apparmor_parser -r /etc/apparmor.d/bwrap"""

VERIFY_CMD = 'bwrap --ro-bind / / --dev /dev -- bwrap --ro-bind / / --dev /dev -- echo "nested works"'


def run_bwrap_diagnostic() -> list[DoctorCheck]:
    """Run the bwrap nested-userns diagnostic (Linux-only; empty list elsewhere)."""
    return check_bwrap_sandbox()


def build_welcome_markdown(actions: list[str], bwrap_checks: list[DoctorCheck], sandbox_mode: str | None) -> str:
    """Compose the welcome Markdown document (pure; no I/O)."""
    lines = ["# AI-Parrot — Claude Code Integration Installed", ""]
    # FILL IN: installed-components list from `actions` ("- ✓ <action>") — bounded by spec §3 M2
    # FILL IN: "## Sandbox Status" — omit when bwrap_checks == []; ok vs failed per Scope; fenced ```bash
    #          blocks with SYSCTL_FIX, APPARMOR_FIX, VERIFY_CMD; link docs/sdd/sandbox-setup.md — AC1/AC2
    # FILL IN: sandbox mode line when sandbox_mode is not None — Scope
    # FILL IN: "## Next Steps" (wikitoolkit query, /parrotwiki, `parrot self doctor --sdd`)
    return "\n".join(lines)


def render_welcome(
    actions: list[str],
    bwrap_checks: list[DoctorCheck],
    sandbox_mode: str | None,
    *,
    non_interactive: bool = False,
) -> None:
    """Print a rich-text post-install welcome with OS guidance."""
    from rich.markdown import Markdown

    from parrot.cli.console import get_console

    get_console().print(Markdown(build_welcome_markdown(actions, bwrap_checks, sandbox_mode)))
```
**Why this shape**: signatures are fixed by spec §3 M1/M2; `non_interactive` is accepted for
API stability (TASK-5159 passes it) even if unused by rendering. Fix strings are module
constants so tests and TASK-5158 can reference them.

### `packages/ai-parrot/tests/knowledge/wiki/test_welcome.py` (CREATE)
```python
"""FEAT-799 welcome renderer / wizard tests."""

from __future__ import annotations

import pytest
from rich.console import Console

from parrot.cli import console as console_mod
from parrot.knowledge.wiki.claude_code import welcome
from parrot.self_.doctor import DoctorCheck

OK = [DoctorCheck(name="sdd: bwrap", ok=True), DoctorCheck(name="sdd: bwrap nested userns", ok=True)]
FAIL = [DoctorCheck(name="sdd: bwrap", ok=True),
        DoctorCheck(name="sdd: bwrap nested userns", ok=False, detail="setgroups denied")]


def test_bwrap_diagnostic_non_linux(monkeypatch): ...      # FILL IN: patch doctor.sys.platform="darwin" → []
def test_bwrap_diagnostic_delegates_to_doctor(monkeypatch): ...  # FILL IN: patch welcome.check_bwrap_sandbox
def test_render_welcome_all_ok(): ...                      # FILL IN: "Sandbox Status" in md, no APPARMOR_FIX
def test_render_welcome_bwrap_fails(): ...                 # FILL IN: APPARMOR_FIX and SYSCTL_FIX in md
def test_render_welcome_no_checks(): ...                   # FILL IN: "Sandbox Status" not in md
def test_render_welcome_prints_to_shared_console(): ...    # FILL IN: set_console(Console(record=True)); finally set_console(None)
```

### FILL IN checklist
- [ ] `build_welcome_markdown` body — Scope + AC1/AC2
- [ ] six test bodies

---

## Acceptance Criteria

- [ ] Spec AC1, AC2 hold for `build_welcome_markdown`
- [ ] No real `bwrap` executed by tests
- [ ] `ruff check` clean

---

## Validation Commands

- `pytest packages/ai-parrot/tests/knowledge/wiki/test_welcome.py -q`

---

## Agent Instructions

Standard SDD flow; close with `parrot sdd task close TASK-5157 claude-install-welcome-wizard verified`.

---

## Completion Note

Added `parrot/knowledge/wiki/claude_code/welcome.py` (`run_bwrap_diagnostic`, `build_welcome_markdown`, `render_welcome`, fix-command constants) and `tests/knowledge/wiki/test_welcome.py`.

Seat: gpt-5.6-terra · Backend: codex · Attempts: 1 · Duration: 199s · Tokens: n/a
Merge-tier validation: 6 passed. Review: orchestrator diff review, no corrections.
Note: `coder_record_review` is failing server-side (see TASK-5156), so no review measurement was recorded; closed via `parrot sdd task close`.
