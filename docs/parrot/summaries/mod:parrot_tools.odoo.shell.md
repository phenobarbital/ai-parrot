---
type: Wiki Summary
title: parrot_tools.odoo.shell
id: mod:parrot_tools.odoo.shell
tags:
- summary
timestamp: '2026-07-16T08:34:12+00:00'
summary: Shell execution helpers for OdooToolkit odoo-bin / odoo-cli tools.
relates_to:
- concept: class:parrot_tools.odoo.shell.OdooCliCommandInput
  rel: defines
- concept: class:parrot_tools.odoo.shell.OdooShellInstallInput
  rel: defines
- concept: class:parrot_tools.odoo.shell.OdooShellUpgradeInput
  rel: defines
- concept: class:parrot_tools.odoo.shell.ShellResult
  rel: defines
- concept: func:parrot_tools.odoo.shell.build_install_argv
  rel: defines
- concept: func:parrot_tools.odoo.shell.default_database
  rel: defines
- concept: func:parrot_tools.odoo.shell.odoo_bin_path
  rel: defines
- concept: func:parrot_tools.odoo.shell.odoo_conf_path
  rel: defines
- concept: func:parrot_tools.odoo.shell.run_odoo_subprocess
  rel: defines
- concept: func:parrot_tools.odoo.shell.validate_subcommand
  rel: defines
- concept: func:parrot_tools.odoo.shell.validate_token
  rel: defines
---

# `parrot_tools.odoo.shell`

Shell execution helpers for OdooToolkit odoo-bin / odoo-cli tools.

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

## Classes

- **`ShellResult(BaseModel)`** — Typed result envelope for odoo-bin / odoo-cli subprocess calls.
- **`OdooShellInstallInput(BaseModel)`** — Input schema for ``odoo_shell_install_module``.
- **`OdooShellUpgradeInput(BaseModel)`** — Input schema for ``odoo_shell_upgrade_module``.
- **`OdooCliCommandInput(BaseModel)`** — Input schema for ``odoo_cli_command``.

## Functions

- `def odoo_bin_path() -> Optional[str]` — Return the path to the odoo-bin binary, or None when not configured.
- `def default_database() -> str` — Return the default Odoo database from the environment.
- `def odoo_conf_path() -> Optional[str]` — Return the Odoo config file path from the environment.
- `def validate_token(token: str, label: str='token') -> None` — Validate that a token contains only safe characters.
- `def validate_subcommand(subcommand: str) -> None` — Validate that a subcommand is on the whitelist.
- `def build_install_argv(bin_path: str, modules: list[str], database: str, upgrade: bool=False) -> list[str]` — Build the argv list for an install or upgrade call.
- `async def run_odoo_subprocess(argv: list[str], timeout: int=DEFAULT_SHELL_TIMEOUT) -> ShellResult` — Run an odoo-bin / odoo-cli subprocess and capture output.
