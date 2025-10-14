<script>
  import { createEventDispatcher } from 'svelte';
  import { crewStore } from '../stores/crewStore';
  import crewAPI from '../api/crewAPI';
  
  const dispatch = createEventDispatcher();
  
  let crewName = '';
  let crewDescription = '';
  let executionMode = 'sequential';
  let uploading = false;
  let uploadStatus = null;
  
  // Subscribe to crew metadata
  crewStore.subscribe(value => {
    crewName = value.metadata.name;
    crewDescription = value.metadata.description;
    executionMode = value.metadata.execution_mode;
  });
  
  function updateMetadata() {
    crewStore.updateMetadata({
      name: crewName,
      description: crewDescription,
      execution_mode: executionMode
    });
  }
  
  async function uploadToAPI() {
    try {
      uploading = true;
      uploadStatus = null;
      
      const crewJSON = crewStore.exportToJSON();
      
      // Create crew via API
      const response = await crewAPI.createCrew(crewJSON);
      
      uploadStatus = {
        type: 'success',
        message: `Crew "${response.name}" created successfully!`
      };
      
      console.log('Crew created:', response);
      
      // Auto-clear status after 3 seconds
      setTimeout(() => {
        uploadStatus = null;
      }, 3000);
      
    } catch (error) {
      uploadStatus = {
        type: 'error',
        message: `Failed to upload: ${error.message}`
      };
      console.error('Upload error:', error);
    } finally {
      uploading = false;
    }
  }
</script>

<div class="toolbar">
  <div class="toolbar-left">
    <div class="logo">
      <span class="icon">🦜</span>
      <span class="title">AgentCrew Builder</span>
    </div>
    
    <div class="metadata-inputs">
      <input 
        type="text" 
        bind:value={crewName}
        on:change={updateMetadata}
        placeholder="Crew name..."
        class="crew-name"
      />
      <input 
        type="text" 
        bind:value={crewDescription}
        on:change={updateMetadata}
        placeholder="Description..."
        class="crew-description"
      />
      <select bind:value={executionMode} on:change={updateMetadata}>
        <option value="sequential">Sequential</option>
        <option value="parallel">Parallel (Coming Soon)</option>
        <option value="hierarchical">Hierarchical (Coming Soon)</option>
      </select>
    </div>
  </div>
  
  <div class="toolbar-right">
    <button class="btn-add" on:click={() => dispatch('addAgent')}>
      <span>+</span> Add Agent
    </button>
    <button 
      class="btn-upload" 
      on:click={uploadToAPI}
      disabled={uploading}
    >
      <span>☁️</span> {uploading ? 'Uploading...' : 'Upload to API'}
    </button>
    <button class="btn-export" on:click={() => dispatch('export')}>
      <span>📥</span> Export JSON
    </button>
  </div>
</div>

{#if uploadStatus}
  <div class="upload-status" class:success={uploadStatus.type === 'success'} class:error={uploadStatus.type === 'error'}>
    {uploadStatus.message}
  </div>
{/if}

<style>
  .toolbar {
    display: flex;
    justify-content: space-between;
    align-items: center;
    padding: 12px 20px;
    background: white;
    border-bottom: 2px solid #e5e7eb;
    box-shadow: 0 2px 4px rgba(0, 0, 0, 0.05);
  }
  
  .toolbar-left {
    display: flex;
    align-items: center;
    gap: 20px;
    flex: 1;
  }
  
  .logo {
    display: flex;
    align-items: center;
    gap: 8px;
  }
  
  .icon {
    font-size: 24px;
  }
  
  .title {
    font-size: 18px;
    font-weight: 700;
    color: #111827;
  }
  
  .metadata-inputs {
    display: flex;
    gap: 12px;
    flex: 1;
    max-width: 800px;
  }
  
  .metadata-inputs input,
  .metadata-inputs select {
    padding: 8px 12px;
    border: 1px solid #d1d5db;
    border-radius: 6px;
    font-size: 13px;
  }
  
  .crew-name {
    flex: 0 0 200px;
    font-weight: 600;
  }
  
  .crew-description {
    flex: 1;
  }
  
  .metadata-inputs select {
    flex: 0 0 150px;
  }
  
  .toolbar-right {
    display: flex;
    gap: 12px;
  }
  
  .toolbar-right button {
    display: flex;
    align-items: center;
    gap: 6px;
    padding: 8px 16px;
    border: none;
    border-radius: 6px;
    font-size: 14px;
    font-weight: 500;
    cursor: pointer;
    transition: all 0.2s;
  }
  
  .btn-add {
    background: #4f46e5;
    color: white;
  }
  
  .btn-add:hover {
    background: #4338ca;
  }
  
  .btn-upload {
    background: #059669;
    color: white;
  }
  
  .btn-upload:hover:not(:disabled) {
    background: #047857;
  }
  
  .btn-upload:disabled {
    opacity: 0.6;
    cursor: not-allowed;
  }
  
  .btn-export {
    background: #0284c7;
    color: white;
  }
  
  .btn-export:hover {
    background: #0369a1;
  }
  
  button span:first-child {
    font-size: 16px;
  }
  
  .upload-status {
    position: fixed;
    top: 80px;
    right: 20px;
    padding: 12px 20px;
    border-radius: 8px;
    font-size: 14px;
    font-weight: 500;
    box-shadow: 0 4px 12px rgba(0, 0, 0, 0.15);
    animation: slideIn 0.3s ease-out;
    z-index: 1000;
  }
  
  .upload-status.success {
    background: #d1fae5;
    color: #065f46;
    border: 1px solid #6ee7b7;
  }
  
  .upload-status.error {
    background: #fee2e2;
    color: #991b1b;
    border: 1px solid #fecaca;
  }
  
  @keyframes slideIn {
    from {
      transform: translateX(100%);
      opacity: 0;
    }
    to {
      transform: translateX(0);
      opacity: 1;
    }
  }
</style>
