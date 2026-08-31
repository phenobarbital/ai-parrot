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
 */

import { browser } from "$app/environment";
import { config } from "$lib/config";
import { ApiError } from "$lib/api/http";
import { getAuthHeaders as getBaseAuthHeaders } from "$lib/api/auth-headers";
import type { AgentChatRequest, AgentChatResponse } from "$lib/types/agent";
import type { BotChatRequest, BotChatResponse } from "$lib/types/bot-chat";

export type StreamChunk =
  | { type: "chunk"; text: string }
  | { type: "done"; message: AgentChatResponse | BotChatResponse };

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

/**
 * Internal helper: consume a ReadableStream and yield StreamChunk events.
 *
 * The protocol splits text from the final JSON AIMessage with a NUL byte:
 *   <text...>\x00{json}
 * Text before the NUL streams out as chunks; bytes after it accumulate until
 * EOF and are parsed as the final AIMessage. The separator can land anywhere
 * inside a TextDecoder read (start, middle, end), and the JSON itself can span
 * multiple reads — both are handled by buffering after the separator.
 */
async function* consumeStream(response: Response): AsyncGenerator<StreamChunk> {
  if (!response.body) {
    throw new ApiError("Response body is null", "network");
  }

  const reader = response.body.getReader();
  const decoder = new TextDecoder();

  let separatorSeen = false;
  let jsonBuffer = "";

  const emitText = function* (text: string): Generator<StreamChunk> {
    if (text) yield { type: "chunk", text };
  };

  try {
    while (true) {
      const { done, value } = await reader.read();
      if (done) break;

      const text = decoder.decode(value, { stream: true });
      if (!text) continue;

      if (separatorSeen) {
        jsonBuffer += text;
        continue;
      }

      const sepIdx = text.indexOf(SEPARATOR);
      if (sepIdx === -1) {
        yield* emitText(text);
      } else {
        yield* emitText(text.slice(0, sepIdx));
        separatorSeen = true;
        jsonBuffer += text.slice(sepIdx + SEPARATOR.length);
      }
    }

    // Flush any remaining bytes from the decoder
    const remaining = decoder.decode();
    if (remaining) {
      if (separatorSeen) {
        jsonBuffer += remaining;
      } else {
        const sepIdx = remaining.indexOf(SEPARATOR);
        if (sepIdx === -1) {
          yield* emitText(remaining);
        } else {
          yield* emitText(remaining.slice(0, sepIdx));
          separatorSeen = true;
          jsonBuffer += remaining.slice(sepIdx + SEPARATOR.length);
        }
      }
    }
  } finally {
    reader.releaseLock();
  }

  if (separatorSeen && jsonBuffer.trim()) {
    try {
      const parsed = JSON.parse(jsonBuffer);
      if (
        parsed !== null &&
        typeof parsed === "object" &&
        !Array.isArray(parsed)
      ) {
        yield {
          type: "done",
          message: parsed as unknown as AgentChatResponse | BotChatResponse,
        };
      }
    } catch {
      // Malformed JSON after separator — fall through; caller treats absence
      // of 'done' as a stream that was cut short and uses the partial text.
    }
  }
}

/**
 * Stream a chat request to an agent via HTTP chunked transfer encoding.
 *
 * Yields { type: 'chunk', text } for each text fragment, and
 * { type: 'done', message } when the final JSON chunk is received.
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
