<!--
  ai-parrot (FEAT-476 TASK-2596): test-only stub for avatar-gating.test.ts.

  AvatarViewer.svelte's own LiveKit connect logic is a verbatim port with
  no gating changes to verify — this stub replaces it (via `vi.mock`) so
  the test can drive AgentChat's `onstatuschange` handling directly
  instead of simulating a full (mocked) LiveKit session. Not part of the
  production build; only ever reached through the test's `vi.mock`.
-->
<script lang="ts">
  let { onstatuschange }: { onstatuschange?: (status: string) => void } =
    $props();
  (globalThis as any).__avatarStatusCallback = onstatuschange ?? null;
</script>
