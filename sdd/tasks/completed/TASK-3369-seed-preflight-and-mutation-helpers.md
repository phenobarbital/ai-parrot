# TASK-3369: Seed preflight, atomic write, and comment-preserving toggle/remove

**Feature**: FEAT-570 — `parrot toolkits` on-demand local-MCP toolkit installation
**Spec**: `sdd/specs/expose-local-mcp-tools.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: L (4-8h)
**Depends-on**: TASK-3368
**Assigned-to**: unassigned

---

## Context

Spec §3 Module 4, driven by design research **S4** and **S5** (both CONFIRM, both
`risk: high`).

Two defects block `parrot toolkits` from mutating `.parrot/mcp-toolkits.yaml`
safely:

1. **Non-atomic, non-validating seeding (S4).** `seed_toolkit_sections` catches
   the `ValueError` raised while loading an existing config, appends anyway, and
   only fails on the *reload* — so a malformed file gets appended to and is left
   worse than it was found. It also seeds the valid names of a request that
   contains an unknown one, contradicting the all-or-nothing behavior the CLI
   needs.
2. **No safe way to toggle or remove (S5).** Seeding is append-only text; there is
   no helper to flip `enabled:` or delete a section. A naive `yaml.safe_dump` of
   the parsed model would silently destroy every operator comment and the
   carefully commented kwargs the FEAT-570 templates ship. No round-trip YAML
   parser is declared (`ruamel` is absent from `packages/ai-parrot/pyproject.toml`),
   and the spec's decision (§7) is a **narrowly-scoped lexical editor, not a new
   dependency**.

`parrot toolkits enable/disable/uninstall` (TASK-3375) is built directly on the
helpers this task adds.

---

## Scope

- Add `preflight_seed(root, names)` — validate the whole request before any write.
- Make `seed_toolkit_sections` call it, and make its write atomic.
- Add `set_section_enabled(root, name, enabled)` — lexical, comment-preserving.
- Add `remove_section(root, name)` — lexical, comment-preserving, atomic.
- Write tests for comment/format preservation, atomicity and all-or-nothing.

**NOT in scope**: the `requires_dist` template header (TASK-3370), any CLI wiring
(TASK-3375/3376), the host reconcilers (TASK-3371/3372/3373).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/mcp/toolkit_seed.py` | MODIFY | Add preflight + atomic write + toggle/remove helpers |
| `tests/mcp/test_toolkit_seed.py` | MODIFY | Preflight, atomicity, comment preservation |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from parrot.mcp.toolkit_config import load_toolkits_config  # verified: toolkit_config.py:105
from parrot.mcp.toolkit_seed import (                        # verified: toolkit_seed.py
    SeedResult,            # line 35
    ToolkitTemplate,       # line 26
    available_templates,   # line 47
    load_template,         # line 61
    seed_toolkit_sections, # line 154
    template_drift,        # line 127
)
```

### Existing Signatures to Use
```python
# packages/ai-parrot/src/parrot/mcp/toolkit_seed.py
TEMPLATE_PACKAGE: str = "parrot.mcp"            # line 17
TEMPLATE_DIR: str = "_toolkit_templates"        # line 18
REPO_ROOT_PLACEHOLDER: str = "{{repo_root}}"    # line 19
_META_PREFIX: str = "# parrot:"                 # line 20
_DRIFT_IGNORED_KEYS: frozenset[str] = frozenset({"enabled"})  # line 23

class ToolkitTemplate(BaseModel):               # line 26
    name: str; body: str; requires_llm: bool = False; summary: str = ""

class SeedResult(BaseModel):                    # line 35
    created_file: bool = False
    added: list[str]; skipped: list[str]; unknown: list[str]
    drift: dict[str, list[str]]

def available_templates() -> tuple[str, ...]: ...       # line 47
def load_template(name: str) -> ToolkitTemplate: ...    # line 61 — raises KeyError
def template_drift(root: Path, name: str) -> list[str]: ...  # line 127
def seed_toolkit_sections(root: Path, names: Sequence[str]) -> SeedResult: ...  # line 154
#   - dedupes `names` preserving order
#   - `result.unknown = [n for n in deduped if n not in available]`  <- currently NON-fatal
#   - `try: config = load_toolkits_config(root_path) ... except ValueError: pass`  <- swallows malformed
#   - opens the file in "a" (append) mode and writes rendered bodies
#   - `needs_leading_newline` guard for a file with no trailing newline
#   - re-loads afterwards and raises ValueError if a seeded name is missing

# The config file this module writes:
#   <root>/.parrot/mcp-toolkits.yaml     (root key: `toolkits:`; sections indented 2 spaces)
```

### Does NOT Exist
- ~~`ruamel.yaml`~~ — NOT a declared dependency. Do not add it; the spec (§7)
  decided a lexical editor instead.
- ~~`toolkit_seed.set_section_enabled`~~ / ~~`remove_section`~~ / ~~`preflight_seed`~~
  — these are what THIS task creates.
- ~~`SeedResult.removed`~~ / ~~`SeedResult.toggled`~~ — not fields; the new helpers
  return `bool`, they do not extend `SeedResult`.
- ~~`ToolkitSection.enabled` as a writable round-trip target~~ — the Pydantic model
  is read-only for this purpose; the toggle edits TEXT, never a dumped model.
- ~~`yaml.round_trip_dump`~~ / ~~`yaml.RoundTripLoader`~~ — PyYAML has no such API.
- ~~`BUILTIN_TOOLKITS`~~ — deleted by TASK-3368.

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {"path": "packages/ai-parrot/src/parrot/mcp/toolkit_seed.py", "action": "MODIFY"},
    {"path": "tests/mcp/test_toolkit_seed.py", "action": "MODIFY"}
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot/src/parrot/mcp/toolkit_seed.py#seed_toolkit_sections",
    "sym:packages/ai-parrot/src/parrot/mcp/toolkit_seed.py#SeedResult",
    "sym:packages/ai-parrot/src/parrot/mcp/toolkit_seed.py#load_template",
    "sym:packages/ai-parrot/src/parrot/mcp/toolkit_seed.py#available_templates",
    "sym:packages/ai-parrot/src/parrot/mcp/toolkit_config.py#load_toolkits_config"
  ]
}
```

---

## Implementation Notes

### Key Constraints
- **Atomic replace**: write to a sibling temp file in the same directory, then
  `os.replace()`. A same-directory temp is required — `os.replace` is only atomic
  within one filesystem.
- **Lexical, not semantic**: the toggle and the removal operate on lines. Parse
  with PyYAML only to *locate* and *validate*, never to re-emit.
- **Section boundaries**: a section starts at a line matching `^  <name>:\s*$`
  and runs until the next line matching `^  \S` (a sibling key at the same indent)
  or EOF. Comment lines immediately preceding a section header belong to it.
- Preserve the existing `needs_leading_newline` protection — a hand-edited file
  without a trailing newline must not get its last line concatenated.

### References in Codebase
- `packages/ai-parrot/src/parrot/mcp/toolkit_seed.py:154` — the function being hardened
- `packages/ai-parrot/src/parrot/mcp/_toolkit_templates/sdd-coder.yaml` — a template
  whose kwargs carry many operator-facing comments; it is the worst case for AC10

---

## Implementation Blueprint

### Steps (in order)
1. Add `preflight_seed` — *why*: every mutation must be able to fail before the
   file is touched, which is the only way AC8 ("byte-identical after a failed
   mutation") can hold.
2. Add a private `_atomic_write(path, text)` — *why*: all three mutating helpers
   need the same temp-then-`os.replace` guarantee; writing it once prevents three
   subtly different versions.
3. Add `_find_section_span` — *why*: the toggle and the removal both need the same
   definition of where a section begins and ends, including its leading comments.
4. Add `set_section_enabled` and `remove_section` on top of those two — *why*:
   TASK-3375's enable/disable/uninstall are thin wrappers over them.
5. Rewrite `seed_toolkit_sections` to call `preflight_seed` first and build the
   full new text in memory before one atomic write — *why*: append mode is what
   makes the current failure mode destructive.

### `packages/ai-parrot/src/parrot/mcp/toolkit_seed.py` (MODIFY — additions)
```python
# occurrences: 1 (verified: grep -cF 'def seed_toolkit_sections(root: Path, names: Sequence[str]) -> SeedResult:' packages/ai-parrot/src/parrot/mcp/toolkit_seed.py)
# BEFORE — insert above `def seed_toolkit_sections(root: Path, names: Sequence[str]) -> SeedResult:`
# (verified: toolkit_seed.py:154)
import os
import tempfile


def _config_path(root: Path) -> Path:
    """Return `<root>/.parrot/mcp-toolkits.yaml`."""
    return Path(root) / ".parrot" / "mcp-toolkits.yaml"


def _atomic_write(path: Path, text: str) -> None:
    """Replace `path` with `text` atomically.

    Writes a temp file in the SAME directory (os.replace is only atomic within a
    filesystem), flushes and fsyncs it, then renames over the target.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=str(path.parent), prefix=".mcp-toolkits.", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(text)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp, path)
    except BaseException:
        Path(tmp).unlink(missing_ok=True)
        raise


def preflight_seed(root: Path, names: Sequence[str]) -> None:
    """Validate a seeding request BEFORE anything is written.

    Raises:
        ValueError: any name has no packaged template (all-or-nothing — the
            pre-FEAT-570 behavior seeded the valid names anyway), or an existing
            `.parrot/mcp-toolkits.yaml` cannot be parsed (the pre-FEAT-570
            behavior swallowed this and appended to the malformed file).
    """
    available = set(available_templates())
    unknown = [name for name in dict.fromkeys(names) if name not in available]
    if unknown:
        raise ValueError(
            f"No packaged template for: {', '.join(sorted(unknown))}. "
            f"Available: {', '.join(available_templates())}"
        )
    path = _config_path(root)
    if path.exists():
        load_toolkits_config(Path(root))  # raises ValueError naming file+section


def _find_section_span(lines: list[str], name: str) -> tuple[int, int] | None:
    """Return the [start, end) line span of section `name`, including its leading comments.

    A section header is `  <name>:` at two-space indent; the body runs until the
    next line at that same indent that is not a comment, or EOF. Returns None when
    the section is absent.
    """
    # FILL IN: locate the header, walk back over contiguous `#` comment lines to
    # include them in the span, then walk forward to the next sibling key —
    # bounded by AC10 (comments and formatting survive) and the two-space section
    # indent the templates and seeding both use.
    raise NotImplementedError


def set_section_enabled(root: Path, name: str, enabled: bool) -> bool:
    """Flip (or insert) `enabled:` for one section, preserving comments and formatting.

    Lexical edit + atomic replace — never `yaml.safe_dump` of a parsed model, which
    would discard every operator comment (no round-trip parser is declared).

    Returns:
        False when the section is absent; True when the file was rewritten.
    """
    # FILL IN: within the section span, rewrite an existing `    enabled: <bool>`
    # line in place, or insert one directly below the header when absent; then
    # `_atomic_write`. Preserve the line's original indentation — bounded by AC10.
    raise NotImplementedError


def remove_section(root: Path, name: str) -> bool:
    """Delete one section and its leading comment block; atomic replace.

    Returns:
        False when the section is absent; True when the file was rewritten.
    """
    # FILL IN: drop `_find_section_span`'s slice, collapse a resulting run of blank
    # lines to one, and keep the `toolkits:` root key even when the file becomes
    # empty of sections — bounded by AC10.
    raise NotImplementedError
```
**Why this shape**: `preflight_seed` is a separate public function rather than an
inline check because TASK-3375's `install_toolkits` must be able to validate a
whole multi-name request *before* it starts touching hosts. `_atomic_write` is
private and shared so the three mutators cannot drift. `_find_section_span`
returning a span (not a parsed object) is what keeps the edit lexical — the moment
a helper returns a dict, someone will dump it and lose the comments AC10 protects.
Do not change these four signatures; TASK-3375 imports `preflight_seed`,
`set_section_enabled` and `remove_section` by name.

### `packages/ai-parrot/src/parrot/mcp/toolkit_seed.py` (MODIFY — `seed_toolkit_sections`)
```python
# occurrences: 1 (verified: grep -cF 'def seed_toolkit_sections(root: Path, names: Sequence[str]) -> SeedResult:' packages/ai-parrot/src/parrot/mcp/toolkit_seed.py)
# Inside seed_toolkit_sections (verified: toolkit_seed.py:154):
#   1. Call `preflight_seed(root, names)` as the FIRST statement after the local
#      `load_toolkits_config` import — it raises before any mkdir or write.
#   2. DELETE the `result.unknown = [...]` / `valid_names = [...]` split — after
#      preflight there are no unknown names. Keep the `SeedResult.unknown` FIELD
#      (callers still read it; it is simply always empty now).
#   3. DELETE the `try: ... except ValueError: pass` around the existing-section
#      probe — preflight already proved the file parses.
#   4. Build the complete new file text in a local string, then call
#      `_atomic_write(path, text)` ONCE instead of opening the file in "a" mode.
# FILL IN: the text assembly — preserve `needs_toolkits_root` and
# `needs_leading_newline` semantics exactly; bounded by AC8 and the existing
# `test_toolkit_seed.py` expectations.
```
**Why**: append-mode is precisely what makes today's failure destructive — the
bytes are already on disk when the reload check fails. Assembling in memory and
replacing atomically means a failure anywhere leaves the original file untouched,
which is AC8. Keep the post-write reload assertion; it is now a genuine invariant
check rather than the only line of defense.

### `tests/mcp/test_toolkit_seed.py` (MODIFY)
```python
# occurrences: 1 (verified: grep -c 'def test_' tests/mcp/test_toolkit_seed.py returns the existing cases)
# ADD these cases; do not delete the existing ones (they pin behavior that must not regress).
def test_preflight_rejects_unknown_name_before_write(tmp_path): ...
def test_preflight_rejects_malformed_yaml(tmp_path): ...
def test_seed_unknown_name_leaves_file_byte_identical(tmp_path): ...
def test_set_section_enabled_preserves_comments(tmp_path): ...
def test_remove_section_preserves_neighbours(tmp_path): ...
def test_set_enabled_returns_false_for_absent_section(tmp_path): ...
# FILL IN: bodies — the comment-preservation cases must assert on the FULL file
# text, not a parsed round-trip, or they cannot detect comment loss;
# bounded by AC8 and AC10.
```
**Why**: a test that parses the YAML and compares dicts passes even when every
comment is gone. Comparing raw text is the only assertion that actually protects
AC10.

### FILL IN checklist
- [ ] `toolkit_seed.py::_find_section_span` — span detection incl. leading comments; bounded by AC10
- [ ] `toolkit_seed.py::set_section_enabled` — in-place flip or insert, preserve indent; bounded by AC10
- [ ] `toolkit_seed.py::remove_section` — drop span, collapse blank runs, keep `toolkits:`; bounded by AC10
- [ ] `toolkit_seed.py::seed_toolkit_sections` — in-memory assembly + one atomic write; bounded by AC8
- [ ] `test_toolkit_seed.py` — six new cases asserting on raw file text; bounded by AC8, AC10

---

## Acceptance Criteria

- [ ] `preflight_seed` raises `ValueError` for an unknown name and writes nothing
- [ ] `preflight_seed` raises `ValueError` for a malformed existing config
- [ ] A failed `seed_toolkit_sections` leaves `.parrot/mcp-toolkits.yaml` byte-identical
- [ ] `set_section_enabled` / `remove_section` preserve every comment and the
      surrounding sections' formatting (asserted on raw text)
- [ ] Both helpers return `False` for an absent section rather than raising
- [ ] No new dependency added to `packages/ai-parrot/pyproject.toml`
- [ ] No linting errors: `ruff check packages/ai-parrot/src/parrot/mcp/toolkit_seed.py`

---

## Validation Commands

- `pytest tests/mcp/test_toolkit_seed.py -q`
- `pytest tests/mcp/test_toolkit_config.py -q`

---

## Test Specification

```python
# tests/mcp/test_toolkit_seed.py
import pytest
from parrot.mcp.toolkit_seed import preflight_seed, remove_section, seed_toolkit_sections, set_section_enabled

COMMENTED = """toolkits:
  # operator note that must survive
  memory:
    class: parrot.tools.working_memory.tool.WorkingMemoryToolkit
    enabled: true
    kwargs: {}  # trailing comment
  bounded-source:
    class: parrot_tools.tool_optimizations.reader.BoundedSourceToolkit
"""


def test_preflight_rejects_unknown_name_before_write(tmp_path):
    with pytest.raises(ValueError, match="No packaged template"):
        preflight_seed(tmp_path, ["definitely-not-a-template"])


def test_seed_unknown_name_leaves_file_byte_identical(tmp_path):
    # FILL IN: write COMMENTED, attempt a seed containing one valid + one unknown
    # name, assert ValueError AND that the file bytes are unchanged
    ...


def test_set_section_enabled_preserves_comments(tmp_path):
    # FILL IN: assert "operator note that must survive" and "# trailing comment"
    # are still present in the RAW text after toggling memory to disabled
    ...
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** (§3 Module 4, §7 Known Risks, design research S4 and S5).
2. **Check dependencies** — TASK-3368 must be in `sdd/tasks/completed/`.
3. **Verify the Codebase Contract** — confirm `seed_toolkit_sections` is still at
   `toolkit_seed.py:154` and that the `BUILTIN_TOOLKITS` import is already gone.
4. **Update status** in `sdd/tasks/index/expose-local-mcp-tools.json` → `"in-progress"`.
5. **Implement** from the Implementation Blueprint; complete every `# FILL IN:`.
6. **Verify** all acceptance criteria.
7. **Move this file** to `sdd/tasks/completed/TASK-3369-seed-preflight-and-mutation-helpers.md`.
8. **Update index** → `"done"`.
9. **Fill in the Completion Note** below.

---

## Completion Note

**Completed by**: sdd-coder (native, sonnet)
**Date**: 2026-09-18
**Notes**: Added `_config_path`, `_atomic_write`, `preflight_seed` (all-or-nothing
unknown-name + malformed-YAML rejection), `_find_section_span`,
`set_section_enabled` and `remove_section` (lexical, comment-preserving) to
`toolkit_seed.py`; `seed_toolkit_sections` now preflights, assembles the full
file text in memory, then does exactly one atomic write instead of appending.
Replaced pre-existing `test_unknown_name_reported_not_raised` (asserted the OLD
non-atomic report-but-still-seed behavior) with
`test_seed_unknown_name_raises_before_writing_new_sections`, since the old
assertions directly contradicted this task's AC8 all-or-nothing mandate —
confirmed against spec §5's own test list, which has no surviving counterpart
for the old test. Validation: `pytest tests/mcp/test_toolkit_seed.py
tests/mcp/test_toolkit_config.py -q` → 35 passed; `ruff check --no-cache`
clean. Merge-tier check: only "file not found" for sibling tasks' not-yet-
created test files (TASK-3372, TASK-3376) — no real regressions. Lint autofix
(black) applied by the merge gate, commit 82e5ab77b.
Seat: sonnet · Backend: native · Model: sonnet · Attempts: 1 · Duration: n/a · Tokens: n/a

**Deviations from spec**: Replaced one pre-existing test
(`test_unknown_name_reported_not_raised` → `test_seed_unknown_name_raises_before_writing_new_sections`)
whose assertions were incompatible with the new all-or-nothing preflight
contract this task mandates (AC8). Verified against spec §4/§5 — required, not
scope creep.
