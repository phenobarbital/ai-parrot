// ai-parrot: trimmed to client-side shapes only (FEAT-476 TASK-2592). The
// hand-written `AgentMetadata`, `AgentToolCall` and `AgentChatResponse`
// interfaces navigator defined here are replaced by the codegen-generated
// types from the `AgentTalk` envelope contract (TASK-2590,
// `parrot.server.ui.chat_models`) so drift between the backend dict
// builders and the UI fails CI instead of silently diverging — spec §2
// Data Models / §3 Module 2.
import type { SourceLink, BotDocumentEntry } from "$lib/types/bot-chat.js";
import type { AgentToolCall as GeneratedAgentToolCall } from "$lib/types/generated/AgentChatResponse";
import type { A2UIEnvelope } from "$lib/components/agents/canvas/a2ui/a2ui-types";

export interface AgentChatRequest {
  ws_channel_id?: string;
  query: string;
  session_id?: string;
  [key: string]: any; // Allow for extra properties if needed
}

export type {
  AgentChatResponse,
  AgentChatMetadata as AgentMetadata,
  AgentToolCall,
} from "$lib/types/generated/AgentChatResponse";

export interface AgentMessage {
  id: string; // generated UUID or turn_id
  role: "user" | "assistant";
  content: string;
  timestamp: Date;
  metadata?: import("$lib/types/generated/AgentChatResponse").AgentChatMetadata;
  data?: any;
  code?: string | null;
  output?: any; // For structured output (like ECharts JSON)
  tool_calls?: GeneratedAgentToolCall[];
  output_mode?: string;
  htmlResponse?: string | null; // Full HTML response for iframe rendering
  sources?: SourceLink[]; // Resolved source links for rendering (bot mode)
  documents?: Record<string, BotDocumentEntry>; // Raw documents dict from API (for persistence)
  // OAuth2 auth_required envelope fields
  type?: string; // "auth_required" for OAuth2 prompts
  provider?: string; // OAuth2 provider slug (e.g., "jira")
  auth_url?: string; // Authorization URL for the popup flow
  scopes?: string[]; // Requested OAuth2 scopes
  // Voice answer (AgentTalk Voice): the spoken contestation rendered as a
  // player beneath the assistant text. Kept in-memory only (not persisted to
  // IndexedDB to avoid bloat) — degrades to text-only on reload.
  audio_base64?: string;
  audio_format?: string;
  // A2UI envelope (FEAT-527): present on both `output_mode: "infographic"`
  // (dual-emit, additive) and `output_mode: "a2ui"` turns.
  a2ui_envelope?: A2UIEnvelope;
}

/**
 * Structured output payload produced by parrot's ``DatabaseAgent`` (e.g.
 * the ``sql_analyst`` plugin). Sent on the wire when ``output_mode ===
 * "sql_analysis"``. The frontend renders ``query`` as a dedicated SQL
 * artifact card; ``explanation`` flows through ``message.content`` and
 * renders as normal bubble markdown.
 */
export interface SqlAnalysisOutput {
  explanation: string;
  query: string | null;
  data_variable?: string | null;
  data_variables?: string[] | null;
  data?: {
    columns: string[];
    row_count: number;
    execution_time_ms: number | null;
  } | null;
}

export interface AgentConversation {
  id: string; // session_id
  title: string;
  created_at: Date;
  updated_at: Date;
  agent_name: string;
  last_message?: string;
}

/**
 * Payload returned by the backend when the agent calls interactive_render.
 * Arrives as AgentChatResponse.output when output_mode === "interactive".
 * See: ai-parrot/docs/interactive_artifacts_api.md
 */
export interface InteractiveArtifactResult {
  type: "interactive";
  artifact_id: string;
  html_url: string;
  html_inline: string | null;
  template_name: string;
  theme: string | null;
  libraries_used: string[];
  enhanced: boolean;
}

/**
 * Data stored in the canvas tab for interactive artifacts.
 * Passed as the `data` prop to InteractiveArtifactCanvas.svelte.
 */
export interface InteractiveArtifactTabData {
  artifact_id: string;
  html_inline: string | null;
  html_url?: string;
  template_name: string;
  theme: string | null;
  libraries_used: string[];
  enhanced: boolean;
  session_id?: string;
}
