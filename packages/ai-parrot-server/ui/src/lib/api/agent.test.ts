import { afterEach, describe, expect, it, vi } from "vitest";

import apiClient from "$lib/api/http";
import { config } from "$lib/config";

import { chatWithAgent, uploadAgentData } from "./agent";

describe("chatWithAgent (stream: false path)", () => {
  afterEach(() => {
    vi.restoreAllMocks();
    localStorage.clear();
  });

  it("POSTs /api/v1/agents/chat/<name> with output_format: json", async () => {
    const post = vi.spyOn(apiClient, "post").mockResolvedValue({
      data: { input: "hi", output: "hello", metadata: {}, sources: [], tool_calls: [] },
    });

    await chatWithAgent("my-agent", { query: "hi", stream: false });

    expect(post).toHaveBeenCalledWith(
      "/api/v1/agents/chat/my-agent",
      { query: "hi", stream: false, output_format: "json" },
      { signal: undefined },
    );
  });

  it("sends the bearer token via apiClient's request interceptor", async () => {
    localStorage.setItem(config.tokenStorageKey, "test-token");

    // Replace only the transport adapter (not `.post()` itself) so the
    // real request interceptor — which attaches `Authorization` — still
    // runs; the adapter receives the fully-resolved AxiosRequestConfig.
    let capturedHeaders: Record<string, unknown> = {};
    const originalAdapter = apiClient.defaults.adapter;
    apiClient.defaults.adapter = (async (cfg: any) => {
      capturedHeaders = cfg.headers;
      return { data: {}, status: 200, statusText: "OK", headers: {}, config: cfg };
    }) as typeof apiClient.defaults.adapter;

    try {
      await chatWithAgent("my-agent", { query: "hi", stream: false });
    } finally {
      apiClient.defaults.adapter = originalAdapter;
    }

    expect(capturedHeaders.Authorization).toBe("Bearer test-token");
  });
});

describe("uploadAgentData", () => {
  afterEach(() => {
    vi.restoreAllMocks();
  });

  it("PUTs the multipart body and returns the response body", async () => {
    const body = {
      files: [{ file_id: "f-1", filename: "report.docx" }],
      dataframes: [],
      errors: [],
      agent: "my-agent",
    };
    const put = vi.spyOn(apiClient, "put").mockResolvedValue({ data: body });
    const formData = new FormData();

    const result = await uploadAgentData("my-agent", formData);

    expect(put).toHaveBeenCalledWith("/api/v1/agents/chat/my-agent", formData, {
      headers: { "Content-Type": "multipart/form-data" },
    });
    expect(result).toBe(body);
  });
});
