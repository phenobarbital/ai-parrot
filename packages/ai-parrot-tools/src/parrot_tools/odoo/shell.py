"""Shell execution helpers for OdooToolkit odoo-bin / odoo-cli tools.

Provides subprocess-based helpers to invoke the local ``odoo-bin`` or
``odoo-cli`` binaries (module install/upgrade, scaffold, generic CLI
passthrough).  All execution uses :func:`asyncio.create_subprocess_exec`
with an explicit argv list — **never** ``shell=True``.

Environment variables consumed:
- ``ODOO_BIN``  — absolute path to the ``odoo-bin`` executable.
- ``ODOO_CONF`` — path to the Odoo config file (passed via ``--conf``).
- ``ODOO_TEST_DATABASE`` — default database name when none is supplied.

When ``ODOO_BIN`` is unset or the path is not executable these helpers
return a :class:`ShellResult` with ``success=False`` and a clear message —
they never raise an unhandled exception / crash toolkit initialisation.
"""
from __future__ import annotations

import asyncio
import logging
import os
import re
import shutil
from typing import Optional

from pydantic import BaseModel, ConfigDict, Field

logger = logging.getLogger(__name__)

# ── Constants ────────────────────────────────────────────────────────────────

#: Default subprocess timeout in seconds.
DEFAULT_SHELL_TIMEOUT: int = 120

#: Token allowlist: module names, subcommands, database names.
#: Accepts alphanumerics, underscores, hyphens, and dots.
_TOKEN_RE = re.compile(r"^[a-zA-Z0-9_.-]+$")

#: Whitelisted odoo-cli / odoo-bin subcommands.
ALLOWED_SUBCOMMANDS: frozenset[str] = frozenset(
    {
        "scaffold",
        "populate",
        "db",
        "shell",
        "cloc",
        "start",
    }
)


# ── Models ───────────────────────────────────────────────────────────────────


class ShellResult(BaseModel):
    """Typed result envelope for odoo-bin / odoo-cli subprocess calls.

    Attributes:
        success: True when the process exited with return-code 0.
        returncode: The raw OS exit code.
        stdout: Captured standard output (truncated to 8 KiB).
        stderr: Captured standard error (truncated to 4 KiB).
        argv: The argv list that was executed (for auditability).
        message: Human-readable summary for the agent.
    """

    model_config = ConfigDict(extra="ignore")

    success: bool = Field(..., description="True when exit code is 0")
    returncode: int = Field(..., description="OS exit code")
    stdout: str = Field(default="", description="Captured stdout (≤8 KiB)")
    stderr: str = Field(default="", description="Captured stderr (≤4 KiB)")
    argv: list[str] = Field(default_factory=list, description="Executed argv")
    message: str = Field(default="", description="Summary for the agent")


class OdooShellInstallInput(BaseModel):
    """Input schema for ``odoo_shell_install_module`` and ``odoo_shell_upgrade_module``.

    Attributes:
        modules: Technical module names to install or upgrade.
        database: Target database; defaults to ``ODOO_TEST_DATABASE``.
        upgrade: When True, upgrade (``-u``) instead of install (``-i``).
    """

    model_config = ConfigDict(extra="ignore", protected_namespaces=())

    modules: list[str] = Field(
        ...,
        description="Technical module names to install, e.g. ['sale', 'stock']",
    )
    database: Optional[str] = Field(
        default=None,
        description="Target database; defaults to ODOO_TEST_DATABASE env var",
    )
    upgrade: bool = Field(
        default=False,
        description="If True, upgrade (-u) instead of install (-i)",
    )


class OdooCliCommandInput(BaseModel):
    """Input schema for ``odoo_cli_command``.

    Attributes:
        subcommand: A whitelisted odoo-cli/odoo-bin subcommand.
        args: Additional positional arguments for the subcommand.
        database: Target database; defaults to ``ODOO_TEST_DATABASE``.
    """

    model_config = ConfigDict(extra="ignore", protected_namespaces=())

    subcommand: str = Field(
        ...,
        description=(
            f"Whitelisted odoo-bin subcommand. Allowed: {sorted(ALLOWED_SUBCOMMANDS)}"
        ),
    )
    args: list[str] = Field(
        default_factory=list,
        description="Additional arguments forwarded to the subcommand",
    )
    database: Optional[str] = Field(
        default=None,
        description="Target database; defaults to ODOO_TEST_DATABASE env var",
    )


# ── Helpers ──────────────────────────────────────────────────────────────────


def _odoo_bin_path() -> Optional[str]:
    """Return the path to the odoo-bin binary, or None when not configured.

    Checks the ``ODOO_BIN`` environment variable first; falls back to
    ``shutil.which`` so a binary on ``PATH`` is also accepted.

    Returns:
        Absolute path string, or None if unavailable.
    """
    path = os.environ.get("ODOO_BIN")
    if path:
        return path
    # Fallback: look for odoo-bin or odoo on PATH
    return shutil.which("odoo-bin") or shutil.which("odoo")


def _default_database() -> str:
    """Return the default Odoo database from the environment.

    Returns:
        Database name string (may be empty if env var is unset).
    """
    return os.environ.get("ODOO_TEST_DATABASE", "")


def _odoo_conf_path() -> Optional[str]:
    """Return the Odoo config file path from the environment.

    Returns:
        Config file path string, or None.
    """
    return os.environ.get("ODOO_CONF")


def _validate_token(token: str, label: str = "token") -> None:
    """Validate that a token contains only safe characters.

    Args:
        token: The string to validate.
        label: Human-readable name for error messages.

    Raises:
        ValueError: When the token contains illegal characters.
    """
    if not token or not _TOKEN_RE.match(token):
        raise ValueError(
            f"Invalid {label} {token!r}: only alphanumerics, underscores, "
            "hyphens, and dots are allowed."
        )


def _validate_subcommand(subcommand: str) -> None:
    """Validate that a subcommand is on the whitelist.

    Args:
        subcommand: The subcommand string to validate.

    Raises:
        ValueError: When the subcommand is not whitelisted.
    """
    if subcommand not in ALLOWED_SUBCOMMANDS:
        raise ValueError(
            f"Subcommand {subcommand!r} is not whitelisted. "
            f"Allowed: {sorted(ALLOWED_SUBCOMMANDS)}"
        )


def _build_install_argv(
    bin_path: str,
    modules: list[str],
    database: str,
    upgrade: bool = False,
) -> list[str]:
    """Build the argv list for an install or upgrade call.

    Args:
        bin_path: Absolute path to the odoo-bin executable.
        modules: List of module technical names.
        database: Target Odoo database name.
        upgrade: When True, use ``-u`` flag; otherwise ``-i``.

    Returns:
        argv list ready for :func:`asyncio.create_subprocess_exec`.

    Raises:
        ValueError: When any module name or the database name is invalid.
    """
    if not modules:
        raise ValueError("modules list must not be empty")
    for mod in modules:
        _validate_token(mod, label="module name")
    _validate_token(database, label="database")

    flag = "-u" if upgrade else "-i"
    argv = [
        bin_path,
        "-d",
        database,
        flag,
        ",".join(modules),
        "--stop-after-init",
    ]
    conf = _odoo_conf_path()
    if conf:
        argv = [argv[0], "--conf", conf] + argv[1:]
    return argv


async def run_odoo_subprocess(
    argv: list[str],
    timeout: int = DEFAULT_SHELL_TIMEOUT,
) -> ShellResult:
    """Run an odoo-bin / odoo-cli subprocess and capture output.

    Args:
        argv: The argv list.  The first element must be the binary path.
        timeout: Maximum seconds to wait before killing the process.

    Returns:
        A :class:`ShellResult` with captured stdout, stderr, returncode.
    """
    logger.info("Running odoo subprocess: %s", " ".join(argv))
    try:
        proc = await asyncio.create_subprocess_exec(
            *argv,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        try:
            raw_out, raw_err = await asyncio.wait_for(
                proc.communicate(), timeout=timeout
            )
        except asyncio.TimeoutError:
            proc.kill()
            await proc.communicate()
            msg = f"Process timed out after {timeout}s: {argv[0]}"
            logger.error(msg)
            return ShellResult(
                success=False,
                returncode=-1,
                stdout="",
                stderr=msg,
                argv=argv,
                message=msg,
            )

        stdout_str = raw_out.decode("utf-8", errors="replace")[:8192]
        stderr_str = raw_err.decode("utf-8", errors="replace")[:4096]
        rc = proc.returncode if proc.returncode is not None else -1
        success = rc == 0
        msg = (
            f"{'Success' if success else 'Failed'} (exit {rc}): {argv[0]}"
        )
        logger.info(msg)
        return ShellResult(
            success=success,
            returncode=rc,
            stdout=stdout_str,
            stderr=stderr_str,
            argv=argv,
            message=msg,
        )
    except FileNotFoundError:
        msg = f"Binary not found: {argv[0]!r}"
        logger.error(msg)
        return ShellResult(
            success=False,
            returncode=-1,
            stdout="",
            stderr=msg,
            argv=argv,
            message=msg,
        )
    except Exception as exc:  # noqa: BLE001
        msg = f"Unexpected error running {argv[0]!r}: {exc}"
        logger.exception(msg)
        return ShellResult(
            success=False,
            returncode=-1,
            stdout="",
            stderr=str(exc),
            argv=argv,
            message=msg,
        )
