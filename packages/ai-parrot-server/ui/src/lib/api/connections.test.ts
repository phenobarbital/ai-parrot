import { afterEach, describe, expect, it, vi } from "vitest";

const mocks = vi.hoisted(() => ({
  client: {
    get: vi.fn(),
    post: vi.fn(),
    delete: vi.fn(),
  },
  getAuthHeaders: vi.fn(() => ({ Authorization: "Bearer test-token" })),
}));

vi.mock("$lib/api/http", () => ({
  ApiError: class ApiError extends Error {
    constructor(
      message: string,
      public kind: string,
      public status?: number,
      public raw?: unknown,
    ) {
      super(message);
    }
  },
  createApiClient: () => mocks.client,
}));
vi.mock("$lib/api/auth-headers", () => ({ getAuthHeaders: mocks.getAuthHeaders }));
vi.mock("$lib/config", () => ({ config: { apiBaseUrl: "https://api.example.test" } }));

import {
  confirmChannelLink,
  disconnect,
  getConnection,
  listConnections,
  openConnectionEvents,
  parseSseBlock,
  previewChannelLink,
  startConnect,
} from "$lib/api/connections";

describe("connections API", () => {
  afterEach(() => {
    vi.restoreAllMocks();
    mocks.client.get.mockReset();
    mocks.client.post.mockReset();
    mocks.client.delete.mockReset();
  });

  it("parses connection events, including multiline data", () => {
    expect(parseSseBlock('event: connection\ndata: {"kind":"connection.\ndata: completed"}')).toEqual({
      kind: "connection.\ncompleted",
    });
    expect(parseSseBlock(": keep-alive")).toBeNull();
    expect(parseSseBlock('event: other\ndata: {"kind":"ignored"}')).toBeNull();
    expect(parseSseBlock("event: connection\ndata: not-json")).toBeNull();
  });

  it("uses encoded principal-scoped routes and request bodies", async () => {
    mocks.client.get.mockResolvedValue({ data: [] });
    mocks.client.post.mockResolvedValue({ data: { auth_url: "url" } });
    mocks.client.delete.mockResolvedValue({ data: { provider: "web/slack", disconnected: true } });

    await listConnections();
    await getConnection("web/slack");
    await startConnect("web/slack", "https://ui.example.test", ["read"]);
    await disconnect("web/slack");
    await previewChannelLink("token/value");
    await confirmChannelLink("token/value");

    expect(mocks.client.get).toHaveBeenNthCalledWith(1, "/api/v1/connections");
    expect(mocks.client.get).toHaveBeenNthCalledWith(2, "/api/v1/connections/web%2Fslack");
    expect(mocks.client.get).toHaveBeenNthCalledWith(3, "/api/v1/channel-links/token%2Fvalue");
    expect(mocks.client.post).toHaveBeenNthCalledWith(
      1,
      "/api/v1/connections/web%2Fslack/start",
      { return_origin: "https://ui.example.test", scopes: ["read"] },
    );
    expect(mocks.client.post).toHaveBeenNthCalledWith(
      2,
      "/api/v1/channel-links/token%2Fvalue/confirm",
      { confirm: true },
    );
    expect(mocks.client.delete).toHaveBeenCalledWith("/api/v1/connections/web%2Fslack");
  });

  it("sends auth headers and dispatches frames split across reads", async () => {
    const controller = new ReadableStream<Uint8Array>({
      start(streamController) {
        streamController.enqueue(new TextEncoder().encode('event: connection\ndata: {"kind":"connection.'));
        streamController.enqueue(new TextEncoder().encode('completed"}\n\n: keep-alive\n\n'));
        streamController.close();
      },
    });
    const fetchMock = vi.fn().mockResolvedValue(new Response(controller, { status: 200 }));
    vi.stubGlobal("fetch", fetchMock);
    const signal = new AbortController().signal;
    const onEvent = vi.fn();

    await openConnectionEvents(onEvent, signal);

    expect(fetchMock).toHaveBeenCalledWith(
      "https://api.example.test/api/v1/connections/events",
      expect.objectContaining({
        headers: { Accept: "text/event-stream", Authorization: "Bearer test-token" },
        signal,
      }),
    );
    expect(onEvent).toHaveBeenCalledOnce();
    expect(onEvent).toHaveBeenCalledWith({ kind: "connection.completed" });
  });
});
