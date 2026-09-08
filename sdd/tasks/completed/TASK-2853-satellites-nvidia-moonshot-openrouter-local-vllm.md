# TASK-2853: Satellites: ai-parrot-client-nvidia, -moonshot, -openrouter, -local, -vllm

**Feature**: FEAT-523 — PEP 420 LLM Client Extraction
**Spec**: `sdd/specs/pep-420-llm-clients.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M
**Depends-on**: TASK-2847, TASK-2848
**Assigned-to**: unassigned
**Parallel**: true — parallel: true — moves a disjoint folder set (nvidia, moonshot, openrouter, local, vllm) into new packages/ dirs; only shared file is root pyproject.toml `members` (already `packages/*` glob, no edit needed). Can run in its own worktree alongside TASK-2849..2853.

---

## Context

Spec §3 Module 4 for providers nvidia, moonshot, openrouter, local, vllm. Each folder was made self-contained by TASK-2841..2846 and discovery exists since TASK-2847, so this is a relocation: `git mv` + `pyproject.toml` + `.gitkeep`s. Satellites: `ai-parrot-client-nvidia` ← `parrot/clients/nvidia/`; `ai-parrot-client-moonshot` ← `parrot/clients/moonshot/`; `ai-parrot-client-openrouter` ← `parrot/clients/openrouter/`; `ai-parrot-client-local` ← `parrot/clients/local/`; `ai-parrot-client-vllm` ← `parrot/clients/vllm/`.

---

## Scope

- For each of nvidia, moonshot, openrouter, local, vllm: `mkdir -p packages/ai-parrot-client-<p>/src/parrot/clients && touch packages/ai-parrot-client-<p>/src/parrot/.gitkeep packages/ai-parrot-client-<p>/src/parrot/clients/.gitkeep`; `git mv packages/ai-parrot/src/parrot/clients/<p> packages/ai-parrot-client-<p>/src/parrot/clients/<p>`.
- Move that provider's tests from `packages/ai-parrot/tests/unit/clients/` (e.g. `test_<p>_*`, `tests/unit/clients/<p>/`) to `packages/ai-parrot-client-<p>/tests/unit/` with a `conftest.py` mirroring `packages/ai-parrot-embeddings/tests/`.
- Write `pyproject.toml` from the spec §7 template: `name = "ai-parrot-client-<p>"`, `version = "0.1.0"`, `dependencies = ["ai-parrot", <SDK pins from spec §2 map / §7 table>]`, one `[project.entry-points."parrot.clients"]` line per key in every client class's `provider_keys` (target `parrot.clients.<p>:<ClassName>`), `namespaces = true`, `[tool.uv.sources] ai-parrot = { workspace = true }` like the embeddings satellite.
- Remove the provider from `_IN_CORE_PROVIDERS` in `factory.py` (the entry points now register it). `uv sync` from the repo root so the workspace picks the new member up (root `members = ["packages/*"]`, no edit).
- Verify: `python -c 'import parrot.clients.<p>'`, `LLMFactory.create('<key>:x')` resolves, `LLMFactory.list_providers()['<key>'] == 'ai-parrot-client-<p>'`.

**NOT in scope**: Core extras rewrite (TASK-2854). Any code change inside the moved folder (pure `git mv`; AC-11 for meta).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot-client-<p>/ for p in (nvidia, moonshot, openrouter, local, vllm)` | CREATE | pyproject.toml, src/parrot/.gitkeep, src/parrot/clients/.gitkeep, tests/ |
| `packages/ai-parrot/src/parrot/clients/<p>/ for p in (nvidia, moonshot, openrouter, local, vllm)` | MOVE | → satellite |
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
nvidia:    NvidiaClient ("nvidia",) ; SDK: none
moonshot:  MoonshotClient ("moonshot","kimi") ; SDK: none
openrouter: OpenRouterClient ("openrouter",) ; SDK: none
local:     LocalLLMClient ("local","localllm","ollama","llamacpp") ; SDK: none
vllm:      vLLMClient ("vllm",) ; depends on parrot.clients.local → dependencies += "ai-parrot-client-local"
```

### Existing Signatures to Use
```python
# Satellite pyproject.toml skeleton — spec §7 'Satellite pyproject.toml template' (copy verbatim, fill <p>, pins, keys).
```

### Does NOT Exist
- ~~`packages/ai-parrot-client-<p>/`~~ for nvidia, moonshot, openrouter, local, vllm — do not exist yet.
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

- [ ] `packages/ai-parrot-client-<p>/` exists for nvidia, moonshot, openrouter, local, vllm with pyproject, .gitkeeps, tests; the folder is gone from core
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
7. **Move this file** to `sdd/tasks/completed/TASK-2853-satellites-nvidia-moonshot-openrouter-local-vllm.md`
8. **Update index** → `"done"`
9. **Fill in the Completion Note** below

---

## Completion Note

**Completed by**: sdd-worker (autonomous, FEAT-523 session)
**Date**: 2026-09-04
**Notes**:

Final satellite-extraction task — all 15 providers this feature covers
are now out of core. Same shape as TASK-2849/2850/2851/2852: `git mv` all
five folders (`.gitkeep` verified, no stray `__init__.py`), verified via
grep that all four single-provider satellites (nvidia/moonshot/
openrouter/local) genuinely need no extra SDK beyond `ai-parrot` itself
(each extends `OpenAIBaseClient` and uses only `tenacity`/`aiohttp`,
already core base dependencies) — no Codebase Contract correction needed,
its "SDK: none" claims verified correct. `vllm`'s `vLLMClient(LocalLLMClient)`
is a real unconditional subclass import, so `ai-parrot-client-vllm`
depends on `ai-parrot-client-local` as a genuine package dependency (with
its own `[tool.uv.sources]` entry) — this is the one satellite-to-
satellite dependency among these five.

No tests existed under `tests/unit/clients/` for any of the five (the
scattered top-level `test_nvidia_client.py`/`test_openrouter_factory.py`/
`test_localllm_client.py` stay where they are, per this feature's
established narrow-scope convention for what gets physically moved).

`factory.py`: `_IN_CORE_PROVIDERS` is now an **empty tuple** — every
provider registers via a real `parrot.clients` entry point. Left the
tuple and the transitional-walk machinery in place (not deleted), per
this task's own explicit "NOT in scope: Removing the transitional
registry (TASK-2854)".

**Cross-cutting fix wave** (the largest of this feature's four "last
provider left, so latent bugs surface" sweeps): with `_IN_CORE_PROVIDERS`
now empty, `test_factory_discovery.py`'s two tests that used to fall back
to "pick any in-core provider" (`test_list_models_active_deprecated`,
`test_list_providers_lists_in_core_keys`) had nowhere left to fall back
to — rewrote both against a mocked entry point, extending `fakes.
FakeClient` with `.models`/`.deprecated_models` for this purpose. This
also prompted a full repo-wide grep sweep for
`SUPPORTED_CLIENTS[...] is <Class>` (the pattern every one of the earlier
per-task fixes had been chasing piecemeal), which found **8 more**
instances of the same root cause: a provider's `SUPPORTED_CLIENTS` value
used to be a direct class reference (or, for a shared hand-written
`_lazy_*` closure, the same function object for every alias); now every
alias key carries its **own** `EntryPoint` (hence its own `.load` bound
method) even when multiple aliases target the same class, so raw
identity/equality comparisons against the registry value no longer work.
Fixed all 8, each with the same resolve-then-compare pattern
(`LLMFactory.create()`'s own approach):

1. `test_nvidia_client.py::test_factory_registration`
2. `test_openrouter_factory.py::test_openrouter_in_supported_clients`
3. `test_localllm_client.py::test_factory_alias_registered[local/
   localllm/ollama/llamacpp]` (the pre-existing `[vllm]` parametrize case
   — asserting the wrong class entirely, `LocalLLMClient` instead of
   `vLLMClient` — is a separate, pre-existing bug left untouched)
4. `test_factory_nova.py::test_nova_key_registered_lazy` — a **real
   regression** that slipped through TASK-2850's own verification (nova
   left core there, via the amazon satellite, but this specific test
   wasn't re-checked at the time — found now via this task's repo-wide
   sweep)
5. `test_admin_catalog.py::test_build_catalog_dedups_provider_aliases` —
   this one exposed a **real production bug**, not just a test bug:
   `server/ui/catalog.py::_dedup_llm_providers()` deduplicated
   `SUPPORTED_CLIENTS` aliases by raw value identity, which happened to
   work when aliases shared one hand-written class/closure reference but
   silently stopped deduplicating once every alias got its own
   `EntryPoint`. Fixed the helper itself (not just its test) to resolve
   each value before deduplicating.
6. `tests/clients/test_meta_client.py` — 3 parametrized alias-resolution
   assertions + 1 set-comprehension-based assertion.
7. `tests/clients/test_claude_agent.py::test_supported_clients_includes_keys`
   — imported `_lazy_claude_agent` from `factory.py`, a name that has not
   existed since TASK-2847's rewrite removed every hand-written `_lazy_*`
   closure; rewritten against `ClaudeAgentClient` directly (imported from
   `parrot.clients.anthropic`).
8. `tests/clients/test_moonshot_client.py` — 2 registration assertions.

**Evidence**:
- `uv sync --all-packages` (worktree-local `.venv`) installed all five
  satellites for real; `ai-parrot-client-vllm`'s dependency on
  `ai-parrot-client-local` resolved correctly.
- `importlib.metadata.entry_points(group="parrot.clients")` → **36 total
  keys across all 15 satellites** (the complete final set).
- `LLMFactory.create()` verified end-to-end for all five new providers,
  including `"vllm"` → `vLLMClient` (confirming the cross-satellite
  dependency resolves at runtime, not just at install time).
- Satellite suites: nvidia/moonshot/openrouter/local/vllm all 1/1 passed.
- Core `pytest packages/ai-parrot/tests/unit/clients -q` → **337/337
  passed, zero failures**. `test_core_independence.py` (3/3) confirms
  core still imports cleanly with all 15 providers blocked in
  `sys.modules` — this is the acceptance bar the whole feature was built
  toward.
- `ruff check` on every touched/created file (5 new satellites + 12
  fixed test/production files) → clean.
- Full satellite matrix re-run (all 15) → clean except the two
  already-documented pre-existing multiround failures (openai×4, groq×4),
  which moved with their test files in TASK-2849/2852 respectively.
- Server studio+handlers+admin_catalog sweep (213 tests, shared venv) →
  only the 3 pre-existing `test_meta_agent.py` failures. Pipelines sweep
  → only the 1 pre-existing `test_endcap_no_shelves_promotional.py`
  assertion failure. Crew regression smoke
  (`test_crew_ask_prompt_regression.py`) → 23/23 passed.

**Deviations from spec**: the cross-cutting fix wave (8 test files + 1
production file, `server/ui/catalog.py`) is not literally within this
task's Scope text, but — as with TASK-2852's smaller version of the same
situation — was necessary to keep "the tree... green" once the LAST
provider left `_IN_CORE_PROVIDERS`, which is precisely the condition that
made every remaining raw-identity assertion's assumption (a provider is
either a direct class or a shared closure object) finally, unavoidably
false everywhere at once. Documented here in full rather than silently
expanding scope.
