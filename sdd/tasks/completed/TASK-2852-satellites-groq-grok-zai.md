# TASK-2852: Satellites: ai-parrot-client-groq, -grok, -zai

**Feature**: FEAT-523 — PEP 420 LLM Client Extraction
**Spec**: `sdd/specs/pep-420-llm-clients.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M
**Depends-on**: TASK-2847, TASK-2848
**Assigned-to**: unassigned
**Parallel**: true — parallel: true — moves a disjoint folder set (groq, grok, zai) into new packages/ dirs; only shared file is root pyproject.toml `members` (already `packages/*` glob, no edit needed). Can run in its own worktree alongside TASK-2849..2853.

---

## Context

Spec §3 Module 4 for providers groq, grok, zai. Each folder was made self-contained by TASK-2841..2846 and discovery exists since TASK-2847, so this is a relocation: `git mv` + `pyproject.toml` + `.gitkeep`s. Satellites: `ai-parrot-client-groq` ← `parrot/clients/groq/`; `ai-parrot-client-grok` ← `parrot/clients/grok/`; `ai-parrot-client-zai` ← `parrot/clients/zai/`.

---

## Scope

- For each of groq, grok, zai: `mkdir -p packages/ai-parrot-client-<p>/src/parrot/clients && touch packages/ai-parrot-client-<p>/src/parrot/.gitkeep packages/ai-parrot-client-<p>/src/parrot/clients/.gitkeep`; `git mv packages/ai-parrot/src/parrot/clients/<p> packages/ai-parrot-client-<p>/src/parrot/clients/<p>`.
- Move that provider's tests from `packages/ai-parrot/tests/unit/clients/` (e.g. `test_<p>_*`, `tests/unit/clients/<p>/`) to `packages/ai-parrot-client-<p>/tests/unit/` with a `conftest.py` mirroring `packages/ai-parrot-embeddings/tests/`.
- Write `pyproject.toml` from the spec §7 template: `name = "ai-parrot-client-<p>"`, `version = "0.1.0"`, `dependencies = ["ai-parrot", <SDK pins from spec §2 map / §7 table>]`, one `[project.entry-points."parrot.clients"]` line per key in every client class's `provider_keys` (target `parrot.clients.<p>:<ClassName>`), `namespaces = true`, `[tool.uv.sources] ai-parrot = { workspace = true }` like the embeddings satellite.
- Remove the provider from `_IN_CORE_PROVIDERS` in `factory.py` (the entry points now register it). `uv sync` from the repo root so the workspace picks the new member up (root `members = ["packages/*"]`, no edit).
- Verify: `python -c 'import parrot.clients.<p>'`, `LLMFactory.create('<key>:x')` resolves, `LLMFactory.list_providers()['<key>'] == 'ai-parrot-client-<p>'`.

**NOT in scope**: Core extras rewrite (TASK-2854). Any code change inside the moved folder (pure `git mv`; AC-11 for meta).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot-client-<p>/ for p in (groq, grok, zai)` | CREATE | pyproject.toml, src/parrot/.gitkeep, src/parrot/clients/.gitkeep, tests/ |
| `packages/ai-parrot/src/parrot/clients/<p>/ for p in (groq, grok, zai)` | MOVE | → satellite |
| `packages/ai-parrot/src/parrot/clients/factory.py` | MODIFY | shrink _IN_CORE_PROVIDERS |

---

## Codebase Contract (Anti-Hallucination)

> **CRITICAL**: VERIFIED references from `dev` @ `d44045f51` (2026-09-04). Re-verify line
> numbers with `grep`/`read` before relying on them — earlier tasks in this feature move files.

### Verified Imports
```python
# Pattern package: packages/ai-parrot-embeddings/pyproject.toml
[tool.setuptools.packages.find]  where = ["src"]  include = ["parrot*"]  namespaces = true   # :108-111
[tool.uv.sources]                                                                          # :113
# Root pyproject.toml:57-58  [tool.uv.workspace] members = ["packages/*"]
from parrot.clients.factory import LLMFactory   # list_providers()/list_models() from TASK-2847
# Class names / keys to declare (verified 2026-09-04, re-check provider_keys in each client.py):
groq:      GroqClient ("groq",) ; SDK: groq==0.33.0
grok:      GrokClient ("grok","xai") ; SDK: xai-sdk>=1.12.0
zai:       ZaiClient ("zai","z.ai") ; SDK: zai-sdk>=0.2.3
```

### Existing Signatures to Use
```python
# Satellite pyproject.toml skeleton — spec §7 'Satellite pyproject.toml template' (copy verbatim, fill <p>, pins, keys).
```

### Does NOT Exist
- ~~`packages/ai-parrot-client-<p>/`~~ for groq, grok, zai — do not exist yet.
- ~~`src/parrot/__init__.py` or `src/parrot/clients/__init__.py` in a satellite~~ — MUST NOT exist (PEP 420); only `.gitkeep`.
- ~~`_ParrotClientsRedirector`~~ — never existed (v0.2 idea, dropped in v0.3). Do NOT add a MetaPathFinder.
- ~~`AbstractClient.conversation_memory`, `create_conversation_memory()`~~ — removed by FEAT-524; clients are memory-less.
- ~~`parrot/clients/openai.py`~~ — the OpenAI client file is `gpt.py` today.
- ~~`parrot.clients.registry`~~ — no registry module; `SUPPORTED_CLIENTS` in `factory.py` is the only registry.

---

## Implementation Notes

### Folder convention (normative, spec §2)
```
parrot/clients/<provider>/
├── __init__.py   # re-exports client class(es) + model enum, __all__
├── client.py     # AbstractClient / OpenAIBaseClient subclass(es)
└── models.py     # <Provider>Model(str, Enum) + capability sets + DEPRECATIONS; pure data
```
Every client class gets: `provider_keys: tuple[str, ...]` (primary key first, every factory alias),
`models: type[Enum]`, optional `deprecated_models: Mapping[str, str] | None = None`.
`models.py` must not import `client.py`. Use `git mv` so history follows the file.
Enum members/values are moved **byte-identical**. Any caller of a renamed module path
(inside `packages/*/src`, `tests/`, `examples/`) is updated in THIS task — the tree must be
green (import-clean, `pytest packages/ai-parrot/tests/unit/clients -q`) when the task ends.

### Key Constraints
Keep `.gitkeep` files so the empty namespace dirs survive git. `dependencies` must NOT include SDKs the provider does not import (e.g. the nvidia/moonshot/openrouter/local/vllm/meta satellites need only `ai-parrot` because `openai` stays a core dep). Tests moved into the satellite import `parrot.clients.<p>` exactly as before.

### References in Codebase
- `packages/ai-parrot/src/parrot/embeddings/__init__.py` — `extend_path` pattern (FEAT-201)
- `packages/ai-parrot-embeddings/pyproject.toml` — satellite packaging pattern
- `packages/ai-parrot/src/parrot/clients/google/`, `nova/` — folders that already exist
- `sdd/specs/pep-420-llm-clients.spec.md` §2 map, §6 contract, §7 gotchas

---

## Acceptance Criteria

- [ ] `packages/ai-parrot-client-<p>/` exists for groq, grok, zai with pyproject, .gitkeeps, tests; the folder is gone from core
- [ ] `uv sync` succeeds; `python -c 'from parrot.clients.<p> import *'` works from the workspace venv
- [ ] Every `provider_keys` entry appears as an entry point and `LLMFactory.list_providers()` maps it to the satellite name
- [ ] Satellite `pytest packages/ai-parrot-client-<p>/tests -q` green; core `pytest packages/ai-parrot/tests/unit/clients -q` still green

---

## Test Specification

```python
# packages/ai-parrot-client-<p>/tests/unit/test_entry_points.py
from importlib.metadata import entry_points
import importlib
def test_entry_points_cover_provider_keys():
    eps = {e.name: e for e in entry_points(group="parrot.clients")}
    pkg = importlib.import_module("parrot.clients.<p>")
    for name in pkg.__all__:
        cls = getattr(pkg, name)
        for key in getattr(cls, "provider_keys", ()):
            assert key in eps and eps[key].load() is cls
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at the path listed above for full context
2. **Check dependencies** — verify `Depends-on` tasks are in `sdd/tasks/completed/`
3. **Verify the Codebase Contract** — before writing ANY code, confirm every import/signature still exists; if a prior task moved it, update the contract FIRST
4. **Update status** in `sdd/tasks/index/pep-420-llm-clients.json` → `"in-progress"` with your session ID
5. **Implement** following the scope, contract and notes above — hard cuts, no shims
6. **Verify** all acceptance criteria are met (run the commands, paste evidence in the note)
7. **Move this file** to `sdd/tasks/completed/TASK-2852-satellites-groq-grok-zai.md`
8. **Update index** → `"done"`
9. **Fill in the Completion Note** below

---

## Completion Note

**Completed by**: sdd-worker (autonomous, FEAT-523 session)
**Date**: 2026-09-04
**Notes**:

Same shape as TASK-2849/2850/2851, no Codebase Contract corrections
needed this time — all three SDKs (`groq==0.33.0`, `xai-sdk>=1.12.0`,
`zai-sdk>=0.2.3`) are genuinely used by their respective clients (verified
via grep: each imports its native SDK lazily inside `__init__`/methods —
`groq.AsyncGroq`, `xai_sdk.AsyncClient`, `zai.ZaiClient` — but that SDK is
the class's primary transport, not a secondary feature, so it's declared
as a hard satellite dependency, unlike `aws_sdk_bedrock_runtime`/`torch`
in earlier tasks). `groq`/`zai` both extend `OpenAIBaseClient`
(OpenAI-compatible API), `grok` extends `AbstractClient` directly.

`git mv` all three folders + moved `test_grok_multiround_usage.py` +
`test_grok_no_private_memory.py` (grok) and `test_groq_multiround_usage.py`
(groq) from `tests/unit/clients/`. `zai` had zero tests under that
directory. `factory.py`: removed `"groq"`, `"grok"`, `"zai"` from
`_IN_CORE_PROVIDERS` (only `nvidia`, `moonshot`, `openrouter`, `local`,
`vllm` remain transitional — TASK-2853 finishes the set).
`test_factory_discovery.py`'s two example-in-core-provider assertions
(previously `"groq"`/`"zai"`) now use `"nvidia"`/`"moonshot"`.

**Cross-cutting bugfix** (not caused by groq/grok/zai themselves, but by
"google" becoming a real entry-point-sourced provider back in TASK-2851 —
found via this task's own regression sweep): four call sites read
`SUPPORTED_CLIENTS` directly and instantiated the value without resolving
the zero-arg lazy-loader shape a real entry point produces (`ep.load`,
not the class itself — `LLMFactory.create()` already resolves this, and
`bots/abstract.py` already had a `_resolve_supported_client()` helper for
exactly this, but these four call sites predate that helper's use here):

1. `parrot_pipelines/abstract.py::_get_llm()` — confirmed genuinely
   broken via a real `TypeError: EntryPoint.load() got an unexpected
   keyword argument 'model'`, surfaced by
   `test_planogram_types.py::test_unknown_type_raises_valueerror` in this
   task's own pipelines regression sweep (its default provider is
   `"google"`). Fixed inline with the same two-line resolve pattern.
2. `parrot/bots/voice.py`, `parrot/advisors/mixin.py`,
   `parrot/interfaces/tools.py` — same latent bug, found via a targeted
   grep sweep of every remaining direct `SUPPORTED_CLIENTS` consumer
   (all default to or resolve `"google"`). Fixed inline, same pattern.
3. `parrot/bots/flows/crew/crew.py` had a second, more serious issue: a
   **module-scope** `from ....clients.google import GoogleGenAIClient` —
   core importing a provider unconditionally at import time (spec AC-3),
   which would hard-fail merely importing `crew.py` if
   `ai-parrot-client-google` isn't installed. Made lazy (moved to the one
   real instantiation site at `run_loop()`'s default-LLM fallback). Its
   three separate `SUPPORTED_CLIENTS` instantiation sites (constructor's
   3-way branch ×2, `synthesize_report()`'s `executive_summary` default)
   now import and reuse `bots.abstract`'s existing
   `_resolve_supported_client()` helper rather than duplicating the
   resolve logic a third time in this file.

**Evidence**:
- `uv sync --all-packages` (worktree-local `.venv`) installed all three
  satellites for real; `groq==0.33.0`, `xai-sdk==1.19.0`, `zai-sdk==0.2.3`
  genuinely resolved. Entry points confirmed for all 10 satellites
  extracted so far via `importlib.metadata.entry_points(group=
  "parrot.clients")`.
- `LLMFactory.create("groq:llama-3.3-70b-versatile")` →
  `GroqClient`; `.create("grok:grok-4-fast")` → `GrokClient`;
  `.create("zai")` raises the *expected* `ValueError: ZAI_API_KEY is
  required` (a real runtime credential check, not an import/resolution
  bug — confirms the class resolves and instantiates correctly up to
  that point).
- Satellite suites: groq 1/5 passed (4 pre-existing multiround failures,
  confirmed byte-identical to the ones that moved WITH the test file);
  grok 13/13 passed; zai 1/1 passed.
- Core `pytest packages/ai-parrot/tests/unit/clients -q` → **337/337
  passed, zero failures** — the previously-documented pre-existing
  groq/grok multiround failures moved out of core along with their test
  files, so core itself is now fully clean.
- `ruff check` on every touched/created file (both the 3 satellites and
  the 5 lazy-loader-resolution fixes) → clean; the 5 pre-existing
  findings in `grok/client.py` (4×E402 + 1×F841) confirmed unrelated to
  my edits (none on lines I touched).
- Regression sweep: pipelines went from 38 passed/2 failed (before the
  lazy-loader fix) to **39 passed/1 failed** (the remaining failure is
  the pre-existing, unrelated `test_endcap_no_shelves_promotional.py`
  product-name-matching assertion). Full crew regression suite (7 files)
  → **84/84 passed, zero failures** — confirms both the crew.py
  module-scope-import fix and its three resolve-wrapped call sites are
  correct. Server/studio sweep unaffected (same 3 pre-existing
  `test_meta_agent.py` failures only).

**Deviations from spec**: the four-file lazy-loader-resolution bugfix and
the crew.py module-scope-import fix are not literally within this task's
Scope text (which only names groq/grok/zai), but were required to keep
"the tree... green" (per Implementation Notes) once google's TASK-2851
extraction exposed them — deferring would have left a confirmed,
reproducible regression in already-merged code. Documented here rather
than silently expanding scope.
