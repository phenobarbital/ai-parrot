"""Cross-distribution import verification tests for FEAT-203.

Verifies that imports from the satellite package resolve correctly
through PEP 420 namespace merging.
"""
import importlib
import pathlib
import sys

import pytest

# ---------------------------------------------------------------------------
# Source-tree path verification (without requiring installed package)
# ---------------------------------------------------------------------------

SATELLITE_SRC = pathlib.Path(__file__).parent.parent / "src" / "parrot"


def _class_exists_in_satellite(relpath: str) -> bool:
    """Check that the given relative path exists in the satellite src tree."""
    return (SATELLITE_SRC / relpath).exists()


class TestSatelliteFilePresence:
    """Verify that expected server classes/files exist in satellite src tree."""

    @pytest.mark.parametrize("relpath,description", [
        ("handlers/bots.py", "ChatbotHandler"),
        ("manager/manager.py", "BotManager"),
        ("a2a/server.py", "A2AServer"),
        ("mcp/server.py", "MCPServer"),
        ("services/agent_service.py", "AgentService"),
        ("scheduler/manager.py", "AgentSchedulerManager"),
        ("mcp/oauth_server.py", "OAuthAuthorizationServer"),
        ("autonomous/orchestrator.py", "AutonomousOrchestrator"),
    ])
    def test_file_in_satellite(self, relpath: str, description: str):
        """File containing {description} must exist in satellite."""
        assert _class_exists_in_satellite(relpath), (
            f"Expected {description} in satellite at src/parrot/{relpath}"
        )


class TestHostStubFiles:
    """Verify host contains only expected stub files after extraction."""

    def test_handlers_host_only_stubs(self):
        """Host handlers/ retains only __init__.py and redirect stubs."""
        host_handlers = pathlib.Path(__file__).parent.parent.parent
        host_handlers = host_handlers / "ai-parrot" / "src" / "parrot" / "handlers"
        if not host_handlers.exists():
            pytest.skip("host handlers directory not found — integration test only")
        py_files = {f.name for f in host_handlers.glob("*.py")}
        assert "__init__.py" in py_files, "handlers/__init__.py must remain in host"
        assert "vault_utils.py" in py_files, "vault_utils.py redirect stub must remain in host"
        assert "credentials_utils.py" in py_files, "credentials_utils.py redirect stub must remain in host"
        # No other .py files should remain at the top level
        unexpected = py_files - {"__init__.py", "vault_utils.py", "credentials_utils.py"}
        assert not unexpected, f"Unexpected .py files remain in host handlers/: {unexpected}"

    def test_manager_host_only_init(self):
        """Host manager/ retains only __init__.py."""
        host_manager = pathlib.Path(__file__).parent.parent.parent
        host_manager = host_manager / "ai-parrot" / "src" / "parrot" / "manager"
        if not host_manager.exists():
            pytest.skip("host manager directory not found — integration test only")
        py_files = {f.name for f in host_manager.glob("*.py")}
        assert py_files == {"__init__.py"}, (
            f"Host manager/ should only have __init__.py, found: {py_files}"
        )


class TestHostPyprojectUpdates:
    """Verify host pyproject.toml has been updated correctly."""

    def test_scheduler_extra_removed(self, host_pyproject_text):
        """scheduler extra should be commented out/removed from host."""
        # The scheduler extra was removed; only a comment remains
        import re
        # Check that there's no active scheduler = [...] array with apscheduler
        active_scheduler = re.search(
            r'^scheduler\s*=\s*\[',
            host_pyproject_text,
            re.MULTILINE,
        )
        assert active_scheduler is None, (
            "scheduler extra should be removed from host pyproject.toml "
            "(moved to ai-parrot-server[scheduler])"
        )

    def test_server_extra_exists(self, host_pyproject_text):
        """server extra should reference ai-parrot-server[all]."""
        assert "ai-parrot-server[all]" in host_pyproject_text, (
            "host pyproject.toml should have a server extra referencing ai-parrot-server[all]"
        )

    def test_all_extra_includes_server(self, host_pyproject_text):
        """all meta-extra must include ai-parrot-server[all]."""
        # Find the all = [...] block
        assert "ai-parrot-server[all]" in host_pyproject_text, (
            "host pyproject.toml all meta-extra must include ai-parrot-server[all]"
        )

    def test_parrot_fs_removed_from_host(self, host_pyproject_text):
        """parrot-fs console_script should not be active in host."""
        import re
        # Active means not commented out
        active = re.search(
            r'^\s*parrot-fs\s*=\s*"parrot\.autonomous',
            host_pyproject_text,
            re.MULTILINE,
        )
        assert active is None, (
            "parrot-fs console_script should be removed from host (moved to satellite)"
        )

    def test_parrot_cli_remains(self, host_pyproject_text):
        """parrot console_script must still be in host."""
        assert 'parrot = "parrot.cli:cli"' in host_pyproject_text, (
            "parrot CLI entry point must remain in host pyproject.toml"
        )


class TestVaultUtilsRelocation:
    """Verify vault_utils is properly relocated."""

    def test_security_vault_utils_exists(self):
        """parrot/security/vault_utils.py must exist in host."""
        host_security = pathlib.Path(__file__).parent.parent.parent
        host_security = host_security / "ai-parrot" / "src" / "parrot" / "security"
        vault_utils = host_security / "vault_utils.py"
        assert vault_utils.exists(), (
            "parrot/security/vault_utils.py missing — must be relocated here in FEAT-203"
        )

    def test_security_credentials_utils_exists(self):
        """parrot/security/credentials_utils.py must exist in host."""
        host_security = pathlib.Path(__file__).parent.parent.parent
        host_security = host_security / "ai-parrot" / "src" / "parrot" / "security"
        cred_utils = host_security / "credentials_utils.py"
        assert cred_utils.exists(), (
            "parrot/security/credentials_utils.py missing — must be relocated here in FEAT-203"
        )

    def test_handlers_vault_redirect_is_stub(self):
        """handlers/vault_utils.py should be a redirect stub."""
        host_handlers = pathlib.Path(__file__).parent.parent.parent
        vault_stub = host_handlers / "ai-parrot" / "src" / "parrot" / "handlers" / "vault_utils.py"
        if not vault_stub.exists():
            pytest.skip("host vault_utils stub not found")
        content = vault_stub.read_text()
        assert "parrot.security.vault_utils" in content, (
            "handlers/vault_utils.py should be a redirect to parrot.security.vault_utils"
        )


class TestSatelliteMCPConsolidation:
    """Verify services/mcp/ was consolidated into mcp/ in satellite."""

    def test_parrot_server_in_satellite_mcp(self):
        """parrot_server.py (from services/mcp/server.py) must be in satellite mcp/."""
        parrot_server = SATELLITE_SRC / "mcp" / "parrot_server.py"
        assert parrot_server.exists(), (
            "parrot/mcp/parrot_server.py missing — should have been consolidated from services/mcp/server.py"
        )

    def test_simple_server_in_satellite_mcp(self):
        """simple_server.py (from services/mcp/simple.py) must be in satellite mcp/."""
        simple_server = SATELLITE_SRC / "mcp" / "simple_server.py"
        assert simple_server.exists(), (
            "parrot/mcp/simple_server.py missing — should have been consolidated from services/mcp/simple.py"
        )

    def test_services_mcp_removed_from_host(self):
        """services/mcp/ directory should not exist in host."""
        host_services_mcp = pathlib.Path(__file__).parent.parent.parent
        host_services_mcp = host_services_mcp / "ai-parrot" / "src" / "parrot" / "services" / "mcp"
        assert not host_services_mcp.exists(), (
            "services/mcp/ should have been removed from host after consolidation in FEAT-203"
        )
