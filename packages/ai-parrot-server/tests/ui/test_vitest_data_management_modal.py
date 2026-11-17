from ._vitest import run_vitest


def test_data_management_modal_vitest():
    run_vitest("src/lib/components/agents/DataManagementModal.test.ts")
