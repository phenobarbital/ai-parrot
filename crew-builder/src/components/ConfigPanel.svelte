<script>
  import { createEventDispatcher } from 'svelte';
  
  export let agent;
  
  const dispatch = createEventDispatcher();
  
  let editMode = 'form'; // 'form' or 'json'
  let jsonError = null;
  
  // Form fields
  let formData = {
    agent_id: agent.agent_id || '',
    name: agent.name || '',
    agent_class: agent.agent_class || 'Agent',
    config: {
      model: agent.config?.model || 'gemini-2.5-pro',
      temperature: agent.config?.temperature || 0.7
    },
    tools: agent.tools || [],
    system_prompt: agent.system_prompt || ''
  };
  
  // JSON editor
  let jsonText = JSON.stringify(agent, null, 2);
  
  // Available models
  const models = [
    'gemini-2.5-pro',
    'gpt-4',
    'gpt-3.5-turbo',
    'claude-3-opus',
    'claude-3-sonnet',
    'claude-sonnet-4-5-20250929'
  ];
  
  // Available tools
  const availableTools = [
    'GoogleSearchTool',
    'WebScraperTool',
    'FileReaderTool',
    'CalculatorTool',
    'CodeInterpreterTool'
  ];
  
  function toggleTool(tool) {
    const index = formData.tools.indexOf(tool);
    if (index > -1) {
      formData.tools = formData.tools.filter(t => t !== tool);
    } else {
      formData.tools = [...formData.tools, tool];
    }
  }
  
  function saveForm() {
    dispatch('update', formData);
    dispatch('close');
  }
  
  function saveJSON() {
    try {
      const parsed = JSON.parse(jsonText);
      jsonError = null;
      dispatch('update', parsed);
      dispatch('close');
    } catch (e) {
      jsonError = `Invalid JSON: ${e.message}`;
    }
  }
  
  function handleSave() {
    if (editMode === 'form') {
      saveForm();
    } else {
      saveJSON();
    }
  }
  
  function handleDelete() {
    if (confirm('Are you sure you want to delete this agent?')) {
      dispatch('delete');
    }
  }
  
  function switchMode(mode) {
    if (mode === 'json' && editMode === 'form') {
      // Update JSON from form data
      jsonText = JSON.stringify(formData, null, 2);
    } else if (mode === 'form' && editMode === 'json') {
      // Update form from JSON
      try {
        formData = JSON.parse(jsonText);
        jsonError = null;
      } catch (e) {
        jsonError = `Invalid JSON: ${e.message}`;
        return;
      }
    }
    editMode = mode;
  }
</script>

<div class="config-panel">
  <div class="panel-header">
    <h2>Configure Agent</h2>
    <button class="close-btn" on:click={() => dispatch('close')}>×</button>
  </div>
  
  <div class="mode-toggle">
    <button 
      class:active={editMode === 'form'}
      on:click={() => switchMode('form')}
    >
      Form
    </button>
    <button 
      class:active={editMode === 'json'}
      on:click={() => switchMode('json')}
    >
      JSON
    </button>
  </div>
  
  <div class="panel-body">
    {#if editMode === 'form'}
      <div class="form">
        <div class="form-group">
          <label for="agent-id">Agent ID*</label>
          <input 
            id="agent-id"
            type="text" 
            bind:value={formData.agent_id}
            placeholder="e.g., researcher"
          />
        </div>
        
        <div class="form-group">
          <label for="agent-name">Name*</label>
          <input 
            id="agent-name"
            type="text" 
            bind:value={formData.name}
            placeholder="e.g., Research Agent"
          />
        </div>
        
        <div class="form-group">
          <label for="agent-class">Agent Class</label>
          <input 
            id="agent-class"
            type="text" 
            bind:value={formData.agent_class}
            placeholder="Agent"
          />
        </div>
        
        <div class="form-group">
          <label for="model">Model*</label>
          <select id="model" bind:value={formData.config.model}>
            {#each models as model}
              <option value={model}>{model}</option>
            {/each}
          </select>
        </div>
        
        <div class="form-group">
          <label for="temperature">Temperature</label>
          <input 
            id="temperature"
            type="number" 
            bind:value={formData.config.temperature}
            min="0"
            max="2"
            step="0.1"
          />
          <small>Range: 0.0 - 2.0</small>
        </div>
        
        <div class="form-group">
          <label>Tools</label>
          <div class="tools-grid">
            {#each availableTools as tool}
              <label class="tool-checkbox">
                <input 
                  type="checkbox"
                  checked={formData.tools.includes(tool)}
                  on:change={() => toggleTool(tool)}
                />
                <span>{tool}</span>
              </label>
            {/each}
          </div>
        </div>
        
        <div class="form-group">
          <label for="system-prompt">System Prompt*</label>
          <textarea 
            id="system-prompt"
            bind:value={formData.system_prompt}
            rows="6"
            placeholder="You are an expert AI agent..."
          />
        </div>
      </div>
    {:else}
      <div class="json-editor">
        <textarea 
          bind:value={jsonText}
          rows="20"
          placeholder="Paste or edit JSON configuration..."
        />
        {#if jsonError}
          <div class="error-message">{jsonError}</div>
        {/if}
      </div>
    {/if}
  </div>
  
  <div class="panel-footer">
    <button class="btn-delete" on:click={handleDelete}>Delete</button>
    <div class="spacer" />
    <button class="btn-cancel" on:click={() => dispatch('close')}>Cancel</button>
    <button class="btn-save" on:click={handleSave}>Save</button>
  </div>
</div>

<div class="overlay" on:click={() => dispatch('close')} />

<style>
  .overlay {
    position: fixed;
    top: 0;
    left: 0;
    right: 0;
    bottom: 0;
    background: rgba(0, 0, 0, 0.5);
    z-index: 999;
  }
  
  .config-panel {
    position: fixed;
    top: 0;
    right: 0;
    width: 400px;
    height: 100vh;
    background: white;
    box-shadow: -2px 0 10px rgba(0, 0, 0, 0.2);
    display: flex;
    flex-direction: column;
    z-index: 1000;
  }
  
  .panel-header {
    display: flex;
    justify-content: space-between;
    align-items: center;
    padding: 20px;
    border-bottom: 1px solid #e5e7eb;
  }
  
  .panel-header h2 {
    margin: 0;
    font-size: 18px;
    color: #111827;
  }
  
  .close-btn {
    background: none;
    border: none;
    font-size: 28px;
    cursor: pointer;
    color: #6b7280;
    padding: 0;
    width: 32px;
    height: 32px;
    display: flex;
    align-items: center;
    justify-content: center;
  }
  
  .close-btn:hover {
    color: #111827;
  }
  
  .mode-toggle {
    display: flex;
    padding: 12px 20px;
    gap: 8px;
    border-bottom: 1px solid #e5e7eb;
  }
  
  .mode-toggle button {
    flex: 1;
    padding: 8px 16px;
    border: 1px solid #d1d5db;
    background: white;
    border-radius: 6px;
    cursor: pointer;
    font-size: 14px;
    transition: all 0.2s;
  }
  
  .mode-toggle button.active {
    background: #4f46e5;
    color: white;
    border-color: #4f46e5;
  }
  
  .panel-body {
    flex: 1;
    overflow-y: auto;
    padding: 20px;
  }
  
  .form {
    display: flex;
    flex-direction: column;
    gap: 16px;
  }
  
  .form-group {
    display: flex;
    flex-direction: column;
    gap: 6px;
  }
  
  .form-group label {
    font-size: 13px;
    font-weight: 500;
    color: #374151;
  }
  
  .form-group input[type="text"],
  .form-group input[type="number"],
  .form-group select,
  .form-group textarea {
    padding: 8px 12px;
    border: 1px solid #d1d5db;
    border-radius: 6px;
    font-size: 14px;
    font-family: inherit;
  }
  
  .form-group textarea {
    resize: vertical;
    font-family: 'Courier New', monospace;
  }
  
  .form-group small {
    font-size: 11px;
    color: #6b7280;
  }
  
  .tools-grid {
    display: grid;
    grid-template-columns: 1fr;
    gap: 8px;
  }
  
  .tool-checkbox {
    display: flex;
    align-items: center;
    gap: 8px;
    padding: 8px;
    border: 1px solid #e5e7eb;
    border-radius: 6px;
    cursor: pointer;
    transition: all 0.2s;
  }
  
  .tool-checkbox:hover {
    background: #f9fafb;
    border-color: #d1d5db;
  }
  
  .tool-checkbox input[type="checkbox"] {
    cursor: pointer;
  }
  
  .tool-checkbox span {
    font-size: 13px;
    color: #374151;
  }
  
  .json-editor textarea {
    width: 100%;
    height: 100%;
    padding: 12px;
    border: 1px solid #d1d5db;
    border-radius: 6px;
    font-family: 'Courier New', monospace;
    font-size: 12px;
    resize: none;
  }
  
  .error-message {
    margin-top: 8px;
    padding: 8px 12px;
    background: #fef2f2;
    border: 1px solid #fecaca;
    border-radius: 6px;
    color: #dc2626;
    font-size: 12px;
  }
  
  .panel-footer {
    display: flex;
    gap: 8px;
    padding: 16px 20px;
    border-top: 1px solid #e5e7eb;
  }
  
  .spacer {
    flex: 1;
  }
  
  .panel-footer button {
    padding: 8px 16px;
    border: none;
    border-radius: 6px;
    font-size: 14px;
    font-weight: 500;
    cursor: pointer;
    transition: all 0.2s;
  }
  
  .btn-delete {
    background: #dc2626;
    color: white;
  }
  
  .btn-delete:hover {
    background: #b91c1c;
  }
  
  .btn-cancel {
    background: white;
    color: #374151;
    border: 1px solid #d1d5db;
  }
  
  .btn-cancel:hover {
    background: #f9fafb;
  }
  
  .btn-save {
    background: #4f46e5;
    color: white;
  }
  
  .btn-save:hover {
    background: #4338ca;
  }
</style>
