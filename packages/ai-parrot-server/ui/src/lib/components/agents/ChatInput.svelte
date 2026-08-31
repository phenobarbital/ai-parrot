<script lang="ts">
  import { tick } from "svelte";
  import { browser } from "$app/environment";
  import MarkdownEditorToolbar from "./MarkdownEditorToolbar.svelte";
  import {
    VoiceRecorder,
    isVoiceRecordingSupported,
    type RecordedVoiceNote,
  } from "$lib/utils/voice-recorder";
  let {
    onSend,
    isLoading,
    text = $bindable(""),
    followupTurnId = null,
    onClearFollowup,
    recentQuestions = [],
    allow_custom_llm = false, // Default to false
    hideOutputMode = false, // Hide output_mode select in bot mode
    streamEnabled = false, // NEW — streaming toggle state
    onToggleStream, // NEW — callback when toggle changes
    isStreaming = false, // NEW — true while stream is active
    onStopStream, // NEW — callback to abort stream
    enterToSend = false, // When true, plain Enter sends and Shift+Enter inserts a newline
    placeholder = "Ask a question…", // Base placeholder; keyboard hint is appended automatically
    enableVoiceInput = false, // When true, show the mic button for voice notes
    onSendVoiceNote, // Callback fired with the recorded voice note
    showAdvancedOptions = false,
  } = $props<{
    onSend: (
      text: string,
      methodName?: string,
      outputMode?: string,
      llm?: string,
      kwargs?: Record<string, string>,
    ) => void;
    isLoading: boolean;
    text?: string;
    followupTurnId?: string | null;
    onClearFollowup?: () => void;
    recentQuestions?: string[];
    allow_custom_llm?: boolean; // New prop for custom LLM
    hideOutputMode?: boolean; // Hide output_mode select in bot mode
    streamEnabled?: boolean; // NEW — current toggle state
    onToggleStream?: () => void; // NEW — callback when toggle changes
    isStreaming?: boolean; // NEW — true while stream is active
    onStopStream?: () => void; // NEW — callback to abort stream
    /** When true, plain Enter submits and Shift+Enter inserts a newline.
     *  Default (false) preserves Shift+Enter-to-send for AgentChat. */
    enterToSend?: boolean;
    /** Base placeholder text. A keyboard hint derived from `enterToSend` is
     *  appended automatically (e.g. " (Enter to send)"). */
    placeholder?: string;
    /** When true, a microphone button is shown to record/send a voice note.
     *  Defaults to false — voice notes are opt-in per AgentChat config. */
    enableVoiceInput?: boolean;
    /** Invoked with the recorded note when the user finishes a voice recording. */
    onSendVoiceNote?: (note: RecordedVoiceNote) => void;
    showAdvancedOptions?: boolean;
  }>();

  // ── Voice note recording state ──
  let recorder: VoiceRecorder | null = null;
  let isRecording = $state(false);
  let recordSeconds = $state(0);
  let recordError = $state<string | null>(null);
  let recordTimer: ReturnType<typeof setInterval> | null = null;
  const voiceSupported = browser && isVoiceRecordingSupported();

  function formatSeconds(s: number): string {
    const m = Math.floor(s / 60);
    const sec = s % 60;
    return `${m}:${sec.toString().padStart(2, "0")}`;
  }

  async function startRecording() {
    if (isRecording || isStreaming) return;
    recordError = null;
    recorder = new VoiceRecorder();
    try {
      await recorder.start();
      isRecording = true;
      recordSeconds = 0;
      recordTimer = setInterval(() => (recordSeconds += 1), 1000);
    } catch (e) {
      recorder = null;
      recordError =
        e instanceof DOMException && e.name === "NotAllowedError"
          ? "Microphone permission denied."
          : "Could not start recording.";
    }
  }

  function stopRecordTimer() {
    if (recordTimer) {
      clearInterval(recordTimer);
      recordTimer = null;
    }
  }

  async function stopRecording() {
    if (!recorder || !isRecording) return;
    stopRecordTimer();
    isRecording = false;
    try {
      const note = await recorder.stop();
      if (note.blob.size > 0) onSendVoiceNote?.(note);
    } catch (e) {
      recordError = "Recording failed.";
    } finally {
      recorder = null;
    }
  }

  function cancelRecording() {
    stopRecordTimer();
    isRecording = false;
    recorder?.cancel();
    recorder = null;
  }

  let outputMode = $state("default");
  let selectedLLM = $state(""); // Empty = use agent default LLM
  let showHistory = $state(false);
  let showMarkdownToolbar = $state(false);
  let isExpanded = $state(false);
  let textarea: HTMLTextAreaElement;

  // ── Advanced Options state ──
  let advancedOpen = $state(false);
  let customMethodName = $state("");
  let kwargEntries = $state<{ key: string; value: string }[]>([]);

  function addKwargEntry() {
    kwargEntries = [...kwargEntries, { key: "", value: "" }];
  }

  function removeKwargEntry(index: number) {
    kwargEntries = kwargEntries.filter((_, i) => i !== index);
  }

  function buildKwargs(): Record<string, string> | undefined {
    const result: Record<string, string> = {};
    let hasEntries = false;
    for (const entry of kwargEntries) {
      const k = entry.key.trim();
      if (k && entry.value.trim()) {
        result[k] = entry.value.trim();
        hasEntries = true;
      }
    }
    return hasEntries ? result : undefined;
  }

  // Collapsed cap: min(30% viewport, 160px) — tight Gemini-style anchor, ~6 lines.
  // Expanded cap:  min(60% viewport, 450px) — ample editing space, sane on large screens.
  // The absolute pixel caps prevent absurd heights on 1440p/4K monitors.
  function getMaxHeight(): number {
    if (!browser) return 160;
    if (isExpanded) {
      return Math.min(Math.floor(window.innerHeight * 0.6), 450);
    }
    return Math.min(Math.floor(window.innerHeight * 0.3), 160);
  }

  // Re-run autoResize with smooth transition whenever expand state toggles.
  $effect(() => {
    const _expanded = isExpanded; // reactive dependency
    if (!textarea) return;
    textarea.style.transition = "height 0.18s ease";
    tick().then(() => {
      autoResize();
      setTimeout(() => {
        if (textarea) textarea.style.transition = "";
      }, 200);
    });
  });

  // Recompute height cap whenever the browser window is resized.
  $effect(() => {
    if (!browser) return;
    const onResize = () => autoResize();
    window.addEventListener("resize", onResize, { passive: true });
    return () => window.removeEventListener("resize", onResize);
  });

  const outputModes = [
    { value: "default", label: "Default (Auto)" },
    { value: "echarts", label: "ECharts" },
    { value: "structured_chart", label: "Chart" },
    { value: "structured_map", label: "Map" },
    { value: "structured_table", label: "Table" },
    { value: "interactive", label: "Interactive" },
  ];

  // Supported LLM models (from backend enums: GoogleModel, OpenAIModel, ClaudeModel, GroqModel, GrokModel)
  const supportedModels = [
    { value: "", label: "Default Model" },
    // Google
    { value: "google:gemini-2.5-flash", label: "Gemini 2.5 Flash" },
    { value: "google:gemini-2.5-pro", label: "Gemini 2.5 Pro" },
    { value: "google:gemini-3-flash-preview", label: "Gemini 3 Flash" },
    { value: "google:gemini-3-pro-preview", label: "Gemini 3 Pro" },
    // OpenAI
    { value: "openai:gpt-4.1", label: "GPT 4.1" },
    { value: "openai:gpt-4.1-mini", label: "GPT 4.1 Mini" },
    { value: "openai:gpt-5", label: "GPT 5" },
    { value: "openai:gpt-5-mini", label: "GPT 5 Mini" },
    { value: "openai:o3", label: "o3" },
    { value: "openai:o3-mini", label: "o3 Mini" },
    { value: "openai:o4-mini", label: "o4 Mini" },
    // Anthropic
    {
      value: "anthropic:claude-sonnet-4-5-20250929",
      label: "Claude Sonnet 4.5",
    },
    { value: "anthropic:claude-opus-4-5-20251101", label: "Claude Opus 4.5" },
    { value: "anthropic:claude-opus-4-6", label: "Claude Opus 4.6" },
    { value: "anthropic:claude-haiku-4-5-20251001", label: "Claude Haiku 4.5" },
    // Groq
    { value: "groq:llama-3.3-70b-versatile", label: "Llama 3.3 70B (Groq)" },
    {
      value: "groq:meta-llama/llama-4-scout-17b-16e-instruct",
      label: "Llama 4 Scout (Groq)",
    },
    // xAI
    { value: "xai:grok-4", label: "Grok 4" },
  ];

  function handleKeydown(e: KeyboardEvent) {
    if (e.key !== "Enter") return;
    // Skip while the user is composing CJK/IME input — Enter there confirms the candidate.
    if (e.isComposing) return;
    if (enterToSend) {
      // Plain Enter submits; Shift+Enter (or Ctrl/Meta+Enter) inserts a newline.
      if (!e.shiftKey && !e.ctrlKey && !e.metaKey) {
        e.preventDefault();
        handleSubmit();
      }
    } else {
      // Shift+Enter submits; plain Enter inserts a newline.
      if (e.shiftKey) {
        e.preventDefault();
        handleSubmit();
      }
    }
  }

  function handleSubmit() {
    if (!text.trim()) return;
    const llm = selectedLLM ? selectedLLM : undefined;
    const method = customMethodName.trim() || undefined;
    const kwargs = buildKwargs();
    onSend(
      text,
      method,
      outputMode !== "default" ? outputMode : undefined,
      llm,
      kwargs,
    );
    text = "";
    outputMode = "default";
    selectedLLM = "";
    customMethodName = "";
    kwargEntries = [];
    isExpanded = false;
    if (textarea) {
      textarea.style.height = "auto";
      textarea.style.overflowY = "hidden";
    }
    // Shrink textarea back after clearing
    requestAnimationFrame(() => autoResize());
  }

  function autoResize() {
    if (!textarea) return;
    textarea.style.height = "auto";
    const maxH = getMaxHeight();
    const newH = Math.min(textarea.scrollHeight, maxH);
    textarea.style.height = newH + "px";
    // Show internal scrollbar only when content overflows the cap
    textarea.style.overflowY = textarea.scrollHeight > maxH ? "auto" : "hidden";
  }

  function handlePaste(e: ClipboardEvent) {
    // Get plain text from clipboard to preserve markdown formatting
    const pastedText = e.clipboardData?.getData("text/plain");
    if (pastedText) {
      e.preventDefault();
      // Insert at cursor position
      const start = textarea.selectionStart;
      const end = textarea.selectionEnd;
      const before = text.slice(0, start);
      const after = text.slice(end);
      text = before + pastedText + after;
      // Move cursor after pasted text
      tick().then(() => {
        textarea.selectionStart = textarea.selectionEnd =
          start + pastedText.length;
        autoResize();
      });
    }
  }

  function selectQuestion(question: string) {
    text = question;
    showHistory = false;
    autoResize();
  }
</script>

<div>
  <!-- Follow-up Indicator -->
  {#if followupTurnId}
    <div
      class="bg-success/10 border-success text-success mb-2 flex items-center justify-between rounded-lg border px-2 py-1.5"
    >
      <div class="flex items-center gap-2">
        <svg
          xmlns="http://www.w3.org/2000/svg"
          fill="none"
          viewBox="0 0 24 24"
          stroke-width="1.5"
          stroke="currentColor"
          class="h-3.5 w-3.5"
        >
          <path
            stroke-linecap="round"
            stroke-linejoin="round"
            d="M9 15 3 9m0 0 6-6M3 9h12a6 6 0 0 1 0 12h-3"
          />
        </svg>
        <span class="text-xs font-medium">Replying to previous response</span>
        <span class="badge badge-success badge-xs"
          >{followupTurnId.slice(0, 8)}...</span
        >
      </div>
      <button
        class="flex items-center justify-center h-5 w-5 rounded-full text-success/80 hover:text-success hover:bg-success/20 transition-colors"
        onclick={() => onClearFollowup && onClearFollowup()}
        title="Cancel follow-up"
      >
        <svg
          xmlns="http://www.w3.org/2000/svg"
          fill="none"
          viewBox="0 0 24 24"
          stroke-width="2.5"
          stroke="currentColor"
          class="h-3.5 w-3.5"
        >
          <path
            stroke-linecap="round"
            stroke-linejoin="round"
            d="M6 18 18 6M6 6l12 12"
          />
        </svg>
      </button>
    </div>
  {/if}

  <!-- Main Input Area — Floating Card -->
  <div
    class="flex flex-col bg-white dark:bg-slate-800/95 border border-slate-200/80 dark:border-slate-700/60 rounded-2xl shadow-xl ring-1 ring-black/[0.04] dark:ring-white/[0.06] transition-all duration-200 focus-within:border-blue-400/70 focus-within:ring-2 focus-within:ring-blue-200/50 dark:focus-within:ring-blue-700/40 focus-within:shadow-blue-100/60 dark:focus-within:shadow-blue-950/30"
  >
    <!-- Advanced Options (collapsible) -->
    {#if showAdvancedOptions}
      <div class="border-b border-slate-200/60 dark:border-slate-700/40">
        <button
          type="button"
          class="flex w-full items-center gap-1.5 px-3 py-1.5 text-[11px] font-medium text-slate-500 dark:text-slate-400 hover:text-slate-700 dark:hover:text-slate-300 transition-colors"
          onclick={() => (advancedOpen = !advancedOpen)}
        >
          <svg
            xmlns="http://www.w3.org/2000/svg"
            fill="none"
            viewBox="0 0 24 24"
            stroke-width="2"
            stroke="currentColor"
            class="h-3 w-3 transition-transform duration-150 {advancedOpen ? 'rotate-90' : ''}"
          >
            <path stroke-linecap="round" stroke-linejoin="round" d="m8.25 4.5 7.5 7.5-7.5 7.5" />
          </svg>
          Advanced Options
          {#if customMethodName.trim()}
            <span class="ml-1 rounded bg-blue-100 dark:bg-blue-900/40 px-1.5 py-0.5 text-[10px] font-semibold text-blue-600 dark:text-blue-400">
              {customMethodName.trim()}
            </span>
          {/if}
        </button>

        {#if advancedOpen}
          <div class="px-3 pb-2.5 space-y-2">
            <!-- Method Name -->
            <div class="flex items-center gap-2">
              <label for="chat-method-name" class="text-[11px] text-slate-500 dark:text-slate-400 whitespace-nowrap w-16 shrink-0">Method</label>
              <input
                id="chat-method-name"
                type="text"
                placeholder="e.g. speech_report"
                bind:value={customMethodName}
                class="flex-1 h-6 rounded border border-slate-200 dark:border-slate-600 bg-slate-50 dark:bg-slate-700/50 px-2 text-[11px] text-slate-700 dark:text-slate-300 placeholder-slate-400 focus:outline-none focus:ring-1 focus:ring-blue-300 focus:border-blue-300"
              />
            </div>

            <!-- Key-Value Arguments -->
            <div>
              <div class="flex items-center justify-between mb-1">
                <span class="text-[11px] text-slate-500 dark:text-slate-400">Arguments</span>
                <button
                  type="button"
                  class="flex items-center gap-0.5 text-[10px] text-blue-500 hover:text-blue-600 dark:hover:text-blue-400 transition-colors"
                  onclick={addKwargEntry}
                >
                  <svg xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24" stroke-width="2" stroke="currentColor" class="h-3 w-3">
                    <path stroke-linecap="round" stroke-linejoin="round" d="M12 4.5v15m7.5-7.5h-15" />
                  </svg>
                  Add
                </button>
              </div>
              {#each kwargEntries as entry, i}
                <div class="flex items-center gap-1.5 mb-1">
                  <input
                    type="text"
                    placeholder="key"
                    bind:value={entry.key}
                    class="w-24 shrink-0 h-6 rounded border border-slate-200 dark:border-slate-600 bg-slate-50 dark:bg-slate-700/50 px-2 text-[11px] text-slate-700 dark:text-slate-300 placeholder-slate-400 focus:outline-none focus:ring-1 focus:ring-blue-300"
                  />
                  <input
                    type="text"
                    placeholder="value"
                    bind:value={entry.value}
                    class="flex-1 h-6 rounded border border-slate-200 dark:border-slate-600 bg-slate-50 dark:bg-slate-700/50 px-2 text-[11px] text-slate-700 dark:text-slate-300 placeholder-slate-400 focus:outline-none focus:ring-1 focus:ring-blue-300"
                  />
                  <button
                    type="button"
                    class="flex h-5 w-5 shrink-0 items-center justify-center rounded text-slate-400 hover:text-red-500 hover:bg-red-50 dark:hover:bg-red-900/20 transition-colors"
                    onclick={() => removeKwargEntry(i)}
                    title="Remove argument"
                  >
                    <svg xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24" stroke-width="2" stroke="currentColor" class="h-3 w-3">
                      <path stroke-linecap="round" stroke-linejoin="round" d="M6 18 18 6M6 6l12 12" />
                    </svg>
                  </button>
                </div>
              {/each}
            </div>
          </div>
        {/if}
      </div>
    {/if}

    <!-- Markdown toolbar (shown when toggled ON) -->
    {#if showMarkdownToolbar && textarea}
      <MarkdownEditorToolbar bind:textarea bind:text />
    {/if}

    <!-- Textarea row with optional loading spinner -->
    <div class="flex items-start">
      <textarea
        bind:this={textarea}
        bind:value={text}
        oninput={autoResize}
        onkeydown={handleKeydown}
        onpaste={handlePaste}
        placeholder="{placeholder} ({enterToSend
          ? 'Enter to send'
          : 'Shift+Enter to send'})"
        rows="1"
        class="min-w-0 flex-1 resize-none border-0 bg-transparent pl-3 pr-2 py-3 text-sm leading-tight text-slate-900 dark:text-slate-100 placeholder-slate-400 dark:placeholder-slate-500 focus:outline-none focus:ring-0"
        style="overflow-y: hidden;"
      ></textarea>
      {#if isLoading}
        <div class="flex items-center gap-1.5 pr-3 pt-3 shrink-0">
          <span class="loading loading-spinner loading-sm text-primary"></span>
          <span class="text-xs text-slate-400 font-medium whitespace-nowrap"
            >Thinking…</span
          >
        </div>
      {/if}
    </div>

    <!-- Action Bar / Footer -->
    <div class="flex items-center justify-between px-3 py-2">
      <!-- Left: History Button -->
      <div class="dropdown dropdown-top">
        <button
          class="flex h-7 w-7 items-center justify-center rounded-md text-slate-400 hover:text-slate-600 hover:bg-slate-100 dark:hover:text-slate-300 dark:hover:bg-slate-700 transition-colors"
          title="Recent questions — click to reuse a previous prompt"
          onclick={() => (showHistory = !showHistory)}
        >
          <svg
            xmlns="http://www.w3.org/2000/svg"
            fill="none"
            viewBox="0 0 24 24"
            stroke-width="1.5"
            stroke="currentColor"
            class="h-4 w-4"
          >
            <path
              stroke-linecap="round"
              stroke-linejoin="round"
              d="M12 6v6h4.5m4.5 0a9 9 0 1 1-18 0 9 9 0 0 1 18 0Z"
            />
          </svg>
        </button>

        {#if showHistory && recentQuestions.length > 0}
          <div
            class="dropdown-content bg-white dark:bg-slate-800 rounded-lg border border-slate-200 dark:border-slate-700 z-[50] mb-2 w-72 p-0 shadow-lg"
          >
            <div
              class="flex items-center justify-between px-3 py-2 border-b border-slate-100 dark:border-slate-700"
            >
              <span
                class="text-xs font-medium text-slate-600 dark:text-slate-400"
                >Recent Questions</span
              >
              <button
                class="text-xs text-slate-400 hover:text-slate-600"
                onclick={() => (showHistory = false)}>✕</button
              >
            </div>
            <ul class="max-h-48 overflow-y-auto py-1">
              {#each recentQuestions.slice(0, 8) as question, i}
                <li>
                  <button
                    class="w-full px-3 py-2 text-left text-xs text-slate-600 dark:text-slate-400 hover:bg-slate-50 dark:hover:bg-slate-700 transition-colors"
                    onclick={() => selectQuestion(question)}
                  >
                    <p class="line-clamp-2">{question}</p>
                  </button>
                </li>
              {/each}
            </ul>
          </div>
        {:else if showHistory}
          <div
            class="dropdown-content bg-white dark:bg-slate-800 rounded-lg border border-slate-200 dark:border-slate-700 z-[50] mb-2 w-40 p-3 shadow-lg"
          >
            <p class="text-xs text-slate-400">No history</p>
          </div>
        {/if}
      </div>

      <!-- Right: Expand + Markdown Toggle + LLM Model + Output Mode + Send -->
      <div class="flex items-center gap-2">
        <!-- Expand / Collapse input height anchor -->
        {#if text.length > 0}
          <button
            type="button"
            class="flex h-7 w-7 items-center justify-center rounded-md transition-colors {isExpanded
              ? 'bg-blue-100 text-blue-500 hover:bg-blue-200 dark:bg-blue-900/40 dark:text-blue-400 dark:hover:bg-blue-900/60'
              : 'text-slate-400 hover:text-slate-600 hover:bg-slate-100 dark:hover:text-slate-300 dark:hover:bg-slate-700'}"
            onclick={() => (isExpanded = !isExpanded)}
            title={isExpanded ? "Collapse input" : "Expand input"}
          >
            {#if isExpanded}
              <svg
                xmlns="http://www.w3.org/2000/svg"
                fill="none"
                viewBox="0 0 24 24"
                stroke-width="2.5"
                stroke="currentColor"
                class="h-3.5 w-3.5"
              >
                <path
                  stroke-linecap="round"
                  stroke-linejoin="round"
                  d="m19.5 8.25-7.5 7.5-7.5-7.5"
                />
              </svg>
            {:else}
              <svg
                xmlns="http://www.w3.org/2000/svg"
                fill="none"
                viewBox="0 0 24 24"
                stroke-width="2.5"
                stroke="currentColor"
                class="h-3.5 w-3.5"
              >
                <path
                  stroke-linecap="round"
                  stroke-linejoin="round"
                  d="m4.5 15.75 7.5-7.5 7.5 7.5"
                />
              </svg>
            {/if}
          </button>
        {/if}
        <!-- Markdown editor toggle -->
        <button
          type="button"
          class="flex h-7 items-center justify-center rounded-md px-2 text-[11px] font-medium transition-colors {showMarkdownToolbar
            ? 'bg-blue-100 text-blue-600 dark:bg-blue-900/40 dark:text-blue-400'
            : 'bg-slate-100 text-slate-500 hover:bg-slate-200 dark:bg-slate-700 dark:text-slate-400 dark:hover:bg-slate-600'}"
          title="Toggle Markdown editor — format your message with bold, tables, code blocks"
          onclick={() => (showMarkdownToolbar = !showMarkdownToolbar)}
        >
          M↓
        </button>
        <!-- Custom LLM Selector (left of output mode) -->
        {#if allow_custom_llm}
          <select
            class="flex items-center h-7 rounded-md border-0 bg-slate-100 dark:bg-slate-700 px-2 py-0 text-[11px] leading-none text-slate-500 dark:text-slate-400 focus:outline-none focus:ring-1 focus:ring-blue-300 cursor-pointer max-w-[140px]"
            bind:value={selectedLLM}
            title="Select AI Model — choose which language model powers this conversation"
          >
            {#each supportedModels as model}
              <option value={model.value}>{model.label}</option>
            {/each}
          </select>
        {/if}

        {#if !hideOutputMode}
          <select
            class="flex items-center h-7 rounded-md border-0 bg-slate-100 dark:bg-slate-700 px-2 py-0 text-[11px] leading-none text-slate-500 dark:text-slate-400 focus:outline-none focus:ring-1 focus:ring-blue-300 cursor-pointer"
            bind:value={outputMode}
            title="Response format — controls how the agent structures its answer (Auto, Table, HTML…)"
          >
            {#each outputModes as mode}
              <option value={mode.value}>{mode.label}</option>
            {/each}
          </select>
        {/if}

        <!-- Streaming toggle button -->
        {#if onToggleStream}
          <button
            type="button"
            class="p-1.5 rounded-md transition-colors {streamEnabled
              ? 'text-blue-500 bg-blue-500/10'
              : 'text-gray-400 hover:text-gray-600 dark:hover:text-gray-300'}"
            onclick={onToggleStream}
            title={streamEnabled ? "Streaming ON — responses appear word by word. Click to disable." : "Streaming OFF — response appears all at once. Click to enable."}
          >
            <svg
              xmlns="http://www.w3.org/2000/svg"
              class="w-4 h-4"
              viewBox="0 0 20 20"
              fill="currentColor"
            >
              <path
                d="M11.3 1.046A1 1 0 0112 2v5h4a1 1 0 01.82 1.573l-7 10A1 1 0 018 18v-5H4a1 1 0 01-.82-1.573l7-10a1 1 0 011.12-.381z"
              />
            </svg>
          </button>
        {/if}

        <!-- Voice note recorder (AgentTalk Voice) — opt-in via enableVoiceInput -->
        {#if enableVoiceInput && voiceSupported}
          {#if isRecording}
            <div
              class="flex items-center gap-1.5 rounded-md bg-red-500/10 px-2 h-7"
              title="Recording voice note"
            >
              <span class="h-2 w-2 rounded-full bg-red-500 animate-pulse"
              ></span>
              <span class="text-[11px] font-medium tabular-nums text-red-500"
                >{formatSeconds(recordSeconds)}</span
              >
              <button
                type="button"
                class="flex h-5 w-5 items-center justify-center rounded text-slate-400 hover:text-slate-600 dark:hover:text-slate-300"
                onclick={cancelRecording}
                title="Cancel recording"
                aria-label="Cancel recording"
              >
                <svg
                  xmlns="http://www.w3.org/2000/svg"
                  fill="none"
                  viewBox="0 0 24 24"
                  stroke-width="2.5"
                  stroke="currentColor"
                  class="h-3.5 w-3.5"
                >
                  <path
                    stroke-linecap="round"
                    stroke-linejoin="round"
                    d="M6 18 18 6M6 6l12 12"
                  />
                </svg>
              </button>
              <button
                type="button"
                class="flex h-5 w-5 items-center justify-center rounded bg-red-500 text-white hover:bg-red-600 transition-colors"
                onclick={stopRecording}
                title="Send voice note"
                aria-label="Send voice note"
              >
                <svg
                  xmlns="http://www.w3.org/2000/svg"
                  class="h-3 w-3"
                  viewBox="0 0 20 20"
                  fill="currentColor"
                >
                  <rect x="4" y="4" width="12" height="12" rx="1" />
                </svg>
              </button>
            </div>
          {:else}
            <button
              type="button"
              class="flex h-7 w-7 items-center justify-center rounded-md text-slate-400 hover:text-slate-600 hover:bg-slate-100 dark:hover:text-slate-300 dark:hover:bg-slate-700 transition-colors disabled:opacity-40 disabled:cursor-not-allowed"
              onclick={startRecording}
              disabled={isStreaming || isLoading}
              title={recordError ?? "Record a voice note — speak your question instead of typing"}
              aria-label="Record a voice note"
            >
              <svg
                xmlns="http://www.w3.org/2000/svg"
                fill="none"
                viewBox="0 0 24 24"
                stroke-width="1.5"
                stroke="currentColor"
                class="h-4 w-4"
              >
                <path
                  stroke-linecap="round"
                  stroke-linejoin="round"
                  d="M12 18.75a6 6 0 0 0 6-6v-1.5m-6 7.5a6 6 0 0 1-6-6v-1.5m6 7.5v3.75m-3.75 0h7.5M12 15.75a3 3 0 0 1-3-3V4.5a3 3 0 1 1 6 0v8.25a3 3 0 0 1-3 3Z"
                />
              </svg>
            </button>
          {/if}
        {/if}

        <!-- Stop button (shown during streaming) or Send button -->
        {#if isStreaming}
          <button
            type="button"
            class="flex h-7 w-7 items-center justify-center rounded-md bg-red-500 hover:bg-red-600 text-white transition-colors disabled:opacity-50 disabled:cursor-not-allowed"
            onclick={onStopStream}
            disabled={!onStopStream}
            title="Stop streaming"
          >
            <svg
              xmlns="http://www.w3.org/2000/svg"
              class="w-4 h-4"
              viewBox="0 0 20 20"
              fill="currentColor"
            >
              <rect x="4" y="4" width="12" height="12" rx="1" />
            </svg>
          </button>
        {:else}
          <button
            class="flex h-7 w-7 items-center justify-center rounded-md leading-none transition-all duration-200 {text.trim()
              ? 'bg-blue-500 text-white hover:bg-blue-600 shadow-sm'
              : 'bg-slate-100 dark:bg-slate-700 text-slate-400 cursor-not-allowed'}"
            onclick={handleSubmit}
            disabled={!text.trim() || isStreaming}
            title="Send message (Shift+Enter)"
          >
            <svg
              xmlns="http://www.w3.org/2000/svg"
              viewBox="0 0 24 24"
              fill="currentColor"
              class="h-4 w-4"
            >
              <path
                d="M3.478 2.404a.75.75 0 00-.926.941l2.432 7.905H13.5a.75.75 0 010 1.5H4.984l-2.432 7.905a.75.75 0 00.926.94 60.519 60.519 0 0018.445-8.986.75.75 0 000-1.218A60.517 60.517 0 003.478 2.404z"
              />
            </svg>
          </button>
        {/if}
      </div>
    </div>
  </div>
</div>
