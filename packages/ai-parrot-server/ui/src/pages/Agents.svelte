<!--
  Agents page (TASK-2530) — thin wrapper delegating to the agents module
  (pages/agents/AgentsList.svelte). Serves both /agents (end-user list:
  Chat only) and /admin/agents (management: create/edit/delete), picking
  the mode from the current path.
-->
<script lang="ts">
  import { config } from "$lib/config";
  import { router } from "$lib/router.svelte";
  import AgentsList from "./agents/AgentsList.svelte";

  const mode = $derived(router.path.startsWith(`${config.adminPath}/`) ? "admin" : "user");
</script>

{#key mode}
  <AgentsList {mode} />
{/key}
