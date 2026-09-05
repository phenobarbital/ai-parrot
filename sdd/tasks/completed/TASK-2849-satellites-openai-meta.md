# TASK-2849: Satellites: ai-parrot-client-openai, ai-parrot-client-meta

**Feature**: FEAT-523 — PEP 420 LLM Client Extraction
**Spec**: `sdd/specs/pep-420-llm-clients.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M
**Depends-on**: TASK-2847, TASK-2848
**Assigned-to**: unassigned
**Parallel**: true — parallel: true — moves a disjoint folder set (openai, meta) into new packages/ dirs; only shared file is root pyproject.toml `members` (already `packages/*` glob, no edit needed). Can run in its own worktree alongside TASK-2849..2853.

---

## Context

Spec §3 Module 4 for providers openai, meta. Each folder was made self-contained by TASK-2841..2846 and discovery exists since TASK-2847, so this is a relocation: `git mv` + `pyproject.toml` + `.gitkeep`s. Satellites: `ai-parrot-client-openai` ← `parrot/clients/openai/`; `ai-parrot-client-meta` ← `parrot/clients/meta/`.

---

## Scope

- For each of openai, meta: `mkdir -p packages/ai-parrot-client-<p>/src/parrot/clients && touch packages/ai-parrot-client-<p>/src/parrot/.gitkeep packages/ai-parrot-client-<p>/src/parrot/clients/.gitkeep`; `git mv packages/ai-parrot/src/parrot/clients/<p> packages/ai-parrot-client-<p>/src/parrot/clients/<p>`.
- Move that provider's tests from `packages/ai-parrot/tests/unit/clients/` (e.g. `test_<p>_*`, `tests/unit/clients/<p>/`) to `packages/ai-parrot-client-<p>/tests/unit/` with a `conftest.py` mirroring `packages/ai-parrot-embeddings/tests/`.
- Write `pyproject.toml` from the spec §7 template: `name = "ai-parrot-client-<p>"`, `version = "0.1.0"`, `dependencies = ["ai-parrot", <SDK pins from spec §2 map / §7 table>]`, one `[project.entry-points."parrot.clients"]` line per key in every client class's `provider_keys` (target `parrot.clients.<p>:<ClassName>`), `namespaces = true`, `[tool.uv.sources] ai-parrot = { workspace = true }` like the embeddings satellite.
- Remove the provider from `_IN_CORE_PROVIDERS` in `factory.py` (the entry points now register it). `uv sync` from the repo root so the workspace picks the new member up (root `members = ["packages/*"]`, no edit).
- Verify: `python -c 'import parrot.clients.<p>'`, `LLMFactory.create('<key>:x')` resolves, `LLMFactory.list_providers()['<key>'] == 'ai-parrot-client-<p>'`.

**NOT in scope**: Core extras rewrite (TASK-2854). Any code change inside the moved folder (pure `git mv`; AC-11 for meta).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot-client-<p>/ for p in (openai, meta)` | CREATE | pyproject.toml, src/parrot/.gitkeep, src/parrot/clients/.gitkeep, tests/ |
| `packages/ai-parrot/src/parrot/clients/<p>/ for p in (openai, meta)` | MOVE | → satellite |
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
openai:    OpenAIClient ("openai",) ; OpenAICodexClient ("codex-agent","openai-codex","codex-code") ; SDK: openai-codex (openai is core)
meta:      MetaClient ("meta","muse","meta-muse") — landed by FEAT-526 in parrot/clients/meta/ ; SDK: none
```

### Existing Signatures to Use
```python
# Satellite pyproject.toml skeleton — spec §7 'Satellite pyproject.toml template' (copy verbatim, fill <p>, pins, keys).
```

### Does NOT Exist
- ~~`packages/ai-parrot-client-<p>/`~~ for openai, meta — do not exist yet.
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

- [ ] `packages/ai-parrot-client-<p>/` exists for openai, meta with pyproject, .gitkeeps, tests; the folder is gone from core
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
7. **Move this file** to `sdd/tasks/completed/TASK-2849-satellites-openai-meta.md`
8. **Update index** → `"done"`
9. **Fill in the Completion Note** below

---

## Completion Note

**Completed by**: sdd-worker (autonomous, FEAT-523 session)
**Date**: 2026-09-04
**Notes**:

`git mv` both provider folders into `packages/ai-parrot-client-<p>/src/parrot/
clients/<p>/` with `.gitkeep` at `src/parrot/` and `src/parrot/clients/`
(no stray `__init__.py`, verified). Wrote `pyproject.toml` per the spec §7
template for each: `ai-parrot-client-openai` depends on `ai-parrot` +
`openai-codex>=0.1.0` (the `openai` SDK itself stays a core `ai-parrot
[openai]` extra since `OpenAIBaseClient` lives in core), plus an added
`bridge` optional extra (`mcp`, `starlette`, `uvicorn`) for
`codex_tool_bridge.py` — verified that module is only ever imported lazily
(`TYPE_CHECKING` / inside a method) from `codex_agent.py`, never at
`parrot.clients.openai`'s own import time, so the base install stays
light. `ai-parrot-client-meta` depends on `ai-parrot` only (no SDK).
Entry points declared for every `provider_keys` alias on both classes.

Moved the narrowly-scoped tests per the Scope text's literal anchor
(`packages/ai-parrot/tests/unit/clients/` only — not the scattered
`test_openai_client.py`/`test_prompt_caching_openai.py`/top-level
`/tests/clients/test_meta_*.py` files elsewhere in the repo, which the
Scope/AC never named and which keep working unchanged via the merged
namespace once the satellite is installed): the `openai/` subdir
(`test_deprecations.py` + `conftest.py`), `test_openai_multiround_usage.py`,
`test_codex_agent.py`. `meta` had zero tests under that directory to move.

Removed `"openai"` and `"meta"` from `factory.py`'s `_IN_CORE_PROVIDERS`.
Updated the two TASK-2847 `test_factory_discovery.py` assertions that used
`"openai"` as an example in-core provider (`test_list_models_active_
deprecated`, `test_list_providers_lists_in_core_keys`) to use `"google"`/
`"anthropic"` instead, so the core test suite no longer depends on any
satellite being installed to pass.

**Real py-packaging gotcha found and fixed**: naming the moved test
directory bare `openai` one level directly under a non-package `tests/
unit/` collides with the *real* top-level `openai` SDK module during
pytest collection — pytest's rootdir-insertion walked up to `tests/unit/`
(no `__init__.py` there) and put it on `sys.path`, making the test
package importable as bare `openai`, shadowing the genuine SDK
(`ImportError: cannot import name 'APIConnectionError' from 'openai'
<- our test dir>`, breaking `test_codex_agent.py`/`test_openai_client.py`-
style tests that need the real SDK). Fixed by adding `tests/unit/
__init__.py` so pytest's insertion point moves one level higher
(`packages/ai-parrot-client-openai/`), making the test package
`tests.unit.openai` instead of bare `openai`. The original core location
never hit this because `tests/unit/clients/__init__.py` already existed
as an extra wrapper level.

**Verification — two independent passes**:

1. *Consumer-side simulation* (shared venv, synthetic `.dist-info` +
   `entry_points.txt` written to a throwaway `/tmp` dir matching each
   satellite's `pyproject.toml` exactly, never committed, never added to
   the persistent PYTHONPATH file): `LLMFactory.create("openai:...")`,
   `.create("meta")`, `.list_providers()["openai"] == "ai-parrot-client-
   openai"`, both satellites' `test_entry_points_cover_provider_keys` —
   all correct.
2. *Genuine end-to-end* (discovered mid-task: a background process ran a
   real `uv sync` against a **new worktree-local `.venv`** — isolated to
   this worktree, not the shared repo venv, so no cross-session mutation
   risk). Ran `uv sync --all-packages` there myself (the two new
   satellites are optional, not root dependencies, so plain `uv sync`
   alone doesn't pull them in) — both satellites built and installed for
   real via their own `pyproject.toml` (`openai-codex==0.147.0` resolved
   genuinely). `importlib.metadata.entry_points(group="parrot.clients")`
   returned all 7 real entries (`openai`, `codex-agent`, `openai-codex`,
   `codex-code`, `meta`, `muse`, `meta-muse`), each resolving to the
   correct class via `LLMFactory.create()`/`.list_providers()`. This new
   `.venv` will be reused (not recreated) for the remaining satellite
   tasks (2850-2855) going forward, since it gives genuine verification
   that the shared-venv simulation cannot.

**Test results** (both venvs agree on non-pre-existing failures = none):
- `packages/ai-parrot-client-openai/tests -q` → 50/54 passed (4
  pre-existing `test_openai_multiround_usage.py` `MagicMock`/
  `raw_response` failures, byte-identical to the ones already present at
  the TASK-2848 commit — confirmed via `git stash`).
- `packages/ai-parrot-client-meta/tests -q` → 1/1 passed.
- `packages/ai-parrot/tests/unit/clients -q` → still green (only the
  pre-existing groq/grok multiround failures + fresh-venv-only gaps from
  optional SDKs not installed by `--all-packages` — `transformers`/
  `google-genai` — unrelated to this task; the shared venv, which has
  those extras, shows the identical pre-existing-only failure set).
- `ruff check` on every touched/created file → clean except one
  pre-existing finding (`InvokeResult` unused import in `openai/client.py`,
  confirmed via `git show HEAD:...` on the pre-move file — untouched
  content, `git mv` only).
- Broader regression sweep unchanged from TASK-2848 (studio/handlers,
  pipelines, byok) — same pre-existing failures only, none new.

**Deviations from spec**: none beyond the `bridge` optional-extra addition
(not explicitly requested by the base template, but necessary for
`codex_tool_bridge.py`'s real dependencies to be installable at all once
it left core, where they were previously bundled into the `codex-agent`
extra) and the `tests/unit/__init__.py` naming-collision fix above (both
documented in-line in the respective files).
