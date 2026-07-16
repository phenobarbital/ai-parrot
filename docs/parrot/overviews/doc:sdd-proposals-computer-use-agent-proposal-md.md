---
type: Wiki Overview
title: FEAT-227 — Computer-Use Agent
id: doc:sdd-proposals-computer-use-agent-proposal-md
tags:
- overview
timestamp: '2026-07-16T08:34:12+00:00'
summary: 'The original request, preserved verbatim:'
---

---
id: FEAT-227
title: Computer-Use Agent — ComputerInteraction toolkit + ComputerAgent for Playwright browser automation with Gemini
slug: computer-use-agent
type: feature
mode: enrichment
status: review
source:
  kind: inline
  jira_key: null
  jira_url: null
  fetched_at: 2026-06-05
  summary_oneline: ComputerInteraction toolkit + ComputerAgent for vision-based browser automation using Gemini computer-use models
overall_confidence: high
base_branch: dev
research_state: sdd/state/FEAT-227/
created: 2026-06-05
updated: 2026-06-05
---

# FEAT-227 — Computer-Use Agent

> **Mode**: enrichment
> **Confidence**: high
> **Source**: `inline` — user-provided feature brief
> **Audit**: [`sdd/state/FEAT-227/`](../state/FEAT-227/)

---

## 0. Origin

The original request, preserved verbatim:

> This is a combination of a Toolkit (ComputerInteraction) and an Agent (ComputerAgent)
> for using browser automation with gemini-2.5-computer-use-preview-10-2025 or
> gemini-3.1-pro-preview-customtools. The usage of this Agent is for doing multi-tasks
> using Playwright.
>
> Tasks:
> - Toolkit for ComputerInteraction combining with WebscrapingToolkit for browser
>   interaction and browser extraction.
> - ComputerAgent: Agent for using those toolkits for interaction and scraping
>   information for pages.

**Initial signals** (extracted, not interpreted):
- Verbs: "using", "combining", "interaction", "scraping" → feature enrichment
- Named entities: ComputerInteraction, ComputerAgent, WebscrapingToolkit, Playwright, Gemini
- Reference: https://github.com/google-gemini/computer-use-preview
- Model: gemini-2.5-computer-use-preview-10-2025, gemini-3-flash-preview
- Acceptance criteria provided: no (implicit from tasks list)

---

## 1. Synthesis Summary

The request is to add **vision-based browser automation** to AI-Parrot via Google's
Gemini computer-use models. Unlike the existing WebScrapingToolkit (which uses CSS selectors
and XPath for element targeting), the computer-use approach is **coordinate-based**: the
model sees a screenshot, decides where to click/type/scroll, and receives the next screenshot.
The implementation requires three new components — a `ComputerInteractionToolkit`
(AbstractToolkit wrapping the 13 predefined computer-use actions), a `ComputerAgent`
(Agent subclass configured for computer-use models), and an async `ComputerBackend`
(bridging the computer-use action interface to AI-Parrot's existing async PlaywrightDriver).
The Google client (`GoogleGenAIClient`) must be extended to emit `types.Tool(computer_use=...)`
and handle `FunctionResponseBlob` (screenshot bytes) in function responses.

---

## 2. Codebase Findings

> All entries in this section are grounded in the research findings persisted
> at `sdd/state/FEAT-227/findings/`. Each cites the finding ID(s) that justify
> its inclusion. **No fabricated paths or symbols.**

### 2.1 Localization

The code areas relevant to this request:

| # | Path | Symbol | Lines | Role | Evidence |
|---|------|--------|-------|------|----------|
| 1 | `packages/ai-parrot-tools/.../scraping/drivers/playwright_driver.py` | `PlaywrightDriver` | 1-395 | Existing async Playwright driver — reusable browser backend | F002 |
| 2 | `packages/ai-parrot-tools/.../scraping/drivers/abstract.py` | `AbstractDriver` | 11-352 | Abstract browser interface with screenshot/click/navigate | F002 |
| 3 | `packages/ai-parrot/src/parrot/clients/google/client.py` | `GoogleGenAIClient._build_tools()` | 959-1037 | Tool builder — must extend for ComputerUse type | F004 |
| 4 | `packages/ai-parrot/src/parrot/models/google.py` | `GoogleModel` | 9-37 | Model enum — needs computer-use entries | F004 |
| 5 | `packages/ai-parrot/src/parrot/tools/toolkit.py` | `AbstractToolkit` | 191-544 | Base class for ComputerInteractionToolkit | F003, F005 |
| 6 | `packages/ai-parrot/src/parrot/bots/agent.py` | `BasicAgent` | 37-264 | Base class for ComputerAgent | F003 |
| 7 | `packages/ai-parrot-tools/.../scraping/toolkit.py` | `WebScrapingToolkit` | 274-942 | Composable selector-based scraping toolkit | F002 |

### 2.2 Constraints Discovered

- **GoogleGenAIClient only handles FunctionDeclaration tools.** The `_build_tools()` method
  creates `types.Tool(function_declarations=[...])` but has no path for `types.ComputerUse`.
  *Implication*: Must extend without breaking existing tools.
  *Evidence*: F004

- **Computer-use actions use predefined FunctionCalls, not FunctionDeclarations.** The 13
  actions (click_at, navigate, etc.) are implicit from the ComputerUse tool type — they
  are NOT declared in the tools list.
  *Implication*: The tool dispatch in GoogleGenAIClient must recognize and route these
  predefined function names to the ComputerInteraction backend.
  *Evidence*: F001, F006

- **Screenshots return as FunctionResponseBlob.** Each action response includes PNG bytes
  inline via `FunctionResponseBlob(mime_type="image/png", data=screenshot_bytes)`.
  *Implication*: GoogleGenAIClient's function response construction must support binary blobs.
  *Evidence*: F001, F006

- **Reference implementation is sync; AI-Parrot is async-first.** The google-gemini
  reference repo uses `playwright.sync_api`. AI-Parrot's existing PlaywrightDriver
  uses `playwright.async_api`.
  *Implication*: ComputerBackend must be a new async implementation, not a port of the
  reference's sync PlaywrightComputer.
  *Evidence*: F001, F002

- **Thinking mode is required.** Computer-use models need
  `ThinkingConfig(include_thoughts=True)`.
  *Implication*: Must auto-enable for computer-use models.
  *Evidence*: F001, F006

- **Coordinate normalization.** The model outputs coordinates in 0-1000 range; they must
  be denormalized to the actual viewport size before dispatching to Playwright.
  *Implication*: ComputerInteractionToolkit handles the math.
  *Evidence*: F001

### 2.3 Recent History (Relevant)

No existing commits touch computer-use functionality. The relevant infrastructure
(WebScrapingToolkit, PlaywrightDriver, GoogleGenAIClient) has been stable. The
Google client was recently enhanced with combined tools+schema support (FEAT-193)
and prompt caching (FEAT-181).

---

## 3. Probable Scope

### What's New

- **`ComputerInteractionToolkit`** — AbstractToolkit subclass with `tool_prefix="computer"`.
  Exposes the 13 predefined computer-use actions as async methods: `click_at`, `hover_at`,
  `type_text_at`, `scroll_document`, `scroll_at`, `wait`, `go_back`, `go_forward`,
  `search`, `navigate`, `key_combination`, `drag_and_drop`, `open_browser`. Each method
  accepts normalized coordinates (0-1000), denormalizes to viewport, dispatches to the
  async Playwright backend, and returns an `EnvState` (screenshot bytes + current URL).

  Additionally exposes **screenshot and recording capabilities** as toolkit methods:
  - `screenshot(full_page: bool = False) -> bytes` — capture current viewport or full page as PNG
  - `screenshot_element(selector: str) -> bytes` — capture a specific element
  - `start_recording(output_dir: str) -> None` — begin video recording of the browser session
    (via Playwright's `record_video_dir` context option)
  - `stop_recording() -> str` — stop recording, return the video file path
  - `start_tracing(screenshots: bool = True) -> None` — begin Playwright trace recording
    (DevTools trace format with optional screenshot snapshots)
  - `stop_tracing(output_path: str) -> str` — stop trace, save to file, return path
  - `record_har(output_path: str) -> None` — start HAR network log recording
  - `save_pdf(output_path: str) -> str` — export current page to PDF (Chromium only)

  These build on PlaywrightDriver's existing `screenshot()`, `start_tracing()`,
  `stop_tracing()`, `record_har()`, and `save_pdf()` capabilities (F002). They are
  exposed as regular toolkit tools so the agent (or the user) can invoke them alongside
  the computer-use actions.

  Finally, exposes **loop and flow execution** capabilities for repetitive multi-step
  navigation patterns (pagination, batch form fills, list processing):
  - `define_task(name: str, description: str, steps: list[str]) -> ComputerTask` —
    define a named, reusable sequence of natural-language instructions that the agent
    executes as a unit. Steps are high-level ("click the Next button", "extract the
    table data") — the model resolves them to coordinate actions at runtime.
  - `run_task(task: str, params: dict | None = None) -> TaskResult` — execute a
    previously defined task once, optionally injecting parameters (e.g., form values).
  - `run_loop(task: str, iterations: int | None = None, until: str | None = None, params_list: list[dict] | None = None, max_iterations: int = 100, collect_results: bool = True) -> LoopResult` —
    execute a task repeatedly. Supports three modes:
    - **Count-based**: `iterations=N` — repeat exactly N times.
    - **Condition-based**: `until="<natural-language condition>"` — repeat until the
      model determines the condition is met (e.g., `"no more pages"`, `"the Submit
      button is disabled"`, `"the URL stops changing"`). The model evaluates the
      condition against the screenshot after each iteration.
    - **Data-driven**: `params_list=[{...}, {...}, ...]` — iterate over a list of
      parameter dicts, executing the task once per entry (e.g., fill a form with
      each row from a dataset).
    `max_iterations` is a safety cap for condition-based loops.
    Returns `LoopResult` with per-iteration results, total iterations, stop reason.
  - `abort_loop() -> None` — cancel a running loop from outside (e.g., safety trigger).

  **`ComputerTask` model** (Pydantic):
  ```
  ComputerTask(name, description, steps: list[str], params_schema: dict | None)
  ```
  Tasks are lightweight — they describe *what* to do in natural language, not *how*
  (no hardcoded coordinates or selectors). The computer-use model resolves each step
  to concrete actions using the current screenshot. This makes tasks resilient to
  layout changes across iterations.

  **`LoopResult` model** (Pydantic):
  ```
  LoopResult(task_name, iterations_completed, stop_reason: "count"|"condition_met"|"max_reached"|"aborted"|"error",
             results: list[TaskResult], errors: list[str])
  ```

- **`ComputerAgent`** — Agent subclass registered as `"computer_agent"`. Configured with
  a computer-use model (default: `gemini-2.5-computer-use-preview-10-2025`). Composes
  `ComputerInteractionToolkit` + optionally `WebScrapingToolkit` for hybrid
  vision+selector workflows. Implements screenshot memory management (keep last N turns).
  Includes safety decision handling (configurable: auto-acknowledge or interactive).

  The agent natively supports **looped workflows** via `define_task` / `run_loop`.
  Example use cases:
  - **Pagination**: `run_loop(task="scrape_page", until="no more Next button")`
  - **Batch form fill**: `run_loop(task="fill_form", params_list=[{"name": "Alice"}, {"name": "Bob"}, ...])`
  - **Multi-page extraction**: `run_loop(task="extract_and_next", iterations=10, collect_results=True)`
  - **Monitoring**: `run_loop(task="check_dashboard", until="alert banner appears", max_iterations=50)`

  The loop controller lives inside ComputerAgent (not the toolkit) because it needs
  to manage the agent's conversation history and screenshot pruning across iterations.
  Between iterations the agent resets its tool-call chain but preserves the accumulated
  `LoopResult` and any extracted data.

- **`AsyncComputerBackend`** — Async implementation of the Computer abstract interface.
  Wraps AI-Parrot's existing PlaywrightDriver (async_api) with the computer-use action
  interface (click_at, type_text_at, etc. returning `EnvState`). Handles browser lifecycle
  (start, context creation, page management, cleanup).

- **`GoogleModel` entries** — `GEMINI_COMPUTER_USE = "gemini-2.5-computer-use-preview-10-2025"`
  and `GEMINI_3_FLASH_PREVIEW = "gemini-3-flash-preview"` added to the model enum.

### What Changes

- **`GoogleGenAIClient._build_tools()`** — Extended to detect when a `ComputerUseConfig`
  is present and emit `types.Tool(computer_use=types.ComputerUse(...))` in the tools list
  alongside regular FunctionDeclaration tools.  *Evidence*: F004, F006

- **`GoogleGenAIClient` (function response handling)** — Extended to support
  `FunctionResponseBlob` in the response construction path, so screenshot bytes are
  sent back correctly.  *Evidence*: F004, F006

- **`GoogleGenAIClient._requires_thinking()`** — Extended to recognize computer-use
  models.  *Evidence*: F004

### What's Untouched (Non-Goals)

- **WebScrapingToolkit** — No modifications; it continues to work independently for
  selector-based scraping. The two toolkits are complementary, not competing.
- **Browserbase backend** — The reference repo supports it, but it can be added later
  as a separate task. Initial scope is Playwright-only.
- **Anthropic computer-use** — Different protocol entirely; out of scope.
- **Non-browser environments** — Only `ENVIRONMENT_BROWSER` is supported initially.
- **AbstractDriver interface** — Not modified; ComputerBackend is a separate abstraction
  optimized for coordinate-based (not selector-based) interaction.

### Patterns to Follow

- **FileManagerToolkit pattern**: Static async methods with `tool_prefix` for namespacing.
  *Evidence*: F005
- **DriverRegistry pattern**: Register the async Playwright backend via a factory function.
  *Evidence*: F002
- **`@register_agent`**: Register ComputerAgent with `at_startup=False` (created on demand).
  *Evidence*: F003
- **Screenshot pruning**: Keep only the last N turns of screenshots in conversation
  history to prevent context window exhaustion (reference uses N=3).
  *Evidence*: F001

### Integration Risks

- **SDK version compatibility**: The `types.ComputerUse`, `types.FunctionResponseBlob` types
  may require a specific minimum version of the `google-genai` SDK. *Mitigation*: Pin
  minimum version in dependencies; add try/except import with actionable error message.
  *Evidence*: F006

- **Screenshot memory bloat**: Each screenshot is a PNG (~100-500KB as base64). Long
  conversations can exhaust the context window. *Mitigation*: Implement the reference
  implementation's pruning strategy (keep last 3 turns' screenshots, strip older ones).
  *Evidence*: F001

- **Coordinate precision**: Denormalizing 0-1000 to small viewports may lose precision.
  *Mitigation*: Default viewport of 1280x720 (matching reference), configurable.
  *Evidence*: F001

---

## 4. Confidence Map

| ID | Claim | Evidence | Confidence | Reasoning |
|----|-------|----------|------------|-----------|
| C1 | Gemini computer-use requires `types.Tool(computer_use=types.ComputerUse(...))` in GenerateContentConfig | F001, F006 | high | Directly read from reference implementation source code |
| C2 | Existing PlaywrightDriver (async) provides all browser primitives needed for computer-use actions | F002 | high | PlaywrightDriver has click, fill, navigate, screenshot, scroll, hover — maps 1:1 |
| C3 | GoogleGenAIClient._build_tools() must be extended for ComputerUse tool type | F004 | high | Direct code read confirms only FunctionDeclaration is handled |
| C4 | ComputerInteractionToolkit fits the AbstractToolkit pattern with tool_prefix | F003, F005 | high | Consistent with FileManagerToolkit and JiraToolkit patterns |
| C5 | FunctionResponse must include FunctionResponseBlob with PNG screenshot bytes | F001, F006 | high | Required by the API contract per reference implementation |
| C6 | WebScrapingToolkit extraction can complement ComputerInteraction for structured data | F002 | medium | Both operate on Playwright with different targeting — composition is reasonable but untested |
| C7 | google-genai SDK in AI-Parrot's dependencies includes ComputerUse types | F006 | medium | Reference repo uses these types; AI-Parrot's SDK version may need upgrade |
| C8 | Natural-language condition evaluation for loop termination is feasible via screenshot analysis | F001 | medium | The model already reasons over screenshots to decide actions; evaluating a stop condition ("no more Next button") is the same capability, but loop reliability depends on the model's consistency across iterations |

Distribution: **5** high, **3** medium, **0** low.

---

## 5. Open Questions

### Resolved (during proposal phase)

- [x] **Should ComputerInteractionToolkit live in `parrot_tools/` (satellite) or `parrot/tools/` (core)?** — *Resolved*: `parrot_tools/` (satellite package, alongside WebScrapingToolkit). Keeps core lightweight; Google client changes remain in core but the toolkit lives in the satellite.
  *Resolves claims*: C4

- [x] **How should safety_decision confirmations be handled in ComputerAgent?** — *Resolved*: Configurable. Default to auto-acknowledge with logging; option for interactive confirmation via agent event hooks. Constructor parameter `safety_mode: Literal["auto", "interactive"] = "auto"`.
  *Resolves claims*: —

### Unresolved (defer to spec / implementation)

*(none)*

---

## 6. Recommended Next Step

**`/sdd-spec FEAT-227`** — *Rationale*: Localization is high-confidence (C1-C5 all high)
and the scope is well-bounded with clear integration points across toolkit, agent, client,
and model layers. Multiple tasks will be needed (toolkit, agent, client changes, models,
tests) making this suitable for full spec + task decomposition.

### Alternatives

- **`/sdd-brainstorm FEAT-227`** — if you want to explore alternative architectures
  (e.g., extending AbstractDriver vs. creating a separate ComputerBackend, or integrating
  at the client level vs. the toolkit level).
- **`/sdd-task FEAT-227`** — not recommended; this feature spans multiple modules and
  requires coordination across toolkit, client, and agent layers.
- **Manual review** — not needed; research is complete and confidence is high.

---

## 7. Research Audit

Full state of the research session, for reproducibility and review.

| Artifact | Path |
|----------|------|
| State checkpoints | `sdd/state/FEAT-227/state.json` |
| Source (raw) | `sdd/state/FEAT-227/source.md` |
| Findings (digests) | `sdd/state/FEAT-227/findings/F001-*.md` through `F006-*.md` |
| Synthesis (JSON) | `sdd/state/FEAT-227/synthesis.json` |

**Budget consumed**:
- Files read: 18 / 40
- Grep calls: 8 / 25
- Git calls: 0 / 10
- Truncated: **no**

**Mode determination**: `auto` → resolved to `enrichment` (additive verbs: "using",
"combining", "interaction"; no negation or bug indicators).

---

## 8. Provenance

| Field | Value |
|-------|-------|
| Generated by | `/sdd-proposal v1.0` |
| Synthesis prompt | `sdd/templates/synthesis.prompt.md v1.0` |
| Plan prompt | `sdd/templates/research_plan.prompt.md v1.0` |
| Schema versions | state=1.0, synthesis=1.0, research_plan=1.0 |
| Reference repo | https://github.com/google-gemini/computer-use-preview |
| Reference model | https://ai.google.dev/gemini-api/docs/models/gemini-2.5-computer-use-preview-10-2025 |
| Operator | Claude Opus 4.6 |
