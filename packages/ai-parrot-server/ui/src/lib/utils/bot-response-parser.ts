import type { BotDocumentEntry, SourceLink } from "$lib/types/bot-chat.js";
import { config } from "$lib/config.js";

/**
 * Strip the ## **Sources:** section from the response markdown.
 * Returns only the answer portion for rendering in the chat bubble.
 */
export function stripSourcesFromResponse(response: string): string {
  const sourceSeparator = /## \*\*Sources:\*\*/i;
  return response.split(sourceSeparator)[0].trim();
}

/**
 * Resolve the `documents` dictionary into SourceLink[] with real URLs.
 *
 * - file:// keys → rewrite using file_path: extract path after "/static/"
 *   and prepend config.apiBaseUrl
 * - https:// keys (YouTube, etc.) → use the key URL as-is
 */
export function resolveDocumentSources(
  documents: Record<string, BotDocumentEntry> | null | undefined,
): SourceLink[] {
  if (!documents) return [];

  const results: SourceLink[] = [];

  for (const [key, doc] of Object.entries(documents)) {
    if (key.startsWith("file://")) {
      const filePath = doc.file_path || "";
      if (!filePath) continue; // Skip entries with empty file_path

      const staticIndex = filePath.indexOf("/static/");
      const relativePath =
        staticIndex !== -1
          ? filePath.substring(staticIndex) // "/static/assembly/PDFs/doc.pdf"
          : `/static/${filePath}`; // fallback

      // URL-encode the path to handle spaces and special characters
      const encodedPath = encodeURI(relativePath);

      results.push({
        title: doc.filename || key.replace("file://", ""),
        url: `${config.apiBaseUrl}${encodedPath}`,
        type: "document",
        icon: "mdi:file-document-outline",
      });
    } else {
      // HTTP/HTTPS URL — YouTube or other web source
      const isYoutube = key.includes("youtube.com") || key.includes("youtu.be");

      results.push({
        title: doc.docinfo?.title || doc.title || doc.filename || key,
        url: key,
        type: isYoutube ? "video" : "web",
        icon: isYoutube ? "mdi:youtube" : "mdi:web",
      });
    }
  }

  return results;
}

/**
 * Resolve the RAG agent `sources` array (top-level field on AgentChatResponse)
 * into SourceLink[] for rendering in SourcesPanel.
 *
 * Each entry typically carries `url`/`source`, `filename`, optional `file_path`,
 * and a `metadata` blob. Multiple chunks of the same document are deduped by URL.
 */
export function resolveAgentSources(sources: unknown): SourceLink[] {
  if (!Array.isArray(sources)) return [];

  const seen = new Set<string>();
  const results: SourceLink[] = [];

  for (const raw of sources) {
    if (!raw || typeof raw !== "object") continue;
    const src = raw as Record<string, any>;

    const filePath: string = src.file_path || src.source_path || "";
    const rawUrl: string = src.url || src.source || "";

    let url = rawUrl;
    let type: SourceLink["type"] = "web";
    let icon = "mdi:web";

    if (rawUrl.includes("youtube.com") || rawUrl.includes("youtu.be")) {
      type = "video";
      icon = "mdi:youtube";
    } else if (filePath || rawUrl.startsWith("file://")) {
      type = "document";
      icon = "mdi:file-document-outline";
      const path = filePath || rawUrl.replace(/^file:\/\//, "");
      const staticIndex = path.indexOf("/static/");
      const relativePath =
        staticIndex !== -1
          ? path.substring(staticIndex)
          : `/static/${path.replace(/^\/+/, "")}`;
      url = `${config.apiBaseUrl}${encodeURI(relativePath)}`;
    }

    if (!url || seen.has(url)) continue;
    seen.add(url);

    const title =
      src.filename ||
      src.metadata?.document_meta?.title ||
      src.metadata?.filename ||
      url;

    results.push({ title, url, type, icon });
  }

  return results;
}
