"""FEAT-777 (TASK-5053): run the connections client/store vitests from pytest (validation contract)."""

from ._vitest import run_vitest


def test_connections_store_vitest() -> None:
    """Connections client, SSE parsing, store refresh/backoff/stop."""
    run_vitest("src/lib/api/connections.test.ts", "src/lib/stores/connections.test.ts")
