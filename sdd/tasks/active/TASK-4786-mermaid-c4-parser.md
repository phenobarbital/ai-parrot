# TASK-4786: Mermaid C4 parser (`from_mermaid_c4`) + `from_mermaid` dispatch + round-trip

**Feature**: FEAT-754 — C4 architecture diagrams as a `Graph` kind
**Spec**: `sdd/specs/a2ui-c4-diagrams.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: L (4-8h)
**Depends-on**: TASK-4785
**Assigned-to**: unassigned

---

## Context

Spec §3 Module 2, parse half. Adds `from_mermaid_c4` to the module TASK-4785 created, routes
`from_mermaid` for `C4*` headers, and proves the round-trip contract (byte-stable text; object
equality after the spec's normalization minus `C4_LOSSY_FIELDS`). Also produces the upstream
Mermaid parse evidence required before M2 acceptance.

---

## Scope

- Implement `from_mermaid_c4(text)` and `_split_macro_args(line_no, content, raw)` in `mermaid_c4.py`
  using `_prepare_lines`, `_unescape_label`, `_IDENT`, the inverted tables, and line-addressed
  `MermaidCodecError`s with the fixed reason texts of spec §3 M2 ("Rejected").
- Accept spelled aliases `Rel_Up/Rel_Down/Rel_Left/Rel_Right`; parse `RelIndex` (sort by index;
  gaps/duplicates raise) and plain `Rel` inside `C4Dynamic` (numbered after indexed ones).
- Add the `C4` header branch in `from_mermaid` before the "unrecognized … header" raise.
- Append parser and round-trip tests to `test_mermaid_c4.py` (spec §4 M2 rows).
- Record upstream Mermaid verification (exact version; every emitted macro parsed) under
  `artifacts/logs/feat-754-mermaid-c4-upstream.md` (external env; no project dependency).

**NOT in scope**: emitter changes beyond bug fixes found by round-trip; `graph/__init__.py` re-export (TASK-4793).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/outputs/a2ui/graph/mermaid_c4.py` | MODIFY | parser |
| `packages/ai-parrot/src/parrot/outputs/a2ui/graph/mermaid.py` | MODIFY | `from_mermaid` C4 dispatch |
| `packages/ai-parrot/tests/outputs/a2ui/graph/test_mermaid_c4.py` | MODIFY | parser + round-trip tests |
| `artifacts/logs/feat-754-mermaid-c4-upstream.md` | CREATE | upstream Mermaid evidence (`git add -f`, artifacts/ is ignored) |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from parrot.outputs.a2ui.graph.mermaid import MermaidCodecError, _unescape_label, _prepare_lines, _IDENT  # verified: mermaid.py:126,153,174,109
from parrot.outputs.a2ui.graph.mermaid import from_mermaid, to_mermaid  # verified: mermaid.py:323,206
from parrot.outputs.a2ui.graph.mermaid_c4 import C4_LOSSY_FIELDS, to_mermaid_c4  # created by TASK-4785
from parrot.outputs.a2ui.catalog.base import CatalogValidationError  # verified: catalog/base.py:317
```

### Existing Signatures to Use
```python
# mermaid.py (verified at 65144d730)
def _unescape_label(token: Optional[str]) -> Optional[str]                     # line 153
def _prepare_lines(text: str) -> list[tuple[int, str]]                         # line 174 (drops blanks/%% ; rejects %%{ at 191)
def from_mermaid(text: str) -> GraphSpec                                        # line 323; header dispatch 344-349
    raise MermaidCodecError(header_no, header, "unrecognized or unsupported diagram header")   # line 350
# mermaid_c4.py (TASK-4785): _LEVEL_HEADER, _ELEMENT_MACRO, _MACRO_ELEMENT, _BOUNDARY_MACRO, _REL_MACRO
```

### Does NOT Exist
- ~~`Deployment_Node` / `Node` / C4Deployment support~~ — reject.
- ~~`neighbor` hints~~ — `Rel_Neighbor`/`Rel_Back_Neighbor` are unknown macros → `MermaidCodecError`.
- ~~a mermaid npm/pip dependency in the project~~ — upstream check runs in an external environment only.

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {"path": "packages/ai-parrot/src/parrot/outputs/a2ui/graph/mermaid_c4.py", "action": "MODIFY"},
    {"path": "packages/ai-parrot/src/parrot/outputs/a2ui/graph/mermaid.py", "action": "MODIFY"},
    {"path": "packages/ai-parrot/tests/outputs/a2ui/graph/test_mermaid_c4.py", "action": "MODIFY"},
    {"path": "artifacts/logs/feat-754-mermaid-c4-upstream.md", "action": "CREATE"}
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot/src/parrot/outputs/a2ui/graph/mermaid.py#from_mermaid",
    "sym:packages/ai-parrot/src/parrot/outputs/a2ui/graph/mermaid.py#_prepare_lines",
    "sym:packages/ai-parrot/src/parrot/outputs/a2ui/graph/mermaid.py#_unescape_label"
  ]
}
```

---

## Implementation Notes

### Key Constraints
- Reason texts fixed: "styling is not in the supported subset"; "sprite/tags/link arguments are not in the supported subset".
- Parsed specs get `direction="TB"`; label equal to id → `None`; empty optional strings → `None`.
- Round-trip normalization (spec §3 M2) is applied by the TESTS (a `_normalize` helper in the test
  module), not by the parser. `C4_LOSSY_FIELDS` is dotted paths — apply nested exclusions per node/edge/layout.
- Test both canonical and noncanonical (child-before-parent groups, interleaved nodes) inputs.

---

## Implementation Blueprint

### Steps (in order)
1. Add `_split_macro_args` — *why*: commas inside quoted labels must not split.
2. Add `from_mermaid_c4`: header → level; optional `title`; a boundary stack for `{`/`}`; element / boundary / rel / `UpdateLayoutConfig` regexes; rejections.
3. Restore `"from_mermaid_c4"` in `__all__`.
4. Add the `from_mermaid` branch (function-local import).
5. Append tests incl. `_normalize`; run; then the external upstream check and log.

### `packages/ai-parrot/src/parrot/outputs/a2ui/graph/mermaid_c4.py` (MODIFY)
```python
# AFTER to_mermaid_c4 (end of file)
def _split_macro_args(line_no: int, content: str, raw: str) -> list[str]:
    """Split a macro argument list on top-level commas, honouring double quotes; strips and unescapes each."""
    # FILL IN: char scan with in_quote flag; unbalanced quote → MermaidCodecError(line_no, raw, ...)
    raise NotImplementedError


def from_mermaid_c4(text: str) -> GraphSpec:
    """Parse Mermaid C4 source (C4Context/C4Container/C4Component/C4Dynamic) into a ``kind="c4"`` GraphSpec.

    Raises:
        MermaidCodecError: empty source, unknown header, unknown/unsupported macro, styling or
            sprite/tags/link arguments, arity violation, bad identifier, unbalanced boundary block,
            duplicate/gapped RelIndex — always naming the offending line.
    """
    lines = _prepare_lines(text)
    # FILL IN: header line → level via inverted _LEVEL_HEADER, else MermaidCodecError
    # FILL IN: walk lines with a stack of open boundary ids; nodes get group membership via the innermost boundary
    # FILL IN: rejections — UpdateElementStyle/UpdateRelStyle, $sprite=/$tags=/$link=, arity, _IDENT, stray "}",
    #          unclosed boundary at EOF, Deployment_Node/Node, unknown macro
    # FILL IN: RelIndex ordering (gaps/duplicates raise); plain Rel in C4Dynamic numbered after indexed
    # FILL IN: build GraphSpec(kind="c4", level=..., ...) — let model validation (V1–V7) run
    raise NotImplementedError
```
**Why**: one entry point, strict arity (spec §8 Q4: raise on drift).

### `packages/ai-parrot/src/parrot/outputs/a2ui/graph/mermaid.py` (MODIFY)
```python
# occurrences: 1 (verified: grep -c 'raise MermaidCodecError(header_no, header, "unrecognized or unsupported diagram header")' mermaid.py)
# BEFORE — insert above that raise (verified: mermaid.py:350)
    if stripped_header.startswith("C4"):
        # Function-local: mermaid_c4 imports this module.
        from .mermaid_c4 import from_mermaid_c4

        return from_mermaid_c4(text)
# verified: mermaid.py:342-343 bind `header_no, header = lines[0]` and `stripped_header = header.strip()`
```

### `packages/ai-parrot/tests/outputs/a2ui/graph/test_mermaid_c4.py` (MODIFY — append)
```python
from parrot.outputs.a2ui.graph.mermaid import MermaidCodecError, from_mermaid
from parrot.outputs.a2ui.graph.mermaid_c4 import C4_LOSSY_FIELDS, from_mermaid_c4
from parrot.outputs.a2ui.catalog.base import CatalogValidationError


def _normalize(spec: GraphSpec) -> dict: ...  # FILL IN: spec §3 M2 "Round-trip normalization", nested lossy exclusions

def test_c4_roundtrip_container_level_byte_stable() -> None: ...
def test_c4_roundtrip_each_level_header() -> None: ...
def test_c4_all_twenty_element_macros() -> None: ...
def test_c4_roundtrip_normalization() -> None: ...
def test_c4_rejects_neighbor_macros() -> None: ...
def test_c4_nested_boundaries() -> None: ...
def test_c4_rel_macros_and_birel() -> None: ...
def test_c4_dynamic_relindex_ordering() -> None: ...
def test_c4_update_layout_config() -> None: ...
def test_c4_rejects_styling_sprites_and_deployment() -> None: ...
def test_c4_quotes_and_unescapes_labels() -> None: ...
def test_c4_error_is_catalog_validation_error() -> None: ...
def test_generic_dispatch_to_c4() -> None: ...
# FILL IN: every body — bounded by spec §4 M2 rows
```

### `artifacts/logs/feat-754-mermaid-c4-upstream.md` (CREATE)
Record: Mermaid version, environment/command used, the canonical example texts (one per emitted macro,
all four headers, `UpdateLayoutConfig`), and pass/fail per example. Stage with `git add -f`.

### FILL IN checklist
- [ ] `_split_macro_args`, `from_mermaid_c4`
- [ ] `_normalize` + 13 test bodies
- [ ] upstream evidence recorded

---

## Acceptance Criteria

- [ ] Fixture round trip is byte-stable and object-equal after normalization minus `C4_LOSSY_FIELDS`.
- [ ] Every rejected construct raises `MermaidCodecError` naming its line.
- [ ] `graph/test_mermaid.py` unchanged and passing.
- [ ] Upstream Mermaid evidence committed under `artifacts/logs/`.

## Validation Commands
- `pytest packages/ai-parrot/tests/outputs/a2ui/graph/test_mermaid_c4.py -q`
- `pytest packages/ai-parrot/tests/outputs/a2ui/graph/test_mermaid.py -q`

---

## Test Specification
Spec §4 M2 rows (names fixed above).

---

## Agent Instructions

Standard FEAT-754 procedure; close with `scripts/sdd/close_task.sh TASK-4786 a2ui-c4-diagrams verified`.

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**:
**Date**:
**Notes**:

**Deviations from spec**: none
