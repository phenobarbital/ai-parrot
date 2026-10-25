from ._vitest import run_vitest


def test_upload_status_vitest():
    run_vitest(
        "src/lib/components/agents/upload-status.test.ts",
        "src/lib/api/agent.test.ts",
    )
