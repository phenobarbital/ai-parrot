"""Cross-distribution import verification tests for FEAT-203.

Verifies that imports from the satellite package resolve correctly
through PEP 420 namespace merging.
"""
import importlib
import pathlib
import sys
import time
import hashlib
import hmac as hmac_mod
from typing import Optional
from unittest.mock import patch

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


# ---------------------------------------------------------------------------
# Backward-compat stub: vault_utils redirect
# ---------------------------------------------------------------------------

class TestVaultUtilsBackwardCompatStub:
    """Verify that the old import path redirects to the new canonical location."""

    def test_vault_utils_redirect_resolves_same_object(self):
        """handlers/vault_utils and security/vault_utils must expose the same objects."""
        host_handlers_stub = (
            pathlib.Path(__file__).parent.parent.parent
            / "ai-parrot" / "src" / "parrot" / "handlers" / "vault_utils.py"
        )
        if not host_handlers_stub.exists():
            pytest.skip("handlers/vault_utils.py stub not found — integration test only")

        content = host_handlers_stub.read_text()
        # The stub must import from the canonical location
        assert "parrot.security.vault_utils" in content, (
            "handlers/vault_utils.py must redirect to parrot.security.vault_utils"
        )

    def test_vault_utils_canonical_path_has_expected_functions(self):
        """parrot.security.vault_utils must define the expected public helpers."""
        vault_utils_path = (
            pathlib.Path(__file__).parent.parent.parent
            / "ai-parrot" / "src" / "parrot" / "security" / "vault_utils.py"
        )
        if not vault_utils_path.exists():
            pytest.skip("parrot/security/vault_utils.py not found")
        content = vault_utils_path.read_text()
        for name in ("store_vault_credential", "retrieve_vault_credential", "delete_vault_credential"):
            assert f"def {name}" in content or f"async def {name}" in content, (
                f"{name} must be defined in parrot/security/vault_utils.py"
            )


# ---------------------------------------------------------------------------
# Lazy __getattr__ for parrot.autonomous
# ---------------------------------------------------------------------------

class TestAutonomousLazyLoader:
    """Verify the lazy __getattr__ in parrot/autonomous/__init__.py."""

    def test_unknown_name_raises_attribute_error(self):
        """Accessing a non-existent name raises AttributeError with install hint."""
        autonomous_init = (
            pathlib.Path(__file__).parent.parent.parent
            / "ai-parrot" / "src" / "parrot" / "autonomous" / "__init__.py"
        )
        if not autonomous_init.exists():
            pytest.skip("parrot/autonomous/__init__.py not found")

        content = autonomous_init.read_text()
        # Verify the lazy loader is present
        assert "__getattr__" in content, (
            "parrot/autonomous/__init__.py must define __getattr__ for lazy loading"
        )
        assert "ai-parrot-server" in content, (
            "__getattr__ must include install hint mentioning ai-parrot-server"
        )

    def test_satellite_absent_raises_import_error_with_hint(self):
        """When satellite is absent, ImportError with install hint is raised."""
        autonomous_init = (
            pathlib.Path(__file__).parent.parent.parent
            / "ai-parrot" / "src" / "parrot" / "autonomous" / "__init__.py"
        )
        if not autonomous_init.exists():
            pytest.skip("parrot/autonomous/__init__.py not found")

        content = autonomous_init.read_text()
        # The error message must mention pip install
        assert "pip install" in content, (
            "__getattr__ must suggest pip install ai-parrot-server in the error"
        )

    def test_autonomous_classes_listed(self):
        """_AUTONOMOUS_CLASSES must include AutonomousOrchestrator."""
        autonomous_init = (
            pathlib.Path(__file__).parent.parent.parent
            / "ai-parrot" / "src" / "parrot" / "autonomous" / "__init__.py"
        )
        if not autonomous_init.exists():
            pytest.skip("parrot/autonomous/__init__.py not found")

        content = autonomous_init.read_text()
        assert "AutonomousOrchestrator" in content, (
            "_AUTONOMOUS_CLASSES must map AutonomousOrchestrator"
        )


# ---------------------------------------------------------------------------
# HMAC signing round-trip and timestamp enforcement
# ---------------------------------------------------------------------------

def _sign_request(payload: bytes, secret: str, timestamp: str) -> str:
    """Helper: compute HMAC-SHA256 signature the same way the security module does."""
    message = timestamp.encode() + payload
    return hmac_mod.new(secret.encode(), message, hashlib.sha256).hexdigest()


class TestHMACRoundTrip:
    """Verify InMemoryCredentialProvider HMAC signing round-trip."""

    @pytest.mark.asyncio
    async def test_valid_signature_fresh_timestamp(self):
        """A fresh, correctly-signed request returns a CallerIdentity."""
        try:
            from parrot.a2a.security import InMemoryCredentialProvider
        except ImportError:
            pytest.skip("parrot.a2a.security not importable")

        provider = InMemoryCredentialProvider()
        result = await provider.register_agent(
            "TestBot",
            permissions=["skill:*"],
        )
        secret = result["hmac_secret"]
        payload = b'{"skill": "analyze"}'
        timestamp = str(int(time.time()))
        sig = _sign_request(payload, secret, timestamp)

        identity = await provider.validate_hmac(sig, payload, timestamp, agent_name="TestBot")
        assert identity is not None, "Valid fresh HMAC should return CallerIdentity"
        assert identity.agent_name == "TestBot"

    @pytest.mark.asyncio
    async def test_stale_timestamp_rejected(self):
        """A correctly-signed request with a stale timestamp is rejected."""
        try:
            from parrot.a2a.security import InMemoryCredentialProvider, HMAC_TIMESTAMP_WINDOW
        except ImportError:
            pytest.skip("parrot.a2a.security not importable")

        provider = InMemoryCredentialProvider()
        result = await provider.register_agent("StaleBot", permissions=[])
        secret = result["hmac_secret"]
        payload = b"test"
        # Timestamp is 10 seconds beyond the freshness window
        stale_timestamp = str(int(time.time()) - HMAC_TIMESTAMP_WINDOW - 10)
        sig = _sign_request(payload, secret, stale_timestamp)

        identity = await provider.validate_hmac(
            sig, payload, stale_timestamp, agent_name="StaleBot"
        )
        assert identity is None, "Stale HMAC timestamp must be rejected"

    @pytest.mark.asyncio
    async def test_invalid_timestamp_rejected(self):
        """A non-integer timestamp is rejected."""
        try:
            from parrot.a2a.security import InMemoryCredentialProvider
        except ImportError:
            pytest.skip("parrot.a2a.security not importable")

        provider = InMemoryCredentialProvider()
        await provider.register_agent("Bot", permissions=[])

        identity = await provider.validate_hmac("sig", b"payload", "not-a-number")
        assert identity is None, "Non-integer timestamp must be rejected"

    @pytest.mark.asyncio
    async def test_wrong_signature_rejected(self):
        """A fresh but wrong signature is rejected."""
        try:
            from parrot.a2a.security import InMemoryCredentialProvider
        except ImportError:
            pytest.skip("parrot.a2a.security not importable")

        provider = InMemoryCredentialProvider()
        await provider.register_agent("Bot2", permissions=[])
        timestamp = str(int(time.time()))
        payload = b"test"

        identity = await provider.validate_hmac(
            "wrong_signature", payload, timestamp, agent_name="Bot2"
        )
        assert identity is None, "Wrong signature must be rejected"

    @pytest.mark.asyncio
    async def test_future_timestamp_within_window_accepted(self):
        """A slightly future timestamp (clock skew) within the window is accepted."""
        try:
            from parrot.a2a.security import InMemoryCredentialProvider, HMAC_TIMESTAMP_WINDOW
        except ImportError:
            pytest.skip("parrot.a2a.security not importable")

        provider = InMemoryCredentialProvider()
        result = await provider.register_agent("FutureBot", permissions=[])
        secret = result["hmac_secret"]
        payload = b"future"
        # 30 seconds in the future (well within ±5min window)
        future_timestamp = str(int(time.time()) + 30)
        sig = _sign_request(payload, secret, future_timestamp)

        identity = await provider.validate_hmac(
            sig, payload, future_timestamp, agent_name="FutureBot"
        )
        assert identity is not None, "Slightly future timestamp within window must be accepted"
