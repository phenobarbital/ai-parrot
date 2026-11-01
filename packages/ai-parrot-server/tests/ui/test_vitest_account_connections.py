"""FEAT-777 (TASK-5056): run the Account › Connections / Link vitests from pytest."""

from ._vitest import run_vitest


def test_account_connections_vitest() -> None:
    """Connections panel actions and the preview-then-confirm link page."""
    run_vitest(
        "src/lib/components/account/ConnectionsPanel.test.ts",
        "src/pages/account/LinkChannel.test.ts",
    )
