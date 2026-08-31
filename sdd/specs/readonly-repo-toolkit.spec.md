---
# SDD flow type and base branch (FEAT-145).
# - type: feature  (default)  → base_branch: dev (or any non-main branch)
# - type: hotfix              → base_branch MUST be: main
type: feature
base_branch: dev
---

# Feature Specification: ReadOnlyRepoToolkit — Safe Repo Grounding for Any Client

**Feature ID**: FEAT-484
**Date**: 2026-08-31
**Author**: Jesus Lara
**Status**: draft
**Target version**: next
**Brainstorm**: `sdd/proposals/devflow-complementary-research.brainstorm.md` (Option A, Modules 1–2)
**Split from**: `sdd/specs/devflow-complementary-research.spec.md` (FEAT-482, §8 Q2 resolved)

---

## 1. Motivation & Business Requirements

### Problem Statement

AI-Parrot can point many kinds of model at a repository — Bedrock Converse seats,
Gemini, local LLMs, any `AbstractClient` — but it has **no safe, reusable way to let
one read that repository**. Today the only cwd-confined repo readers in the codebase
are **private methods on a dispatcher**: `LLMCodeDispatcher._tool_read_file`
(`dispatchers/llm.py:662`), `_tool_list_files` (`:677`) and `_tool_search_files`
(`:691`). They are not a toolkit, not importable, and are welded to an
OpenAI-chat-completions dispatch loop. Anything that is not that dispatcher gets
nothing.

The consequence shows up wherever a non-CLI model needs repo grounding.
`NovaAdversarialReviewDispatcher` (`dispatchers/nova.py:240`) is documented as
"read-only BY CONSTRUCTION: no tools are ever passed to the model" — the diff is
pasted into the prompt because there is no safe tool surface to hand it. That is a
sound design given what exists, but it means the reviewer cannot look at anything
the prompt author did not anticipate.

Two further gaps make a naive implementation the wrong answer:

1. **Grep is a poor search primitive for an agent.** It matches literal strings only,
   returns unranked `path:line` hits the model must then open files to interpret, and
   happily searches build artifacts. Measured on this repo: `grep -rn` for one symbol
   returned 23 hits including duplicates from
   `packages/ai-parrot/build/lib.linux-x86_64-cpython-311/`.
2. **A code graph already exists and is unused by any agent tool.** The wiki plane
   indexes Python via stdlib `ast` (`wiki/languages/python.py:30`) and
   PHP/JS/TS/Rust/Perl via tree-sitter, builds cross-file `references` edges
   (`repo_scan.py:718`), and is queryable over FTS5/BM25 (`wiki/search.py:32`). Live
   plane, verified 2026-08-31: **11518 pages, 18844 edges, 548 MB**, 10442 sources
   tracked with incremental git-post-commit rebuilds. The same query returned 12
   ranked, deduplicated, build-artifact-free results in **~592 tokens**.

So the gap is not "we need a grep tool". It is: **a read-only, cwd-confined toolkit
that prefers the existing code graph over grep, and that any client can be given.**

Its first consumer is FEAT-482 (`devflow-complementary-research`), whose Nova 2
research partner needs exactly this. It is specified separately because it is
independently valuable, independently reviewable, and carries this initiative's real
security weight: it grants a hosted model read access to a checkout.

### Goals

- Ship `ReadOnlyRepoToolkit`, an `AbstractToolkit` registerable on any
  `AbstractClient`, giving cwd-confined read access across four grounding axes.
- Make it **read-only by construction** — no write tool exists to misconfigure.
- Make `search_code` **graph-backed** over the existing wiki plane, with `grep_files`
  as an explicit fallback rather than the default.
- Resolve the plane correctly from inside a **git worktree** without rebuilding it.
- Degrade, never fail: a missing plane, a broken git, or a blocked network reduces
  capability without raising.
- Be usable by consumers beyond FEAT-482 with no dev-flow coupling.

### Non-Goals (explicitly out of scope)

- **Any write capability.** No `apply_patch`, no `run_command`, no file creation. Not
  behind a flag, not behind a permission mode — absent.
- **Building or refreshing the code graph.** `wikitoolkit build` and its
  git-post-commit hook own indexing. This toolkit is a pure consumer; if the plane is
  stale or missing, it degrades.
- **The vector/embedding leg of graph search.** Lexical FTS5/BM25 only (FEAT-482 §8
  Q10). Conceptual-recall improvement is a separate follow-up.
- **A new AST parser or language scanner.** `wiki/languages/` already covers Python,
  PHP, JavaScript/TypeScript, Rust and Perl.
- **Any dev-flow / dev-loop wiring.** Constructing, configuring and injecting the
  toolkit is FEAT-482's job. This spec ships the component and its tests only.
- **Sandboxing beyond path confinement.** Resource limits (cgroups, seccomp) are out
  of scope; bounds here are byte-size and timeout.

---

## 2. Architectural Design

### Overview

One `AbstractToolkit` subclass with a confinement core shared by every filesystem-
and subprocess-touching tool.

| Axis | Tools | Backed by |
|---|---|---|
| Structural | `search_code`, `related_code` | `WikiCombinedSearch` (`wiki/search.py:32`) over the AST/tree-sitter plane |
| Static | `read_file`, `list_files`, `grep_files` | New, confinement approach ported from `llm.py:662/677/691` |
| Historical | `git_log`, `git_show`, `git_blame` | New — local `git` via `asyncio.create_subprocess_exec` |
| External | `web_search` | `DdgSearchTool` (`ddgsearch.py:19`), opt-in via constructor |

**Read-only by construction.** The toolkit's method set contains no mutating
operation. `AbstractToolkit._generate_tools()` (`tools/toolkit.py:537`) exposes public
methods as tools, so "no write tool is defined" and "no write tool is reachable" are
the same statement. This mirrors `NovaAdversarialReviewDispatcher`
(`dispatchers/nova.py:240`) — a property of construction, not of configuration.

**Confinement is one code path.** Every tool that resolves a caller-supplied path
funnels through a single `resolve_within_root()` helper: resolve to an absolute real
path (following symlinks), then verify the result is inside `repo_root`. Rejection
returns a structured tool error the model can read and recover from — never an
exception that aborts the loop, and never a silent empty result. Centralizing this is
deliberate: a second implementation is a second chance to get it wrong.

**Graph search first, grep as fallback.** `search_code` queries the plane and returns
ranked, token-budgeted page stubs with API outlines. `grep_files` stays available for
what the plane genuinely cannot answer — regexes, config strings, literals in
unindexed files. When the plane is missing, unbuilt, or errors, `search_code` logs a
warning and transparently serves a `grep_files` result annotated with a
`degraded: true` marker, so the model knows the answer is weaker.

**Worktree plane resolution.** The plane is rooted at a checkout and is large (548 MB
here), so a per-worktree build is a non-starter. `WikiProjectConfig.storage_dir` "may
be absolute, so two repositories can share one" (`wiki/project.py:74`). When
`repo_root` is a git worktree, the toolkit resolves the **main checkout** via
`git rev-parse --path-format=absolute --git-common-dir` and points at its plane. The
partner therefore sees the repo at roughly last-commit state; `git_*` and `read_file`
cover uncommitted edits. This is correct for research (investigating a codebase), and
would be wrong for review (inspecting a diff) — a distinction worth preserving if
this toolkit is later reused by a reviewer.

### Component Diagram

```
                         ReadOnlyRepoToolkit(AbstractToolkit)
                                      │
        ┌──────────────┬──────────────┼──────────────┬──────────────┐
        ▼              ▼              ▼              ▼              ▼
   search_code    read_file      grep_files      git_log       web_search
   related_code   list_files                     git_show      (opt-in)
        │              │              │          git_blame          │
        │              └──────┬───────┴──────────────┘              │
        │                     ▼                                     ▼
        │          resolve_within_root()                     DdgSearchTool
        │          · realpath + containment                  (ddgsearch.py:19)
        │          · symlink escape rejected
        │          · byte + timeout bounds
        ▼
  WikiCombinedSearch(mode="lexical")  ──▶  pages_fts (FTS5)  [store.py:117]
        │                                   AST / tree-sitter plane
        │  plane missing / error
        └──────────────────────────▶ grep_files  +  {"degraded": true}

  plane location:  repo_root is a worktree?
                     yes → main checkout's absolute storage_dir  [project.py:74]
                     no  → repo_root/.parrot/wiki
```

### Integration Points

| Existing Component | Integration Type | Notes |
|---|---|---|
| `AbstractToolkit` | **extends** | `tools/toolkit.py:216`; tools generated by `_generate_tools()` (`:537`), surfaced via `get_tools()` (`:484`) |
| `tool_schema` decorator | **uses** | `tools/decorators.py:39` — Pydantic arg schemas per tool |
| `WikiCombinedSearch` | **uses (unmodified)** | `wiki/search.py:32`, lexical mode; vector leg skipped (no embedder) |
| `WikiRelatedTool` | **delegates to** | `wiki/tools.py:225` for `related_code` |
| `pack_results` | **uses** | token budgeting, as `wiki_search.py:112` does |
| `WikiProjectConfig` | **uses** | `wiki/project.py:402/457` for plane resolution |
| `DdgSearchTool` | **wraps** | `parrot_tools/ddgsearch.py:19`, only when `enable_web_search=True` |
| `AbstractClient.tools` | **registered into** | `clients/base.py:355`; executed via `_execute_tool` (`:1454`) |
| `LLMCodeDispatcher._tool_*` | **pattern source only — unmodified** | Confinement approach ported, not imported (they are private) |

### Data Models

```python
class RepoSearchHit(BaseModel):
    """One ranked result from search_code."""
    page_id: str
    path: str
    summary: str = ""
    outline: list[str] = []      # API outline lines, when the page has one
    score: float = 0.0
    approx_tokens: int = 0


class RepoSearchResult(BaseModel):
    """search_code / related_code envelope."""
    query: str
    hits: list[RepoSearchHit] = []
    degraded: bool = False        # True when served by the grep fallback
    degraded_reason: str = ""
    total_tokens: int = 0


class RepoReadResult(BaseModel):
    path: str
    content: str
    truncated: bool = False
    total_bytes: int = 0


class RepoToolError(BaseModel):
    """Structured, model-readable rejection. NEVER raised as an exception."""
    error: str                    # "path_outside_root" | "not_found" | "timeout" | ...
    detail: str
    path: str = ""
```

### New Public Interfaces

```python
class ReadOnlyRepoToolkit(AbstractToolkit):
    """Cwd-confined, write-free repository access for any AbstractClient."""

    def __init__(
        self,
        *,
        repo_root: Path,
        wiki_store: Optional[object] = None,
        wiki_name: str = "parrot",
        enable_web_search: bool = False,
        max_result_bytes: int = 64_000,
        max_search_hits: int = 12,
        search_budget_tokens: int = 4_000,
        command_timeout: float = 20.0,
    ) -> None: ...

    async def search_code(self, query: str, top_k: int = 12) -> RepoSearchResult: ...
    async def related_code(self, page_id: str) -> RepoSearchResult: ...
    async def read_file(self, path: str, start: int = 1, end: int = 0) -> RepoReadResult: ...
    async def list_files(self, path: str = ".", depth: int = 1) -> dict[str, Any]: ...
    async def grep_files(self, pattern: str, glob: str = "") -> RepoSearchResult: ...
    async def git_log(self, path: str = "", limit: int = 20) -> dict[str, Any]: ...
    async def git_show(self, ref: str) -> dict[str, Any]: ...
    async def git_blame(self, path: str, start: int = 1, end: int = 0) -> dict[str, Any]: ...
    async def web_search(self, query: str, max_results: int = 5) -> dict[str, Any]: ...


def resolve_within_root(root: Path, candidate: str) -> Path:
    """Resolve `candidate` and assert containment in `root`.

    Raises:
        PathOutsideRootError: Resolved path (after following symlinks) is not
            inside `root`. Callers convert this to a RepoToolError.
    """


def resolve_plane_root(repo_root: Path) -> Path:
    """Return the checkout whose wiki plane should be queried.

    For a git worktree this is the MAIN checkout (via `git rev-parse
    --git-common-dir`), so a 548 MB plane is shared rather than rebuilt.
    """
```

---

## 3. Module Breakdown

### Module 1: Confinement core + `read_file` / `list_files`
- **Path**: `packages/ai-parrot/src/parrot/tools/repo/__init__.py`,
  `confinement.py`, `toolkit.py`
- **Responsibility**: package scaffold; `resolve_within_root()` with realpath +
  containment (rejecting `..` traversal **and** symlink escape);
  `PathOutsideRootError`; the `ReadOnlyRepoToolkit` class with `read_file` and
  `list_files`; byte bounds via `max_result_bytes` with explicit truncation markers;
  `RepoReadResult` / `RepoToolError`.
- **Depends on**: `AbstractToolkit` (`tools/toolkit.py:216`), `tool_schema`
  (`tools/decorators.py:39`).

### Module 2: `grep_files` — bounded literal search
- **Path**: `parrot/tools/repo/toolkit.py`
- **Responsibility**: pattern search confined to `repo_root`, hit-count and byte
  bounded, timeout bounded, executed with `asyncio.create_subprocess_exec` (never
  `shell=True`, never blocking `subprocess.run`). Honors `.gitignore` by preferring
  `git grep` when the root is a work tree. Child processes terminated on cancellation.
- **Depends on**: Module 1.

### Module 3: Local git history tools
- **Path**: `parrot/tools/repo/git_tools.py`
- **Responsibility**: `git_log`, `git_show`, `git_blame` over the local checkout —
  argv-list invocation only, output byte- and timeout-bounded, refs validated, path
  arguments confined via Module 1. **Not** `parrot_tools/gittoolkit.py`, which is a
  GitHub API toolkit (see §6 Does NOT Exist).
- **Depends on**: Module 1.

### Module 4: Graph-backed `search_code` / `related_code`
- **Path**: `parrot/tools/repo/graph_search.py`
- **Responsibility**: `resolve_plane_root()` (worktree → main checkout via
  `git rev-parse --git-common-dir`, honoring an absolute `storage_dir`,
  `project.py:74`); open the plane; query `WikiCombinedSearch` in **lexical** mode;
  pack with `pack_results` under `search_budget_tokens`; map to
  `RepoSearchHit`/`RepoSearchResult`; delegate `related_code` to `WikiRelatedTool`
  (`wiki/tools.py:225`). **Degrade to `grep_files` with `degraded=True` and a logged
  warning** on missing/unbuilt plane or any query error.
- **Depends on**: Modules 1, 2.

### Module 5: `web_search` opt-in + packaging and docs
- **Path**: `parrot/tools/repo/toolkit.py`, `docs/`
- **Responsibility**: wrap `DdgSearchTool` (`ddgsearch.py:19`) behind
  `enable_web_search`; when `False` the method is not exposed as a tool at all (not
  merely erroring), preserving the by-construction property for the egress axis too.
  Document the toolkit, its bounds, the degradation contract, and the worktree plane
  behavior.
- **Depends on**: Modules 1–4.

---

## 4. Test Specification

### Unit Tests

| Test | Module | Description |
|---|---|---|
| `test_toolkit_exposes_no_write_tools` | 1 | `get_tools()` contains no `apply_patch`/`run_command`/`write`/`edit`-shaped name |
| `test_resolve_within_root_accepts_nested` | 1 | Ordinary nested path resolves |
| `test_resolve_within_root_rejects_parent_traversal` | 1 | `../../etc/passwd` → `PathOutsideRootError` |
| `test_resolve_within_root_rejects_symlink_escape` | 1 | Symlink inside root pointing outside → rejected |
| `test_resolve_within_root_rejects_absolute_outside` | 1 | `/etc/passwd` → rejected |
| `test_read_file_truncates_at_byte_bound` | 1 | Oversized file truncated, `truncated=True`, marker present |
| `test_path_rejection_returns_structured_error` | 1 | Returns `RepoToolError`, does not raise |
| `test_list_files_confined_and_depth_bounded` | 1 | Does not escape root; respects `depth` |
| `test_grep_files_respects_gitignore` | 2 | Build artifacts / ignored paths absent from hits |
| `test_grep_files_no_shell_injection` | 2 | Pattern `; rm -rf /` is a literal pattern, not a shell command |
| `test_grep_files_timeout_terminates_child` | 2 | Hanging child cancelled; no orphan process |
| `test_git_log_bounded_and_confined` | 3 | Limit honored; path argument confined |
| `test_git_show_rejects_argv_injection` | 3 | Ref beginning `--upload-pack=` rejected |
| `test_git_tools_degrade_outside_git_repo` | 3 | Non-repo root → structured error, no raise |
| `test_search_code_queries_plane_not_grep` | 4 | `WikiCombinedSearch.search` called; no grep subprocess spawned |
| `test_search_code_lexical_mode_no_embedder` | 4 | Vector leg skipped (`search.py:202`) |
| `test_search_code_degrades_to_grep_when_plane_missing` | 4 | `degraded=True`, reason set, hits still returned, warning logged |
| `test_search_code_respects_token_budget` | 4 | `total_tokens <= search_budget_tokens` |
| `test_related_code_delegates_to_wiki_related_tool` | 4 | `WikiRelatedTool` invoked |
| `test_resolve_plane_root_from_worktree` | 4 | Worktree → main checkout path; **no plane build attempted** |
| `test_resolve_plane_root_plain_checkout` | 4 | Non-worktree → own `.parrot/wiki` |
| `test_web_search_absent_when_disabled` | 5 | Not present in `get_tools()` when `enable_web_search=False` |
| `test_web_search_present_when_enabled` | 5 | Present and delegates to `DdgSearchTool` |

### Integration Tests

| Test | Description |
|---|---|
| `test_toolkit_registers_on_client` | Registered on a stub `AbstractClient`; `_execute_tool` dispatches each tool by name |
| `test_search_then_read_flow` | `search_code` hit → `read_file` on its path succeeds within bounds |
| `test_toolkit_against_real_plane` | **Opt-in**, skipped when `.parrot/wiki` is absent: real query returns ranked hits excluding `build/` artifacts |
| `test_worktree_shares_main_plane` | Real `git worktree add` in a tmp repo; toolkit resolves the main plane |

### Test Data / Fixtures

```python
@pytest.fixture
def temp_repo(tmp_path: Path) -> Path:
    """git-init'd repo: nested dirs, an ignored build/ dir, a symlink escaping
    the root, an oversized file, and two commits."""

@pytest.fixture
def temp_worktree(temp_repo: Path) -> Path:
    """A real `git worktree add` off temp_repo — drives plane resolution."""

@pytest.fixture
def stub_wiki_store():
    """Answers search_fts with fixed rows; a variant that raises, driving
    the grep-degradation path."""
```

New test files under `packages/ai-parrot/tests/tools/repo/`:
`test_confinement.py`, `test_readonly_toolkit.py`, `test_git_tools.py`,
`test_graph_search.py`, `test_integration.py`.

---

## 5. Acceptance Criteria

- [ ] All unit tests pass (`pytest packages/ai-parrot/tests/tools/repo/ -v`)
- [ ] `ruff check` and `mypy` clean on all changed files
- [ ] **Read-only by construction**: no write-shaped tool appears in `get_tools()`
      under any constructor configuration — asserted, not assumed
- [ ] **Confinement holds**: parent traversal, absolute outside paths, and symlink
      escape are each rejected as a structured `RepoToolError`, never an exception
      and never a silent empty result
- [ ] **No shell injection**: every subprocess uses an argv list; no `shell=True`
      anywhere in the package
- [ ] **No blocking I/O**: no `subprocess.run` / `time.sleep` / sync file reads in any
      async path; all children terminated on cancellation
- [ ] **Bounded**: every tool result respects `max_result_bytes`; every subprocess
      respects `command_timeout`
- [ ] **Graph search, not grep**: `search_code` spawns no grep subprocess on the happy
      path, and degrades with `degraded=True` when the plane is unavailable
- [ ] **Worktree sharing**: from a real worktree the toolkit resolves the main
      checkout's plane and performs no plane build
- [ ] **Web search is absent, not disabled**, when `enable_web_search=False`
- [ ] Toolkit registers on an `AbstractClient` and every tool dispatches via
      `_execute_tool`
- [ ] No dev-flow / dev-loop import anywhere in `parrot/tools/repo/`
- [ ] No new required dependency
- [ ] Documentation added in `docs/` covering bounds, degradation, and worktree behavior

---

## 6. Codebase Contract

> Anchors verified 2026-08-31 against `dev` after merging `origin/dev`
> (post-FEAT-480, PR #1280).

### Verified Imports

```python
from parrot.tools.toolkit import AbstractToolkit                    # tools/toolkit.py:216
from parrot.tools.decorators import tool_schema                     # tools/decorators.py:39
from parrot.knowledge.wiki.search import WikiCombinedSearch         # wiki/search.py:32
from parrot.knowledge.wiki.tools import WikiQueryTool, WikiRelatedTool  # wiki/tools.py:155/225
from parrot.knowledge.wiki.context import pack_results              # used wiki_search.py:112
from parrot_tools.ddgsearch import DdgSearchTool                    # ddgsearch.py:19
```

### Existing Class Signatures

```python
# packages/ai-parrot/src/parrot/tools/toolkit.py
class AbstractToolkit(ABC):                                          # line 216
    def get_tools(...)                                               # line 484
    def _generate_tools(self) -> None                                # line 537
    async def get_tools_filtered(...)                                # line 574
    def get_tools_sync(...)                                          # line 594
    # Public methods become LLM-callable tools; underscore-prefixed do not.

# packages/ai-parrot/src/parrot/tools/decorators.py
def tool_schema(schema: Type[BaseModel], description: Optional[str] = None)  # line 39

# packages/ai-parrot/src/parrot/clients/base.py
class AbstractClient:
    self.tools: Dict[str, Union[ToolDefinition, AbstractTool]] = {}  # line 355
    async def _execute_tool(...)                                     # line 1454

# packages/ai-parrot/src/parrot/knowledge/wiki/search.py
class WikiCombinedSearch:                                            # line 32
    async def search(self, query, mode=..., top_k=..., tree_name=...)# line 91
    # modes: lexical (FTS5/BM25) | vector (needs embedder) | combined
    # default weights lexical .6 / vector .4                         # line 174
    # vector leg SKIPPED when embedder is None                       # line 202

# packages/ai-parrot/src/parrot/knowledge/wiki/store.py
CREATE VIRTUAL TABLE IF NOT EXISTS pages_fts USING fts5(...)         # line 117
async def search_fts(self, query, category=None, limit=10)           # line 1147
async def search_vector(self, embedding, limit=10)                   # line 1195

# packages/ai-parrot/src/parrot/knowledge/wiki/tools.py   (FEAT-403 Module 5)
class WikiQueryTool(AbstractTool):                                   # line 155
class WikiPageTool(AbstractTool):                                    # line 190
class WikiRelatedTool(AbstractTool):                                 # line 225
class WikiStatusTool(AbstractTool):                                  # line 409
def create_wiki_tools(store, root=None, config=None) -> list[AbstractTool]  # line 541

# packages/ai-parrot/src/parrot/knowledge/wiki/project.py
    storage_dir: str = Field(default=f"{PARROT_DIR}/wiki")           # line 402
    def storage_path(self, root: Path) -> Path                       # line 457
    # ":74 — storage_dir may be absolute, so two repositories can share one"

# packages/ai-parrot/src/parrot/knowledge/wiki/repo_scan.py   (indexing — consumed, not called)
def discover_repo_files(...)  # 355     def _git_ls_files(root)      # 398
def build_file_slice(...)     # 556     def build_dir_pages(...)     # 645
def build_import_edges(...)   # 718     def scan_repository(...)     # 776

# packages/ai-parrot/src/parrot/knowledge/wiki/languages/python.py
class PythonScanner(LanguageScanner):                                # line 30
    tree = ast.parse(source, filename=rel_path or "<unknown>")       # line 49

# PATTERN SOURCE ONLY — private, do NOT import:
# packages/ai-parrot/src/parrot/flows/dev_loop/dispatchers/llm.py
    def _tool_read_file(self, cwd, args) -> Dict[str, Any]           # line 662
    def _tool_list_files(self, cwd, args) -> Dict[str, Any]          # line 677
    async def _tool_search_files(...)                                # line 691
    async def _tool_apply_patch(...)   # 723  — deliberately NOT ported
    async def _tool_run_command(...)   # 749  — deliberately NOT ported
```

Live plane verified via `wikitoolkit status` (2026-08-31): sqlite backend, 11518
pages / 18844 edges, 548 MB at `.parrot/wiki`, 10442 sources tracked / 229 stale,
`Languages: {python: ast, php|javascript|rust|perl: tree-sitter}`.

### Integration Points

| New Component | Connects To | Via | Verified At |
|---|---|---|---|
| `ReadOnlyRepoToolkit` | `AbstractToolkit` | subclass; tools from `_generate_tools()` | `tools/toolkit.py:216,537` |
| tool arg schemas | `tool_schema` | decorator | `tools/decorators.py:39` |
| `search_code` | `WikiCombinedSearch.search()` | lexical mode + `pack_results` | `wiki/search.py:32,91` |
| `related_code` | `WikiRelatedTool` | delegation | `wiki/tools.py:225` |
| `resolve_plane_root` | `WikiProjectConfig.storage_path()` | absolute `storage_dir` | `wiki/project.py:74,457` |
| `web_search` | `DdgSearchTool` | delegation, opt-in | `ddgsearch.py:19` |
| toolkit registration | `AbstractClient.tools` / `_execute_tool` | client-side registration | `clients/base.py:355,1454` |

### Does NOT Exist (Anti-Hallucination)

- ~~`ReadOnlyRepoToolkit`~~ / ~~`RepoBrowseToolkit`~~ / ~~`parrot.tools.repo`~~ — the
  entire package is new. No read-only repo toolkit exists anywhere today.
- ~~an importable cwd-confined file reader~~ — the only ones are **private methods**
  on `LLMCodeDispatcher` (`llm.py:662/677/691`). Port the approach; do not import.
- ~~a local-git toolkit~~ — `parrot_tools/gittoolkit.py` is a **GitHub API** toolkit
  (`RepositoryCredential:48`, `CreatePullRequestInput:267`, `SearchRepoCodeInput:438`).
  It offers no `git log`/`show`/`blame` over a local checkout.
- ~~`parrot_tools.code_toolkit.CodeToolkit` as a repo browser~~ — exists
  (`code_toolkit.py:266`) but is a coding-agent-delegation toolkit
  (`implement_spec`, `fix_bug`, `review_diff`, `generate_tests`, `explain_patch`).
- ~~`FileReaderTool` as a safe repo reader~~ — exists (`file_reader.py:31`) but is
  **not** confined to a repo root.
- ~~`GraphIndexToolkit` as the code-search backend~~ — exists
  (`parrot_tools/graphindex/toolkit.py:72`) but requires a prebuilt
  `rustworkx.PyDiGraph` + `faiss.Index` + node maps (`:116`). **Not** the subsystem
  behind `wikitoolkit` code search; that is `parrot/knowledge/wiki/` over SQLite FTS5.
- ~~a need to write an AST parser or code-graph builder~~ — `wiki/languages/` +
  `repo_scan.py` already do this, for five languages, deterministically and offline.
- ~~`wiki_query` tools being absent~~ — **they exist**: `WikiQueryTool`
  (`wiki/tools.py:155`) and five siblings, plus `create_wiki_tools()` (`:541`) and
  `LLMWikiToolkit` (`wiki/toolkit.py:54`). Bind them; do not write new wiki tools.
- ~~an embedder wired into `DevLoopWikiSearch`~~ — none is passed, so the vector leg
  is skipped (`search.py:202`). Lexical only.

---

## 7. Implementation Notes & Constraints

### Patterns to Follow

- Subclass `AbstractToolkit` (`tools/toolkit.py:216`); public methods become tools, so
  keep every helper underscore-prefixed.
- `@tool_schema(SomeInput)` (`decorators.py:39`) for each tool's Pydantic arg schema.
- Mirror `DevLoopWikiSearch.build_research_context`'s best-effort contract
  (`wiki_search.py:91`): warn and return a degraded result, never raise.
- Read-only by **construction** (`dispatchers/nova.py:240`), never by flag.
- Async-first: `asyncio.create_subprocess_exec` with argv lists; never `shell=True`,
  never blocking `subprocess.run`. Terminate children in `finally`/on cancellation.
- Google-style docstrings, strict type hints, Pydantic for all structured data,
  `self.logger` — never `print`.
- Every tool docstring is the LLM's tool description — write them for the model.

### Known Risks / Gotchas

| Risk | Mitigation |
|---|---|
| **Path confinement is the security boundary** — this grants a hosted model read access to a checkout | One `resolve_within_root()` used by every path-taking tool; realpath-based so symlink escape is caught; deny by default. This module deserves the adversarial-review budget |
| Argv injection via a ref or pattern (`--upload-pack=…`) | Validate refs; pass `--` separators; argv lists only; explicit tests |
| Cancellation leaking `git`/grep children | Terminate in `finally`; test asserts no orphan |
| Reading secrets from the checkout (`.env`, keys) | In scope of "read the repo", but worth an explicit ignore list for `.env*` and common key patterns; flagged as §8 Q1 |
| Plane staleness inside a worktree | Accepted and documented: research reads a codebase, not a diff; `git_*`/`read_file` cover uncommitted edits. Would be wrong for a reviewer consumer |
| Silent degradation hiding a broken plane | `degraded=True` + `degraded_reason` are part of the payload the model sees, plus a logged warning — never silent |
| Large repos blowing the token budget | `search_budget_tokens` + `max_search_hits` + `pack_results` |
| `git grep` unavailable (non-repo root) | Fall back to a bounded walk; structured error if that also fails |

### External Dependencies

| Package | Version | Reason |
|---|---|---|
| `parrot.knowledge.wiki` | in-repo | Graph-backed `search_code` over the FTS5 plane |
| `ddgs` (via `parrot_tools.ddgsearch`) | existing | Keyless web search, opt-in |
| `pydantic` | existing | All contracts |
| `git` | system | History axis and `git grep`; degrades if absent |

**No new required dependency.**

---

## Worktree Strategy

- **Default isolation unit**: `per-spec` — all tasks sequential in one worktree.
- **Rationale**: Modules 2–4 all depend on Module 1's confinement core and its
  `RepoToolError` contract. Parallelizing before that contract exists in code would
  mean coordinating it in prose. The module count is small and the sequence is short.
- **Cross-feature dependencies**: **none**. This spec imports nothing from
  `dev_flow`/`dev_loop` and touches no file that FEAT-479 is editing. It can proceed
  fully in parallel with FEAT-479 and FEAT-482's non-toolkit modules.
- **Downstream**: **FEAT-482 depends on this spec** — its research partner registers
  this toolkit. **Merge FEAT-484 before FEAT-482's Module 2** (`NovaResearchPartner`).

```bash
git worktree add -b feat-484-readonly-repo-toolkit \
  .claude/worktrees/feat-484-readonly-repo-toolkit origin/dev
```

---

## 8. Open Questions

- [ ] **Q1 — Should the toolkit refuse to read secrets?** `.env`, `env/.env`,
  `*.pem`, `id_rsa`, `.parrot/wiki.local.json` and similar are inside the repo root
  and therefore readable under the current design. An ignore list is cheap and
  defensible; against it, a research agent legitimately benefits from seeing
  `.env.example` and config *shapes*. Proposed: deny-list actual secret files, allow
  `*.example` / `*.sample`. — *Owner: Jesus Lara*
- [ ] **Q2 — Should `search_code` expose `mode` to the model?** Currently lexical is
  hard-wired. Exposing `mode` would let a future embedder-enabled deployment get
  combined search with no signature change, but gives the model a knob it has no
  basis to set. Proposed: keep it a constructor argument, not a tool argument.
  — *Owner: Jesus Lara*
- [x] **Q3 — Own spec, or folded into FEAT-482?** — *Resolved*: own spec (this one).
  The toolkit is independently valuable and carries the security weight; FEAT-482
  §8 Q2 records the decision.
- [x] **Q4 — Vector leg in scope?** — *Resolved*: no. Lexical FTS5/BM25 only;
  conceptual recall is a follow-up. Measured basis: symbol/topic queries score
  0.8–1.0, conceptual scored 0.06/0.00 with no embedder.
- [x] **Q5 — Worktree plane strategy?** — *Resolved*: share the main checkout's plane
  via absolute `storage_dir` (`project.py:74`); never build per worktree.

---

## Revision History

| Version | Date | Author | Change |
|---|---|---|---|
| 0.1 | 2026-08-31 | Jesus Lara | Initial draft — split out of FEAT-482 per its §8 Q2 |
