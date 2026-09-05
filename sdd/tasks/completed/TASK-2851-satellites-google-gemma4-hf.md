# TASK-2851: Satellites: ai-parrot-client-google, -gemma4, -hf

**Feature**: FEAT-523 — PEP 420 LLM Client Extraction
**Spec**: `sdd/specs/pep-420-llm-clients.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M
**Depends-on**: TASK-2847, TASK-2848
**Assigned-to**: unassigned
**Parallel**: true — parallel: true — moves a disjoint folder set (google, gemma4, hf) into new packages/ dirs; only shared file is root pyproject.toml `members` (already `packages/*` glob, no edit needed). Can run in its own worktree alongside TASK-2849..2853.

---

## Context

Spec §3 Module 4 for providers google, gemma4, hf. Each folder was made self-contained by TASK-2841..2846 and discovery exists since TASK-2847, so this is a relocation: `git mv` + `pyproject.toml` + `.gitkeep`s. Satellites: `ai-parrot-client-google` ← `parrot/clients/google/`; `ai-parrot-client-gemma4` ← `parrot/clients/gemma4/`; `ai-parrot-client-hf` ← `parrot/clients/hf/`.

---

## Scope

- For each of google, gemma4, hf: `mkdir -p packages/ai-parrot-client-<p>/src/parrot/clients && touch packages/ai-parrot-client-<p>/src/parrot/.gitkeep packages/ai-parrot-client-<p>/src/parrot/clients/.gitkeep`; `git mv packages/ai-parrot/src/parrot/clients/<p> packages/ai-parrot-client-<p>/src/parrot/clients/<p>`.
- Move that provider's tests from `packages/ai-parrot/tests/unit/clients/` (e.g. `test_<p>_*`, `tests/unit/clients/<p>/`) to `packages/ai-parrot-client-<p>/tests/unit/` with a `conftest.py` mirroring `packages/ai-parrot-embeddings/tests/`.
- Write `pyproject.toml` from the spec §7 template: `name = "ai-parrot-client-<p>"`, `version = "0.1.0"`, `dependencies = ["ai-parrot", <SDK pins from spec §2 map / §7 table>]`, one `[project.entry-points."parrot.clients"]` line per key in every client class's `provider_keys` (target `parrot.clients.<p>:<ClassName>`), `namespaces = true`, `[tool.uv.sources] ai-parrot = { workspace = true }` like the embeddings satellite.
- Remove the provider from `_IN_CORE_PROVIDERS` in `factory.py` (the entry points now register it). `uv sync` from the repo root so the workspace picks the new member up (root `members = ["packages/*"]`, no edit).
- Verify: `python -c 'import parrot.clients.<p>'`, `LLMFactory.create('<key>:x')` resolves, `LLMFactory.list_providers()['<key>'] == 'ai-parrot-client-<p>'`.

**NOT in scope**: Core extras rewrite (TASK-2854). Any code change inside the moved folder (pure `git mv`; AC-11 for meta).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot-client-<p>/ for p in (google, gemma4, hf)` | CREATE | pyproject.toml, src/parrot/.gitkeep, src/parrot/clients/.gitkeep, tests/ |
| `packages/ai-parrot/src/parrot/clients/<p>/ for p in (google, gemma4, hf)` | MOVE | → satellite |
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
google:    GoogleGenAIClient ("google",) ; GeminiLiveClient ("gemini-live",) ; SDK: google-genai>=2.18.1 (+ google-api-python-client, google-cloud-texttospeech per spec map)
gemma4:    Gemma4Client ("gemma4",) ; SDK: transformers>=4.48.0,<5.0, torch
hf:        TransformersClient ("hf","transformers") ; SDK: transformers>=4.48.0,<5.0, sentence-transformers
```

### Existing Signatures to Use
```python
# Satellite pyproject.toml skeleton — spec §7 'Satellite pyproject.toml template' (copy verbatim, fill <p>, pins, keys).
```

### Does NOT Exist
- ~~`packages/ai-parrot-client-<p>/`~~ for google, gemma4, hf — do not exist yet.
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

- [ ] `packages/ai-parrot-client-<p>/` exists for google, gemma4, hf with pyproject, .gitkeeps, tests; the folder is gone from core
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
7. **Move this file** to `sdd/tasks/completed/TASK-2851-satellites-google-gemma4-hf.md`
8. **Update index** → `"done"`
9. **Fill in the Completion Note** below

---

## Completion Note

**Completed by**: sdd-worker (autonomous, FEAT-523 session)
**Date**: 2026-09-04
**Notes**:

Same shape as TASK-2849/2850. `git mv` all three provider folders
(google's `analysis.py`/`generation.py` — not individually named in the
Codebase Contract but part of the same folder — moved with it); no stray
`__init__.py` verified for any of the three.

**Contract corrections** (verified against actual code, same pattern as
TASK-2850's amazon/anthropic direction fix):

1. **google**: the Codebase Contract listed "SDK: google-genai>=2.18.1
   (+ google-api-python-client, google-cloud-texttospeech per spec map)".
   `grep -rn "from google\|import google" parrot/clients/google/*.py`
   shows only `google.genai`/`google.oauth2`/`google.auth` — never
   `googleapiclient`/`texttospeech`/`aiplatform`. Those three extra SDKs
   back OTHER core Google integrations (Calendar/Sheets/TTS tools),
   unrelated to this LLM client. Declared `google-genai>=2.18.1` only.
2. **gemma4/hf**: the Codebase Contract listed "transformers>=4.48.0,<5.0,
   torch" (gemma4) and "transformers>=4.48.0,<5.0, sentence-transformers"
   (hf). Spec §7's own External Dependencies table lists only
   `transformers` for both — the more authoritative, formal source.
   Verified via grep: both import `torch` lazily inside methods only (a
   pre-existing "avoid heavy deps until used" comment/pattern, unchanged
   by this pure `git mv`); neither imports `sentence-transformers`
   anywhere (that package backs the unrelated `ai-parrot-embeddings
   [huggingface]` extra). Declared `transformers>=4.48.0,<5.0` only for
   both, per the Key Constraint's explicit "must NOT include SDKs the
   provider does not import".

Moved `test_gemini_multiround_usage.py` + `test_google_format_history.py`
(both confirmed via import-line grep to target `parrot.clients.google`)
into the google satellite. No `tests/unit/clients/gemma4/` or `/hf/`
files existed to move for those two.

`factory.py`: removed `"google"`, `"gemma4"`, `"hf"` from
`_IN_CORE_PROVIDERS`. Updated `test_factory_discovery.py`'s two
example-in-core-provider assertions (previously `"google"`, extracted now)
to `"groq"`/`"zai"`.

**Verification**: `uv sync --all-packages` (worktree-local `.venv`,
reused across TASK-2849/2850/2851) built and installed all three new
satellites. Real entry points now cover all 7 satellites extracted so
far (14 provider keys total): `openai, codex-agent, openai-codex,
codex-code, meta, muse, meta-muse, anthropic, claude, bedrock,
anthropic-aws, claude-agent, claude-code, bedrock-converse, nova,
bedrock-mantle, mantle, google, gemini-live, gemma4, hf, transformers`.
`LLMFactory.create("google:gemini-2.5-flash")` resolves correctly.
Satellite suites: google 12/12, gemma4 1/1, hf 1/1, all green.
`transformers` genuinely installed via the satellite dependency (not
`torch`) and `test_folder_convention.py`'s `[hf]`/`[gemma4]` rows pass
without `torch` present — confirms the "leave torch undeclared" call is
sound for what these tests actually check. `ruff check` on every new/
touched file → only pre-existing findings in `hf/client.py` (F821 `torch`
quoted-annotation, F841 `turn_id`), confirmed via `diff` against the
pre-move committed content to be byte-for-byte unchanged. Core clients
unit suite (worktree venv, `transformers` genuinely present, `google-genai`
not needed anymore since google left core) → only the pre-existing
grok/groq multiround failures. Broader server/studio + pipelines
regression sweep (shared venv, PYTHONPATH updated with the 3 new
satellite `src/` dirs) → same pre-existing failures only
(`test_meta_agent.py` × 3, `test_endcap_no_shelves_promotional.py` × 1,
`test_planogram_types.py::test_unknown_type_raises_valueerror` × 1 — all
confirmed via `git stash` to predate this task).

**Deviations from spec**: none beyond the two Codebase Contract
corrections above (factual corrections verified against code and the
spec's own more-authoritative §7 table, not design changes).
