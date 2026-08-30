/**
 * AgentFormState (TASK-2586, FEAT-475) — the centralized rune-class store
 * backing the agent create/edit form (spec §2 Data Models, §2 Overview).
 * Headless: owns the full `BotWritePayload` draft plus dirty tracking,
 * per-field validation, and per-tab error aggregation; the six tab panels
 * (TASK-2587) render slices of `values` and read `errors`/`tabErrors`.
 *
 * `diff()` never includes `name` in edit mode (§8 Q3 — renaming an
 * existing agent is out of scope for v1; `name` is read-only in the edit
 * form) nor any `IMMUTABLE_FIELDS` (server-assigned, never part of
 * `BotWritePayload` to begin with).
 */
import type { BotAgentItem } from "$lib/types/generated/BotAgentItem";
import type { BotWritePayload } from "$lib/types/generated/BotWritePayload";

import { defaults, FIELD_TAB, IMMUTABLE_FIELDS, type TabId, validate as validateFields } from "$lib/agents/fields";

export type AgentFormMode = "create" | "edit";

/** `BotWritePayload` keys backed by a JSON object (coerced from `null` on load). */
const DICT_FIELDS = [
  "prompt_config",
  "model_config",
  "vector_store_config",
  "reranker_config",
  "parent_searcher_config",
  "memory_config",
] as const;

/** `BotWritePayload` keys backed by a list (coerced from `null` on load). */
const LIST_FIELDS = ["pre_instructions", "tools", "kb", "custom_kbs"] as const;

/** Server-assigned metadata surfaced read-only in edit mode (never in `values`/`BotWritePayload`). */
export interface AgentFormMeta {
  chatbot_id?: string;
  created_at?: string;
  created_by?: number | string | null;
  updated_at?: string;
}

/** Deterministic string form of a value for structural-equality comparisons. */
function stableStringify(value: unknown): string {
  if (Array.isArray(value)) {
    return `[${value.map(stableStringify).join(",")}]`;
  }
  if (value !== null && typeof value === "object") {
    const keys = Object.keys(value as Record<string, unknown>).sort();
    return `{${keys
      .map((k) => `${JSON.stringify(k)}:${stableStringify((value as Record<string, unknown>)[k])}`)
      .join(",")}}`;
  }
  return JSON.stringify(value);
}

function deepEqual(a: unknown, b: unknown): boolean {
  return stableStringify(a) === stableStringify(b);
}

/** Coerce `null` dict/list-typed fields to `{}`/`[]` (tolerates a raw API payload). */
function coerceShapes(values: BotWritePayload): BotWritePayload {
  const next: BotWritePayload = { ...values };
  for (const key of DICT_FIELDS) {
    if (next[key] === null || next[key] === undefined) {
      (next as Record<string, unknown>)[key] = {};
    }
  }
  for (const key of LIST_FIELDS) {
    if (next[key] === null || next[key] === undefined) {
      (next as Record<string, unknown>)[key] = [];
    }
  }
  return next;
}

const META_KEYS = ["chatbot_id", "created_at", "created_by", "updated_at"] as const;

export class AgentFormState {
  mode: AgentFormMode = $state("create");
  /** Snapshot loaded for edit (post-coercion); `null` in create mode. */
  original: BotWritePayload | null = $state(null);
  values = $state<BotWritePayload>(defaults());
  errors = $state<Record<string, string>>({});
  serverError: string | null = $state(null);
  saving = $state(false);
  /** `chatbot_id`/`created_at`/`created_by`/`updated_at` — display-only. */
  meta: AgentFormMeta = $state({});

  /** True when `values` differs from the loaded/blank baseline. */
  readonly dirty = $derived(!deepEqual(this.values, this.original ?? defaults()));

  /** Count of `errors` entries per tab, for the per-tab red-indicator badge. */
  readonly tabErrors = $derived.by((): Partial<Record<TabId, number>> => {
    const counts: Partial<Record<TabId, number>> = {};
    for (const field of Object.keys(this.errors)) {
      const tab = FIELD_TAB[field as keyof BotWritePayload];
      if (!tab) continue;
      counts[tab] = (counts[tab] ?? 0) + 1;
    }
    return counts;
  });

  /**
   * Load a `GET /api/v1/bots/{name}` response (a `BotAgentItem`) into this
   * state for edit mode. Tolerates extra fields (`BotAgentItem`'s
   * `extra="allow"` shape) and coerces `null` dict/list fields to `{}`/`[]`.
   */
  load(agent: BotAgentItem): void {
    this.mode = "edit";
    const raw = agent as unknown as Record<string, unknown>;

    const meta: AgentFormMeta = {};
    for (const key of META_KEYS) {
      if (raw[key] !== undefined && raw[key] !== null) {
        (meta as Record<string, unknown>)[key] = raw[key];
      }
    }
    this.meta = meta;

    const draft: Record<string, unknown> = { ...defaults() };
    for (const [key, value] of Object.entries(raw)) {
      if (key === "source") continue;
      if ((META_KEYS as readonly string[]).includes(key)) continue;
      if (!(key in (draft as object)) && key !== "name") {
        // Unknown extra field (registry-shape leakage, future BotModel
        // columns, etc.) — BotWritePayload doesn't declare it; drop it
        // rather than pass through an untyped key.
        continue;
      }
      draft[key] = value;
    }

    const coerced = coerceShapes(draft as BotWritePayload);
    this.values = coerced;
    this.original = { ...coerced };
    this.errors = {};
    this.serverError = null;
  }

  /** Validate `values`; fills `errors` and returns whether the form is valid. */
  validate(): boolean {
    this.errors = validateFields(this.values, this.mode);
    return Object.keys(this.errors).length === 0;
  }

  /**
   * Changed fields only, relative to `original` (or `defaults()` when
   * there is none) — the body `updateAgent()` sends. Never includes an
   * `IMMUTABLE_FIELDS` key (not part of `BotWritePayload` to begin with),
   * `storage` (create-only), or `name` in edit mode (§8 Q3 — renaming is
   * out of scope; `name` is read-only in the edit form).
   */
  diff(): Partial<BotWritePayload> {
    const base = this.original ?? defaults();
    const out: Partial<BotWritePayload> = {};
    for (const key of Object.keys(this.values) as (keyof BotWritePayload)[]) {
      if ((IMMUTABLE_FIELDS as readonly string[]).includes(key)) continue;
      if (key === "storage") continue;
      if (this.mode === "edit" && key === "name") continue;
      if (!deepEqual(this.values[key], base[key])) {
        (out as Record<string, unknown>)[key] = this.values[key];
      }
    }
    return out;
  }

  /** Full payload for `createAgent()` — `values` plus `storage: "database"`. */
  payload(): BotWritePayload {
    return { ...this.values, storage: "database" };
  }
}
