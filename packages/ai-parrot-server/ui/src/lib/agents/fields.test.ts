import { describe, expect, it } from "vitest";

import type { BotWritePayload } from "$lib/types/generated/BotWritePayload";

import { defaults, FIELD_TAB, IMMUTABLE_FIELDS, JSON_FIELDS, REQUIRED_FIELDS, validate } from "./fields";

describe("defaults()", () => {
  const d = defaults();

  it("matches the BotModel field defaults", () => {
    expect(d.enabled).toBe(true);
    expect(d.timezone).toBe("UTC");
    expect(d.language).toBe("en");
    expect(d.role).toBe("AI Assistant");
    expect(d.goal).toBe("Help users accomplish their tasks effectively.");
    expect(d.backstory).toBe(
      "I am an AI assistant created to help users with various tasks.",
    );
    expect(d.rationale).toBe(
      "I maintain a professional tone and provide accurate, helpful information.",
    );
    expect(d.capabilities).toBe(
      "I can engage in conversation, answer questions, and use tools when needed.",
    );
    expect(d.llm).toBe("google");
    expect(d.tools_enabled).toBe(true);
    expect(d.auto_tool_detection).toBe(true);
    expect(d.tool_threshold).toBe(0.7);
    expect(d.operation_mode).toBe("adaptive");
    expect(d.use_kb).toBe(false);
    expect(d.use_vector).toBe(false);
    expect(d.context_search_limit).toBe(10);
    expect(d.context_score_threshold).toBe(0.7);
    expect(d.memory_type).toBe("memory");
    expect(d.max_context_turns).toBe(5);
    expect(d.use_conversation_history).toBe(true);
    expect(d.bot_class).toBe("BasicBot");
  });

  it("uses {} for dict fields and [] for list fields per BotModel", () => {
    expect(d.prompt_config).toEqual({});
    expect(d.model_config).toEqual({});
    expect(d.vector_store_config).toEqual({});
    expect(d.reranker_config).toEqual({});
    expect(d.parent_searcher_config).toEqual({});
    expect(d.memory_config).toEqual({});
    expect(d.permissions).toEqual({});
    expect(d.pre_instructions).toEqual([]);
    expect(d.tools).toEqual([]);
    expect(d.kb).toEqual([]);
  });

  it("custom_kbs defaults to null (BotModel: Field(nullable=True, default=None), not [])", () => {
    expect(d.custom_kbs).toBeNull();
  });
});

describe("FIELD_TAB coverage", () => {
  it("has an entry for every BotWritePayload key", () => {
    // Fixture exercising every documented key (mirrors the generated
    // type's field set) so a key added to BotWritePayload without a
    // matching FIELD_TAB entry fails this test, not just `tsc`.
    const fixture: Required<BotWritePayload> = {
      storage: "database",
      name: null,
      description: null,
      avatar: null,
      enabled: null,
      timezone: null,
      language: null,
      disclaimer: null,
      role: null,
      goal: null,
      backstory: null,
      rationale: null,
      capabilities: null,
      system_prompt_template: null,
      human_prompt_template: null,
      pre_instructions: null,
      prompt_config: null,
      llm: null,
      model_config: null,
      tools_enabled: null,
      auto_tool_detection: null,
      tool_threshold: null,
      tools: null,
      operation_mode: null,
      use_kb: null,
      kb: null,
      custom_kbs: null,
      use_vector: null,
      vector_store_config: null,
      reranker_config: null,
      parent_searcher_config: null,
      context_search_limit: null,
      context_score_threshold: null,
      memory_type: null,
      memory_config: null,
      max_context_turns: null,
      use_conversation_history: null,
      bot_class: null,
      permissions: null,
    };

    for (const key of Object.keys(fixture) as (keyof BotWritePayload)[]) {
      expect(FIELD_TAB[key], `missing FIELD_TAB entry for "${key}"`).toBeDefined();
    }
  });

  it("every FIELD_TAB value is one of the six known tabs", () => {
    const knownTabs = new Set([
      "general",
      "behavior",
      "ai",
      "capabilities",
      "data_memory",
      "advanced",
    ]);
    for (const tab of Object.values(FIELD_TAB)) {
      expect(knownTabs.has(tab)).toBe(true);
    }
  });
});

describe("validate()", () => {
  function valid(): BotWritePayload {
    return defaults();
  }

  it("passes on the defaults (with required fields filled)", () => {
    const values = { ...valid(), name: "helpdesk" };
    expect(validate(values)).toEqual({});
  });

  for (const field of REQUIRED_FIELDS) {
    it(`flags an empty "${field}" as required, on its owning tab`, () => {
      const values = { ...valid(), name: "helpdesk", [field]: "" };
      const errors = validate(values);
      expect(errors[field]).toBeDefined();
      expect(FIELD_TAB[field as keyof BotWritePayload]).toBeDefined();
    });
  }

  it("rejects tool_threshold outside [0, 1]", () => {
    expect(validate({ ...valid(), name: "x", tool_threshold: 1.5 }).tool_threshold).toBeDefined();
    expect(validate({ ...valid(), name: "x", tool_threshold: -0.1 }).tool_threshold).toBeDefined();
    expect(validate({ ...valid(), name: "x", tool_threshold: 0 }).tool_threshold).toBeUndefined();
    expect(validate({ ...valid(), name: "x", tool_threshold: 1 }).tool_threshold).toBeUndefined();
  });

  it("rejects context_score_threshold outside [0, 1]", () => {
    const errors = validate({ ...valid(), name: "x", context_score_threshold: 2 });
    expect(errors.context_score_threshold).toBeDefined();
  });

  it("rejects a negative context_search_limit / max_context_turns", () => {
    const errors = validate({
      ...valid(),
      name: "x",
      context_search_limit: -1,
      max_context_turns: -5,
    });
    expect(errors.context_search_limit).toBeDefined();
    expect(errors.max_context_turns).toBeDefined();
  });

  it("rejects an invalid operation_mode / memory_type", () => {
    const errors = validate({
      ...valid(),
      name: "x",
      // @ts-expect-error -- deliberately invalid for the test
      operation_mode: "bogus",
      // @ts-expect-error -- deliberately invalid for the test
      memory_type: "bogus",
    });
    expect(errors.operation_mode).toBeDefined();
    expect(errors.memory_type).toBeDefined();
  });

  it("tolerates a provider alias in llm not present in any catalog", () => {
    // llm has no enum validation client-side (§7: catalog aliases) —
    // any non-empty string must pass.
    const errors = validate({ ...valid(), name: "x", llm: "claude-agent" });
    expect(errors.llm).toBeUndefined();
  });

  for (const field of JSON_FIELDS) {
    if (field === "permissions") continue; // dual shape, tested separately
    it(`rejects a non-object "${field}"`, () => {
      const errors = validate({ ...valid(), name: "x", [field]: [1, 2, 3] });
      expect(errors[field]).toBeDefined();
    });

    it(`accepts a plain object "${field}"`, () => {
      const errors = validate({ ...valid(), name: "x", [field]: { a: 1 } });
      expect(errors[field]).toBeUndefined();
    });
  }

  it("model_config rejects a negative temperature / non-integer max_tokens", () => {
    const errors = validate({
      ...valid(),
      name: "x",
      model_config: { temperature: -1 },
    });
    expect(errors.model_config).toBeDefined();

    const errors2 = validate({
      ...valid(),
      name: "x",
      model_config: { max_tokens: 1.5 },
    });
    expect(errors2.model_config).toBeDefined();
  });

  it("permissions accepts both a dict and a list of rule dicts", () => {
    expect(
      validate({ ...valid(), name: "x", permissions: { admin: true } }).permissions,
    ).toBeUndefined();
    expect(
      validate({ ...valid(), name: "x", permissions: [{ role: "admin" }] }).permissions,
    ).toBeUndefined();
    expect(
      validate({ ...valid(), name: "x", permissions: ["not-a-dict"] as never }).permissions,
    ).toBeDefined();
  });

  it("does not validate IMMUTABLE_FIELDS (not part of BotWritePayload / not user-editable)", () => {
    for (const field of IMMUTABLE_FIELDS) {
      expect(field in defaults()).toBe(false);
    }
  });
});
