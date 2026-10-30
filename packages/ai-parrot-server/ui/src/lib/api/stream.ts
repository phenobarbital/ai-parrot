/**
 * Streaming API functions for AgentChat.
 *
 * These use native fetch() + ReadableStream to consume HTTP chunked transfer
 * encoding responses from the backend. They sit alongside the existing
 * Axios-based chatWithAgent() / chatWithBot() functions.
 *
 * The backend streaming endpoint (X-Parrot-Stream: chunked-aimessage) emits:
 *   <utf8 text chunks...>\x00{...AIMessage JSON...}
 *
 * The NUL byte (\x00) separates the streamed text from the final JSON object.
 * With the opt-in `suggestions_trailer` request flag the server appends a second
 * frame after the envelope (X-Parrot-Stream: chunked-aimessage+suggestions):
 *   <text...>\x00{envelope}\x00{"suggestions": [...], "turn_id": "..."}
 * Every NUL starts a new JSON frame; frame #1 is the envelope, later frames are
 * trailers.
 */

import { browser } from "$app/environment";
import { config } from "$lib/config";
import { ApiError } from "$lib/api/http";
import { getAuthHeaders as getBaseAuthHeaders } from "$lib/api/auth-headers";
import type { AgentChatRequest, AgentChatResponse } from "$lib/types/agent";
import type { BotChatRequest, BotChatResponse } from "$lib/types/bot-chat";
import type { AgentChatSuggestion } from "$lib/types/generated/AgentChatResponse";

export type StreamChunk =
  | { type: "chunk"; text: string }
  | { type: "done"; message: AgentChatResponse | BotChatResponse }
  | { type: "suggestions"; suggestions: AgentChatSuggestion[]; turn_id?: string };

const SEPARATOR = "\x00";

/**
 * Read the auth token from localStorage and return headers including Content-Type.
 * Delegates token extraction to the shared getAuthHeaders utility.
 */
function getAuthHeaders(): Record<string, string> {
  return {
    "Content-Type": "application/json",
    ...getBaseAuthHeaders(),
  };
}

/** Parse one JSON frame; returns the object, or null for empty/malformed/non-object frames. */
function parseObjectFrame(text: string): Record<string, unknown> | null {
  if (!text.trim()) return null;
  try {
    const parsed = JSON.parse(text);
    if (parsed !== null && typeof parsed === "object" && !Array.isArray(parsed)) {
      return parsed as Record<string, unknown>;
    }
  } catch {
    // Malformed JSON: the caller treats the absence of a chunk as a stream cut short.
  }
  return null;
}

/**
 * Internal helper: consume a ReadableStream and yield StreamChunk events.
 *
 * The protocol splits text from the final JSON AIMessage with a NUL byte:
 *   <text...>\x00{json}[\x00{trailer json}]
 * Text before the first NUL streams out as chunks. Each later NUL starts a new
 * JSON frame: frame #1 is the AIMessage envelope — `done` is yielded as soon as
 * the second NUL proves it complete (or at EOF for single-frame streams, old
 * servers and bot chat). Later frames are trailers; one carrying a `suggestions`
 * array yields a `suggestions` chunk, anything else (e.g. a late error frame) is
 * ignored. The separator can land anywhere inside a TextDecoder read, and a frame
 * can span multiple reads — both are handled by buffering per frame.
 */
async function* consumeStream(response: Response): AsyncGenerator<StreamChunk> {
  if (!response.body) {
    throw new ApiError("Response body is null", "network");
  }

  const reader = response.body.getReader();
  const decoder = new TextDecoder();

  let separatorSeen = false;
  let doneYielded = false;
  const frames: string[] = []; // frames[0] = envelope, frames[1..] = trailers

  const feed = function* (text: string): Generator<StreamChunk> {
    let rest = text;
    if (!separatorSeen) {
      const sepIdx = rest.indexOf(SEPARATOR);
      if (sepIdx === -1) {
        if (rest) yield { type: "chunk", text: rest };
        return;
      }
      if (sepIdx > 0) yield { type: "chunk", text: rest.slice(0, sepIdx) };
      separatorSeen = true;
      frames.push("");
      rest = rest.slice(sepIdx + SEPARATOR.length);
    }
    while (true) {
      const sepIdx = rest.indexOf(SEPARATOR);
      if (sepIdx === -1) {
        frames[frames.length - 1] += rest;
        return;
      }
      frames[frames.length - 1] += rest.slice(0, sepIdx);
      if (!doneYielded && frames.length === 1) {
        // A second NUL proves the envelope complete: finish the answer now.
        doneYielded = true;
        const envelope = parseObjectFrame(frames[0]);
        if (envelope) {
          yield { type: "done", message: envelope as unknown as AgentChatResponse | BotChatResponse };
        }
      }
      frames.push("");
      rest = rest.slice(sepIdx + SEPARATOR.length);
    }
  };

  try {
    while (true) {
      const { done, value } = await reader.read();
      if (done) break;
      const text = decoder.decode(value, { stream: true });
      if (text) yield* feed(text);
    }
    // Flush any remaining bytes from the decoder
    const remaining = decoder.decode();
    if (remaining) yield* feed(remaining);
  } finally {
    reader.releaseLock();
  }

  if (!separatorSeen) return;

  if (!doneYielded) {
    doneYielded = true;
    const envelope = parseObjectFrame(frames[0]);
    if (envelope) {
      yield { type: "done", message: envelope as unknown as AgentChatResponse | BotChatResponse };
    }
  }

  for (const frame of frames.slice(1)) {
    const trailer = parseObjectFrame(frame);
    if (trailer && Array.isArray(trailer.suggestions)) {
      yield {
        type: "suggestions",
        suggestions: trailer.suggestions as AgentChatSuggestion[],
        turn_id: typeof trailer.turn_id === "string" ? trailer.turn_id : undefined,
      };
    }
  }
}

/**
 * Stream a chat request to an agent via HTTP chunked transfer encoding.
 *
 * Yields { type: 'chunk', text } for each text fragment, and
 * { type: 'done', message } when the final JSON chunk is received. When the
 * request opted in with `suggestions_trailer`, a later
 * { type: 'suggestions', suggestions, turn_id? } follows the `done` chunk.
 *
 * Throws ApiError on non-2xx responses or network failures.
 * Propagates AbortError when the signal is aborted (caller handles it).
 */
export async function* streamChatWithAgent(
  agentName: string,
  request: AgentChatRequest & { stream: true },
  signal?: AbortSignal,
  baseUrl?: string,
): AsyncGenerator<StreamChunk> {
  if (!browser) {
    throw new TypeError(
      "streamChatWithAgent must only be called in the browser",
    );
  }

  const url = `${baseUrl ?? config.apiBaseUrl}/api/v1/agents/chat/${agentName}`;

  let response: Response;
  try {
    response = await fetch(url, {
      method: "POST",
      headers: getAuthHeaders(),
      body: JSON.stringify(request),
      signal,
    });
  } catch (err: unknown) {
    if (err instanceof Error && err.name === "AbortError") {
      throw err; // Let caller handle abort
    }
    throw new ApiError("Network unavailable", "network", undefined, err);
  }

  if (!response.ok) {
    const code = response.status === 401 ? "auth" : "server";
    throw new ApiError(`HTTP ${response.status}`, code, response.status);
  }

  yield* consumeStream(response);
}

/**
 * Stream a chat request to a bot via HTTP chunked transfer encoding.
 *
 * Yields { type: 'chunk', text } for each text fragment, and
 * { type: 'done', message } when the final JSON chunk is received.
 *
 * Throws ApiError on non-2xx responses or network failures.
 * Propagates AbortError when the signal is aborted (caller handles it).
 */
export async function* streamChatWithBot(
  chatbotId: string,
  request: BotChatRequest & { stream: true },
  signal?: AbortSignal,
  baseUrl?: string,
): AsyncGenerator<StreamChunk> {
  if (!browser) {
    throw new TypeError("streamChatWithBot must only be called in the browser");
  }

  const url = `${baseUrl ?? config.apiBaseUrl}/api/v1/chat/${chatbotId}`;

  let response: Response;
  try {
    response = await fetch(url, {
      method: "POST",
      headers: getAuthHeaders(),
      body: JSON.stringify(request),
      signal,
    });
  } catch (err: unknown) {
    if (err instanceof Error && err.name === "AbortError") {
      throw err; // Let caller handle abort
    }
    throw new ApiError("Network unavailable", "network", undefined, err);
  }

  if (!response.ok) {
    const code = response.status === 401 ? "auth" : "server";
    throw new ApiError(`HTTP ${response.status}`, code, response.status);
  }

  yield* consumeStream(response);
}
