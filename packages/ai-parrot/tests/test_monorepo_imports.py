"""Tests for monorepo import proxy resolution and backward compatibility.

Validates import paths work correctly in both the pre-migration flat layout
and the post-migration monorepo layout. Tests that require the monorepo
layout use try/except with pytest.skip for graceful degradation.
"""

import importlib
import pytest

# ---------------------------------------------------------------------------
# Core package imports (must work in any layout)
# ---------------------------------------------------------------------------


class TestCoreImports:
    """Verify core parrot imports work without sub-packages."""

    def test_import_parrot(self):
        import parrot

        assert hasattr(parrot, "__version__")

    def test_import_bots(self):
        from parrot.bots import Chatbot, Agent

        assert Chatbot is not None
        assert Agent is not None

    def test_import_abstract_loader(self):
        from parrot.loaders.abstract import AbstractLoader

        assert AbstractLoader is not None

    def test_import_document(self):
        from parrot.loaders import Document

        assert Document is not None

    def test_import_tools_base(self):
        from parrot.tools import AbstractTool, AbstractToolkit

        assert AbstractTool is not None
        assert AbstractToolkit is not None


# ---------------------------------------------------------------------------
# Direct submodule imports (work in both layouts)
# ---------------------------------------------------------------------------


class TestDirectSubmoduleImports:
    """Verify direct submodule imports always work."""

    def test_tools_pythonrepl(self):
        from parrot.tools.pythonrepl import PythonREPLTool

        assert PythonREPLTool is not None

    def test_tools_agent(self):
        from parrot.tools.agent import AgentTool

        assert AgentTool is not None

    def test_tools_openapi(self):
        from parrot.tools.openapitoolkit import OpenAPIToolkit

        assert OpenAPIToolkit is not None

    def test_loaders_abstract(self):
        from parrot.loaders.abstract import AbstractLoader

        assert AbstractLoader is not None


# ---------------------------------------------------------------------------
# Monorepo-specific: parrot_tools package
# ---------------------------------------------------------------------------


class TestParrotToolsPackage:
    """Verify parrot_tools package when installed."""

    def test_parrot_tools_importable(self):
        try:
            import parrot_tools
        except ImportError:
            pytest.skip("parrot_tools not installed")
        assert hasattr(parrot_tools, "TOOL_REGISTRY")
        assert isinstance(parrot_tools.TOOL_REGISTRY, dict)
        assert len(parrot_tools.TOOL_REGISTRY) > 0

    def test_proxy_resolves_tool_submodule(self):
        """from parrot.tools.<external_tool> resolves via proxy."""
        try:
            from parrot_tools import TOOL_REGISTRY
        except ImportError:
            pytest.skip("parrot_tools not installed")
        # Pick a tool from registry and try to import via proxy
        if not TOOL_REGISTRY:
            pytest.skip("TOOL_REGISTRY is empty")
        key = next(iter(TOOL_REGISTRY))
        dotted = TOOL_REGISTRY[key]
        module_path, class_name = dotted.rsplit(".", 1)
        try:
            mod = importlib.import_module(module_path)
            assert hasattr(mod, class_name)
        except ImportError:
            pytest.skip(f"Optional dependency for {key} not installed")


# ---------------------------------------------------------------------------
# Monorepo-specific: parrot_loaders package
# ---------------------------------------------------------------------------


class TestParrotLoadersPackage:
    """Verify parrot_loaders package when installed."""

    def test_parrot_loaders_importable(self):
        try:
            import parrot_loaders
        except ImportError:
            pytest.skip("parrot_loaders not installed")
        assert hasattr(parrot_loaders, "LOADER_REGISTRY")
        assert isinstance(parrot_loaders.LOADER_REGISTRY, dict)
        assert len(parrot_loaders.LOADER_REGISTRY) > 0

    def test_proxy_resolves_loader_submodule(self):
        """from parrot.loaders.<loader> resolves via proxy."""
        try:
            from parrot_loaders import LOADER_REGISTRY
        except ImportError:
            pytest.skip("parrot_loaders not installed")
        if not LOADER_REGISTRY:
            pytest.skip("LOADER_REGISTRY is empty")
        # Try a simple loader (txt is always available)
        if "TextLoader" in LOADER_REGISTRY:
            dotted = LOADER_REGISTRY["TextLoader"]
            module_path, class_name = dotted.rsplit(".", 1)
            mod = importlib.import_module(module_path)
            assert hasattr(mod, class_name)


# ---------------------------------------------------------------------------
# Discovery system
# ---------------------------------------------------------------------------


class TestDiscovery:
    """Verify tool discovery works."""

    def test_discover_from_registry(self):
        try:
            from parrot.tools.discovery import discover_from_registry
        except (ImportError, ModuleNotFoundError):
            pytest.skip("discovery module not available (pre-monorepo layout)")
        registry = discover_from_registry()
        assert isinstance(registry, dict)

    def test_discover_all(self):
        try:
            from parrot.tools.discovery import discover_all
        except (ImportError, ModuleNotFoundError):
            pytest.skip("discovery module not available (pre-monorepo layout)")
        result = discover_all()
        assert isinstance(result, dict)


# ---------------------------------------------------------------------------
# Monorepo-specific: parrot_pipelines package
# ---------------------------------------------------------------------------


class TestParrotPipelinesPackage:
    """Verify parrot_pipelines package when installed."""

    def test_parrot_pipelines_importable(self):
        try:
            import parrot_pipelines
        except ImportError:
            pytest.skip("parrot_pipelines not installed")
        assert hasattr(parrot_pipelines, "PIPELINE_REGISTRY")
        assert isinstance(parrot_pipelines.PIPELINE_REGISTRY, dict)
        assert len(parrot_pipelines.PIPELINE_REGISTRY) > 0

    def test_proxy_resolves_pipeline_module(self):
        try:
            from parrot.pipelines.models import PlanogramConfig
            from parrot.pipelines.planogram.plan import PlanogramCompliance
        except ImportError:
            pytest.skip("parrot_pipelines not installed")
        assert PlanogramConfig is not None
        assert PlanogramCompliance is not None


# ---------------------------------------------------------------------------
# FEAT-612: removed legacy planogram pipeline / detector APIs
# ---------------------------------------------------------------------------

_REMOVED_PIPELINE_NAMES = ("PlanogramCompliancePipeline", "RetailDetector")


class TestPlanogramLegacyRemoval:
    """Surviving planogram exports resolve; removed legacy names and proxy modules do not (AC14)."""

    @pytest.fixture(autouse=True)
    def _require_pipelines(self):
        try:
            import parrot_pipelines  # noqa: F401
        except ImportError:
            pytest.skip("parrot_pipelines not installed")

    def test_surviving_package_exports_resolve(self):
        from parrot_pipelines.planogram import AbstractPlanogramType, InkWall, PlanogramCompliance

        assert AbstractPlanogramType is not None
        assert InkWall is not None
        assert PlanogramCompliance.__name__ == "PlanogramCompliance"

    def test_surviving_core_proxy_exports_resolve(self):
        import parrot_pipelines.planogram as pkg
        from parrot.pipelines.planogram import AbstractPlanogramType, PlanogramCompliance

        assert PlanogramCompliance is pkg.PlanogramCompliance
        assert AbstractPlanogramType is pkg.AbstractPlanogramType

    @pytest.mark.parametrize("name", _REMOVED_PIPELINE_NAMES)
    def test_removed_names_not_importable_from_package(self, name):
        import parrot_pipelines.planogram as planogram

        assert name not in planogram.__all__
        with pytest.raises(AttributeError):
            getattr(planogram, name)

    @pytest.mark.parametrize("name", _REMOVED_PIPELINE_NAMES)
    def test_removed_names_not_importable_from_core_proxy(self, name):
        import parrot.pipelines.planogram as proxy

        assert name not in proxy.__all__
        with pytest.raises(ImportError):
            exec(f"from parrot.pipelines.planogram import {name}", {})

    @pytest.mark.parametrize(
        "module",
        [
            "parrot_pipelines.planogram.legacy",
            "parrot_pipelines.detector",
            "parrot.pipelines.planogram.legacy",
            "parrot.pipelines.detector",
        ],
    )
    def test_removed_modules_raise_import_error(self, module):
        with pytest.raises(ImportError):
            importlib.import_module(module)

    def test_registry_has_no_removed_entries(self):
        from parrot_pipelines import PIPELINE_REGISTRY

        for name in ("AbstractDetector", "PlanogramCompliancePipeline", "RetailDetector"):
            assert name not in PIPELINE_REGISTRY
        for path in PIPELINE_REGISTRY.values():
            module = path.rsplit(".", 1)[0]
            assert ".legacy" not in module
            assert module != "parrot_pipelines.detector"

    def test_pipelines_source_has_no_heavy_legacy_imports(self):
        """Static guard: no pipelines module imports pytesseract / torch / ultralytics at any indentation."""
        import re
        from pathlib import Path

        import parrot_pipelines

        pattern = re.compile(r"^\s*(import|from)\s+(pytesseract|torch|ultralytics)\b")
        root = Path(parrot_pipelines.__file__).parent
        offenders = []
        for py in root.rglob("*.py"):
            for lineno, line in enumerate(py.read_text(encoding="utf-8").splitlines(), 1):
                if pattern.match(line):
                    offenders.append(f"{py}:{lineno}")
        assert not offenders, offenders
