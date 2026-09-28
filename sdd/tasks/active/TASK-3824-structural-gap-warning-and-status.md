# TASK-3824: Build warning and `status` `Symbols:` line when the structural tier is missing

**Feature**: FEAT-609 — Honest structural tier, Svelte component symbols, module-local JS functions, and federated symbol queries in wikitoolkit
**Spec**: `sdd/specs/wikitoolkit-structural-coverage.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: S (< 2h)
**Depends-on**: TASK-3821
**Assigned-to**: unassigned

---

## Context

Spec §1 defect 1 / §3 Module 1 / G1. A build of 3,305 TS/Svelte files logged `0 symbols` at
INFO level, and nothing else. `status` claimed `javascript: tree-sitter`. With the predictive
`mode` (TASK-3821), the CLI can now say *before and during* a build that symbols are off, and
why.

---

## Scope

- Add a pure helper `_structural_gap_warning(scan) -> str | None` to `cli.py`. It returns the
  one-line warning when all of these hold:
  - `structural_enabled()` is true (the kill switch suppresses it);
  - `astgrep.is_available()` is false;
  - the scan holds at least one file whose `FileSlice.language` is structural-capable (every
    registered scanner except `python` and `luau`).

  Otherwise it returns `None`.
  Format: `"%d %s file(s) scanned without the structural tier: no sym: pages for them. Install
  'ai-parrot[wiki-languages]'"`, where `%s` is the comma-joined sorted language names.
- `build`: right after `scan` is produced and before `_pipeline` runs, call the helper and, when
  it returns text, emit it once. Log it with `_cli_logger.warning(...)`, and also print it with
  `click.echo(..., err=True)` unless `quiet`.
- `status`: add `payload["symbols"] = {"enabled": bool, "disabled_for": [names]}`, and print a
  `Symbols   :` line right after the `Structural:` line. The line reads one of:
  - `Symbols   : enabled`;
  - `Symbols   : disabled for javascript, php, rust, perl — pip install 'ai-parrot[wiki-languages]'`;
  - `Symbols   : disabled by configuration (structural tier switched off)` when the kill switch
    is off.
- Write tests.

**NOT in scope**: the re-ingest after installing (TASK-3828), and changing `mode` itself
(TASK-3821).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/knowledge/wiki/cli.py` | MODIFY | helper, build call site, status payload + line |
| `tests/knowledge/wiki/test_cli_structural_gap.py` | CREATE | unit + CLI tests |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from parrot.knowledge.wiki.languages import all_scanners                   # cli.py:67 (already imported)
from parrot.knowledge.wiki.languages import astgrep                        # add to cli.py
from parrot.knowledge.wiki.languages.render import structural_enabled, set_structural_enabled  # render.py:35, :45
from parrot.knowledge.wiki.repo_scan import scan_repository                # used by build, cli.py:1527
```

### Existing Signatures to Use
```python
# cli.py:106
_cli_logger = logging.getLogger("wikitoolkit.cli")
# cli.py:1454  def build(...)  — scan produced at cli.py:1527 (`scan = scan_repository(...)`),
#              then `        output_dir = config.storage_path(root)` at cli.py:1536 (occurrences: 1)
# repo_scan.py:148 class FileSlice(BaseModel): ... language: str | None = None   (repo_scan.py:184)
# cli.py:2129  (status payload; occurrences: 1)
        "structural": {name: s.mode for name, s in all_scanners().items()},
# cli.py:2180  (status text; occurrences: 1)
    click.echo(f"Structural: {payload['structural']}")
# languages/astgrep.py:74  def is_available() -> bool
```

### Does NOT Exist
- ~~`scan.languages` / `scan.language_counts`~~: count from `scan.files[*].language`.
- ~~A `--strict-structural` flag~~: out of scope, so do not add flags.

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {"path": "packages/ai-parrot/src/parrot/knowledge/wiki/cli.py", "action": "MODIFY"},
    {"path": "tests/knowledge/wiki/test_cli_structural_gap.py", "action": "CREATE"}
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot/src/parrot/knowledge/wiki/cli.py#build",
    "sym:packages/ai-parrot/src/parrot/knowledge/wiki/repo_scan.py#FileSlice",
    "sym:packages/ai-parrot/src/parrot/knowledge/wiki/languages/astgrep.py#is_available"
  ]
}
```

---

## Implementation Notes

### Key Constraints
- The helper is pure (no logging, no I/O), so it can be unit-tested directly.
- Structural-capable set: `{name for name in all_scanners() if name not in {"python", "luau"}}`.
  Python has stdlib `ast` symbols, and Luau never emits symbols (`languages/luau.py:9`).
- `status` must also print the line in scoped (`--ns`) mode. That is harmless, because it
  describes this process's scanners.

---

## Implementation Blueprint

### Steps (in order)
1. Add the helper near the other module-level helpers. *Why*: keeps `build` short.
2. Wire it into `build`. *Why*: G1, a loud warning once per build.
3. Extend the `status` payload and text. *Why*: G1, visibility before any build.
4. Write the tests and mutation-check.

### `packages/ai-parrot/src/parrot/knowledge/wiki/cli.py` (MODIFY) — helper
```python
# occurrences: 1 (verified: grep -c '^def _require_built(root: Path, config: WikiProjectConfig) -> BaseWikiStore:' cli.py)
# BEFORE — insert above `def _require_built(...)` (verified: cli.py:401)

_NON_STRUCTURAL_SCANNERS = frozenset({"python", "luau"})
_STRUCTURAL_INSTALL_HINT = "pip install 'ai-parrot[wiki-languages]'"


def _structural_capable_languages() -> list[str]:
    """Scanner names whose symbols come only from the ast-grep seam (FEAT-609)."""
    return sorted(name for name in all_scanners() if name not in _NON_STRUCTURAL_SCANNERS)


def _structural_gap_warning(scan: Any) -> str | None:
    """One-line warning when structural-capable files were scanned without ast-grep.

    Pure: no logging, no I/O. ``None`` when the kill switch is off, ast-grep is
    available, or the scan holds no structural-capable file.
    """
    if not structural_enabled() or astgrep.is_available():
        return None
    capable = set(_structural_capable_languages())
    counts: dict[str, int] = {}
    for file_slice in scan.files:
        if file_slice.language in capable:
            counts[file_slice.language] = counts.get(file_slice.language, 0) + 1
    if not counts:
        return None
    total = sum(counts.values())
    names = ", ".join(sorted(counts))
    return (
        f"{total} {names} file(s) scanned without the structural tier: "
        f"no sym: pages for them. Install {_STRUCTURAL_INSTALL_HINT}"
    )
```
Add `from parrot.knowledge.wiki.languages import astgrep` and
`from parrot.knowledge.wiki.languages.render import structural_enabled` to the imports.
Put them next to the `all_scanners` import at `cli.py:67`. Check first that neither is
already imported under another name.

### `cli.py` (MODIFY) — build call site
```python
# occurrences: 1 (verified: grep -c '        output_dir = config.storage_path(root)' cli.py)
# BEFORE — insert above `        output_dir = config.storage_path(root)` (verified: cli.py:1536)
        gap_warning = _structural_gap_warning(scan)
        if gap_warning:
            _cli_logger.warning(gap_warning)
            if not quiet:
                click.echo(f"WARNING: {gap_warning}", err=True)
```
**Why**: at this point `scan` exists for both the vault and the repository paths. A vault scan
holds no code files, so the helper returns `None` for it.

### `cli.py` (MODIFY) — status payload
```python
# occurrences: 1 (verified: grep -c '        "structural": {name: s.mode for name, s in all_scanners().items()},' cli.py)
# AFTER — insert below that line (verified: cli.py:2129)
        "symbols": _symbols_status(),
```
Add the helper next to `_structural_gap_warning`:
```python
def _symbols_status() -> dict[str, Any]:
    """``status``'s view of the symbol plane: which languages lack their tier."""
    if not structural_enabled():
        return {"enabled": False, "disabled_for": _structural_capable_languages(), "reason": "config"}
    missing = [name for name in _structural_capable_languages() if all_scanners()[name].mode != "ast-grep"]
    return {"enabled": not missing, "disabled_for": missing, "reason": "missing-extra" if missing else None}
```

### `cli.py` (MODIFY) — status text
```python
# occurrences: 1 (verified: grep -c "    click.echo(f\"Structural: {payload\['structural'\]}\")" cli.py)
# AFTER — insert below that line (verified: cli.py:2180)
    click.echo(f"Symbols   : {_format_symbols_status(payload['symbols'])}")
```
```python
def _format_symbols_status(info: dict[str, Any]) -> str:
    """Render the ``Symbols`` status line."""
    # FILL IN: "enabled" | "disabled by configuration (structural tier switched off)" |
    # "disabled for <names> — <_STRUCTURAL_INSTALL_HINT>" — bounded by §Scope wording
```

### `tests/knowledge/wiki/test_cli_structural_gap.py` (CREATE)
```python
"""FEAT-609 M1: the missing structural tier is loud, in build and in status."""

from __future__ import annotations

from parrot.knowledge.wiki import cli
from parrot.knowledge.wiki.languages import astgrep
from parrot.knowledge.wiki.languages.render import set_structural_enabled
from parrot.knowledge.wiki.repo_scan import scan_repository


def _scan(tmp_path, files: dict[str, str]):
    for rel, text in files.items():
        path = tmp_path / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
    return scan_repository(tmp_path, use_git=False)


def test_structural_gap_warning_text(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(astgrep, "is_available", lambda: False)
    warning = cli._structural_gap_warning(_scan(tmp_path, {"a.ts": "export function f() {}\n"}))
    assert warning is not None
    assert "javascript" in warning and "wiki-languages" in warning


def test_no_warning_for_python_only(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(astgrep, "is_available", lambda: False)
    assert cli._structural_gap_warning(_scan(tmp_path, {"a.py": "def f():\n    pass\n"})) is None


def test_no_warning_when_kill_switch_off(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(astgrep, "is_available", lambda: False)
    set_structural_enabled(False)
    try:
        assert cli._structural_gap_warning(_scan(tmp_path, {"a.ts": "const x = 1\n"})) is None
    finally:
        set_structural_enabled(True)


def test_status_symbols_line(tmp_path, monkeypatch) -> None:
    # FILL IN: build a tiny wiki and invoke `status` via click's CliRunner exactly as
    # tests/knowledge/wiki/test_cli_status_sqlite.py does; with astgrep.is_available
    # patched False assert "Symbols" and "wiki-languages" in the output — bounded by AC
    ...
```
**Why**: verify the `scan_repository` keyword names (`use_git`) against `repo_scan.py` before
running. The build path calls it with `use_git=not no_git` (`cli.py:1532`).

### FILL IN checklist
- [ ] `_format_symbols_status` wording. Bound: the three strings in §Scope.
- [ ] `test_status_symbols_line`. Bound: reuse the `test_cli_status_sqlite.py` harness.

---

## Acceptance Criteria

- [ ] Without ast-grep, a build over `.ts` files prints the `wiki-languages` WARNING exactly
      once, and `status` shows `Symbols   : disabled for …`.
- [ ] With ast-grep installed, no warning, and `Symbols   : enabled`.
- [ ] Kill switch off: no warning, and the `status` line says disabled by configuration.
- [ ] Mutation-checked: making the helper return `None` unconditionally turns
      `test_structural_gap_warning_text` RED.

---

## Validation Commands

- `pytest tests/knowledge/wiki/test_cli_structural_gap.py -q`
- `pytest tests/knowledge/wiki/test_cli_status_sqlite.py -q`

---

## Test Specification

See the CREATE block above.

---

## Agent Instructions

1. **Work in the feature worktree**
   (`python -m scripts.sdd.ensure_worktree --slug wikitoolkit-structural-coverage --feature-id FEAT-609`).
2. Confirm TASK-3821 is `done`. Verify the contract and re-run each `grep -c`.
3. Implement, validate, mutation-check, and stage only the listed files.
4. Close with `scripts/sdd/close_task.sh TASK-3824 wikitoolkit-structural-coverage verified`,
   then fill in the Completion Note.

---

## Completion Note

*(Agent fills this in when done)*
