"""FEAT-777 (TASK-5055): run the chat auth-required / auto-retry vitests from pytest."""

from ._vitest import run_vitest


def test_chat_auth_retry_vitest() -> None:
    """Pill in both modes; one guarded auto-retry; manual retry otherwise."""
    run_vitest(
        "src/lib/components/agents/AgentChat.auth-retry.test.ts",
        "src/lib/components/agents/integrations/ConnectIntegrationPill.test.ts",
        "src/lib/components/agents/AgentChat.test.ts",
        "src/lib/components/agents/avatar-gating.test.ts",
        "src/lib/components/agents/voice-gating.test.ts",
        "src/pages/agents/AgentDetail.test.ts",
        "src/pages/agents/AgentChatPage.test.ts",
    )
