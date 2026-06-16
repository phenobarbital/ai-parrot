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

  Offline:  build_odoo_pageindex.py  ──→  bundled Odoo 16/18/19 PDFs  ──→  PageIndex store
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
  `agents/odoo_agent/docs/` (16/, 18/, 19/).
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
  PDF into `agents/odoo_agent/docs/<version>/`. Document the LaTeX toolchain prerequisite
  (`make latexpdf` needs a TeX distribution). The External API (XML-RPC for 16,
  JSON-RPC/REST/JSON-2 for 18/19) and the `odoo-bin`/`odoo-cli` CLI reference are part of
  this same documentation repo, so they are captured by the same build.
- **Depends on**: none (offline tooling). Network + LaTeX toolchain required at build time.

### Module 3: PageIndex builder (offline ingestion)
- **Path**: `scripts/odoo_agent/build_odoo_pageindex.py` (new)
- **Responsibility**: Build the documentation PageIndex from the Module 2 PDFs using
  `PageIndexToolkit.import_pdf` (or `build_page_index`). Organise as a single tree with
  per-version parent nodes (`Odoo 16`, `Odoo 18`, `Odoo 19`) and a `CLI (odoo-bin/odoo-cli)`
  node. Persist to the agent's `storage_dir`. Idempotent / re-runnable.
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
| `test_build_pageindex_creates_version_nodes` | M3 | Builder creates `Odoo 16/18/19` + CLI parent nodes (mocked `import_pdf`) |
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
- [ ] **AC4** — A documentation **PageIndex** for Odoo 16 / 18 / 19 (incl. `odoo-bin`/
      `odoo-cli` reference) is built by an offline script and attached via `PageIndexToolkit`.
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
    # Tools: store, store_result, get_stored, get_result, list_stored, search_stored, ...

# packages/ai-parrot/src/parrot/skills/mixin.py
class SkillRegistryMixin:                               # line 27
    enable_skill_registry: bool = True                  # line 57
    skill_registry_expose_tools: bool = True            # line 58
    skill_registry_inject_context: bool = True          # line 59
    skill_registry_auto_extract: bool = False           # line 60
    skill_paths: List[Path] = []                        # line 65
    inject_skills_into_prompt: bool = True              # line 69
    async def _configure_skill_registry(self) -> None: ...   # called at end of configure()

# packages/ai-parrot/src/parrot/auth/confirmation.py
class ConfirmationConfig(BaseModel):                    # line 66
    window_seconds: int = 0; approval_timeout: float = 120.0
    default_channel: str = "telegram"; max_edit_retries: int = 1
class ConfirmationGuard:                                # line 378
    def __init__(self, store, human_manager=None, config=None): ...   # lines ~390
    async def confirm(self, *, tool, parameters, permission_context=None) -> ConfirmationDecision: ...

# packages/ai-parrot/src/parrot/tools/manager.py
class ToolManager:
    def set_confirmation_guard(self, guard: "ConfirmationGuard") -> None: ...  # line 338
    @property
    def confirmation_guard(self) -> Optional["ConfirmationGuard"]: ...         # line 356
    def register_toolkit(self, toolkit) -> ...                                 # used by porygon.py:437

# packages/ai-parrot/src/parrot/tools/toolkit.py
class AbstractToolkit:
    confirming_tools: frozenset[str] = frozenset()      # lines 264-276; methods named here get
                                                        # routing_meta["requires_confirmation"]=True (lines 575-578)

# packages/ai-parrot/src/parrot/stores/kb/user.py
class UserInfo(AbstractKnowledgeBase):                  # line 11
    def __init__(self, **kwargs):                       # always_active=True, priority=10
    async def search(self, query: str, user_id: int, **kwargs) -> List[Dict]: ...  # lines 43-76

# packages/ai-parrot/src/parrot/bots/abstract.py
def register_kb(self, kb: AbstractKnowledgeBase): ...   # line 962
#   always_active KBs are auto-activated and injected into the system prompt
#   (abstract.py:2807-2810, _build_kb_context).
```

### Reference Implementation Pattern (verified)
```python
# agents/backup/odoo.py — minimal existing OdooAgent (the model to extend)
@register_agent(name="odoo_agent", at_startup=True)        # line 42
class OdooAgent(Agent):                                     # line 43
    agent_id: str = "odoo_agent"; model: str = GoogleModel.GEMINI_FLASH_LATEST
    def __init__(self, *args, **kwargs):
        super().__init__(*args, backstory=BACKSTORY, **kwargs)
        self._odoo_toolkit: OdooToolkit | None = None
    def agent_tools(self):
        self._odoo_toolkit = OdooToolkit(url=ODOO_TEST_URL, database=ODOO_TEST_DATABASE,
            username=ODOO_TEST_USERNAME, password=ODOO_TEST_PASSWORD, verify_ssl=False)
        return self._odoo_toolkit.get_tools()
    async def cleanup(self):
        if self._odoo_toolkit: await self._odoo_toolkit.cleanup()
        await super().cleanup()

# agents/porygon.py — verified wiring of mixin + WorkingMemory + skills
class Porygon(SkillRegistryMixin, EpisodicMemoryMixin, PandasAgent):   # line 253
    enable_skill_registry: bool = True                                 # line 266
    async def configure(self, app=None, queries=None):
        wm_toolkit = WorkingMemoryToolkit()                            # line 436
        self.tool_manager.register_toolkit(wm_toolkit)                 # line 437
        await super().configure(app=app, queries=queries)
        await self._configure_skill_registry()                        # line 442 (loads agents/porygon/skills/*)

# packages/ai-parrot/examples/workday_checkin.py — verified ConfirmationGuard wiring
guard = ConfirmationGuard(store=InMemoryConfirmationWindowStore(),
                          human_manager=human_manager, config=ConfirmationConfig(...))   # line 107
mgr.set_confirmation_guard(guard)                                                        # line 112
```

### Integration Points
| New Component | Connects To | Via | Verified At |
|---|---|---|---|
| `OdooAgent.agent_tools()` | `OdooToolkit.get_tools()` + `PageIndexToolkit.get_tools()` | list concat | backup/odoo.py:82, toolkit pattern |
| `OdooAgent.configure()` | `ToolManager.register_toolkit()` | WorkingMemoryToolkit | porygon.py:437 |
| `OdooAgent.configure()` | `ToolManager.set_confirmation_guard()` | ConfirmationGuard | manager.py:338, workday_checkin.py:112 |
| `OdooAgent.configure()` | `register_kb(UserInfo())` | always-active KB | abstract.py:962, user.py:11 |
| `OdooAgent` | `_configure_skill_registry()` | SkillRegistryMixin | porygon.py:442, mixin.py |
| new shell tools | `OdooToolkit.confirming_tools` | routing_meta flag | toolkit.py:264-276,575-578 |

### Does NOT Exist (Anti-Hallucination)
- ~~`PageIndex` class~~ — there is NO `PageIndex` class; it's a dict validated by
  `PageIndexTree`/`PageIndexNode` schemas. Use `PageIndexToolkit` + `build_page_index`.
- ~~built-in PageIndex agent mixin / `agent.register_pageindex()`~~ — does not exist;
  attach via `agent_tools()` returning `PageIndexToolkit.get_tools()`.
- ~~`toolkit.save_learning()`~~ — does not exist; use `insert_content` / `insert_markdown`.
- ~~existing `odoo-bin`/`odoo-cli`/shell tools in `OdooToolkit`~~ — RPC-only today; the
  shell tools in Module 1 are NEW.
- ~~`enable_user_info` / `enable_userinfo` agent flag~~ — does not exist; enablement is
  `register_kb(UserInfo())` (UserInfo declares `always_active=True`).
- ~~`gemini-3.5-flash` as a literal enum member name~~ — the **value** is
  `"gemini-3.5-flash"`; the member is `GoogleModel.GEMINI_3_5_FLASH`.
- ~~`SkillRegistryMixin` already mixed into `Agent`~~ — it is NOT; it must be added to the
  class bases explicitly (as porygon does).

---

## 7. Implementation Notes & Constraints

### Patterns to Follow
- Mixin ordering: `class OdooAgent(SkillRegistryMixin, Agent)` (mixins first), per porygon.
- Register heavy toolkits (WorkingMemory) and the ConfirmationGuard inside `configure()`,
  *after* `super().__init__`/before `super().configure()` as appropriate; load skills at
  the end of `configure()` via `await self._configure_skill_registry()`.
- `OdooToolkit` from `ODOO_TEST_*` env (`os.getenv(...)`), `verify_ssl=False`, exactly as
  `agents/backup/odoo.py`. Do NOT use the staging `ODOO_*` vars.
- All new shell tools: `asyncio.create_subprocess_exec` (argv list, never `shell=True`),
  explicit timeout, captured stdout/stderr into a typed result, input validation/whitelist.
- async/await throughout; `self.logger` for logging; Pydantic `@tool_schema` inputs.
- Build the PageIndex **offline** (script) and load the persisted tree at runtime — never
  ingest PDFs on the request path.

### Known Risks / Gotchas
- **`/agents/` is git-ignored** (`.gitignore:267`). *Resolved (OQ1)*: this feature
  **temporarily removes the `/agents/` rule** so `agents/oddie.py`, `agents/odoo_agent/skills/`,
  and the generated `agents/odoo_agent/docs/` are tracked while the feature is built. Caveat:
  un-ignoring `/agents/` surfaces **every** existing agent dir in `git status` — staging must
  be surgical (only the FEAT-240 files), and large generated PDFs should be reconsidered for a
  tracked path or Git LFS before commit. Restore/re-scope the ignore once the feature lands.
- **Shell tools require a co-located Odoo** with the binary reachable (`odoo-bin`/`odoo-cli`).
  When `ODOO_BIN` is unset/unreachable the tools must self-disable gracefully. They are a
  real attack surface → HITL-gated + input-validated + no `shell=True` + subcommand whitelist.
- **HITL needs a `HumanInteractionManager` + channel.** `ConfirmationGuard` requires a store
  and (for real prompts) a human manager. How the agent obtains the human manager/channel at
  runtime (handler-provided vs constructed in `configure()`) is unresolved (§8 OQ2).
- **PDF licensing/attribution** for the official Odoo docs must be respected when the feature
  sources/converts them (§8 OQ3).
- **PageIndex build cost**: ingesting 3 full doc sets is LLM-heavy and slow — it's an offline
  one-time/periodic job, not per-request. Use a lightweight adapter model for summaries.
- **Existing registered `odoo_agent`**: `agents/backup/odoo.py` also registers
  `name="odoo_agent"` at startup. Ensure only one is loaded (backup/ should not be on the
  load path) to avoid a registry name collision.

### External Dependencies
| Package | Version | Reason |
|---|---|---|
| `pymupdf4llm` | (existing) | PDF→markdown extraction used by PageIndex `import_pdf` |
| Odoo docs toolchain | TBD | Sourcing/converting official docs to PDF (Module 2) — pin in impl |

---

## 8. Open Questions

> Resolved items carry `[x]` with the decision; unresolved items `[ ]` block or are
> deferred to implementation.

- [x] **odoo-cli / odoo-bin handling** — *Resolved by user (2026-06-16)*: **Add shell-exec
      toolkit functions** to `OdooToolkit` (subprocess-based, HITL-gated, require a co-located
      Odoo). Reflected in Module 1, G9, AC10.
- [x] **Odoo documentation source** — *Resolved by user (2026-06-16)*: **The feature
      generates the docs from the official Odoo documentation repo**
      (`github.com/odoo/documentation`), per-version branch (`16.0`/`18.0`/`19.0`) via
      `make latexpdf`. Reflected in Module 2, G2, AC4.
- [x] **OQ3 — Doc licensing** — *Resolved (2026-06-16)*: docs are generated locally from the
      official open Odoo documentation repository (not redistributed third-party PDFs); only
      the generated PDFs land in the agent's local `docs/` dir. No bundling of proprietary
      assets.
- [x] **OQ1 — Versioning of agent assets** — *Resolved by user (2026-06-16)*: **temporarily
      remove the `/agents/` rule from `.gitignore`** so `agents/oddie.py`, the skills, and the
      generated docs/PageIndex can be tracked while this feature is built. Restore (or
      re-scope) the ignore afterwards. See §7 Known Risks and Worktree Strategy.
- [x] **OdooToolkit credentials** — *Resolved by user (2026-06-16)*: use the **`ODOO_TEST_*`**
      env vars registered in `env/.env`. Reflected in G8, AC3, §6/§7.
- [x] **HITL scope** — *Resolved from request*: confirm **write operations** on Odoo →
      interpreted as all write/delete RPC tools plus all shell tools. Reflected in G6/AC8.
- [x] **OQ2 — HITL human channel** — how does `OdooAgent` obtain the `HumanInteractionManager`
      / confirmation channel at runtime (handler-injected vs constructed in `configure()`)?
      *Owner: Jesus Lara*: constructed in configure()
- [x] **OQ4 — PageIndex storage_dir** — exact persisted location and whether one tree (with
      version parent nodes) or three trees (one per version). *Owner: implementer* (spec
      recommends one tree with `Odoo 16/18/19` + `CLI` parent nodes): path: agent/odoo_agent/documentation/ and per-odoo tree inside of that directory.

---

## Worktree Strategy

- **Default isolation unit**: `per-spec` — all tasks run sequentially in one worktree
  (`feat-240-odoo-pageindex-documentation-agent`).
- **Parallelizable sub-tasks** (could be split if desired): Module 2 (doc fetching) and
  Module 1 (shell tools) are independent of each other; Module 3 depends on Module 2;
  Modules 4/5 depend on 1 & 3; Modules 6/7 (skills) are independent docs. Given the heavy
  cross-wiring in the agent, a single sequential worktree is recommended.
- **Cross-feature dependencies**: none — builds entirely on already-merged components
  (`OdooToolkit`, PageIndex, skills, working memory, confirmation, UserInfo KB).
- **Gotcha**: the `/agents/` ignore is being temporarily removed (OQ1), so agent files become
  trackable — but `git status` will show all other agent dirs too. Stage only FEAT-240 files;
  restore/re-scope the ignore after the feature merges.

---

## Revision History

| Version | Date | Author | Change |
|---|---|---|---|
| 0.1 | 2026-06-16 | Jesus Lara | Initial draft (FEAT-240) — research-grounded codebase contract; user-resolved decisions on shell tools, doc bundling, ODOO_TEST_* creds |
