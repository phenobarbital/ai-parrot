import { fireEvent, render, waitFor } from "@testing-library/svelte";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import apiClient from "$lib/api/http";
import { config } from "$lib/config";
import { router } from "$lib/router.svelte";
import type { AdminCatalog } from "$lib/types/generated/AdminCatalog";
import type { BotAgentItem } from "$lib/types/generated/BotAgentItem";
import type { ToolInfo } from "$lib/types/generated/ToolsListResponse";

import AgentForm from "./AgentForm.svelte";

const catalog: AdminCatalog = {
  llm_providers: ["google", "openai"],
  operation_modes: ["conversational", "agentic", "adaptive"],
  memory_types: ["memory", "file", "redis"],
  knowledge_bases: [],
  bot_class_default: "BasicBot",
};

const tools: Record<string, ToolInfo> = {
  search_web: { tool_name: "search_web", module_path: "parrot_tools.search.SearchWeb" },
};

function dbAgent(overrides: Partial<BotAgentItem> = {}): BotAgentItem {
  return {
    chatbot_id: "11111111-1111-1111-1111-111111111111",
    name: "helpdesk",
    source: "database",
    description: "Handles support tickets",
    avatar: null,
    enabled: true,
    timezone: "UTC",
    role: "Support Agent",
    goal: "Resolve tickets quickly.",
    backstory: "I help with support.",
    rationale: "I stay calm and professional.",
    capabilities: "I can search the KB.",
    system_prompt_template: null,
    human_prompt_template: null,
    pre_instructions: [],
    prompt_config: {},
    llm: "google",
    model_config: {},
    tools_enabled: true,
    auto_tool_detection: true,
    tool_threshold: 0.7,
    tools: [],
    operation_mode: "adaptive",
    use_kb: false,
    kb: [],
    custom_kbs: null,
    use_vector: false,
    vector_store_config: {},
    reranker_config: {},
    parent_searcher_config: {},
    context_search_limit: 10,
    context_score_threshold: 0.7,
    memory_type: "memory",
    memory_config: {},
    max_context_turns: 5,
    use_conversation_history: true,
    bot_class: "BasicBot",
    permissions: {},
    language: "en",
    disclaimer: null,
    created_at: "2026-01-01 00:00:00",
    created_by: 1,
    updated_at: "2026-01-01 00:00:00",
    ...overrides,
  };
}

describe("AgentForm", () => {
  beforeEach(() => {
    router.beforeNavigate = null;
  });

  afterEach(() => {
    vi.restoreAllMocks();
    router.beforeNavigate = null;
  });

  it("create: PUT payload has storage=database and navigates to the returned slug", async () => {
    const put = vi.spyOn(apiClient, "put").mockResolvedValue({
      data: { message: "Created", name: "helpdesk-2" },
    });
    const navigateSpy = vi.spyOn(router, "navigate");

    const { getByTestId } = render(AgentForm, { mode: "create", catalog, tools });

    await fireEvent.input(getByTestId("field-name"), { target: { value: "Helpdesk 2" } });
    await fireEvent.click(getByTestId("form-footer-save"));

    await waitFor(() => expect(put).toHaveBeenCalled());
    const [url, body] = put.mock.calls[0];
    expect(url).toBe("/api/v1/bots");
    expect((body as Record<string, unknown>).storage).toBe("database");
    expect((body as Record<string, unknown>).name).toBe("Helpdesk 2");

    await waitFor(() =>
      expect(navigateSpy).toHaveBeenCalledWith("/admin/agents/helpdesk-2", { replace: true }),
    );
  });

  it("create: shows a notice when the returned name differs from what was typed", async () => {
    vi.spyOn(apiClient, "put").mockResolvedValue({
      data: { message: "Created", name: "helpdesk-2" },
    });
    vi.spyOn(router, "navigate");

    const { getByTestId, findByTestId } = render(AgentForm, {
      mode: "create",
      catalog,
      tools,
    });

    await fireEvent.input(getByTestId("field-name"), { target: { value: "Helpdesk 2!!" } });
    await fireEvent.click(getByTestId("form-footer-save"));

    expect((await findByTestId("rename-notice")).textContent).toContain("helpdesk-2");
  });

  it("edit: sends only the diff, never chatbot_id/created_*/name", async () => {
    const post = vi.spyOn(apiClient, "post").mockResolvedValue({
      data: { message: "Updated", name: "helpdesk" },
    });

    const { getByTestId } = render(AgentForm, {
      mode: "edit",
      agent: dbAgent(),
      catalog,
      tools,
    });

    await fireEvent.input(getByTestId("field-description"), {
      target: { value: "Updated description" },
    });
    await fireEvent.click(getByTestId("form-footer-save"));

    await waitFor(() => expect(post).toHaveBeenCalled());
    const [url, body] = post.mock.calls[0];
    expect(url).toBe("/api/v1/bots/helpdesk");
    expect(body).toEqual({ description: "Updated description" });
    expect(body).not.toHaveProperty("chatbot_id");
    expect(body).not.toHaveProperty("created_at");
    expect(body).not.toHaveProperty("created_by");
    expect(body).not.toHaveProperty("name");
  });

  it("shows a server 400 message and keeps the user's input", async () => {
    const { ApiError } = await import("$lib/api/http");
    vi.spyOn(apiClient, "post").mockRejectedValue(
      new ApiError("Duplicate agent name", "server", 400),
    );

    const { getByTestId, findByTestId } = render(AgentForm, {
      mode: "edit",
      agent: dbAgent(),
      catalog,
      tools,
    });

    await fireEvent.input(getByTestId("field-description"), {
      target: { value: "Kept on failure" },
    });
    await fireEvent.click(getByTestId("form-footer-save"));

    const serverError = await findByTestId("form-footer-server-error");
    expect(serverError.textContent).toContain("Duplicate agent name");
    expect((getByTestId("field-description") as HTMLInputElement).value).toBe(
      "Kept on failure",
    );
  });

  it("an empty goal marks the Behavior tab badge and disables Save", async () => {
    const { getByTestId, queryByTestId } = render(AgentForm, {
      mode: "edit",
      agent: dbAgent(),
      catalog,
      tools,
    });

    expect(queryByTestId("tab-badge-behavior")).toBeNull();
    expect((getByTestId("form-footer-save") as HTMLButtonElement).disabled).toBe(false);

    await fireEvent.click(getByTestId("tab-trigger-behavior"));
    await fireEvent.input(getByTestId("field-goal"), { target: { value: "" } });

    await waitFor(() => expect(getByTestId("tab-badge-behavior")).toBeTruthy());
    expect((getByTestId("form-footer-save") as HTMLButtonElement).disabled).toBe(true);
  });

  it("a dirty form asks before navigating away, via router.beforeNavigate", async () => {
    render(AgentForm, { mode: "edit", agent: dbAgent(), catalog, tools });

    // Not dirty yet -> the hook allows navigation synchronously.
    expect(router.beforeNavigate).toBeTypeOf("function");
    expect(router.beforeNavigate!("/admin/agents")).toBe(true);
  });

  it("dirty + beforeNavigate returns a pending promise resolved by the confirm dialog", async () => {
    const { getByTestId } = render(AgentForm, { mode: "edit", agent: dbAgent(), catalog, tools });

    await fireEvent.input(getByTestId("field-description"), { target: { value: "dirty now" } });

    const result = router.beforeNavigate!("/admin/agents");
    expect(result).not.toBe(true);
    expect(result).toBeInstanceOf(Promise);

    await waitFor(() => expect(getByTestId("unsaved-changes-dialog")).toBeTruthy());
    await fireEvent.click(getByTestId("unsaved-changes-discard"));

    await expect(result).resolves.toBe(true);
  });

  it("bypasses the guard for the login redirect even while dirty", async () => {
    const { getByTestId } = render(AgentForm, { mode: "edit", agent: dbAgent(), catalog, tools });

    await fireEvent.input(getByTestId("field-description"), { target: { value: "dirty now" } });

    expect(router.beforeNavigate!(`${config.loginPath}?next=%2Fadmin%2Fagents`)).toBe(true);
  });
});
