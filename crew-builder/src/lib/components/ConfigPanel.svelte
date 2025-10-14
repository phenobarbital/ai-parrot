<script lang="ts">
  import type { AgentNodeData } from '$lib/stores/crewStore';

  // Svelte 5: Use callback props instead of createEventDispatcher
  interface Props {
    agent: AgentNodeData;
    onClose?: () => void;
    onUpdate?: (data: Partial<AgentNodeData>) => void;
    onDelete?: () => void;
  }

  let { agent, onClose, onUpdate, onDelete }: Props = $props();

  let editMode = $state<'form' | 'json'>('form');
  let jsonError = $state<string | null>(null);

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

  let formData = $state(buildFormState(agent));
  let jsonText = $state(JSON.stringify(agent, null, 2));

  $effect(() => {
    if (agent && agent.agent_id !== formData.agent_id) {
      formData = buildFormState(agent);
      jsonText = JSON.stringify(agent, null, 2);
      jsonError = null;
    }
  });

  function toggleTool(tool: string) {
    if (formData.tools.includes(tool)) {
      formData = { ...formData, tools: formData.tools.filter((item) => item !== tool) };
    } else {
      formData = { ...formData, tools: [...formData.tools, tool] };
    }
  }

  function handleSave() {
    if (editMode === 'form') {
      onUpdate?.(formData);
      onClose?.();
      return;
    }

    try {
      const parsed = JSON.parse(jsonText);
      jsonError = null;
      onUpdate?.(parsed);
      onClose?.();
    } catch (error) {
      jsonError = error instanceof Error ? error.message : 'Invalid JSON';
    }
  }

  function handleFormSubmit(event: SubmitEvent) {
    event.preventDefault();
    handleSave();
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

  function handleDeleteClick() {
    if (confirm('Are you sure you want to delete this agent?')) {
      onDelete?.();
    }
  }
</script>

<div class="fixed inset-0 z-40 flex justify-end">
  <div
    class="absolute inset-0 bg-base-content/40"
    role="button"
    tabindex="0"
    onclick={() => onClose?.()}
    onkeydown={(event) => {
      if (event.key === 'Enter' || event.key === ' ') {
        event.preventDefault();
        onClose?.();
      }
    }}
  ></div>
  <aside class="relative z-10 flex h-full w-full max-w-md flex-col bg-base-100 shadow-2xl">
    <header class="flex items-center justify-between border-b border-base-200 px-6 py-4">
      <h2 class="text-lg font-semibold">Configure Agent</h2>
      <button class="btn btn-circle btn-ghost btn-sm" onclick={() => onClose?.()} aria-label="Close">
        ✕
      </button>
    </header>

    <div class="flex items-center gap-2 border-b border-base-200 px-6 py-3">
      <button
        class={`btn btn-sm flex-1 ${editMode === 'form' ? 'btn-primary' : 'btn-outline'}`}
        type="button"
        onclick={() => switchMode('form')}
      >
        Form
      </button>
      <button
        class={`btn btn-sm flex-1 ${editMode === 'json' ? 'btn-primary' : 'btn-outline'}`}
        type="button"
        onclick={() => switchMode('json')}
      >
        JSON
      </button>
    </div>

    <div class="flex-1 overflow-y-auto p-6">
      {#if editMode === 'form'}
        <form class="space-y-4" onsubmit={handleFormSubmit}>
          <div class="form-control">
            <label class="label" for="agent-id">
              <span class="label-text">Agent ID</span>
            </label>
            <input
              id="agent-id"
              class="input input-bordered input-sm"
              type="text"
              bind:value={formData.agent_id}
              placeholder="agent_1"
            />
          </div>

          <div class="form-control">
            <label class="label" for="agent-name">
              <span class="label-text">Name</span>
            </label>
            <input
              id="agent-name"
              class="input input-bordered input-sm"
              type="text"
              bind:value={formData.name}
              placeholder="Agent 1"
            />
          </div>

          <div class="form-control">
            <label class="label" for="agent-class">
              <span class="label-text">Agent Class</span>
            </label>
            <input
              id="agent-class"
              class="input input-bordered input-sm"
              type="text"
              bind:value={formData.agent_class}
              placeholder="Agent"
            />
          </div>

          <div class="form-control">
            <label class="label" for="agent-model">
              <span class="label-text">Model</span>
            </label>
            <select id="agent-model" class="select select-bordered select-sm" bind:value={formData.config.model}>
              {#each models as model}
                <option value={model}>{model}</option>
              {/each}
            </select>
          </div>

          <div class="form-control">
            <label class="label" for="agent-temperature">
              <span class="label-text">Temperature: {formData.config.temperature}</span>
            </label>
            <input
              id="agent-temperature"
              class="range range-primary range-sm"
              type="range"
              min="0"
              max="1"
              step="0.1"
              bind:value={formData.config.temperature}
            />
          </div>

          <div class="form-control">
            <label class="label">
              <span class="label-text">Tools</span>
            </label>
            <div class="space-y-2">
              {#each availableTools as tool}
                <label class="flex cursor-pointer items-center gap-2">
                  <input
                    type="checkbox"
                    class="checkbox checkbox-sm"
                    checked={formData.tools.includes(tool)}
                    onchange={() => toggleTool(tool)}
                  />
                  <span class="text-sm">{tool}</span>
                </label>
              {/each}
            </div>
          </div>

          <div class="form-control">
            <label class="label" for="agent-prompt">
              <span class="label-text">System Prompt</span>
            </label>
            <textarea
              id="agent-prompt"
              class="textarea textarea-bordered h-32"
              bind:value={formData.system_prompt}
              placeholder="You are an expert AI agent."
            ></textarea>
          </div>
        </form>
      {:else}
        <div class="space-y-4">
          <textarea
            class="textarea textarea-bordered h-96 w-full font-mono text-xs"
            bind:value={jsonText}
            placeholder="Edit JSON..."
          ></textarea>
          {#if jsonError}
            <div class="alert alert-error">
              <span>{jsonError}</span>
            </div>
          {/if}
        </div>
      {/if}
    </div>

    <footer class="flex items-center justify-between border-t border-base-200 p-6">
      <button class="btn btn-error btn-sm" type="button" onclick={handleDeleteClick}>
        Delete Agent
      </button>
      <div class="flex gap-2">
        <button class="btn btn-ghost btn-sm" type="button" onclick={() => onClose?.()}>
          Cancel
        </button>
        <button class="btn btn-primary btn-sm" type="button" onclick={handleSave}>
          Save Changes
        </button>
      </div>
    </footer>
  </aside>
</div>
