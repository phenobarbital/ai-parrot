# TASK-4077: Toolkit templates: requires_pip / post_install / requires_env headers

**Feature**: FEAT-633 — Parrot Bootstrap Installer
**Spec**: `sdd/specs/parrot-installer.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: S (< 2h)
**Depends-on**: none
**Assigned-to**: unassigned

---

## Context

Spec §3 Module 4 (and §2 Data Models). Packaged toolkit templates today carry only
`summary` / `requires_llm` / `requires_dist`: exposing a toolkit to a coding host installs
nothing, so a missing distribution (e.g. `parrot_tools`, Playwright's browser) is only
discovered when the MCP server fails to start. This task adds three install-metadata
header keys to `ToolkitTemplate` and its lenient header parser, and fills them in for the
four templates whose toolkits need extra packages. It is the data source for
`parrot self add <component>` (TASK-4079), the inventory hint (TASK-4078) and the
`parrot self doctor` env check (TASK-4080).

Contract boundaries (spec §3 M4, codex S6 adopted scoped):
- `requires_pip` holds **PEP 508 requirement strings** and is never used for import
  probing — `requires_dist` keeps that job unchanged.
- `post_install` argv is executed by `self add` only because templates are package data
  (`available_templates()` / `load_template()` read `importlib.resources` exclusively,
  toolkit_seed.py:49-75) — no user-writable source.
- The parser stays lenient: unknown `# parrot:` keys are skipped silently, so old runtimes
  tolerate templates carrying the new keys (forward compatibility).

---

## Scope

- Add `requires_pip`, `post_install`, `requires_env` (`tuple[str, ...] = ()`) to
  `ToolkitTemplate`.
- Add three `elif` branches to `load_template()`'s header loop, with this FIXED grammar:
  - `# parrot:requires_pip: <one PEP 508 requirement>` — **repeatable**, one requirement per
    line, accumulated in order. No comma splitting (PEP 508 extras such as
    `pkg[a,b]` contain commas).
  - `# parrot:post_install: <command>` — single line, parsed with `shlex.split` into the
    argv tuple (last occurrence wins). A leading `python` token is a placeholder: TASK-4079
    substitutes the target venv's interpreter at run time.
  - `# parrot:requires_env: A,B` — comma-separated environment-variable names, stripped,
    empties dropped.
- Keep unknown keys silently ignored (and test it).
- Add install metadata header lines to `browsing`, `scraping`, `lsp`, `querysource`
  templates (header lines only — template bodies untouched).
- Write tests for parsing, repeatability, unknown-key tolerance and the shipped values.

**NOT in scope**: `ToolkitRow` / inventory / CLI hints (TASK-4078); running installs or
post-install commands (TASK-4079); doctor checks (TASK-4080); headers for any template
other than the four listed; validating requirement strings with `packaging` (not a core
dependency — spec §5 "no new runtime dependency").

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/mcp/toolkit_seed.py` | MODIFY | Three new `ToolkitTemplate` fields + three parser branches + ctor kwargs |
| `packages/ai-parrot/src/parrot/mcp/_toolkit_templates/browsing.yaml` | MODIFY | Header: requires_pip + post_install |
| `packages/ai-parrot/src/parrot/mcp/_toolkit_templates/scraping.yaml` | MODIFY | Header: requires_pip + post_install |
| `packages/ai-parrot/src/parrot/mcp/_toolkit_templates/lsp.yaml` | MODIFY | Header: requires_pip |
| `packages/ai-parrot/src/parrot/mcp/_toolkit_templates/querysource.yaml` | MODIFY | Header: requires_pip + requires_env |
| `packages/ai-parrot/tests/mcp/test_toolkit_seed_install_metadata.py` | CREATE | Parser + shipped-values tests |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from parrot.mcp.toolkit_seed import ToolkitTemplate, available_templates, load_template  # verified: packages/ai-parrot/src/parrot/mcp/toolkit_seed.py:27,49,63
import shlex  # stdlib — new import in toolkit_seed.py
```

### Existing Signatures to Use
```python
# packages/ai-parrot/src/parrot/mcp/toolkit_seed.py
_META_PREFIX: str = "# parrot:"                                # line 21
class ToolkitTemplate(BaseModel):                              # line 27
    name: str                                                  # line 30
    body: str                                                  # line 31
    requires_llm: bool = False                                 # line 32
    summary: str = ""                                          # line 33
    requires_dist: tuple[str, ...] = ()                        # line 34
def available_templates() -> tuple[str, ...]:                  # line 49 (importlib.resources only)
def load_template(name: str) -> ToolkitTemplate:               # line 63
    template_dir = files(TEMPLATE_PACKAGE) / TEMPLATE_DIR      # line 69 — `files` imported at line 9 (monkeypatchable)
    requires_dist: tuple[str, ...] = ()                        # line 81 (local; same text as line 34)
    body_start = 0                                             # line 82
    # header loop lines 84-98; stops at first non-"# parrot:" line (line 85-87)
    elif meta_content.startswith("requires_dist:"):            # line 96
    return ToolkitTemplate(                                    # line 104
        name=name, body=body, requires_llm=requires_llm, summary=summary, requires_dist=requires_dist  # line 105
    )
```
```yaml
# packages/ai-parrot/src/parrot/mcp/_toolkit_templates/<name>.yaml — line 3 of each of the four:
# browsing.yaml / scraping.yaml / lsp.yaml:  # parrot:requires_dist: parrot_tools
# querysource.yaml:                          # parrot:requires_dist: parrot_tools,querysource
```
```toml
# packages/ai-parrot-tools/pyproject.toml
name = "ai-parrot-tools"                                       # line 6 — the PyPI distribution name
scraping = ["selenium>=4.35", ..., "playwright>=1.52", ...]    # line 73
db = ["querysource>=5.1.2", "psycopg-binary>=3.2"]             # line 77
```
- `querysource.conf.asyncpg_url` (the DSN the querysource toolkit uses,
  `parrot_tools/querysource/_qs.py:63-64`) is built from `PG_USER`, `PG_PWD`, `PG_HOST`,
  `PG_PORT`, `PG_DATABASE` (`.venv/.../querysource/conf.py:38-44`); only `PG_USER` and
  `PG_PWD` have no fallback.
- LSP: Pyright 1.1.414 + Node.js are operator-provisioned, "Nothing here is automatic"
  (`docs/sdd/lsp-pilot.md:19-37`).
- Existing tests that must stay green: `tests/mcp/test_toolkit_templates.py`
  (asserts `querysource` `requires_dist == ("parrot_tools", "querysource")`, line 54),
  `tests/mcp/test_toolkit_seed.py`, `packages/ai-parrot/tests/mcp/test_lsp_template.py`
  (asserts lsp `requires_dist == ("parrot_tools",)`, line 35).

### Does NOT Exist
- ~~`ToolkitTemplate.requires_pip` / `.post_install` / `.requires_env`~~ — added by this task.
- ~~any repo-local / user-writable template source~~ — templates load only from package data.
- ~~`packaging` as a core ai-parrot dependency~~ — not declared in `packages/ai-parrot/pyproject.toml`; do not import it in `toolkit_seed.py`.
- ~~an `lsp` or `browsing` extra in ai-parrot-tools~~ — only `scraping` (Playwright) and `db` (querysource) extras are relevant.
- ~~an existing toolkit_seed test under `packages/ai-parrot/tests/`~~ — the seed tests live at repo-root `tests/mcp/`; this task creates a new file under `packages/ai-parrot/tests/mcp/`.

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {"path": "packages/ai-parrot/src/parrot/mcp/toolkit_seed.py", "action": "MODIFY"},
    {"path": "packages/ai-parrot/src/parrot/mcp/_toolkit_templates/browsing.yaml", "action": "MODIFY"},
    {"path": "packages/ai-parrot/src/parrot/mcp/_toolkit_templates/scraping.yaml", "action": "MODIFY"},
    {"path": "packages/ai-parrot/src/parrot/mcp/_toolkit_templates/lsp.yaml", "action": "MODIFY"},
    {"path": "packages/ai-parrot/src/parrot/mcp/_toolkit_templates/querysource.yaml", "action": "MODIFY"},
    {"path": "packages/ai-parrot/tests/mcp/test_toolkit_seed_install_metadata.py", "action": "CREATE"}
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot/src/parrot/mcp/toolkit_seed.py#ToolkitTemplate",
    "sym:packages/ai-parrot/src/parrot/mcp/toolkit_seed.py#load_template",
    "sym:packages/ai-parrot/src/parrot/mcp/toolkit_seed.py#available_templates"
  ]
}
```

---

## Implementation Notes

### Pattern to Follow
```python
# packages/ai-parrot/src/parrot/mcp/toolkit_seed.py:96-98 — the existing branch shape
elif meta_content.startswith("requires_dist:"):
    raw = meta_content[len("requires_dist:") :].strip()
    requires_dist = tuple(part.strip() for part in raw.split(",") if part.strip())
```

### Key Constraints
- Lenient parser stays lenient (spec §7): a malformed `post_install` line (unbalanced
  quotes → `shlex.split` raises `ValueError`) must be logged with `logger.warning` and
  ignored, never fatal.
- Header lines must stay in the leading `# parrot:` block — the loop stops at the first
  non-meta line (toolkit_seed.py:85-87).
- `requires_pip` accumulates (repeatable); `post_install` last-wins; `requires_env`
  last-wins.
- No `print`; module logger only.

### References in Codebase
- `packages/ai-parrot/src/parrot/mcp/toolkit_seed.py:63-106` — the parser
- `tests/mcp/test_toolkit_templates.py` — existing shipped-template assertions

---

## Implementation Blueprint

### Steps (in order)
1. Add `import shlex` and the three fields to `ToolkitTemplate` — *why*: §2 Data Models fixes names/types; defaults keep every other template valid.
2. Add the three local accumulators and three `elif` branches, then pass them to the ctor — *why*: mirrors the `requires_dist:` branch (spec §3 M4 "parser keys mirror existing branch").
3. Add header lines to the four templates — *why*: these are the toolkits whose distributions are not core.
4. Create the test file — *why*: spec §4 `test_template_new_headers_parse`, `test_template_unknown_keys_ignored`.

### `packages/ai-parrot/src/parrot/mcp/toolkit_seed.py` (MODIFY)
```python
# occurrences: 1 (verified: grep -c 'import re' packages/ai-parrot/src/parrot/mcp/toolkit_seed.py)
# AFTER — insert below `import re` (verified: packages/ai-parrot/src/parrot/mcp/toolkit_seed.py:7)
import shlex
```
```python
# occurrences: 2 (verified: grep -c 'requires_dist: tuple\[str, ...\] = ()' packages/ai-parrot/src/parrot/mcp/toolkit_seed.py)
# AFTER — the CLASS field (line 34), disambiguated by its 3-line context (verified: toolkit_seed.py:32-34):
#     requires_llm: bool = False
#     summary: str = ""
#     requires_dist: tuple[str, ...] = ()
    requires_pip: tuple[str, ...] = ()  # PEP 508 requirement strings for `parrot self add` (never import-probed)
    post_install: tuple[str, ...] = ()  # argv run after install; leading "python" = target venv interpreter
    requires_env: tuple[str, ...] = ()  # env var names `parrot self doctor` checks
```
```python
# occurrences: 1 (verified: grep -c '    requires_llm = False' packages/ai-parrot/src/parrot/mcp/toolkit_seed.py)
# AFTER — insert below `    requires_llm = False` (verified: toolkit_seed.py:80), i.e. next to the local
# `requires_dist: tuple[str, ...] = ()` at line 81 (the second occurrence of the field text above)
    requires_pip: list[str] = []
    post_install: tuple[str, ...] = ()
    requires_env: tuple[str, ...] = ()
```
```python
# occurrences: 1 (verified: grep -c '        elif meta_content.startswith("requires_dist:"):' packages/ai-parrot/src/parrot/mcp/toolkit_seed.py)
# AFTER — the requires_dist branch body (verified: toolkit_seed.py:96-98), same indent
        elif meta_content.startswith("requires_pip:"):
            requirement = meta_content[len("requires_pip:") :].strip()
            if requirement:
                requires_pip.append(requirement)  # repeatable, one PEP 508 string per line — no comma split
        elif meta_content.startswith("post_install:"):
            raw = meta_content[len("post_install:") :].strip()
            try:
                post_install = tuple(shlex.split(raw))
            except ValueError as exc:  # unbalanced quotes — stay lenient (spec §7)
                logger.warning("template %s: ignoring unparsable post_install %r: %s", name, raw, exc)
        elif meta_content.startswith("requires_env:"):
            raw = meta_content[len("requires_env:") :].strip()
            requires_env = tuple(part.strip() for part in raw.split(",") if part.strip())
```
```python
# occurrences: 1 (verified: grep -c 'name=name, body=body, requires_llm=requires_llm, summary=summary, requires_dist=requires_dist' packages/ai-parrot/src/parrot/mcp/toolkit_seed.py)
# REPLACE — the ctor kwargs line (verified: toolkit_seed.py:105) with:
        name=name,
        body=body,
        requires_llm=requires_llm,
        summary=summary,
        requires_dist=requires_dist,
        requires_pip=tuple(requires_pip),
        post_install=post_install,
        requires_env=requires_env,
```
**Why**: three `elif`s keep the existing lenient shape; unknown keys still fall through
every branch and are skipped.

### `packages/ai-parrot/src/parrot/mcp/_toolkit_templates/browsing.yaml` (MODIFY)
```yaml
# occurrences: 1 (verified: grep -c '^# parrot:requires_dist:' packages/ai-parrot/src/parrot/mcp/_toolkit_templates/browsing.yaml)
# AFTER — insert below `# parrot:requires_dist: parrot_tools` (verified: browsing.yaml:3)
# parrot:requires_pip: ai-parrot-tools[scraping]
# parrot:post_install: python -m playwright install chromium
```

### `packages/ai-parrot/src/parrot/mcp/_toolkit_templates/scraping.yaml` (MODIFY)
```yaml
# occurrences: 1 (verified: grep -c '^# parrot:requires_dist:' packages/ai-parrot/src/parrot/mcp/_toolkit_templates/scraping.yaml)
# AFTER — insert below `# parrot:requires_dist: parrot_tools` (verified: scraping.yaml:3)
# parrot:requires_pip: ai-parrot-tools[scraping]
# parrot:post_install: python -m playwright install chromium
```
**Why**: `playwright>=1.52` ships only in the `scraping` extra (ai-parrot-tools pyproject.toml:73); the browser binary is a separate download.

### `packages/ai-parrot/src/parrot/mcp/_toolkit_templates/lsp.yaml` (MODIFY)
```yaml
# occurrences: 1 (verified: grep -c '^# parrot:requires_dist:' packages/ai-parrot/src/parrot/mcp/_toolkit_templates/lsp.yaml)
# AFTER — insert below `# parrot:requires_dist: parrot_tools` (verified: lsp.yaml:3)
# parrot:requires_pip: ai-parrot-tools
```
**Why**: no `post_install` on purpose — Pyright 1.1.414 + Node.js are operator-provisioned and the template must never trigger a process or network access (docs/sdd/lsp-pilot.md:19-37; lsp.yaml body comment).

### `packages/ai-parrot/src/parrot/mcp/_toolkit_templates/querysource.yaml` (MODIFY)
```yaml
# occurrences: 1 (verified: grep -c '^# parrot:requires_dist:' packages/ai-parrot/src/parrot/mcp/_toolkit_templates/querysource.yaml)
# AFTER — insert below `# parrot:requires_dist: parrot_tools,querysource` (verified: querysource.yaml:3)
# parrot:requires_pip: ai-parrot-tools[db]
# parrot:requires_env: PG_USER,PG_PWD
```
**Why**: the `db` extra is the declared carrier of `querysource>=5.1.2` (ai-parrot-tools pyproject.toml:77); `PG_USER`/`PG_PWD` are the only `asyncpg_url` inputs with no fallback (querysource/conf.py:39-44). navconfig can also read them from `env/.env` — doctor (TASK-4080) reports them as a warning, not an error.

### `packages/ai-parrot/tests/mcp/test_toolkit_seed_install_metadata.py` (CREATE)
```python
"""Install-metadata template headers (FEAT-633, TASK-4077)."""

from __future__ import annotations

from pathlib import Path

import pytest

from parrot.mcp import toolkit_seed
from parrot.mcp.toolkit_seed import ToolkitTemplate, available_templates, load_template


@pytest.fixture
def fake_templates(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Point `load_template` at a tmp `_toolkit_templates/` dir (it reads `files(pkg) / TEMPLATE_DIR`)."""
    template_dir = tmp_path / toolkit_seed.TEMPLATE_DIR
    template_dir.mkdir()
    monkeypatch.setattr(toolkit_seed, "files", lambda _pkg: tmp_path)
    return template_dir


def _write(template_dir: Path, name: str, header: str) -> None:
    (template_dir / f"{name}.yaml").write_text(f"{header}\n  {name}:\n    class: x.Y\n", encoding="utf-8")


def test_template_new_headers_parse(fake_templates: Path) -> None:
    """requires_pip (repeatable, commas kept) / post_install (shlex) / requires_env (csv) round-trip."""
    _write(
        fake_templates,
        "demo",
        "# parrot:requires_pip: pkg[a,b]>=1.0\n"
        "# parrot:requires_pip: other; python_version >= '3.11'\n"
        "# parrot:post_install: python -m tool install 'two words'\n"
        "# parrot:requires_env: A, B,,",
    )
    tpl = load_template("demo")
    assert tpl.requires_pip == ("pkg[a,b]>=1.0", "other; python_version >= '3.11'")
    assert tpl.post_install == ("python", "-m", "tool", "install", "two words")
    assert tpl.requires_env == ("A", "B")


def test_template_unknown_keys_ignored(fake_templates: Path) -> None:
    """Forward-compat: an unknown `# parrot:` key is skipped, the rest still parses."""
    # FILL IN: header with `# parrot:future_key: x` between known keys; assert known fields set,
    # body starts at the section line — bounded by spec §5 "unknown-key skip verified"
    raise NotImplementedError


def test_malformed_post_install_is_ignored(fake_templates: Path) -> None:
    """Unbalanced quotes never make the parser fatal."""
    # FILL IN: `# parrot:post_install: python -c 'oops`; assert post_install == () — bounded by spec §7 lenient parser
    raise NotImplementedError


def test_old_templates_default_empty() -> None:
    """Templates without the new keys keep `()` defaults (memory ships none)."""
    tpl = load_template("memory")
    assert (tpl.requires_pip, tpl.post_install, tpl.requires_env) == ((), (), ())


@pytest.mark.parametrize("name", ["browsing", "scraping"])
def test_browser_templates_ship_playwright_install(name: str) -> None:
    tpl = load_template(name)
    assert tpl.requires_pip == ("ai-parrot-tools[scraping]",)
    assert tpl.post_install == ("python", "-m", "playwright", "install", "chromium")


def test_lsp_and_querysource_metadata() -> None:
    # FILL IN: lsp → requires_pip == ("ai-parrot-tools",), post_install == (); querysource →
    # requires_pip == ("ai-parrot-tools[db]",), requires_env == ("PG_USER", "PG_PWD"),
    # requires_dist unchanged — bounded by the template values fixed in this task
    raise NotImplementedError


def test_every_shipped_template_still_loads() -> None:
    for name in available_templates():
        assert isinstance(load_template(name), ToolkitTemplate)
```
**Why this shape**: monkeypatching `toolkit_seed.files` exercises the real parser on
synthetic headers without adding a repo-local template source (forbidden by spec §3 M4).

### FILL IN checklist
- [ ] `test_toolkit_seed_install_metadata.py::test_template_unknown_keys_ignored` — header + asserts; bounded by spec §5
- [ ] `test_toolkit_seed_install_metadata.py::test_malformed_post_install_is_ignored` — bounded by spec §7
- [ ] `test_toolkit_seed_install_metadata.py::test_lsp_and_querysource_metadata` — bounded by the values in this task

---

## Acceptance Criteria

- [ ] `ToolkitTemplate` has `requires_pip`, `post_install`, `requires_env` (`tuple[str, ...] = ()`).
- [ ] `requires_pip` is repeatable and never comma-split; `post_install` is `shlex.split`; `requires_env` is comma-split.
- [ ] Unknown `# parrot:` keys and an unparsable `post_install` are ignored, never fatal (spec §5 "old runtimes still parse new templates").
- [ ] browsing/scraping/lsp/querysource ship the values fixed above; every other template parses with `()` defaults.
- [ ] Existing template/seed tests still pass (`tests/mcp/test_toolkit_templates.py`, `tests/mcp/test_toolkit_seed.py`, `packages/ai-parrot/tests/mcp/test_lsp_template.py`).
- [ ] `ruff check packages/ai-parrot/src/parrot/mcp/toolkit_seed.py` clean.

---

## Validation Commands

Run from the feature worktree with `PYTHONPATH=packages/ai-parrot/src` (the shared venv is
editable-installed against the main checkout).

- `pytest packages/ai-parrot/tests/mcp/test_toolkit_seed_install_metadata.py -q`
- `pytest packages/ai-parrot/tests/mcp/test_lsp_template.py -q`
- `pytest tests/mcp/test_toolkit_templates.py -q`
- `pytest tests/mcp/test_toolkit_seed.py -q`

---

## Test Specification

See the CREATE block above (`packages/ai-parrot/tests/mcp/test_toolkit_seed_install_metadata.py`):
`test_template_new_headers_parse`, `test_template_unknown_keys_ignored` (spec §4 names),
plus malformed-`post_install`, defaults, and shipped-value tests.

---

## Agent Instructions

When you pick up this task:

1. **Work in the feature worktree** — never on `base_branch`
   (`python -m scripts.sdd.ensure_worktree --slug parrot-installer --feature-id FEAT-633`)
2. **Read the spec** at the path listed above for full context
3. **Check dependencies** — every `Depends-on` task must be `"done"` in the
   per-spec index `sdd/tasks/index/parrot-installer.json`
4. **Verify the Codebase Contract** — before writing ANY code:
   - Confirm every import in "Verified Imports" still exists (`grep` or `read` the source)
   - Confirm every class/method in "Existing Signatures" still has the listed attributes
   - If anything has changed, update the contract FIRST, then implement
   - **NEVER** reference an import, attribute, or method not in the contract without verifying it exists
5. **Update status** in `sdd/tasks/index/parrot-installer.json` → `"in-progress"`
   (set `started_at`) and commit only that index file
6. **Implement** — start from the Implementation Blueprint blocks, complete every
   `# FILL IN:` marker, and never change a signature or path the blueprint fixes
7. **Verify** all acceptance criteria are met — run the Validation Commands
8. **Commit the code** — stage only the files this task lists (never `git add .` / `-A`)
9. **Close the task** with `scripts/sdd/close_task.sh TASK-4077 parrot-installer verified`
   — it moves this file to `sdd/tasks/completed/` and marks it `"done"` in the
   index; never move or copy the file by hand
10. **Fill in the Completion Note** below, then commit the staged SDD state

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**: <session or agent ID>
**Date**: YYYY-MM-DD
**Notes**: What was implemented, any deviations from scope, issues encountered.

**Deviations from spec**: none | describe if any
