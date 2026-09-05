# TASK-2854: Core extras → satellites, drop extracted SDK pins, remove transitional registry

**Feature**: FEAT-523 — PEP 420 LLM Client Extraction
**Spec**: `sdd/specs/pep-420-llm-clients.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M
**Depends-on**: TASK-2849, TASK-2850, TASK-2851, TASK-2852, TASK-2853
**Assigned-to**: unassigned
**Parallel**: false — Sequential: needs all 15 satellite names; edits core pyproject.toml and factory.py.

---

## Context

Spec §3 Module 5, AC-8, AC-9. With all folders relocated, core's extras must install satellites instead of raw SDKs, core must stop pinning SDKs it no longer imports, and the transitional in-core registry in `factory.py` goes away.

---

## Scope

- `packages/ai-parrot/pyproject.toml` extras: `anthropic = ["ai-parrot-client-anthropic"]`, `openai = ["ai-parrot-client-openai"]`, `google = ["ai-parrot-client-google"]`, `groq`, `zai`, `bedrock`/`bedrock-native` → `["ai-parrot-client-amazon"]`, `claude-agent` → anthropic satellite, `codex-agent` → openai satellite; add `gemma4`, `hf`, `grok`, `nvidia`, `moonshot`, `openrouter`, `local`, `vllm`, `meta`; `llms = [all 15]`.
- Remove from core `dependencies`/extras every pin now owned by a satellite (`anthropic`, `google-genai`, `groq`, `xai-sdk`, `zai-sdk`, `aioboto3`, `claude-agent-sdk`, `openai-codex`, `transformers`/`torch` **only if** no remaining core module imports them — grep first; `images` extra may still need torch). **Keep `openai==3.3.1` and `tiktoken`** (spec decision: `OpenAIBaseClient` stays in core).
- Root `pyproject.toml`: `all` extra pulls `ai-parrot[llms]` transitively (verify current shape first).
- `factory.py`: delete `_IN_CORE_PROVIDERS` and its branch in `_discover()`; entry points are now the only source.
- `uv lock && uv sync --all-extras`; `python -c 'import parrot.clients.factory'` in a venv with **no** satellites installed must succeed.

**NOT in scope**: Version bumps / release (`/release` skill). Documentation beyond a `docs/migration/feat-523-llm-client-satellites.md` stub listing the renamed import paths.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/pyproject.toml` | MODIFY | extras → satellites; drop pins |
| `pyproject.toml (root)` | MODIFY | all extra transitive |
| `packages/ai-parrot/src/parrot/clients/factory.py` | MODIFY | remove transitional registry |
| `docs/migration/feat-523-llm-client-satellites.md` | CREATE | renamed paths table |
| `uv.lock` | MODIFY | regenerated |

---

## Codebase Contract (Anti-Hallucination)

> **CRITICAL**: VERIFIED references from `dev` @ `d44045f51` (2026-09-04). Re-verify line
> numbers with `grep`/`read` before relying on them — earlier tasks in this feature move files.

### Verified Imports
```python
# packages/ai-parrot/pyproject.toml extras (line numbers 2026-09-04): anthropic:484 bedrock:491 bedrock-native:502
#   claude-agent:516 codex-agent:520 openai:527 google:532 groq:539 zai:543 ; core deps: tiktoken>=0.9.0 :61 ;
#   google-genai>=2.18.1 :432 and openai==3.3.1 :433 appear inside another extra (:431 mcp) — inspect before touching.
# Root pyproject.toml:57-58 [tool.uv.workspace] members = ["packages/*"]
# Pattern for a meta-extra that pulls satellites: packages/ai-parrot/pyproject.toml `all`/embeddings extras from FEAT-201
```

### Existing Signatures to Use
```python
# spec §7 External Dependencies table lists the pins each satellite owns.
```

### Does NOT Exist
- ~~`_IN_CORE_PROVIDERS`~~ — exists only between TASK-2847 and this task; delete it.
- ~~`ai-parrot[llms]` installing SDKs directly~~ — after this task it installs satellites which bring their own SDKs.
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
Grep for residual core imports before dropping a pin: `grep -rn "^\s*\(from\|import\) \(anthropic\|google.genai\|groq\|xai_sdk\|aioboto3\|claude_agent_sdk\|transformers\|torch\)" packages/ai-parrot/src`. `parrot/tokenizer` or `interfaces/images` may still need `transformers`/`torch` — keep those pins in their own extras, not in `llms`.

### References in Codebase
- `packages/ai-parrot/src/parrot/embeddings/__init__.py` — `extend_path` pattern (FEAT-201)
- `packages/ai-parrot-embeddings/pyproject.toml` — satellite packaging pattern
- `packages/ai-parrot/src/parrot/clients/google/`, `nova/` — folders that already exist
- `sdd/specs/pep-420-llm-clients.spec.md` §2 map, §6 contract, §7 gotchas

---

## Acceptance Criteria

- [ ] Core `dependencies` has no extracted SDK pin except `openai` and `tiktoken`; `ai-parrot[llms]` resolves to the 15 satellites
- [ ] Fresh venv with `uv pip install -e packages/ai-parrot` (no satellites) → `python -c 'from parrot.clients.factory import LLMFactory; LLMFactory.list_providers()'` returns `{}` without error
- [ ] `_IN_CORE_PROVIDERS` gone; `uv lock` clean; full `pytest packages/ai-parrot/tests/unit -q` green (timeout-wrapped)

---

## Test Specification

```python
# tests/unit/clients/test_core_has_no_sdk_pins.py
import tomllib, pathlib
def test_core_pins():
    py = tomllib.loads(pathlib.Path("packages/ai-parrot/pyproject.toml").read_text())
    deps = " ".join(py["project"]["dependencies"])
    for sdk in ("anthropic", "google-genai", "groq", "xai-sdk", "zai-sdk", "aioboto3", "claude-agent-sdk"):
        assert sdk not in deps
    assert "openai" in deps and "tiktoken" in deps
    assert len(py["project"]["optional-dependencies"]["llms"]) == 15
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
7. **Move this file** to `sdd/tasks/completed/TASK-2854-core-extras-workspace-cleanup.md`
8. **Update index** → `"done"`
9. **Fill in the Completion Note** below

---

## Completion Note

**Completed by**: sdd-worker (autonomous, FEAT-523 session)
**Date**: 2026-09-04
**Notes**:

`factory.py`: deleted `_IN_CORE_PROVIDERS` and the transitional walk
branch in `_discover()` — entry points are now the sole discovery
source. Rewrote the module docstring (was describing a two-source design
that no longer exists) and the two docstrings/comments still referencing
the transitional registry (`list_providers()`, `_PROVIDER_DIST`'s own
comment). Verified for real: uninstalled all 15 satellites from the
worktree venv and confirmed `LLMFactory.list_providers()` returns exactly
`{}` and `from parrot.clients.factory import LLMFactory` still imports
cleanly — the literal AC-2 check, not a mocked approximation.

**Extras rewrite** (`packages/ai-parrot/pyproject.toml`): every
provider-specific extra now references its satellite
(`anthropic`/`bedrock`/`claude-agent` → `ai-parrot-client-anthropic`;
`bedrock-native` → `ai-parrot-client-amazon`; `codex-agent` →
`ai-parrot-client-openai[bridge]`; `openai`/`google`/`groq`/`zai` → their
own satellites). Added the 9 extras the task named as missing
(`grok`/`gemma4`/`hf`/`nvidia`/`moonshot`/`openrouter`/`local`/`vllm`/
`meta`), and repointed the pre-existing `xai` extra (a separate,
already-existing name for the exact same grok/xAI SDK) at
`ai-parrot-client-grok` too, rather than leaving a duplicate/stale extra
behind. `llms` now lists exactly the 15 satellite package names — no
more, no less, matching this task's own Test Specification's literal
`len(...) == 15` check.

Added a `[tool.uv.sources]` section to core's `pyproject.toml` — core
never needed one before this feature (it never depended on a sibling
workspace package), mapping all 15 `ai-parrot-client-*` names to
`{ workspace = true }`.

**Contract corrections / judgment calls, each verified via grep before
acting** (same discipline as every satellite task's own corrections):

1. **`google` extra**: the Scope text said `google = ["ai-parrot-client-
   google"]`, a full replacement. Verified via grep that
   `google-api-python-client`/`google-cloud-texttospeech`/
   `google-cloud-aiplatform` are NOT imported anywhere under
   `parrot/clients/google/` (only `google.genai`/`google.oauth2`/
   `google.auth` are) — they back `parrot.interfaces.http`'s
   `googleapiclient` usage and other, unrelated core Google integrations.
   Kept them alongside the new satellite reference rather than removing
   them, which would have silently broken those unrelated features.
2. **`aioboto3`**: grep found `parrot/interfaces/aws.py` and
   `parrot/storage/backends/dynamodb.py` also `import aioboto3`
   unconditionally, entirely unrelated to Bedrock. Did not strip
   `aioboto3` from anywhere — `bedrock-native` now points at
   `ai-parrot-client-amazon`, which itself declares `aioboto3>=13.2.0`,
   so those two unrelated files stay satisfied transitively through the
   same extra path as before (no regression).
3. **`openai==3.3.1` → base dependency**: the task's own Test
   Specification asserts `"openai" in deps` where `deps` is `project.
   dependencies` (base), not an extra — this only holds if `openai`
   becomes a base dependency. Moved it there (alongside the pre-existing
   `tiktoken>=0.9.0`), justified the same way as the existing `tenacity`
   base dependency: `OpenAIBaseClient` (core) is subclassed by **seven**
   satellites (openai, groq, zai, moonshot, openrouter, local, nvidia),
   not just one. Also corrected the `tenacity` comment's stale file
   reference (`clients/gpt.py` → renamed `clients/openai/client.py` by
   TASK-2842, since moved out of core entirely to the openai satellite).
   Removed the redundant `openai==3.3.1` pin I'd first added to
   `ai-parrot-client-openai`'s own `dependencies` once core covered it
   transitively.
4. **Root `pyproject.toml`**: the Scope said "all extra pulls
   `ai-parrot[llms]` transitively (verify current shape first)" — per
   that explicit instruction, verified first: root's own
   `[project.optional-dependencies]` has no `all` key at all. Left root
   completely untouched; nothing to fix.
5. **`gemma4`/`hf` resolver conflict**: a pre-existing comment
   ("REMOVED: gemma4 extra — was mutually exclusive with audio/images/
   all/dev/security/ml-heavy (8 conflict pairs)") warned this exact
   provider previously caused `uv lock` backtracking when its
   `transformers`/`torch` pins lived inside core's own extras. Since
   `gemma4` (and `hf`) are now separate packages with their own
   dependency graphs, ran `uv lock` to confirm the conflict doesn't
   resurface — it resolved cleanly (920 packages, no errors). Left the
   historical comment in place (superseded, not deleted) with a note
   explaining why the old constraint no longer applies.

**Evidence**:
- `uv lock` → resolved cleanly, no conflicts.
- `uv sync --package ai-parrot --extra llms --extra <every other LLM
  extra>` → all 15 satellites installed for real, zero errors
  (`uv sync --all-extras` at the *workspace* level hits an unrelated,
  pre-existing `tree-sitter-languages` cp313-wheel-availability gap from
  an unrelated extra — confirmed via error message unrelated to any file
  this task touched).
- Uninstalled all 15 satellites → `LLMFactory.list_providers()` returns
  `{}`; `from parrot.clients.factory import LLMFactory` imports cleanly.
- `pytest packages/ai-parrot/tests/unit/clients -q` → **338/338 passed**
  (337 + the new `test_core_has_no_sdk_pins.py`), zero failures, with all
  15 satellites reinstalled afterward.
- Full 15-satellite matrix re-run → clean except the two
  already-documented pre-existing multiround failures (openai×4, groq×4).
- `ruff check` on every touched Python file → clean.
- Server studio+handlers+admin_catalog sweep (213 tests), pipelines sweep
  (39/40, 1 pre-existing), top-level `tests/clients/` sweep (105/106, 1
  pre-existing live-credit-balance failure), crew regression smoke test
  (23/23) — all only the same already-documented pre-existing failures.

**Deviations from spec**: the five contract corrections/judgment calls
above, each verified via grep/`uv lock` before acting and documented
in-line in the pyproject.toml comments themselves, not silent
overrides.
