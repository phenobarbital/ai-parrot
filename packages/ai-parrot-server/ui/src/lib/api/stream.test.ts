import { it, expect, vi, afterEach } from "vitest";
import { streamChatWithAgent } from "./stream";

const enc = new TextEncoder();

function resp(parts: string[], status = 200) {
  const stream = new ReadableStream({
    start(c) {
      parts.forEach((p) => c.enqueue(enc.encode(p)));
      c.close();
    },
  });
  return new Response(stream, { status });
}

afterEach(() => {
  vi.unstubAllGlobals();
});

it("splits text and final JSON around \\x00", async () => {
  vi.stubGlobal(
    "fetch",
    vi.fn().mockResolvedValue(
      resp([
        "Hel",
        'lo\n\x00{"input":"q","output":"Hello","metadata":{"session_id":"s","turn_id":"t"},"sources":[],"tool_calls":[]}',
      ]),
    ),
  );
  const out = [];
  for await (const c of streamChatWithAgent("bot", { query: "q", stream: true })) out.push(c);
  expect(out.map((c) => c.type)).toEqual(["chunk", "chunk", "done"]);
});

// NOTE: the task's Test Specification describes this case as
// "handles a body without separator ... yields `done`", but the ported
// `consumeStream` (navigator src/lib/api/stream.ts, unmodified per the
// copy-in doctrine) only ever emits `{type: "done"}` when the `\x00`
// separator was actually seen — a body with no separator at all is
// forwarded purely as `chunk` events, never parsed as JSON. Asserting
// the real (ported) behavior here rather than the spec snippet's
// literal wording; flagged in TASK-2592's Completion Note.
it("handles a body without separator (streamed as chunks, not parsed as JSON)", async () => {
  vi.stubGlobal(
    "fetch",
    vi.fn().mockResolvedValue(resp(['{"output":"x","metadata":{}}'])),
  );
  const out = [];
  for await (const c of streamChatWithAgent("bot", { query: "q", stream: true })) out.push(c);
  expect(out.every((c) => c.type === "chunk")).toBe(true);
  expect(out.some((c) => c.type === "done")).toBe(false);
});

it("finds the separator at the very start of a chunk", async () => {
  vi.stubGlobal(
    "fetch",
    vi.fn().mockResolvedValue(
      resp(["\x00{\"input\":\"q\",\"output\":\"o\",\"metadata\":{},\"sources\":[],\"tool_calls\":[]}"]),
    ),
  );
  const out = [];
  for await (const c of streamChatWithAgent("bot", { query: "q", stream: true })) out.push(c);
  expect(out.map((c) => c.type)).toEqual(["done"]);
});

it("finds the separator at the very end of a chunk, JSON spanning the next read", async () => {
  vi.stubGlobal(
    "fetch",
    vi.fn().mockResolvedValue(
      resp([
        "Hello\x00",
        '{"input":"q","output":"o","metadata":{},',
        '"sources":[],"tool_calls":[]}',
      ]),
    ),
  );
  const out = [];
  for await (const c of streamChatWithAgent("bot", { query: "q", stream: true })) out.push(c);
  expect(out.map((c) => c.type)).toEqual(["chunk", "done"]);
});

it("throws ApiError('auth') on a 401 response", async () => {
  vi.stubGlobal("fetch", vi.fn().mockResolvedValue(resp(["unauthorized"], 401)));
  await expect(async () => {
    for await (const _ of streamChatWithAgent("bot", { query: "q", stream: true })) {
      // drain
    }
  }).rejects.toMatchObject({ code: "auth" });
});

it("propagates AbortError when the signal is aborted", async () => {
  const controller = new AbortController();
  vi.stubGlobal(
    "fetch",
    vi.fn().mockImplementation(() => {
      const err = new Error("aborted");
      err.name = "AbortError";
      return Promise.reject(err);
    }),
  );
  controller.abort();
  await expect(async () => {
    for await (const _ of streamChatWithAgent(
      "bot",
      { query: "q", stream: true },
      controller.signal,
    )) {
      // drain
    }
  }).rejects.toThrow("aborted");
});
