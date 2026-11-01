"""FEAT-777 (TASK-5057): run the IntegrationsMenu vitest from pytest (validation contract)."""

from ._vitest import run_vitest


def test_integrations_menu_vitest() -> None:
    """Menu reads the connections store and never calls /enable."""
    run_vitest("src/lib/components/agents/integrations/IntegrationsMenu.test.ts")
