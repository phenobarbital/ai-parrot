<script lang="ts">
  import { createEventDispatcher } from 'svelte';
  import type { AgentNodeData } from '$lib/stores/crewStore';

  export let agent: AgentNodeData;

  const dispatch = createEventDispatcher();
  let editMode: 'form' | 'json' = 'form';
  let jsonError: string | null = null;

  const models = [
    'gemini-2.5-pro',
    'gpt-4',
    'gpt-3.5-turbo',
    'claude-3-opus',
    'claude-3-sonnet',
    'claude-sonnet-4-5-20250929'
  ];

  const availableTools = [
    'GoogleSearchTool',
    'WebScraperTool',
    'FileReaderTool',
    'CalculatorTool',
    'CodeInterpreterTool'
  ];

  const buildFormState = (source: AgentNodeData) => ({
    agent_id: source.agent_id ?? '',
    name: source.name ?? '',
    agent_class: source.agent_class ?? 'Agent',
    config: {
      model: source.config?.model ?? 'gemini-2.5-pro',
      temperature: source.config?.temperature ?? 0.7
    },
    tools: source.tools ? [...source.tools] : [],
    system_prompt: source.system_prompt ?? ''
  });

  let formData = buildFormState(agent);
  let jsonText = JSON.stringify(agent, null, 2);

  $: if (agent && agent.agent_id !== formData.agent_id) {
    formData = buildFormState(agent);
    jsonText = JSON.stringify(agent, null, 2);
    jsonError = null;
  }

  function toggleTool(tool: string) {
    if (formData.tools.includes(tool)) {
      formData = { ...formData, tools: formData.tools.filter((item) => item !== tool) };
    } else {
      formData = { ...formData, tools: [...formData.tools, tool] };
    }
  }

  function handleSave() {
    if (editMode === 'form') {
      dispatch('update', formData);
      dispatch('close');
      return;
    }

    try {
      const parsed = JSON.parse(jsonText);
      jsonError = null;
      dispatch('update', parsed);
      dispatch('close');
    } catch (error) {
      jsonError = error instanceof Error ? error.message : 'Invalid JSON';
    }
  }

  function switchMode(mode: 'form' | 'json') {
    if (mode === editMode) return;
    if (mode === 'json') {
      jsonText = JSON.stringify(formData, null, 2);
      jsonError = null;
    } else {
      try {
        formData = buildFormState(JSON.parse(jsonText) as AgentNodeData);
        jsonError = null;
      } catch (error) {
        jsonError = error instanceof Error ? error.message : 'Invalid JSON';
        return;
      }
    }
    editMode = mode;
  }

  function handleDelete() {
    if (confirm('Are you sure you want to delete this agent?')) {
      dispatch('delete');
    }
  }
</script>

<div class="fixed inset-0 z-40 flex justify-end">
  <div class="absolute inset-0 bg-base-content/40" on:click={() => dispatch('close')} />
  <aside class="relative z-10 flex h-full w-full max-w-md flex-col bg-base-100 shadow-2xl">
    <header class="flex items-center justify-between border-b border-base-200 px-6 py-4">
      <h2 class="text-lg font-semibold">Configure Agent</h2>
      <button class="btn btn-circle btn-ghost btn-sm" on:click={() => dispatch('close')} aria-label="Close">
        ✕
      </button>
    </header>

    <div class="flex items-center gap-2 border-b border-base-200 px-6 py-3">
      <button
        class={`btn btn-sm flex-1 ${editMode === 'form' ? 'btn-primary' : 'btn-outline'}`}
        type="button"
        on:click={() => switchMode('form')}
      >
        Form
      </button>
      <button
        class={`btn btn-sm flex-1 ${editMode === 'json' ? 'btn-primary' : 'btn-outline'}`}
        type="button"
        on:click={() => switchMode('json')}
      >
        JSON
      </button>
    </div>

    <section class="flex-1 overflow-y-auto px-6 py-4">
      {#if editMode === 'form'}
        <form class="flex flex-col gap-4 text-sm" on:submit|preventDefault={handleSave}>
          <label class="form-control w-full">
            <span class="label-text">Agent ID*</span>
            <input class="input input-bordered" bind:value={formData.agent_id} placeholder="e.g., researcher" required />
          </label>
          <label class="form-control w-full">
            <span class="label-text">Name*</span>
            <input class="input input-bordered" bind:value={formData.name} placeholder="e.g., Research Agent" required />
          </label>
          <label class="form-control w-full">
            <span class="label-text">Agent Class</span>
            <input class="input input-bordered" bind:value={formData.agent_class} placeholder="Agent" />
          </label>
          <label class="form-control w-full">
            <span class="label-text">Model*</span>
            <select class="select select-bordered" bind:value={formData.config.model}>
              {#each models as modelOption}
                <option value={modelOption}>{modelOption}</option>
              {/each}
            </select>
          </label>
          <label class="form-control w-full">
            <span class="label-text">Temperature</span>
            <input
              class="input input-bordered"
              type="number"
              min="0"
              max="2"
              step="0.1"
              bind:value={formData.config.temperature}
            />
            <span class="label-text-alt">Range: 0.0 - 2.0</span>
          </label>
          <div class="form-control w-full">
            <span class="label-text">Tools</span>
            <div class="grid gap-2">
              {#each availableTools as tool}
                <label class={`flex items-center justify-between rounded-lg border px-4 py-2 ${formData.tools.includes(tool) ? 'border-primary bg-primary/10' : 'border-base-200'}`}>
                  <span>{tool}</span>
                  <input type="checkbox" class="checkbox" checked={formData.tools.includes(tool)} on:change={() => toggleTool(tool)} />
                </label>
              {/each}
            </div>
          </div>
          <label class="form-control w-full">
            <span class="label-text">System Prompt*</span>
            <textarea
              class="textarea textarea-bordered font-mono"
              rows="6"
              bind:value={formData.system_prompt}
              placeholder="You are an expert AI agent..."
            />
          </label>
        </form>
      {:else}
        <div class="flex flex-col gap-3">
          <textarea
            class={`textarea textarea-bordered h-80 font-mono text-xs ${jsonError ? 'textarea-error' : ''}`}
            bind:value={jsonText}
            placeholder="Paste or edit JSON configuration..."
          />
          {#if jsonError}
            <div class="alert alert-error text-sm">
              <span>{jsonError}</span>
            </div>
          {/if}
        </div>
      {/if}
    </section>

    <footer class="flex items-center gap-2 border-t border-base-200 px-6 py-4">
      <button class="btn btn-error btn-sm" type="button" on:click={handleDelete}>Delete</button>
      <span class="flex-1" />
      <button class="btn btn-ghost btn-sm" type="button" on:click={() => dispatch('close')}>
        Cancel
      </button>
      <button class="btn btn-primary btn-sm" type="button" on:click={handleSave}>
        Save
      </button>
    </footer>
  </aside>
</div>
