<!--
  ai-parrot (FEAT-476 TASK-2597): test-only stand-in for the real,
  heavy-dependency `AgentChat.svelte` (WebSocket connect, prompt-library
  fetch, stream client, …) — swapped in via `vi.mock(
  "$lib/components/agents/AgentChat.svelte", ...)` in AgentChatPage.test.ts
  and AgentDetail.test.ts, per this task's own Test Specification sketch.
  Exposes the props a caller passed as data-* attributes so a test can
  assert on them without needing the full mock surface AgentChat.test.ts
  requires.
-->
<script lang="ts">
  let {
    agentId,
    chatbotId,
    variant,
  }: {
    agentId: string;
    chatbotId?: string;
    variant?: string;
  } = $props();
</script>

<div
  data-testid="agentchat-stub"
  data-agent-id={agentId}
  data-chatbot-id={chatbotId}
  data-variant={variant}
></div>
