---
type: Wiki Overview
title: 'Feature Specification: Odoo PageIndex Documentation Agent (OdooAgent / "Oddie")'
id: doc:sdd-specs-odoo-pageindex-documentation-agent-spec-md
tags:
- overview
timestamp: '2026-07-16T08:34:12+00:00'
summary: 'AI-Parrot already ships an `OdooToolkit` (RPC: JSON-2 / XML-RPC / JSON-RPC)
  and a'
relates_to:
- concept: mod:parrot.auth.confirmation
  rel: mentions
- concept: mod:parrot.bots
  rel: mentions
- concept: mod:parrot.bots.agent
  rel: mentions
- concept: mod:parrot.knowledge.pageindex
  rel: mentions
- concept: mod:parrot.models.google
  rel: mentions
- concept: mod:parrot.registry
  rel: mentions
- concept: mod:parrot.skills
  rel: mentions
- concept: mod:parrot.stores.kb.user
  rel: mentions
- concept: mod:parrot.tools.working_memory
  rel: mentions
- concept: mod:parrot_tools.odoo
  rel: mentions
---

---
type: feature
base_branch: dev
---

# Feature Specification: Odoo PageIndex Documentation Agent (OdooAgent / "Oddie")

**Feature ID**: FEAT-240
**Date**: 2026-06-16
**Author**: Jesus Lara
**Status**: approved
**Target version**: TBD

---

## 1. Motivation & Business Requirements

> Why does this feature exist? What problem does it solve?

### Problem Statement

AI-Parrot already ships an `OdooToolkit` (RPC: JSON-2 / XML-RPC / JSON-RPC) and a
backup `OdooAgent` (`agents/backup/odoo.py`). What is missing is a **self-documenting,
self-improving Odoo operations agent** that:

- Knows the *behavioural differences* between Odoo **16 (XML-RPC)**, **18**, and
  **19 (JSON-RPC / REST / JSON-2)** by grounding answers in the official documentation,
  not in the model's parametric memory.
- Records what it learns (operations, gotchas, doc gaps) so the next conversation is
  better than the last — into a **PageIndex** (for documentation/learnings) and a
  **Skill Registry** (for repeatable operations).
- Gates **write operations** on the live Odoo instance behind explicit human
  confirmation (HITL).
- Personalises its system prompt with **user context** automatically (Userinfo KB).
- Can both *query* Odoo over RPC **and** *administer* it via `odoo-bin` / `odoo-cli`
  shell commands (e.g. install modules), with the dangerous shell surface gated by HITL.

Today an operator must read three different Odoo doc sets, remember which RPC transport
each version speaks, and hand-hold every write. This agent collapses that into one
grounded, confirmable, learning assistant.

### Goals

- **G1** — Ship a registered agent at `agents/oddie.py`, class `OdooAgent`,
  slug/`agent_id` `odoo_agent`, model **`gemini-3.5-flash`** via the `GoogleModel` enum.
- **G2** — Build and attach a **PageIndex** containing the official Odoo 16 / 18 / 19
  documentation (sourced and converted to PDF by this feature), including `odoo-cli` /
  `odoo-bin` reference material.
- **G3** — Register the **PageIndexToolkit** and instruct the agent (in its backstory)
  to write any *learning not found in the documentation* back into the documentation
  PageIndex.
- **G4** — Enable the **Skill Registry** (via `SkillRegistryMixin`) and instruct the
  agent to document a **skill** whenever it learns how to perform an Odoo operation.
- **G5** — Register the **WorkingMemoryToolkit** and instruct the agent to use it for
  intermediate results, including data staged for presentation to the user.
- **G6** — Gate Odoo **write/delete** RPC operations **and** all `odoo-bin`/`odoo-cli`
  shell operations behind **HITL confirmation**.
- **G7** — Register the **Userinfo KB** (`UserInfo`, `always_active=True`) so the system
  prompt auto-incorporates user information.
- **G8** — Configure `OdooToolkit` from the **`ODOO_TEST_*`** environment variables in
  `env/.env` (test instance `prozac`, Odoo 18).
- **G9** — Extend `OdooToolkit` with **`odoo-bin` / `odoo-cli` shell functions**
  (subprocess-based, HITL-gated) — e.g. module install/upgrade, scaffold, shell.
- **G10** — Author two **composite skills** under `agents/odoo_agent/skills/`:
  - `install-odoo-module` — how to install a new Odoo module.
  - `structured-operation-response` — answer "how do I do X in Odoo" as an *ordered
    bullet list* of steps.

### Non-Goals (explicitly out of scope)

- Replacing the existing `agents/backup/odoo.py` (kept as a minimal reference).
- Building a generic RAG vectorstore for Odoo docs — grounding is via **PageIndex** only.
- Multi-tenant credential management — the agent targets a single Odoo instance via
  `ODOO_TEST_*`.
- Production Odoo (the staging `ODOO_*` vars) — out of scope; this agent uses the
  **test** instance.
- Auto-publishing skills/learnings to a shared/remote registry — local persistence only.

---

## 2. Architectural Design

### Overview

`OdooAgent` ("Oddie") is a registered `Agent` subclass that composes
`SkillRegistryMixin` for skill capabilities. It wires five capability surfaces:

1. **OdooToolkit** (RPC + new shell functions) — the action layer against the live
   Odoo test instance. Constructed from `ODOO_TEST_*` env vars.
2. **PageIndexToolkit** — grounded retrieval over the bundled Odoo 16/18/19 docs, plus a
   *write-back* path so out-of-doc learnings are spliced into the documentation tree.
3. **Skill Registry** (`SkillRegistryMixin`) — DB-backed + file-based skills under
   `agents/odoo_agent/skills/`; the agent documents new operations as skills.
4. **WorkingMemoryToolkit** — intermediate result store for staged/presentable data.
5. **HITL ConfirmationGuard** — wraps the ToolManager; write/delete RPC tools and all
   shell tools require human confirmation before execution.
6. **Userinfo KB** (`UserInfo`) — always-active KB injected into the system prompt.

The **backstory** is the behavioural contract: it explains *when* to use OdooToolkit,
*when* to write a learning into the PageIndex, *when* to document a skill, *how* to use
working memory, and that writes will be confirmed.

The Odoo documentation PageIndex is **built offline** by an ingestion script (the agent
consumes the persisted tree at runtime; it does not build it on the request path).

### Component Diagram

```
                         ┌─────────────────────────────────────────────┐
                         │              OdooAgent ("Oddie")             │
                         │  Agent + SkillRegistryMixin                  │
                         │  model = GoogleModel.GEMINI_3_5_FLASH        │
                         └───────────────┬─────────────────────────────┘
                                         │ agent_tools() / configure()
        ┌───────────────┬────────────────┼─────────────────┬──────────────────┐
        ▼               ▼                ▼                 ▼                  ▼
  OdooToolkit     PageIndexToolkit  WorkingMemory   SkillRegistry        Userinfo KB
  (RPC + shell)   (docs tree +      Toolkit         (file + DB skills)   (UserInfo,
   ODOO_TEST_*     write-back)                       agents/odoo_agent/   always_active)
        │                                            skills/)
        ▼
  ConfirmationGuard (HITL)  ◀── gates write/delete RPC + odoo-bin/odoo-cli shell tools

  Offline:  build_odoo_pageindex.py  ──→  Odoo 16/18/19 PDFs  ──→  per-version trees
            (agents/odoo_agent/documentation/: odoo_16, odoo_18, odoo_19)
```

### Integration Points

| Existing Component | Integration Type | Notes |
|---|---|---|
| `parrot.bots.Agent` | subclass | `OdooAgent(SkillRegistryMixin, Agent)` |
| `parrot.skills.SkillRegistryMixin` | mixin | `enable_skill_registry=True`; loads `agents/odoo_agent/skills/` |
| `parrot_tools.odoo.OdooToolkit` | uses + **extends** | constructed from `ODOO_TEST_*`; new shell functions added |
| `parrot.knowledge.pageindex.PageIndexToolkit` | uses | constructed with `PageIndexLLMAdapter` + persisted `storage_dir` |
| `parrot.knowledge.pageindex.build_page_index` / `import_pdf` | uses (offline) | builds the docs tree from bundled PDFs |
| `parrot.tools.working_memory.WorkingMemoryToolkit` | uses | `register_toolkit` in `configure()` |
| `parrot.auth.confirmation.ConfirmationGuard` | uses | `tool_manager.set_confirmation_guard(guard)` |
| `parrot.stores.kb.user.UserInfo` | uses | `register_kb(UserInfo())` |
| `parrot.models.google.GoogleModel` | uses | `GEMINI_3_5_FLASH` enum member |
| `parrot.registry.register_agent` | decorator | `@register_agent(name="odoo_agent", at_startup=True)` |

### Data Models

No new persistent Pydantic models are required for the agent itself. The PageIndex tree
uses the existing `PageIndexNode` / `PageIndexTree` schemas. The new shell tools use
`@tool_schema` Pydantic input models, e.g.:

```python
class OdooShellInstallInput(BaseModel):
    modules: list[str] = Field(..., description="Technical module names to install, e.g. ['sale','stock']")
    database: str | None = Field(None, description="Target database; defaults to ODOO_TEST_DATABASE")
    upgrade: bool = Field(False, description="If True, upgrade (-u) instead of install (-i)")
```

### New Public Interfaces

```python
# agents/oddie.py  (NOTE: agents/ is gitignored — see §7 Known Risks)
@register_agent(name="odoo_agent", at_startup=True)
class OdooAgent(SkillRegistryMixin, Agent):
    agent_id: str = "odoo_agent"
    model = GoogleModel.GEMINI_3_5_FLASH          # str-enum member; .value == "gemini-3.5-flash"
    enable_skill_registry: bool = True
    skill_registry_expose_tools: bool = True
    skill_registry_inject_context: bool = True

    def __init__(self, *args, **kwargs): ...
    def agent_tools(self) -> list[AbstractTool]: ...   # OdooToolkit + PageIndexToolkit tools
    async def configure(self, app=None, queries=None) -> None: ...  # WM toolkit, guard, KB, skills
    async def cleanup(self) -> None: ...

# parrot_tools.odoo (NEW shell functions on OdooToolkit, HITL-gated)
class OdooToolkit(AbstractToolkit):
    confirming_tools: frozenset[str]  # extended to include shell + write/delete tools
    async def odoo_shell_install_module(self, modules: list[str], ...) -> ShellResult: ...
    async def odoo_shell_upgrade_module(self, modules: list[str], ...) -> ShellResult: ...
    async def odoo_cli_command(self, subcommand: str, args: list[str], ...) -> ShellResult: ...
```

---

## 3. Module Breakdown

> Each module maps to one or more Task Artifacts in Phase 2.

### Module 1: OdooToolkit shell extension (`odoo-bin` / `odoo-cli`)
- **Path**: `packages/ai-parrot-tools/src/parrot_tools/odoo/shell.py` (new) + edits to
  `packages/ai-parrot-tools/src/parrot_tools/odoo/toolkit.py`
- **Responsibility**: Add subprocess-based async tools that invoke `odoo-bin` / `odoo-cli`
  (module install/upgrade, scaffold, generic CLI passthrough). Path to the binary,
  config file, and database resolved from env (`ODOO_BIN`, `ODOO_CONF`, `ODOO_TEST_DATABASE`).
  Use `asyncio.create_subprocess_exec` (never `shell=True`); validate/whitelist
  subcommands; capture stdout/stderr into a typed `ShellResult`; enforce a timeout.
  Mark every shell tool in `confirming_tools` so HITL gates it.
- **Depends on**: existing `OdooToolkit`, `AbstractToolkit.confirming_tools` machinery.
- **Constraint**: these tools only work when Odoo is co-located / the binary is reachable.
  When `ODOO_BIN` is unset, the tools must self-disable with a clear message (not crash).

### Module 2: Odoo documentation sourcing + PDF conversion
- **Path**: `scripts/odoo_agent/fetch_odoo_docs.sh` (new) + generated output under
  `agents/odoo_agent/documentation/` (`16.0/`, `18.0/`, `19.0/`).
- **Responsibility**: Generate the official Odoo docs as PDFs from the **official Odoo
  documentation repository** (`https://github.com/odoo/documentation.git`), one PDF per
  version, by checking out the version branch and running `make latexpdf`:
  ```bash
  git clone https://github.com/odoo/documentation.git
  cd documentation
  git checkout 18.0        # repeat for 16.0 and 19.0
  make latexpdf            # produces the docs PDF under the build output dir
  ```
  Wrap this in `fetch_odoo_docs.sh` to loop over `16.0 18.0 19.0`, collect each generated
  PDF into `agents/odoo_agent/documentation/<version>/`. Document the LaTeX toolchain prerequisite
  (`make latexpdf` needs a TeX distribution). The External API (XML-RPC for 16,
  JSON-RPC/REST/JSON-2 for 18/19) and the `odoo-bin`/`odoo-cli` CLI reference are part of
  this same documentation repo, so they are captured by the same build.
- **Depends on**: none (offline tooling). Network + LaTeX toolchain required at build time.

### Module 3: PageIndex builder (offline ingestion)
- **Path**: `scripts/odoo_agent/build_odoo_pageindex.py` (new)
- **Responsibility**: Build the documentation PageIndex from the Module 2 PDFs using
  `PageIndexToolkit.import_pdf` (or `build_page_index`). Create **one tree per Odoo
  version** — `odoo_16`, `odoo_18`, `odoo_19` — importing each version's PDF into its own
  tree (the per-version PDF already includes that version's `odoo-bin`/`odoo-cli` CLI
  reference). Persist `storage_dir = agents/odoo_agent/documentation/`. Idempotent /
  re-runnable.
- **Depends on**: Module 2, `parrot.knowledge.pageindex`.

### Module 4: OdooAgent implementation
- **Path**: `agents/oddie.py` (new)
- **Responsibility**: The registered agent. Compose `SkillRegistryMixin + Agent`; build
  `OdooToolkit` from `ODOO_TEST_*`; build `PageIndexToolkit` (adapter + persisted store);
  register `WorkingMemoryToolkit`; attach `ConfirmationGuard`; register `UserInfo` KB;
  enable file/DB skills under `agents/odoo_agent/skills/`. Author the backstory contract.
- **Depends on**: Modules 1 & 3, all referenced toolkits/KB/guard.

### Module 5: Backstory authoring
- **Path**: inside `agents/oddie.py` (string constant)
- **Responsibility**: Encode the behavioural contract: how/when to use OdooToolkit;
  write out-of-doc learnings into the PageIndex; document new operations as skills; use
  working memory for intermediate/presentable data; writes are HITL-confirmed; ground
  every answer in the docs PageIndex and cite version differences (16 XML-RPC vs 18/19).
- **Depends on**: Module 4.

### Module 6: Skill — install an Odoo module
- **Path**: `agents/odoo_agent/skills/install-odoo-module/SKILL.md` (+ assets)
- **Responsibility**: Composite skill describing how to install a new Odoo module —
  via `odoo-bin -i` / `odoo-cli` (Module 1 tools) and via Apps/RPC where applicable —
  including prerequisites, restart, and verification steps.
- **Depends on**: Module 1.

### Module 7: Skill — structured operation response
- **Path**: `agents/odoo_agent/skills/structured-operation-response/SKILL.md`
- **Responsibility**: Composite skill instructing that "how do I do X in Odoo" questions
  are answered as an **ordered bullet list** of concrete steps (grounded in the PageIndex,
  version-aware).
- **Depends on**: none.

---

## 4. Test Specification

### Unit Tests
| Test | Module | Description |
|---|---|---|
| `test_odoo_shell_install_builds_argv` | M1 | `odoo_shell_install_module` builds correct `odoo-bin -d <db> -i <mods> --stop-after-init` argv; no `shell=True` |
| `test_odoo_shell_disabled_without_bin` | M1 | Tools self-disable (clear message, no crash) when `ODOO_BIN` unset |
| `test_odoo_shell_tools_are_confirming` | M1 | All shell tools appear in `confirming_tools` → `routing_meta["requires_confirmation"] is True` |
| `test_odoo_shell_subcommand_whitelist` | M1 | Non-whitelisted CLI subcommands are rejected |
| `test_build_pageindex_creates_per_version_trees` | M3 | Builder creates `odoo_16`/`odoo_18`/`odoo_19` trees (mocked `import_pdf`) |
| `test_pageindex_build_idempotent` | M3 | Re-running the builder does not duplicate version nodes |
| `test_odoo_agent_registers` | M4 | `@register_agent("odoo_agent")` resolvable from registry |
| `test_odoo_agent_model_is_gemini_3_5_flash` | M4 | `OdooAgent.model` resolves to `"gemini-3.5-flash"` |
| `test_odoo_toolkit_uses_test_env` | M4 | OdooToolkit constructed with `ODOO_TEST_URL/DATABASE/USERNAME/PASSWORD` |
| `test_agent_tools_include_odoo_and_pageindex` | M4 | `agent_tools()` returns both `odoo_*` and `pageindex_*` tools |
| `test_userinfo_kb_registered_and_active` | M4 | `UserInfo` registered and `always_active is True` |
| `test_confirmation_guard_attached` | M4 | `tool_manager.confirmation_guard` is not None after `configure()` |
| `test_skills_discovered` | M4 | Both composite skills discovered from `agents/odoo_agent/skills/` |
| `test_install_module_skill_frontmatter` | M6 | `install-odoo-module/SKILL.md` parses (valid frontmatter + trigger) |
| `test_structured_response_skill_frontmatter` | M7 | `structured-operation-response/SKILL.md` parses |

### Integration Tests
| Test | Description |
|---|---|
| `test_agent_grounds_answer_in_pageindex` | With a built test PageIndex, a "how do I X in Odoo 16 vs 19" question retrieves version-aware nodes |
| `test_write_op_requires_confirmation` | A create/update RPC call returns `status="cancelled"` when the guard denies (mocked human) |
| `test_learning_written_back_to_pageindex` | An out-of-doc learning is spliced via `pageindex_insert_content`/`insert_markdown` |

### Test Data / Fixtures
```python
@pytest.fixture
def odoo_test_env(monkeypatch):
    monkeypatch.setenv("ODOO_TEST_URL", "http://prozac:8069")
    monkeypatch.setenv("ODOO_TEST_DATABASE", "odoo")
    monkeypatch.setenv("ODOO_TEST_USERNAME", "admin")
    monkeypatch.setenv("ODOO_TEST_PASSWORD", "admin")

@pytest.fixture
def tiny_pageindex(tmp_path):
    """A minimal persisted PageIndex tree with Odoo 16/18/19 nodes for retrieval tests."""
    ...
```

---

## 5. Acceptance Criteria

> This feature is complete when ALL of the following are true:

- [ ] **AC1** — `agents/oddie.py` defines `OdooAgent(SkillRegistryMixin, Agent)`, slug
      `odoo_agent`, registered via `@register_agent(name="odoo_agent", at_startup=True)`.
- [ ] **AC2** — Model is set via the `GoogleModel` enum (`GEMINI_3_5_FLASH`), not a raw
      string; `OdooAgent.model` resolves to `"gemini-3.5-flash"`.
- [ ] **AC3** — `OdooToolkit` is constructed from `ODOO_TEST_*` env vars (`verify_ssl=False`),
      targeting the test instance — not the staging `ODOO_*` vars.
- [ ] **AC4** — A documentation **PageIndex** with **one tree per Odoo version**
      (`odoo_16`/`odoo_18`/`odoo_19`, incl. each version's `odoo-bin`/`odoo-cli` reference) is
      built by an offline script under `agents/odoo_agent/documentation/` and attached via
      `PageIndexToolkit`.
- [ ] **AC5** — Backstory instructs the agent to write learnings *not found in the docs*
      into the documentation PageIndex (and the toolkit exposes a write-back path).
- [ ] **AC6** — Skill Registry enabled; backstory instructs documenting a skill when the
      agent learns an Odoo operation; skills load from `agents/odoo_agent/skills/`.
- [ ] **AC7** — `WorkingMemoryToolkit` registered; backstory instructs its use, including
      staging intermediate information for presentation to the user.
- [ ] **AC8** — Odoo write/delete RPC tools **and** all `odoo-bin`/`odoo-cli` shell tools
      are gated by a `ConfirmationGuard` (HITL) attached to the agent's ToolManager.
- [ ] **AC9** — `UserInfo` KB registered and active; system prompt auto-incorporates user info.
- [ ] **AC10** — New `OdooToolkit` shell functions for `odoo-bin`/`odoo-cli` exist, use
      `create_subprocess_exec` (no `shell=True`), validate inputs, and self-disable cleanly
      when the binary is unavailable.
- [ ] **AC11** — `install-odoo-module` and `structured-operation-response` composite skills
      exist under `agents/odoo_agent/skills/` and parse correctly.
- [ ] **AC12** — All unit tests pass (`pytest packages/ai-parrot/tests -k odoo -v` and the
      new agent/shell tests).
- [ ] **AC13** — No breaking changes to the existing `OdooToolkit` RPC API.

---

## 6. Codebase Contract

> **CRITICAL — Anti-Hallucination Anchor.** Every reference below was verified by reading
> source. Implementing agents MUST NOT reference imports/attributes/methods not listed
> here without first verifying via `grep`/`read`.

### Verified Imports
```python
# Agent base + registry
from parrot.bots import Agent                          # verified: agents/backup/odoo.py:3 (re-exported from parrot.bots.agent.Agent, agent.py:1256)
from parrot.registry import register_agent             # verified: agents/backup/odoo.py:4, agents/porygon.py:6
from parrot.models.google import GoogleModel           # verified: packages/ai-parrot/src/parrot/models/google.py:9

# Skills
from parrot.skills import SkillRegistryMixin           # verified: agents/porygon.py:5

# Odoo toolkit
from parrot_tools.odoo import OdooToolkit              # verified: agents/backup/odoo.py:5; __init__ exports OdooToolkit

# PageIndex
from parrot.knowledge.pageindex import (               # verified: packages/ai-parrot/src/parrot/knowledge/pageindex/__init__.py:1-43
    PageIndexToolkit, PageIndexLLMAdapter, build_page_index,
)

# Working memory
from parrot.tools.working_memory import WorkingMemoryToolkit  # verified: agents/porygon.py:9

# HITL confirmation
from parrot.auth.confirmation import ConfirmationGuard, ConfirmationConfig  # verified: packages/ai-parrot/examples/workday_checkin.py:107
# (InMemoryConfirmationWindowStore also from parrot.auth.confirmation — verified: workday_checkin.py)

# Userinfo KB
from parrot.stores.kb.user import UserInfo             # verified: packages/ai-parrot/src/parrot/stores/kb/user.py:11
```

### Existing Class Signatures
```python
# packages/ai-parrot/src/parrot/bots/agent.py
class BasicAgent(Chatbot, NotificationMixin):           # line 37
    def __init__(self, name='Agent', agent_id='agent', use_llm='google', llm=None,
                 tools=None, system_prompt=None, human_prompt=None, use_tools=True,
                 instructions=None, dataframes=None, **kwargs): ...   # lines 80-109
class Agent(BasicAgent): ...                            # line 1256
    # `backstory` accepted via kwargs → AbstractBot (abstract.py:386-388) and rendered
    # into the system prompt (abstract.py:1054, 1107).

# packages/ai-parrot/src/parrot/models/google.py
class GoogleModel(str, Enum):
    GEMINI_3_5_FLASH = "gemini-3.5-flash"               # line 16 (aliases: GEMINI_3_FLASH:17, GEMINI_3_FLASH_PREVIEW:18)
    GEMINI_FLASH_LATEST = "..."                         # used by backup agent

# packages/ai-parrot-tools/src/parrot_tools/odoo/toolkit.py
class OdooToolkit(AbstractToolkit):                     # line 159 ; tool_prefix = "odoo" (line 178)
    def __init__(self, url=None, database=None, username=None, password=None,
                 timeout=None, verify_ssl=None, protocol="auto", transport=None, **kwargs): ...  # lines 180-191
    async def cleanup(self) -> None: ...                # called by backup agent cleanup
    # Write/delete tools enforce @requires_permission("odoo.write"/"odoo.delete").
    # Existing write/delete tools include: odoo_create_record(s), odoo_update_record(s),
    # odoo_delete_record(s), odoo_import_records, odoo_create_partner, odoo_create_quotation,
    # odoo_confirm_sale_order, odoo_create_invoice, odoo_post_invoice, odoo_register_payment,
    # odoo_set_binary_field, odoo_attach_document.

# packages/ai-parrot/src/parrot/knowledge/pageindex/toolkit.py
class PageIndexToolkit(AbstractToolkit):                # line 50 ; tool_prefix = "pageindex" (line 86)
    def __init__(self, adapter: PageIndexLLMAdapter, storage_dir: str | Path,
                 reranker=None, lightweight_model=None, model=None, default_bm25_k=20,
                 folder_concurrency=4, content_cache_size=256, embedding_model=None,
                 embedding_dimension=256, embedding_backend=None, use_vec_rank=False,
                 use_embedding_walk=False, **kwargs): ...   # lines 88-104
    async def import_pdf(self, tree_name, pdf_path, parent_node_id=None,
                         with_summaries=False, with_doc_description=False): ...  # lines 773-821
    async def insert_content(self, tree_name, content, parent_node_id=None, hint=None): ...  # lines 730-752
    async def insert_markdown(self, tree_name, markdown, parent_node_id=None, doc_name=None): ...  # lines 692-728
    def get_tools(self) -> list[AbstractTool]: ...      # inherited from AbstractToolkit

# packages/ai-parrot/src/parrot/knowledge/pageindex/llm_adapter.py
class PageIndexLLMAdapter:                              # line 42
    def __init__(self, client: AbstractClient, model="gemini-3.1-flash-lite-preview",
                 max_retries=3, retry_delay=1.0): ...    # lines 49-59

# packages/ai-parrot/src/parrot/tools/working_memory/tool.py
class WorkingMemoryToolkit(AbstractToolkit):           # line 43 ; tool_prefix = "wm"
    def __init__(self, session_id=None, max_rows=10, max_cols=30,
                 tool_locals_registry=None, answer_memory=None, **kwargs): ...  # lines 87-115

…(truncated)…
