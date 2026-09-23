from ._vitest import run_vitest


def test_tools_tab_vitest():
    run_vitest("src/pages/agents/form/TabsTools.test.ts")
