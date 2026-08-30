import { describe, expect, it } from "vitest";

import type { BotAgentItem } from "$lib/types/generated/BotAgentItem";

import { AgentFormState } from "./agent-form.svelte";

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
    tools: ["search_kb"],
    operation_mode: "adaptive",
    use_kb: true,
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

describe("AgentFormState", () => {
  it("starts in create mode with BotModel defaults and not dirty", () => {
    const form = new AgentFormState();
    expect(form.mode).toBe("create");
    expect(form.values.enabled).toBe(true);
    expect(form.values.llm).toBe("google");
    expect(form.dirty).toBe(false);
  });

  describe("load()", () => {
    it("switches to edit mode and populates values/meta", () => {
      const form = new AgentFormState();
      form.load(dbAgent());

      expect(form.mode).toBe("edit");
      expect(form.values.name).toBe("helpdesk");
      expect(form.values.goal).toBe("Resolve tickets quickly.");
      expect(form.meta.chatbot_id).toBe("11111111-1111-1111-1111-111111111111");
      expect(form.meta.created_at).toBe("2026-01-01 00:00:00");
    });

    it("drops `source` from values (it is not a BotWritePayload field)", () => {
      const form = new AgentFormState();
      form.load(dbAgent());
      expect((form.values as Record<string, unknown>).source).toBeUndefined();
    });

    it("coerces null dict/list fields to {} / []", () => {
      const form = new AgentFormState();
      form.load(dbAgent({ custom_kbs: null, kb: null as never, prompt_config: null as never }));

      expect(form.values.custom_kbs).toEqual([]);
      expect(form.values.kb).toEqual([]);
      expect(form.values.prompt_config).toEqual({});
    });

    it("tolerates extra fields not in BotWritePayload (registry-shape leakage)", () => {
      const form = new AgentFormState();
      expect(() =>
        form.load(dbAgent({ module_path: "plugins.x" } as never)),
      ).not.toThrow();
    });

    it("is not dirty immediately after load", () => {
      const form = new AgentFormState();
      form.load(dbAgent());
      expect(form.dirty).toBe(false);
    });
  });

  describe("dirty", () => {
    it("becomes true after an edit and false again after reverting", () => {
      const form = new AgentFormState();
      form.load(dbAgent());
      expect(form.dirty).toBe(false);

      form.values.goal = "A different goal.";
      expect(form.dirty).toBe(true);

      form.values.goal = "Resolve tickets quickly.";
      expect(form.dirty).toBe(false);
    });
  });

  describe("validate()", () => {
    it("fills errors and returns false for a missing required field", () => {
      const form = new AgentFormState();
      form.load(dbAgent({ goal: "" }));

      const valid = form.validate();

      expect(valid).toBe(false);
      expect(form.errors.goal).toBeDefined();
    });

    it("returns true and clears errors for a valid form", () => {
      const form = new AgentFormState();
      form.load(dbAgent());

      expect(form.validate()).toBe(true);
      expect(form.errors).toEqual({});
    });

    it("blocks Save when a JSON field's editor holds malformed JSON, even though values[field] itself is still the last-known-good object", () => {
      // Regression: JsonEditor only writes its bound `value` when the
      // textarea content is valid JSON — a field being actively edited
      // to something malformed never changes `state.values[field]`.
      // Without `setJsonValid()` feeding into `validate()`, the form
      // would report itself valid (and Save would silently submit the
      // stale last-good value) while the JsonEditor's own UI is still
      // showing an inline parse error — contradicting the spec's
      // "malformed JSON blocks submission" requirement.
      const form = new AgentFormState();
      form.load(dbAgent());
      expect(form.validate()).toBe(true);

      form.setJsonValid("permissions", false);

      expect(form.validate()).toBe(false);
      expect(form.errors.permissions).toBeDefined();
    });

    it("setJsonValid(field, true) clears the block once the JSON becomes valid again", () => {
      const form = new AgentFormState();
      form.load(dbAgent());

      form.setJsonValid("model_config", false);
      expect(form.validate()).toBe(false);

      form.setJsonValid("model_config", true);
      expect(form.validate()).toBe(true);
      expect(form.errors.model_config).toBeUndefined();
    });

    it("load() resets invalidJsonFields so a stale flag never leaks across agents", () => {
      const form = new AgentFormState();
      form.load(dbAgent());
      form.setJsonValid("permissions", false);
      expect(form.validate()).toBe(false);

      form.load(dbAgent({ name: "another-bot" }));

      expect(form.validate()).toBe(true);
    });
  });

  describe("tabErrors", () => {
    it("aggregates error counts by owning tab", () => {
      const form = new AgentFormState();
      form.load(dbAgent({ goal: "", tool_threshold: 5 }));
      form.validate();

      // goal -> behavior, tool_threshold -> capabilities
      expect(form.tabErrors.behavior).toBe(1);
      expect(form.tabErrors.capabilities).toBe(1);
      expect(form.tabErrors.general).toBeUndefined();
    });
  });

  describe("diff()", () => {
    it("excludes unchanged fields", () => {
      const form = new AgentFormState();
      form.load(dbAgent());

      expect(form.diff()).toEqual({});
    });

    it("includes only changed fields", () => {
      const form = new AgentFormState();
      form.load(dbAgent());

      form.values.enabled = false;
      form.values.tool_threshold = 0.9;

      expect(form.diff()).toEqual({ enabled: false, tool_threshold: 0.9 });
    });

    it("never includes name in edit mode, even when changed", () => {
      const form = new AgentFormState();
      form.load(dbAgent());

      form.values.name = "renamed-bot";

      expect(form.diff().name).toBeUndefined();
    });

    it("never includes storage (create-only field)", () => {
      const form = new AgentFormState();
      form.load(dbAgent());
      // storage isn't in a loaded BotAgentItem's values at all, but guard
      // the invariant explicitly even if something sets it.
      (form.values as Record<string, unknown>).storage = "database";

      expect(form.diff().storage).toBeUndefined();
    });

    it("never includes immutable fields (they are not part of values)", () => {
      const form = new AgentFormState();
      form.load(dbAgent());
      const diff = form.diff();

      expect(diff).not.toHaveProperty("chatbot_id");
      expect(diff).not.toHaveProperty("created_at");
      expect(diff).not.toHaveProperty("created_by");
    });
  });

  describe("payload()", () => {
    it("adds storage: 'database' to the full values for create", () => {
      const form = new AgentFormState();
      form.values.name = "new-bot";
      form.values.goal = "Do things.";
      form.values.backstory = "Backstory.";
      form.values.rationale = "Rationale.";

      const payload = form.payload();

      expect(payload.storage).toBe("database");
      expect(payload.name).toBe("new-bot");
      expect(payload.llm).toBe("google"); // full payload, not a diff
    });
  });
});
