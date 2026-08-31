<script lang="ts">
  import { markdownToHtml } from "$lib/utils/markdown";
  import { slide } from "svelte/transition";
  import { highlightElement } from "$lib/utils/highlight";
  import type { AgentMessage, SqlAnalysisOutput } from "$lib/types/agent";
  import {
    REGENERATION_MODELS,
    DEFAULT_MODEL,
    findModelByMetadata,
  } from "$lib/config/regeneration-models";
  import DataTable from "./DataTable.svelte";
  import SqlArtifactCard from "./SqlArtifactCard.svelte";
  import type { AppChartConfig } from "$lib/components/charts/chart-contract";
  import { features } from "$lib/features";

  // Heavy visualization components are lazy-loaded only when a message needs
  // them, so the global FloatingChat does not pull echarts/leaflet/layerchart
  // into the eager graph of every page. ai-parrot (FEAT-476 TASK-2594): each
  // load is additionally gated behind its `features.X` flag (spec §2) — the
  // targets (ECharts/AppChart under features.charts; DataMap/StructuredMap
  // under features.maps) ship from TASK-2595 and may not exist yet.
  let EChartsComp = $state<
    | typeof import("$lib/components/visualizations/ECharts.svelte").default
    | null
  >(null);
  let AppChartComp = $state<
    typeof import("$lib/components/charts/AppChart.svelte").default | null
  >(null);
  let DataMapComp = $state<typeof import("./DataMap.svelte").default | null>(
    null,
  );
  let StructuredMapComp = $state<
    typeof import("./StructuredMap.svelte").default | null
  >(null);
  let VoiceNotePlayerComp = $state<
    typeof import("./VoiceNotePlayer.svelte").default | null
  >(null);

  $effect(() => {
    if (isUser) return;
    const mode = message.output_mode;
    if (features.charts && mode === "echarts" && message.output && !EChartsComp) {
      import("$lib/components/visualizations/ECharts.svelte").then(
        (m) => (EChartsComp = m.default),
      );
    }
    if (
      features.charts &&
      mode === "structured_chart" &&
      message.output &&
      !AppChartComp
    ) {
      import("$lib/components/charts/AppChart.svelte").then(
        (m) => (AppChartComp = m.default),
      );
    }
    if (features.maps && mode === "map" && !DataMapComp) {
      import("./DataMap.svelte").then((m) => (DataMapComp = m.default));
    }
    if (
      features.maps &&
      mode === "structured_map" &&
      message.output &&
      !StructuredMapComp
    ) {
      import("./StructuredMap.svelte").then(
        (m) => (StructuredMapComp = m.default),
      );
    }
    if (
      features.voice &&
      !isUser &&
      !isStreaming &&
      message.audio_base64 &&
      !VoiceNotePlayerComp
    ) {
      import("./VoiceNotePlayer.svelte").then(
        (m) => (VoiceNotePlayerComp = m.default),
      );
    }
  });

  /**
   * Safely parse a structured-chart `output` into an AppChartConfig object.
   * The backend may return a non-JSON string (e.g. a graceful-degradation error
   * message) — never throw; return null so the UI shows a fallback instead of crashing.
   */
  function parseChartConfig(output: unknown): AppChartConfig | null {
    try {
      const cfg = typeof output === "string" ? JSON.parse(output) : output;
      return cfg && typeof cfg === "object" && "type" in cfg
        ? (cfg as AppChartConfig)
        : null;
    } catch {
      return null;
    }
  }

  /**
   * Parse a structured output config (table / map) — `message.output` may be a
   * JSON string or an already-parsed object. Never throws; returns null on
   * invalid input so the UI shows a fallback instead of crashing.
   */
  function parseOutputConfig(output: unknown): Record<string, any> | null {
    try {
      const cfg = typeof output === "string" ? JSON.parse(output) : output;
      return cfg && typeof cfg === "object"
        ? (cfg as Record<string, any>)
        : null;
    } catch {
      return null;
    }
  }
  import QuickRating from "./QuickRating.svelte";
  import type { QuickRatingType } from "./FeedbackTypes";
  import SourcesPanel from "./SourcesPanel.svelte";

  import Icon from "@iconify/svelte";
  import { AppTooltip } from "$lib/ui/components";
  import { chatBubble, type ChatBubbleVariants } from "./chat-bubble.variants";

  // Props
  let {
    message,
    onRepeat,
    onFollowup,
    onExplain,
    onFeedback,
    onDetailedFeedback,
    onRetry,
    onRegenerate,
    onDelete,
    onOpenSpreadsheet,
    onMoveToCanvas,
    onFetchAudio,
    onMoveTableDataToCanvas,
    onCopyChartToCanvas,
    onCopyChartToChartCanvas,
    onCreateInfographic,
    onCancel,
    isLastAssistantMessage = false,
    chartBackend = "chartjs",
    sessionId,
    chatbotId,
    botMode = false,
    compact = false,
    onSqlArtifact,
    showDataActions = true,
    isStreaming = false,
  } = $props<{
    message: AgentMessage;
    onRepeat?: (text: string) => void;
    onFollowup?: (turnId: string, data: any) => void;
    onExplain?: (turnId: string, data: any) => void;
    onFeedback?: (messageId: string, isLike: boolean) => void;
    onDetailedFeedback?: (messageId: string) => void;
    onRetry?: (msgId: string) => void;
    onRegenerate?: (
      option: "retry" | "details" | "model",
      payload?: string,
    ) => void;
    onDelete?: (messageId: string, turnId: string) => void;
    onOpenSpreadsheet?: (data: any) => void;
    onMoveToCanvas?: (content: string) => void;
    onFetchAudio?: () => void | Promise<void>;
    onMoveTableDataToCanvas?: (
      rows: Record<string, unknown>[],
      columns: string[],
    ) => void;
    onCopyChartToCanvas?: (data: Record<string, any>[], config: any) => void;
    onCopyChartToChartCanvas?: (
      data: Record<string, any>[],
      config: any,
    ) => void;
    onCreateInfographic?: (
      response: string,
      data: Record<string, unknown>[],
    ) => void;
    onCancel?: () => void;
    isLastAssistantMessage?: boolean;
    chartBackend?: "chartjs" | "layerchart";
    sessionId?: string;
    chatbotId?: string;
    botMode?: boolean;
    /**
     * Tight layout for narrow side rails (~280 px). Drops the side-action
     * reservation (`-4rem`) on assistant bubbles since hover-actions don't
     * fit in compact mode anyway.
     */
    compact?: boolean;
    /**
     * Optional handler invoked when the user clicks "Copy to Editor" on a
     * `` ```sql `` code block in an assistant message. The handler receives
     * the SQL text and decides what to do with it (typically: push it into
     * a parent editor's state). When omitted, the button isn't rendered —
     * generic chat surfaces stay unchanged. Used by the QuerySource
     * Query Executor's AI Assistant panel to pipe the agent's suggested
     * SQL into the active query tab.
     */
    onSqlArtifact?: (sql: string) => void;
    /**
     * Whether to show the data-related action buttons in the row beneath
     * an assistant message (View JSON/Table, Copy to Canvas, Download CSV,
     * Open Spreadsheet, Create Infographic).
     *
     * Default ``true`` matches the historical behaviour. Set to ``false``
     * on surfaces where the agent's ``data`` field is incidental metadata
     * rather than a user-runnable result set — e.g. the ``sql_analyst``
     * panel in the Query Executor, where ``data`` is just the schema
     * descriptions the LLM looked at while building a SQL artifact.
     * The SQL artifact button itself is NOT affected by this flag — it
     * depends on ``onSqlArtifact``.
     */
    showDataActions?: boolean;
    /**
     * When true, the message is actively being streamed. Shows a blinking
     * cursor and hides panels that only make sense after the full response
     * is available (sources, feedback, data actions, regeneration).
     */
    isStreaming?: boolean;
  }>();

  // FEAT-257: lazy replay-audio fetch state (fetch-on-click). The reply audio
  // is synthesized server-side and served over HTTP; we fetch it only when the
  // user clicks the play button, then `message.audio_base64` renders the player.
  let audioLoading = $state(false);
  // True once the user fetched the audio via the play button → autoplay it.
  let didFetchAudio = $state(false);

  let isUser = $derived(message.role === "user");
  let bubbleRole = $derived<ChatBubbleVariants["role"]>(
    message.role === "user"
      ? "user"
      : message.role === "system"
        ? "system"
        : "assistant",
  );
  let bubbleEdge = $derived<ChatBubbleVariants["edge"]>(
    isUser ? "end" : "start",
  );
  let showData = $state(false);
  let showMetadata = $state(false);
  // Collapsible state for visualizations (default to expanded)
  let isCollapsed = $state(false);
  // Table format choice dropdown
  let tableFormatMenuOpen = $state(false);

  /**
   * Extract map marker data from Leaflet HTML response.
   * Parses L.marker([lat, lng]) calls and .bindPopup("label") from the HTML source.
   */
  function extractMapDataFromHtml(html: string): Record<string, any>[] {
    const results: Record<string, any>[] = [];
    // Match L.marker([lat, lng]) patterns, optionally followed by .bindPopup(...)
    const markerRegex =
      /L\.marker\(\s*\[\s*([-\d.]+)\s*,\s*([-\d.]+)\s*\]\s*\)(?:\s*\.bindPopup\(\s*(?:['"`])(.+?)(?:['"`])\s*\))?/g;
    let match;
    while ((match = markerRegex.exec(html)) !== null) {
      const lat = parseFloat(match[1]);
      const lng = parseFloat(match[2]);
      const label = match[3] || "";
      if (Number.isFinite(lat) && Number.isFinite(lng)) {
        results.push({ label, lat, lng });
      }
    }
    // Also try JSON array patterns like markers = [{lat: ..., lng: ..., ...}]
    if (results.length === 0) {
      const jsonArrayRegex =
        /(?:markers|data|points|locations)\s*=\s*(\[[\s\S]*?\]);/g;
      let jMatch;
      while ((jMatch = jsonArrayRegex.exec(html)) !== null) {
        try {
          const parsed = JSON.parse(jMatch[1]);
          if (Array.isArray(parsed)) {
            for (const item of parsed) {
              const lat = Number(
                item.lat ?? item.latitude ?? item.Lat ?? item.Latitude,
              );
              const lng = Number(
                item.lng ??
                  item.lon ??
                  item.longitude ??
                  item.Lng ??
                  item.Lon ??
                  item.Longitude,
              );
              if (Number.isFinite(lat) && Number.isFinite(lng)) {
                results.push({ ...item, lat, lng });
              }
            }
          }
        } catch {
          /* ignore parse errors */
        }
      }
    }
    return results;
  }

  // More Actions Menu State (three-dots menu in feedback footer)
  let showMoreMenu = $state(false);
  let moreMenuRef = $state<HTMLElement>();

  function toggleMoreMenu(e: MouseEvent) {
    e.stopPropagation();
    showMoreMenu = !showMoreMenu;
  }

  function handleMoreMenuOutsideClick(event: MouseEvent) {
    if (
      showMoreMenu &&
      moreMenuRef &&
      !moreMenuRef.contains(event.target as Node)
    ) {
      showMoreMenu = false;
    }
  }

  $effect(() => {
    if (showMoreMenu) {
      document.addEventListener("click", handleMoreMenuOutsideClick);
    } else {
      document.removeEventListener("click", handleMoreMenuOutsideClick);
    }
    return () => {
      document.removeEventListener("click", handleMoreMenuOutsideClick);
    };
  });

  // Regeneration Menu State
  let showRegenMenu = $state(false);
  let showModelSubmenu = $state(false); // Using boolean for simplicity, could be derived if logic gets complex
  let showDetailsInput = $state(false);
  let detailsInputValue = $state("");
  let regenMenuRef = $state<HTMLElement>();
  let detailsInputRef = $state<HTMLInputElement>();

  // Derive selectedModel from the message metadata (sticky to what generated this response)
  // Uses fuzzy matching to handle backend vs frontend naming differences
  let selectedModel = $derived(
    findModelByMetadata(message.metadata?.model)?.value ?? DEFAULT_MODEL,
  );
  let detailsExpanded = $state(false);

  function toggleRegenMenu(e: MouseEvent) {
    e.stopPropagation();
    showRegenMenu = !showRegenMenu;
    if (!showRegenMenu) {
      showModelSubmenu = false;
      showDetailsInput = false;
    }
  }

  function handleRegenerateAction(
    option: "retry" | "details" | "model",
    payload?: string,
  ) {
    if (onRegenerate) {
      onRegenerate(option, payload);
      showRegenMenu = false; // Close menu after action
      showDetailsInput = false;
      showModelSubmenu = false;
    }
  }

  function handleOutsideClick(event: MouseEvent) {
    if (
      showRegenMenu &&
      regenMenuRef &&
      !regenMenuRef.contains(event.target as Node)
    ) {
      showRegenMenu = false;
      showModelSubmenu = false;
      showDetailsInput = false;
    }
  }

  // Effect to handle click outside
  $effect(() => {
    if (showRegenMenu) {
      document.addEventListener("click", handleOutsideClick);
    } else {
      document.removeEventListener("click", handleOutsideClick);
    }
    return () => {
      document.removeEventListener("click", handleOutsideClick);
    };
  });

  // Effect to focus input when shown
  $effect(() => {
    if (showDetailsInput && detailsInputRef) {
      detailsInputRef.focus();
    }
  });

  // Track local feedback state for visual feedback
  let feedbackState = $state<{ like: boolean | null }>({ like: null });
  let quickRatingType = $state<QuickRatingType | null>(null);

  function handleFeedback(isLike: boolean) {
    if (onFeedback && message.metadata?.turn_id) {
      feedbackState.like = isLike; // Update local state
      onFeedback(message.metadata.turn_id, isLike);
    }
  }

  function toggleQuickRating(type: QuickRatingType) {
    quickRatingType = quickRatingType === type ? null : type;
  }

  function handleQuickRatingSubmit(type: QuickRatingType) {
    feedbackState.like = type === "positive";
    quickRatingType = null;
  }

  // Check for error state either via metadata or content convention
  let isError = $derived(
    message.metadata?.is_error || message.content.startsWith("**Error:**"),
  );

  // Rotating placeholder verbs shown next to the bouncing dots while the
  // assistant has no content yet. Cycles every ~1.6s so users see activity
  // instead of an indefinite "..." that can read as a stalled UI.
  const THINKING_WORDS = ["Thinking", "Working", "Processing", "Analyzing"];
  let thinkingWordIndex = $state(
    Math.floor(Math.random() * THINKING_WORDS.length),
  );
  let isThinking = $derived(
    !message.content && !isError && !message.htmlResponse,
  );

  $effect(() => {
    if (!isThinking) return;
    const interval = setInterval(() => {
      let next = thinkingWordIndex;
      if (THINKING_WORDS.length > 1) {
        while (next === thinkingWordIndex) {
          next = Math.floor(Math.random() * THINKING_WORDS.length);
        }
      }
      thinkingWordIndex = next;
    }, 1600);
    return () => clearInterval(interval);
  });

  // Check if data is present and not empty
  let hasData = $derived(
    message.data &&
      (Array.isArray(message.data)
        ? message.data.length > 0
        : Object.keys(message.data).length > 0),
  );

  // Structured SQL output from DatabaseAgent-style agents (e.g.
  // ``sql_analyst``). When ``output_mode === "sql_analysis"`` the
  // backend ships a ``QueryResponse``-shaped payload in ``message.output``
  // — we render the SQL as a dedicated artifact card below. ``null``
  // for any other message type leaves all SQL-specific UI hidden.
  let sqlAnalysis = $derived.by<SqlAnalysisOutput | null>(() => {
    if (message.output_mode !== "sql_analysis") return null;
    const out = message.output;
    if (!out || typeof out !== "object") return null;
    if (typeof out.explanation !== "string") return null;
    return out as SqlAnalysisOutput;
  });
  let sqlArtifact = $derived(sqlAnalysis?.query?.trim() || null);

  /**
   * Strip the agent-context preamble some agents prepend to the question.
   *
   * The QuerySource sql_analyst injects a wrapper at request time so the
   * LLM sees the active datasource + the SQL the user is editing on every
   * turn:
   *
   *     [Live editor context]
   *     Active connection: ...
   *     The user is currently editing this SQL ...
   *
   *     [User question]
   *     <the actual question typed by the user>
   *
   * The backend persists the wrapped form (it's what flows through
   * ``ask(question=…)``), and Dexie's sync pulls that down — so without
   * this trim, the chat bubble shows the whole preamble to the user.
   * Trim ONLY for display; the stored form is left intact so the LLM
   * keeps seeing the context in conversation history.
   */
  function stripAgentContextPreamble(raw: string): string {
    if (!raw.startsWith("[Live editor context]")) return raw;
    const m = raw.match(
      /^\[Live editor context\][\s\S]*?\n\[User question\]\n/,
    );
    return m ? raw.slice(m[0].length) : raw;
  }
  /**
   * Drop markdown table lines from the body. Used for structured_table / structured_map,
   * where the agent often repeats the data as a markdown table inside its explanation;
   * the dedicated component already renders that table, so the prose-only body avoids
   * a duplicate (and survives malformed tables — mismatched columns, missing header).
   * Any line whose trimmed form starts with `|` is a table header/separator/row and is
   * removed; prose never starts with `|`.
   */
  function stripMarkdownTables(md: string): string {
    return md
      .split("\n")
      .filter((line) => !line.trim().startsWith("|"))
      .join("\n")
      .replace(/\n{3,}/g, "\n\n")
      .trim();
  }

  let displayContent = $derived.by(() => {
    const base = stripAgentContextPreamble(message.content || "");
    return message.output_mode === "structured_table" ||
      message.output_mode === "structured_map"
      ? stripMarkdownTables(base)
      : base;
  });

  // Markdown parsing — normalize, parse, wrap tables, and sanitize via shared utility
  let parsedContent = $derived(markdownToHtml(displayContent));

  // Parse [Details]: pattern for user messages into main query + context payload
  let detailsParts = $derived.by(() => {
    if (!isUser || !message.content) return null;
    const delimiter = "\n\n[Details]:";
    const idx = message.content.indexOf("[Details]:");
    if (idx === -1) return null;
    // Find the actual split point (could have \n\n before or just be inline)
    const splitIdx = message.content.lastIndexOf("\n", idx);
    const mainQuery = (
      splitIdx > 0
        ? message.content.slice(0, splitIdx)
        : message.content.slice(0, idx)
    ).trim();
    const contextPayload = message.content
      .slice(idx + "[Details]:".length)
      .trim();
    if (!contextPayload) return null;
    return { mainQuery, contextPayload };
  });

  // Copy to clipboard function
  const copyToClipboard = async (text: string) => {
    try {
      await navigator.clipboard.writeText(text);
      // Ideally show a toast here
      // alert('Copied to clipboard');
    } catch (err) {
      console.error("Failed to copy!", err);
    }
  };

  let contentRef = $state<HTMLElement>();

  $effect(() => {
    if (contentRef) {
      // Highlight code blocks
      contentRef.querySelectorAll("pre code").forEach((el) => {
        highlightElement(el as HTMLElement);
      });

      // Add copy buttons to code blocks
      contentRef.querySelectorAll("pre").forEach((pre) => {
        if (pre.querySelector(".copy-btn")) return; // already added

        const button = document.createElement("button");
        button.className =
          "copy-btn absolute top-2 right-2 btn btn-xs btn-square btn-ghost opacity-50 hover:opacity-100";
        button.innerHTML =
          '<svg xmlns="http://www.w3.org/2000/svg" width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><rect x="9" y="9" width="13" height="13" rx="2" ry="2"></rect><path d="M5 15H4a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h9a2 2 0 0 1 2 2v1"></path></svg>';
        button.title = "Copy Code";

        button.addEventListener("click", () => {
          const code = pre.querySelector("code")?.innerText || "";
          copyToClipboard(code);
          // ephemeral success state
          button.classList.add("text-success");
          setTimeout(() => button.classList.remove("text-success"), 1000);
        });

        pre.style.position = "relative";
        pre.appendChild(button);
      });
    }
  });
</script>

<div class={`chat ${isUser ? "chat-end" : "chat-start"}`}>
  <div class="chat-header mb-1 text-xs opacity-50 flex items-center gap-2">
    <time class="text-xs opacity-50"
      >{new Date(message.timestamp).toLocaleTimeString()}</time
    >
    {#if isUser && onRepeat}
      <button
        class="btn btn-ghost btn-xs btn-circle text-muted-foreground hover:text-primary"
        onclick={() => onRepeat && onRepeat(displayContent)}
        title="Repeat question"
      >
        <svg
          xmlns="http://www.w3.org/2000/svg"
          fill="none"
          viewBox="0 0 24 24"
          stroke-width="1.5"
          stroke="currentColor"
          class="size-3"
        >
          <path
            stroke-linecap="round"
            stroke-linejoin="round"
            d="M16.023 9.348h4.992v-.001M2.985 19.644v-4.992m0 0h4.992m-4.993 0 3.181 3.183a8.25 8.25 0 0 0 13.803-3.7M4.031 9.865a8.25 8.25 0 0 1 13.803-3.7l3.181 3.182m0-4.991v4.99"
          />
        </svg>
      </button>
    {/if}
    {#if isUser && onDelete}
      <button
        class="btn btn-ghost btn-xs btn-circle text-muted-foreground hover:text-destructive transition-colors"
        onclick={() =>
          onDelete && onDelete(message.id, message.metadata?.turn_id || "")}
        title="Remove message"
      >
        <Icon icon="mdi:trash-can-outline" class="size-3" />
      </button>
    {/if}
  </div>

  <div
    class={`${chatBubble({ role: bubbleRole, edge: bubbleEdge })} group relative !overflow-visible ${isUser ? "col-start-1" : `col-start-2 !w-full ${compact ? "max-w-full" : "max-w-[calc(100%-4rem)]"}`}`}
  >
    <!-- Side Actions (Reply, Explain) -->
    {#if !isUser}
      <div
        class="absolute -right-10 top-0 flex h-full flex-col gap-1 py-2 opacity-0 transition-opacity group-hover:opacity-100"
      >
        <!-- Follow-up Reply -->
        {#if onFollowup && message.metadata?.turn_id}
          <button
            class="btn btn-ghost btn-xs btn-square text-success"
            onclick={() =>
              onFollowup &&
              onFollowup(message.metadata?.turn_id || "", message.data)}
            title="Reply to this message"
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
                d="M9 15 3 9m0 0 6-6M3 9h12a6 6 0 0 1 0 12h-3"
              />
            </svg>
          </button>
        {/if}

        <!-- Explain -->
        {#if onExplain}
          <button
            class="btn btn-ghost btn-xs btn-square text-warning"
            onclick={() => onExplain && onExplain(message.id, message.data)}
            title="Explain results"
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
                d="M9.879 7.519c1.171-1.025 3.071-1.025 4.242 0 1.172 1.025 1.172 2.687 0 3.712-.203.179-.43.326-.67.442-.745.361-1.45.999-1.45 1.827v.75M21 12a9 9 0 1 1-18 0 9 9 0 0 1 18 0Zm-9 5.25h.008v.008H12v-.008Z"
              />
            </svg>
          </button>
        {/if}

        <!-- Copy -->
        <button
          class="btn btn-ghost btn-xs btn-square text-slate-400 hover:text-slate-600"
          onclick={() => copyToClipboard(displayContent)}
          title="Copy answer"
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
              d="M15.75 17.25v3.375c0 .621-.504 1.125-1.125 1.125h-9.75a1.125 1.125 0 0 1-1.125-1.125V7.875c0-.621.504-1.125 1.125-1.125H6.75a9.06 9.06 0 0 1 1.5.124m7.5 10.376h3.375c.621 0 1.125-.504 1.125-1.125V11.25c0-4.46-3.243-8.161-7.5-8.876a9.06 9.06 0 0 0-1.5-.124H9.375c-.621 0-1.125.504-1.125 1.125v3.5m7.5 10.375H9.375a1.125 1.125 0 0 1-1.125-1.125v-9.25m12 6.625v-1.875a3.375 3.375 0 0 0-3.375-3.375h-1.5"
            />
          </svg>
        </button>

        <!-- Move to Canvas (text content) -->
        {#if onMoveToCanvas}
          <button
            class="btn btn-ghost btn-xs btn-square text-slate-400 hover:text-purple-500 transition-colors"
            onclick={() => onMoveToCanvas && onMoveToCanvas(displayContent)}
            title="Add to canvas"
          >
            <Icon icon="mdi:palette-outline" class="h-4 w-4" />
          </button>
        {/if}
      </div>
    {/if}

    <!-- Regeneration Options Popup (triggered from more-actions menu) -->
    {#if !isStreaming && showRegenMenu && onRegenerate && isLastAssistantMessage}
      <div
        bind:this={regenMenuRef}
        class="absolute right-0 bottom-full mb-2 z-50 w-56 rounded-2xl border border-border bg-popover/75 backdrop-blur-xl p-2.5 flex flex-col gap-2"
        role="menu"
      >
        <!-- Section: Quick Action -->
        <span
          class="px-2.5 pt-1 pb-1.5 text-[9px] font-semibold uppercase tracking-[0.1em] text-slate-600 dark:text-slate-400 select-none"
          >Quick Action</span
        >

        <!-- Try Again (Hero Button) -->
        <button
          class="flex w-full items-center justify-center gap-2 rounded-xl px-3 py-1.5 text-[11px] font-semibold text-white bg-primary-500 hover:bg-primary-600 transition-all duration-200 active:scale-[0.98]"
          onclick={(e) => {
            e.stopPropagation();
            handleRegenerateAction("retry");
          }}
        >
          <Icon icon="mdi:refresh" class="h-3.5 w-3.5" />
          <span>Try again</span>
        </button>

        <!-- Add Details -->
        <div class="relative w-full">
          {#if !showDetailsInput}
            <button
              class="flex w-full items-center gap-2.5 rounded-xl px-2.5 py-2 text-xs text-left text-foreground hover:bg-accent transition-colors"
              onclick={(e) => {
                e.stopPropagation();
                showDetailsInput = true;
                detailsInputValue = "";
              }}
            >
              <Icon
                icon="mdi:pencil-outline"
                class="h-3.5 w-3.5 text-slate-600 dark:text-slate-400"
              />
              <span class="font-medium">Add details</span>
            </button>
          {:else}
            <div
              class="p-2.5 flex flex-col gap-2.5 bg-muted/60 rounded-xl"
              onclick={(e) => e.stopPropagation()}
              onkeydown={(e) => e.stopPropagation()}
              role="group"
            >
              <input
                bind:this={detailsInputRef}
                type="text"
                class="w-full rounded-lg bg-card border-0 ring-1 ring-border px-2.5 py-1.5 text-xs text-foreground placeholder:text-muted-foreground focus:outline-none focus:ring-2 focus:ring-ring/50 transition-shadow"
                placeholder="Provide more context..."
                bind:value={detailsInputValue}
                onkeydown={(e) => {
                  if (e.key === "Enter" && detailsInputValue.trim())
                    handleRegenerateAction("details", detailsInputValue);
                  if (e.key === "Escape") showDetailsInput = false;
                }}
              />
              <div class="flex justify-end gap-1">
                <button
                  class="px-2 py-1 rounded-md text-[10px] font-medium text-muted-foreground hover:text-foreground hover:bg-accent/50 transition-colors"
                  onclick={() => (showDetailsInput = false)}>Cancel</button
                >
                <button
                  class="px-2.5 py-1 rounded-md text-[10px] font-semibold text-white bg-primary-500 hover:bg-primary-600 shadow-sm transition-colors disabled:opacity-40"
                  disabled={!detailsInputValue.trim()}
                  onclick={() =>
                    handleRegenerateAction("details", detailsInputValue)}
                  >Regenerate</button
                >
              </div>
            </div>
          {/if}
        </div>

        <!-- Divider -->
        <div
          class="my-0.5 border-t border-slate-200/60 dark:border-white/[0.06]"
        ></div>

        <!-- Section: Model -->
        <button
          class="flex w-full items-center justify-between px-2.5 pt-1 pb-1.5 group cursor-pointer"
          onclick={(e) => {
            e.stopPropagation();
            showModelSubmenu = !showModelSubmenu;
          }}
        >
          <span
            class="text-[9px] font-semibold uppercase tracking-[0.1em] text-slate-600 dark:text-slate-400 select-none group-hover:text-slate-700 dark:group-hover:text-slate-300 transition-colors"
            >Model</span
          >
          <svg
            xmlns="http://www.w3.org/2000/svg"
            fill="none"
            viewBox="0 0 24 24"
            stroke-width="2"
            stroke="currentColor"
            class={`h-3 w-3 text-slate-400 dark:text-slate-500 transition-transform duration-200 ${showModelSubmenu ? "rotate-180" : ""}`}
          >
            <path
              stroke-linecap="round"
              stroke-linejoin="round"
              d="m19.5 8.25-7.5 7.5-7.5-7.5"
            />
          </svg>
        </button>

        {#if showModelSubmenu}
          <div
            class="flex flex-col gap-0.5 pb-1"
            transition:slide={{ duration: 200 }}
          >
            {#each REGENERATION_MODELS as model}
              {@const isActive = model.value === selectedModel}
              {@const isDisabled = !model.enabled}
              <button
                class={`flex w-full items-center justify-between rounded-xl px-2.5 py-2 text-xs text-left transition-all duration-150 ${isDisabled ? "opacity-40 cursor-not-allowed" : isActive ? "bg-primary/10 text-primary" : "text-muted-foreground hover:bg-accent hover:text-foreground"}`}
                disabled={isDisabled}
                onclick={(e) => {
                  e.stopPropagation();
                  handleRegenerateAction("model", model.value);
                }}
              >
                <div class="flex flex-col gap-0.5">
                  <span
                    class={`leading-none ${isActive ? "font-semibold" : "font-medium"}`}
                    >{model.label}</span
                  >
                  <span
                    class={`text-[9px] leading-none ${isActive ? "text-primary-400/70 dark:text-primary-400/50" : "text-slate-400 dark:text-slate-500"}`}
                    >{model.provider}{#if isDisabled}
                      · Coming Soon{/if}</span
                  >
                </div>
                {#if isActive}
                  <svg
                    xmlns="http://www.w3.org/2000/svg"
                    viewBox="0 0 20 20"
                    fill="currentColor"
                    class="h-4 w-4 text-primary-500 dark:text-primary-400 shrink-0"
                  >
                    <path
                      fill-rule="evenodd"
                      d="M16.704 4.153a.75.75 0 0 1 .143 1.052l-8 10.5a.75.75 0 0 1-1.127.075l-4.5-4.5a.75.75 0 0 1 1.06-1.06l3.894 3.893 7.48-9.817a.75.75 0 0 1 1.05-.143Z"
                      clip-rule="evenodd"
                    />
                  </svg>
                {/if}
              </button>
            {/each}
          </div>
        {/if}
      </div>
    {/if}

    <!-- Message Content -->
    {#if !message.htmlResponse}
      <div
        bind:this={contentRef}
        class={`chat-markdown max-w-none text-sm ${isError ? "text-error" : ""}`}
      >
        {#if !message.content && !isError}
          <!-- Thinking Animation -->
          <div class="flex items-center gap-2 p-2">
            <span
              class="text-xs italic text-muted-foreground select-none min-w-[5.5rem]"
              aria-live="polite"
            >
              {THINKING_WORDS[thinkingWordIndex]}
            </span>
            <div class="flex items-center gap-1">
              <div
                class="h-2 w-2 rounded-full bg-muted-foreground animate-bounce [animation-delay:-0.3s]"
              ></div>
              <div
                class="h-2 w-2 rounded-full bg-muted-foreground animate-bounce [animation-delay:-0.15s]"
              ></div>
              <div
                class="h-2 w-2 rounded-full bg-muted-foreground animate-bounce"
              ></div>
            </div>
            {#if onCancel}
              <button
                class="btn btn-ghost btn-xs btn-square text-muted-foreground hover:text-red-500 transition-colors"
                onclick={onCancel}
                title="Stop"
              >
                <Icon icon="mdi:stop-circle-outline" class="size-4" />
              </button>
            {/if}
          </div>
        {:else if detailsParts}
          <!-- User message with [Details]: parsed into main query + refinement card -->
          {@const CONTEXT_CHAR_LIMIT = 60}
          {@const isExpandable =
            detailsParts.contextPayload.length > CONTEXT_CHAR_LIMIT}
          <div class="space-y-2">
            <div>
              {@html markdownToHtml(detailsParts.mainQuery)}
            </div>
            {#if isExpandable}
              <!-- Long text: interactive expand/collapse card -->
              <button
                class="flex w-full max-w-[280px] items-start gap-2 rounded-lg bg-white/15 dark:bg-white/10 px-3 py-2 text-left cursor-pointer hover:bg-white/25 dark:hover:bg-white/15 transition-colors"
                onclick={() => (detailsExpanded = !detailsExpanded)}
              >
                <Icon
                  icon="mdi:pencil-outline"
                  class="h-3.5 w-3.5 mt-0.5 shrink-0 opacity-60"
                />
                <div
                  class="flex-1 flex flex-col gap-0.5 min-w-0 overflow-hidden"
                >
                  <span
                    class="text-[9px] font-semibold uppercase tracking-wider opacity-50"
                    >Added Context</span
                  >
                  <div
                    class="overflow-hidden transition-all duration-200 ease-out"
                    style={detailsExpanded
                      ? "max-height: 500px;"
                      : "max-height: 1.25em;"}
                  >
                    <span class="text-xs opacity-80 italic whitespace-pre-wrap"
                      >{detailsParts.contextPayload}</span
                    >
                  </div>
                </div>
                <svg
                  xmlns="http://www.w3.org/2000/svg"
                  fill="none"
                  viewBox="0 0 24 24"
                  stroke-width="2"
                  stroke="currentColor"
                  class={`h-3.5 w-3.5 mt-0.5 shrink-0 opacity-40 transition-transform duration-200 ${detailsExpanded ? "rotate-180" : ""}`}
                >
                  <path
                    stroke-linecap="round"
                    stroke-linejoin="round"
                    d="m19.5 8.25-7.5 7.5-7.5-7.5"
                  />
                </svg>
              </button>
            {:else}
              <!-- Short text: static card, no interaction -->
              <div
                class="flex max-w-[280px] items-start gap-2 rounded-lg bg-white/15 dark:bg-white/10 px-3 py-2"
              >
                <Icon
                  icon="mdi:pencil-outline"
                  class="h-3.5 w-3.5 mt-0.5 shrink-0 opacity-60"
                />
                <div class="flex flex-col gap-0.5 min-w-0">
                  <span
                    class="text-[9px] font-semibold uppercase tracking-wider opacity-50"
                    >Added Context</span
                  >
                  <span class="text-xs opacity-80 italic"
                    >{detailsParts.contextPayload}</span
                  >
                </div>
              </div>
            {/if}
          </div>
        {:else}
          {@html parsedContent}
          {#if isStreaming}
            <span
              class="inline-block w-2 h-4 ml-0.5 bg-current animate-pulse rounded-sm align-text-bottom"
            ></span>
          {/if}
        {/if}
      </div>

      <!-- Retry Action for Errors -->
      {#if isError && onRetry}
        <div
          class="mt-2 flex justify-center w-full border-t border-error/20 pt-2"
        >
          <button
            class="btn btn-sm btn-ghost gap-2 text-error hover:bg-error/10"
            onclick={() => onRetry && onRetry(message.id)}
            title="Retry request"
          >
            <svg
              xmlns="http://www.w3.org/2000/svg"
              fill="none"
              viewBox="0 0 24 24"
              stroke-width="1.5"
              stroke="currentColor"
              class="size-4"
            >
              <path
                stroke-linecap="round"
                stroke-linejoin="round"
                d="M16.023 9.348h4.992v-.001M2.985 19.644v-4.992m0 0h4.992m-4.993 0 3.181 3.183a8.25 8.25 0 0 0 13.803-3.7M4.031 9.865a8.25 8.25 0 0 1 13.803-3.7l3.181 3.182m0-4.991v4.99"
              />
            </svg>
            Retry
          </button>
        </div>
      {/if}
    {/if}

    <!-- Voice answer player (AgentTalk Voice): rendered beneath the assistant's
         text and BEFORE the data/visualization action buttons. Only present when
         the answer came back with synthesized audio. -->
    {#if features.voice && !isUser && !isStreaming && message.audio_base64 && VoiceNotePlayerComp}
      {@const VoiceNotePlayer = VoiceNotePlayerComp}
      <VoiceNotePlayer
        audioBase64={message.audio_base64}
        audioFormat={message.audio_format}
        autoplay={didFetchAudio}
      />
    {:else if !isUser && !isStreaming && isLastAssistantMessage && onFetchAudio}
      <!-- FEAT-257: fetch-on-click replay. The room/avatar reply audio was
           synthesized server-side; fetch it on demand instead of relying on a
           realtime WS push. Only on the last assistant message (the backend
           keeps a single last-answer slot per session). -->
      <button
        type="button"
        class="btn btn-ghost btn-xs mt-1 gap-1 text-xs"
        disabled={audioLoading}
        onclick={async () => {
          audioLoading = true;
          try {
            await onFetchAudio?.();
            didFetchAudio = true;
          } finally {
            audioLoading = false;
          }
        }}
      >
        <Icon
          icon={audioLoading
            ? "svg-spinners:3-dots-fade"
            : "mdi:play-circle-outline"}
          class="h-4 w-4"
        />
        {audioLoading ? "Cargando audio…" : "Reproducir respuesta"}
      </button>
    {/if}

    <!-- Visualization Content -->
    {#if !isUser}
      <div class="mt-2 flex w-full flex-col gap-2">
        <!-- Native ECharts Rendering (Priority if output data exists) -->
        {#if message.output_mode === "echarts" && message.output}
          <div
            class="border-base-300 bg-base-100 rounded-box border overflow-hidden"
          >
            <div
              class="border-b border-base-300 bg-base-200 p-2 px-4 flex items-center justify-between text-sm font-medium cursor-pointer hover:bg-base-300/50 transition-colors"
              onclick={() => (isCollapsed = !isCollapsed)}
              role="button"
              tabindex="0"
              onkeydown={(e) =>
                e.key === "Enter" && (isCollapsed = !isCollapsed)}
            >
              <div class="flex items-center gap-2">
                <svg
                  xmlns="http://www.w3.org/2000/svg"
                  fill="none"
                  viewBox="0 0 24 24"
                  stroke-width="1.5"
                  stroke="currentColor"
                  class="size-4 text-purple-500"
                >
                  <path
                    stroke-linecap="round"
                    stroke-linejoin="round"
                    d="M3.75 3v11.25A2.25 2.25 0 0 0 6 16.5h2.25M3.75 3h-1.5m1.5 0h16.5m0 0h1.5m-1.5 0v11.25A2.25 2.25 0 0 1 18 16.5h-2.25m-7.5 0h7.5m-7.5 0-1 3m8.5-3 1 3m0 0 .5 1.5m-.5-1.5h-9.5m0 0-.5 1.5M9 11.25v1.5M12 9v3.75m3-6v6"
                  />
                </svg>
                Chart View (ECharts)
              </div>
              <!-- Toggle Icon -->
              <button
                class="btn btn-ghost btn-xs btn-circle"
                aria-label={isCollapsed ? "Expand chart" : "Collapse chart"}
                title={isCollapsed ? "Expand chart" : "Collapse chart"}
                onclick={(e) => {
                  e.stopPropagation();
                  isCollapsed = !isCollapsed;
                }}
              >
                <svg
                  xmlns="http://www.w3.org/2000/svg"
                  fill="none"
                  viewBox="0 0 24 24"
                  stroke-width="1.5"
                  stroke="currentColor"
                  class={`size-4 transition-transform duration-200 ${isCollapsed ? "-rotate-90" : "rotate-0"}`}
                >
                  <path
                    stroke-linecap="round"
                    stroke-linejoin="round"
                    d="m19.5 8.25-7.5 7.5-7.5-7.5"
                  />
                </svg>
              </button>
            </div>
            {#if !isCollapsed}
              <div class="bg-white p-4">
                {#if EChartsComp}
                  <EChartsComp
                    options={typeof message.output === "string"
                      ? JSON.parse(message.output)
                      : message.output}
                    style="width: 100%; height: 500px;"
                  />
                {:else}
                  <div
                    class="flex h-[500px] items-center justify-center text-sm text-muted-foreground"
                  >
                    Loading chart…
                  </div>
                {/if}
              </div>
            {/if}
          </div>

          <!-- Structured Chart (LayerChart / AppChart) — agnostic config from backend -->
        {:else if message.output_mode === "structured_chart" && message.output}
          {@const chartConfig = parseChartConfig(message.output)}
          <div
            class="border-base-300 bg-base-100 rounded-box border overflow-hidden"
          >
            <div
              class="border-b border-base-300 bg-base-200 p-2 px-4 flex items-center justify-between text-sm font-medium cursor-pointer hover:bg-base-300/50 transition-colors"
              onclick={() => (isCollapsed = !isCollapsed)}
              role="button"
              tabindex="0"
              onkeydown={(e) =>
                e.key === "Enter" && (isCollapsed = !isCollapsed)}
            >
              <div class="flex items-center gap-2">
                <svg
                  xmlns="http://www.w3.org/2000/svg"
                  fill="none"
                  viewBox="0 0 24 24"
                  stroke-width="1.5"
                  stroke="currentColor"
                  class="size-4 text-blue-500"
                >
                  <path
                    stroke-linecap="round"
                    stroke-linejoin="round"
                    d="M3.75 3v11.25A2.25 2.25 0 0 0 6 16.5h2.25M3.75 3h-1.5m1.5 0h16.5m0 0h1.5m-1.5 0v11.25A2.25 2.25 0 0 1 18 16.5h-2.25m-7.5 0h7.5m-7.5 0-1 3m8.5-3 1 3m0 0 .5 1.5m-.5-1.5h-9.5m0 0-.5 1.5M9 11.25v1.5M12 9v3.75m3-6v6"
                  />
                </svg>
                <span class="truncate"
                  >{chartConfig?.title || "Chart View"}</span
                >
              </div>
              <button
                class="btn btn-ghost btn-xs btn-circle"
                aria-label={isCollapsed ? "Expand chart" : "Collapse chart"}
                title={isCollapsed ? "Expand chart" : "Collapse chart"}
                onclick={(e) => {
                  e.stopPropagation();
                  isCollapsed = !isCollapsed;
                }}
              >
                <svg
                  xmlns="http://www.w3.org/2000/svg"
                  fill="none"
                  viewBox="0 0 24 24"
                  stroke-width="1.5"
                  stroke="currentColor"
                  class={`size-4 transition-transform duration-200 ${isCollapsed ? "-rotate-90" : "rotate-0"}`}
                >
                  <path
                    stroke-linecap="round"
                    stroke-linejoin="round"
                    d="m19.5 8.25-7.5 7.5-7.5-7.5"
                  />
                </svg>
              </button>
            </div>
            {#if !isCollapsed}
              <div
                class="bg-white p-4 dark:bg-[#1d232a]"
                style="height: 520px;"
              >
                {#if chartConfig && AppChartComp}
                  <AppChartComp
                    config={chartConfig}
                    data={Array.isArray(message.data) ? message.data : []}
                  />
                {:else if chartConfig}
                  <div
                    class="flex h-full items-center justify-center text-sm text-muted-foreground"
                  >
                    Loading chart…
                  </div>
                {:else}
                  <div
                    class="flex h-full items-center justify-center text-center text-sm text-muted-foreground"
                  >
                    Unable to render chart (invalid response).
                  </div>
                {/if}
              </div>
            {/if}
          </div>

          <!-- Structured Table (framework-agnostic config from backend) -->
        {:else if message.output_mode === "structured_table" && message.output}
          {@const tableConfig = parseOutputConfig(message.output)}
          <div
            class="border-base-300 bg-base-100 rounded-box border overflow-hidden"
          >
            <div
              class="border-b border-base-300 bg-base-200 p-2 px-4 flex items-center justify-between text-sm font-medium cursor-pointer hover:bg-base-300/50 transition-colors"
              onclick={() => (isCollapsed = !isCollapsed)}
              role="button"
              tabindex="0"
              onkeydown={(e) =>
                e.key === "Enter" && (isCollapsed = !isCollapsed)}
            >
              <div class="flex items-center gap-2">
                <Icon icon="mdi:table" class="size-4 text-blue-500" />
                <span class="truncate"
                  >{tableConfig?.title || "Table View"}</span
                >
              </div>
              <button
                class="btn btn-ghost btn-xs btn-circle"
                aria-label={isCollapsed ? "Expand table" : "Collapse table"}
                title={isCollapsed ? "Expand table" : "Collapse table"}
                onclick={(e) => {
                  e.stopPropagation();
                  isCollapsed = !isCollapsed;
                }}
              >
                <Icon
                  icon="mdi:chevron-down"
                  class={`size-4 transition-transform duration-200 ${isCollapsed ? "-rotate-90" : "rotate-0"}`}
                />
              </button>
            </div>
            {#if !isCollapsed}
              <div class="p-2">
                {#if tableConfig && Array.isArray(message.data) && message.data.length}
                  <DataTable
                    data={message.data}
                    columns={Array.isArray(tableConfig.columns)
                      ? tableConfig.columns.map((c: any) => c.name)
                      : undefined}
                    {chartBackend}
                  />
                {:else}
                  <div
                    class="flex items-center justify-center p-6 text-center text-sm text-muted-foreground"
                  >
                    Unable to render table (no data).
                  </div>
                {/if}
              </div>
            {/if}
          </div>

          <!-- Structured Map (Leaflet layers + viewport from backend) -->
        {:else if message.output_mode === "structured_map" && message.output}
          {@const mapConfig = parseOutputConfig(message.output)}
          <div
            class="border-base-300 bg-base-100 rounded-box border overflow-hidden"
          >
            <div
              class="border-b border-base-300 bg-base-200 p-2 px-4 flex items-center justify-between text-sm font-medium cursor-pointer hover:bg-base-300/50 transition-colors"
              onclick={() => (isCollapsed = !isCollapsed)}
              role="button"
              tabindex="0"
              onkeydown={(e) =>
                e.key === "Enter" && (isCollapsed = !isCollapsed)}
            >
              <div class="flex items-center gap-2">
                <Icon icon="mdi:map-outline" class="size-4 text-blue-500" />
                <span class="truncate">{mapConfig?.title || "Map View"}</span>
              </div>
              <button
                class="btn btn-ghost btn-xs btn-circle"
                aria-label={isCollapsed ? "Expand map" : "Collapse map"}
                title={isCollapsed ? "Expand map" : "Collapse map"}
                onclick={(e) => {
                  e.stopPropagation();
                  isCollapsed = !isCollapsed;
                }}
              >
                <Icon
                  icon="mdi:chevron-down"
                  class={`size-4 transition-transform duration-200 ${isCollapsed ? "-rotate-90" : "rotate-0"}`}
                />
              </button>
            </div>
            {#if !isCollapsed}
              <div style="height: 480px;">
                {#if mapConfig && StructuredMapComp}
                  <StructuredMapComp
                    config={mapConfig}
                    data={Array.isArray(message.data) ? message.data : []}
                    {chatbotId}
                  />
                {:else if mapConfig}
                  <div
                    class="flex h-full items-center justify-center text-sm text-muted-foreground"
                  >
                    Loading map…
                  </div>
                {:else}
                  <div
                    class="flex h-full items-center justify-center text-center text-sm text-muted-foreground"
                  >
                    Unable to render map (invalid response).
                  </div>
                {/if}
              </div>
            {/if}
          </div>

          <!-- Native Map Rendering -->
        {:else if message.output_mode === "map" && hasData && Array.isArray(message.data)}
          {@const cols =
            message.data.length > 0 ? Object.keys(message.data[0]) : []}
          {@const lowerCols = cols.map((c) => c.toLowerCase())}
          {@const latCol =
            cols[lowerCols.findIndex((c) => c === "latitude" || c === "lat")] ||
            cols[lowerCols.findIndex((c) => c.includes("lat"))] ||
            ""}
          {@const lngCol =
            cols[
              lowerCols.findIndex(
                (c) =>
                  c === "longitude" ||
                  c === "lng" ||
                  c === "lon" ||
                  c === "long",
              )
            ] ||
            cols[
              lowerCols.findIndex((c) => c.includes("lng") || c.includes("lon"))
            ] ||
            ""}
          <div
            class="border-base-300 bg-base-100 rounded-box border overflow-hidden"
          >
            <div
              class="border-b border-base-300 bg-base-200 p-2 px-4 flex items-center justify-between text-sm font-medium cursor-pointer hover:bg-base-300/50 transition-colors"
              onclick={() => (isCollapsed = !isCollapsed)}
              role="button"
              tabindex="0"
              onkeydown={(e) =>
                e.key === "Enter" && (isCollapsed = !isCollapsed)}
            >
              <div class="flex items-center gap-2">
                <svg
                  xmlns="http://www.w3.org/2000/svg"
                  fill="none"
                  viewBox="0 0 24 24"
                  stroke-width="1.5"
                  stroke="currentColor"
                  class="size-4 text-green-500"
                >
                  <path
                    stroke-linecap="round"
                    stroke-linejoin="round"
                    d="M9 6.75V15m6-6v8.25m.503 3.498 4.875-2.437c.381-.19.622-.58.622-1.006V4.82c0-.836-.88-1.38-1.628-1.006l-3.869 1.934c-.317.159-.69.159-1.006 0L9.503 3.252a1.125 1.125 0 0 0-1.006 0L3.622 5.689C3.24 5.88 3 6.27 3 6.695V19.18c0 .836.88 1.38 1.628 1.006l3.869-1.934c.317-.159.69-.159 1.006 0l4.994 2.497c.317.158.69.158 1.006 0Z"
                  />
                </svg>
                Map View
                <span
                  class="badge badge-sm border-none bg-green-100 text-green-700"
                  >{message.data.length} points</span
                >
              </div>
              <button
                class="btn btn-ghost btn-xs btn-circle"
                aria-label={isCollapsed ? "Expand map" : "Collapse map"}
                title={isCollapsed ? "Expand map" : "Collapse map"}
                onclick={(e) => {
                  e.stopPropagation();
                  isCollapsed = !isCollapsed;
                }}
              >
                <svg
                  xmlns="http://www.w3.org/2000/svg"
                  fill="none"
                  viewBox="0 0 24 24"
                  stroke-width="1.5"
                  stroke="currentColor"
                  class={`size-4 transition-transform duration-200 ${isCollapsed ? "-rotate-90" : "rotate-0"}`}
                >
                  <path
                    stroke-linecap="round"
                    stroke-linejoin="round"
                    d="m19.5 8.25-7.5 7.5-7.5-7.5"
                  />
                </svg>
              </button>
            </div>
            {#if !isCollapsed}
              <div class="p-0">
                {#if DataMapComp}
                  <DataMapComp
                    data={message.data}
                    config={{
                      type: "map",
                      mapLatColumn: latCol,
                      mapLngColumn: lngCol,
                      mapLabelColumns: cols.filter(
                        (c) => c !== latCol && c !== lngCol,
                      ),
                      title: "",
                    }}
                    onCopyToChartCanvas={onCopyChartToChartCanvas
                      ? (d, c) => onCopyChartToChartCanvas!(d, c)
                      : undefined}
                  />
                {:else}
                  <div
                    class="flex h-64 items-center justify-center text-sm text-muted-foreground"
                  >
                    Loading map…
                  </div>
                {/if}
              </div>
            {/if}
          </div>

          <!-- Map from htmlResponse (agent returned Leaflet HTML but no structured data) -->
        {:else if message.output_mode === "map" && message.htmlResponse}
          {@const mapData = extractMapDataFromHtml(message.htmlResponse)}
          {#if mapData.length > 0}
            <!-- Render native DataMap from extracted coordinates -->
            {@const eCols = Object.keys(mapData[0])}
            {@const eLower = eCols.map((c) => c.toLowerCase())}
            {@const eLatCol =
              eCols[eLower.findIndex((c) => c === "latitude" || c === "lat")] ||
              eCols[eLower.findIndex((c) => c.includes("lat"))] ||
              "lat"}
            {@const eLngCol =
              eCols[
                eLower.findIndex(
                  (c) =>
                    c === "longitude" ||
                    c === "lng" ||
                    c === "lon" ||
                    c === "long",
                )
              ] ||
              eCols[
                eLower.findIndex((c) => c.includes("lng") || c.includes("lon"))
              ] ||
              "lng"}
            <div
              class="border-base-300 bg-base-100 rounded-box border overflow-hidden"
            >
              <div
                class="border-b border-base-300 bg-base-200 p-2 px-4 flex items-center justify-between text-sm font-medium cursor-pointer hover:bg-base-300/50 transition-colors"
                onclick={() => (isCollapsed = !isCollapsed)}
                role="button"
                tabindex="0"
                onkeydown={(e) =>
                  e.key === "Enter" && (isCollapsed = !isCollapsed)}
              >
                <div class="flex items-center gap-2">
                  <svg
                    xmlns="http://www.w3.org/2000/svg"
                    fill="none"
                    viewBox="0 0 24 24"
                    stroke-width="1.5"
                    stroke="currentColor"
                    class="size-4 text-green-500"
                  >
                    <path
                      stroke-linecap="round"
                      stroke-linejoin="round"
                      d="M9 6.75V15m6-6v8.25m.503 3.498 4.875-2.437c.381-.19.622-.58.622-1.006V4.82c0-.836-.88-1.38-1.628-1.006l-3.869 1.934c-.317.159-.69.159-1.006 0L9.503 3.252a1.125 1.125 0 0 0-1.006 0L3.622 5.689C3.24 5.88 3 6.27 3 6.695V19.18c0 .836.88 1.38 1.628 1.006l3.869-1.934c.317-.159.69-.159 1.006 0l4.994 2.497c.317.158.69.158 1.006 0Z"
                    />
                  </svg>
                  Map View
                  <span
                    class="badge badge-sm border-none bg-green-100 text-green-700"
                    >{mapData.length} points</span
                  >
                </div>
                <button
                  class="btn btn-ghost btn-xs btn-circle"
                  aria-label={isCollapsed ? "Expand map" : "Collapse map"}
                  title={isCollapsed ? "Expand map" : "Collapse map"}
                  onclick={(e) => {
                    e.stopPropagation();
                    isCollapsed = !isCollapsed;
                  }}
                >
                  <svg
                    xmlns="http://www.w3.org/2000/svg"
                    fill="none"
                    viewBox="0 0 24 24"
                    stroke-width="1.5"
                    stroke="currentColor"
                    class={`size-4 transition-transform duration-200 ${isCollapsed ? "-rotate-90" : "rotate-0"}`}
                  >
                    <path
                      stroke-linecap="round"
                      stroke-linejoin="round"
                      d="m19.5 8.25-7.5 7.5-7.5-7.5"
                    />
                  </svg>
                </button>
              </div>
              {#if !isCollapsed}
                <div class="p-0">
                  {#if DataMapComp}
                    <DataMapComp
                      data={mapData}
                      config={{
                        type: "map",
                        mapLatColumn: eLatCol,
                        mapLngColumn: eLngCol,
                        mapLabelColumns: eCols.filter(
                          (c) =>
                            ![
                              "lat",
                              "lng",
                              "lon",
                              "long",
                              "latitude",
                              "longitude",
                            ].includes(c.toLowerCase()),
                        ),
                        title: "",
                      }}
                      onCopyToChartCanvas={onCopyChartToChartCanvas
                        ? (d, c) => onCopyChartToChartCanvas!(d, c)
                        : undefined}
                    />
                  {:else}
                    <div
                      class="flex h-64 items-center justify-center text-sm text-muted-foreground"
                    >
                      Loading map…
                    </div>
                  {/if}
                </div>
              {/if}
            </div>

            <!-- Data action buttons (icon-only with tooltips) -->
            <div class="mt-2 flex items-center gap-1">
              <AppTooltip
                content="Show data ({mapData.length})"
                placement="bottom"
              >
                <button
                  class="inline-flex items-center justify-center size-7 rounded-md text-blue-600 bg-blue-50 hover:bg-blue-100 transition-colors"
                  onclick={() => (showData = !showData)}
                >
                  <Icon icon="mdi:table" class="size-3.5" />
                </button>
              </AppTooltip>
              {#if onOpenSpreadsheet}
                <AppTooltip content="Open in Spreadsheet" placement="bottom">
                  <button
                    class="inline-flex items-center justify-center size-7 rounded-md text-emerald-600 bg-emerald-50 hover:bg-emerald-100 transition-colors"
                    onclick={() =>
                      onOpenSpreadsheet && onOpenSpreadsheet(mapData)}
                  >
                    <Icon icon="mdi:grid" class="size-3.5" />
                  </button>
                </AppTooltip>
              {/if}
            </div>

            {#if showData}
              <div
                class="mt-3 animate-in fade-in slide-in-from-top-2 duration-200"
              >
                <DataTable data={mapData} {chartBackend} />
              </div>
            {/if}
          {:else}
            <!-- Fallback: render iframe with relaxed sandbox for map content -->
            <div
              class="border-base-300 bg-base-100 rounded-box border overflow-hidden"
            >
              <div
                class="border-b border-base-300 bg-base-200 p-2 px-4 flex items-center justify-between text-sm font-medium cursor-pointer hover:bg-base-300/50 transition-colors"
                onclick={() => (isCollapsed = !isCollapsed)}
                role="button"
                tabindex="0"
                onkeydown={(e) =>
                  e.key === "Enter" && (isCollapsed = !isCollapsed)}
              >
                <div class="flex items-center gap-2">
                  <svg
                    xmlns="http://www.w3.org/2000/svg"
                    fill="none"
                    viewBox="0 0 24 24"
                    stroke-width="1.5"
                    stroke="currentColor"
                    class="size-4 text-green-500"
                  >
                    <path
                      stroke-linecap="round"
                      stroke-linejoin="round"
                      d="M9 6.75V15m6-6v8.25m.503 3.498 4.875-2.437c.381-.19.622-.58.622-1.006V4.82c0-.836-.88-1.38-1.628-1.006l-3.869 1.934c-.317.159-.69.159-1.006 0L9.503 3.252a1.125 1.125 0 0 0-1.006 0L3.622 5.689C3.24 5.88 3 6.27 3 6.695V19.18c0 .836.88 1.38 1.628 1.006l3.869-1.934c.317-.159.69-.159 1.006 0l4.994 2.497c.317.158.69.158 1.006 0Z"
                    />
                  </svg>
                  Interactive Map
                </div>
                <button
                  class="btn btn-ghost btn-xs btn-circle"
                  aria-label={isCollapsed ? "Expand map" : "Collapse map"}
                  title={isCollapsed ? "Expand map" : "Collapse map"}
                  onclick={(e) => {
                    e.stopPropagation();
                    isCollapsed = !isCollapsed;
                  }}
                >
                  <svg
                    xmlns="http://www.w3.org/2000/svg"
                    fill="none"
                    viewBox="0 0 24 24"
                    stroke-width="1.5"
                    stroke="currentColor"
                    class={`size-4 transition-transform duration-200 ${isCollapsed ? "-rotate-90" : "rotate-0"}`}
                  >
                    <path
                      stroke-linecap="round"
                      stroke-linejoin="round"
                      d="m19.5 8.25-7.5 7.5-7.5-7.5"
                    />
                  </svg>
                </button>
              </div>
              {#if !isCollapsed}
                <div class="p-0">
                  <iframe
                    class="w-full rounded-lg"
                    style="min-height: 500px; background: #ffffff; border: none;"
                    srcdoc={message.htmlResponse}
                    sandbox="allow-scripts allow-forms allow-popups"
                    title="Map visualization"
                  ></iframe>
                </div>
              {/if}
            </div>
          {/if}

          <!-- SQL Analysis Artifact (DatabaseAgent / sql_analyst) -->
        {:else if sqlAnalysis && sqlArtifact}
          <SqlArtifactCard
            sql={sqlArtifact}
            rowCount={sqlAnalysis.data?.row_count ?? null}
            executionTimeMs={sqlAnalysis.data?.execution_time_ms ?? null}
            onSendToEditor={onSqlArtifact}
          />

          <!-- HTML Response Iframe (Fallback for full HTML documents) -->
        {:else if message.htmlResponse}
          <div
            class="border-base-300 bg-base-100 rounded-box border overflow-hidden"
          >
            <div
              class="border-b border-base-300 bg-base-200 p-2 px-4 flex items-center justify-between text-sm font-medium cursor-pointer hover:bg-base-300/50 transition-colors"
              onclick={() => (isCollapsed = !isCollapsed)}
              role="button"
              tabindex="0"
              onkeydown={(e) =>
                e.key === "Enter" && (isCollapsed = !isCollapsed)}
            >
              <div class="flex items-center gap-2">
                <svg
                  xmlns="http://www.w3.org/2000/svg"
                  fill="none"
                  viewBox="0 0 24 24"
                  stroke-width="1.5"
                  stroke="currentColor"
                  class="text-secondary h-4 w-4"
                >
                  <path
                    stroke-linecap="round"
                    stroke-linejoin="round"
                    d="M17.25 6.75 22.5 12l-5.25 5.25m-10.5 0L1.5 12l5.25-5.25m7.5-3-4.5 16.5"
                  />
                </svg>
                Interactive View ({message.output_mode || "html"})
              </div>
              <button
                class="btn btn-ghost btn-xs btn-circle"
                aria-label={isCollapsed ? "Expand view" : "Collapse view"}
                title={isCollapsed ? "Expand view" : "Collapse view"}
                onclick={(e) => {
                  e.stopPropagation();
                  isCollapsed = !isCollapsed;
                }}
              >
                <svg
                  xmlns="http://www.w3.org/2000/svg"
                  fill="none"
                  viewBox="0 0 24 24"
                  stroke-width="1.5"
                  stroke="currentColor"
                  class={`size-4 transition-transform duration-200 ${isCollapsed ? "-rotate-90" : "rotate-0"}`}
                >
                  <path
                    stroke-linecap="round"
                    stroke-linejoin="round"
                    d="m19.5 8.25-7.5 7.5-7.5-7.5"
                  />
                </svg>
              </button>
            </div>
            {#if !isCollapsed}
              <div class="p-0">
                <iframe
                  class="w-full rounded-lg"
                  style="min-height: 500px; background: #ffffff; border: 1px solid #ccc;"
                  srcdoc={message.htmlResponse}
                  sandbox="allow-scripts allow-forms allow-popups"
                  title="Response visualization"
                ></iframe>
              </div>
            {/if}
          </div>
        {/if}

        <!-- Sources Panel — shown whenever the response carries sources (RAG/bot) -->
        {#if !isStreaming && message.sources && message.sources.length > 0}
          <SourcesPanel sources={message.sources} />
        {/if}

        <!-- Data Display + action row. The botMode guard hides the row
             for chatbot-style surfaces. SQL artifacts have their own
             dedicated card (rendered above) with a primary CTA, so they
             don't need a button here. -->
        {#if !isStreaming && hasData && !botMode}
          {@const isTabularData =
            Array.isArray(message.data) &&
            message.data.length > 0 &&
            message.output_mode !== "json"}
          {@const dataCount = Array.isArray(message.data)
            ? message.data.length
            : message.data
              ? Object.keys(message.data).length
              : 0}
          <div class="mt-2 flex items-center gap-1">
            {#if hasData && showDataActions}
              <AppTooltip
                content={isTabularData
                  ? `Show data (${dataCount})`
                  : `Show JSON (${dataCount})`}
                placement="bottom"
              >
                <button
                  class="inline-flex items-center justify-center size-7 rounded-md text-blue-600 bg-blue-50 hover:bg-blue-100 transition-colors"
                  onclick={() => (showData = !showData)}
                >
                  <Icon
                    icon={isTabularData ? "mdi:table" : "mdi:code-json"}
                    class="size-3.5"
                  />
                </button>
              </AppTooltip>
            {/if}
            {#if isTabularData && showDataActions}
              {#if onMoveToCanvas || onMoveTableDataToCanvas}
                <!-- Table format choice dropdown -->
                <div class="relative">
                  <AppTooltip content="Copy table to Canvas" placement="bottom">
                    <button
                      class="inline-flex items-center justify-center size-7 rounded-md text-teal-600 bg-teal-50 hover:bg-teal-100 transition-colors"
                      onclick={() =>
                        (tableFormatMenuOpen = !tableFormatMenuOpen)}
                    >
                      <Icon icon="mdi:note-plus-outline" class="size-3.5" />
                    </button>
                  </AppTooltip>
                  {#if tableFormatMenuOpen}
                    <!-- Backdrop -->
                    <div
                      class="fixed inset-0 z-40"
                      onclick={() => (tableFormatMenuOpen = false)}
                      onkeydown={(e) =>
                        e.key === "Escape" && (tableFormatMenuOpen = false)}
                      role="button"
                      tabindex="-1"
                    ></div>
                    <!-- Dropdown -->
                    <div
                      class="absolute bottom-full left-0 z-50 mb-1 w-44 rounded-md border border-border bg-popover shadow-md py-1"
                    >
                      {#if onMoveToCanvas}
                        <button
                          class="flex items-center gap-2 w-full px-3 py-1.5 text-xs text-foreground hover:bg-muted transition-colors"
                          onclick={(e) => {
                            e.stopPropagation();
                            const rows = message.data as Record<
                              string,
                              unknown
                            >[];
                            if (!rows.length) {
                              tableFormatMenuOpen = false;
                              return;
                            }
                            const headers = Object.keys(rows[0]);
                            const mdHeader = `| ${headers.join(" | ")} |`;
                            const mdSep = `| ${headers.map(() => "---").join(" | ")} |`;
                            const mdRows = rows
                              .map(
                                (row) =>
                                  `| ${headers.map((h) => String(row[h] ?? "")).join(" | ")} |`,
                              )
                              .join("\n");
                            const markdown = `${mdHeader}\n${mdSep}\n${mdRows}`;
                            onMoveToCanvas!(markdown);
                            tableFormatMenuOpen = false;
                          }}
                        >
                          <Icon icon="mdi:table-large" class="size-3.5" />
                          As Markdown
                        </button>
                      {/if}
                      {#if onMoveTableDataToCanvas}
                        <button
                          class="flex items-center gap-2 w-full px-3 py-1.5 text-xs text-foreground hover:bg-muted transition-colors"
                          onclick={(e) => {
                            e.stopPropagation();
                            const rows = message.data as Record<
                              string,
                              unknown
                            >[];
                            if (!rows.length) {
                              tableFormatMenuOpen = false;
                              return;
                            }
                            const columns = Object.keys(rows[0]);
                            onMoveTableDataToCanvas!(rows, columns);
                            tableFormatMenuOpen = false;
                          }}
                        >
                          <Icon icon="mdi:table-edit" class="size-3.5" />
                          As Interactive Table
                        </button>
                      {/if}
                    </div>
                  {/if}
                </div>
              {/if}
              <AppTooltip content="Download CSV" placement="bottom">
                <button
                  class="inline-flex items-center justify-center size-7 rounded-md text-violet-600 bg-violet-50 hover:bg-violet-100 transition-colors"
                  onclick={() => {
                    // Generate and download CSV
                    const data = message.data as Record<string, unknown>[];
                    const headers = Object.keys(data[0]);
                    const csv = [
                      headers.join(","),
                      ...data.map((row) =>
                        headers
                          .map((h) => JSON.stringify(row[h] ?? ""))
                          .join(","),
                      ),
                    ].join("\n");
                    const blob = new Blob([csv], { type: "text/csv" });
                    const url = URL.createObjectURL(blob);
                    const a = document.createElement("a");
                    a.href = url;
                    a.download = `data-${message.id}.csv`;
                    a.click();
                    URL.revokeObjectURL(url);
                  }}
                >
                  <Icon icon="mdi:download" class="size-3.5" />
                </button>
              </AppTooltip>
              {#if onOpenSpreadsheet}
                <AppTooltip content="Open in Spreadsheet" placement="bottom">
                  <button
                    class="inline-flex items-center justify-center size-7 rounded-md text-emerald-600 bg-emerald-50 hover:bg-emerald-100 transition-colors"
                    onclick={() =>
                      onOpenSpreadsheet && onOpenSpreadsheet(message.data)}
                  >
                    <Icon icon="mdi:grid" class="size-3.5" />
                  </button>
                </AppTooltip>
              {/if}
              {#if onCreateInfographic}
                <AppTooltip content="Create Infographic" placement="bottom">
                  <button
                    class="inline-flex items-center justify-center size-7 rounded-md text-purple-600 bg-purple-50 hover:bg-purple-100 transition-colors"
                    onclick={() =>
                      onCreateInfographic &&
                      onCreateInfographic(
                        message.content || "",
                        message.data as Record<string, unknown>[],
                      )}
                  >
                    <Icon icon="mdi:image-text" class="size-3.5" />
                  </button>
                </AppTooltip>
              {/if}
            {/if}
          </div>

          {#if showData}
            <div
              class="mt-3 animate-in fade-in slide-in-from-top-2 duration-200"
            >
              {#if isTabularData}
                <DataTable
                  data={message.data}
                  {chartBackend}
                  {onCopyChartToCanvas}
                  {onCopyChartToChartCanvas}
                />
              {:else}
                <pre
                  class="bg-[#1f2937] text-gray-100 rounded-lg p-4 text-sm overflow-auto max-h-96"><code
                    class="language-json"
                    >{JSON.stringify(message.data, null, 2)}</code
                  ></pre>
              {/if}
            </div>
          {/if}
        {/if}

        <!-- Metadata Display -->
        {#if showMetadata && message.metadata}
          <div class="mt-2 animate-in fade-in slide-in-from-top-2">
            <div
              class="text-xs font-semibold text-slate-500 mb-1 flex items-center gap-2"
            >
              <span class="badge badge-xs badge-info">Metadata</span>
              <span>{message.metadata.model || "Unknown Model"}</span>
            </div>
            <pre
              class="bg-[var(--agent-chat-code-bg)] text-[var(--agent-chat-code-fg)] rounded-lg p-3 text-xs overflow-auto max-h-60"><code
                class="language-json"
                >{JSON.stringify(message.metadata, null, 2)}</code
              ></pre>
          </div>
        {/if}
      </div>
    {/if}

    <!-- Feedback Footer -->
    {#if !isStreaming && !isUser && !isError && message.metadata?.turn_id}
      <div
        class="mt-2 flex items-center justify-end gap-2 border-t border-slate-200 dark:border-slate-700 pt-2 opacity-0 group-hover:opacity-100 transition-opacity"
      >
        {#if !compact}
          <span class="text-[10px] text-slate-400 mr-auto"
            >Rate this response:</span
          >
        {/if}

        <!-- Thumbs Up with QuickRating dropdown -->
        <div class="relative">
          <button
            class={`btn btn-ghost btn-xs btn-circle ${feedbackState.like === true ? "text-green-500" : "text-slate-400 hover:text-green-500"}`}
            onclick={(e) => {
              e.stopPropagation();
              toggleQuickRating("positive");
            }}
            title="Helpful"
          >
            {#if feedbackState.like === true}
              <Icon icon="mdi:thumb-up" class="h-4 w-4" />
            {:else}
              <Icon icon="mdi:thumb-up-outline" class="h-4 w-4" />
            {/if}
          </button>

          {#if quickRatingType === "positive" && sessionId && chatbotId}
            <QuickRating
              type="positive"
              messageId={message.metadata.turn_id}
              {sessionId}
              {chatbotId}
              onSubmit={() => handleQuickRatingSubmit("positive")}
              onClose={() => (quickRatingType = null)}
            />
          {/if}
        </div>

        <!-- Thumbs Down with QuickRating dropdown -->
        <div class="relative">
          <button
            class={`btn btn-ghost btn-xs btn-circle ${feedbackState.like === false ? "text-red-500" : "text-slate-400 hover:text-red-500"}`}
            onclick={(e) => {
              e.stopPropagation();
              toggleQuickRating("negative");
            }}
            title="Not Helpful"
          >
            {#if feedbackState.like === false}
              <Icon icon="mdi:thumb-down" class="h-4 w-4" />
            {:else}
              <Icon icon="mdi:thumb-down-outline" class="h-4 w-4" />
            {/if}
          </button>

          {#if quickRatingType === "negative" && sessionId && chatbotId}
            <QuickRating
              type="negative"
              messageId={message.metadata.turn_id}
              {sessionId}
              {chatbotId}
              onSubmit={() => handleQuickRatingSubmit("negative")}
              onClose={() => (quickRatingType = null)}
            />
          {/if}
        </div>

        <!-- Detailed Feedback Button -->
        {#if onDetailedFeedback}
          <div
            class="border-l border-slate-200 dark:border-slate-600 pl-2 ml-1"
          >
            <button
              class="btn btn-ghost btn-xs btn-circle text-slate-400 hover:text-blue-500"
              onclick={() =>
                onDetailedFeedback(message.metadata?.turn_id || "")}
              title="Provide detailed feedback"
            >
              <Icon icon="mdi:comment-text-outline" class="h-4 w-4" />
            </button>
          </div>
        {/if}

        <!-- More Actions (three-dots menu) -->
        {#if message.metadata || onDelete || (onRegenerate && isLastAssistantMessage)}
          <div class="relative">
            <button
              class="btn btn-ghost btn-xs btn-circle text-slate-400 hover:text-slate-600"
              onclick={toggleMoreMenu}
              title="More actions"
            >
              <Icon icon="mdi:dots-vertical" class="h-4 w-4" />
            </button>

            {#if showMoreMenu}
              <div
                bind:this={moreMenuRef}
                class="absolute bottom-full right-0 mb-1 z-50 w-44 rounded-lg border border-border bg-popover shadow-lg py-1"
                role="menu"
              >
                <!-- Show Metadata -->
                {#if message.metadata}
                  <button
                    class="flex w-full items-center gap-2 px-3 py-1.5 text-xs text-foreground hover:bg-accent transition-colors"
                    onclick={() => {
                      showMetadata = !showMetadata;
                      showMoreMenu = false;
                    }}
                    role="menuitem"
                  >
                    <Icon
                      icon="mdi:information-outline"
                      class="h-4 w-4 text-info"
                    />
                    <span
                      >{showMetadata ? "Hide Metadata" : "Show Metadata"}</span
                    >
                  </button>
                {/if}

                <!-- Regenerate Response -->
                {#if onRegenerate && isLastAssistantMessage}
                  <button
                    class="flex w-full items-center gap-2 px-3 py-1.5 text-xs text-foreground hover:bg-accent transition-colors"
                    onclick={(e) => {
                      showMoreMenu = false;
                      toggleRegenMenu(e);
                    }}
                    role="menuitem"
                  >
                    <Icon icon="mdi:refresh" class="h-4 w-4 text-primary" />
                    <span>Regenerate Response</span>
                  </button>
                {/if}

                <!-- Remove Message -->
                {#if onDelete}
                  <div
                    class="border-t border-slate-200 dark:border-slate-700 my-1"
                  ></div>
                  <button
                    class="flex w-full items-center gap-2 px-3 py-1.5 text-xs text-red-600 dark:text-red-400 hover:bg-red-50 dark:hover:bg-red-900/20 transition-colors"
                    onclick={() => {
                      onDelete!(message.id, message.metadata?.turn_id || "");
                      showMoreMenu = false;
                    }}
                    role="menuitem"
                  >
                    <Icon icon="mdi:trash-can-outline" class="h-4 w-4" />
                    <span>Remove Message</span>
                  </button>
                {/if}
              </div>
            {/if}
          </div>
        {/if}
      </div>
    {/if}
  </div>
</div>
