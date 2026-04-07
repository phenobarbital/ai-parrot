"""Import Integrity Validation Test Suite.

Ensures that all tools in TOOL_REGISTRY are importable and that no stale
cross-package imports exist. These tests prevent regressions during monorepo
maintenance and tool additions.

Test categories:
1. test_import_all_registered_tools — verify every tool in TOOL_REGISTRY can be imported
2. test_bridge_reexports — verify bridge files correctly re-export core classes
3. test_no_stale_cross_package_imports — grep-based check for broken imports
"""

import importlib
import subprocess
import sys
from pathlib import Path

import pytest


class TestToolRegistryImports:
    """Verify every tool in TOOL_REGISTRY is importable without errors."""

    def test_import_all_registered_tools(self):
        """Import each tool in TOOL_REGISTRY and verify no ImportError."""
        from parrot_tools import TOOL_REGISTRY

        failures = []
        for name, dotted_path in TOOL_REGISTRY.items():
            # TOOL_REGISTRY maps tool names to dotted paths like "parrot_tools.jiratoolkit.JiraToolkit"
            # We need to import the module (not the class), so extract the module path
            module_path = dotted_path.rsplit(".", 1)[0] if "." in dotted_path else dotted_path
            try:
                importlib.import_module(module_path)
            except ImportError as e:
                failures.append(f"{name} ({module_path}): {e}")
            except Exception as e:
                # Some tools may have other initialization issues, but we're testing imports
                failures.append(f"{name} ({module_path}): {type(e).__name__}: {e}")

        assert not failures, (
            f"{len(failures)} tool(s) failed to import:\n"
            + "\n".join(failures)
        )


class TestBridgeReexports:
    """Verify bridge files in parrot_tools correctly re-export core symbols."""

    @pytest.mark.parametrize("symbol", [
        "AbstractTool",
        "ToolResult",
        "AbstractToolArgsSchema",
    ])
    def test_abstract_bridge(self, symbol):
        """Verify parrot_tools.abstract re-exports core AbstractTool classes."""
        import parrot_tools.abstract as bridge
        import parrot.tools.abstract as core

        assert hasattr(bridge, symbol), (
            f"parrot_tools.abstract missing {symbol} — bridge file may be incomplete"
        )
        assert getattr(bridge, symbol) is getattr(core, symbol), (
            f"parrot_tools.abstract.{symbol} does not match parrot.tools.abstract.{symbol}"
        )

    @pytest.mark.parametrize("symbol", ["AbstractToolkit", "ToolkitTool"])
    def test_toolkit_bridge(self, symbol):
        """Verify parrot_tools.toolkit re-exports core toolkit classes."""
        import parrot_tools.toolkit as bridge
        import parrot.tools.toolkit as core

        assert hasattr(bridge, symbol), (
            f"parrot_tools.toolkit missing {symbol} — bridge file may be incomplete"
        )
        assert getattr(bridge, symbol) is getattr(core, symbol), (
            f"parrot_tools.toolkit.{symbol} does not match parrot.tools.toolkit.{symbol}"
        )

    @pytest.mark.parametrize("symbol", ["tool_schema", "tool", "requires_permission"])
    def test_decorators_bridge(self, symbol):
        """Verify parrot_tools.decorators re-exports core decorators."""
        import parrot_tools.decorators as bridge
        import parrot.tools.decorators as core

        assert hasattr(bridge, symbol), (
            f"parrot_tools.decorators missing {symbol} — bridge file may be incomplete"
        )
        assert getattr(bridge, symbol) is getattr(core, symbol), (
            f"parrot_tools.decorators.{symbol} does not match parrot.tools.decorators.{symbol}"
        )


class TestNoStaleCrossPackageImports:
    """Grep-based test: no parrot.tools.<X> imports for modules only in parrot_tools.

    After monorepo migration, tool modules that exist ONLY in parrot_tools
    must not be imported via parrot.tools.*. This test prevents regressions.

    To update PARROT_TOOLS_ONLY list:
    1. Check the current directory structure: ls -1 packages/ai-parrot-tools/src/parrot_tools/
    2. Compare with packages/ai-parrot/src/parrot/tools/
    3. Any directory/module NOT in parrot.tools should be in this list
    """

    # Modules that exist ONLY in parrot_tools (not in parrot.tools core)
    # Keep this sorted and updated when new tools are added to parrot_tools
    PARROT_TOOLS_ONLY = [
        "calculator",
        "chart",
        "codeinterpreter",
        "company_info",
        "databasequery",
        "docker",
        "epson",
        "file",
        "flowtask",
        "google",
        "ibisworld",
        "ibkr",
        "massive",
        "messaging",
        "navigator",
        "o365",
        "pricestool",
        "pulumi",
        "quant",
        "querytoolkit",
        "retail",
        "sassie",
        "scraping",
        "security",
        "shell_tool",
        "sitesearch",
        "cloudsploit",
        "system_health",
        "troc",
        "workday",
    ]

    def test_no_stale_imports_in_runtime_code(self):
        """Ensure no .py files import from parrot.tools.<module> for
        modules that only exist in parrot_tools.

        This grep-based test catches edge cases that might be missed by manual
        audits, especially as the codebase grows.
        """
        parrot_tools_dir = Path(__file__).resolve().parent.parent / "src" / "parrot_tools"

        # Build regex pattern: from parrot\.tools\.(module1|module2|...)
        pattern = "|".join(rf"from parrot\.tools\.{m}" for m in self.PARROT_TOOLS_ONLY)

        result = subprocess.run(
            ["grep", "-rn", "-E", pattern, str(parrot_tools_dir),
             "--include=*.py"],
            capture_output=True, text=True,
        )

        # Filter out __pycache__ and false positives
        stale = [
            line for line in result.stdout.strip().split("\n")
            if line and "__pycache__" not in line and line.strip()
        ]

        assert not stale, (
            f"Found {len(stale)} stale cross-package import(s) in parrot_tools:\n"
            + "\n".join(stale)
            + "\n\nThese imports should use parrot_tools.* instead of parrot.tools.*"
        )
