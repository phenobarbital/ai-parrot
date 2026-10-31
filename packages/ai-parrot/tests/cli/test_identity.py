"""Tests for the FEAT-774 CLI identity hard cut."""
from __future__ import annotations

import parrot.cli.identity as identity


def test_o365_bootstrap_symbols_are_removed():
    """The retired O365 environment bootstrap has no compatibility shim."""
    assert identity.CLI_CHANNEL == "cli"
    for name in (
        "O365_PRINCIPAL_ENV_VAR",
        "O365_TENANT_ID_ENV_VAR",
        "UNSET_CLI_TENANT",
        "resolve_cli_o365_principal",
        "bot_declares_o365_device_code",
    ):
        assert not hasattr(identity, name)
