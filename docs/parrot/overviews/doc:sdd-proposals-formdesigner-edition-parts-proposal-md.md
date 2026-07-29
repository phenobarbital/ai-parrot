---
type: Wiki Overview
title: FEAT-169 — FormDesigner Edit via Tool-Based Toolkit
id: doc:sdd-proposals-formdesigner-edition-parts-proposal-md
tags:
- overview
timestamp: '2026-07-16T08:34:12+00:00'
summary: The `POST /api/v1/forms/{form_id}/edit` endpoint currently serializes the
---

---
id: FEAT-169
title: "FormDesigner Edit via Tool-Based Toolkit Instead of Full-Form Regeneration"
type: feature
mode: investigation
status: discussion
base_branch: dev
source:
  kind: inline
  summary_oneline: "Edit endpoint sends 230K-char full form to LLM; replace with tool-calling toolkit for surgical edits"
confidence: high
research_state: sdd/state/FEAT-169/
---

# FEAT-169 — FormDesigner Edit via Tool-Based Toolkit

## 0. Origin

The `POST /api/v1/forms/{form_id}/edit` endpoint currently serializes the
**entire** `FormSchema` as JSON and sends it to the LLM alongside the user's
edit prompt.  For large forms (100+ fields), this produces prompts of 230K+
characters, causing:

- **~3 minute latency** (161s observed for `gemini-2.5-flash` on a real form)
- **Full-form regeneration risk** — the LLM must reproduce every field verbatim,
  creating opportunities for subtle data loss or reordering
- **Token waste** — the vast majority of the form is unchanged by a typical edit
- **Retry amplification** — on validation failure, the entire conversation
  (including the full form) is re-sent up to 2 more times

Observed in production logs:
```
prompt_chars=230466  system_prompt_chars=4497  tools=0
generate_content_ms=161748.9  model=gemini-2.5-flash
```

## 1. Synthesis Summary

The root cause is architectural: `CreateFormTool._build_refinement_messages()`
(line 354 of `create_form.py`) calls `existing.model_dump_json(indent=2)` and
embeds the **complete** JSON into the prompt.  The LLM is then instructed via
`_REFINEMENT_PROMPT` (line 98) to return a "COMPLETE, valid FormSchema JSON —
not a partial diff."

Meanwhile, the codebase already has a mature **granular operations system**
(`api/operations.py`) with 8 atomic edit operations (`AddField`, `MoveField`,
`RemoveField`, `UpdateField`, `UpdateSectionMeta`, `UpdateFormMeta`,
`DuplicateField`, `AddSection`).  And `GoogleGenAIClient.ask()` already
supports `tools` and `use_tools` parameters for native function calling.

**The missing piece is a bridge** that exposes form inspection and granular
edit operations as LLM-callable tools, so the LLM can surgically locate and
modify specific elements without ever seeing the full form.

## 2. Codebase Findings

### 2.1 Localization

| File | Symbol / Lines | Role |
|------|---------------|------|
| `parrot_formdesigner/tools/create_form.py` | `_build_refinement_messages` (L354-372) | Serializes full form → prompt |
| `parrot_formdesigner/tools/create_form.py` | `_REFINEMENT_PROMPT` (L98-112) | Instructs LLM to return complete JSON |
| `parrot_formdesigner/tools/create_form.py` | `_call_llm` (L374-413) | Calls `client.ask()` with `stateless=True`, no tools |
| `parrot_formdesigner/api/handlers.py` | `edit_form` (L294-348) | HTTP handler, calls `_create_tool.execute(refine_form_id=...)` |
| `parrot_formdesigner/api/operations.py` | 8 op classes (L52-134) | Existing atomic edit operations |
| `parrot_formdesigner/api/operations.py` | `_DISPATCH` (L339-348) | Op name → apply function mapping |
| `parrot/clients/google/client.py` | `ask()` (L1724-1744) | Accepts `tools`, `use_tools` params |
| `parrot/clients/google/client.py` | `_build_tools` (L634) | Converts tool dicts → Google `types.Tool` |
| `parrot/clients/google/client.py` | `_handle_stateless_function_calls` (L728) | Executes tool calls in stateless mode |

### 2.2 Constraints

- `FormSchema` is the SSOT.  Any toolkit must produce valid `FormSchema`
  state after each operation.
- The `operations.py` apply functions are **pure** — they operate on a
  Pydantic deep copy and validate post-apply.  This is ideal for tool-call
  execution.
- `GoogleGenAIClient` already handles multi-turn tool calling with up to
  `max_iterations=15` rounds (L1742).
- The existing `edit_form` handler must remain backward-compatible (same
  HTTP contract: `POST {form_id}/edit` with `{"prompt": "..."}`, returns
  `{"form_id", "title", "url"}`).

### 2.3 Recent History

- FEAT-152 introduced the operations endpoint and the full renderer/validator
  pipeline.
- The `FormSubsection` model was just added, changing `FormSection.fields`
  to `list[FormField | FormSubsection]`.  The toolkit must use
  `section.iter_fields()` for field searches.

## 3. Proposed Architecture — Edit Toolkit

Replace the "send full form, get full form back" pattern with a **tool-calling
loop** where the LLM uses a small, focused toolkit:

### 3.1 Toolkit Tools

| Tool | Purpose | Sends to LLM |
|------|---------|-------------|
| `get_form_summary` | Returns form structure (section IDs, field IDs, labels) — no values, no options, no constraints | Compact outline (~2-5% of full JSON) |
| `get_section` | Returns full JSON for one section by `section_id` | One section only |
| `get_field` | Returns full JSON for one field by `field_id` (searches across sections/subsections) | One field only |
| `search_fields` | Search fields by label, field_type, or field_id pattern (regex/substring) | Matching field summaries |
| `update_field` | Apply RFC 7396 merge-patch to a single field | Nothing (confirmation) |
| `add_field` | Add a new field to a section at optional position | Nothing (confirmation) |
| `remove_field` | Remove a field from a section | Nothing (confirmation) |
| `add_section` | Add a new section at optional position | Nothing (confirmation) |
| `update_section` | Update section title/description/meta | Nothing (confirmation) |
| `move_field` | Move a field within or across sections | Nothing (confirmation) |
| `update_form_meta` | Update form-level title/description/meta | Nothing (confirmation) |
| `done` | Signal that all edits are complete | Nothing (final) |

### 3.2 Flow

```
User: "Change the phone field label to 'Mobile Number'"

1. LLM calls: get_form_summary()
   → Returns: {sections: [{id: "contact", title: "Contact", fields: ["name", "email", "phone", ...]}]}
   
2. LLM calls: get_field(field_id="phone")
   → Returns: {field_id: "phone", field_type: "phone", label: "Phone", ...}
   
3. LLM calls: update_field(section_id="contact", field_id="phone", patch={"label": "Mobile Number"})
   → Returns: {success: true}
   
4. LLM calls: done()
   → Loop ends, return updated FormSchema
```

**Token usage:** ~500 chars per round instead of 230K.  Even with 5 rounds,
total is ~2,500 chars — a **99% reduction**.

### 3.3 Implementation Location

Create a new module: `parrot_formdesigner/tools/edit_toolkit.py`

This toolkit:
1. Wraps the existing `operations.py` apply functions for mutations
2. Adds read-only inspection tools (`get_form_summary`, `get_section`,
   `get_field`, `search_fields`)
3. Exposes tools in the format expected by `GoogleGenAIClient._build_tools()`
   (list of dicts with `name`, `description`, `parameters`)
4. Manages a working copy of the `FormSchema` during the edit session

### 3.4 Integration with `CreateFormTool`

Add a new method `_execute_toolkit_edit()` alongside the existing
`_build_refinement_messages()` path.  The `_execute()` method selects the
toolkit path when `refine_form_id` is set and the form exceeds a size
threshold (e.g., >10 fields or >20K chars serialized).  Small forms can
still use the existing full-form approach for simplicity.

### 3.5 Fallback Strategy

If the LLM fails to use tools correctly (e.g., exhausts max iterations without
calling `done`), fall back to the existing full-form refinement path.  This
ensures no regression for edge cases.

## 4. Confidence Map

| Claim | Confidence | Evidence |
|-------|-----------|----------|
| Full form serialization is the root cause of latency | **high** | Logs show 230K prompt chars, 161s generation |
| Operations.py apply functions can be reused as tool backends | **high** | They're pure functions on deep copies, already validated |
| GoogleGenAIClient supports multi-turn tool calling | **high** | `ask()` signature, `_handle_stateless_function_calls`, `max_iterations` |
| A summary tool can reduce prompt size by ~95% | **high** | Outline of section/field IDs is ~5K vs 230K full form |
| LLM (Gemini Flash) can reliably use 5-10 simple tools | **medium** | Google docs confirm tool-use, but complex multi-step may need tuning |
| Small forms should keep the full-form path | **medium** | Full-form is simpler and fast enough for <10 fields |

## 5. Open Questions

- **Q1:** Should the toolkit support batch operations (multiple `update_field`
  calls in a single tool invocation) or strictly one-at-a-time?  One-at-a-time
  is simpler but may add rounds for bulk edits.

- **Q2:** Should `get_form_summary` include field descriptions/constraints in
  the summary, or keep it truly minimal (ID + label + type only)?

## 6. Recommended Next Step

```
/sdd-spec FEAT-169
```

The localization is strong, the existing operations infrastructure covers most
mutation needs, and the GoogleGenAIClient tool-calling support is confirmed.
A spec can directly decompose this into tasks.

## 7. Research Audit

- **Files read:** `create_form.py`, `handlers.py`, `operations.py`,
  `schema.py`, `google/client.py`, `field_helpers.py`, `database_form.py`,
  `request_form.py`
- **Greps:** `use_tools`, `tool_type`, `function_call`, `_build_tools`,
  `ask()` signature, `_handle_stateless_function_calls`
- **Key finding:** The entire tool-calling infrastructure exists in the
  Google client but is never wired up by `CreateFormTool`
