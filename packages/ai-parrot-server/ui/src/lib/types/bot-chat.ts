export interface BotChatRequest {
  query: string;
  session_id: string;
  message_id?: string;
  turn_id?: string;
}

/** Raw document entry from the documents dictionary */
export interface BotDocumentEntry {
  filename?: string;
  file_path?: string; // e.g. "/nfs/static/assembly/PDFs/doc.pdf"
  content_type?: string;
  // Video-specific fields
  id?: string;
  title?: string;
  docinfo?: {
    url?: string;
    title?: string;
    author?: string;
    embed_url?: string;
    video_id?: string;
    watch_url?: string;
    view_count?: number;
    description?: string;
    publish_date?: string;
  };
  language?: string;
}

export interface BotChatResponse {
  input: string;
  output: string; // Plain text answer
  response: string; // Markdown with embedded ## **Sources:** section
  data: any;
  documents: Record<string, BotDocumentEntry>; // Keyed by source URL
  model: string;
  provider: string;
  usage: {
    prompt_tokens: number;
    completion_tokens: number;
    total_tokens: number;
  };
  session_id: string;
  turn_id: string;
  output_mode: string;
}

/** Resolved source link ready for rendering */
export interface SourceLink {
  title: string; // Display name (filename or video title)
  url: string; // Resolved clickable URL
  type: "document" | "video" | "web"; // Source category
  icon?: string; // Optional icon hint
}
