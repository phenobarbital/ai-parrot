---
type: Wiki Overview
title: Brainstorm — Containing arbitrary-exec credential leakage across the agent
  runtime
id: doc:sdd-proposals-brainstorm-repl-sandbox-response-contract-scrubber-md
tags:
- overview
timestamp: '2026-07-16T08:34:12+00:00'
summary: A production `JiraSpecialist` agent (model `gemini-3`, pod `navigator-agent-jira`)
relates_to:
- concept: mod:parrot.security
  rel: mentions
---

---
id: FEAT-NNN
title: REPL sandboxing + Gemini response contract + deterministic output scrubber
overall_confidence: medium
revision: 2
status: brainstorm
related: [shell_tool/SecurityPolicy, ResultEncoder seam, bots/base output_mode]
trigger_incident: JiraSpecialist (gemini-3) leaked full os.environ via python_repl → Telegram + CloudWatch
---

# Brainstorm — Containing arbitrary-exec credential leakage across the agent runtime

## 0. Context (the incident that triggered this)

A production `JiraSpecialist` agent (model `gemini-3`, pod `navigator-agent-jira`)
running an autonomous "process the remaining tickets" loop called the
`python_repl` tool, evaluated `os.environ.keys()`, and the **`repr` of the
resulting `KeysView` serialized the entire mapping *with values***. That string
was returned as the tool result, fed back into the model's context, echoed by
the model as its final answer, rendered to Telegram, and logged in cleartext to
CloudWatch via fluent-bit.

**Verified mechanism** (reproduced locally):

```python
>>> repr(os.environ.keys())
KeysView(environ({'REDIS_DB': '1', 'ODOO_EPSON_PRODUCTION_PASSWORD': '...', ...}))
>>> list(os.environ.keys())            # what the model believed it was doing
['REDIS_DB', 'ODOO_EPSON_PRODUCTION_PASSWORD', ...]
```

Three independent failures stacked, each sufficient on its own to cause the leak:

1. `python_repl` runs **in-process with full access to the real `os.environ`**;
   `BLOCKED_IMPORTS` is empty and `sanitize_input` only strips markdown fences.
2. The **Gemini client surfaced raw tool output as the final response** — a
   recurring pattern where "internal" / non-useful tool calls or echoed results
   become the user-facing answer.
3. **No deterministic redaction** at any hop (tool result → model context →
   channel egress).

This brainstorm scopes three workstreams matching those three failures, plus
one cross-cutting foundation item.

## 1. Goals / Non-goals

**Containment thesis (the framing that orders everything below):** the objective
is **not** to stop the sandbox from running code — it's to stop the model's
internal reasoning / scaffolding / raw tool output from becoming the *external*
response, and to stop it treating a Python tool as license to execute *arbitrary*
code to explore the system. The weight sits on the response boundary (WS2 + WS3)
plus an anti-arbitrariness guardrail with two halves: a **capability** limit (WS1,
an allowlist-first REPL gate) and a **behavioral** limit (WS2, an explicit closed
tool manifest so the model stops hunting tools that don't exist).

**Goals**
- `python_repl` is **allowlist-first (RESTRICTIVE)**: only an explicit set of
  computation operations runs; everything else — including things we never
  anticipated — is denied by default. The allowlist *includes* navconfig logging
  and the `builtins` tools depend on, so it doesn't break infra; it's an AST
  allowlist, not a module denylist.
- The Gemini tool-call loop has an explicit, deterministic contract for **what
  constitutes a final response**, so raw tool output / code-exec stdout / echoed
  results / introspection scaffolding never become the answer unfiltered; and the
  model is told the **complete, closed** tool set so it stops improvising. *(Primary
  defense.)*
- A **deterministic secret scrubber** lives in the `AbstractTool` execution seam,
  applied in *both* directions (before results enter the LLM context, and before
  egress to a channel). *(Primary defense; load-bearing — see Q1.)*

**Non-goals (this FEAT)**
- Rotating the burned credentials / purging logs — operational, already in flight,
  out of scope for the code work.
- **Moving secrets out of `os.environ`** — decided NOT now (Q1, closed in §6).
  Infra uses `python-dotenv` (copies `.env` into the OS environment) + K8S env
  injection; structural change deferred. Consequence: the env-gate + scrubber are
  load-bearing, not redundant.
- **Subprocess / seccomp isolation of the REPL** — deferred (breaks navconfig
  socket logging and the `data_analysis` shared-state path; see §3.5).
- Per-tenant data-plane authorization (that's the `AuthorizingDataSource` track).

## 2. Cross-cutting foundation: a single deterministic security primitive

All three workstreams want the same thing: a fast, compiled, deterministic
pattern engine that classifies a string (code or output) against a policy. We
already have one for shell commands.

> **Existing, verified:** `packages/ai-parrot-tools/src/parrot_tools/shell_tool/security.py`
> — `CommandSanitizer`, `SecurityPolicy` (`.restrictive()` / `.moderate()` /
> `.permissive()`), `ValidationResult`, `CommandVerdict`, pre-compiled regex
> pattern list, `denied_patterns`, `max_output_bytes`, `audit_log`.

**Proposal (placement decided):** the reusable engine lives in **core
(`ai-parrot`)**, e.g. `parrot.security`, and `shell_tool` (in `ai-parrot-tools`)
imports it from core. Dependency direction is `parrot_tools → core`, never the
reverse, so the shared code **must** sit in core — moving `shell_tool`'s
`CommandSanitizer`/`SecurityPolicy` primitives down into core and re-importing
them. Code duplication is acceptable if a clean extraction is awkward; it is *not*
a blocker. The same core engine backs:
- `CommandSanitizer` (shell — relocated to core, re-exported to `parrot_tools`)
- `PythonCodeSanitizer` (workstream 1 — new, core)
- `OutputScrubber` (workstream 3 — new, core)

---

## 3. Workstream 1 — `python_repl` sandboxing

### 3.1 Current state (verified anchors)

- `packages/ai-parrot/src/parrot/tools/pythonrepl.py` → `class PythonREPLTool(AbstractTool)`
- Exec path: `async _execute()` → `loop.run_in_executor(None, self._execute_code, code, debug)`
  — runs on the **default thread pool of the same process**.
- `_execute_code()` builds namespace from `self.globals` / `self.locals`, captures
  stdout via `redirect_stdout(StringIO)`, returns captured output + a
  "new variables created" report.
- `BLOCKED_IMPORTS: set = set()` — **empty**.
- `sanitize_input()` — strips ```` ```python ```` fences only.
- Namespace seeded in `_setup_environment()` with `pd, np, plt, sns, numexpr,
  json_encoder/decoder, report_directory, execution_results, save_current_plot,
  …`. `os` is **not** seeded, but `import os` works (full `__builtins__`).
- **Shared-state coupling to verify before subprocessing:** the PandasAgent /
  DatasetManager path depends on in-process namespace sharing —
  `packages/ai-parrot/src/parrot/tools/dataset_manager/tool.py` uses
  `self._repl_locals_getter()` to read DataFrames the model created in the REPL
  (`store_dataframe`), and `packages/ai-parrot/src/parrot/tools/agent.py`
  `_inject_context_to_repl()` writes `previous_result` / `<agent>_result` into
  `python_repl.globals`. **A subprocess REPL breaks both** unless we add a
  state-transfer channel.

### 3.2 The two distinct REPL profiles

| Profile | Used by | Needs FS? | Needs net/subprocess? | Needs shared in-proc state? |
|---|---|---|---|---|
| `general` (`python_repl`) | JiraSpecialist, GithubReviewer, general agents | no | no | no |
| `data_analysis` (`python_repl_pandas`) | PandasAgent, DatasetManager | catalog reads only (via `fetch_dataset`, not raw FS) | no | **yes** (DataFrame catalog) |

The incident agent used the **`general`** profile, which has zero legitimate need
for bulk env access, network, subprocess, or introspection. This split is the key
insight: we don't have to solve the hard subprocess-state-transfer problem to fix
the incident — both profiles share the same expression-level baseline (§3.4), and
`data_analysis` simply gets catalog-mediated data access on top.

### 3.3 The guardrail is against *arbitrariness*, not a list of bad patterns

The surprising part of the incident isn't that `os.environ` leaked — it's that an
agent handed a *Python tool* decided, unprompted, to execute arbitrary code to
introspect the OS. That arbitrariness is the disease; the env dump is one symptom.
A denylist of known-bad patterns only ever chases symptoms. The guardrail has to
constrain the **space** of what the REPL may do, so the model can't improvise
system exploration in the first place — including things we never anticipated.

So the `general` profile is **allowlist-first (RESTRICTIVE)**: only an explicit set
of computation operations is permitted; everything else is denied by default. Same
posture as `shell_tool`'s `SecurityLevel.RESTRICTIVE` ("only explicitly allowed
commands run"), applied to Python AST nodes/calls. (The behavioral half of the
anti-arbitrariness guardrail — stopping the model from *wanting* to write arbitrary
discovery code — lives in WS2 §4.4: an explicit, closed tool manifest.)

Two constraints bound the allowlist:

- **Q1 (closed) — secrets stay in `os.environ`.** Infra loads `.env` via
  `python-dotenv` (copies into the OS environment) + K8S env injection; removing
  them is a deferred structural change. Consequence: we can't swap `os.environ` for
  an in-process REPL, so env access stays *off the allowlist* and the
  `OutputScrubber` is the load-bearing backstop.
- **navconfig logging needs sockets.** `navconfig.logging` ships logs to Logstash
  over a socket and most tools log via navconfig; some tools need `builtins`. The
  allowlist must *include* navconfig logging and those builtins — which is exactly
  why the instrument is an AST allowlist, **not** a module denylist that would
  break infra.

### 3.4 Allowlist-first gate — `PythonCodeSanitizer`

`general` permits an explicit operation set and denies the rest by default:

**Allowed (illustrative):** literals, names, arithmetic / comparison / boolean ops,
assignments, f-strings, comprehensions, `for`/`if`/`while`, `def`/`lambda`, calls to
a whitelisted builtin set (`len`, `range`, `sum`, `sorted`, `min`/`max`, `print`,
`enumerate`, `zip`, …), imports from an allowlist (`navconfig`/`navconfig.logging`,
`pandas`, `numpy`, `json`, `math`, `datetime`, `statistics`, `re`), and ordinary
pandas/numpy computation on already-materialized data.

**Categorically denied — enforced even if someone routes around the allowlist:**

| Class | Examples | Rationale |
|---|---|---|
| Env access | `os.environ`, `os.environ.keys/values/items()`, `dict(os.environ)`, `os.getenv/putenv` | incident vector; secrets live here (Q1) |
| Introspection-to-escape / state dump | `__class__`/`__bases__`/`__subclasses__`/`__mro__`/`__globals__`/`__builtins__`/`__dict__` walking, `globals()`/`locals()`/`vars()`, `gc.get_objects()` | sandbox escape **and** internal-state leakage |
| Dynamic exec | `eval`, `exec`, `compile`, `__import__(dynamic)` | arbitrary re-entry around the allowlist |
| Data ingress/egress (Q4 — from `bots/data.py`) | `open`, `pathlib.read_*`, `glob`, `os.listdir/scandir/walk`, `pd.read_csv/read_sql/read_html/…`, `requests`/`urllib`/`httpx`/`aiohttp`, DB drivers, outbound `socket.connect` | unauthorized data access |

```python
# does NOT exist yet — allowlist-first, import-friendly
@dataclass(frozen=True)
class PythonExecutionPolicy:
    level: SecurityLevel = SecurityLevel.RESTRICTIVE   # reuse shell_tool enum
    default_deny: bool = True                          # anything not allowed is denied
    allowed_imports: frozenset = frozenset({"navconfig", "pandas", "numpy", "json",
                                            "math", "datetime", "statistics", "re"})
    allowed_builtins: frozenset = frozenset({"len", "range", "sum", "sorted", ...})
    # categorical denials enumerated so a partial allowlist can't be routed around:
    deny_env_access: bool = True
    deny_introspection: bool = True
    deny_dynamic_exec: bool = True
    deny_data_io: bool = True                          # the bots/data.py set (Q4)
    isolation: Literal["in_process"] = "in_process"    # subprocess deferred
    max_output_bytes: int = 1_048_576

class PythonCodeSanitizer:
    """AST allowlist gate. RESTRICTIVE: deny any node/call/import not allowlisted."""
    def validate(self, code: str) -> ValidationResult:   # reuse shell_tool verdict type
        tree = ast.parse(code)
        # walk: any node type / call target / import NOT on the allowlist => DENY
        ...
```

> **Q4 (closed):** the `bots/data.py` forbidden-pattern list is promoted from
> prompt-layer guidance to the deterministic `PythonCodeSanitizer`, applied as a
> categorical denial under **every** profile. The profiles then differ only in how
> wide the *allowlist* is: `general` (Jira/GitHub) keeps the tightest set and gets
> its real data through tools, not the REPL; `data_analysis` widens the allowlist to
> permit pandas/numpy compute on DataFrames already materialized via `fetch_dataset`
> over the catalog (still no raw FS/net/DB).

Wiring: `PythonREPLTool.__init__` takes `policy: PythonExecutionPolicy`
(default the general/restrictive profile); `_execute()` runs
`sanitizer.validate(code)` and on `is_denied` returns a structured refusal
(no exec, no echo of the offending code).

### 3.5 Isolation: stay in-process (subprocess deferred)

| | In-process (chosen) | Subprocess (deferred) |
|---|---|---|
| navconfig socket logging | works unchanged | seccomp/socket tension |
| `data_analysis` shared DataFrame state (`_repl_locals_getter`, `_inject_context_to_repl`) | works | needs pyarrow/pickle state channel |
| env isolation | **cannot** swap `os.environ` → gate + scrubber carry it (Q1) | clean env by construction |
| escape resistance | weaker — mitigated by gate + WS3 + the response boundary (WS2) | real OS boundary |

Decision: **in-process + expression-level gate + `OutputScrubber`**, response
boundary (WS2/WS3) as primary containment. Subprocess stays on the shelf as a
future hardening if escape-resistance ever needs to be a hard boundary.

### 3.6 Does NOT exist yet
- `PythonExecutionPolicy`, `PythonCodeSanitizer` (expression-level AST gate).
- Promotion of `bots/data.py` patterns into deterministic enforcement.
- Any env-access / introspection gating in the REPL exec path.
- (Subprocess isolation + state channel — explicitly **deferred**, not this FEAT.)

---

## 4. Workstream 2 — Gemini tool-call → response contract

> **This is the primary containment per the thesis in §1.** Since secrets stay in
> `os.environ` (Q1) and the REPL is in-process, the exec-side gate cannot be a hard
> boundary — so the load-bearing guarantee is here: the model's internal reasoning,
> scaffolding, and raw tool output must never reach the external response.

### 4.1 Current state (verified anchors)

`packages/ai-parrot/src/parrot/clients/google/client.py`:
- `_handle_multiturn_function_calls()` — the loop. Each iteration:
  `_get_function_calls_from_response()` → if **none**, `final_text =
  _safe_extract_text(current_response)` and the loop ends, returning that as the answer.
- `_get_function_calls_from_response()` — extracts native `function_call` parts,
  **also converts ` ```tool_code ` text blocks to function calls**
  (`_parse_tool_code_blocks`), skips `part.thought is True`.
- `_safe_extract_text()` — filters `function_call` and thought parts; returns text.
- The **forced-synthesis block is commented out**; when `final_text` is empty
  after tools, it currently logs a warning and **skips synthesis**.
- Fallback observed in `resume()` / streaming path:
  `if not assistant_response_text and code_execution_content['output']:
  assistant_response_text = "\n".join(code_execution_content['output'])`
  — i.e. **raw code-exec stdout can become the answer**.

### 4.2 The failure class (your framing)

"Tool calls that return nothing useful, or that are *internal*, end up selected
as the output." Concretely, the response that reaches the user can be:
1. A genuine model synthesis (correct).
2. **A verbatim echo of the last tool result** (the incident — model emitted the
   environ dump as text; `_safe_extract_text` returned it).
3. **Raw code-exec stdout** used as a fallback when no text part exists.
4. Scaffolding the model talks to itself with — `default_api` import attempts,
   `tool_code` blocks, calls to non-existent tools — that leak into text.

We have no step that **classifies** the candidate final text by provenance and
decides whether it's a legitimate answer.

### 4.3 Options

| Option | What it does | Pros | Cons |
|---|---|---|---|
| A. Just run the scrubber (WS3) on `final_text` | Redact secrets in the final answer | Stops *this* leak | Doesn't fix the general "internal output becomes answer" class |
| B. Echo detection | Similarity check between `final_text` and last N `tool_result`s; if high → suppress | Catches verbatim/near-verbatim dumps | Threshold tuning; legitimate summaries can resemble results |
| C. Provenance tagging | Track whether final text is synthesis vs code-exec-fallback vs echo; gate per source | Principled; kills the code-exec-stdout fallback vector | More plumbing through the loop |
| D. **`_resolve_final_response()` chokepoint (recommended)** | Single deterministic method at loop exit: scrubber (WS3) + echo/provenance rules + explicit empty-handling + `default_api`/tool_code hygiene | One place to reason about "what is a response"; reuses WS3; testable | Refactors the loop tail |

### 4.4 Proposed direction

Introduce one chokepoint that every Gemini terminal path funnels through:

```python
# does NOT exist yet — single source of truth for "what is a final response"
def _resolve_final_response(self, candidate_text, all_tool_calls, code_exec_output):
    # 1. provenance: was this synthesis, an echo of a tool_result, or code-exec stdout?
    provenance = classify_provenance(candidate_text, all_tool_calls, code_exec_output)
    # 2. never ship a verbatim/near-verbatim echo of a tool result as the answer
    if provenance == "tool_echo":
        candidate_text = self._synthesize_or_safe_fallback(...)   # decide policy (Open Q #2)
    # 3. never promote raw code-exec stdout to the answer without scrubbing + framing
    # 4. deterministic scrub (WS3) ALWAYS runs last, regardless of provenance
    return OutputScrubber(policy).scrub(candidate_text)
```

Adjacent hygiene — two layers, prevention then containment:

- **Prevention (root cause, closed):** passing Gemini the tools' JSON schemas at
  instantiation is **not enough** — it keeps hunting for tools it imagines exist
  (`default_api`) and writes arbitrary Python to find them. The fix is to be
  *explicit and closed* in the system prompt / per-call instruction: "these are
  **all** the tools available; there is no other API, module, or `default_api` to
  import; if a task needs a capability not in this list, say so — do not write code
  to discover or call anything else." This is the behavioral half of the
  anti-arbitrariness guardrail (WS1 §3.3 is the capability half). It directly
  removes the motive that walked `os.environ`.
- **Containment (belt-and-suspenders):** in `_get_function_calls_from_response` /
  the loop, still detect and drop `default_api` import attempts and self-referential
  `tool_code` targeting non-existent tools, and surface a typed "tool not available"
  rather than letting it improvise.
- Decide the **empty-after-tools policy** deliberately (revive forced synthesis, or
  return a typed "no answer produced" — Open Q #1), instead of silently falling back
  to raw output.

### 4.5 Does NOT exist yet
- `_resolve_final_response()` / provenance classification / echo detection.
- Any guard against `default_api` import attempts or non-existent-tool `tool_code`.
- A defined policy for the empty-response case (currently: skip + implicit raw fallback).

⚠️ VERIFY: confirm every terminal return in the Gemini client (`ask`, streaming
`ask_stream`, `resume`, `invoke`) routes through the new chokepoint — there are
**at least four** exit points building `AIMessageFactory.from_gemini(...)`.

---

## 5. Workstream 3 — deterministic scrubber in `AbstractTool`

### 5.1 Current state (anchors + VERIFY)

- Tool execution base: `packages/ai-parrot/src/parrot/tools/abstract.py` →
  `AbstractTool`. Log strings seen at runtime: `"Executing tool: <name>"`,
  `"Tool <name> executed successfully"`.
- The NOTICE logs `📤 Raw Result Type: <class ...>`, `🔍 Tool: <name>`,
  `Tool <name> output preview: ...` appear **without a class logger prefix** —
  ⚠️ VERIFY which module emits them (likely the result-handling wrapper in
  `abstract.py` or `bots/base.py`); that emission site is the natural scrub point
  because it already has the raw result in hand.
- Egress side: `packages/ai-parrot/src/parrot/bots/base.py` has
  `_sanitize_tool_data()` (JSON-serialization safety, **not** secret redaction)
  and `output_mode` formatting for `OutputMode.TELEGRAM` / `MSTEAMS`.

### 5.2 Proposed direction — `OutputScrubber`

Deterministic, compiled, idempotent. Same engine as §2. Detects and replaces
with `***REDACTED:<reason>***`:

| Class | Pattern (illustrative) | Reason tag |
|---|---|---|
| Environ repr | `environ(`, `KeysView(environ(`, `os._Environ` | `env_dump` |
| Secret-named pair | `('PASSWORD'|'TOKEN'|'SECRET'|'API_KEY'|'_PWD'|'DSN'…): '…'` | `secret_kv` |
| Connection string | `proto://user:pass@host[:port]` (postgres/redis/amqp/mysql…) | `dsn` |
| Bearer / JWT | `eyJ[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\.` | `jwt` |
| Cloud key | `AKIA[0-9A-Z]{16}`, `-----BEGIN .* PRIVATE KEY-----` | `cloud_key` |
| Internal topology (configurable) | `172\.(1[6-9]|2\d|3[01])\.`, `10\.`, internal hostnames | `net_topology` |

Rules:
- **Two emplacements:** (a) on every tool result *before it returns to the client/
  model* (so secrets never enter LLM context, Vertex logs, or CloudWatch) — **this
  one is load-bearing, not belt-and-suspenders**, because Q1 means `os.environ`
  keeps the secrets and any tool can surface them; (b) reused by WS2's
  `_resolve_final_response` for channel egress.
- **Never log the secret value.** The audit log records the matched key
  name / pattern tag and tool name only (model the `audit_log` flag from
  `SecurityPolicy`).
- **Allowlist-aware** to avoid clobbering legitimate payloads (e.g. a ticket body
  that legitimately contains `token=`); configurable, default conservative.
- **Idempotent + fast** (pre-compiled regex, like `CommandSanitizer`).
- Hook point should be the single result-handling wrapper, not per-tool, so every
  tool inherits it (the incident tool, `python_repl`, gets covered for free, but
  so does any future tool that returns a dict/string with secrets).

### 5.3 Does NOT exist yet
- `OutputScrubber` / the secret pattern library.
- Any redaction on the tool-result-in path (only JSON-serialization sanitization exists).
- Audit logging of redactions.

⚠️ VERIFY: exact method in `abstract.py` (or `bots/base.py`) where the raw tool
result is materialized into the `Raw Result Type` / `output preview` NOTICE — that
is the single insertion point for emplacement (a).

---

## 6. Open Questions

### Closed in this revision
- **Q1 — secrets out of `os.environ`: NO, not now.** Infra uses `python-dotenv`
  (copies `.env` into the OS environment) + K8S env injection; moving to a mounted
  secret store / Vault is a structural change deferred. **Consequence baked into the
  design:** the WS1 env-access AST gate and the WS3 in-bound `OutputScrubber` are
  load-bearing, and subprocess env-isolation is off the table for now.
- **Q4 — promote `bots/data.py` forbidden patterns: YES.** They move from
  prompt-layer guidance to the deterministic `PythonCodeSanitizer`, applied as a
  categorical denial under all REPL profiles (§3.4).
- **Module placement — shared engine lives in core (`ai-parrot`).** Dependency
  direction is `parrot_tools → core`, so `shell_tool`'s `CommandSanitizer` /
  `SecurityPolicy` primitives move down into core and `parrot_tools` re-imports
  them. Code duplication is acceptable if extraction is awkward; not a blocker (§2).
- **`default_api` / arbitrary tool hunting — explicit closed tool manifest.** JSON
  schemas alone don't stop it; the system prompt must state the complete, closed

…(truncated)…
