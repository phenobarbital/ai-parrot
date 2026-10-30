---
type: feature
base_branch: dev
projects: [ai-parrot-client-google, ai-parrot-integrations]
tags: [google, gemini, prompt-caching, streaming, transcriber, ledger-fix]
---

# Feature Specification: google-client-fixes

**Feature ID**: FEAT-781
**Date**: 2026-10-30
**Author**: Jesus Lara (with Claude Opus 5.5, via /sdd-fix)
**Status**: approved
**Target version**: 1.2.6

> **Source**: work-ledger group `fixgroup:5d5408571c68`, routed to the SDD lane by
> `wikitoolkit ledger plan-fix` (max_severity major). Resolves `issue:71716068e28f`,
> `issue:d34e3f558f8e` and `issue:461ceca67d43`. Parents `spec:FEAT-746` and `spec:FEAT-719` are
> closed, so this is a new feature.

---

## 1. Motivation & Business Requirements

### Problem Statement

Three independent defects in `GoogleGenAIClient` (`packages/ai-parrot-client-google/src/parrot/clients/google/client.py`),
all live on `dev` @ `ec55de512f`:

1. **Explicit CachedContent breaks `ask()`** (`issue:71716068e28f`, major). When `system_prompt` is a
   `List[CacheableSegment]` whose cacheable text reaches `_min_cache_tokens` (4096), `ask()` creates a
   `CachedContent` and sets `final_config.cached_content` (client.py:3593-3605) while the same config still
   carries `system_instruction`, `tools` and `tool_config`. Gemini rejects that with
   `400 INVALID_ARGUMENT "CachedContent can not be used with GenerateContent request setting
   system_instruction, tools or tool_config"`. Every agent whose prompt builder emits cacheable segments hits it
   — with tools (the FEAT-746 G4 live run) and without tools (`system_instruction` is always set).
2. **Stream chunks are stripped** (`issue:d34e3f558f8e`, major). `_safe_extract_text(..., is_stream_chunk=True)`
   (client.py:2743) `.strip()`s `response.text`, each `part.text` and the joined result. Streaming loses the
   whitespace at every chunk boundary and drops whitespace-only chunks: words glue together (`"thehighest"`),
   and Markdown tables collapse onto one line. `ask_stream` builds its final text from the same chunks
   (client.py:4562), so the returned `AIMessage` and the saved history are corrupted too.
3. **FEAT-719 leftovers** (`issue:461ceca67d43`, minor).
   a. `_computer_use_vocabulary` (client.py:295) returns `str`. `model-deprecation-followups.spec.md` specifies
      `Literal["legacy", "v3_8"]` (alias `ComputerUseVocabulary`).
   b. `OpenAIWhisperBackend._parse_result` (`packages/ai-parrot-integrations/src/parrot/voice/transcriber/openai_backend.py:315-317`)
      makes up a two-letter code from an unmapped language name: `"malay"` → `"ma"` (ISO `ms`), `"welsh"` →
      `"we"` (ISO `cy`). The `language_hint[:2]` fallback has the same bug for a hint like `"spanish"`.

### Goals
- `ask()` never sends a request that combines `cached_content` with `system_instruction`, `tools` or `tool_config`.
- Streamed text, joined, equals the model's text verbatim (whitespace and newlines included).
- `_computer_use_vocabulary` is typed `ComputerUseVocabulary`; the transcriber never makes up an ISO code.

### Non-Goals (explicitly out of scope)
- Reusing CachedContent across calls (today one resource is created per `ask()`; unchanged).
- Moving `tools` / `tool_config` into the CachedContent (cache churn per tool set; implicit caching covers it).
- Whitespace handling of non-stream responses (`is_stream_chunk=False` keeps stripping).
- Other clients' streaming (the issue left them unverified; not in this group).

---

## 2. Architectural Design

### Overview

**M1 — cache attach.** A new helper `_attach_gemini_cache(final_config, model, segments)` takes over the
inline block at client.py:3593-3605:
- `final_config.tools` or `final_config.tool_config` set → skip explicit caching (debug log); Gemini 2.5+/3.x
  implicit prefix caching still applies to the plain `system_instruction`.
- Otherwise create the CachedContent holding the **full** resolved `final_config.system_instruction` (cacheable +
  non-cacheable text — the request may not carry any of it), then set `cached_content` and clear
  `system_instruction`. A failed create (fail-open) leaves the config untouched.

`_maybe_apply_gemini_cache` gets an optional keyword `system_instruction: Optional[str] = None`; when given, it is
cached in place of the joined cacheable segments. The existing positional contract and its tests are unchanged.

**M2 — verbatim stream chunks.** In `_safe_extract_text`, when `is_stream_chunk=True`, return `response.text` and
the joined text parts verbatim and keep whitespace-only parts. Thought parts, function-call-only chunks and
code-execution handling are unchanged. The `is_stream_chunk=False` path is byte-for-byte unchanged.

**M3 — leftovers.** Module-level `ComputerUseVocabulary = Literal["legacy", "v3_8"]` in client.py, used as the
return type. In the transcriber, a helper `_iso_language(value)` maps a name through `_LANGUAGE_NAMES`, accepts
an ISO-looking code (`^[a-z]{2}([-_][a-z0-9]+)*$`, returned as its first two letters), and otherwise returns `None`.
Both the payload value and the `language_hint` go through it. `_LANGUAGE_NAMES` gains `malay`/`ms`,
`welsh`/`cy`, `indonesian`/`id`, `vietnamese`/`vi`, `thai`/`th`, `hungarian`/`hu`.

### Integration Points
| Existing Component | Integration Type | Notes |
|---|---|---|
| `GoogleGenAIClient.ask` | modifies | cache block → `_attach_gemini_cache` |
| `GoogleGenAIClient._maybe_apply_gemini_cache` | extends | new optional kw-only `system_instruction` |
| `GoogleGenAIClient._safe_extract_text` | modifies | stream branch only |
| `OpenAIWhisperBackend._parse_result` | modifies | language normalisation |

### Data Models / New Public Interfaces
None public. `ComputerUseVocabulary` is a module-level type alias.

---

## 3. Module Breakdown

| Module | Eligible? | Decided patterns / exact contracts | Why not (if no) |
|---|---|---|---|
| M1 | yes | §2 M1 | — |
| M2 | yes | §2 M2 | — |
| M3 | yes | §2 M3 | — |

### Module 1: Cache attach without forbidden fields — TASK-4911 (`issue:71716068e28f`)
- **Path**: `packages/ai-parrot-client-google/src/parrot/clients/google/client.py`
- **Interface Skeleton**:
  ```python
  async def _maybe_apply_gemini_cache(self, client, model: str, payload: dict, segments: list,
                                      *, system_instruction: Optional[str] = None) -> dict:
      """As today; caches ``system_instruction`` instead of the joined cacheable segments when given."""
  async def _attach_gemini_cache(self, final_config: GenerateContentConfig, model: str, segments: list) -> None:
      """Attach an explicit CachedContent to ``final_config`` in place, or skip when tools/tool_config are set."""
  ```

### Module 2: Verbatim stream chunks — TASK-4912 (`issue:d34e3f558f8e`)
- **Path**: same file, `_safe_extract_text`.

### Module 3: FEAT-719 leftovers — TASK-4913 (`issue:461ceca67d43`)
- **Paths**: client.py (`ComputerUseVocabulary`), `openai_backend.py` (`_iso_language`, `_LANGUAGE_NAMES`).

---

## 4. Test Specification

### Unit Tests
| Test | Module | Description |
|---|---|---|
| `test_attach_skips_when_tools_present` | M1 | tools set → no `caches.create`, config unchanged |
| `test_attach_skips_when_tool_config_present` | M1 | tool_config only → skipped |
| `test_attach_moves_system_instruction_into_cache` | M1 | no tools → cached text == full system_instruction; `system_instruction is None`; `cached_content` set |
| `test_attach_fail_open_keeps_system_instruction` | M1 | create raises → config untouched |
| `test_stream_chunks_join_verbatim` | M2 | the issue's 6-chunk sequence joins to the exact expected string |
| `test_stream_whitespace_only_chunk_kept` | M2 | `"\n\n"` chunk returned as-is |
| `test_non_stream_still_strips` | M2 | `is_stream_chunk=False` keeps stripping |
| `test_stream_skips_thought_parts` | M2 | thought part excluded in stream mode |
| `test_vocabulary_alias` | M3 | `get_type_hints(...)["return"] is ComputerUseVocabulary` |
| `test_iso_language_*` | M3 | malay→ms, welsh→cy, en-US→en, unknown name→None, hint `spanish`→es |

### Validation Contract

tests:
- packages/ai-parrot-client-google/tests/unit/test_google_client_fixes.py
- packages/ai-parrot/tests/test_prompt_caching_gemini.py
- packages/ai-parrot-client-google/tests/unit/test_computer_use_vocabulary.py
- packages/ai-parrot-integrations/tests/voice/transcriber/test_openai_language_codes.py
- packages/ai-parrot-integrations/tests/integrations/msteams/test_openai_whisper_backend.py
markers: none

### Test Data / Fixtures
- Stream chunks: synthetic `types.GenerateContentResponse` objects built from the issue's six-chunk sequence.
- Cache tests: a bare `GoogleGenAIClient.__new__` instance plus a `MagicMock` genai client whose
  `aio.caches.create` is an `AsyncMock` (same pattern as `test_prompt_caching_gemini.py`).

---

## 5. Acceptance Criteria
- [ ] AC-1: With tools or tool_config on the config, `ask()` makes no `caches.create` call and sends no `cached_content`.
- [ ] AC-2: Without tools, a request carrying `cached_content` has `system_instruction is None`, and the cache holds the full resolved system prompt.
- [ ] AC-3: A failed cache creation leaves `system_instruction` intact (fail-open).
- [ ] AC-4: Joining `_safe_extract_text(c, is_stream_chunk=True)` over the issue's chunks equals the expected string exactly.
- [ ] AC-5: Non-stream extraction output is unchanged.
- [ ] AC-6: `_computer_use_vocabulary` is annotated `-> ComputerUseVocabulary`.
- [ ] AC-7: The transcriber returns `ms` for "malay" and `cy` for "welsh", never `ma`/`we`; an unknown name falls back to the hint, then to `"en"`.
- [ ] AC-8: All Validation Contract tests pass; `ruff check` is clean on the changed files.

---

## 6. Codebase Contract

### Verified Imports
```python
from parrot.clients.google.client import GoogleGenAIClient          # verified: test_prompt_caching_gemini.py:12
from parrot.bots.prompts.segments import CacheableSegment           # verified: test_prompt_caching_gemini.py:11
from google.genai import types                                      # used throughout client.py
from google.genai.types import GenerateContentConfig                # used at client.py:3566
from parrot.voice.transcriber.openai_backend import OpenAIWhisperBackend, _LANGUAGE_NAMES
```

### Existing Class Signatures
```python
# client.py (dev @ ec55de512f)
from typing import Any, AsyncIterator, Dict, List, Optional, Sequence, Union  # line 2 (no Literal yet)
class GoogleGenAIClient:
    _min_cache_tokens: int = 4096                                           # line 170
    _cache_ttl: str = "300s"                                                # line 172
    def _computer_use_vocabulary(self, model: str) -> str:                  # line 295
    def _apply_cache_hints(self, payload: dict, segments: list) -> tuple:   # line 497
    async def _maybe_apply_gemini_cache(self, client, model, payload, segments) -> dict:  # line 548
    def _safe_extract_text(self, response, is_stream_chunk: bool = False) -> str:       # line 2743
    async def ask(...)                                                      # line 3237
    async def ask_stream(...)                                               # line 4169 (no explicit cache)
# openai_backend.py
_LANGUAGE_NAMES: Dict[str, str]                                             # line 27
class OpenAIWhisperBackend:
    @staticmethod
    def _parse_result(model: str, payload: dict, language_hint: Optional[str]) -> tuple[str, str, float]:  # line 290
```

### Does NOT Exist (Anti-Hallucination)
- ~~`ComputerUseVocabulary`~~ — named only in the FEAT-719 spec; not defined in code yet (M3 adds it).
- ~~`GoogleGenAIClient._attach_gemini_cache`~~ — added by M1.
- ~~`_iso_language`~~ — added by M3.
- `ask_stream` never calls `_maybe_apply_gemini_cache` — no stream-side cache fix is needed.

### Edit Sites (Blueprint Anchors)
Verified against: `ec55de512f`
| File | Action | Verbatim anchor line | Verified at | Occurrences |
|---|---|---|---|---|
| `packages/ai-parrot-client-google/src/parrot/clients/google/client.py` | MODIFY | `    def _computer_use_vocabulary(self, model: str) -> str:` | `client.py:295` | 1 |
| same | MODIFY | `    async def _maybe_apply_gemini_cache(` | `client.py:548` | 1 |
| same | MODIFY | `        if _pending_cache_segs:` | `client.py:3593` | 1 |
| same | MODIFY | `                    if text := response.text.strip():` | `client.py:2783` | 1 |
| same | MODIFY | `                        if clean_text := part.text.strip():` | `client.py:2821` | 1 |
| same | MODIFY | `                    if combined_text := "".join(text_parts).strip():` | `client.py:2852` | 1 |
| `packages/ai-parrot-integrations/src/parrot/voice/transcriber/openai_backend.py` | MODIFY | `            lang = _LANGUAGE_NAMES.get(norm) or (norm[:2] if len(norm) <= 5 else None)` | `openai_backend.py:315` | 1 |
| `packages/ai-parrot-client-google/tests/unit/test_google_client_fixes.py` | CREATE | — | — | — |
| `packages/ai-parrot-integrations/tests/voice/transcriber/test_openai_language_codes.py` | CREATE | — | — | — |

---

## 7. Implementation Notes & Constraints

### Known Risks / Gotchas
- The cache-or-not decision reads `final_config.tools` / `final_config.tool_config`, not `_use_tools`, so it
  matches exactly what gets sent.
- Caching the full system prompt includes the per-request, non-cacheable text. This is no regression: a new
  resource is already created on every call.
- The worktree's shared `.venv` is editable-installed against the main checkout: run tests with
  `PYTHONPATH=packages/ai-parrot-client-google/src:packages/ai-parrot/src:packages/ai-parrot-integrations/src`.

---

## 8. Open Questions
- [x] Tools in CachedContent vs skip? → skip (issue's second option; cache would churn per tool set).

---

## Revision History
| Version | Date | Author | Change |
|---|---|---|---|
| 0.1 | 2026-10-30 | Jesus Lara / Claude (sdd-fix) | Initial draft from ledger group `fixgroup:5d5408571c68` |
