<!--
  Agents page (TASK-2530) — thin wrapper delegating to the read-only
  agents module (pages/agents/AgentsList.svelte). Kept as a separate file
  (rather than repointing App.svelte's route table, which is outside this
  task's Files to Create/Modify) so /admin/agents keeps working unchanged.
-->
<script lang="ts">
  import AgentsList from "./agents/AgentsList.svelte";
</script>

<AgentsList />
