# TASK-1574: OdooCodeExtractor

**Feature**: FEAT-240 — GraphIndex Odoo-aware Extractor + SQLite Persistence + Graph Reader
**Spec**: `sdd/specs/odoo-graphindex-code.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: L (4-8h)
**Depends-on**: TASK-1571, TASK-1572
**Assigned-to**: unassigned

---

## Context

The OdooCodeExtractor is the core domain-specific component. It subclasses
`CodeExtractor` to detect Odoo model classes via `_name`/`_inherit`/`_inherits`
assignments and Odoo base classes, emitting canonical model nodes, `EXTENDS`/
`DEFINES` edges, field nodes, and decorator annotations. Non-Odoo classes
fall back to the base extractor.

Implements Spec §3 Module 4. Reference implementation in brainstorm §5.

---

## Scope

- Create `OdooCodeExtractor(CodeExtractor)` class
- Override `_extract_class` to:
  - Detect Odoo model classes (via `_name`/`_inherit`/`_inherits` or base classes `Model`/`TransientModel`/`AbstractModel`)
  - Emit `odoo_model_class` nodes with model metadata in `domain_tags`
  - Create/upsert canonical `odoo_model` nodes with synthetic `source_uri` (`odoo-model://<name>`)
  - Emit `DEFINES` edges (class→canonical when `_name` present)
  - Emit `EXTENDS` edges (class→canonical for each `_inherit`/`_inherits` name)
  - Fall back to `super()._extract_class()` for non-Odoo classes
- Walk model body to extract:
  - `fields.*` declarations → `odoo_field` nodes with `field_type`, `comodel_name`, `string`, etc.
  - `@api.*` decorators → `decorators` list in function's `domain_tags`
- Handle edge cases: dynamic `_name` (f-strings), `_inherit` as string/list, `_inherits` as dict
- Write comprehensive tests

**NOT in scope**: SQLitePersistence, SQLiteGraphReader, builder wiring

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/knowledge/graphindex/extractors/odoo_code.py` | CREATE | OdooCodeExtractor class |
| `packages/ai-parrot/src/parrot/knowledge/graphindex/extractors/__init__.py` | MODIFY | Export OdooCodeExtractor |
| `packages/ai-parrot/tests/knowledge/graphindex/test_odoo_extractor.py` | CREATE | Tests |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from parrot.knowledge.graphindex.extractors.code import (
    CodeExtractor,   # verified: code.py:61
    _make_node_id,   # verified: code.py:34
    _get_node_text,  # verified: code.py:48
)
from parrot.knowledge.graphindex.schema import (
    EdgeKind,        # verified: schema.py:53
    NodeKind,        # verified: schema.py:33
    Provenance,      # verified: schema.py:18
    UniversalNode,   # verified: schema.py:71
    UniversalEdge,   # verified: schema.py:102
)
```

### Existing Signatures to Use
```python
# packages/ai-parrot/src/parrot/knowledge/graphindex/extractors/code.py

def _make_node_id(source_uri: str, symbol: str) -> str:  # line 34
    # Returns: hashlib.sha1(f"{source_uri}::{symbol}".encode()).hexdigest()[:16]

def _get_node_text(node, source_bytes: bytes) -> str:  # line 48
    # Returns: source_bytes[node.start_byte:node.end_byte].decode(...)

class CodeExtractor:  # line 61
    async def extract(
        self, file_path: str, source: str, *, mtime: Optional[float] = None,
    ) -> tuple[list[UniversalNode], list[UniversalEdge]]:  # line 95
    # (mtime added by TASK-1572)

    def _extract_class(
        self, node, file_path: str, source_bytes: bytes,
        parent_id: str, nodes: list[UniversalNode],
        edges: list[UniversalEdge],
    ) -> str:  # line 237
    # Returns the class node_id

    def _extract_function(
        self, node, file_path: str, source_bytes: bytes,
        parent_id: str, nodes: list[UniversalNode],
        edges: list[UniversalEdge],
    ) -> str:  # line 295

    def _get_docstring(
        self, func_or_class_node, source_bytes: bytes,
    ) -> Optional[str]:  # line 374
```

### Does NOT Exist
- ~~`OdooCodeExtractor`~~ — this task creates it
- ~~`extractors/odoo_code.py`~~ — file does not exist yet
- ~~`EdgeKind.EXTENDS`~~ — created by TASK-1571 (dependency)
- ~~`CodeExtractor._extract_model_meta()`~~ — does not exist in base; new to this class
- ~~`CodeExtractor._extract_bases()`~~ — does not exist in base; new to this class

---

## Implementation Notes

### Design (from brainstorm §5)

The brainstorm provides a complete reference implementation. Key design points:

1. **`_extract_class` override**: Check for Odoo signals first. If none found,
   `return super()._extract_class(...)`. This is the fallback mechanism.

2. **`_extract_model_meta`**: Walk the class body for `_name`, `_inherit`,
   `_inherits` assignments. Use `_literal_value` helper for safe literal evaluation.

3. **`_link_model`**: Create canonical `odoo_model` nodes with stable IDs via
   `_make_node_id("__odoo_model__", model_name)`. Emit `DEFINES` for `_name`,
   `EXTENDS` for each inherited model (excluding self-inherit).

4. **`_walk_model_body`**: Iterate class body for field assignments and decorated
   functions. Fields detected by `fields.X(...)` call pattern.

5. **`_maybe_extract_field`**: Parse `name = fields.Type(...)` pattern. Extract
   kwargs like `comodel_name`, `string`, `compute`, `store`, etc.

6. **`_extract_decorators`**: Parse `@api.depends(...)` and similar. Store as
   `[{"name": "depends", "args": ["a", "b"]}]` in `domain_tags["decorators"]`.

### Key Constraints
- Canonical model `node_id`: `_make_node_id("__odoo_model__", model_name)` for stability
- Canonical model `source_uri`: `f"odoo-model://{model_name}"` (NEVER a file path)
- Non-Odoo classes MUST produce identical output to base `CodeExtractor`
- Dynamic `_name` (f-strings, concatenation) → skip canonical linking, don't crash
- `_inherit = "same.model"` where `_name` is also set → do NOT emit `EXTENDS` to self

### References in Codebase
- `packages/ai-parrot/src/parrot/knowledge/graphindex/extractors/code.py` — base class
- `sdd/proposals/odoo-graphindex-code.brainstorm.md` §5 — reference implementation

---

## Acceptance Criteria

- [ ] `_name = 'x.y'` → `odoo_model_class` node + canonical `odoo_model` node + `DEFINES` edge
- [ ] `_inherit = 'res.partner'` (no `_name`) → `EXTENDS` edge, no `DEFINES`
- [ ] `_inherit` as list → one `EXTENDS` per name
- [ ] `_inherits` as dict → one `EXTENDS` per key
- [ ] `fields.Many2one('res.partner', string='Cliente')` → `odoo_field` node with correct kwargs
- [ ] `@api.depends('a', 'b')` → `decorators` in domain_tags
- [ ] Plain Python class → identical to base CodeExtractor output
- [ ] `_name = f"x.{var}"` → no crash, no canonical links
- [ ] All symbol nodes have `lineno`/`end_lineno`
- [ ] Tests pass: `pytest packages/ai-parrot/tests/knowledge/graphindex/test_odoo_extractor.py -v`

---

## Test Specification

```python
import pytest
from parrot.knowledge.graphindex.extractors.odoo_code import OdooCodeExtractor
from parrot.knowledge.graphindex.schema import EdgeKind, NodeKind

ODOO_DEFINE = '''
from odoo import models, fields, api

class ResPartner(models.Model):
    _name = 'res.partner'
    _inherit = ['mail.thread']

    vat_verified = fields.Boolean(string='VAT Verified')

    @api.depends('vat')
    def _compute_vat_status(self):
        pass
'''

ODOO_EXTEND = '''
from odoo import models, fields

class ResPartnerExt(models.Model):
    _inherit = 'res.partner'
    loyalty = fields.Integer(string='Points')
'''

PLAIN = '''
class Service:
    def run(self):
        pass
'''

class TestOdooCodeExtractor:
    async def test_define_model(self):
        ext = OdooCodeExtractor()
        nodes, edges = await ext.extract("mod/models.py", ODOO_DEFINE)
        # canonical node, model class, field, function, module = 5 nodes
        canonicals = [n for n in nodes if n.domain_tags.get("symbol_type") == "odoo_model"]
        assert len(canonicals) >= 1
        assert canonicals[0].source_uri == "odoo-model://res.partner"
        defines = [e for e in edges if e.kind == EdgeKind.DEFINES]
        assert any(e.target_id == canonicals[0].node_id for e in defines)

    async def test_extend_model(self):
        ext = OdooCodeExtractor()
        nodes, edges = await ext.extract("ext/models.py", ODOO_EXTEND)
        extends = [e for e in edges if e.kind == EdgeKind.EXTENDS]
        assert len(extends) == 1

    async def test_field_extraction(self):
        ext = OdooCodeExtractor()
        nodes, _ = await ext.extract("mod/models.py", ODOO_DEFINE)
        fields = [n for n in nodes if n.domain_tags.get("symbol_type") == "odoo_field"]
        assert len(fields) == 1
        assert fields[0].domain_tags["field_type"] == "Boolean"

    async def test_decorator_annotation(self):
        ext = OdooCodeExtractor()
        nodes, _ = await ext.extract("mod/models.py", ODOO_DEFINE)
        funcs = [n for n in nodes if n.domain_tags.get("symbol_type") == "function"]
        decorated = [f for f in funcs if "decorators" in f.domain_tags]
        assert len(decorated) == 1
        assert decorated[0].domain_tags["decorators"][0]["name"] == "depends"

    async def test_plain_class_fallback(self):
        from parrot.knowledge.graphindex.extractors.code import CodeExtractor
        odoo_ext = OdooCodeExtractor()
        base_ext = CodeExtractor()
        odoo_nodes, _ = await odoo_ext.extract("svc.py", PLAIN)
        base_nodes, _ = await base_ext.extract("svc.py", PLAIN)
        assert len(odoo_nodes) == len(base_nodes)

    async def test_dynamic_name_no_crash(self):
        src = 'from odoo import models\nclass X(models.Model):\n    _name = f"x.{y}"\n'
        ext = OdooCodeExtractor()
        nodes, edges = await ext.extract("dyn.py", src)
        canonicals = [n for n in nodes if n.domain_tags.get("symbol_type") == "odoo_model"]
        assert len(canonicals) == 0  # no canonical since name is dynamic
```

---

## Completion Note

*(Agent fills this in when done)*
