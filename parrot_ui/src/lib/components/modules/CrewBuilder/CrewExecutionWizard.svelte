<script>
    import { onMount, onDestroy } from 'svelte';
    import { fade, slide } from 'svelte/transition';
    import { crew as crewApi } from '$lib/api/crew';
    import { markdownToHtml } from '$lib/utils/markdown';
    
    // Props
    let { showModal = false, crew = null, initialJobId = null, initialJobStatus = null, onClose = () => {} } = $props();

    // State Variables
    let currentStep = $state(1); // 1: Input, 2: Running, 3: Results
    let isSubmitting = $state(false);
    let jobError = $state('');
    let statusMessage = $state('');
    let jobId = $state(null);
    let pollingInterval = null;
    
    // Create state for full crew details
    let crewDetails = $state(null);
    let crewDetailsLoading = $state(false);
    let crewDetailsError = $state('');
    
    // Step 1: Input State
    let question = $state('');
    let generateSummary = $state(true);
    let currentMode = $state('sequential');
    let executionOptions = $state({}); // To hold other specialized options if needed
    
    // Loop & Sequence State
    let loopCondition = $state('');
    let loopMaxIterations = $state(4);
    let loopAgentSequence = $state([]); // Array of agent IDs
    let draggingIndex = $state(null);
    
    // Step 2: Running State
    let agentStatuses = $state([]);
    let jobStatus = $state(null);
    let agentResults = $state({}); // Map agent_id -> result content
    let selectedAgentId = $state(null); // For viewing specific agent result in Step 2/3
    let selectedAgentResult = $state(null);
    
    // Step 3: Results State
    let finalResult = $state(null);
    let summaryText = $state('');
    let summaryMode = $state('executive_summary');
    let summaryPrompt = $state('');
    let askQuestionText = $state('');
    let askQuestionResponse = $state('');
    
    let resultsTab = $state('summary'); // 'summary', 'agents', 'full'
    let copied = $state(false);
    
    // Constants
     const executionModeMeta = {
        sequential: { label: 'Sequential', description: "Run agents one after another." },
        parallel: { label: 'Parallel', description: 'Execute agents simultaneously.' },
        loop: { label: 'Loop', description: 'Iterate through agents until condition met.' },
        flow: { label: 'Flow', description: "Follow flow configuration." }
    };

    // Derived
    let selectedCrewId = $derived(crew?.crew_id);
    let selectedAgent = $derived(agentStatuses.find(a => a.agent_id === selectedAgentId));

    $effect(() => {
        if (showModal) {
            resetWizard();
        } else {
            stopPolling();
        }
    });

    // Cleanup
    onDestroy(() => {
        stopPolling();
    });

    async function fetchCrewDetails(id) {
        if (!id) return;
        crewDetailsLoading = true;
        crewDetailsError = '';
        try {
            const details = await crewApi.getCrewById(id);
            crewDetails = details;
            
            // Initialize agent sequence from full details
            if (details.agents && Array.isArray(details.agents)) {
                 loopAgentSequence = details.agents.map(a => a.agent_id);
            }
        } catch (error) {
            console.error("Failed to load crew details", error);
            crewDetailsError = "Failed to load crew configuration details.";
        } finally {
            crewDetailsLoading = false;
        }
    }

    function resetWizard() {
        jobId = initialJobId || null;
        
        if (jobId) {
             if (initialJobStatus === 'completed') {
                 currentStep = 3;
             } else {
                 currentStep = 2;
             }
        } else {
             currentStep = 1;
        }
        
        question = ''; 
        currentMode = crew?.execution_mode || 'sequential';
        agentStatuses = [];
        agentResults = {};
        jobError = '';
        statusMessage = '';
        isSubmitting = false;
        finalResult = null;
        isSubmitting = false;
        finalResult = null;
        stopPolling();

        // Reset full details state
        crewDetails = null;
        loopAgentSequence = [];
        
        // Fetch details if we have a crew ID
        if (selectedCrewId) {
            fetchCrewDetails(selectedCrewId);
        }
        
        if (jobId) {
            startPolling();
        }
    }
    
    function stopPolling() {
        if (pollingInterval) {
            clearInterval(pollingInterval);
            pollingInterval = null;
        }
    }

    // Helper to initialize sequence when crew changes
    // Removed previous effect as initialization is now handled in fetchCrewDetails


    // --- Drag and Drop Handlers ---

    function moveAgentInSequence(fromIndex, toIndex) {
        if (fromIndex === toIndex || fromIndex < 0 || toIndex < 0) return;
        const updated = [...loopAgentSequence];
        if (fromIndex >= updated.length) return;
        const [moved] = updated.splice(fromIndex, 1);
        const clampedIndex = Math.min(Math.max(toIndex, 0), updated.length);
        updated.splice(clampedIndex, 0, moved);
        loopAgentSequence = updated;
    }

    function handleDragStart(event, index) {
        draggingIndex = index;
        if (event.dataTransfer) {
            event.dataTransfer.effectAllowed = 'move';
            event.dataTransfer.setData('text/plain', index.toString());
        }
    }

    function handleDragOver(event) {
        event.preventDefault();
        if (event.dataTransfer) event.dataTransfer.dropEffect = 'move';
    }

    function handleDrop(event, index) {
        event.preventDefault();
        const data = event.dataTransfer?.getData('text/plain');
        const fromIndex = draggingIndex ?? (data ? parseInt(data, 10) : -1);
        if (Number.isNaN(fromIndex) || fromIndex < 0) {
            draggingIndex = null;
            return;
        }
        moveAgentInSequence(fromIndex, index);
        draggingIndex = null;
    }

    function handleDragEnd() {
        draggingIndex = null;
    }
    
    function getAgentName(agentId) {
        // Try to find in full details first, then fall back to initial prop
        const agentFromDetails = crewDetails?.agents?.find(a => a.agent_id === agentId);
        if (agentFromDetails) return agentFromDetails.name;

        return crew?.agents?.find(a => a.agent_id === agentId)?.name || agentId;
    }

    // --- STEP 1: Start Execution ---

    async function handleStartExecution() {
        if (!question.trim()) {
            jobError = "Please describe the business problem.";
            return;
        }
        
        isSubmitting = true;
        jobError = '';
        console.log("[Wizard] handleStartExecution started. Mode:", currentMode);
        
        try {
            console.log("[Wizard] Executing crew:", selectedCrewId);
            const options = {
                execution_mode: currentMode,
                generate_summary: generateSummary
            };
            
            // Add Loop/Sequence Params
            if (currentMode === 'loop') {
                 if (!loopCondition.trim()) {
                    jobError = "Please provide a stopping condition for the loop.";
                    isSubmitting = false;
                    return;
                }
                const kwargs = {
                    condition: loopCondition,
                    max_iterations: parseInt(loopMaxIterations.toString()) || 4,
                    agent_sequence: loopAgentSequence
                };
                options.kwargs = kwargs;
            } else if (currentMode === 'sequential') {
                if (loopAgentSequence.length > 0) {
                     options.kwargs = { agent_sequence: loopAgentSequence };
                }
            }
            
            const execution = await crewApi.executeCrew(selectedCrewId, question, options);
            console.log("[Wizard] API Execution Response:", execution);
            
            if (execution && execution.job_id) {
                console.log("[Wizard] Successfully obtained Job ID:", execution.job_id);
                // First set jobId, then move to step 2
                jobId = execution.job_id;
                
                // Small delay to ensure state update propagates if needed
                setTimeout(() => {
                    console.log("[Wizard] Transitioning to Step 2");
                    currentStep = 2;
                }, 100);
            } else {
                console.error("[Wizard] No job_id in response");
                throw new Error("Failed to start crew: No Job ID returned");
            }
        } catch (e) {
            console.error("[Wizard] Execution error:", e);
            jobError = e.message || "Failed to start execution";
        } finally {
            isSubmitting = false;
        }
    }

    // --- STEP 2: Polling & Monitoring ---

    $effect(() => {
        // Automatically start polling when we have a jobId and are in Step 2
        if (showModal && jobId && currentStep === 2 && !pollingInterval) {
            console.log("[Wizard] Starting polling effect for Job:", jobId);
            startPolling();
        }
    });

    function startPolling() {
        stopPolling(); // Safety
        pollStatus(); // Immediate first poll
        pollingInterval = setInterval(pollStatus, 3000); 
    }

    async function pollStatus() {
        if (!jobId || !selectedCrewId) {
            console.log("[Wizard] Polling skipped: jobId or selectedCrewId missing", { jobId, selectedCrewId });
            return;
        }
        
        try {
            // 1. Get Job Status (Overall)
            const status = await crewApi.getJobStatus(jobId);
            jobStatus = status;
            console.log("[Wizard] Polled Job status:", status.status);
            
            // 2. Get Agent Statuses
            try {
                const statuses = await crewApi.getAgentStatuses(jobId, selectedCrewId);
                console.log("[Wizard] Polled Agent statuses count:", statuses?.length || 0);
                if (Array.isArray(statuses)) {
                    agentStatuses = statuses;
                    
                    // If we have agents but none selected, select the first one working or finished
                    if (!selectedAgentId && statuses.length > 0) {
                        const active = statuses.find(s => s.status === 'working') || statuses.find(s => s.status === 'finished');
                        if (active) selectedAgentId = active.agent_id;
                    }
                }
            } catch (agentErr) {
               console.warn("[Wizard] Failed to fetch agent statuses", agentErr);
            }
            
            // Check for completion
            if (status.status === 'completed' || status.status === 'failed') {
                console.log("[Wizard] Job reached terminal state:", status.status);
                stopPolling();
                
                if (status.status === 'completed') {
                    finalResult = status.result;
                    // Move to results after a short delay for UX
                    setTimeout(() => {
                        if (currentStep === 2) currentStep = 3;
                    }, 1500);
                } else {
                    jobError = status.error || "Job failed during execution.";
                }
            }
        } catch (pollErr) {
            console.error("[Wizard] Polling error:", pollErr);
            // Don't stop polling on single error unless it's a 404 or similar.
            // But we might want to alert if it keeps failing.
        }
    }

    async function loadAgentResult(agentId) {
        if (!jobId) {
             console.warn("Cannot load agent result: Job ID is missing"); // Changed from error to warn
             return;
        }
        selectedAgentId = agentId;
        selectedAgentResult = null; // Clear prev
        
        try {
            const res = await crewApi.getAgentResult(jobId, selectedCrewId, agentId);
            selectedAgentResult = res;
            agentResults[agentId] = res; // cache
        } catch (e) {
            console.error("Error fetching agent result", e);
            // Check if agent is actually working to show better message
            const currentStatus = agentStatuses.find(a => a.agent_id === agentId)?.status;
            if (currentStatus === 'working' || currentStatus === 'idle') {
                 // Not really an error, just not ready
                 selectedAgentResult = null; // Will trigger the "Agent is working..." view in template
            } else {
                 selectedAgentResult = { result: "⚠️ Unable to load result. The agent might have failed or returned empty output.", error: e.message };
            }
        }
    }
    
    // --- STEP 3: Results & Interaction ---
    
    async function handleAskQuestion() {
        if (!askQuestionText.trim()) return;
        
        try {
            const res = await crewApi.askCrew(jobId, selectedCrewId, askQuestionText);
            askQuestionResponse = res.response; // Assuming { response: "..." }
        } catch (e) {
            console.error(e);
            askQuestionResponse = "Error: " + e.message;
        }
    }
    
    async function handleGenerateSummary() {
        try {
            const res = await crewApi.summaryCrew(jobId, selectedCrewId, summaryMode, summaryPrompt);
             // Update final result display or show in a specific area?
             // User: "switch button with 'switch to full report'"
             // Maybe we update the right pane content
             if (res.summary) {
                 // For now, let's append or replace final result view?
                 // Or separate variable
                 summaryText = res.summary;
             }
        } catch (e) {
            console.error(e);
        }
    }
    
    async function handleExportPDF() {
        if (!finalResult && !summaryText) return;
        const content = summaryText || finalResult.summary || finalResult.output;
        const printWindow = window.open('', '_blank');
        if (printWindow) {
             printWindow.document.write(`
                <html>
                    <head>
                        <title>Report - ${crew?.name || 'Crew Execution'}</title>
                        <style>
                            body { font-family: sans-serif; line-height: 1.6; padding: 2rem; max-width: 800px; margin: 0 auto; color: #1f2937; }
                            h1, h2, h3, h4 { color: #111827; }
                            .prose { max-width: 100%; }
                            pre { background: #f3f4f6; padding: 1rem; border-radius: 0.5rem; overflow-x: auto; }
                            code { font-family: monospace; }
                        </style>
                    </head>
                    <body>
                        <h1>${crew?.name || 'Crew Execution Report'}</h1>
                        <div class="prose">
                            ${markdownToHtml(content)}
                        </div>
                        <script>
                            window.onload = () => { window.print(); window.close(); }
                        <\/script>
                    </body>
                </html>
            `);
            printWindow.document.close();
        }
    }

    async function copyToClipboard(text) {
        if (!text) return;
        try {
            await navigator.clipboard.writeText(text);
            copied = true;
            setTimeout(() => copied = false, 2000);
        } catch (e) {
            console.error(e);
        }
    }

    function close() {
        onClose();
    }

    let activeTab = 'summary'; // 'summary', 'agents', 'full_log', 'metadata'

</script>

{#if showModal}
<div class="fixed inset-0 z-50 flex items-center justify-center bg-black/60 backdrop-blur-sm p-4" transition:fade>
    <div class="flex h-[90vh] w-[95vw] max-w-7xl flex-col overflow-hidden rounded-2xl bg-white shadow-2xl dark:bg-gray-900" 
         role="dialog" 
         aria-modal="true">
         
        <!-- Header -->
        <div class="flex items-center justify-between border-b border-gray-200 bg-gray-50 px-6 py-4 dark:border-gray-800 dark:bg-gray-800/50">
            <div>
                <h2 class="text-xl font-bold text-gray-900 dark:text-white">
                    {#if crew}
                        {crew.name || 'Crew Execution'}
                        <span class="ml-2 rounded bg-green-100 px-2 py-0.5 text-xs font-medium text-green-800 dark:bg-green-900/30 dark:text-green-400">
                             {currentStep === 1 ? 'Configure' : currentStep === 2 ? 'Running' : 'Results'}
                        </span>
                    {:else}
                        Crew Execution
                    {/if}
                </h2>
                <div class="mt-1 flex items-center gap-2 text-sm text-gray-500 dark:text-gray-400">
                    {#if jobId}
                    <span class="font-mono text-xs opacity-70">Job ID: {jobId}</span>
                    {/if}
                </div>
            </div>
            
            <button 
                onclick={close}
                class="rounded-lg p-2 text-gray-500 hover:bg-gray-200 hover:text-gray-700 dark:text-gray-400 dark:hover:bg-gray-800 dark:hover:text-gray-200 transition-colors">
                <svg class="h-6 w-6" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                    <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M6 18L18 6M6 6l12 12" />
                </svg>
            </button>
        </div>

        <!-- Content Area -->
        <div class="flex-1 overflow-hidden relative">
            
            <!-- STEP 1: CONFIGURATION -->
            {#if currentStep === 1}
            <div class="flex h-full flex-col p-8 max-w-4xl mx-auto" transition:fade>
                <div class="text-center mb-10">
                    <h3 class="text-3xl font-bold text-gray-900 dark:text-white mb-4">What problem should I solve?</h3>
                </div>
                
                <div class="space-y-6 flex-1">
                    <!-- Question Input -->
                    <div class="relative group">
                        <textarea
                            bind:value={question}
                            class="w-full rounded-2xl border-gray-200 bg-gray-50 p-6 text-lg shadow-sm transition-all focus:border-green-500 focus:bg-white focus:ring-green-500 dark:border-gray-700 dark:bg-gray-800 dark:text-white dark:focus:bg-gray-900 min-h-[160px] resize-none"
                            placeholder="Describe a business problem..."
                            disabled={isSubmitting}
                        ></textarea>
                        
                         <!-- Quick Actions Bar inside textarea or below? User requested "inside text area" style implies overlay or integrated -->
                         <div class="absolute bottom-4 left-4 flex gap-2">
                             <!-- Markdown/Formatting tools could go here -->
                         </div>

                         
                         <div class="absolute bottom-4 right-4">
                            <button
                               type="button"
                               onclick={handleStartExecution}
                               disabled={isSubmitting || !question.trim()}
                               class="inline-flex items-center gap-2 rounded-xl bg-green-600 px-6 py-2 font-semibold text-white shadow-lg shadow-green-600/20 transition-all hover:bg-green-500 hover:shadow-xl hover:-translate-y-0.5 disabled:opacity-50 disabled:cursor-not-allowed disabled:hover:translate-y-0"
                            >
                                {#if isSubmitting}
                                    <svg class="animate-spin h-5 w-5 text-white" xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24">
                                        <circle class="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" stroke-width="4"></circle>
                                        <path class="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4zm2 5.291A7.962 7.962 0 014 12H0c0 3.042 1.135 5.824 3 7.938l3-2.647z"></path>
                                    </svg>
                                    Starting...
                                {:else}
                                    Run <span aria-hidden="true">&rarr;</span>
                                {/if}
                             </button>
                         </div>

                         <!-- Generate Summary Option -->
                         <div class="absolute bottom-4 left-4 flex gap-5">
                             <div class="flex items-center">
                                 <input 
                                    id="generate_summary" 
                                    type="checkbox" 
                                    bind:checked={generateSummary}
                                    class="h-4 w-4 rounded border-gray-300 text-green-600 focus:ring-green-500 dark:border-gray-600 dark:bg-gray-700 dark:ring-offset-gray-800"
                                 >
                                 <label for="generate_summary" class="ml-2 text-sm text-gray-700 dark:text-gray-300 select-none cursor-pointer">
                                     Generate Synthesis
                                 </label>
                             </div>
                         </div>
                    </div>
                    
                    <!-- Mode Selection Cards (Row) -->
                    <div class="grid grid-cols-2 gap-4 md:grid-cols-4 mt-8">
                         {#each Object.entries(executionModeMeta) as [mode, meta]}
                            <label class="cursor-pointer relative">
                                <input type="radio" class="peer sr-only" bind:group={currentMode} value={mode} />
                                <div class="h-full rounded-xl border-2 border-transparent bg-gray-50 p-4 transition-all hover:bg-gray-100 peer-checked:border-green-500 peer-checked:bg-green-50/50 dark:bg-gray-800 dark:hover:bg-gray-750 dark:peer-checked:bg-green-900/20">
                                    <div class="font-semibold text-gray-900 dark:text-white mb-1">{meta.label}</div>
                                    <div class="text-xs text-gray-500 dark:text-gray-400 leading-relaxed">{meta.description}</div>
                                </div>
                            </label>
                         {/each}
                    </div>

                    <!-- LOOP CONFIGURATION -->
                    {#if currentMode === 'loop'}
                    <div class="mt-6 p-6 rounded-xl bg-gray-50 border border-gray-200 dark:bg-gray-800 dark:border-gray-700" transition:slide>
                        <h4 class="text-sm font-bold uppercase tracking-wider text-gray-500 dark:text-gray-400 mb-4">Loop Configuration</h4>
                        <div class="grid grid-cols-1 md:grid-cols-2 gap-4">
                            <div>
                                <label for="loop-condition" class="block text-sm font-medium text-gray-700 dark:text-gray-300 mb-2">Stopping Condition</label>
                                <input 
                                    id="loop-condition"
                                    type="text" 
                                    bind:value={loopCondition}
                                    placeholder="e.g. Stop when the report is approved"
                                    class="w-full rounded-lg border-gray-300 bg-white px-3 py-2 text-sm shadow-sm focus:border-green-500 focus:ring-green-500 dark:border-gray-600 dark:bg-gray-700 dark:text-white"
                                >
                            </div>
                            <div>
                                <label for="loop-max-iterations" class="block text-sm font-medium text-gray-700 dark:text-gray-300 mb-2">Max Iterations</label>
                                <input 
                                    id="loop-max-iterations"
                                    type="number" 
                                    min="1" 
                                    max="50"
                                    bind:value={loopMaxIterations}
                                    class="w-full rounded-lg border-gray-300 bg-white px-3 py-2 text-sm shadow-sm focus:border-green-500 focus:ring-green-500 dark:border-gray-600 dark:bg-gray-700 dark:text-white"
                                >
                            </div>
                        </div>
                    </div>
                    {/if}

                    <!-- AGENT SEQUENCE (Shared for Loop & Sequential) -->
                    {#if currentMode === 'loop' || currentMode === 'sequential'}
                    <div class="mt-6" transition:slide>
                        <h4 class="text-sm font-bold uppercase tracking-wider text-gray-500 dark:text-gray-400 mb-4">
                            Agent Sequence 
                            <span class="text-[10px] normal-case font-normal text-gray-400 ml-2">(Drag to reorder)</span>
                        </h4>
                        
                        {#if loopAgentSequence.length > 0}
                            <div class="space-y-2 max-h-60 overflow-y-auto pr-2 custom-scrollbar">
                                {#each loopAgentSequence as agentId, index (agentId)}
                                    <div 
                                        role="listitem"
                                        draggable="true"
                                        ondragstart={(e) => handleDragStart(e, index)}
                                        ondragover={handleDragOver}
                                        ondrop={(e) => handleDrop(e, index)}
                                        ondragend={handleDragEnd}
                                        class="flex items-center gap-3 rounded-lg border border-gray-200 bg-white p-3 shadow-sm hover:border-green-400 transition-colors cursor-move dark:border-gray-700 dark:bg-gray-800 {draggingIndex === index ? 'opacity-50 border-dashed border-green-500' : ''}"
                                    >
                                        <div class="text-gray-400">
                                            <svg class="h-4 w-4" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                                                <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M4 8h16M4 16h16" />
                                            </svg>
                                        </div>
                                        <span class="inline-flex h-6 w-6 items-center justify-center rounded-full bg-gray-100 text-xs font-medium text-gray-600 dark:bg-gray-700 dark:text-gray-300">
                                            {index + 1}
                                        </span>
                                        <span class="font-medium text-gray-700 dark:text-gray-200">
                                            {getAgentName(agentId)}
                                        </span>
                                    </div>
                                {/each}
                            </div>
                        {:else}
                            <p class="text-sm text-gray-500 italic">No agents found in this crew.</p>
                        {/if}
                    </div>
                    {/if}

                    {#if jobError}
                    <div class="mt-6 rounded-xl bg-red-50 p-4 text-red-600 dark:bg-red-900/20 dark:text-red-400">
                        {jobError}
                    </div>
                    {/if}
                </div>
            </div>
            {/if}
            
            <!-- STEP 2: EXECUTION -->
            {#if currentStep === 2}
            <div class="flex h-full w-full" transition:fade>
                <!-- Left Pane: Question context -->
                <div class="w-1/4 border-r border-gray-200 bg-gray-50 p-6 dark:border-gray-800 dark:bg-gray-900/50 overflow-y-auto">
                    <h3 class="text-xs font-bold uppercase tracking-wider text-gray-500 dark:text-gray-400 mb-4">Initial Request</h3>
                    <div class="prose prose-sm dark:prose-invert">
                         {@html markdownToHtml(question)}
                    </div>
                </div>
                
                <!-- Middle Pane: Agents Status (Grid) -->
                <div class="{selectedAgentId ? 'w-1/3' : 'w-3/4'} bg-white p-6 dark:bg-gray-900 overflow-y-auto transition-all duration-300">
                     <h3 class="text-xs font-bold uppercase tracking-wider text-gray-500 dark:text-gray-400 mb-6 flex justify-between items-center">
                        <span>Agents Working</span>
                        <div class="flex items-center gap-2">
                            <span class="inline-block h-2 w-2 rounded-full bg-green-500 animate-pulse"></span>
                            <span class="text-[10px]">Live</span>
                        </div>
                     </h3>
                     
                     <div class="grid grid-cols-1 gap-4">
                         {#if agentStatuses.length === 0}
                             <div class="p-8 text-center text-gray-400 border border-dashed border-gray-200 rounded-xl">
                                 <div class="flex justify-center mb-2">
                                     <svg class="h-6 w-6 animate-pulse" fill="none" viewBox="0 0 24 24" stroke="currentColor"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M5 12h.01M12 12h.01M19 12h.01M6 12a1 1 0 11-2 0 1 1 0 012 0zm7 0a1 1 0 11-2 0 1 1 0 012 0zm7 0a1 1 0 11-2 0 1 1 0 012 0z" /></svg>
                                 </div>
                                 <p class="text-sm">Connecting to agents...</p>
                                 {#if !selectedCrewId}
                                     <p class="text-xs text-red-400 mt-2">Error: No Crew ID selected.</p>
                                 {/if}
                                 {#if jobError}
                                     <p class="text-xs text-red-400 mt-2 font-medium bg-red-50 p-2 rounded border border-red-100 dark:bg-red-900/20 dark:border-red-800">
                                         {jobError}
                                     </p>
                                 {/if}
                             </div>
                         {:else}
                             {#each agentStatuses as agent (agent.agent_id)}
                                <button 
                                    onclick={() => loadAgentResult(agent.agent_id)}
                                    class="flex items-start gap-4 rounded-xl border p-4 text-left transition-all hover:shadow-md
                                    {selectedAgentId === agent.agent_id ? 'border-green-500 bg-green-50/10 ring-1 ring-green-500' : 'border-gray-200 bg-white hover:border-gray-300 dark:border-gray-700 dark:bg-gray-800 dark:hover:border-gray-600'}"
                                >
                                    <div class="mt-1 flex h-8 w-8 shrink-0 items-center justify-center rounded-lg 
                                        {agent.status === 'working' ? 'bg-blue-100 text-blue-600 dark:bg-blue-900/30 dark:text-blue-400' : 
                                         agent.status === 'finished' ? 'bg-green-100 text-green-600 dark:bg-green-900/30 dark:text-green-400' :
                                         'bg-gray-100 text-gray-400 dark:bg-gray-800 dark:text-gray-500'}">
                                         {#if agent.status === 'working'}
                                            <svg class="h-4 w-4 animate-spin" fill="none" viewBox="0 0 24 24"><circle class="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" stroke-width="4"></circle><path class="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4zm2 5.291A7.962 7.962 0 014 12H0c0 3.042 1.135 5.824 3 7.938l3-2.647z"></path></svg>
                                         {:else if agent.status === 'finished'}
                                            <svg class="h-4 w-4" fill="none" viewBox="0 0 24 24" stroke="currentColor"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M5 13l4 4L19 7" /></svg>
                                         {:else if agent.status === 'idle'}
                                            <svg class="h-3 w-3" fill="currentColor" viewBox="0 0 24 24"><circle cx="12" cy="12" r="6" /></svg>
                                         {:else}
                                            <span class="text-xs font-bold">{agent.status?.[0]?.toUpperCase()}</span>
                                         {/if}
                                    </div>
                                    <div class="flex-1 min-w-0">
                                        <div class="flex items-center justify-between">
                                            <p class="font-medium text-gray-900 dark:text-white truncate">{agent.agent_name}</p>
                                            <span class="text-[10px] font-mono uppercase text-gray-400">{agent.status}</span>
                                        </div>
                                        <p class="mt-1 text-sm text-gray-500 dark:text-gray-400 line-clamp-2">
                                            {agent.task || 'Waiting for task...'}
                                        </p>
                                    </div>
                                </button>
                             {/each}
                         {/if}
                     </div>
                </div>
                
                <!-- Right Pane: Live Agent Result -->
                {#if selectedAgentId}
                <div class="w-5/12 border-l border-gray-200 bg-white p-0 flex flex-col dark:border-gray-800 dark:bg-gray-900" transition:slide={{axis: 'x', duration: 300}}>
                    <div class="flex items-center justify-between border-b border-gray-100 p-4 dark:border-gray-800">
                        <h4 class="font-medium text-gray-900 dark:text-white">
                             Output: {agentStatuses.find(a => a.agent_id === selectedAgentId)?.agent_name}
                        </h4>
                        <div class="flex items-center gap-2">
                            {#if copied}
                                <span class="text-xs font-semibold text-green-600 dark:text-green-400 animate-pulse">Copied!</span>
                            {/if}
                            <button onclick={() => copyToClipboard(selectedAgentResult?.result || '')} class="p-1.5 text-gray-400 hover:text-gray-600 rounded-lg hover:bg-gray-100 dark:hover:bg-gray-800 transition-colors" title="Copy Output">
                                <svg class="h-5 w-5" fill="none" viewBox="0 0 24 24" stroke="currentColor"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M8 16H6a2 2 0 01-2-2V6a2 2 0 012-2h8a2 2 0 012 2v2m-6 12h8a2 2 0 002-2v-8a2 2 0 00-2-2h-8a2 2 0 00-2 2v8a2 2 0 002 2z" /></svg>
                            </button>
                            <button onclick={() => selectedAgentId = null} class="p-1.5 text-gray-400 hover:text-gray-600 rounded-lg hover:bg-gray-100 dark:hover:bg-gray-800 transition-colors">
                                <svg class="h-5 w-5" fill="none" viewBox="0 0 24 24" stroke="currentColor"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M6 18L18 6M6 6l12 12" /></svg>
                            </button>
                        </div>
                    </div>
                    <div class="flex-1 overflow-y-auto p-4">
                        {#if selectedAgentResult}
                            {#if selectedAgentResult.result}
                                <div class="prose prose-sm dark:prose-invert max-w-none">
                                    {@html markdownToHtml(selectedAgentResult.result)}
                                </div>
                            {:else}
                                <div class="flex h-full items-center justify-center text-gray-400 flex-col gap-2">
                                    {#if agentStatuses.find(a => a.agent_id === selectedAgentId)?.status === 'working'}
                                        <svg class="h-6 w-6 animate-spin text-green-500" fill="none" viewBox="0 0 24 24"><circle class="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" stroke-width="4"></circle><path class="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4zm2 5.291A7.962 7.962 0 014 12H0c0 3.042 1.135 5.824 3 7.938l3-2.647z"></path></svg>
                                        <p class="text-center text-sm">Here you can see the Agent's result.<br>Be patient, I am still working...</p>
                                    {:else}
                                        <p>No result available.</p>
                                    {/if}
                                </div>
                            {/if}
                        {:else}
                            <div class="flex h-full items-center justify-center">
                                <div class="h-6 w-6 animate-spin rounded-full border-2 border-green-500 border-t-transparent"></div>
                            </div>
                        {/if}
                    </div>
                </div>
                {/if}
            </div>
            {/if}

            <!-- STEP 3: RESULTS & SYNTHESIS -->
            {#if currentStep === 3}
            <div class="flex h-full w-full" transition:fade>
                 <!-- Left Pane: Interaction & Close -->
                 <div class="w-1/3 border-r border-gray-200 bg-gray-50 flex flex-col dark:border-gray-800 dark:bg-gray-900/50 relative">
                    <div class="flex-1 overflow-y-auto p-6 space-y-8 pb-20">
                         <!-- Rationale/Summary Section -->
                         <div>
                             <h3 class="mb-3 text-xs font-bold uppercase tracking-wider text-gray-500 dark:text-gray-400">Project Summary</h3>
                             <div class="rounded-xl bg-white p-4 shadow-sm dark:bg-gray-800 border border-gray-200 dark:border-gray-700">
                                 <label class="block text-sm font-medium text-gray-700 dark:text-gray-300 mb-2">Generate Report</label>
                                 <textarea
                                     bind:value={summaryPrompt}
                                     placeholder="Instructions for the final report..."
                                     class="w-full text-sm rounded-lg border-gray-300 dark:bg-gray-900 dark:border-gray-700 mb-3 focus:ring-green-500 focus:border-green-500"
                                     rows="6"
                                 ></textarea>
                                 <div class="flex justify-between items-center">
                                      <select bind:value={summaryMode} class="text-xs rounded border-gray-300 dark:bg-gray-900 dark:border-gray-700 py-1">
                                          <option value="executive_summary">Executive Summary</option>
                                          <option value="full_report">Full Report</option>
                                      </select>
                                      <button onclick={handleGenerateSummary} class="text-xs bg-green-100 text-green-700 px-3 py-1.5 rounded-lg hover:bg-green-200 font-medium">
                                          Generate
                                      </button>
                                 </div>
                             </div>
                         </div>
                         
                         <!-- Ask Question Section -->
                         <div>
                             <h3 class="mb-3 text-xs font-bold uppercase tracking-wider text-gray-500 dark:text-gray-400">Do a question to the crew</h3>
                              <div class="bg-white rounded-xl shadow-sm border border-gray-200 dark:bg-gray-800 dark:border-gray-700 overflow-hidden">
                                  {#if askQuestionResponse}
                                  <div class="p-4 bg-blue-50/50 dark:bg-blue-900/20 border-b border-blue-100 dark:border-blue-900/30 text-sm">
                                      <p class="font-semibold text-blue-800 dark:text-blue-300 mb-1">Answer:</p>
                                      <div class="prose prose-sm prose-blue dark:prose-invert max-w-none">
                                          {@html markdownToHtml(askQuestionResponse)}
                                      </div>
                                  </div>
                                  {/if}
                                  <div class="p-4">
                                     <textarea
                                         bind:value={askQuestionText}
                                         placeholder="Ask a follow-up question..."
                                         class="w-full text-sm rounded-lg border-gray-300 dark:bg-gray-900 dark:border-gray-700 mb-3 focus:ring-green-500 focus:border-green-500"
                                         rows="5"
                                     ></textarea>
                                      <div class="flex justify-end">
                                          <button onclick={handleAskQuestion} class="px-4 py-2 bg-gray-900 text-white text-sm rounded-lg hover:bg-gray-800 dark:bg-white dark:text-gray-900">
                                              Ask Question
                                          </button>
                                      </div>
                                  </div>
                              </div>
                         </div>
                    </div>
                    
                    <!-- Close Button Area (Bottom of Left Pane) -->
                    <div class="absolute bottom-0 left-0 right-0 p-6 bg-gradient-to-t from-gray-50 via-gray-50 to-transparent dark:from-gray-900 dark:via-gray-900">
                         <button onclick={onClose} class="w-full flex justify-center items-center gap-2 px-4 py-3 bg-gray-200 text-gray-800 rounded-xl hover:bg-gray-300 font-bold dark:bg-gray-700 dark:text-gray-200 dark:hover:bg-gray-600 shadow-sm">
                             <svg class="h-5 w-5" fill="none" viewBox="0 0 24 24" stroke="currentColor"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M6 18L18 6M6 6l12 12" /></svg>
                             Close Wizard
                         </button>
                    </div>
                 </div>
                 
                 <!-- Right Pane: Final Output & Tabs -->
                 <div class="w-2/3 bg-white flex flex-col h-full dark:bg-gray-900">
                     <div class="flex items-center justify-between border-b border-gray-100 px-6 py-4 dark:border-gray-800">
                         <h3 class="font-bold text-gray-900 dark:text-white">Final Output</h3>
                         <div class="flex gap-2 items-center">
                             {#if copied}
                               <span class="text-xs font-semibold text-green-600 dark:text-green-400 animate-fade-out mr-2">Copied!</span>
                             {/if}
                             <button onclick={() => copyToClipboard(summaryText || finalResult?.output || '')} class="p-2 text-gray-500 hover:text-gray-700 rounded-lg hover:bg-gray-100" title="Copy">
                                 <svg class="h-5 w-5" fill="none" viewBox="0 0 24 24" stroke="currentColor"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M8 16H6a2 2 0 01-2-2V6a2 2 0 012-2h8a2 2 0 012 2v2m-6 12h8a2 2 0 002-2v-8a2 2 0 00-2-2h-8a2 2 0 00-2 2v8a2 2 0 002 2z" /></svg>
                             </button>
                             <button onclick={handleExportPDF} class="flex items-center gap-2 px-3 py-1.5 text-sm font-medium text-gray-700 bg-gray-100 rounded-lg hover:bg-gray-200 dark:bg-gray-800 dark:text-gray-300">
                                 <svg class="h-4 w-4" fill="none" viewBox="0 0 24 24" stroke="currentColor"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M4 16v1a3 3 0 003 3h10a3 3 0 003-3v-1m-4-4l-4 4m0 0l-4-4m4 4V4" /></svg>
                                 Export PDF
                             </button>
                         </div>
                     </div>
                     
                     <!-- Tabs Header -->
                     <div class="flex items-center gap-1 px-6 border-b border-gray-100 dark:border-gray-800 bg-gray-50/50 dark:bg-gray-800/20">
                          <button class="px-4 py-3 text-sm font-medium border-b-2 transition-colors {resultsTab === 'summary' ? 'border-green-500 text-green-600 dark:text-green-400' : 'border-transparent text-gray-500 hover:text-gray-700 dark:text-gray-400'}"
                                  onclick={() => resultsTab = 'summary'}>
                              Summary
                          </button>
                          <button class="px-4 py-3 text-sm font-medium border-b-2 transition-colors {resultsTab === 'agents' ? 'border-green-500 text-green-600 dark:text-green-400' : 'border-transparent text-gray-500 hover:text-gray-700 dark:text-gray-400'}"
                                  onclick={() => resultsTab = 'agents'}>
                              Agent Results
                          </button>
                          <button class="px-4 py-3 text-sm font-medium border-b-2 transition-colors {resultsTab === 'metadata' ? 'border-green-500 text-green-600 dark:text-green-400' : 'border-transparent text-gray-500 hover:text-gray-700 dark:text-gray-400'}"
                                  onclick={() => resultsTab = 'metadata'}>
                              Metadata
                          </button>
                          <button class="px-4 py-3 text-sm font-medium border-b-2 transition-colors {resultsTab === 'full' ? 'border-green-500 text-green-600 dark:text-green-400' : 'border-transparent text-gray-500 hover:text-gray-700 dark:text-gray-400'}"
                                  onclick={() => resultsTab = 'full'}>
                              Full Log
                          </button>
                     </div>

                     <div class="flex-1 overflow-y-auto p-8 pt-6 relative">
                         <div class="prose prose-lg dark:prose-invert max-w-4xl mx-auto pb-16">
                             {#if resultsTab === 'summary'}
                                 {#if summaryText || finalResult?.summary}
                                     <div class="mb-8 p-6 bg-slate-50 dark:bg-slate-800/50 rounded-xl border border-slate-200 dark:border-slate-700">
                                         <h4 class="text-sm font-bold uppercase tracking-wider text-slate-500 mb-4">Executive Summary</h4>
                                         {@html markdownToHtml(summaryText || finalResult.summary)}
                                     </div>
                                 {:else}
                                     <div class="text-center py-12 text-gray-400 bg-gray-50 rounded-xl border border-dashed border-gray-200">
                                         <p>No summary generated. Use the "Generate Synthesis" option.</p>
                                     </div>
                                 {/if}
                             {:else if resultsTab === 'agents'}
                                 {#if agentStatuses && agentStatuses.length > 0}
                                     <div class="space-y-6">
                                         {#each agentStatuses as agentResult}
                                             <div class="rounded-xl border border-gray-200 dark:border-gray-700 overflow-hidden shadow-sm">
                                                 <div class="bg-gray-50 px-4 py-3 border-b border-gray-200 dark:bg-gray-800 dark:border-gray-700 flex justify-between items-center">
                                                     <h4 class="font-bold text-sm text-gray-700 dark:text-gray-200">{agentResult.agent_name || agentResult.agent_id || 'Agent'}</h4>
                                                     <div class="flex gap-2 items-center">
                                                         <span class="text-xs uppercase tracking-wider text-gray-500 font-mono">{agentResult.status || 'Unknown'}</span>
                                                     </div>
                                                 </div>
                                                 <div class="p-5 bg-white dark:bg-gray-900 prose prose-sm dark:prose-invert max-w-none">
                                                     {@html markdownToHtml(agentResult.result || '')}
                                                     {#if !agentResult.result && agentResult.error}
                                                         <div class="text-red-500 font-mono text-xs">{agentResult.error}</div>
                                                     {:else if !agentResult.result}
                                                          <div class="text-gray-400 italic">No output content</div>
                                                     {/if}
                                                 </div>
                                             </div>
                                         {/each}
                                     </div>
                                 {:else}
                                      <div class="text-center py-12 text-gray-400">
                                         <p>No individual agent results available.</p>
                                      </div>
                                 {/if}
                             {:else if resultsTab === 'metadata'}
                                 <div class="bg-slate-50 dark:bg-slate-900 rounded-lg font-mono text-xs whitespace-pre-wrap text-gray-700 dark:text-gray-300 border border-slate-200 dark:border-slate-800 p-4">
                                     {JSON.stringify(finalResult?.metadata || {}, null, 2)}
                                 </div>
                             {:else if resultsTab === 'full'}
                                 {#if finalResult?.output || finalResult?.execution_log}
                                     <div class="p-4 bg-slate-50 dark:bg-slate-900 rounded-lg font-mono text-xs whitespace-pre-wrap text-gray-700 dark:text-gray-300 border border-slate-200 dark:border-slate-800">
                                         {typeof finalResult?.output === 'string' ? finalResult.output : JSON.stringify(finalResult?.execution_log || finalResult, null, 2)}
                                     </div>
                                 {:else}
                                     <p class="text-gray-500 italic">No output log available.</p>
                                 {/if}
                             {/if}
                         
                            
                         </div>
                     </div>
                 </div>
            </div>
            {/if}
            
        </div>
    </div>
</div>
{/if}
