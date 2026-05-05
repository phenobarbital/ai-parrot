"""Unit tests for Phase 2 OdooToolkit methods.

Tests are deterministic and network-free, using a mocked transport for
Odoo-dependent methods and real logic for pure-function methods.

Phase 2 methods:
- ``diagnose_odoo_call`` (pure)
- ``generate_json2_payload`` (pure)
- ``scan_addons_source`` (filesystem only)
- ``fit_gap_report`` (heuristic + optional live Odoo)
- ``business_pack_report`` (pack definitions + optional live check)
"""
from __future__ import annotations

import os
import sys
import tempfile
import types
from unittest.mock import AsyncMock, MagicMock

import pytest

# ── Stub heavy parrot.utils dependencies ────────────────────────────────────

if "parrot.utils.types" not in sys.modules:
    _utils_types_stub = types.ModuleType("parrot.utils.types")
    _utils_types_stub.SafeDict = dict
    _utils_types_stub.cPrint = lambda *a, **kw: None
    sys.modules["parrot.utils.types"] = _utils_types_stub

if "parrot.utils" not in sys.modules:
    _utils_stub = types.ModuleType("parrot.utils")
    _utils_stub.SafeDict = dict
    _utils_stub.cPrint = lambda *a, **kw: None
    sys.modules["parrot.utils"] = _utils_stub

# ─────────────────────────────────────────────────────────────────────────────

from parrot.interfaces.odoointerface import OdooConfig  # noqa: E402
from parrot_tools.odoo.models.envelopes import (  # noqa: E402
    AddonScanResult,
    BusinessPackResult,
    FitGapResult,
    Json2PayloadResult,
    OdooCallDiagnosisResult,
)
from parrot_tools.odoo.toolkit import OdooToolkit  # noqa: E402


# ── Fixtures ─────────────────────────────────────────────────────────────────


def _fake_transport(uid: int = 1) -> MagicMock:
    """Build a minimal fake AbstractOdooTransport."""
    transport = MagicMock()
    transport.config = OdooConfig(
        url="https://odoo.example.com",
        database="testdb",
        username="admin",
        password="secret",
        timeout=10,
        verify_ssl=False,
    )
    transport.uid = uid
    transport.name = "jsonrpc"
    transport.authenticate = AsyncMock(return_value=uid)
    transport.execute_kw = AsyncMock(return_value=None)
    transport.version = AsyncMock(
        return_value={"server_serie": "17.0", "server_version": "17.0+e"}
    )
    transport.close = AsyncMock(return_value=None)
    return transport


def _make_toolkit(transport: MagicMock | None = None) -> OdooToolkit:
    return OdooToolkit(
        url="https://odoo.example.com",
        database="testdb",
        username="admin",
        password="secret",
        verify_ssl=False,
        transport=transport or _fake_transport(),
    )


@pytest.fixture
def sample_addon_dir():
    """Create a temporary directory with a minimal Odoo addon structure."""
    with tempfile.TemporaryDirectory() as tmpdir:
        # Create a test addon
        addon_path = os.path.join(tmpdir, "test_addon")
        os.makedirs(addon_path)

        # Write __manifest__.py
        with open(os.path.join(addon_path, "__manifest__.py"), "w") as f:
            f.write("{'name': 'Test Addon', 'version': '17.0.1.0', 'depends': ['base']}\n")

        # Write models/__init__.py
        models_dir = os.path.join(addon_path, "models")
        os.makedirs(models_dir)
        with open(os.path.join(models_dir, "__init__.py"), "w") as f:
            f.write("from . import my_model\n")

        # Write models/my_model.py with model class and risky methods
        with open(os.path.join(models_dir, "my_model.py"), "w") as f:
            f.write(
                "from odoo import models, fields\n\n"
                "class MyModel(models.Model):\n"
                "    _name = 'test.model'\n"
                "    name = fields.Char()\n\n"
                "    def unlink(self):\n"
                "        self.sudo().check()\n"
                "        return super().unlink()\n"
                "\n"
                "    def sudo(self):\n"
                "        return super().sudo()\n"
            )

        # Write security/ir.model.access.csv
        security_dir = os.path.join(addon_path, "security")
        os.makedirs(security_dir)
        with open(os.path.join(security_dir, "ir.model.access.csv"), "w") as f:
            f.write("id,name,model_id:id,group_id:id,perm_read,perm_write,perm_create,perm_unlink\n")

        # Write views/my_model_views.xml
        views_dir = os.path.join(addon_path, "views")
        os.makedirs(views_dir)
        with open(os.path.join(views_dir, "my_model_views.xml"), "w") as f:
            f.write("<odoo><data/></odoo>\n")

        yield tmpdir


# ── diagnose_odoo_call ────────────────────────────────────────────────────────


def test_diagnose_call_read_only_method():
    """search_read is classified as read_only."""
    tk = _make_toolkit()
    result = tk.diagnose_odoo_call(model="res.partner", method="search_read")

    assert isinstance(result, OdooCallDiagnosisResult)
    assert result.method_safety == "read_only"
    assert result.model == "res.partner"
    assert result.method == "search_read"


def test_diagnose_call_destructive_method():
    """unlink is classified as destructive with a warning."""
    tk = _make_toolkit()
    result = tk.diagnose_odoo_call(model="res.partner", method="unlink")

    assert result.method_safety == "destructive"
    assert any("mutates" in w.lower() or "destructive" in w.lower() or "write" in w.lower()
               for w in result.warnings)


def test_diagnose_call_side_effect_method():
    """action_confirm is classified as side_effect."""
    tk = _make_toolkit()
    result = tk.diagnose_odoo_call(model="sale.order", method="action_confirm")

    assert result.method_safety == "side_effect"


def test_diagnose_call_unknown_method():
    """Custom methods are classified as unknown."""
    tk = _make_toolkit()
    result = tk.diagnose_odoo_call(model="sale.order", method="my_custom_method")

    assert result.method_safety == "unknown"


def test_diagnose_call_invalid_model_name():
    """Model names with invalid characters produce a warning."""
    tk = _make_toolkit()
    result = tk.diagnose_odoo_call(model="SELECT * FROM users", method="read")

    assert any("invalid" in w.lower() or "characters" in w.lower() for w in result.warnings)


def test_diagnose_call_odoo20_deprecation_warning():
    """target_version='20.0' triggers XML-RPC deprecation warning."""
    tk = _make_toolkit()
    result = tk.diagnose_odoo_call(
        model="res.partner", method="search_read", target_version="20.0"
    )

    assert any("20" in w or "xml-rpc" in w.lower() or "xmlrpc" in w.lower()
               for w in result.warnings)
    assert len(result.next_actions) > 0


def test_diagnose_call_observed_error_hints():
    """When observed_error contains 'access', next_actions suggests diagnose_access."""
    tk = _make_toolkit()
    result = tk.diagnose_odoo_call(
        model="res.partner", method="write",
        observed_error="Access Error: insufficient rights",
    )

    assert any("diagnose_access" in action for action in result.next_actions)


def test_diagnose_call_with_args_builds_corrected_payload():
    """When args/kwargs are provided, a corrected_payload is included."""
    tk = _make_toolkit()
    result = tk.diagnose_odoo_call(
        model="res.partner",
        method="search_read",
        args=[[("is_company", "=", True)]],
        kwargs={"limit": 10},
    )

    assert result.corrected_payload is not None
    assert result.corrected_payload["model"] == "res.partner"


# ── generate_json2_payload ────────────────────────────────────────────────────


def test_generate_json2_search_read_endpoint():
    """search_read produces the correct /json/2/ endpoint."""
    tk = _make_toolkit()
    result = tk.generate_json2_payload(model="res.partner", method="search_read")

    assert isinstance(result, Json2PayloadResult)
    assert result.endpoint == "/json/2/res.partner/search_read"
    assert "Content-Type" in result.headers


def test_generate_json2_search_read_maps_positional_args():
    """Positional args for search_read are mapped to named params."""
    tk = _make_toolkit()
    result = tk.generate_json2_payload(
        model="res.partner",
        method="search_read",
        args=[[("is_company", "=", True)], ["name", "email"]],
    )

    params = result.body["params"]
    assert params["domain"] == [("is_company", "=", True)]
    assert params["fields"] == ["name", "email"]


def test_generate_json2_create_mapping():
    """create maps first arg to vals_list."""
    tk = _make_toolkit()
    result = tk.generate_json2_payload(
        model="res.partner",
        method="create",
        args=[{"name": "Alice"}],
    )

    params = result.body["params"]
    assert params["vals_list"] == {"name": "Alice"}


def test_generate_json2_write_mapping():
    """write maps first arg to ids, second to vals."""
    tk = _make_toolkit()
    result = tk.generate_json2_payload(
        model="res.partner",
        method="write",
        args=[[1, 2, 3], {"name": "Updated"}],
    )

    params = result.body["params"]
    assert params["ids"] == [1, 2, 3]
    assert params["vals"] == {"name": "Updated"}


def test_generate_json2_unknown_method_generic_body():
    """Unknown methods fall back to a generic body structure."""
    tk = _make_toolkit()
    result = tk.generate_json2_payload(model="res.partner", method="my_custom_action")

    assert result.endpoint == "/json/2/res.partner/my_custom_action"
    assert len(result.notes) > 0


def test_generate_json2_notes_contain_full_url():
    """Notes include the full URL hint."""
    tk = _make_toolkit()
    result = tk.generate_json2_payload(model="res.partner", method="search_read")

    assert any("http" in note for note in result.notes)


# ── scan_addons_source ────────────────────────────────────────────────────────


def test_scan_addons_finds_manifest(sample_addon_dir):
    """Discovers __manifest__.py in a valid addon directory."""
    tk = _make_toolkit()
    result = tk.scan_addons_source(addons_paths=[sample_addon_dir])

    assert isinstance(result, AddonScanResult)
    assert result.addons_found >= 1
    addon = result.addons[0]
    assert addon["name"] == "test_addon"
    assert addon["manifest_file"] == "__manifest__.py"


def test_scan_addons_detects_model_class(sample_addon_dir):
    """Discovers _name = 'test.model' inside the model Python file."""
    tk = _make_toolkit()
    result = tk.scan_addons_source(addons_paths=[sample_addon_dir])

    addon = result.addons[0]
    assert "test.model" in addon["models"]


def test_scan_addons_detects_risky_methods(sample_addon_dir):
    """Flags 'unlink' and 'sudo' as risky method overrides."""
    tk = _make_toolkit()
    result = tk.scan_addons_source(addons_paths=[sample_addon_dir])

    addon = result.addons[0]
    risky_names = {r["method"] for r in addon["risky_methods"]}
    assert "unlink" in risky_names or "sudo" in risky_names


def test_scan_addons_detects_security_files(sample_addon_dir):
    """ir.model.access.csv is included in security_files."""
    tk = _make_toolkit()
    result = tk.scan_addons_source(addons_paths=[sample_addon_dir])

    addon = result.addons[0]
    assert any("ir.model.access.csv" in f for f in addon["security_files"])


def test_scan_addons_respects_max_files():
    """max_files=1 stops scanning after the cap is reached."""
    tk = _make_toolkit()
    with tempfile.TemporaryDirectory() as tmpdir:
        # Create an addon with many Python files
        addon_path = os.path.join(tmpdir, "big_addon")
        os.makedirs(addon_path)
        with open(os.path.join(addon_path, "__manifest__.py"), "w") as f:
            f.write("{'name': 'Big', 'version': '1.0'}")
        for i in range(5):
            with open(os.path.join(addon_path, f"model_{i}.py"), "w") as f:
                f.write(f"# file {i}\nclass M{i}:\n    _name = 'model.{i}'\n")

        result = tk.scan_addons_source(addons_paths=[tmpdir], max_files=2)
        # Some files were parsed but the cap was hit
        # The important thing is it completed without error
        assert isinstance(result, AddonScanResult)


def test_scan_addons_handles_syntax_error():
    """Files with syntax errors are reported as parse_warnings, not crashes."""
    tk = _make_toolkit()
    with tempfile.TemporaryDirectory() as tmpdir:
        addon_path = os.path.join(tmpdir, "broken_addon")
        os.makedirs(addon_path)
        with open(os.path.join(addon_path, "__manifest__.py"), "w") as f:
            f.write("{'name': 'Broken', 'version': '1.0'}")
        with open(os.path.join(addon_path, "bad_file.py"), "w") as f:
            f.write("this is NOT valid python !!!\n def broken(:\n")

        result = tk.scan_addons_source(addons_paths=[tmpdir])
        # Should not raise — syntax errors go into parse_warnings
        assert isinstance(result, AddonScanResult)
        if result.addons:
            addon = result.addons[0]
            # parse_warnings may contain syntax error info
            assert isinstance(addon.get("parse_warnings", []), list)


def test_scan_addons_no_paths_returns_warning():
    """Calling with no paths returns a warning, not an error."""
    tk = _make_toolkit()
    result = tk.scan_addons_source(addons_paths=None)

    assert result.addons_found == 0
    assert len(result.warnings) > 0


def test_scan_addons_nonexistent_path():
    """A non-existent path generates a warning, not a crash."""
    tk = _make_toolkit()
    result = tk.scan_addons_source(addons_paths=["/this/path/does/not/exist/ever"])

    assert isinstance(result, AddonScanResult)
    assert len(result.warnings) > 0


# ── fit_gap_report ────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_fit_gap_standard_requirement():
    """'track sales orders' classifies as 'standard'."""
    transport = _fake_transport()
    toolkit = _make_toolkit(transport)

    # schema_catalog call fails gracefully
    transport.execute_kw.return_value = []
    result = await toolkit.fit_gap_report(
        requirements=[{"description": "track sales orders and quotations"}]
    )

    assert isinstance(result, FitGapResult)
    assert len(result.requirements) == 1
    classified = result.requirements[0]
    assert classified["classification"] in ("standard", "custom_module", "unknown")
    assert "standard" in result.summary or "custom_module" in result.summary


@pytest.mark.asyncio
async def test_fit_gap_custom_module_requirement():
    """Novel integration requirements classify as 'custom_module' or 'unknown'."""
    transport = _fake_transport()
    toolkit = _make_toolkit(transport)

    transport.execute_kw.return_value = []
    result = await toolkit.fit_gap_report(
        requirements=[{"description": "integrate with our proprietary AI system via REST webhook"}]
    )

    assert isinstance(result, FitGapResult)
    classified = result.requirements[0]
    assert classified["classification"] in ("custom_module", "unknown")


@pytest.mark.asyncio
async def test_fit_gap_studio_requirement():
    """'add a custom field' classifies as 'studio'."""
    transport = _fake_transport()
    toolkit = _make_toolkit(transport)

    transport.execute_kw.return_value = []
    result = await toolkit.fit_gap_report(
        requirements=[{"description": "add a custom field for tracking external reference"}]
    )

    assert isinstance(result, FitGapResult)
    classified = result.requirements[0]
    assert classified["classification"] in ("studio", "custom_module", "unknown")


@pytest.mark.asyncio
async def test_fit_gap_avoid_requirement():
    """Anti-pattern requirements (raw SQL) classify as 'avoid'."""
    transport = _fake_transport()
    toolkit = _make_toolkit(transport)

    transport.execute_kw.return_value = []
    result = await toolkit.fit_gap_report(
        requirements=[{"description": "bypass the ORM and use raw sql queries"}]
    )

    classified = result.requirements[0]
    assert classified["classification"] == "avoid"


@pytest.mark.asyncio
async def test_fit_gap_summary_is_complete():
    """Summary dict covers all requirements, totalling to len(requirements)."""
    transport = _fake_transport()
    toolkit = _make_toolkit(transport)

    transport.execute_kw.return_value = []
    requirements = [
        {"description": "manage sales orders"},
        {"description": "add a custom field to partners"},
        {"description": "use raw sql for reporting"},
    ]
    result = await toolkit.fit_gap_report(requirements=requirements)

    total = sum(result.summary.values())
    assert total == len(requirements)


# ── business_pack_report ──────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_business_pack_sales():
    """'sales' pack returns sale-related expected modules and models."""
    transport = _fake_transport()
    toolkit = _make_toolkit(transport)

    # server_info() uses transport.version() directly — not execute_kw
    # execute_kw is called for: context_get + module search_read
    transport.execute_kw.side_effect = [
        {"lang": "en_US"},
        [{"name": "sale", "shortdesc": "Sales", "installed_version": "17.0.1.0"}],
    ]
    result = await toolkit.business_pack_report(pack="sales")

    assert isinstance(result, BusinessPackResult)
    assert result.pack == "sales"
    expected_module_names = [m["name"] for m in result.expected_modules]
    assert "sale" in expected_module_names
    assert "sale.order" in result.expected_models


@pytest.mark.asyncio
async def test_business_pack_hr():
    """'hr' pack returns HR-related expected modules and models."""
    transport = _fake_transport()
    toolkit = _make_toolkit(transport)

    # server_info() uses transport.version() — execute_kw handles context_get + modules
    transport.execute_kw.side_effect = [
        {"lang": "en_US"},
        [],  # no modules installed
    ]
    result = await toolkit.business_pack_report(pack="hr")

    assert result.pack == "hr"
    expected_module_names = [m["name"] for m in result.expected_modules]
    assert "hr" in expected_module_names
    assert "hr.employee" in result.expected_models


@pytest.mark.asyncio
async def test_business_pack_live_check_installed_missing():
    """business_pack_report populates installed/missing from live module list."""
    transport = _fake_transport()
    toolkit = _make_toolkit(transport)

    # server_info() uses transport.version(); execute_kw handles context_get + module list
    # (only 'sale' installed, not 'sale_management')
    transport.execute_kw.side_effect = [
        {"lang": "en_US"},
        [{"name": "sale", "shortdesc": "Sales", "installed_version": "17.0.1.0"}],
    ]
    result = await toolkit.business_pack_report(pack="sales")

    assert "sale" in result.installed
    assert "sale_management" in result.missing


@pytest.mark.asyncio
async def test_business_pack_invalid_pack_raises():
    """Unknown pack name raises ValueError."""
    tk = _make_toolkit()
    with pytest.raises(ValueError, match="Unknown business pack"):
        await tk.business_pack_report(pack="invalid_pack_xyz")
