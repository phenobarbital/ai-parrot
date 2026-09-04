# TASK-2850: Satellites: ai-parrot-client-anthropic, ai-parrot-client-amazon

**Feature**: FEAT-523 — PEP 420 LLM Client Extraction
**Spec**: `sdd/specs/pep-420-llm-clients.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M
**Depends-on**: TASK-2847, TASK-2848
**Assigned-to**: unassigned
**Parallel**: true — parallel: true — moves a disjoint folder set (anthropic, amazon) into new packages/ dirs; only shared file is root pyproject.toml `members` (already `packages/*` glob, no edit needed). Can run in its own worktree alongside TASK-2849..2853.

---

## Context

Spec §3 Module 4 for providers anthropic, amazon. Each folder was made self-contained by TASK-2841..2846 and discovery exists since TASK-2847, so this is a relocation: `git mv` + `pyproject.toml` + `.gitkeep`s. Satellites: `ai-parrot-client-anthropic` ← `parrot/clients/anthropic/`; `ai-parrot-client-amazon` ← `parrot/clients/amazon/`.

---

## Scope

- For each of anthropic, amazon: `mkdir -p packages/ai-parrot-client-<p>/src/parrot/clients && touch packages/ai-parrot-client-<p>/src/parrot/.gitkeep packages/ai-parrot-client-<p>/src/parrot/clients/.gitkeep`; `git mv packages/ai-parrot/src/parrot/clients/<p> packages/ai-parrot-client-<p>/src/parrot/clients/<p>`.
- Move that provider's tests from `packages/ai-parrot/tests/unit/clients/` (e.g. `test_<p>_*`, `tests/unit/clients/<p>/`) to `packages/ai-parrot-client-<p>/tests/unit/` with a `conftest.py` mirroring `packages/ai-parrot-embeddings/tests/`.
- Write `pyproject.toml` from the spec §7 template: `name = "ai-parrot-client-<p>"`, `version = "0.1.0"`, `dependencies = ["ai-parrot", <SDK pins from spec §2 map / §7 table>]`, one `[project.entry-points."parrot.clients"]` line per key in every client class's `provider_keys` (target `parrot.clients.<p>:<ClassName>`), `namespaces = true`, `[tool.uv.sources] ai-parrot = { workspace = true }` like the embeddings satellite.
- Remove the provider from `_IN_CORE_PROVIDERS` in `factory.py` (the entry points now register it). `uv sync` from the repo root so the workspace picks the new member up (root `members = ["packages/*"]`, no edit).
- Verify: `python -c 'import parrot.clients.<p>'`, `LLMFactory.create('<key>:x')` resolves, `LLMFactory.list_providers()['<key>'] == 'ai-parrot-client-<p>'`.

**NOT in scope**: Core extras rewrite (TASK-2854). Any code change inside the moved folder (pure `git mv`; AC-11 for meta).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot-client-<p>/ for p in (anthropic, amazon)` | CREATE | pyproject.toml, src/parrot/.gitkeep, src/parrot/clients/.gitkeep, tests/ |
| `packages/ai-parrot/src/parrot/clients/<p>/ for p in (anthropic, amazon)` | MOVE | → satellite |
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
anthropic: AnthropicClient ("claude","anthropic","bedrock","anthropic-aws") ; ClaudeAgentClient ("claude-agent","claude-code") ; SDK: anthropic[aiohttp,aws]>=0.109.0,<1.0.0, claude-agent-sdk>=0.1.68
amazon:    BedrockConverseClient ("bedrock-converse",) ; NovaClient ("nova",) ; BedrockMantleClient ("bedrock-mantle","mantle") ; SDK: aioboto3>=13.2.0, anthropic[aiohttp,aws], aws_sdk_bedrock_runtime
```

### Existing Signatures to Use
```python
# Satellite pyproject.toml skeleton — spec §7 'Satellite pyproject.toml template' (copy verbatim, fill <p>, pins, keys).
```

### Does NOT Exist
- ~~`packages/ai-parrot-client-<p>/`~~ for anthropic, amazon — do not exist yet.
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

- [ ] `packages/ai-parrot-client-<p>/` exists for anthropic, amazon with pyproject, .gitkeeps, tests; the folder is gone from core
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
7. **Move this file** to `sdd/tasks/completed/TASK-2850-satellites-anthropic-amazon.md`
8. **Update index** → `"done"`
9. **Fill in the Completion Note** below

---

## Completion Note

**Completed by**: sdd-worker (autonomous, FEAT-523 session)
**Date**: 2026-09-04
**Notes**:

Same shape as TASK-2849. `git mv` both provider folders (amazon's `nova/`
subdir moved whole) with `.gitkeep` markers; no stray `__init__.py`
verified. `pyproject.toml` per satellite per the spec §7 template.

**Contract correction**: the Codebase Contract's line 56 claimed "amazon:
... SDK: aioboto3>=13.2.0, anthropic[aiohttp,aws], aws_sdk_bedrock_runtime"
— verified this against the actual code and it's backwards. `grep -rn
"anthropic" packages/.../amazon/` shows zero `import anthropic` anywhere;
every hit is a Bedrock model-ID string literal (`"anthropic.claude-..."`).
The real cross-satellite dependency is the other direction:
`anthropic/backends.py:175` does a lazy (in-method, not module-scope)
`from parrot.clients.amazon.models import translate` for the Bedrock
backend. So: `ai-parrot-client-amazon`'s `dependencies` = `["ai-parrot",
"aioboto3>=13.2.0"]` only; `ai-parrot-client-anthropic`'s pyproject has a
comment noting the soft/lazy dependency on `ai-parrot-client-amazon` for
its Bedrock backend (left undeclared, same treatment as the pre-existing
undeclared `aws_sdk_bedrock_runtime`).

Moved `test_claude_multiround_usage.py` (anthropic) and
`test_bedrock_format_history.py`/`test_bedrock_multiround_usage.py`
(amazon) from `tests/unit/clients/` — verified each file's actual import
target first (`test_bedrock_*` import `parrot.clients.amazon.bedrock`/
`.nova`, not anthropic's own Bedrock backend, despite the shared
"bedrock" name). No `tests/unit/clients/anthropic/` or `/amazon/` subdirs
existed to move.

`factory.py`: removed `"anthropic"` and `"amazon"` from
`_IN_CORE_PROVIDERS`. Updated `test_factory_discovery.py`'s
`test_list_providers_lists_in_core_keys` (previously asserted
`"anthropic"`, now uses `"groq"`, still genuinely in-core).

**Verification** — reused the worktree-local `.venv` discovered mid-TASK-2849
(a background process's `uv sync` created it; confirmed isolated to this
worktree, not the shared repo venv). `uv sync --all-packages` picked up
both new satellites automatically (workspace `members = ["packages/*"]`
glob, no edit needed). Real `importlib.metadata.entry_points(group=
"parrot.clients")` now returns all 4 satellites extracted so far (7
openai/meta keys + 6 anthropic/amazon keys = 13 total), each resolving via
`LLMFactory.create()`/`.list_providers()` to the correct class and
distribution name. `packages/ai-parrot-client-anthropic/tests -q` → 5/5
passed; `packages/ai-parrot-client-amazon/tests -q` → 21/21 passed.
`packages/ai-parrot/tests/unit/clients -q` (both this fresh venv with
missing optional SDKs reinstalled, and the shared venv) → only the
pre-existing groq/grok multiround `MagicMock`/`raw_response` failures,
confirmed byte-identical to TASK-2849's commit. `ruff check` on every
touched/created file → all clean (`All checks passed!`). Broader
server/studio + pipelines regression sweep (shared venv) → same
pre-existing failures only (`test_meta_agent.py` × 3,
`test_endcap_no_shelves_promotional.py` × 1), none new.

**Deviations from spec**: none beyond the Codebase Contract direction
correction documented above (a factual correction verified against code,
not a design change) and the cross-satellite soft-dependency comment in
`ai-parrot-client-anthropic/pyproject.toml` (documentation only, no new
hard dependency added).

**Process note**: `git commit -m "..."` with backticks inside the message
triggers bash command substitution even inside double quotes — one
sentence referencing `` `import anthropic` `` got silently eaten mid-commit
(harmless "command not found" side effects, but a mangled message). Fixed
via `git commit --amend -F <file>`. Will use `-F <file>` for any future
commit message containing backticks.
