"""Tests for parrot.knowledge.graphindex.extractors.odoo_code.OdooCodeExtractor
(FEAT-240)."""

from __future__ import annotations

import pytest

from parrot.knowledge.graphindex.extractors.code import CodeExtractor
from parrot.knowledge.graphindex.extractors.odoo_code import OdooCodeExtractor
from parrot.knowledge.graphindex.schema import EdgeKind

# ---------------------------------------------------------------------------
# Test fixtures / source snippets
# ---------------------------------------------------------------------------

ODOO_DEFINE = """
from odoo import models, fields, api

class ResPartner(models.Model):
    _name = 'res.partner'
    _inherit = ['mail.thread']

    vat_verified = fields.Boolean(string='VAT Verified')

    @api.depends('vat')
    def _compute_vat_status(self):
        pass
"""

ODOO_EXTEND = """
from odoo import models, fields

class ResPartnerExt(models.Model):
    _inherit = 'res.partner'
    loyalty = fields.Integer(string='Points')
"""

ODOO_INHERITS_DICT = """
from odoo import models

class SaleOrder(models.Model):
    _name = 'sale.order'
    _inherits = {'account.move': 'invoice_id', 'res.partner': 'partner_id'}
"""

ODOO_INHERIT_LIST = """
from odoo import models

class HrEmployee(models.Model):
    _name = 'hr.employee'
    _inherit = ['mail.thread', 'mail.activity.mixin']
"""

ODOO_FIELD_KWARGS = """
from odoo import models, fields

class StockMove(models.Model):
    _name = 'stock.move'

    partner_id = fields.Many2one('res.partner', string='Partner', required=True)
    qty = fields.Float(compute='_compute_qty', store=True)
"""

DYNAMIC_NAME = """
from odoo import models

class X(models.Model):
    _name = f"x.{var}"
"""

PLAIN = """
class Service:
    def run(self):
        pass
"""

ODOO_NO_NAME_NO_INHERIT = """
from odoo import models

class MyMixin(models.AbstractModel):
    pass
"""


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestOdooCodeExtractor:
    """Tests for OdooCodeExtractor."""

    @pytest.fixture
    def ext(self):
        """Return a fresh OdooCodeExtractor instance."""
        return OdooCodeExtractor()

    # ------------------------------------------------------------------
    # DEFINES — _name present
    # ------------------------------------------------------------------

    @pytest.mark.asyncio
    async def test_define_emits_canonical_node(self, ext):
        """A class with _name emits an odoo_model canonical node."""
        nodes, edges = await ext.extract("mod/models.py", ODOO_DEFINE)
        canonicals = [
            n for n in nodes if n.domain_tags.get("symbol_type") == "odoo_model"
        ]
        assert len(canonicals) >= 1
        assert canonicals[0].source_uri == "odoo-model://res.partner"
        assert canonicals[0].title == "res.partner"

    @pytest.mark.asyncio
    async def test_define_emits_odoo_model_class(self, ext):
        """A class with _name has symbol_type == odoo_model_class."""
        nodes, _ = await ext.extract("mod/models.py", ODOO_DEFINE)
        classes = [
            n for n in nodes if n.domain_tags.get("symbol_type") == "odoo_model_class"
        ]
        assert any(c.title == "ResPartner" for c in classes)

    @pytest.mark.asyncio
    async def test_define_emits_defines_edge_to_canonical(self, ext):
        """DEFINES edge points from the class to the canonical model node."""
        nodes, edges = await ext.extract("mod/models.py", ODOO_DEFINE)
        canonical = next(
            (n for n in nodes if n.domain_tags.get("symbol_type") == "odoo_model"),
            None,
        )
        assert canonical is not None
        defines = [e for e in edges if e.kind == EdgeKind.DEFINES]
        # The class → canonical DEFINES edge must exist
        class_node = next(
            (n for n in nodes if n.domain_tags.get("symbol_type") == "odoo_model_class"),
            None,
        )
        assert class_node is not None
        assert any(
            e.source_id == class_node.node_id and e.target_id == canonical.node_id
            for e in defines
        )

    # ------------------------------------------------------------------
    # EXTENDS — _inherit without _name
    # ------------------------------------------------------------------

    @pytest.mark.asyncio
    async def test_extend_emits_extends_edge(self, ext):
        """A class with only _inherit emits one EXTENDS edge."""
        nodes, edges = await ext.extract("ext/models.py", ODOO_EXTEND)
        extends = [e for e in edges if e.kind == EdgeKind.EXTENDS]
        assert len(extends) == 1

    @pytest.mark.asyncio
    async def test_extend_no_defines_edge_to_inherited(self, ext):
        """When only _inherit is set (no _name), no DEFINES to the extended model."""
        nodes, edges = await ext.extract("ext/models.py", ODOO_EXTEND)
        canonical = next(
            (
                n
                for n in nodes
                if n.domain_tags.get("symbol_type") == "odoo_model"
                and n.title == "res.partner"
            ),
            None,
        )
        assert canonical is not None
        defines_to_canonical = [
            e
            for e in edges
            if e.kind == EdgeKind.DEFINES and e.target_id == canonical.node_id
        ]
        assert len(defines_to_canonical) == 0

    # ------------------------------------------------------------------
    # EXTENDS — _inherit as list
    # ------------------------------------------------------------------

    @pytest.mark.asyncio
    async def test_inherit_list_produces_multiple_extends(self, ext):
        """_inherit as list produces one EXTENDS per inherited model."""
        nodes, edges = await ext.extract("mod/hr.py", ODOO_INHERIT_LIST)
        extends = [e for e in edges if e.kind == EdgeKind.EXTENDS]
        inherited_targets = {
            n.title
            for n in nodes
            if n.domain_tags.get("symbol_type") == "odoo_model"
        }
        assert "mail.thread" in inherited_targets
        assert "mail.activity.mixin" in inherited_targets
        assert len(extends) == 2

    # ------------------------------------------------------------------
    # EXTENDS — _inherits as dict
    # ------------------------------------------------------------------

    @pytest.mark.asyncio
    async def test_inherits_dict_produces_multiple_extends(self, ext):
        """_inherits as dict produces one EXTENDS per key."""
        nodes, edges = await ext.extract("mod/sale.py", ODOO_INHERITS_DICT)
        extends = [e for e in edges if e.kind == EdgeKind.EXTENDS]
        assert len(extends) == 2
        inherited = {
            n.title
            for n in nodes
            if n.domain_tags.get("symbol_type") == "odoo_model"
            and n.title != "sale.order"
        }
        assert "account.move" in inherited
        assert "res.partner" in inherited

    # ------------------------------------------------------------------
    # Field extraction
    # ------------------------------------------------------------------

    @pytest.mark.asyncio
    async def test_field_extracted_with_correct_type(self, ext):
        """fields.Boolean(...) produces an odoo_field with field_type=Boolean."""
        nodes, _ = await ext.extract("mod/models.py", ODOO_DEFINE)
        fields = [
            n for n in nodes if n.domain_tags.get("symbol_type") == "odoo_field"
        ]
        assert len(fields) >= 1
        boolean_field = next(
            (f for f in fields if f.domain_tags.get("field_type") == "Boolean"), None
        )
        assert boolean_field is not None
        assert boolean_field.title == "vat_verified"

    @pytest.mark.asyncio
    async def test_field_kwargs_captured(self, ext):
        """Field kwarg 'string' is captured in domain_tags."""
        nodes, _ = await ext.extract("mod/models.py", ODOO_DEFINE)
        field = next(
            (
                n
                for n in nodes
                if n.domain_tags.get("symbol_type") == "odoo_field"
                and n.title == "vat_verified"
            ),
            None,
        )
        assert field is not None
        assert field.domain_tags.get("string") == "VAT Verified"

    @pytest.mark.asyncio
    async def test_field_comodel_positional_arg(self, ext):
        """First positional string arg becomes comodel_name."""
        nodes, _ = await ext.extract("mod/stock.py", ODOO_FIELD_KWARGS)
        field = next(
            (
                n
                for n in nodes
                if n.domain_tags.get("symbol_type") == "odoo_field"
                and n.title == "partner_id"
            ),
            None,
        )
        assert field is not None
        assert field.domain_tags.get("comodel_name") == "res.partner"

    @pytest.mark.asyncio
    async def test_field_summary_equals_string_kwarg(self, ext):
        """Field summary is set from 'string' kwarg."""
        nodes, _ = await ext.extract("mod/models.py", ODOO_DEFINE)
        field = next(
            (
                n
                for n in nodes
                if n.domain_tags.get("symbol_type") == "odoo_field"
                and n.title == "vat_verified"
            ),
            None,
        )
        assert field is not None
        assert field.summary == "VAT Verified"

    # ------------------------------------------------------------------
    # Decorator extraction
    # ------------------------------------------------------------------

    @pytest.mark.asyncio
    async def test_decorator_annotation_stored(self, ext):
        """@api.depends stored in domain_tags['decorators']."""
        nodes, _ = await ext.extract("mod/models.py", ODOO_DEFINE)
        funcs = [
            n for n in nodes if n.domain_tags.get("symbol_type") == "function"
        ]
        decorated = [f for f in funcs if "decorators" in f.domain_tags]
        assert len(decorated) >= 1
        deco = decorated[0].domain_tags["decorators"][0]
        assert deco["name"] == "depends"
        assert "vat" in deco["args"]

    # ------------------------------------------------------------------
    # Plain class fallback
    # ------------------------------------------------------------------

    @pytest.mark.asyncio
    async def test_plain_class_fallback_identical_output(self, ext):
        """Non-Odoo class produces exactly the same node count as base extractor."""
        base_ext = CodeExtractor()
        odoo_nodes, _ = await ext.extract("svc.py", PLAIN)
        base_nodes, _ = await base_ext.extract("svc.py", PLAIN)
        assert len(odoo_nodes) == len(base_nodes)

    @pytest.mark.asyncio
    async def test_plain_class_no_odoo_tags(self, ext):
        """Non-Odoo class does not emit odoo_model or odoo_model_class nodes."""
        nodes, _ = await ext.extract("svc.py", PLAIN)
        odoo_types = {
            n.domain_tags.get("symbol_type")
            for n in nodes
            if n.domain_tags.get("symbol_type") in ("odoo_model", "odoo_model_class")
        }
        assert len(odoo_types) == 0

    # ------------------------------------------------------------------
    # Dynamic _name — no crash
    # ------------------------------------------------------------------

    @pytest.mark.asyncio
    async def test_dynamic_name_no_crash(self, ext):
        """Dynamic _name (f-string) produces no canonical links but no errors."""
        nodes, edges = await ext.extract("dyn.py", DYNAMIC_NAME)
        canonicals = [
            n for n in nodes if n.domain_tags.get("symbol_type") == "odoo_model"
        ]
        assert len(canonicals) == 0

    @pytest.mark.asyncio
    async def test_dynamic_name_class_still_emitted(self, ext):
        """Even with a dynamic _name, the class node is still emitted."""
        nodes, _ = await ext.extract("dyn.py", DYNAMIC_NAME)
        class_nodes = [
            n for n in nodes if n.domain_tags.get("symbol_type") == "odoo_model_class"
        ]
        # Class detected via base class (AbstractModel/Model hint) — emitted as odoo_model_class
        # because the class has Odoo base
        assert len(class_nodes) >= 1

    # ------------------------------------------------------------------
    # Lineno stamping
    # ------------------------------------------------------------------

    @pytest.mark.asyncio
    async def test_model_class_has_lineno(self, ext):
        """odoo_model_class node carries lineno/end_lineno."""
        nodes, _ = await ext.extract("mod/models.py", ODOO_DEFINE)
        class_node = next(
            (
                n
                for n in nodes
                if n.domain_tags.get("symbol_type") == "odoo_model_class"
            ),
            None,
        )
        assert class_node is not None
        assert "lineno" in class_node.domain_tags
        assert "end_lineno" in class_node.domain_tags
        assert class_node.domain_tags["lineno"] >= 1

    @pytest.mark.asyncio
    async def test_field_has_lineno(self, ext):
        """odoo_field node carries lineno/end_lineno."""
        nodes, _ = await ext.extract("mod/models.py", ODOO_DEFINE)
        field = next(
            (n for n in nodes if n.domain_tags.get("symbol_type") == "odoo_field"),
            None,
        )
        assert field is not None
        assert "lineno" in field.domain_tags
        assert "end_lineno" in field.domain_tags

    # ------------------------------------------------------------------
    # AbstractModel (no _name, no _inherit) — detected via base class
    # ------------------------------------------------------------------

    @pytest.mark.asyncio
    async def test_abstract_model_no_name_no_inherit(self, ext):
        """AbstractModel subclass detected via base class, emitted as odoo_model_class."""
        nodes, _ = await ext.extract("mod/mixin.py", ODOO_NO_NAME_NO_INHERIT)
        classes = [
            n for n in nodes if n.domain_tags.get("symbol_type") == "odoo_model_class"
        ]
        assert any(c.title == "MyMixin" for c in classes)

    # ------------------------------------------------------------------
    # module node still has sha1 (inherited from TASK-1572)
    # ------------------------------------------------------------------

    @pytest.mark.asyncio
    async def test_module_node_has_sha1(self, ext):
        """Module node inherits sha1 stamping from base extractor (TASK-1572)."""
        nodes, _ = await ext.extract("mod/models.py", ODOO_DEFINE)
        module = next(
            (n for n in nodes if n.domain_tags.get("symbol_type") == "module"), None
        )
        assert module is not None
        assert "sha1" in module.domain_tags
        assert len(module.domain_tags["sha1"]) == 40

    # ------------------------------------------------------------------
    # _inherit self-reference excluded from EXTENDS
    # ------------------------------------------------------------------

    @pytest.mark.asyncio
    async def test_inherit_self_excluded_from_extends(self, ext):
        """When _inherit == _name, no EXTENDS edge to self is emitted."""
        src = """
from odoo import models

class ResPartner(models.Model):
    _name = 'res.partner'
    _inherit = 'res.partner'
"""
        nodes, edges = await ext.extract("mod/p.py", src)
        extends = [e for e in edges if e.kind == EdgeKind.EXTENDS]
        assert len(extends) == 0
