<script lang="ts">
  import { onMount, tick, untrack } from "svelte";
  import { marked } from "marked";
  import { agentChatSidebarItem } from "./agent-chat.variants";
  import { v4 as uuidv4 } from "uuid";
  import { ChatService } from "$lib/services/chat-db";
  import {
    chatWithAgent,
    callAgentMethod,
    sendVoiceNote,
    checkVoiceSupport,
  } from "$lib/api/agent";
  import type { RecordedVoiceNote } from "$lib/utils/voice-recorder";
  import { chatWithBot } from "$lib/api/botChat";
  import { createApiClient } from "$lib/api/http";
  import { streamChatWithAgent, streamChatWithBot } from "$lib/api/stream";
  import { ChunkAccumulator } from "$lib/utils/chunk-accumulator";
  import { browser } from "$app/environment";
  import type {
    AgentMessage,
    AgentChatRequest,
    InteractiveArtifactResult,
    InteractiveArtifactTabData,
  } from "$lib/types/agent";
  import type { BotChatRequest } from "$lib/types/bot-chat";
  import {
    stripSourcesFromResponse,
    resolveDocumentSources,
    resolveAgentSources,
  } from "$lib/utils/bot-response-parser";
  import ChatBubble from "./ChatBubble.svelte";
  import ChatInput from "./ChatInput.svelte";
  import ConversationList from "./ConversationList.svelte";
  import FeedbackModal from "./FeedbackModal.svelte";
  import PromptPills from "./PromptPills.svelte";
  import StarterPromptBubbles from "./StarterPromptBubbles.svelte";
  import PromptLibraryModal from "./PromptLibraryModal.svelte";
  import * as promptStore from "$lib/stores/prompt-library.svelte";
  import type { Prompt } from "$lib/types/prompt-library";

  import Icon from "@iconify/svelte";
  import { toastStore } from "$lib/stores/toast.svelte";
  import { notificationStore } from "$lib/stores/notifications.svelte";
  import { wsService } from "$lib/services/websocket-service";
  import { onDestroy } from "svelte";
  import * as chatLayout from "$lib/stores/agentchat-layout.svelte";
  // ai-parrot (FEAT-476 TASK-2594): DataManagementModal, DatasetConfigModal
  // (features.datasets, TASK-2596), CanvasPanel (features.canvas,
  // TASK-2595) and AvatarViewer/VoiceNativeAvatarViewer (features.avatar,
  // TASK-2596) are no longer static imports — every gated component is
  // reached only through `{#if features.X}{#await import(...)}` at its
  // single render site below (spec §2 "Feature flags"). canvasTabManager
  // and canvas-block-types stay always-on: they are dependency-free state/
  // type modules AgentChat's core message-handling calls unconditionally
  // (creating/updating canvas tabs even before the visual CanvasPanel is
  // rendered) — only CanvasPanel.svelte itself (and the chart/map/rich-
  // editor bundles it pulls in) is gated.
  import * as canvasTabManager from "./canvas/canvas-tab-manager.svelte.js";
  import { createBlock, isCanvasBlockArray } from "./canvas/canvas-block-types";
  import type { CanvasBlock } from "./canvas/canvas-block-types";
  import IntegrationsMenu from "./integrations/IntegrationsMenu.svelte";
  import ConnectIntegrationPill from "./integrations/ConnectIntegrationPill.svelte";
  import { features } from "$lib/features";

  // FEAT-169: LiveAvatar Integration
  import { sendAvatarTextTurn, type AvatarStatus } from "$lib/api/avatar";
  import {
    loadAvatarPreference,
    saveAvatarPreference,
    markAvatarUnavailable,
    isAvatarUnavailable,
  } from "$lib/stores/avatar.svelte";
  import { clientStore } from "$lib/stores/client.svelte";

  // Props
  let {
    agentId,
    chatbotId,
    chartBackend = "chartjs",
    allow_custom_llm = false,
    apiUrl,
    welcomeIcon,
    botMode = false,
    enableCanvas = true,
    variant = "default",
    formatKwargs,
    context,
    onSqlArtifact,
    showDataActions = true,
    enableVoiceNotes = false,
    agentName,
  } = $props<{
    agentId: string;
    /** Chatbot UUID — required for Prompt Library API calls. If omitted, only local prompts load. */
    chatbotId?: string;
    chartBackend?: "chartjs" | "layerchart";
    allow_custom_llm?: boolean;
    apiUrl?: string;
    welcomeIcon?: string;
    botMode?: boolean;
    enableCanvas?: boolean;
    /**
     * Layout variant.
     * - `default` (current behavior): full layout with ConversationList aside, header dock, prompt pills.
     * - `compact`: hides the left ConversationList aside and the prompt-pills bar so the chat fits in a
     *   narrow panel (e.g. the QueryExecutor right rail). All other behavior is identical.
     */
    variant?: "default" | "compact";
    /**
     * Extra format/output hints forwarded into the agent request as `format_kwargs`.
     * Merged with the internally-computed format_kwargs (caller wins on key collisions).
     * NOTE: in the parrot framework `format_kwargs` is consumed by the response
     * formatter (html mode, table mode, etc), NOT by the LLM prompt. For
     * agent context use `context` instead.
     */
    formatKwargs?: Record<string, unknown>;
    /**
     * Free-form context string forwarded into the agent request as `context`.
     * Database-style agents (e.g. sql_analyst) inject it into the system prompt
     * via the `$user_context` template variable, so the LLM sees it on every
     * turn without the user having to repeat it. Plain text or short markdown
     * works best — keep it focused.
     */
    context?: string;
    /**
     * Optional handler invoked when the user clicks "Copy to Editor" on a
     * `` ```sql `` block in an assistant message. Passed through to every
     * rendered ChatBubble. Use it from surfaces that own a SQL editor
     * (e.g. the QuerySource Query Executor) to pipe agent suggestions
     * directly into the active query tab.
     */
    onSqlArtifact?: (sql: string) => void;
    /**
     * Whether ChatBubble shows the data-result action buttons (View JSON,
     * Copy table to Canvas, Download CSV, Open Spreadsheet, Infographic).
     * Default ``true``. Pass ``false`` from surfaces where the agent's
     * ``data`` field is incidental metadata rather than a runnable result —
     * e.g. the sql_analyst panel, where ``data`` is just schema info.
     */
    showDataActions?: boolean;
    /**
     * Whether the input area exposes a microphone for sending voice notes
     * (AgentTalk Voice — non-streaming round-trip: audio → STT → agent → TTS).
     * Default ``false``: voice notes are OFF unless a surface opts in. When
     * enabled, recorded notes are sent to ``/api/v1/agents/voice/{agentId}``
     * and the spoken answer is rendered as an inline player in the bubble.
     */
    enableVoiceNotes?: boolean;
    /**
     * Human-readable display name for the agent shown in the chat header.
     * Falls back to a formatted version of agentId (underscores → spaces, title case).
     */
    agentName?: string;
  }>();

  let isCompact = $derived(variant === "compact");

  let displayName = $derived(
    agentName ??
      agentId
        .replace(/_/g, " ")
        .replace(/\b\w/g, (c: string) => c.toUpperCase()),
  );

  // In bot mode, canvas is disabled by default unless explicitly enabled
  let effectiveEnableCanvas = $derived(
    botMode ? enableCanvas === true : enableCanvas,
  );

  // Scoped API client — uses custom URL when provided, global client otherwise
  let scopedClient = $derived(apiUrl ? createApiClient(apiUrl) : undefined);

  // Pagination
  const PAGE_SIZE = 10;
  let messageLimit = $state(PAGE_SIZE);
  let hasMoreMessages = $state(false);
  let loadingMore = $state(false);

  // Read the last-active session id BEFORE any $effect or $state has been
  // wired up. If we left ``currentSessionId`` initialised to ``null``, the
  // persistence effect declared below would fire on first run and immediately
  // remove the storage key — wiping the value we wanted to restore. The
  // matching async existence check in onMount validates the id is still
  // real (and clears it otherwise).
  const lastSessionStorageKey = `navigator:agentchat:lastSession:${agentId}`;
  let _initialSessionId: string | null = null;
  try {
    if (typeof localStorage !== "undefined") {
      _initialSessionId = localStorage.getItem(lastSessionStorageKey);
    }
  } catch {
    /* SSR / storage-disabled — degrade gracefully */
  }

  // State
  let currentSessionId = $state<string | null>(_initialSessionId);
  let messages = $state<AgentMessage[]>([]);
  let pendingQuestions = $state<
    Map<string, { query: string; controller: AbortController }>
  >(new Map());
  let chatContainer = $state<HTMLElement>();
  let messagesContent = $state<HTMLElement>(); // Inner scrollable content (for scroll anchoring)
  let drawerOpen = $state(false); // Mobile drawer
  let compactHistoryOpen = $state(false); // Compact variant history dropdown
  let inputText = $state(""); // External control for input text
  let currentConversationTitle = $state(""); // Title of the active conversation

  // Guard flag to prevent message reload during lazy conversation creation.
  // IMPORTANT: deliberately NOT $state — if it were $state, the $effect that
  // loads messages would track it as a dependency and re-fire when it resets
  // to false in handleSend's finally block, overwriting the optimistic state
  // with potentially incomplete backend data (bug: first userMsg disappears).
  let isCreatingNewConversation = false;

  // ai-parrot (FEAT-476 TASK-2596): guard for the session-load $effect
  // below's `else { messages = [] }` branch. Discovered while testing
  // voice-note degradation: a brand-new conversation whose *first* send
  // fails (policy-denial 401 in handleSend, or a voice 404 in
  // handleVoiceNote) drops the just-created conversation and resets
  // `currentSessionId` to null so the failed attempt leaves no trace —
  // but that reset alone made the $effect immediately wipe the
  // in-flight error bubble the same catch block had just written into
  // `messages`, so the user saw the empty welcome screen instead of an
  // explanation (a real, pre-existing bug — not previously caught
  // because the affected AgentChat.test.ts assertions happened to
  // resolve on `waitFor`'s first synchronous check, before the effect's
  // next tick). Deliberately NOT `$state`, same reasoning as
  // `isCreatingNewConversation` above — this is a one-shot flag the
  // effect consumes, not a value the effect should re-run on writing.
  let suppressSessionClearOnce = false;

  // Followup state
  let followupTurnId = $state<string | null>(null);
  let followupData = $state<any>(null);

  // Streaming state
  let streamEnabled = $state(false);
  let isStreaming = $state(false);
  let activeStreamController = $state<AbortController | null>(null);
  // ID of the message currently being streamed (for isStreaming prop on ChatBubble)
  let streamingMessageId = $state<string | null>(null);

  // Voice support: only true once feature-detection confirms the server has the
  // voice route registered. Starts false so the mic stays hidden until proven
  // available (probe runs in onMount, only when enableVoiceNotes is on).
  let voiceAvailable = $state(false);

  // Detailed Feedback Modal State
  let detailedFeedbackModalOpen = $state(false);
  let detailedFeedbackTargetTurnId = $state("");
  let detailedFeedbackTargetChatbotId = $state("");

  // Configuration Modal State
  let configModalOpen = $state(false);
  let datasetModalOpen = $state(false);
  let explainPrompt = $state(
    "Please explain these results in a concise manner.",
  );

  // Prompt Library Modal State
  let promptModalOpen = $state(false);

  // FEAT-169: LiveAvatar state
  let avatarEnabled = $state(false);
  let avatarLive = $state(false);
  let avatarCollapsed = $state(false);
  // tenantId is derived from the client store slug
  let tenantId = $derived(clientStore.getClient()?.slug);

  // Load avatar preference from localStorage when agentId is known
  $effect(() => {
    if (browser && agentId) {
      avatarEnabled = loadAvatarPreference(agentId);
    }
  });

  // The avatar/voice panels mount only when a session exists (the avatar backend
  // keys its LiveKit room by session_id). On a fresh chat `currentSessionId` is
  // null until the first message is sent, so toggling the avatar on would
  // silently render nothing. Create a session eagerly here — mirrors the lazy
  // creation in `handleSend`, and that send path then reuses this session.
  async function ensureSession() {
    if (currentSessionId) return;
    const sessionId = uuidv4();
    await ChatService.createConversation(agentId, sessionId);
    currentSessionId = sessionId;
  }

  async function handleAvatarToggle() {
    // ai-parrot (FEAT-476 TASK-2596): once this agent's avatar session has
    // proven unavailable (403/404) earlier this session, don't let the
    // user re-trigger a known-broken connect attempt — explain once.
    if (!avatarEnabled && isAvatarUnavailable(agentId)) {
      toastStore.error("Avatar is unavailable on this server.");
      return;
    }
    avatarEnabled = !avatarEnabled;
    saveAvatarPreference(agentId, avatarEnabled);
    // Phase A and Phase C both want the avatar tracks — only one may publish/mount.
    if (avatarEnabled) {
      voiceNativeEnabled = false;
      await ensureSession();
    }
  }

  function handleAvatarStatusChange(s: AvatarStatus) {
    avatarLive = s === "live";
    // On 403 (disabled): reset toggle OFF so tenant without opt-in doesn't re-trigger
    if (s === "disabled") {
      const wasAvailable = !isAvatarUnavailable(agentId);
      avatarEnabled = false;
      saveAvatarPreference(agentId, false);
      markAvatarUnavailable(agentId);
      if (wasAvailable) {
        toastStore.error("Avatar is unavailable on this server.");
      }
    }
  }

  // FEAT-243: voice-native (Phase C) avatar state. Distinct from the Phase A
  // avatar above: here the browser publishes its mic and turn-taking is native.
  let voiceNativeEnabled = $state(false);

  async function handleVoiceNativeToggle() {
    if (!voiceNativeEnabled && isAvatarUnavailable(agentId)) {
      toastStore.error("Avatar is unavailable on this server.");
      return;
    }
    voiceNativeEnabled = !voiceNativeEnabled;
    // Mutually exclusive with the Phase A avatar (both subscribe the avatar tracks).
    if (voiceNativeEnabled) {
      avatarEnabled = false;
      saveAvatarPreference(agentId, false);
      await ensureSession();
    }
  }

  function handleVoiceNativeStatusChange(s: AvatarStatus) {
    if (s === "disabled") {
      const wasAvailable = !isAvatarUnavailable(agentId);
      voiceNativeEnabled = false;
      markAvatarUnavailable(agentId);
      if (wasAvailable) {
        toastStore.error("Avatar is unavailable on this server.");
      }
    }
  }

  // Split-layout: when either avatar mode is active (and a session exists), the
  // thread area splits into two panels — conversation on the left, avatar docked
  // on the right (stacked below on narrow screens) instead of a small floating card.
  let avatarPanelActive = $derived(
    !!currentSessionId && (avatarEnabled || voiceNativeEnabled),
  );

  /**
   * Append a structured output (Phase C) to the chat thread, reusing the normal
   * assistant-message render + persistence path.
   */
  async function handleVoiceNativeStructured(message: AgentMessage) {
    messages = [...messages, message];
    try {
      await ChatService.saveMessage(message);
    } catch {
      // non-fatal: in-memory render still works
    }
    scrollToBottom();
  }

  // Initialize streaming toggle from localStorage (runs on mount and on agentId change)
  $effect(() => {
    if (browser) {
      const key = `stream_enabled_${agentId}`;
      streamEnabled = localStorage.getItem(key) === "true";
    }
  });

  // Cleanup: abort any active stream when component is destroyed
  $effect(() => {
    return () => {
      if (activeStreamController) {
        activeStreamController.abort();
      }
    };
  });

  function handleToggleStream() {
    streamEnabled = !streamEnabled;
    if (browser) {
      localStorage.setItem(`stream_enabled_${agentId}`, String(streamEnabled));
    }
  }

  function handleStopStream() {
    if (activeStreamController) {
      activeStreamController.abort();
      activeStreamController = null;
    }
    isStreaming = false;
    streamingMessageId = null;
  }

  function jsonToMarkdownTable(data: any[]): string {
    if (!data || data.length === 0) return "";

    // Get headers from first object
    const headers = Object.keys(data[0]);

    // Create header row
    let markdown = `| ${headers.join(" | ")} |\n`;

    // Create separator row
    markdown += `| ${headers.map(() => "---").join(" | ")} |\n`;

    // Create data rows
    data.forEach((row) => {
      const values = headers.map((header) => {
        const val = row[header];
        return val === null || val === undefined ? "" : String(val);
      });
      markdown += `| ${values.join(" | ")} |\n`;
    });

    return markdown;
  }

  // Explanation state (no longer used for inline display — results go to canvas)

  // Layout store derived values
  let historyOpen = $derived(chatLayout.getHistoryOpen());
  let canvasOpen = $derived(chatLayout.getCanvasOpen());
  let canvasExpanded = $derived(chatLayout.getCanvasExpanded());

  // Canvas resize state
  let canvasWidth = $state(480);
  let isResizing = $state(false);

  function startCanvasResize(e: PointerEvent) {
    e.preventDefault();
    isResizing = true;
    const startX = e.clientX;
    const startWidth = canvasWidth;

    function onMove(ev: PointerEvent) {
      const delta = startX - ev.clientX;
      canvasWidth = Math.max(
        280,
        Math.min(startWidth + delta, window.innerWidth * 0.7),
      );
    }

    function onUp() {
      isResizing = false;
      window.removeEventListener("pointermove", onMove);
      window.removeEventListener("pointerup", onUp);
    }

    window.addEventListener("pointermove", onMove);
    window.addEventListener("pointerup", onUp);
  }

  // Auto-close history when user starts typing
  $effect(() => {
    if (inputText.length > 0) {
      chatLayout.closeHistory();
    }
  });

  // Derived: are there any pending questions?
  let hasPendingQuestions = $derived(pendingQuestions.size > 0);

  // Derived: recent user questions for quick repeat
  let recentQuestions = $derived(
    messages
      .filter((m) => m.role === "user")
      .slice(-10)
      .reverse()
      .map((m) => m.content),
  );

  // Derived: ID of the last assistant message with content (for regeneration constraint)
  let lastAssistantMsgId = $derived(
    [...messages].reverse().find((m) => m.role === "assistant" && m.content)
      ?.id ?? null,
  );

  // Prompt Library: get prompts reactively
  function getAgentPrompts(): Prompt[] {
    return promptStore.getPrompts();
  }

  // Welcome-screen starter bubbles: first 5 system (public) prompts. The
  // rule now lives in the prompt store (promptStore.getStarterPrompts) so the
  // text chat and voice chat stay consistent — see the store for details.

  // Handle prompt pill selection - copy to input (don't send)
  function handlePromptSelect(resolvedQuery: string, _prompt: Prompt) {
    inputText = resolvedQuery;
    // Focus will happen via tick when the input updates
    tick().then(() => {
      // ChatInput should auto-focus or we can trigger focus
      const textarea = document.querySelector<HTMLTextAreaElement>(
        'textarea[placeholder*="question"]',
      );
      if (textarea) {
        textarea.focus();
        // Move cursor to end of text
        textarea.selectionStart = textarea.value.length;
        textarea.selectionEnd = textarea.value.length;
      }
    });
  }

  // Load messages when session changes + persist the active session id so
  // a refresh lands the user back on the same conversation.
  // (The `lastSessionStorageKey` is declared at the top of the script next
  // to the synchronous hydration block — see the comment there for why.)
  $effect(() => {
    if (currentSessionId) {
      // No recargar si estamos en medio de crear una conversación nueva (lazy creation)
      if (!isCreatingNewConversation) {
        // Read `messageLimit` with untrack: this effect must react only to a
        // session change. `loadMoreMessages` already handles limit increments
        // and preserves scroll position. If messageLimit were a dependency here,
        // "Load earlier messages" would re-trigger loadMessages() → scrollToBottom()
        // and jump to the bottom instead of revealing the older messages.
        untrack(() => loadMessages(currentSessionId!, messageLimit));
      }
      // Subscribe to WebSocket channel for this session
      wsService.subscribe(currentSessionId);
    } else if (suppressSessionClearOnce) {
      suppressSessionClearOnce = false;
    } else {
      messages = [];
    }

    try {
      if (typeof localStorage !== "undefined") {
        if (currentSessionId) {
          localStorage.setItem(lastSessionStorageKey, currentSessionId);
        } else {
          localStorage.removeItem(lastSessionStorageKey);
        }
      }
    } catch {
      /* quota / serialize errors — non-fatal */
    }
  });

  let wsUnsubscribe: (() => void) | null = null;

  onMount(async () => {
    // Validate the synchronously-hydrated session id (from localStorage)
    // still maps to a real conversation in IndexedDB. If it doesn't (cache
    // cleared, dev DB wiped, …), clear it so the UI shows the empty state
    // instead of a broken "selected" but empty chat. The persistence
    // effect picks up the change and cleans the storage key.
    if (currentSessionId) {
      try {
        const convs = await ChatService.getConversations(agentId);
        const conv = convs.find((c) => c.id === currentSessionId);
        if (conv) {
          currentConversationTitle = conv.title ?? "";
        } else {
          currentSessionId = null;
        }
      } catch {
        /* best-effort */
      }
    }

    // Auto-collapse global navigation to maximize workspace — skip in
    // "compact" variant (embedded widget; must not touch the host page's
    // global nav/canvas layout state, per spec §3 Module 4).
    if (!isCompact) {
      chatLayout.collapseGlobalNav();
    }

    // Connect to WebSocket (use custom API URL if provided)
    await wsService.connect(apiUrl);

    // Load prompt library for this agent (pass chatbotId UUID for API prompts if available)
    promptStore.loadPrompts(agentId, chatbotId);

    // Feature-detect the voice endpoint (only when opted in). Hides the mic
    // proactively when the server lacks the voice stack (404 on /voice/...).
    if (features.voice && enableVoiceNotes) {
      checkVoiceSupport(agentId, scopedClient)
        .then((ok) => (voiceAvailable = ok))
        .catch(() => (voiceAvailable = false));
    }

    // Initialize empty canvas (no persistence — FEAT-042)
    canvasTabManager.resetCanvas();
    canvasTabManager.initCanvas();

    // Listen for answer ready notifications
    wsUnsubscribe = wsService.onMessage("answer_ready", (msg) => {
      // Verify it matches current session
      if (msg.session_id === currentSessionId && currentSessionId) {
        toastStore.info("Your answer is ready!");
        // We could trigger a reload here if needed, or just let user know
        // For now, re-fetching the last message might happen automatically via some store or manual reload
        // Only reload if we are NOT waiting for a response in this session to avoid race condition
        // If pendingQuestions is not empty, handleSend will update UI and DB when ready.
        if (pendingQuestions.size === 0) {
          loadMessages(currentSessionId, messageLimit);
        }
      }
    });
  });

  onDestroy(() => {
    // Abort all pending requests
    for (const { controller } of pendingQuestions.values()) {
      controller.abort();
    }

    // Restore global navigation on leave (mirrors the compact-mode skip above)
    if (!isCompact) {
      chatLayout.restoreGlobalNav();
    }

    if (currentSessionId) {
      wsService.unsubscribe(currentSessionId);
    }
    wsUnsubscribe?.();
    // Don't disconnect global service, just unsubscribe
  });

  async function loadMessages(sessionId: string, limit: number = PAGE_SIZE) {
    const fetched = await ChatService.getMessages(sessionId, agentId, limit);
    // If we got exactly `limit` messages, there are likely more available
    hasMoreMessages = fetched.length >= limit;
    messages = fetched;
    await tick();
    scrollToBottom();
  }

  // Re-pin the chat to a reference element so prepending older messages never
  // moves the viewport. We anchor on the first currently-rendered message and
  // keep its offset from the top of the container constant. The correction is
  // applied instantly (bypassing the container's `scroll-smooth`), so the user
  // sees no scroll animation — only the scrollbar thumb shifts.
  function pinToAnchor(
    anchorId: string | undefined,
    targetOffset: number | null,
  ) {
    if (!chatContainer || !anchorId || targetOffset === null) return;
    const el = chatContainer.querySelector<HTMLElement>(
      `[data-msg-id="${CSS.escape(anchorId)}"]`,
    );
    if (!el) return;
    const currentOffset =
      el.getBoundingClientRect().top -
      chatContainer.getBoundingClientRect().top;
    const delta = currentOffset - targetOffset;
    if (delta === 0) return;
    const prevBehavior = chatContainer.style.scrollBehavior;
    chatContainer.style.scrollBehavior = "auto";
    chatContainer.scrollTop += delta;
    chatContainer.style.scrollBehavior = prevBehavior;
  }

  async function loadMoreMessages() {
    if (!currentSessionId || loadingMore) return;
    loadingMore = true;
    // Capture the anchor (first visible message) and its current offset so we
    // can restore it exactly after older messages are prepended above it.
    const anchorId = messages[0]?.id;
    const anchorEl = anchorId
      ? chatContainer?.querySelector<HTMLElement>(
          `[data-msg-id="${CSS.escape(anchorId)}"]`,
        )
      : null;
    const targetOffset =
      anchorEl && chatContainer
        ? anchorEl.getBoundingClientRect().top -
          chatContainer.getBoundingClientRect().top
        : null;
    try {
      const newLimit = messageLimit + PAGE_SIZE;
      const fetched = await ChatService.getMessages(
        currentSessionId,
        agentId,
        newLimit,
      );
      hasMoreMessages = fetched.length >= newLimit;
      messageLimit = newLimit;
      messages = fetched;
      await tick();
      // Pin immediately for the synchronous layout.
      pinToAnchor(anchorId, targetOffset);
      // Keep re-pinning briefly: prepended messages may contain charts, tables
      // or images that finish rendering after `tick()`, changing the height
      // above the anchor. A ResizeObserver re-applies the correction on each
      // such change until the layout settles (or the 1s window closes).
      if (messagesContent && targetOffset !== null) {
        const ro = new ResizeObserver(() =>
          pinToAnchor(anchorId, targetOffset),
        );
        ro.observe(messagesContent);
        setTimeout(() => ro.disconnect(), 1000);
      }
    } finally {
      loadingMore = false;
    }
  }

  function unescapeHtml(html: string): string {
    if (!html) return html;
    // If the HTML looks like it has JSON-style escapes for quotes/newlines, clean them.
    // NOTE: Standard JSON parsing handles this, but user feedback indicates explicit cleanup might be needed
    // for some backend responses.
    return html
      .replace(/\\n/g, "\n")
      .replace(/\\"/g, '"')
      .replace(/\\t/g, "\t");
  }

  function scrollToBottom() {
    // Auto scroll logic (existing)
    if (chatContainer) {
      chatContainer.scrollTop = chatContainer.scrollHeight;
    }
  }

  async function handleNewConversation() {
    // Reset UI state only — do NOT create a conversation yet.
    // The actual conversation is created lazily on first message send (handleSend).
    currentSessionId = null;
    currentConversationTitle = "";
    messages = [];
    drawerOpen = false;
  }

  async function handleSelectConversation(id: string) {
    messageLimit = PAGE_SIZE;
    currentSessionId = id;
    drawerOpen = false;
    // Fetch title from IndexedDB
    const convs = await ChatService.getConversations(agentId);
    const conv = convs.find((c) => c.id === id);
    currentConversationTitle = conv?.title ?? "";

    // Reset canvas for new conversation (no persistence — FEAT-042)
    canvasTabManager.resetCanvas();
    canvasTabManager.initCanvas();
  }

  async function handleSend(
    query: string,
    methodName?: string,
    outputMode?: string,
    llm?: string,
    kwargs?: Record<string, string>,
    existingUserMsgId?: string,
  ) {
    let sessionId = currentSessionId;
    let isNewConversation = false;

    // Si no hay sesión activa, crear una nueva conversación ahora (lazy creation)
    if (!sessionId) {
      isNewConversation = true;
      sessionId = uuidv4();
      isCreatingNewConversation = true; // Evitar reload de mensajes por el $effect
      await ChatService.createConversation(agentId, sessionId);
      currentSessionId = sessionId;
    }

    // Create a placeholder for the pending response
    const pendingResponseId = uuidv4();
    const pendingMsg: AgentMessage = {
      id: pendingResponseId,
      role: "assistant",
      content: "",
      timestamp: new Date(),
      metadata: {
        session_id: sessionId,
        model: "loading",
        provider: "",
        turn_id: "",
        response_time: 0,
      },
    };

    const abortController = new AbortController();

    // Generate a stable user message ID upfront so it can be sent to the
    // backend as message_id, keeping both sides in sync and avoiding
    // duplicate bubbles when syncMessagesFromBackend runs later.
    const userMsgId = existingUserMsgId || uuidv4();

    if (existingUserMsgId) {
      // Optmistic Update for pending placeholder only
      messages = [...messages, pendingMsg];
      pendingQuestions = new Map([
        ...pendingQuestions,
        [pendingResponseId, { query, controller: abortController }],
      ]);
    } else {
      // 1. Create User Message
      const userMsg: AgentMessage = {
        id: userMsgId,
        role: "user",
        content: query,
        timestamp: new Date(),
        metadata: {
          session_id: sessionId,
          model: "",
          provider: "",
          turn_id: "",
          response_time: 0,
        },
      };

      // Optimistic Update with both user message and pending placeholder
      messages = [...messages, userMsg, pendingMsg];
      pendingQuestions = new Map([
        ...pendingQuestions,
        [pendingResponseId, { query, controller: abortController }],
      ]);

      await ChatService.saveMessage(userMsg);
    }

    await tick();
    scrollToBottom();

    try {
      let assistantMsg: AgentMessage;

      // ── Streaming branch ──
      if (streamEnabled) {
        isStreaming = true;
        streamingMessageId = pendingResponseId;
        const streamController = new AbortController();
        activeStreamController = streamController;
        const accumulator = new ChunkAccumulator();

        let streamFailed = false;
        let streamError: unknown = null;
        let finalMessage: AgentMessage | null = null;

        try {
          // Build the appropriate payload with stream: true
          let generator: AsyncGenerator<import("$lib/api/stream").StreamChunk>;

          if (botMode) {
            const botPayload: BotChatRequest & { stream: true } = {
              query,
              session_id: sessionId!,
              message_id: userMsgId,
              ...(followupTurnId && { turn_id: followupTurnId }),
              stream: true,
            };
            clearFollowup();
            generator = streamChatWithBot(
              agentId,
              botPayload,
              streamController.signal,
              apiUrl,
            );
          } else {
            const internalFormatKwargs =
              outputMode &&
              outputMode !== "default" &&
              outputMode !== "interactive"
                ? {
                    output_format: "html",
                    html_mode: "complete",
                    table_mode: "grid",
                  }
                : undefined;
            const mergedFormatKwargs =
              internalFormatKwargs || formatKwargs
                ? { ...(internalFormatKwargs ?? {}), ...(formatKwargs ?? {}) }
                : undefined;

            let finalQuery = query;
            if (followupTurnId) {
              const refMsg =
                messages.find((m) => m.metadata?.turn_id === followupTurnId) ||
                [...messages].reverse().find((m) => m.role === "assistant");
              if (refMsg) {
                const content = refMsg.content || "";
                const firstPara =
                  content.split(/\n\n/)[0].substring(0, 300) +
                  (content.length > 300 ? "..." : "");
                let ctx = `> You said: "${firstPara}"\n`;
                if (
                  followupData &&
                  Array.isArray(followupData) &&
                  followupData.length > 0 &&
                  followupData.length <= 10
                ) {
                  const cols = Object.keys(followupData[0]);
                  if (cols.length <= 10) {
                    const table = jsonToMarkdownTable(followupData);
                    ctx += `\n\n> Data Context:\n${table
                      .split("\n")
                      .map((l: string) => `> ${l}`)
                      .join("\n")}\n`;
                  }
                }
                finalQuery = `${ctx}\n${query}`;
              }
            }

            const payload: AgentChatRequest & { stream: true } = {
              query: finalQuery,
              session_id: sessionId,
              message_id: userMsgId,
              ...(followupTurnId && { turn_id: followupTurnId }),
              ...(followupData && { data: followupData }),
              ...(outputMode &&
                outputMode !== "default" && { output_mode: outputMode }),
              ...(mergedFormatKwargs && { format_kwargs: mergedFormatKwargs }),
              ...(context && { context }),
              ...(llm && { llm }),
              ...(kwargs && kwargs),
              ws_channel_id: sessionId,
              stream: true,
            };
            clearFollowup();
            generator = streamChatWithAgent(
              agentId,
              payload,
              streamController.signal,
              apiUrl,
            );
          }

          for await (const event of generator) {
            if (event.type === "chunk") {
              accumulator.append(event.text);
              // Update the pending message with renderable + pending text
              messages = messages.map((m) =>
                m.id === pendingResponseId
                  ? {
                      ...m,
                      content:
                        accumulator.getRenderable() + accumulator.getPending(),
                    }
                  : m,
              );
              await tick();
            } else if (event.type === "done") {
              // Final JSON chunk received — build the full assistant message
              const result = event.message;
              if (botMode) {
                // BotChatResponse shape
                const botResult =
                  result as import("$lib/types/bot-chat").BotChatResponse;
                const cleanAnswer = stripSourcesFromResponse(
                  botResult.response || botResult.output || "",
                );
                const resolvedSources = resolveDocumentSources(
                  botResult.documents,
                );
                finalMessage = {
                  id: botResult.turn_id || pendingResponseId,
                  role: "assistant",
                  content: cleanAnswer,
                  timestamp: new Date(),
                  metadata: {
                    model: botResult.model || "",
                    provider: botResult.provider || "",
                    session_id: sessionId!,
                    turn_id: botResult.turn_id || "",
                    response_time: null,
                  },
                  sources: resolvedSources,
                  documents: botResult.documents || undefined,
                  output_mode: "default",
                };
              } else {
                // AgentChatResponse shape — streaming envelope omits `response`
                // and ships the text in `output`, so fall back to that (and to
                // the accumulated stream text as a last resort).
                const agentResult =
                  result as import("$lib/types/agent").AgentChatResponse;
                const outputAsText =
                  typeof agentResult.output === "string"
                    ? agentResult.output
                    : "";
                const responseText =
                  agentResult.response ||
                  outputAsText ||
                  accumulator.getFullText();
                const isHtml =
                  responseText.trim().startsWith("<!DOCTYPE html") ||
                  responseText.trim().startsWith("<html");
                const effectiveOutputMode =
                  agentResult.output_mode || (isHtml ? "html" : "default");
                // For infographic output the artifact opens in the canvas; the
                // bubble shows the agent's explanation (`response`, with
                // metadata.explanation as the explicit contract fallback) rather
                // than the HTML/URL carried in `output`.
                const isInfographic = effectiveOutputMode === "infographic";
                const isInteractive = effectiveOutputMode === "interactive";
                const bubbleText = isInfographic
                  ? agentResult.response ||
                    agentResult.metadata?.explanation ||
                    "Infographic generated — opening in canvas."
                  : isInteractive
                    ? agentResult.response ||
                      agentResult.metadata?.explanation ||
                      "Interactive artifact generated — opening in canvas."
                    : responseText;
                finalMessage = {
                  id: agentResult.metadata?.turn_id || pendingResponseId,
                  role: "assistant",
                  content: bubbleText,
                  timestamp: new Date(),
                  metadata: { ...agentResult.metadata, session_id: sessionId! },
                  data: agentResult.data,
                  code: agentResult.code,
                  output: agentResult.output,
                  tool_calls: agentResult.tool_calls,
                  output_mode: effectiveOutputMode,
                  htmlResponse:
                    isInfographic || isInteractive
                      ? null
                      : isHtml
                        ? responseText
                        : null,
                  sources: resolveAgentSources(agentResult.sources),
                };
              }
            }
          }
        } catch (err: unknown) {
          if (err instanceof Error && err.name === "AbortError") {
            // User aborted — keep partial text
            const partialText = accumulator.getFullText();
            if (partialText) {
              messages = messages.map((m) =>
                m.id === pendingResponseId ? { ...m, content: partialText } : m,
              );
            } else {
              messages = messages.filter((m) => m.id !== pendingResponseId);
            }
            // Clean up and return — skip the non-streaming path
            pendingQuestions.delete(pendingResponseId);
            pendingQuestions = new Map(pendingQuestions);
            isCreatingNewConversation = false;
            isStreaming = false;
            streamingMessageId = null;
            activeStreamController = null;
            await tick();
            scrollToBottom();
            return;
          }

          // Other error — fall back to non-streaming if no partial text
          streamFailed = true;
          streamError = err;
        } finally {
          isStreaming = false;
          streamingMessageId = null;
          activeStreamController = null;
        }

        if (finalMessage) {
          // Stream completed successfully with final message
          const pendingExists = messages.some(
            (m) => m.id === pendingResponseId,
          );
          if (pendingExists) {
            messages = messages.map((m) =>
              m.id === pendingResponseId ? finalMessage! : m,
            );
          } else {
            messages = [...messages, finalMessage];
          }
          await ChatService.saveMessage(finalMessage);
          maybeOpenInfographicCanvas(finalMessage);
          maybeOpenInteractiveArtifactCanvas(finalMessage);
          if (messages.filter((m) => m.role === "user").length <= 1) {
            const title = query.split(" ").slice(0, 4).join(" ");
            await ChatService.updateConversationTitle(
              sessionId!,
              title,
              agentId,
            );
            currentConversationTitle = title;
          }
          pendingQuestions.delete(pendingResponseId);
          pendingQuestions = new Map(pendingQuestions);
          isCreatingNewConversation = false;
          await tick();
          scrollToBottom();
          return;
        }

        if (streamFailed) {
          const partialText = accumulator.getFullText();
          if (partialText) {
            // Keep partial text with error indicator
            const partialMsg: AgentMessage = {
              id: pendingResponseId,
              role: "assistant",
              content: partialText + "\n\n*[Stream interrupted]*",
              timestamp: new Date(),
              metadata: {
                session_id: sessionId!,
                model: "system",
                provider: "",
                turn_id: "",
                response_time: 0,
                is_error: true,
              },
            };
            messages = messages.map((m) =>
              m.id === pendingResponseId ? partialMsg : m,
            );
            await ChatService.saveMessage(partialMsg);
            pendingQuestions.delete(pendingResponseId);
            pendingQuestions = new Map(pendingQuestions);
            isCreatingNewConversation = false;
            await tick();
            scrollToBottom();
            return;
          }
          // No partial text — fall through to non-streaming retry
          toastStore.info("Streaming unavailable, loading full response…");
          messages = messages.map((m) =>
            m.id === pendingResponseId ? { ...m, content: "" } : m,
          );
          activeStreamController = abortController; // allow stop button to cancel fallback
          isStreaming = true; // keep stop button visible
          // Fall through to the non-streaming path below
        } else {
          // Generator ended without 'done' event and no error — treat as empty
          pendingQuestions.delete(pendingResponseId);
          pendingQuestions = new Map(pendingQuestions);
          isCreatingNewConversation = false;
          await tick();
          scrollToBottom();
          return;
        }
      }

      if (botMode) {
        // ── Bot mode: call /api/v1/chat/{chatbot_id} ──
        const botPayload: BotChatRequest = {
          query,
          session_id: sessionId,
          message_id: userMsgId,
          ...(followupTurnId && { turn_id: followupTurnId }),
        };

        // Clear follow-up state after building payload
        clearFollowup();

        const botResult = await chatWithBot(
          agentId,
          botPayload,
          scopedClient,
          abortController.signal,
        );

        // Strip ## **Sources:** section from the response markdown
        const cleanAnswer = stripSourcesFromResponse(
          botResult.response || botResult.output || "",
        );

        // Resolve documents dict into SourceLink[]
        const resolvedSources = resolveDocumentSources(botResult.documents);

        assistantMsg = {
          id: botResult.turn_id || pendingResponseId,
          role: "assistant",
          content: cleanAnswer,
          timestamp: new Date(),
          metadata: {
            model: botResult.model || "",
            provider: botResult.provider || "",
            session_id: sessionId,
            turn_id: botResult.turn_id || "",
            response_time: null,
          },
          sources: resolvedSources,
          documents: botResult.documents || undefined,
          output_mode: "default",
        };
      } else {
        // ── Agent mode: existing logic ──
        // Build format_kwargs for output_mode, then merge any caller-supplied
        // formatKwargs prop on top (caller wins on key collisions).
        const internalFormatKwargs =
          outputMode && outputMode !== "default" && outputMode !== "interactive"
            ? {
                output_format: "html",
                html_mode: "complete",
                table_mode: "grid",
              }
            : undefined;
        const mergedFormatKwargs =
          internalFormatKwargs || formatKwargs
            ? { ...(internalFormatKwargs ?? {}), ...(formatKwargs ?? {}) }
            : undefined;

        let finalQuery = query;

        // Handle Follow-up Context
        if (followupTurnId) {
          const refMsg =
            messages.find((m) => m.metadata?.turn_id === followupTurnId) ||
            [...messages].reverse().find((m) => m.role === "assistant");

          if (refMsg) {
            const content = refMsg.content || "";
            const firstPara =
              content.split(/\n\n/)[0].substring(0, 300) +
              (content.length > 300 ? "..." : "");

            let context = `> You said: "${firstPara}"\n`;

            if (
              followupData &&
              Array.isArray(followupData) &&
              followupData.length > 0 &&
              followupData.length <= 10
            ) {
              const cols = Object.keys(followupData[0]);
              if (cols.length <= 10) {
                const table = jsonToMarkdownTable(followupData);
                context += `\n\n> Data Context:\n${table
                  .split("\n")
                  .map((l) => `> ${l}`)
                  .join("\n")}\n`;
              }
            }

            finalQuery = `${context}\n${query}`;
          }
        }

        const payload: AgentChatRequest = {
          query: finalQuery,
          session_id: sessionId,
          message_id: userMsgId,
          ...(followupTurnId && { turn_id: followupTurnId }),
          ...(followupData && { data: followupData }),
          ...(outputMode &&
            outputMode !== "default" && { output_mode: outputMode }),
          ...(mergedFormatKwargs && { format_kwargs: mergedFormatKwargs }),
          ...(context && { context }),
          ...(llm && { llm }),
          ...(kwargs && kwargs),
          ws_channel_id: sessionId,
        };

        // Clear follow-up state after using it for payload
        clearFollowup();

        // 2. Call API (non-blocking - allows more questions)
        // FEAT-169: when the avatar is live, route text turns through the avatar voice endpoint
        const result =
          avatarLive && !methodName && !botMode
            ? await sendAvatarTextTurn(
                agentId,
                sessionId,
                finalQuery,
                tenantId,
                scopedClient,
                abortController.signal,
              )
            : methodName
              ? await callAgentMethod(
                  agentId,
                  methodName,
                  payload,
                  scopedClient,
                  abortController.signal,
                )
              : await chatWithAgent(
                  agentId,
                  payload,
                  scopedClient,
                  abortController.signal,
                );

        // 3. Build assistant message
        // Check for auth_required envelope (OAuth2 authorization prompt)
        const rawResult = result as any;
        if (rawResult.type === "auth_required") {
          assistantMsg = {
            id: pendingResponseId,
            role: "assistant",
            content:
              rawResult.message ||
              "Authorization required to use this feature.",
            type: "auth_required",
            provider: rawResult.provider,
            auth_url: rawResult.auth_url,
            scopes: rawResult.scopes,
            timestamp: new Date(),
            metadata: {
              session_id: sessionId,
              model: "system",
              provider: rawResult.provider ?? "",
              turn_id: "",
              response_time: 0,
            },
          };
        } else {
          const responseText = result.response || "";
          const isHtml =
            responseText.trim().startsWith("<!DOCTYPE html") ||
            responseText.trim().startsWith("<html");
          const effectiveOutputMode =
            result.output_mode || (isHtml ? "html" : "default");
          // For infographic output the artifact opens in the canvas; the bubble
          // shows the agent's explanation (`response`, with metadata.explanation
          // as the explicit contract fallback) rather than the HTML/URL in `output`.
          const isInfographic = effectiveOutputMode === "infographic";
          const isInteractive = effectiveOutputMode === "interactive";
          const bubbleText = isInfographic
            ? responseText ||
              result.metadata?.explanation ||
              "Infographic generated — opening in canvas."
            : isInteractive
              ? responseText ||
                result.metadata?.explanation ||
                "Interactive artifact generated — opening in canvas."
              : responseText;

          assistantMsg = {
            id: result.metadata?.turn_id || pendingResponseId,
            role: "assistant",
            content: bubbleText,
            timestamp: new Date(),
            metadata: {
              ...result.metadata,
              session_id: sessionId,
            },
            data: result.data,
            code: result.code,
            output: result.output,
            tool_calls: result.tool_calls,
            output_mode: effectiveOutputMode,
            htmlResponse:
              isInfographic || isInteractive
                ? null
                : isHtml
                  ? responseText
                  : null,
            sources: resolveAgentSources(result.sources),
          };
        }
      }

      // Check if pending message still exists (it might have been wiped by a loadMessages race)
      const pendingExists = messages.some((m) => m.id === pendingResponseId);

      if (pendingExists) {
        messages = messages.map((m) =>
          m.id === pendingResponseId ? assistantMsg : m,
        );
      } else {
        // If lost, append it (this fixes the "sometimes not rendered" issue)
        messages = [...messages, assistantMsg];
      }

      await ChatService.saveMessage(assistantMsg);
      maybeOpenInfographicCanvas(assistantMsg);
      maybeOpenInteractiveArtifactCanvas(assistantMsg);

      // Update title if it's the first message
      if (messages.filter((m) => m.role === "user").length <= 1) {
        const title = query.split(" ").slice(0, 4).join(" ");
        await ChatService.updateConversationTitle(sessionId, title, agentId);
        currentConversationTitle = title;
      }
    } catch (error: any) {
      // If the request was cancelled by the user, remove the placeholder silently
      if (abortController.signal.aborted) {
        messages = messages.filter((m) => m.id !== pendingResponseId);
        return;
      }
      console.error("Chat Error", error);
      const isPolicyDenial =
        error?.status === 401 && /policy/i.test(error?.message ?? "");
      const displayContent = isPolicyDenial
        ? `**Access denied.** Your access was denied based on enforced policy rules.`
        : `**Error:** Failed to get response from agent. \n\n\`${error.message}\``;
      const errorMsg: AgentMessage = {
        id: pendingResponseId,
        role: "assistant",
        content: displayContent,
        timestamp: new Date(),
        metadata: {
          session_id: sessionId,
          model: "system",
          provider: "",
          turn_id: "",
          response_time: 0,
          is_error: true, // Flag for retry logic
        },
      };
      messages = messages.map((m) =>
        m.id === pendingResponseId ? errorMsg : m,
      );
      if (isPolicyDenial) {
        // Don't persist denied conversations. If this was a fresh conversation,
        // drop the conversation + user message we optimistically saved before
        // the request failed, so it never shows up in Conversation History.
        if (isNewConversation) {
          await ChatService.deleteConversation(sessionId);
          suppressSessionClearOnce = true;
          currentSessionId = null;
        }
      } else {
        await ChatService.saveMessage(errorMsg);
      }
    } finally {
      pendingQuestions.delete(pendingResponseId);
      pendingQuestions = new Map(pendingQuestions);
      isCreatingNewConversation = false; // Reset flag para permitir reloads futuros
      // Reset fallback streaming state (no-op if already cleared by streaming path)
      activeStreamController = null;
      isStreaming = false;
      await tick();
      scrollToBottom();
    }
  }

  /**
   * Send a recorded voice note to the AgentTalk Voice endpoint and render the
   * answer (text + optional spoken audio). Mirrors `handleSend`'s optimistic
   * UI/persistence flow but is always non-streaming (voice is a single REST
   * round-trip). The user bubble starts as a placeholder and is replaced with
   * the server-side transcript (`envelope.input`) once it returns.
   */
  async function handleVoiceNote(note: RecordedVoiceNote) {
    let sessionId = currentSessionId;
    let isNewConversation = false;

    if (!sessionId) {
      isNewConversation = true;
      sessionId = uuidv4();
      isCreatingNewConversation = true;
      await ChatService.createConversation(agentId, sessionId);
      currentSessionId = sessionId;
    }

    const userMsgId = uuidv4();
    const pendingResponseId = uuidv4();
    const abortController = new AbortController();

    const userMsg: AgentMessage = {
      id: userMsgId,
      role: "user",
      content: "🎤 Voice note…",
      timestamp: new Date(),
      metadata: {
        session_id: sessionId,
        model: "",
        provider: "",
        turn_id: "",
        response_time: 0,
      },
    };
    const pendingMsg: AgentMessage = {
      id: pendingResponseId,
      role: "assistant",
      content: "",
      timestamp: new Date(),
      metadata: {
        session_id: sessionId,
        model: "loading",
        provider: "",
        turn_id: "",
        response_time: 0,
      },
    };

    messages = [...messages, userMsg, pendingMsg];
    pendingQuestions = new Map([
      ...pendingQuestions,
      [pendingResponseId, { query: "voice note", controller: abortController }],
    ]);
    await ChatService.saveMessage(userMsg);
    await tick();
    scrollToBottom();

    try {
      const result = await sendVoiceNote(
        agentId,
        note.blob,
        {
          filename: `voice-note.${note.extension}`,
          sessionId,
          messageId: userMsgId,
          // FEAT-169: when avatar is live, route voice note through avatar pipeline
          ...(avatarLive && { avatar: true, tenantId }),
        },
        scopedClient,
        abortController.signal,
      );

      // Replace the placeholder user bubble with the real transcript.
      const transcript = (result.input || "").trim();
      const updatedUserMsg: AgentMessage = {
        ...userMsg,
        content: transcript || "🎤 Voice note",
      };

      const responseText = result.response || "";
      const isHtml =
        responseText.trim().startsWith("<!DOCTYPE html") ||
        responseText.trim().startsWith("<html");
      const effectiveOutputMode =
        result.output_mode || (isHtml ? "html" : "default");
      const isInteractive = effectiveOutputMode === "interactive";

      const assistantMsg: AgentMessage = {
        id: result.metadata?.turn_id || pendingResponseId,
        role: "assistant",
        content: responseText,
        timestamp: new Date(),
        metadata: {
          ...result.metadata,
          session_id: sessionId,
        },
        data: result.data,
        code: result.code,
        output: result.output,
        tool_calls: result.tool_calls,
        output_mode: effectiveOutputMode,
        htmlResponse: isInteractive ? null : isHtml ? responseText : null,
        sources: resolveAgentSources(result.sources),
        // Spoken answer (present only when TTS succeeded) — kept in-memory only.
        // FEAT-169: in avatar mode, audio comes from the LiveKit room — do not play audio_base64
        audio_base64: avatarLive ? undefined : result.audio_base64,
        audio_format: avatarLive ? undefined : result.audio_format,
      };

      messages = messages.map((m) =>
        m.id === userMsgId
          ? updatedUserMsg
          : m.id === pendingResponseId
            ? assistantMsg
            : m,
      );

      await ChatService.saveMessage(updatedUserMsg);
      // Strip the (potentially large) base64 audio before persisting — the
      // player is a session-only enhancement; reloads degrade to text.
      const { audio_base64: _omit, ...persistableAssistant } = assistantMsg;
      await ChatService.saveMessage(persistableAssistant as AgentMessage);
      maybeOpenInfographicCanvas(assistantMsg);
      maybeOpenInteractiveArtifactCanvas(assistantMsg);

      if (messages.filter((m) => m.role === "user").length <= 1) {
        const title = transcript
          ? transcript.split(" ").slice(0, 4).join(" ")
          : "Voice note";
        await ChatService.updateConversationTitle(sessionId, title, agentId);
        currentConversationTitle = title;
      }
    } catch (error: any) {
      if (abortController.signal.aborted) {
        messages = messages.filter(
          (m) => m.id !== pendingResponseId && m.id !== userMsgId,
        );
        return;
      }
      console.error("Voice Note Error", error);
      const status = error?.status ?? error?.response?.status;
      const serverError = error?.response?.data?.error;
      let displayContent: string;
      if (status === 404) {
        displayContent =
          "**Voice unavailable.** This server does not have voice support enabled.";
        // ai-parrot (FEAT-476 TASK-2596): the mount-time checkVoiceSupport()
        // preflight (TASK-2594) is a HEAD request and can pass even when the
        // real POST route 404s — degrade for the rest of the session on the
        // first such failure and tell the user once, per spec §3 Module 6.
        if (voiceAvailable) {
          voiceAvailable = false;
          toastStore.error(
            "Voice notes are unavailable on this server — switched to text.",
          );
        }
      } else if (status === 503) {
        displayContent =
          "**Voice transcription unavailable.** Please try sending your question as text.";
      } else if (status === 400) {
        displayContent = `**Could not transcribe audio.** ${serverError ?? "Try recording again."}`;
      } else {
        displayContent = `**Error:** Failed to send voice note. \n\n\`${error.message}\``;
      }
      const errorMsg: AgentMessage = {
        id: pendingResponseId,
        role: "assistant",
        content: displayContent,
        timestamp: new Date(),
        metadata: {
          session_id: sessionId,
          model: "system",
          provider: "",
          turn_id: "",
          response_time: 0,
          is_error: true,
        },
      };
      messages = messages.map((m) =>
        m.id === pendingResponseId ? errorMsg : m,
      );
      if (isNewConversation && status === 404) {
        await ChatService.deleteConversation(sessionId);
        suppressSessionClearOnce = true;
        currentSessionId = null;
      } else {
        await ChatService.saveMessage(errorMsg);
      }
    } finally {
      pendingQuestions.delete(pendingResponseId);
      pendingQuestions = new Map(pendingQuestions);
      isCreatingNewConversation = false;
      await tick();
      scrollToBottom();
    }
  }

  function handleCancelQuestion(pendingId: string) {
    const entry = pendingQuestions.get(pendingId);
    if (entry) {
      entry.controller.abort();
      pendingQuestions.delete(pendingId);
      pendingQuestions = new Map(pendingQuestions);
      // Remove the pending placeholder message
      messages = messages.filter((m) => m.id !== pendingId);
    }
  }

  function handleCancelAll() {
    for (const [id, { controller }] of pendingQuestions) {
      controller.abort();
      messages = messages.filter((m) => m.id !== id);
    }
    pendingQuestions = new Map();
  }

  function handleRepeat(text: string) {
    inputText = text;
  }

  function handleFollowup(turnId: string, data: any) {
    followupTurnId = turnId;
    followupData = data;
    // Focus on input would be nice, but we'll just show the indicator
  }

  function clearFollowup() {
    followupTurnId = null;
    followupData = null;
  }

  async function handleExplain(turnId: string, data: any) {
    // Create a canvas tab immediately with loading state
    canvasTabManager.initCanvas();
    const tabId = canvasTabManager.addTab(
      "markdown",
      "Explanation",
      "__loading__",
    );
    chatLayout.openCanvas();

    try {
      if (!currentSessionId) return;

      let finalQuery = explainPrompt;

      // Check if data is array and small enough (<= 10x10)
      if (Array.isArray(data) && data.length > 0 && data.length <= 10) {
        const cols = Object.keys(data[0]);
        if (cols.length <= 10) {
          const table = jsonToMarkdownTable(data);
          finalQuery += `\n\n<pre>\n${table}\n</pre>`;
        }
      }

      // Construct a specialized payload for explanation
      const payload: AgentChatRequest = {
        query: finalQuery,
        session_id: currentSessionId,
        turn_id: turnId,
        data: data, // Send the specific data to explain
        ...(formatKwargs && { format_kwargs: formatKwargs }),
        ...(context && { context }),
      };

      const result = await chatWithAgent(agentId, payload, scopedClient);
      canvasTabManager.updateTabData(
        tabId,
        result.response || "No explanation available.",
      );
    } catch (error: any) {
      console.error("Explanation Error", error);
      canvasTabManager.updateTabData(tabId, `**Error:** ${error.message}`);
    }
  }

  function handleOpenSpreadsheet(data: any) {
    canvasTabManager.initCanvas();
    const rows = Array.isArray(data) ? data : [];
    canvasTabManager.addTab("spreadsheet", `Sheet (${rows.length} rows)`, rows);
    chatLayout.openCanvas();
  }

  function handleMoveToCanvas(content: string) {
    canvasTabManager.initCanvas();
    const mainTab = canvasTabManager
      .getTabs()
      .find((t) => t.id === "main-canvas");
    if (mainTab) {
      const blocks = isCanvasBlockArray(mainTab.data)
        ? [...(mainTab.data as CanvasBlock[])]
        : [];
      blocks.push(createBlock("markdown", { content }));
      canvasTabManager.updateTabData(mainTab.id, blocks);
      canvasTabManager.setActiveTab(mainTab.id);
    }
    chatLayout.openCanvas();
    toastStore.success("Content added to canvas.");
  }

  function handleMoveTableDataToCanvas(
    rows: Record<string, unknown>[],
    columns: string[],
  ) {
    canvasTabManager.initCanvas();
    const mainTab = canvasTabManager
      .getTabs()
      .find((t) => t.id === "main-canvas");
    if (mainTab) {
      const blocks = isCanvasBlockArray(mainTab.data)
        ? [...(mainTab.data as CanvasBlock[])]
        : [];
      blocks.push(createBlock("table", { rows, columns }));
      canvasTabManager.updateTabData(mainTab.id, blocks);
      canvasTabManager.setActiveTab(mainTab.id);
    }
    chatLayout.openCanvas();
    toastStore.success("Table added to canvas.");
  }

  function handleCopyChartToCanvas(
    data: Record<string, any>[],
    config: any,
    imageDataUrl?: string,
  ) {
    // imageDataUrl kept in signature for backward compatibility but no longer used
    // Charts are now rendered as live interactive blocks
    canvasTabManager.initCanvas();
    const mainTab = canvasTabManager
      .getTabs()
      .find((t) => t.id === "main-canvas");
    if (mainTab) {
      const blocks = isCanvasBlockArray(mainTab.data)
        ? [...(mainTab.data as CanvasBlock[])]
        : [];
      blocks.push(createBlock("chart", { data, config }));
      canvasTabManager.updateTabData(mainTab.id, blocks);
      canvasTabManager.setActiveTab(mainTab.id);
    }
    chatLayout.openCanvas();
    toastStore.success("Chart added to canvas.");
  }

  function handleCopyChartToChartCanvas(
    data: Record<string, any>[],
    config: any,
  ) {
    canvasTabManager.initCanvas();
    // Find existing chart canvas tab or create one
    const existingTab = canvasTabManager
      .getTabs()
      .find((t) => t.type === "chart");
    if (existingTab) {
      const blocks = isCanvasBlockArray(existingTab.data)
        ? [...(existingTab.data as CanvasBlock[])]
        : [];
      blocks.push(createBlock("chart", { data, config }));
      canvasTabManager.updateTabData(existingTab.id, blocks);
      canvasTabManager.setActiveTab(existingTab.id);
    } else {
      const chartBlock = createBlock("chart", { data, config });
      canvasTabManager.addTab("chart", "Charts", [chartBlock]);
    }
    chatLayout.openCanvas();
    toastStore.success("Chart added to chart canvas.");
  }

  function handleCreateInfographic(
    response: string,
    data: Record<string, unknown>[],
  ) {
    // Build a pre-filled query from the chat message context
    const query = [
      response,
      data && data.length > 0
        ? `\n\nData:\n${JSON.stringify(data.slice(0, 20), null, 2)}`
        : "",
    ]
      .join("")
      .trim();

    canvasTabManager.initCanvas();
    canvasTabManager.addTab("infographic", "Infographic", {
      mode: "json",
      query,
    });
    chatLayout.openCanvas();
  }

  /**
   * When an assistant message arrives with output_mode "infographic", open the
   * artifact in a new canvas tab automatically.
   *
   * The backend ships the rendered HTML inline in `output`; when the document
   * is too large it omits the inline copy (metadata.html_inline_omitted) and
   * provides metadata.html_url instead. So we prefer inline HTML (srcdoc) and
   * fall back to the URL (iframe src).
   */
  function maybeOpenInfographicCanvas(message: AgentMessage) {
    if (message.output_mode !== "infographic") return;

    const meta = message.metadata;
    const inlineHtml =
      !meta?.html_inline_omitted && typeof message.output === "string"
        ? message.output
        : "";
    const url = meta?.html_url;

    const common = { template: meta?.template_name, theme: meta?.theme };
    let tabData: {
      mode: "html";
      html?: string;
      url?: string;
      template?: string;
      theme?: string;
    } | null = null;
    if (inlineHtml.includes("<html") || inlineHtml.includes("<!DOCTYPE")) {
      tabData = { mode: "html", html: inlineHtml, ...common };
    } else if (url) {
      tabData = { mode: "html", url, ...common };
    }
    if (!tabData) return;

    canvasTabManager.initCanvas();
    const title = meta?.template_name
      ? `Infographic (${meta.template_name})`
      : "Infographic";
    canvasTabManager.addTab("infographic", title, tabData);
    chatLayout.openCanvas();
  }

  function maybeOpenInteractiveArtifactCanvas(message: AgentMessage) {
    if (message.output_mode !== "interactive") return;

    const artifact = message.output as InteractiveArtifactResult;
    if (!artifact || artifact.type !== "interactive") return;

    const tabData: InteractiveArtifactTabData = {
      artifact_id: artifact.artifact_id,
      html_inline: artifact.html_inline,
      html_url: artifact.html_url,
      template_name: artifact.template_name,
      theme: artifact.theme,
      libraries_used: artifact.libraries_used,
      enhanced: artifact.enhanced,
      session_id: currentSessionId ?? undefined,
    };

    canvasTabManager.initCanvas();
    const title = artifact.template_name
      ? `Interactive (${artifact.template_name})`
      : "Interactive Artifact";
    canvasTabManager.addTab("interactive", title, tabData);
    chatLayout.openCanvas();
  }

  function isPending(msgId: string): boolean {
    return pendingQuestions.has(msgId);
  }

  async function handleRetry(msgId: string) {
    const msgIndex = messages.findIndex((m) => m.id === msgId);
    if (msgIndex === -1) return;

    // The user message should be immediately before the error message
    const userMsg = messages[msgIndex - 1];
    if (!userMsg || userMsg.role !== "user") {
      console.error(
        "Cannot retry: previous message not found or not from user",
      );
      return;
    }

    // Remove the error message from the UI
    messages = messages.filter((m) => m.id !== msgId);

    // Remove from DB if needed (optional based on persistence strategy, but good for cleanup)
    // await ChatService.deleteMessage(msgId);

    // Resend the user's query
    await handleSend(
      userMsg.content,
      undefined,
      undefined,
      undefined,
      undefined,
      userMsg.id,
    );
  }

  function handleDetailedFeedback(turnId: string) {
    detailedFeedbackTargetTurnId = turnId;
    detailedFeedbackTargetChatbotId = agentId;
    detailedFeedbackModalOpen = true;
  }

  async function handleRegenerate(
    option: "retry" | "details" | "model",
    payload?: string,
  ) {
    // Get the last user message context
    // We assume regeneration applies to the *last* exchange usually
    const lastUserMsg = [...messages].reverse().find((m) => m.role === "user");
    if (!lastUserMsg) return;

    // Preserve the output mode of the answer being regenerated (e.g.
    // "structured_chart"). Without this the retry falls back to "default" and
    // the agent returns prose/a table instead of the chart the user asked for.
    const lastAssistantMsg = [...messages]
      .reverse()
      .find((m) => m.role === "assistant" && m.output_mode);
    const outputMode = lastAssistantMsg?.output_mode;

    let query = lastUserMsg.content;
    let llm = undefined;

    if (option === "details" && payload) {
      query += `\n\n[Details]: ${payload}`;
    } else if (option === "model" && payload) {
      llm = payload;
    }

    // Trigger send
    if (option === "retry") {
      await handleSend(query, undefined, outputMode, llm, undefined, lastUserMsg.id);
    } else {
      await handleSend(query, undefined, outputMode, llm);
    }
  }

  async function handleDeleteMessage(messageId: string, turnId: string) {
    if (!currentSessionId) return;

    // Find the message being deleted and its paired question/answer
    const idx = messages.findIndex((m) => m.id === messageId);
    if (idx === -1) return;

    const target = messages[idx];
    const idsToRemove = new Set<string>([messageId]);

    if (target.role === "user") {
      // Deleting a user message — also remove the next assistant message (its answer)
      const next = messages[idx + 1];
      if (next && next.role === "assistant") {
        idsToRemove.add(next.id);
      }
    } else if (target.role === "assistant") {
      // Deleting an assistant message — also remove the preceding user message (its question)
      const prev = messages[idx - 1];
      if (prev && prev.role === "user") {
        idsToRemove.add(prev.id);
      }
    }

    // Remove the full turn from local array
    messages = messages.filter((m) => !idsToRemove.has(m.id));

    // Persist deletion for each message
    for (const id of idsToRemove) {
      await ChatService.deleteMessage(currentSessionId, turnId, id, agentId);
    }
  }
</script>

<!-- Detailed Feedback Modal -->
{#if detailedFeedbackModalOpen && currentSessionId}
  <FeedbackModal
    bind:open={detailedFeedbackModalOpen}
    chatbotId={detailedFeedbackTargetChatbotId}
    sessionId={currentSessionId}
    messageId={detailedFeedbackTargetTurnId}
  />
{/if}

<div class="flex h-full w-full bg-base-200">
  <!-- Left Pane: Conversation History (collapsible, default closed) -->
  <!-- Hidden entirely in compact variant — there's no room for a 288px aside. -->
  {#if !isCompact}
    <aside
      class={`hidden md:flex flex-col min-h-0 border-r bg-card border-border transition-all duration-300 overflow-hidden ${historyOpen ? "w-72" : "w-0"}`}
    >
      {#if historyOpen}
        <div class="flex-1 min-h-0 w-72">
          <ConversationList
            {agentId}
            {currentSessionId}
            onSelect={handleSelectConversation}
            onNew={handleNewConversation}
            onToggleSidebar={() => chatLayout.toggleHistory()}
          />
        </div>

        <div class="border-t border-border flex flex-col gap-1.5 p-3 w-72">
          <button
            class="new-chat-btn flex w-full items-center justify-center gap-2 rounded-lg px-3 py-2 text-xs font-medium transition-all duration-150"
            onclick={() => handleNewConversation()}
          >
            <Icon icon="mdi:plus" class="size-3.5" />
            New Chat
          </button>
          <button
            class="flex w-full items-center justify-center gap-2 rounded-lg border border-border/60 bg-foreground/[0.04] px-3 py-2 text-xs font-medium text-foreground/50 transition-all hover:bg-foreground/[0.07] hover:text-foreground/70"
            onclick={() => (configModalOpen = true)}
          >
            <Icon icon="mdi:cog" class="h-3.5 w-3.5" />
            Settings
          </button>
          <button
            class="flex w-full items-center justify-center gap-2 rounded-lg border border-border/60 bg-foreground/[0.04] px-3 py-2 text-xs font-medium text-foreground/50 transition-all hover:bg-foreground/[0.07] hover:text-foreground/70"
            onclick={() => (datasetModalOpen = true)}
          >
            <Icon icon="mdi:database-cog" class="h-3.5 w-3.5" />
            Dataset Config...
          </button>
        </div>
      {/if}
    </aside>
  {/if}

  <!-- Main Chat Area (hidden when canvas is expanded) -->
  <main
    class={`flex-1 flex flex-col h-full relative overflow-hidden${canvasExpanded ? " hidden" : ""}`}
  >
    <!-- Desktop Header — hidden in compact (caller is expected to provide its own
         section heading; the agentId + title are noise in a narrow side rail). -->
    {#if !isCompact}
      <div
        class="hidden md:flex items-center justify-between px-3 h-8 border-b border-border bg-card shrink-0 select-none"
      >
        <div class="flex items-center gap-1">
          <!-- Toggle History Pane — hidden in compact variant (no aside to toggle) -->
          {#if !isCompact}
            <button
              class="btn btn-ghost btn-xs btn-square text-muted-foreground hover:text-foreground"
              class:text-primary={historyOpen}
              onclick={() => chatLayout.toggleHistory()}
              title={historyOpen ? "Close history" : "Open history"}
            >
              <Icon icon="mdi:history" class="size-3.5" />
            </button>
          {/if}
          <span
            class="text-xs font-medium text-muted-foreground truncate"
          >
            {displayName}
          </span>
        </div>
        <div class="flex-1 text-center truncate px-4">
          <span
            class="text-[13px] font-semibold text-slate-800 dark:text-slate-200"
          >
            {currentConversationTitle || "New Chat"}
          </span>
        </div>
        <div class="flex items-center gap-1">
          <!-- Thread Refresh Button -->
          <button
            class="btn btn-ghost btn-xs btn-square text-muted-foreground hover:text-foreground"
            onclick={() => currentSessionId && loadMessages(currentSessionId)}
            title="Refresh Conversation"
            disabled={!currentSessionId}
          >
            <Icon icon="mdi:refresh" class="size-3.5" />
          </button>
          <!-- Integrations Menu -->
          <IntegrationsMenu {agentId} />
          <!-- FEAT-169: Avatar toggle button -->
          <button
            class="btn btn-ghost btn-xs btn-square text-muted-foreground hover:text-foreground"
            class:text-primary={avatarEnabled}
            onclick={handleAvatarToggle}
            title={avatarEnabled ? "Disable avatar" : "Talk with avatar"}
            aria-label={avatarEnabled ? "Disable avatar" : "Talk with avatar"}
            aria-pressed={avatarEnabled}
          >
            <Icon icon="mdi:account-voice" class="size-3.5" />
          </button>
          <!-- FEAT-243: Voice-native avatar toggle button -->
          <button
            class="btn btn-ghost btn-xs btn-square text-muted-foreground hover:text-foreground"
            class:text-primary={voiceNativeEnabled}
            onclick={handleVoiceNativeToggle}
            title={voiceNativeEnabled
              ? "Disable voice avatar"
              : "Voice conversation with avatar"}
            aria-label={voiceNativeEnabled
              ? "Disable voice avatar"
              : "Voice conversation with avatar"}
            aria-pressed={voiceNativeEnabled}
          >
            <Icon icon="mdi:microphone-message" class="size-3.5" />
          </button>
          <!-- Toggle Canvas Pane -->
          {#if effectiveEnableCanvas}
            <button
              class="btn btn-ghost btn-xs btn-square text-muted-foreground hover:text-foreground"
              class:text-primary={canvasOpen}
              onclick={() => chatLayout.toggleCanvas()}
              title={canvasOpen ? "Close canvas" : "Open canvas"}
            >
              <Icon icon="mdi:dock-right" class="size-3.5" />
            </button>
          {/if}
        </div>
      </div>
    {/if}

    <!-- Desktop Prompt Pills (hidden in compact variant — saves vertical space) -->
    {#if !isCompact}
      <div
        class="hidden md:flex items-center px-3 py-1.5 border-b border-border bg-muted/30 overflow-x-auto gap-1"
      >
        <PromptPills
          prompts={getAgentPrompts()}
          onSelect={handlePromptSelect}
          onConfigure={() => (promptModalOpen = true)}
          compact
          scrollable
        />
      </div>
    {/if}

    <!-- Compact variant toolbar — conversation title + history dropdown + new chat -->
    {#if isCompact}
      <div
        class="hidden md:flex h-8 shrink-0 items-center gap-1 border-b border-border bg-card px-2"
      >
        <span class="min-w-0 flex-1 truncate text-[11px] text-muted-foreground">
          {currentConversationTitle || "New Chat"}
        </span>

        <!-- History dropdown -->
        <div class="relative">
          <button
            class="flex h-6 w-6 items-center justify-center rounded text-muted-foreground transition-colors hover:bg-muted hover:text-foreground"
            class:text-primary={compactHistoryOpen}
            onclick={() => (compactHistoryOpen = !compactHistoryOpen)}
            title="Conversation history"
          >
            <Icon icon="ph:clock-counter-clockwise" class="size-3.5" />
          </button>
          {#if compactHistoryOpen}
            <!-- Click-away backdrop -->
            <div
              class="fixed inset-0 z-40"
              role="presentation"
              onclick={() => (compactHistoryOpen = false)}
            ></div>
            <!-- Dropdown panel -->
            <div
              class="absolute right-0 top-full z-50 mt-1 w-64 overflow-hidden rounded-md border border-border bg-card shadow-lg"
            >
              <div class="max-h-72 overflow-y-auto">
                <ConversationList
                  {agentId}
                  {currentSessionId}
                  onSelect={(id) => {
                    handleSelectConversation(id);
                    compactHistoryOpen = false;
                  }}
                  onNew={() => {
                    handleNewConversation();
                    compactHistoryOpen = false;
                  }}
                />
              </div>
              <div class="border-t border-border p-2">
                <button
                  class="flex w-full items-center justify-center gap-1.5 rounded px-2 py-1.5 text-[11px] font-medium text-muted-foreground transition-colors hover:bg-muted hover:text-foreground"
                  onclick={() => {
                    handleNewConversation();
                    compactHistoryOpen = false;
                  }}
                >
                  <Icon icon="ph:plus" class="size-3" />
                  New conversation
                </button>
              </div>
            </div>
          {/if}
        </div>

        <!-- New Chat shortcut button -->
        <button
          class="flex h-6 w-6 items-center justify-center rounded text-muted-foreground transition-colors hover:bg-muted hover:text-foreground"
          onclick={handleNewConversation}
          title="New conversation"
        >
          <Icon icon="ph:plus" class="size-3.5" />
        </button>
      </div>
    {/if}

    <!-- Header (Mobile Only) -->
    <div
      class="md:hidden flex items-center justify-between p-4 bg-card border-b border-border shadow-sm z-10"
    >
      <button
        class="btn btn-ghost btn-circle"
        onclick={() => (drawerOpen = true)}
        aria-label="Open sidebar"
      >
        <svg
          xmlns="http://www.w3.org/2000/svg"
          fill="none"
          viewBox="0 0 24 24"
          stroke-width="1.5"
          stroke="currentColor"
          class="size-6"
        >
          <path
            stroke-linecap="round"
            stroke-linejoin="round"
            d="M3.75 6.75h16.5M3.75 12h16.5m-16.5 5.25h16.5"
          />
        </svg>
      </button>
      <div class="flex flex-col items-center">
        <div class="font-semibold text-sm">{agentId}</div>
        <span class="text-[10px] text-slate-400 truncate max-w-[200px]">
          {currentConversationTitle || "New Chat"}
        </span>
      </div>
      <button
        class="btn btn-ghost btn-circle"
        onclick={() => handleNewConversation()}
        aria-label="New chat"
      >
        <svg
          xmlns="http://www.w3.org/2000/svg"
          fill="none"
          viewBox="0 0 24 24"
          stroke-width="1.5"
          stroke="currentColor"
          class="size-6"
        >
          <path
            stroke-linecap="round"
            stroke-linejoin="round"
            d="M12 4.5v15m7.5-7.5h-15"
          />
        </svg>
      </button>
    </div>

    <!-- Prompt Library Pills (Mobile) -->
    <div
      class="md:hidden px-3 py-2 border-b border-border bg-muted/50 overflow-x-auto"
    >
      <PromptPills
        prompts={getAgentPrompts()}
        onSelect={handlePromptSelect}
        onConfigure={() => (promptModalOpen = true)}
        compact
        scrollable
      />
    </div>

    <!-- Thread + Avatar split: row on desktop (thread left, avatar right),
         column on narrow screens (avatar stacked below). When no avatar mode
         is active the wrapper just holds the thread full-width. -->
    <div class="flex-1 min-h-0 flex flex-col md:flex-row">
      <!-- Left column: the chat (scrolling message thread + input). min-w-0
           lets it shrink so wide bubble content (tables, code, charts) never
           pushes the avatar panel off-screen — the flexbox min-width:auto
           gotcha that was clipping the avatar video on the right edge. -->
      <div class="flex flex-1 min-w-0 flex-col">
        <!-- Chat Messages — the conversation stream. -->
        <div
          class={isCompact
            ? "flex-1 min-h-0 overflow-y-auto scroll-smooth pt-2 bg-background"
            : "flex-1 min-h-0 overflow-y-auto scroll-smooth pt-4 md:pt-6 lg:pt-10 bg-background"}
          bind:this={chatContainer}
        >
          {#if messages.length === 0}
            {#if isCompact}
              <!-- Compact empty state — no glow, no big icon, just a one-liner.
               Saves ~200 px of vertical space in narrow side rails. -->
              <div
                class="flex h-full flex-col items-center justify-center px-4 text-center"
              >
                <Icon icon="ph:sparkle" class="mb-2 size-5 text-primary-400" />
                <p class="text-xs text-muted-foreground">
                  Ask <span class="uppercase font-semibold">{agentId}</span> about
                  your query.
                </p>
              </div>
            {:else}
              <div
                class="relative flex h-full flex-col items-center justify-center gap-0 overflow-hidden"
              >
                <!-- Glow blob — z-0, fondo del container, color explícito visible -->
                <div
                  class="pointer-events-none absolute inset-0 z-0 flex items-center justify-center"
                >
                  <div
                    class="h-72 w-72 animate-pulse rounded-full blur-3xl"
                    style="background-color: color-mix(in oklch, var(--color-primary-500) 18%, transparent);"
                  ></div>
                </div>
                <!-- Icon — z-10 -->
                <div class="relative z-10 mb-5">
                  <div
                    class="flex h-16 w-16 items-center justify-center rounded-2xl shadow-lg overflow-hidden"
                    style="background: linear-gradient(135deg, color-mix(in oklch, var(--color-primary-500) 22%, transparent), color-mix(in oklch, var(--color-primary-500) 8%, transparent)); border: 1px solid color-mix(in oklch, var(--color-primary-500) 25%, transparent);"
                  >
                    {#if welcomeIcon}
                      <img
                        src={welcomeIcon}
                        alt="Agent icon"
                        class="h-10 w-10 object-contain"
                      />
                    {:else}
                      <svg
                        xmlns="http://www.w3.org/2000/svg"
                        fill="none"
                        viewBox="0 0 24 24"
                        stroke-width="1.5"
                        stroke="currentColor"
                        style="width:2rem;height:2rem;color:var(--color-primary-400);"
                      >
                        <path
                          stroke-linecap="round"
                          stroke-linejoin="round"
                          d="M8.625 12a.375.375 0 1 1-.75 0 .375.375 0 0 1 .75 0Zm0 0H8.25m4.125 0a.375.375 0 1 1-.75 0 .375.375 0 0 1 .75 0Zm0 0H12m4.125 0a.375.375 0 1 1-.75 0 .375.375 0 0 1 .75 0Zm0 0h-.375M21 12c0 4.556-4.03 8.25-9 8.25a9.764 9.764 0 0 1-2.555-.337A5.972 5.972 0 0 1 5.41 20.97a5.969 5.969 0 0 1-.474-.065 4.48 4.48 0 0 0 .978-2.025c.09-.457-.133-.901-.467-1.226C3.93 16.178 3 14.189 3 12c0-4.556 4.03-8.25 9-8.25s9 3.694 9 8.25Z"
                        />
                      </svg>
                    {/if}
                  </div>
                </div>
                <!-- Texto — z-10 -->
                <h2
                  class="relative z-10 text-2xl font-bold tracking-tight text-foreground mb-1.5"
                >
                  Ask to <span
                    style="color:var(--color-primary-400);"
                    class="uppercase">{agentId}</span
                  >
                </h2>
                <p
                  class="relative z-10 text-sm text-muted-foreground max-w-xs text-center leading-relaxed"
                >
                  Start a conversation — your history is saved automatically.
                </p>

                <StarterPromptBubbles
                  prompts={promptStore.getStarterPrompts()}
                  onSelect={handlePromptSelect}
                />
              </div>
            {/if}
          {:else}
            <!-- Tight padding + smaller vertical gap in compact mode so bubbles don't
             get squished to a 100 px-wide column inside a 280 px side rail. -->
            <div
              bind:this={messagesContent}
              class={isCompact
                ? "flex flex-col gap-3 w-full mx-auto px-2"
                : avatarPanelActive
                  ? "flex flex-col gap-6 w-full mx-auto px-4 md:px-6 lg:px-8"
                  : "flex flex-col gap-6 w-full max-w-3xl mx-auto px-4 md:px-6 lg:px-10"}
            >
              {#if hasMoreMessages}
                <div class="flex justify-center py-2">
                  <button
                    class="text-xs text-muted-foreground hover:text-foreground transition-colors flex items-center gap-1.5 px-3 py-1.5 rounded-full border border-border hover:bg-muted"
                    onclick={loadMoreMessages}
                    disabled={loadingMore}
                  >
                    {#if loadingMore}
                      <Icon icon="mdi:loading" class="size-3.5 animate-spin" />
                      Loading...
                    {:else}
                      <Icon icon="mdi:arrow-up" class="size-3.5" />
                      Load earlier messages
                    {/if}
                  </button>
                </div>
              {/if}
              {#each messages as msg (msg.id)}
                <div data-msg-id={msg.id} class="flex flex-col">
                  {#if msg.type === "auth_required"}
                    <ConnectIntegrationPill
                      provider={msg.provider ?? ""}
                      authUrl={msg.auth_url ?? ""}
                      message={msg.content}
                      {agentId}
                    />
                  {:else}
                    <ChatBubble
                      message={msg}
                      {chartBackend}
                      sessionId={currentSessionId ?? undefined}
                      chatbotId={agentId}
                      {botMode}
                      compact={isCompact}
                      {onSqlArtifact}
                      {showDataActions}
                      onRepeat={handleRepeat}
                      onFollowup={handleFollowup}
                      onExplain={handleExplain}
                      onRetry={handleRetry}
                      onDetailedFeedback={handleDetailedFeedback}
                      onRegenerate={handleRegenerate}
                      onDelete={handleDeleteMessage}
                      onOpenSpreadsheet={handleOpenSpreadsheet}
                      onMoveToCanvas={handleMoveToCanvas}
                      onMoveTableDataToCanvas={handleMoveTableDataToCanvas}
                      onCopyChartToCanvas={handleCopyChartToCanvas}
                      onCopyChartToChartCanvas={handleCopyChartToChartCanvas}
                      onCreateInfographic={handleCreateInfographic}
                      onCancel={pendingQuestions.has(msg.id)
                        ? () => handleCancelQuestion(msg.id)
                        : undefined}
                      isLastAssistantMessage={msg.id === lastAssistantMsgId}
                      isStreaming={isStreaming && msg.id === streamingMessageId}
                    />
                  {/if}
                </div>
              {/each}

              <!-- Pending Questions: stop-all shortcut when multiple -->
              {#if pendingQuestions.size > 1}
                <div class="flex justify-start px-2 py-1">
                  <button
                    class="text-[11px] text-muted-foreground hover:text-red-500 transition-colors flex items-center gap-1"
                    onclick={handleCancelAll}
                  >
                    <Icon icon="mdi:stop-circle-outline" class="size-3.5" />
                    Stop all ({pendingQuestions.size})
                  </button>
                </div>
              {/if}
            </div>
          {/if}
        </div>

        <!-- Input Area — lives inside the left chat column so it aligns under
             the thread (not under the avatar) and shrinks with it. -->
        <div
          class={isCompact
            ? "shrink-0 pt-2 pb-2 px-2 bg-background"
            : "shrink-0 pt-3 pb-5 px-4 md:pb-6 md:px-8 bg-background border-t border-border/20"}
        >
          <div
            class={isCompact || avatarPanelActive
              ? "w-full"
              : "max-w-3xl mx-auto"}
          >
            <ChatInput
              bind:text={inputText}
              onSend={handleSend}
              isLoading={hasPendingQuestions}
              {followupTurnId}
              onClearFollowup={clearFollowup}
              {recentQuestions}
              {allow_custom_llm}
              hideOutputMode={botMode || isCompact}
              enterToSend={isCompact}
              {streamEnabled}
              onToggleStream={handleToggleStream}
              {isStreaming}
              onStopStream={handleStopStream}
              showAdvancedOptions={!botMode && !isCompact}
              enableVoiceInput={enableVoiceNotes && voiceAvailable}
              onSendVoiceNote={handleVoiceNote}
            />
            {#if !isCompact}
              <div class="text-center mt-1.5 pb-0.5">
                <p class="text-[10px] text-slate-400 leading-none">
                  AI agents can make mistakes. Please verify important
                  information.
                </p>
              </div>
            {/if}
          </div>
        </div>
      </div>
      <!-- /Left chat column -->

      <!-- Avatar panel (right on desktop, stacked below on narrow screens).
         A prominent "hero" stage: the docked viewer renders as a large rounded
         video card with breathing room around it (video-call style). -->
      {#if avatarPanelActive}
        <div
          class="shrink-0 w-full md:w-[32rem] lg:w-[40rem] xl:w-[46rem] max-h-[55vh] md:max-h-none border-t md:border-t-0 md:border-l border-border bg-muted/30 flex flex-col overflow-hidden p-3 md:p-4"
        >
          {#if features.avatar && avatarEnabled && currentSessionId}
            {#await import("$lib/components/agents/avatar/AvatarViewer.svelte") then { default: AvatarViewer }}
              <AvatarViewer
                {agentId}
                sessionId={currentSessionId}
                {tenantId}
                enabled={avatarEnabled}
                client={scopedClient}
                bind:collapsed={avatarCollapsed}
                docked
                onstatuschange={handleAvatarStatusChange}
              />
            {/await}
          {/if}

          {#if features.avatar && voiceNativeEnabled && currentSessionId}
            {#await import("$lib/components/agents/avatar/VoiceNativeAvatarViewer.svelte") then { default: VoiceNativeAvatarViewer }}
              <VoiceNativeAvatarViewer
                {agentId}
                sessionId={currentSessionId}
                {tenantId}
                enabled={voiceNativeEnabled}
                client={scopedClient}
                bind:collapsed={avatarCollapsed}
                docked
                onstatuschange={handleVoiceNativeStatusChange}
                onStructured={handleVoiceNativeStructured}
              />
            {/await}
          {/if}
        </div>
      {/if}
    </div>
    <!-- /Thread + Avatar split -->
  </main>

  <!-- Resize Handle + Right Pane: Canvas (collapsible, default closed) -->
  {#if canvasOpen && !canvasExpanded}
    <div
      class={`hidden md:flex items-center justify-center w-1.5 cursor-col-resize hover:bg-primary/20 active:bg-primary/30 transition-colors shrink-0 select-none ${isResizing ? "bg-primary/20" : ""}`}
      onpointerdown={startCanvasResize}
      role="separator"
      aria-orientation="vertical"
      title="Drag to resize canvas"
    >
      <div class="w-0.5 h-8 rounded-full bg-border"></div>
    </div>
  {/if}
  <aside
    class={`hidden md:flex flex-col bg-card border-border overflow-hidden ${canvasOpen ? (canvasExpanded ? "flex-1" : "") : "w-0"}`}
    style={canvasOpen && !canvasExpanded ? `width: ${canvasWidth}px` : ""}
  >
    {#if canvasOpen}
      <div
        class={`${canvasExpanded ? "w-full" : ""} h-full`}
        style={!canvasExpanded ? `width: ${canvasWidth}px` : ""}
      >
        {#if features.canvas}
          {#await import("./canvas/CanvasPanel.svelte") then { default: CanvasPanel }}
            <CanvasPanel onClose={() => chatLayout.closeCanvas()} {agentId} />
          {/await}
        {:else}
          <div class="flex h-full items-center justify-center p-4 text-center text-sm text-muted-foreground">
            Canvas is disabled in this build.
          </div>
        {/if}
      </div>
    {/if}
  </aside>

  <!-- Mobile Drawer -->
  {#if drawerOpen}
    <div class="fixed inset-0 z-50 flex md:hidden">
      <!-- Overlay -->
      <div
        class="absolute inset-0 bg-black/50 backdrop-blur-sm transition-opacity"
        onclick={() => (drawerOpen = false)}
        role="button"
        tabindex="0"
        onkeydown={(e) => e.key === "Escape" && (drawerOpen = false)}
      ></div>

      <!-- Drawer Content -->
      <div
        class="relative w-4/5 max-w-xs bg-card h-full shadow-2xl flex flex-col"
      >
        <div
          class="p-4 border-b border-slate-100 dark:border-slate-700 flex items-center justify-between"
        >
          <h2 class="font-bold text-lg">History</h2>
          <button
            class="btn btn-ghost btn-circle btn-sm"
            onclick={() => (drawerOpen = false)}
            aria-label="Close sidebar"
          >
            <svg
              xmlns="http://www.w3.org/2000/svg"
              fill="none"
              viewBox="0 0 24 24"
              stroke-width="1.5"
              stroke="currentColor"
              class="size-6"
            >
              <path
                stroke-linecap="round"
                stroke-linejoin="round"
                d="M6 18 18 6M6 6l12 12"
              />
            </svg>
          </button>
        </div>
        <div class="flex-1 overflow-y-auto p-2">
          <ConversationList
            {agentId}
            {currentSessionId}
            onSelect={handleSelectConversation}
            onNew={handleNewConversation}
          />
        </div>
        <div class="p-4 border-t border-border flex flex-col gap-2">
          <button
            class={agentChatSidebarItem({ state: "active" })}
            onclick={() => handleNewConversation()}
          >
            + New Chat
          </button>
          <button
            class={agentChatSidebarItem({ state: "idle" })}
            onclick={() => (configModalOpen = true)}
          >
            <Icon icon="mdi:cog" class="h-4 w-4" />
            Settings
          </button>
          <button
            class={agentChatSidebarItem({ state: "idle" })}
            onclick={() => (datasetModalOpen = true)}
          >
            <Icon icon="mdi:database-cog" class="h-4 w-4" />
            Dataset Config...
          </button>
        </div>
      </div>
    </div>
  {/if}

  <!-- Config Modal -->
  {#if features.datasets && configModalOpen}
    {#await import("./DataManagementModal.svelte") then { default: DataManagementModal }}
      <DataManagementModal
        bind:open={configModalOpen}
        {agentId}
        bind:explainPrompt
      />
    {/await}
  {/if}

  <!-- Prompt Library Modal -->
  <PromptLibraryModal bind:open={promptModalOpen} {agentId} {chatbotId} />

  <!-- Dataset Config Modal -->
  {#if features.datasets && datasetModalOpen}
    {#await import("./DatasetConfigModal.svelte") then { default: DatasetConfigModal }}
      <DatasetConfigModal bind:open={datasetModalOpen} {agentId} />
    {/await}
  {/if}
</div>

<style>
  .new-chat-btn {
    background-color: color-mix(
      in oklch,
      var(--color-primary-500) 15%,
      transparent
    );
    border: 1px solid
      color-mix(in oklch, var(--color-primary-500) 30%, transparent);
    color: var(--color-primary-400);
  }
  .new-chat-btn:hover {
    background-color: color-mix(
      in oklch,
      var(--color-primary-500) 28%,
      transparent
    );
    border-color: color-mix(
      in oklch,
      var(--color-primary-500) 55%,
      transparent
    );
    color: var(--color-primary-300);
  }
</style>
