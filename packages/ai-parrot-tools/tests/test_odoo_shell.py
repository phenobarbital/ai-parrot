"""Unit tests for OdooToolkit odoo-bin / odoo-cli shell functions (FEAT-240).

These tests verify:
- Correct argv construction for install/upgrade calls.
- Subcommand whitelist enforcement.
- HITL confirmation marking via confirming_tools.
- Graceful self-disable when ODOO_BIN is unset.
"""
from __future__ import annotations

import pytest

from parrot_tools.odoo import OdooToolkit
from parrot_tools.odoo.shell import (
    ALLOWED_SUBCOMMANDS,
    ShellResult,
    _build_install_argv,
    _validate_subcommand,
    _validate_token,
)


# ── Helpers ──────────────────────────────────────────────────────────────────


def _make_toolkit(**env) -> OdooToolkit:
    """Create a minimal OdooToolkit with test credentials."""
    return OdooToolkit(
        url="http://test.example.com",
        database="odoo",
        username="admin",
        password="admin",
    )


# ── argv construction ─────────────────────────────────────────────────────────


def test_install_argv_basic(monkeypatch):
    """install: builds -i flag and --stop-after-init, no shell=True."""
    monkeypatch.setenv("ODOO_BIN", "/opt/odoo/odoo-bin")
    monkeypatch.delenv("ODOO_CONF", raising=False)
    argv = _build_install_argv("/opt/odoo/odoo-bin", ["sale", "stock"], "mydb", upgrade=False)
    assert argv[0] == "/opt/odoo/odoo-bin"
    assert "-d" in argv
    assert "mydb" in argv
    assert "-i" in argv
    assert "sale,stock" in argv
    assert "--stop-after-init" in argv
    # Verify no shell metacharacters — the argv is a list, not a string
    assert isinstance(argv, list)
    # 'shell' as a keyword must NOT appear (we never use shell=True)
    assert "shell" not in argv[1:]  # first element is the binary path


def test_install_argv_upgrade(monkeypatch):
    """upgrade: builds -u flag instead of -i."""
    monkeypatch.delenv("ODOO_CONF", raising=False)
    argv = _build_install_argv("/opt/odoo/odoo-bin", ["sale"], "mydb", upgrade=True)
    assert "-u" in argv
    assert "-i" not in argv


def test_install_argv_with_conf(monkeypatch):
    """When ODOO_CONF is set the --conf flag appears in argv."""
    monkeypatch.setenv("ODOO_CONF", "/etc/odoo/odoo.conf")
    argv = _build_install_argv("/opt/odoo/odoo-bin", ["base"], "mydb", upgrade=False)
    assert "--conf" in argv
    assert "/etc/odoo/odoo.conf" in argv


def test_install_argv_empty_modules():
    """Empty module list raises ValueError."""
    with pytest.raises(ValueError, match="empty"):
        _build_install_argv("/bin/odoo-bin", [], "mydb", upgrade=False)


def test_install_argv_invalid_module_name():
    """Module names with shell metacharacters are rejected."""
    with pytest.raises(ValueError):
        _build_install_argv("/bin/odoo-bin", ["sale; rm -rf /"], "mydb", upgrade=False)


def test_install_argv_invalid_database():
    """Database names with shell metacharacters are rejected."""
    with pytest.raises(ValueError):
        _build_install_argv("/bin/odoo-bin", ["sale"], "db; rm -rf /", upgrade=False)


# ── Subcommand whitelist ──────────────────────────────────────────────────────


def test_subcommand_whitelist_accepts_valid():
    """All allowed subcommands pass validation without raising."""
    for cmd in ALLOWED_SUBCOMMANDS:
        _validate_subcommand(cmd)  # must not raise


def test_subcommand_whitelist_rejects_rm(monkeypatch):
    """Shell injection attempts are rejected."""
    monkeypatch.setenv("ODOO_BIN", "/opt/odoo/odoo-bin")
    with pytest.raises(ValueError):
        _validate_subcommand("rm -rf /")


def test_subcommand_whitelist_rejects_unknown():
    """An unrecognised subcommand is rejected."""
    with pytest.raises(ValueError, match="not whitelisted"):
        _validate_subcommand("uninstall")


# ── Token validation ──────────────────────────────────────────────────────────


def test_token_validation_accepts_valid():
    """Valid module / subcommand / database tokens pass."""
    for token in ["sale", "sale_order", "module.name", "OdooModule-v1"]:
        _validate_token(token)  # must not raise


def test_token_validation_rejects_spaces():
    """Tokens with spaces are rejected."""
    with pytest.raises(ValueError):
        _validate_token("sale order")


def test_token_validation_rejects_semicolons():
    """Tokens with semicolons (shell injection) are rejected."""
    with pytest.raises(ValueError):
        _validate_token("sale; rm -rf /")


# ── confirming_tools ──────────────────────────────────────────────────────────


def test_shell_tools_are_confirming():
    """All three shell tools appear in OdooToolkit.confirming_tools."""
    assert "odoo_shell_install_module" in OdooToolkit.confirming_tools
    assert "odoo_shell_upgrade_module" in OdooToolkit.confirming_tools
    assert "odoo_cli_command" in OdooToolkit.confirming_tools


def test_shell_tools_have_requires_confirmation_routing():
    """Built tools for shell methods carry requires_confirmation=True."""
    tk = _make_toolkit()
    tools_by_name = {t.name: t for t in tk.get_tools()}
    # Tool names have the "odoo_" prefix applied by the toolkit
    for tool_name in [
        "odoo_shell_install_module",
        "odoo_shell_upgrade_module",
        "odoo_cli_command",
    ]:
        assert tool_name in tools_by_name, f"Tool {tool_name!r} not found in get_tools()"
        tool = tools_by_name[tool_name]
        assert tool.routing_meta is not None, f"{tool_name}: routing_meta is None"
        assert tool.routing_meta.get("requires_confirmation") is True, (
            f"{tool_name}: requires_confirmation is not True"
        )


# ── Self-disable without ODOO_BIN ─────────────────────────────────────────────


def test_disabled_without_bin_init_does_not_crash(monkeypatch):
    """OdooToolkit init succeeds even when ODOO_BIN is unset."""
    monkeypatch.delenv("ODOO_BIN", raising=False)
    tk = _make_toolkit()
    assert tk is not None


@pytest.mark.asyncio
async def test_shell_install_disabled_without_bin(monkeypatch):
    """odoo_shell_install_module returns failure result when ODOO_BIN unset."""
    monkeypatch.delenv("ODOO_BIN", raising=False)
    # Also ensure odoo-bin is not on PATH by monkeypatching shutil.which
    import parrot_tools.odoo.shell as shell_module
    monkeypatch.setattr(shell_module, "_odoo_bin_path", lambda: None)

    tk = _make_toolkit()
    result = await tk.odoo_shell_install_module(modules=["sale"])
    assert isinstance(result, ShellResult)
    assert result.success is False
    assert "ODOO_BIN" in result.message or "disabled" in result.message.lower()


@pytest.mark.asyncio
async def test_shell_upgrade_disabled_without_bin(monkeypatch):
    """odoo_shell_upgrade_module returns failure result when ODOO_BIN unset."""
    import parrot_tools.odoo.shell as shell_module
    monkeypatch.setattr(shell_module, "_odoo_bin_path", lambda: None)

    tk = _make_toolkit()
    result = await tk.odoo_shell_upgrade_module(modules=["sale"])
    assert isinstance(result, ShellResult)
    assert result.success is False


@pytest.mark.asyncio
async def test_cli_command_disabled_without_bin(monkeypatch):
    """odoo_cli_command returns failure result when ODOO_BIN unset."""
    import parrot_tools.odoo.shell as shell_module
    monkeypatch.setattr(shell_module, "_odoo_bin_path", lambda: None)

    tk = _make_toolkit()
    result = await tk.odoo_cli_command(subcommand="scaffold")
    assert isinstance(result, ShellResult)
    assert result.success is False


# ── No breakage to RPC API ────────────────────────────────────────────────────


def test_rpc_tools_still_present():
    """Existing RPC tools are not removed by the shell extension."""
    tk = _make_toolkit()
    tool_names = {t.name for t in tk.get_tools()}
    for expected in ["odoo_search_records", "odoo_get_record", "odoo_fields_get"]:
        assert expected in tool_names, f"RPC tool {expected!r} is missing after shell extension"
