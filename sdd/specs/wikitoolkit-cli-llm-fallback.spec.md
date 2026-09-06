---
type: feature
base_branch: dev
---

# Feature Specification: Auto-detect Claude Code / Codex CLI and default wikitoolkit + bookstore's LLM to it

**Feature ID**: FEAT-531
**Date**: 2026-09-06
**Author**: jesuslarag@gmail.com (proposal + spec via Claude Code)
**Status**: approved
**Target version**: 0.30.0

---

## 1. Motivation & Business Requirements

### Problem Statement

`wikitoolkit build`/`ingest` and the `bookstore` CLI run in a fully degraded mode (BM25 /
deterministic carding only — e.g. `"TOC detector failed on page 0: No LLM configured for the
bookstore"`) on any freshly created repo, because `PARROT_BOOKSTORE_LLM` / `WIKI_MODEL` /
`WIKI_LIGHTWEIGHT_MODEL` / `WIKI_EXTRACT_LLM` all require an explicit provider spec and none
of them ever default to anything (verified: `bookstore/_llm.py::resolve_adapter` and the three
resolution points in `wiki/cli.py` all require an explicit env var/flag and degrade silently
otherwise — no provider, including Gemini, is ever chosen implicitly today).

Both `wikitoolkit` and `bookstore` are CLI tools most commonly run from inside a terminal
session that already has a working coding-agent CLI (Claude Code and/or OpenAI Codex)
authenticated. Requiring the user to separately provision and inject a provider API key into
`.env` before these tools do anything useful is unnecessary friction — the credentials to run
a cheap LLM call are usually already sitting on the machine.

### Goals

- On first use, when the relevant env var is unset, auto-detect whether a Claude Code and/or
  Codex CLI session is usable on this machine via a **safe, non-invasive check** (no
  subprocess spawn, no network call, no real LLM request) and, if so, default to it.
- Prefer Claude Code when both are detected.
- Use a cheap, deterministic model for the auto-selected default (Haiku for Claude Code, per
  the existing `ClaudeAgentClient._lightweight_model` precedent).
- Make the auto-selection **visible**: emit an unmissable warning naming the auto-selected
  provider/model and which env var to set to override it.
- Provide a single, global opt-out (`PARROT_NO_AUTO_LLM=1`) that restores today's strict
  degraded-mode behavior exactly.
- Preserve full backward compatibility: any explicit env var configuration always wins over
  auto-detection, unchanged.

### Non-Goals (explicitly out of scope)

- Detecting or defaulting to a `gemini` CLI session — Gemini remains available only via
  explicit configuration (`PARROT_BOOKSTORE_LLM=google:...` etc.).
- Any change to `ClaudeAgentClient` or `OpenAICodexClient` themselves — both already exist and
  are fully registered `LLMFactory` providers; this feature only adds a detection/defaulting
  layer above `LLMFactory.create()`.
- Changing what happens when auto-detection *also* fails (neither CLI is available) — the
  existing degraded-mode behavior (silent BM25/no-LLM fallback with a warning) is unchanged.
- A configurable precedence order between Claude Code and Codex (e.g. an
  `PARROT_AUTO_LLM_PREFERENCE` env var) — Claude Code always wins when both are available; a
  configurable order was considered and explicitly deferred (see
  `sdd/proposals/wikitoolkit-cli-llm-fallback.proposal.md` §5, U1).
- Adding a cheaper/"mini" Codex model tier — `OpenAICodexClient.default_model`
  (`"gpt-5.1-codex"`) is used as-is for the Codex fallback (resolved in the proposal, U3).

---

## 2. Architectural Design

### Overview

A new, provider-agnostic helper, `detect_coding_agent_llm()`, is added to core `parrot.clients`.
It never imports a provider SDK or spawns a subprocess. It uses two already-existing, cheap
signals:

1. `LLMFactory.list_providers()` — the existing entry-point discovery mechanism
   (`packages/ai-parrot/src/parrot/clients/factory.py:214-221`) — to check whether the
   `claude-code` / `codex-code` satellite distributions (`ai-parrot-client-anthropic` /
   `ai-parrot-client-openai`) are even installed.
2. `shutil.which("claude")` / `shutil.which("codex")` — to check whether the corresponding CLI
   binary is actually on `PATH` (i.e. a real, usable coding-agent session, not just an
   installed pip package).

Both checks are synchronous, in-process, and side-effect-free — no `claude_agent_sdk` or
`openai_codex` import is attempted during detection (unlike the original proposal draft,
which planned to `try: import <sdk>`; `list_providers()` is cheaper and sufficient, since a
registered provider key already implies the satellite package that would perform that import
is installed).

Four existing call sites are modified to consult this helper as a fallback, each emitting a
visible warning on a successful auto-selection, and each respecting its own subsystem's
existing env-reading convention for the `PARROT_NO_AUTO_LLM` opt-out:

- `bookstore/_llm.py::resolve_adapter` (reads `os.environ` directly, matching its existing
  convention)
- `wiki/cli.py::_extract_into_graph` (`WIKI_EXTRACT_LLM`)
- `wiki/cli.py::_resolve_model_id` / the `_build_triage_adapters` call site (`WIKI_MODEL` /
  `WIKI_LIGHTWEIGHT_MODEL`, both via `_env_setting`, which is navconfig-aware)

### Component Diagram

```
bookstore/_llm.py::resolve_adapter ───┐
wiki/cli.py::_extract_into_graph  ────┼──→ parrot.clients.detection.detect_coding_agent_llm()
wiki/cli.py::_resolve_model_id ───────┤          │
wiki/cli.py::_build_triage_adapters ──┘          ├──→ LLMFactory.list_providers()  (entry points)
                                                  └──→ shutil.which("claude" | "codex")
```

### Integration Points

| Existing Component | Integration Type | Notes |
|---|---|---|
| `parrot.clients.factory.LLMFactory.list_providers()` | calls | Read-only entry-point discovery; no client instantiated during detection. `packages/ai-parrot/src/parrot/clients/factory.py:214-221` |
| `parrot.clients.factory.LLMFactory.create()` | uses (unchanged) | Detection returns a `"provider:model"` string consumed exactly like any user-supplied spec, at each existing call site. `packages/ai-parrot/src/parrot/clients/factory.py:257-259` |
| `bookstore/_llm.py::resolve_adapter` | extends | Adds the detection fallback before the existing degraded-mode return. `packages/ai-parrot/src/parrot/knowledge/bookstore/_llm.py:52-59` |
| `wiki/cli.py::_extract_into_graph`, `_resolve_model_id`, `_build_triage_adapters` call site | extends | Same fallback pattern, three places. `packages/ai-parrot/src/parrot/knowledge/wiki/cli.py:2712-2723, 3409-3428, 3431-3462` |
| `ClaudeAgentClient.provider_keys` / `OpenAICodexClient.provider_keys` | reads (unchanged) | Detection only checks for the string keys `"claude-code"` / `"codex-code"` in `LLMFactory.list_providers()`; no direct import of either client class. `packages/ai-parrot-client-anthropic/.../claude_agent.py:285`, `packages/ai-parrot-client-openai/.../codex_agent.py:85` |

### Data Models

No new Pydantic models. `detect_coding_agent_llm()` returns `Optional[str]` (an `LLMFactory`
spec string or `None`) — deliberately the same shape `resolve_adapter()` and `_resolve_model_id()`
already consume.

### New Public Interfaces

```python
# packages/ai-parrot/src/parrot/clients/detection.py

def detect_coding_agent_llm() -> Optional[str]:
    """Detect an available coding-agent CLI and return its default LLMFactory spec.

    Checks Claude Code first, then Codex. Never imports a provider SDK and
    never spawns a subprocess — only entry-point discovery
    (``LLMFactory.list_providers()``) and ``shutil.which`` on the CLI binary.

    Returns:
        ``"claude-code:claude-haiku-4-5-20251001"`` if a Claude Code CLI
        session looks usable; ``"codex-code:gpt-5.1-codex"`` if only Codex
        does; ``None`` if neither is detected.
    """
```

---

## 3. Module Breakdown

### Module 1: Detection helper
- **Path**: `packages/ai-parrot/src/parrot/clients/detection.py`
- **Responsibility**: `detect_coding_agent_llm()` — the single shared, provider-agnostic
  safe-detection function described above. No I/O beyond `shutil.which` and reading the
  already-populated `LLMFactory` provider registry.
- **Depends on**: `parrot.clients.factory.LLMFactory` (existing, unmodified)

### Module 2: Bookstore LLM resolution fallback
- **Path**: `packages/ai-parrot/src/parrot/knowledge/bookstore/_llm.py`
- **Responsibility**: `resolve_adapter()` gains a fallback branch: when `PARROT_BOOKSTORE_LLM`
  is unset and `PARROT_NO_AUTO_LLM` is not set (checked via `os.environ`, matching the
  existing convention in this file), call Module 1; on a hit, build the adapter from the
  detected spec and log a `logger.warning` naming the spec and the override variable; on a
  miss, fall through to the existing degraded-mode warning/return unchanged.
- **Depends on**: Module 1

### Module 3: Wikitoolkit LLM resolution fallback
- **Path**: `packages/ai-parrot/src/parrot/knowledge/wiki/cli.py`
- **Responsibility**: the three existing resolution points gain the same fallback:
  - `_extract_into_graph` — when `WIKI_EXTRACT_LLM` is unset (via `_env_setting`) and
    `PARROT_NO_AUTO_LLM` is not set (also via `_env_setting`, matching this file's
    navconfig-aware convention), call Module 1; on a hit, use the detected spec and
    `click.echo` a visible message instead of the current "[extract skipped: ...]" message.
  - `_resolve_model_id` (and, by extension, every ingest-style command that calls it for
    `WIKI_MODEL` / `WIKI_LIGHTWEIGHT_MODEL`) — when **both** the heavy and lightweight values
    are unset together, call Module 1 once and use the same detected spec for both (never
    only one — see Acceptance Criteria for the same-provider constraint). If only one of the
    two is explicitly set and the other is not, keep today's `ClickException` behavior
    unchanged (do not guess a mismatched pairing).
- **Depends on**: Module 1

---

## 4. Test Specification

### Unit Tests

| Test | Module | Description |
|---|---|---|
| `test_detect_returns_none_when_no_provider_registered` | Module 1 | `LLMFactory.list_providers()` monkeypatched to `{}` → returns `None` |
| `test_detect_prefers_claude_code_when_both_available` | Module 1 | both `claude-code` and `codex-code` in providers, both `shutil.which` hits → returns the Claude Code spec |
| `test_detect_falls_back_to_codex` | Module 1 | only `codex-code` registered + `shutil.which("codex")` hits → returns `"codex-code:gpt-5.1-codex"` |
| `test_detect_registered_but_binary_missing` | Module 1 | provider key present but `shutil.which` returns `None` for both → returns `None` (package installed ≠ usable CLI session) |
| `test_resolve_adapter_uses_detection_when_unset` | Module 2 | `PARROT_BOOKSTORE_LLM` unset, `detect_coding_agent_llm` monkeypatched to return a spec → adapter built from that spec, warning logged |
| `test_resolve_adapter_respects_opt_out` | Module 2 | `PARROT_NO_AUTO_LLM=1` set, `PARROT_BOOKSTORE_LLM` unset → degraded mode unchanged, detection never called |
| `test_resolve_adapter_explicit_config_wins` | Module 2 | `PARROT_BOOKSTORE_LLM` set → detection never called (regression guard) |
| `test_extract_into_graph_uses_detection_when_unset` | Module 3 | `WIKI_EXTRACT_LLM` unset, detection returns a spec → extraction proceeds with a visible message instead of "[extract skipped...]" |
| `test_wiki_model_resolution_only_triggers_when_both_unset` | Module 3 | `WIKI_MODEL` set but `WIKI_LIGHTWEIGHT_MODEL` unset → existing `ClickException` behavior preserved, detection never called |
| `test_wiki_model_resolution_uses_detection_when_both_unset` | Module 3 | both unset, detection returns a spec → both light and heavy adapters built from the *same* detected spec |
| `test_wiki_no_auto_llm_opt_out` | Module 3 | `PARROT_NO_AUTO_LLM=1` → all three wiki resolution points keep today's error/skip behavior unchanged |

### Integration Tests

| Test | Description |
|---|---|
| `test_bookstore_cli_degrades_without_any_config_or_cli` | With no env vars and `shutil.which` mocked to return `None` for both binaries, `bookstore` CLI still runs in degraded (BM25) mode exactly as today — full regression guard for the "neither configured nor detected" path |

### Test Data / Fixtures

```python
# packages/ai-parrot/tests/clients/test_detection.py
import shutil
import pytest
from parrot.clients import detection


@pytest.fixture
def no_providers(monkeypatch):
    monkeypatch.setattr(
        "parrot.clients.factory.LLMFactory.list_providers", lambda: {}
    )


@pytest.fixture
def both_providers(monkeypatch):
    monkeypatch.setattr(
        "parrot.clients.factory.LLMFactory.list_providers",
        lambda: {"claude-code": "ai-parrot-client-anthropic", "codex-code": "ai-parrot-client-openai"},
    )
```

---

## 5. Acceptance Criteria

> This feature is complete when ALL of the following are true:

- [ ] `detect_coding_agent_llm()` returns `None` when `LLMFactory.list_providers()` contains
      neither `claude-code` nor `codex-code`.
- [ ] Returns `"claude-code:claude-haiku-4-5-20251001"` when `claude-code` is a discovered
      provider **and** `shutil.which("claude")` finds a binary.
- [ ] Returns `"codex-code:gpt-5.1-codex"` when only `codex-code`/`codex` are discovered and
      available.
- [ ] Claude Code wins when both providers are discovered and both binaries are found.
- [ ] `detect_coding_agent_llm()` never imports `claude_agent_sdk` or `openai_codex`, and
      never spawns a subprocess or makes a network call.
- [ ] `bookstore/_llm.py::resolve_adapter()` logs a visible `WARNING`-level message naming the
      auto-selected spec and `PARROT_BOOKSTORE_LLM` as the override, whenever
      `PARROT_BOOKSTORE_LLM` is unset and detection succeeds.
- [ ] Setting `PARROT_NO_AUTO_LLM=1` restores byte-for-byte the current degraded-mode
      behavior in both bookstore and wikitoolkit — detection is never invoked.
- [ ] `wiki/cli.py`'s `WIKI_MODEL` / `WIKI_LIGHTWEIGHT_MODEL` / `WIKI_EXTRACT_LLM` resolution
      falls back to `detect_coding_agent_llm()`, with a visible message, only when the
      relevant env var(s) are unset.
- [ ] Auto-detection for `WIKI_MODEL`/`WIKI_LIGHTWEIGHT_MODEL` never mixes providers — it only
      triggers when **both** are unset, and always applies the same detected spec to both.
- [ ] Any explicit `PARROT_BOOKSTORE_LLM` / `WIKI_MODEL` / `WIKI_LIGHTWEIGHT_MODEL` /
      `WIKI_EXTRACT_LLM` value always takes precedence over auto-detection (regression test
      required for each).
- [ ] All unit tests pass:
      `pytest packages/ai-parrot/tests/clients/test_detection.py packages/ai-parrot/tests/knowledge/bookstore/test_llm.py packages/ai-parrot/tests/knowledge/wiki/test_cli.py -v`
- [ ] No breaking changes to existing public API — `resolve_adapter()`, `_resolve_model_id()`
      signatures unchanged; only their internal fallback behavior changes.
- [ ] `docs/guides/llm-wiki-guide.md`'s env-var table updated to document `PARROT_NO_AUTO_LLM`
      and the auto-detection behavior for `WIKI_MODEL` / `WIKI_LIGHTWEIGHT_MODEL` /
      `WIKI_EXTRACT_LLM`.

---

## 6. Codebase Contract

> **CRITICAL — Anti-Hallucination Anchor**

### Verified Imports

```python
from parrot.clients.factory import LLMFactory  # verified: packages/ai-parrot/src/parrot/clients/factory.py:163
from parrot.clients import detection  # NEW — to be created at packages/ai-parrot/src/parrot/clients/detection.py
```

### Existing Class Signatures

```python
# packages/ai-parrot/src/parrot/clients/factory.py
class LLMFactory:
    @staticmethod
    def parse_llm_string(llm: str) -> Tuple[str, Optional[str]]: ...      # line 174
    @staticmethod
    def list_providers() -> Dict[str, str]: ...                          # line 214-221; entry-point key -> satellite dist name
    @staticmethod
    def create(
        llm: str,
        model_args: Optional[Dict[str, Any]] = None,
        tool_manager: Optional[Any] = None,
        **kwargs,
    ) -> AbstractClient: ...                                             # line 256-259

# packages/ai-parrot-client-anthropic/src/parrot/clients/anthropic/claude_agent.py
class ClaudeAgentClient(AbstractClient):                                 # line 265
    client_type: str = "claude_agent"                                    # line 281
    client_name: str = "claude-agent"                                    # line 282
    provider_keys: tuple[str, ...] = ("claude-agent", "claude-code")      # line 285
    _default_model: str = "claude-sonnet-4-6"                            # line 288
    _lightweight_model: str = "claude-haiku-4-5-20251001"                # line 289 — the cheap-model precedent this spec reuses

# packages/ai-parrot-client-openai/src/parrot/clients/openai/codex_agent.py
class OpenAICodexClient(AbstractClient):                                 # line 71
    client_type = "openai_codex"                                         # line 79
    client_name = "openai-codex"                                         # line 80
    default_model = "gpt-5.1-codex"                                      # line 81
    provider_keys: tuple[str, ...] = ("codex-agent", "openai-codex", "codex-code")  # line 85
    codex_bin: str = "codex"                                             # constructor default, line 94

# packages/ai-parrot/src/parrot/knowledge/bookstore/_llm.py
def resolve_adapter(
    llm_spec: Optional[str] = None,
    lightweight_model: Optional[str] = None,
) -> tuple[Optional[Any], Optional[str], Optional[Any]]: ...              # line 35-75
ENV_LLM = "PARROT_BOOKSTORE_LLM"                                         # line 29
ENV_LLM_LIGHT = "PARROT_BOOKSTORE_LLM_LIGHT"                             # line 30

# packages/ai-parrot/src/parrot/knowledge/wiki/cli.py
def _env_setting(name: str) -> str | None: ...                          # line 464-479; navconfig-aware, falls back to os.environ
def _extract_into_graph(root, config, text, source_uri, asserted_by, run_id) -> dict | None: ...  # line 2694-2743
def _resolve_model_id(cli_value: str | None, env_name: str) -> str: ...  # line 3409-3428
def _build_triage_adapters(lightweight_model: str, model: str) -> tuple[Any, Any, str, bool]: ...  # line 3431-3462
```

### Integration Points

| New Component | Connects To | Via | Verified At |
|---|---|---|---|
| `detect_coding_agent_llm()` | `LLMFactory.list_providers()` | function call | `packages/ai-parrot/src/parrot/clients/factory.py:214-221` |
| `detect_coding_agent_llm()` | `shutil.which` | stdlib call | n/a (stdlib) |
| `resolve_adapter()` | `detect_coding_agent_llm()` | function call, new fallback branch | `packages/ai-parrot/src/parrot/knowledge/bookstore/_llm.py:52-59` |
| `_extract_into_graph()` | `detect_coding_agent_llm()` | function call, new fallback branch | `packages/ai-parrot/src/parrot/knowledge/wiki/cli.py:2712-2715` |
| `_resolve_model_id()` call site (ingest command) | `detect_coding_agent_llm()` | function call, new fallback branch | `packages/ai-parrot/src/parrot/knowledge/wiki/cli.py:3409-3428` |

### Does NOT Exist (Anti-Hallucination)

- ~~`parrot.clients.detection`~~ — does not exist yet; this spec creates it.
- ~~A cheap/"mini" Codex model id (e.g. `OpenAICodexClient.CHEAP_MODEL`)~~ — does not exist;
  only `default_model = "gpt-5.1-codex"` is defined. Do not invent a cheaper model id.
- ~~`ClaudeAgentClient.cli_bin`~~ — does not exist as a class attribute (unlike
  `OpenAICodexClient.codex_bin`); `ClaudeAgentClient` only exposes a constructor-level
  `cli_path: Optional[str]` parameter, defaulted by the SDK itself. Detection must not assume
  a `cli_bin` class attribute exists symmetrically on both clients.
- ~~A hardcoded default LLM provider anywhere in `bookstore/_llm.py` or `wiki/cli.py` prior to
  this feature~~ — confirmed absent; do not "restore" a default that never existed.
- ~~`PARROT_NO_AUTO_LLM` as an existing env var~~ — does not exist yet; this spec introduces it.

---

## 7. Implementation Notes & Constraints

### Patterns to Follow

- Lazy, exception-safe checks only — mirror the `try: import <sdk>; except ImportError`
  idiom already used inside `ClaudeAgentClient`/`OpenAICodexClient`, but prefer
  `LLMFactory.list_providers()` over an actual import for Module 1 (cheaper, and sufficient).
- Never fail startup on detection or resolution failure — always degrade gracefully with a
  warning, matching the existing `except Exception: return None, None, None` pattern in
  `bookstore/_llm.py`.
- Read the opt-out env var (`PARROT_NO_AUTO_LLM`) using each call site's own existing
  convention: plain `os.environ.get` in `bookstore/_llm.py`, `_env_setting()` in `wiki/cli.py`
  — do not introduce a third, inconsistent reading path.
- Heavy imports stay lazy and, where the existing code already redirects stdout→stderr around
  them (`bookstore/_llm.py`), keep that redirect around any newly-added heavy import too.

### Known Risks / Gotchas

- **Silent-feeling behavior change on any machine with `claude`/`codex` on `PATH`.** Mitigated
  by the mandatory visible warning and the `PARROT_NO_AUTO_LLM` opt-out — do not ship the
  detection fallback without the warning; the two must land together.
- **Light/heavy provider mismatch.** `_build_triage_adapters`'s existing docstring already
  documents that `PageIndexToolkit` pairs the heavy adapter's client with the *light* model
  id internally — auto-detection for wikitoolkit must only fire when both `WIKI_MODEL` and
  `WIKI_LIGHTWEIGHT_MODEL` are unset together, and must apply one detected spec to both.
- **`OpenAICodexClient` has three backends** (`Backend = Literal["auto", "sdk", "cli"]`,
  `packages/ai-parrot-client-openai/.../codex_agent.py:29`) — its `"cli"` backend does not
  require the `openai_codex` pip package at all, only the `codex` binary on `PATH`. This is
  why Module 1 checks `shutil.which("codex")` as the decisive signal for Codex, not an SDK
  import.

### External Dependencies

None new. Detection only uses the stdlib `shutil` module and the already-existing
`LLMFactory.list_providers()`.

---

## 8. Open Questions

### Resolved (during proposal phase)

- [x] **When both `claude` and `codex` CLIs are detected, which wins by default?** —
  *Resolved in proposal*: Claude Code always wins by default.
- [x] **What should the opt-out mechanism be, and what scope should it cover?** —
  *Resolved in proposal*: one global env var, `PARROT_NO_AUTO_LLM=1`, disabling
  auto-detection for both bookstore and wikitoolkit at once.
- [x] **What model id should the Codex fallback use?** — *Resolved in proposal*: use
  `OpenAICodexClient.default_model` (`"gpt-5.1-codex"`) as-is; ship Codex detection in this
  same feature.

### Unresolved (defer to implementation)

- [ ] Exact wording of the visible warning/message text shown in each of the three call
  sites (log level for wikitoolkit's `click.echo` vs. bookstore's `logger.warning`) —
  *Owner*: implementing task. Not architecturally blocking; any phrasing that names the
  auto-selected spec and the override env var satisfies the acceptance criteria above.
- [ ] Whether a fourth `WIKI_*` LLM-resolution call site exists elsewhere in `wiki/cli.py`
  (~4300 lines; this spec's research covered the three call sites a targeted grep found) —
  *Owner*: implementing task, verify with `grep -n "LLMFactory.create\|_env_setting(\"WIKI"
  packages/ai-parrot/src/parrot/knowledge/wiki/cli.py` before closing out Module 3.

---

## Worktree Strategy

- **Isolation unit**: per-spec (single worktree, sequential tasks). This feature is small
  (one new module + two existing files touched) and every task depends on Module 1 existing
  first — no parallelism benefit from splitting.
- **Sequencing**: Module 1 (detection helper + its unit tests) must land before Module 2 and
  Module 3, since both import it. Module 2 and Module 3 touch disjoint files
  (`bookstore/_llm.py` vs. `wiki/cli.py`) and could in principle run in parallel worktrees,
  but given the small size, sequential execution in one worktree is recommended.
- **Cross-feature dependencies**: none — no other in-flight spec touches
  `bookstore/_llm.py`, `wiki/cli.py`, or `parrot/clients/factory.py`.

---

## Revision History

| Version | Date | Author | Change |
|---|---|---|---|
| 0.1 | 2026-09-06 | Claude Code (jesuslarag@gmail.com) | Initial draft, from `sdd/proposals/wikitoolkit-cli-llm-fallback.proposal.md` (FEAT-531) |
