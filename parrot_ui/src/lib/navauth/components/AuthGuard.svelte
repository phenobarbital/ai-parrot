<!-- src/lib/navauth/components/AuthGuard.svelte -->
<script lang="ts">
  import { goto } from '$app/navigation';
  import { onMount } from 'svelte';
  import type { NavAuthStore } from '../store.svelte';
  import type { Snippet } from 'svelte';

  interface Props {
    auth: NavAuthStore;
    redirectTo?: string;
    requiredGroups?: string[];
    requiredPrograms?: string[];
    children: Snippet;
    fallback?: Snippet;
  }

  let {
    auth,
    redirectTo = '/login',
    requiredGroups = [],
    requiredPrograms = [],
    children,
    fallback
  }: Props = $props();

  let checked = $state(false);
  let authorized = $state(false);

  onMount(() => {
    const unsubscribe = auth.subscribe(state => {
      if (state.loading) return;

      checked = true;

      if (!state.isAuthenticated) {
        authorized = false;
        goto(redirectTo);
        return;
      }

      // Check group permissions
      if (requiredGroups.length > 0) {
        const hasGroup = requiredGroups.some(g => state.user?.groups.includes(g));
        if (!hasGroup && !state.user?.isSuperuser) {
          authorized = false;
          return;
        }
      }

      // Check program access
      if (requiredPrograms.length > 0) {
        const hasProgram = requiredPrograms.some(p => state.user?.programs.includes(p));
        if (!hasProgram && !state.user?.isSuperuser) {
          authorized = false;
          return;
        }
      }

      authorized = true;
    });

    return unsubscribe;
  });
</script>

{#if !checked}
  <div class="flex items-center justify-center min-h-screen">
    <span class="loading loading-spinner loading-lg"></span>
  </div>
{:else if authorized}
  {@render children()}
{:else if fallback}
  {@render fallback()}
{:else}
  <div class="flex items-center justify-center min-h-screen">
    <div class="text-center">
      <h2 class="text-xl font-semibold">Access Denied</h2>
      <p class="text-base-content/60">You don't have permission to view this page.</p>
    </div>
  </div>
{/if}
