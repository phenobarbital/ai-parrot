# TASK-5158: welcome.py — sandbox-mode wizard + config persistence

**Feature**: FEAT-799 — `parrot claude install` Welcome Wizard
**Spec**: `sdd/specs/claude-install-welcome-wizard.spec.md`
**Status**: done
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-5157
**Assigned-to**: unassigned

---

## Context

Implements spec §3 M3. **Persistence rule (spec §7 Known Risks, authoritative over
the looser wording of §3 M3 / AC3 / AC5)**: `resolve_sandbox_mode()` raises
`ValueError` when `pyproject.toml` sets `off`/`legacy` — that guard is intentional
security policy. Therefore:

| Choice | Writes |
|---|---|
| native | `pyproject.toml` `[tool.parrot.sdd] sandbox = "required"` **and** removes `PARROT_SDD_SANDBOX_MODE` from `.claude/settings.local.json` `env` (if present) |
| legacy | `.claude/settings.local.json` → `env.PARROT_SDD_SANDBOX_MODE = "legacy"`; pyproject untouched |
| skip   | nothing |

Spec AC5 ("`sandbox = "legacy"`") is satisfied via the env block — never write
`legacy` into pyproject.toml (it would break every `resolve_sandbox_mode` call).

---

## Scope

- Add to `welcome.py`: `sandbox_mode_wizard()`, `write_sandbox_mode()`, `current_sandbox_mode()`,
  and private helpers `_set_pyproject_sandbox()`, `_set_local_env()`.
- §8 Q3 decision: **no `tomli_w`/`tomlkit` dependency** (would need a pyproject edit and
  make this task exclusive). Use minimal text editing: replace an existing `sandbox = ...`
  line inside `[tool.parrot.sdd]`; else insert `sandbox = "required"` right after the
  `[tool.parrot.sdd]` header; else append `\n[tool.parrot.sdd]\nsandbox = "required"\n`.
  Verify with `tomllib.loads()` after editing and raise `RuntimeError` if it no longer parses
  (never write a corrupted file). Create pyproject.toml if missing.
- Idempotent (AC8): writing the same mode twice yields byte-identical files.
- Interactive prompt text exactly per spec §3 M3; `Prompt.ask(..., choices=["1","2","3"], default="1")`.
- Tests appended to `test_welcome.py`.

**NOT in scope**: CLI flags (TASK-5159); applying OS fixes.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/knowledge/wiki/claude_code/welcome.py` | MODIFY | add wizard (append below `render_welcome`) |
| `packages/ai-parrot/tests/knowledge/wiki/test_welcome.py` | MODIFY | append wizard tests |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
import tomllib                                                         # stdlib
from parrot.knowledge.wiki.claude_code.installer import _load_settings, _write_settings  # installer.py:246, :270
from parrot.sdd.scripts.native_claude_sandbox import MODE_ENV, resolve_sandbox_mode       # native_claude_sandbox.py:36, :246
from rich.prompt import Prompt                                         # third-party
```

### Existing Signatures to Use
```python
# installer.py:246 — returns None if missing; raises RuntimeError on bad JSON (do not clobber)
def _load_settings(path: Path) -> Optional[dict[str, Any]]
# installer.py:270 — mkdir parents + json.dumps(indent=2) + "\n"
def _write_settings(path: Path, settings: dict[str, Any]) -> None
# native_claude_sandbox.py:36
MODE_ENV = "PARROT_SDD_SANDBOX_MODE"
# native_claude_sandbox.py:246 — env var first, then pyproject; default "required"; ValueError on bad config
def resolve_sandbox_mode(repo_root: Path) -> str
```

### Does NOT Exist
- ~~`tomli_w` / `tomlkit`~~ — not dependencies; do not import
- ~~any existing writer of `[tool.parrot.sdd] sandbox`~~ — this task adds the first
- ~~`installer.load_settings` / `write_settings` (public)~~ — only the underscored names exist

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {"path": "packages/ai-parrot/src/parrot/knowledge/wiki/claude_code/welcome.py", "action": "MODIFY"},
    {"path": "packages/ai-parrot/tests/knowledge/wiki/test_welcome.py", "action": "MODIFY"}
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot/src/parrot/knowledge/wiki/claude_code/installer.py#_load_settings",
    "sym:packages/ai-parrot/src/parrot/knowledge/wiki/claude_code/installer.py#_write_settings",
    "sym:packages/ai-parrot/src/parrot/sdd/scripts/native_claude_sandbox.py#resolve_sandbox_mode"
  ]
}
```

---

## Implementation Blueprint

### Steps (in order)
1. Append the block below after `render_welcome` in welcome.py — *why*: same module per spec M3.
2. Implement `_set_pyproject_sandbox` with the text-edit rules — *why*: §8 Q3 decision, no new deps.
3. Append tests; use `tmp_path` as root; monkeypatch `welcome.Prompt.ask` is impossible with a lazy import — so import `Prompt` lazily via `from rich import prompt as _prompt` and patch `rich.prompt.Prompt.ask` instead.

### `welcome.py` (MODIFY — append at end of file)
```python
# occurrences: 1 (anchor: `def render_welcome(` created by TASK-5157)
# AFTER — append below the end of render_welcome

_MODE_MAP = {"native": "required", "legacy": "legacy"}
_WIZARD_TEXT = """Sandbox mode for SDD sessions:

  1. native (recommended) — Claude Code's built-in sandbox; requires
     nested bwrap (the OS fix above).
  2. legacy — SDD's own Bubblewrap wrapper (no nested namespaces needed,
     but no Claude Code sandbox protection).
  3. skip — keep current setting, decide later.
"""


def current_sandbox_mode(root: Path) -> str | None:
    """Return "native"/"legacy" as persisted for ``root``, or None if unset/unreadable."""
    # FILL IN: settings.local.json env MODE_ENV == "legacy" → "legacy";
    #          pyproject [tool.parrot.sdd].sandbox == "required" → "native"; else None. Never raise.


def write_sandbox_mode(root: Path, choice: str) -> str:
    """Persist ``choice`` ("native"|"legacy"); return the resolved mode string written."""
    if choice not in _MODE_MAP:
        raise ValueError(f"Unknown sandbox mode {choice!r}; expected native or legacy")
    # FILL IN: native → _set_pyproject_sandbox(root, "required") + _set_local_env(root, None)
    #          legacy → _set_local_env(root, "legacy")  — NEVER write legacy to pyproject (Context table)
    return _MODE_MAP[choice]


def _set_pyproject_sandbox(root: Path, value: str) -> None:
    """Set [tool.parrot.sdd] sandbox = value with minimal text edits; validate with tomllib."""
    # FILL IN: rules in Scope; RuntimeError if result fails tomllib.loads; skip write if unchanged


def _set_local_env(root: Path, value: str | None) -> None:
    """Set (or remove when None) env[MODE_ENV] in .claude/settings.local.json."""
    from parrot.knowledge.wiki.claude_code.installer import _load_settings, _write_settings
    from parrot.sdd.scripts.native_claude_sandbox import MODE_ENV
    # FILL IN: load (or {}), mutate env dict, drop empty env, write only if changed


def sandbox_mode_wizard(root: Path, *, non_interactive: bool = False, preset: str | None = None) -> str | None:
    """Interactive sandbox-mode selection; returns the chosen mode ("native"/"legacy") or None (skipped)."""
    if preset is not None:
        write_sandbox_mode(root, preset)
        return preset
    if non_interactive:
        return current_sandbox_mode(root)   # spec: return current mode, write nothing
    from rich.prompt import Prompt

    from parrot.cli.console import get_console

    get_console().print(_WIZARD_TEXT)
    answer = Prompt.ask("Choice", choices=["1", "2", "3"], default="1", console=get_console())
    # FILL IN: "1" → native, "2" → legacy (write_sandbox_mode), "3" → return current_sandbox_mode(root)
```
Also add `from pathlib import Path` to the module imports.

**Why**: return values are the *user-facing* names ("native"/"legacy") — TASK-5157's
renderer formats those; spec test `test_wizard_non_interactive_skips` expects `None` when nothing is persisted.

### Tests to append (`test_welcome.py`)
```python
def test_wizard_preset_native(tmp_path): ...           # FILL IN: pyproject has sandbox = "required"; resolve_sandbox_mode(tmp_path)=="required" (with MODE_ENV unset via monkeypatch.delenv)
def test_wizard_preset_legacy(tmp_path): ...           # FILL IN: settings.local.json env == legacy; pyproject absent/untouched
def test_wizard_non_interactive_skips(tmp_path): ...   # FILL IN: returns None, no files created
def test_wizard_interactive_choice_1(tmp_path, monkeypatch): ...  # FILL IN: patch rich.prompt.Prompt.ask → "1"
def test_wizard_interactive_choice_3(tmp_path, monkeypatch): ...  # FILL IN: "3" → no files
def test_wizard_creates_toml_section(tmp_path): ...    # FILL IN: pyproject with only [project] → section appended
def test_wizard_preserves_existing_toml(tmp_path): ... # FILL IN: comments + other [tool.parrot.sdd] keys survive
def test_wizard_idempotent(tmp_path): ...              # FILL IN: write native twice → identical bytes (AC8)
def test_native_clears_legacy_env(tmp_path): ...       # FILL IN: legacy then native → MODE_ENV gone, other settings kept
```

### FILL IN checklist
- [ ] `current_sandbox_mode`, `write_sandbox_mode`, `_set_pyproject_sandbox`, `_set_local_env`, wizard branch
- [ ] nine tests

---

## Acceptance Criteria

- [ ] Spec AC3–AC6, AC8 (with legacy via env block, per Context)
- [ ] `resolve_sandbox_mode()` never raises on a repo the wizard wrote
- [ ] `ruff check` clean

---

## Validation Commands

- `pytest packages/ai-parrot/tests/knowledge/wiki/test_welcome.py -q`

---

## Agent Instructions

Standard SDD flow; close with `parrot sdd task close TASK-5158 claude-install-welcome-wizard verified`.

---

## Completion Note

Extended `welcome.py` with `current_sandbox_mode`, `write_sandbox_mode`, `sandbox_mode_wizard` and the TOML/local-env helpers; extended `test_welcome.py`.

Seat: gpt-5.6-terra · Backend: codex · Attempts: 1 · Duration: 224s · Tokens: n/a
Merge-tier validation: 15 passed. Review: orchestrator diff review, no corrections.
Note: `coder_record_review` failing server-side (see TASK-5156); not recorded.
