from ._vitest import run_vitest


def test_my_tool_settings_vitest():
    run_vitest("src/lib/components/agents/MyToolkitSettings.test.ts")
