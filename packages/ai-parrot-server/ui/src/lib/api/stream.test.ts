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

// ── FEAT-752 rev 0.3: suggestions trailer (second NUL-delimited frame) ──────────────────────────

const ENVELOPE =
  '{"input":"q","output":"o","metadata":{"session_id":"s","turn_id":"t1"},"sources":[],"tool_calls":[]}';

/** A response whose body bytes are released by the test, to prove ordering across reads. */
function controlled() {
  let controller!: ReadableStreamDefaultController<Uint8Array>;
  const stream = new ReadableStream<Uint8Array>({
    start(c) {
      controller = c;
    },
  });
  return {
    response: new Response(stream, { status: 200 }),
    push: (s: string) => controller.enqueue(enc.encode(s)),
    close: () => controller.close(),
  };
}

async function collect(parts: string[]) {
  vi.stubGlobal("fetch", vi.fn().mockResolvedValue(resp(parts)));
  const out = [];
  for await (const c of streamChatWithAgent("bot", { query: "q", stream: true })) out.push(c);
  return out;
}

it("yields done before EOF when a trailer frame follows, then the suggestions chunk", async () => {
  const body = controlled();
  vi.stubGlobal("fetch", vi.fn().mockResolvedValue(body.response));
  const it = streamChatWithAgent("bot", { query: "q", stream: true })[Symbol.asyncIterator]();

  body.push(`Hi\x00${ENVELOPE}\x00`); // text + envelope + start of the trailer frame; trailer bytes not sent yet
  expect((await it.next()).value).toEqual({ type: "chunk", text: "Hi" });
  const done = (await it.next()).value;
  expect(done.type).toBe("done"); // delivered while the stream is still open
  expect(done.message.metadata.turn_id).toBe("t1");

  body.push('{"suggestions":[{"label":"A","prompt":"a"}],"turn_id":"t1"}');
  body.close();
  const chips = (await it.next()).value;
  expect(chips).toEqual({
    type: "suggestions",
    suggestions: [{ label: "A", prompt: "a" }],
    turn_id: "t1",
  });
  expect((await it.next()).done).toBe(true);
});

it("handles a trailer split across reads and a separator at a read boundary", async () => {
  const out = await collect([
    "Hel",
    `lo\x00${ENVELOPE.slice(0, 30)}`,
    `${ENVELOPE.slice(30)}\x00{"suggestions":[{"label":"A",`,
    '"prompt":"a"}],"turn_id":"t1"}',
  ]);
  expect(out.map((c) => c.type)).toEqual(["chunk", "chunk", "done", "suggestions"]);
});

it("ignores a trailing error frame (no suggestions, done still delivered)", async () => {
  const out = await collect([`Hi\x00${ENVELOPE}\x00{"error":"boom"}`]);
  expect(out.map((c) => c.type)).toEqual(["chunk", "done"]);
});

it("ignores malformed trailer frames and non-array suggestions", async () => {
  expect((await collect([`Hi\x00${ENVELOPE}\x00{not json`])).map((c) => c.type)).toEqual(["chunk", "done"]);
  expect((await collect([`Hi\x00${ENVELOPE}\x00{"suggestions":"nope"}`])).map((c) => c.type)).toEqual([
    "chunk",
    "done",
  ]);
  expect((await collect([`Hi\x00${ENVELOPE}\x00[1,2]`])).map((c) => c.type)).toEqual(["chunk", "done"]);
});

it("keeps single-frame streams unchanged: done is yielded at EOF, no suggestions", async () => {
  const out = await collect([`Hi\x00${ENVELOPE}`]);
  expect(out.map((c) => c.type)).toEqual(["chunk", "done"]);
});

it("yields suggestions without a turn_id when the trailer omits it", async () => {
  const out = await collect([`\x00${ENVELOPE}\x00{"suggestions":[]}`]);
  const chips = out.find((c) => c.type === "suggestions") as any;
  expect(chips).toEqual({ type: "suggestions", suggestions: [], turn_id: undefined });
});
