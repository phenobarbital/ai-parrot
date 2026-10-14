---
# SDD flow type and base branch (FEAT-145).
# - type: feature  (default)  → base_branch: dev (or any non-main branch)
# - type: hotfix              → base_branch MUST be: main
type: feature
base_branch: dev
projects: [ai-parrot, ai-parrot-tools]
tags: [github-reviewer, wikitoolkit, code-review, gittoolkit, knowledge-graph]
---

# Brainstorm: GitHubReviewer local clone + wikitoolkit graph

**Date**: 2026-10-15
**Author**: Jesus Lara
**Status**: exploration
**Recommended Option**: A

---

## Problem Statement

`GitHubReviewer` reviews a pull request with exactly two inputs: the Jira
ticket (summary, description, acceptance criteria) and the PR **diff** fetched
from the GitHub API (`_fetch_diff`, `github_reviewer.py:998`). It never sees
the repository the diff belongs to.

That makes a whole class of review findings structurally impossible:

- *"this changes a function with 40 callers"* — the diff shows the function,
  not its blast radius;
- *"this duplicates an existing helper two modules over"*;
- *"this new toolkit ignores the convention every sibling toolkit follows"*;
- *"the symbol this patch calls does not exist on that class"*.

Meanwhile the repository already owns the machinery that answers exactly those
questions: the **wikitoolkit** knowledge graph (ranked page stubs, symbol
lookup, code outline, blast radius) — but it is built from a *local* checkout.
`find_project_root()` (`project.py:955`) walks up from the CWD looking for
`.parrot/wiki.json` or a `.git` root, and the reviewer is a long-lived agent in
an aiohttp server whose CWD is whatever directory gunicorn was started in. It
has no local copy of `GITHUB_REVIEW_REPOSITORY` (`conf.py:767`) at all.

**Who is affected**: every deployment that runs a `GitHubReviewer` subclass
per watched repository; indirectly the humans reading its PR reviews, who today
get criteria-vs-diff verdicts with no codebase awareness.

**Why now**: both halves already exist and are already paid for.
`GitToolkit.clone_repo()` shipped with FEAT-250 (`gittoolkit.py:1590`) and is
idempotent and token-scrubbed; every wikitoolkit CLI command already takes an
explicit `--path` (`cli.py:149`), so `find_project_root()` is only the fallback
and does **not** need to change. What is missing is the ~200 lines of wiring
between them.

---

## Constraints & Requirements

Decided with the owner during discovery (Rounds 0–3):

- **Flow**: `type: feature`, `base_branch: dev`.
- **The graph is an enrichment, never a gate.** Clone or build failure ⇒ log
  and fall back to today's diff-only review. Same degradation contract as
  `DevLoopWikiSearch.from_project()` (`wiki_search.py:40`), which returns
  `None` and lets every caller no-op.
- **Build runs as a subprocess** (`wikitoolkit build --path <clone>`), not as
  an in-process call. No refactor of wikitoolkit core in this feature.
- **One persistent clone + one persistent plane per repository**, refreshed
  incrementally — not a fresh clone per PR.
- **The clone tracks the repository's base branch only.** PR head refs
  (including fork heads) are out of scope; the proposed code still arrives as
  the diff.
- **Warm-up at startup**: clone + build kick off in `post_configure()`
  (`github_reviewer.py:503`) without blocking agent startup; each PR event
  refreshes incrementally before the review.
- **The graph plane lives outside the clone**, at an absolute `storage_dir`,
  so the reviewed repository's working tree is never polluted and its own
  `.parrot/` is never touched.
- **Builds are serialized per repository** (an `asyncio.Lock` per repo), because
  `wiki_write_lock` (`project.py:76`) refuses a second concurrent writer and
  `build` exits with status 1 when it cannot acquire it.
- **The reviewer gets the full wiki surface**: `CodeStructuralToolkit` tools,
  prompt-injected ranked context, *and* the complete `LLMWikiToolkit`
  (`toolkit.py:43`) with no confinement — owner's explicit decision, recorded
  as a risk in Open Questions rather than as a blocker.
- No new runtime dependency: `wikitoolkit` is a core console script
  (`pyproject.toml:204`), the build is deterministic and **offline** (no LLM —
  see the `build` docstring, `cli.py:1573`), so enrichment costs CPU/IO, not tokens.
- Must keep working for a reviewer whose repository is **private** (clone must
  authenticate with the same PAT / GitHub App the toolkit already holds).

---

## Options Explored

### Option A: Persistent per-repo clone + CLI build, orchestrated by the agent

The reviewer owns a cache directory. On `post_configure()` it schedules a
background warm-up task: `GitToolkit.clone_repo(GITHUB_REVIEW_REPOSITORY,
dest_dir=<cache>/<owner>-<repo>, private=True)` followed by
`wikitoolkit build --path <clone>` as a subprocess, with `storage_dir` pointed
at an absolute directory outside the clone. On every PR event the same pair
runs again — `clone_repo` detects an existing clone and delegates to
`pull_repo` (fast-forward), and `build` re-ingests only stale files — guarded
by a per-repository `asyncio.Lock`. The resulting root is then handed to
`CodeStructuralToolkit(root=...)` and `LLMWikiToolkit`, attached through the
existing `_attach_toolkit()` (`github_reviewer.py:568`), plus a ranked-context
block spliced into the question built by `_ask_llm_for_review()`
(`github_reviewer.py:1031`).

✅ **Pros:**
- Nothing in wikitoolkit core changes; `--path` already exists for every command.
- Second and later PRs are cheap: `pull` + incremental ingest, no re-clone, no re-scan.
- Failure is naturally local — a non-zero exit code degrades the review, nothing else.
- Reviewer stays a single process; no new service to operate.

❌ **Cons:**
- Depends on `wikitoolkit` being resolvable on the server process's PATH/venv.
- Subprocess error handling is exit-code granularity; stdout is unstructured
  (and the navconfig banner pollutes it — see Open Questions).
- Keeps a working copy of every watched repository on the server's disk
  (retention/GC is an operational concern).
- First warm-up on a large repository is a multi-minute scan.

📊 **Effort:** Medium

📦 **Libraries / Tools:**
| Package | Purpose | Notes |
|---|---|---|
| `wikitoolkit` (console script) | Build the graph over the clone | Ships in core: `parrot.knowledge.wiki.entry:main` (`pyproject.toml:204`) |
| `git` / `gh` CLI | Clone / fast-forward | Already required by `clone_repo`; `gh` optional, preferred for private repos |
| `asyncio` (stdlib) | Per-repo serialization + background warm-up | No new dependency |

🔗 **Existing Code to Reuse:**
- `packages/ai-parrot-tools/src/parrot_tools/gittoolkit.py:1590` — `clone_repo()`, idempotent, token-scrubbed.
- `packages/ai-parrot-tools/src/parrot_tools/gittoolkit.py:1653` — `pull_repo()`, fast-forward only.
- `packages/ai-parrot/src/parrot/knowledge/wiki/structural/toolkit.py:44` — `CodeStructuralToolkit(root=...)`.
- `packages/ai-parrot/src/parrot/knowledge/wiki/toolkit.py:77` — `LLMWikiToolkit`.
- `packages/ai-parrot/src/parrot/flows/dev_loop/wiki_search.py:40` — `DevLoopWikiSearch.from_project(root=...)` as the prompt-injection pattern *and* as the degradation contract.
- `packages/ai-parrot/src/parrot/bots/github_reviewer.py:568` — `_attach_toolkit()`.

---

### Option B: Ephemeral shallow clone + throwaway plane per PR

Each PR event clones into a temporary directory (`depth=1`), builds a graph,
runs the review, and deletes both. No cache, no cross-delivery state.

✅ **Pros:**
- Perfect isolation: concurrent PRs never contend, no lock needed.
- No disk retention policy, no stale-clone class of bug.
- Trivially correct after a force-push or a branch rename.

❌ **Cons:**
- Pays a **full** clone + full scan on every delivery; the incremental-ingest
  machinery (fingerprints, staleness) never gets to help.
- Pushing N commits to a PR means N full builds (the SHA-dedup at
  `github_reviewer.py:811` helps only for identical SHAs).
- Review latency becomes repository-size-dependent, in the webhook path.
- A shallow clone weakens git-based file discovery; `--no-git` loses
  `.gitignore` honouring.

📊 **Effort:** Low–Medium

📦 **Libraries / Tools:**
| Package | Purpose | Notes |
|---|---|---|
| `tempfile` (stdlib) | Per-PR scratch dir | Cleanup on every exit path, including errors |
| `wikitoolkit` | Build | Same as Option A |

🔗 **Existing Code to Reuse:** same set as Option A, minus the cache/lock layer.

---

### Option C: Extract a programmatic `build_wiki()` and orchestrate in-process

Lift the build pipeline out of the click callback (`cli.py:1560`, whose core is
the nested `_pipeline()`) into a reusable coroutine — `build_wiki(root, config,
*, force, no_export, ...)` — that both the CLI and the reviewer call. The agent
then builds in-process: no subprocess, no PATH dependency, structured
exceptions and a real return value instead of an exit code.

✅ **Pros:**
- Testable end-to-end from pytest without spawning processes.
- Real error objects and counts; progress/telemetry become observable.
- Pays off well beyond this feature (dev-loop, MCP server, future agents).
- No PATH / venv coupling between the aiohttp server and a console script.

❌ **Cons:**
- Touches wikitoolkit core, whose `build` command carries a lot of accumulated
  behaviour (vault mode, Roblox enrichment, language fingerprints, OKF export,
  graph.html, remote push). Blast radius well beyond the reviewer.
- Turns a reviewer feature into a refactor feature — different review bar,
  different risk profile.
- The build holds the event loop's attention unless carefully offloaded; a
  subprocess gets isolation for free.

📊 **Effort:** High

📦 **Libraries / Tools:**
| Package | Purpose | Notes |
|---|---|---|
| — | No new dependency | Pure refactor of `parrot/knowledge/wiki/cli.py` |

🔗 **Existing Code to Reuse:**
- `packages/ai-parrot/src/parrot/knowledge/wiki/cli.py:1560` — `build` callback + nested `_pipeline()`, the code to extract.
- `packages/ai-parrot/src/parrot/knowledge/wiki/project.py:76` — `wiki_write_lock()`, which the extracted function must keep honouring.

---

### Option D (unconventional): A shared wiki-cache sidecar; the reviewer only reads

Nobody builds inside the reviewer. A separate long-lived component — a small
daemon, a cron job, or `wikitoolkit serve` in remote mode — maintains clones
and planes for N repositories and publishes them through a shared backend
(`backend=arangodb`, one database per repo, already supported by
`WikiProjectConfig`). Every `GitHubReviewer` subclass becomes a pure **reader**:
it opens the store for its repository and attaches the toolkits, never cloning
and never building.

✅ **Pros:**
- Scales to many reviewer subclasses and many processes without N clones or N locks.
- Build load moves off the webhook path entirely — review latency becomes
  constant-time regardless of repository size.
- Survives ephemeral server disks (containers, autoscaling) because the plane
  is in a database, not on a local filesystem.
- Other agents (dev-loop, chatbots, MCP) can read the same planes.

❌ **Cons:**
- A new operational component to deploy, monitor and secure — the single
  biggest cost, and unjustified while there is one reviewer on one repo.
- Freshness becomes eventual: the reviewer may read a plane that is minutes or
  hours behind the PR's base.
- Requires an ArangoDB (or the remote wiki server) in the deployment, which
  today's reviewer does not need.

📊 **Effort:** High

📦 **Libraries / Tools:**
| Package | Purpose | Notes |
|---|---|---|
| ArangoDB | Shared retrieval plane | `backend="arangodb"` already supported (`project.py:605`) |
| `wikitoolkit serve` / remote mode | Hosted plane + push | Needs `ai-parrot[wikitoolkit-server]` |

🔗 **Existing Code to Reuse:**
- `packages/ai-parrot/src/parrot/knowledge/wiki/structural/toolkit.py:44` — accepts a pre-built `store=`, so a reader-only wiring is already expressible.

---

## Recommendation

**Option A** — persistent per-repo clone, CLI build as a subprocess, per-repo
serialization, read side wired through the existing toolkits.

Why, concretely:

- It is the only option where **no existing code changes shape**. `clone_repo`
  already does the cloning *and* the idempotent refresh; `--path` already makes
  every wikitoolkit command root-agnostic; `CodeStructuralToolkit`,
  `LLMWikiToolkit` and the `DevLoopWikiSearch` pattern already accept an
  explicit root. The feature is wiring plus configuration, which is the right
  size for a capability whose value is still unproven in production.
- Against **B**: the incremental machinery is the whole economic argument. A
  reviewer that rebuilds from scratch on every webhook delivery puts a
  repository-size-dependent cost directly in the latency path, and gains
  isolation we can get more cheaply with one lock.
- Against **C**: extracting `build_wiki()` is the better *engineering* outcome
  and should happen — but it is a wikitoolkit-core refactor with a much larger
  blast radius than a reviewer enrichment, and bundling it here means the
  reviewer feature inherits its review bar and its risk. Split it: ship A, and
  file the extraction as its own feature. The subprocess boundary is a seam we
  can replace later without touching the reviewer's own logic.
- Against **D**: it is the right architecture at N repositories and M reader
  processes, and the wrong one at 1 and 1. Option A's cache layout (one
  directory per `owner-repo`, absolute `storage_dir`) is deliberately
  compatible with D, so the sidecar can take over later by pointing at the same
  planes.

**What we are trading off, explicitly:** (1) the server process must be able to
resolve the `wikitoolkit` console script, which couples the deployment to the
venv layout; (2) disk grows with the number and size of watched repositories,
and nothing in this feature reclaims it; (3) the graph reflects the **base
branch**, so a symbol the PR itself introduces is absent from it — the reviewer
must be told so in its prompt, or it will confidently report a new function as
nonexistent. That last one is the sharpest edge of this design and belongs in
the spec's acceptance criteria, not in a footnote.

---

## Feature Description

### User-Facing Behavior

For the operator: three or four new settings (names TBD in the spec) —
a cache directory for clones, a directory for graph planes, an on/off switch,
and optionally a build timeout. With them unset the reviewer behaves exactly as
it does today, so the feature is opt-in and backwards compatible.

For the human reading the PR review: findings that reference the codebase and
not just the diff — "`AbstractClient.ask()` has 23 call sites; this signature
change is breaking", "a helper with this behaviour already exists at
`parrot/x/y.py`", "every sibling toolkit sets `tool_prefix`; this one does not".
When the graph is unavailable the review looks exactly like today's.

### Internal Behavior

1. **Warm-up (startup).** `post_configure()`, after building the Git and Jira
   toolkits, schedules a background task: resolve the cache path for
   `GITHUB_REVIEW_REPOSITORY`, `clone_repo(..., private=True)`, then run
   `wikitoolkit build --path <clone>` as a subprocess with the plane's absolute
   `storage_dir`. Agent startup never blocks on it.
2. **Attach (once the plane exists).** `CodeStructuralToolkit(root=<clone>)`
   and `LLMWikiToolkit` are registered through `_attach_toolkit()` and synced to
   the LLM through the existing `sync_tools()` call, so the reviewer can ask
   structural questions mid-review.
3. **Refresh (per PR event).** `review_pull_request()` acquires the repo's
   `asyncio.Lock`, runs `clone_repo` (→ fast-forward `pull_repo`) and an
   incremental `build`, then releases it. Deliveries for the same repository
   queue; deliveries for different repositories do not interact.
4. **Inject (per review).** Before calling the LLM, a ranked, token-budgeted
   context block — the `DevLoopWikiSearch.build_research_context()` shape
   (`wiki_search.py:101`), keyed on the PR's changed paths and title — is
   spliced into the question assembled in `_ask_llm_for_review()`, alongside a
   sentence stating that the graph reflects the base branch and that symbols
   added by this PR are expected to be absent from it.
5. **Degrade.** Any failure in 1–4 logs and leaves the review on today's path.

### Edge Cases & Error Handling

- **`wikitoolkit` not on PATH** → warm-up fails once, logs loudly, feature
  disabled for the process lifetime. Not retried per PR.
- **Clone fails** (bad token, repo renamed, network) → graph disabled; the
  diff-only review still runs.
- **Build exits non-zero because another writer holds `wiki_write_lock`** →
  shouldn't happen behind the per-repo lock, but an external writer (a human
  running `wikitoolkit build` on the same plane) can cause it; treat as a
  soft failure and reuse the existing plane.
- **Build times out** on a very large repository → kill the subprocess, keep
  whatever plane exists, degrade.
- **Clone exists but is not a git repo** (half-deleted cache dir) → `pull_repo`
  raises `GitToolkitError` ("not a git clone"); recovery is to remove and
  re-clone, which the spec must decide (automatic vs. manual).
- **Force-push / rebase of the base branch** → `pull --ff-only` fails; same
  recovery question.
- **PR from a fork, or a PR whose head is not in the clone** → by design; the
  graph answers base-branch questions only, and the prompt says so.
- **Disk exhaustion** → clone/build fail; degrade. No GC in v1 (Open Question).
- **Two reviewer subclasses watching the same repository in one process** →
  must share one cache entry and one lock (key on the repo slug, not on the
  agent instance).
- **Private repository without `gh` installed** → `clone_repo` falls back to a
  token-in-URL clone and scrubs the token from any error; verify nothing logs
  the raw argv.

---

## Capabilities

### New Capabilities
- `github-reviewer-local-clone`: maintain an authenticated, idempotently
  refreshed local clone of the watched repository in a server-side cache.
- `github-reviewer-wiki-context`: build and refresh a wikitoolkit plane over
  that clone, outside the clone's tree, serialized per repository.
- `github-reviewer-structural-review`: expose the structural/wiki toolkits to
  the review LLM and inject ranked base-branch context into the review prompt.

### Modified Capabilities
- `github-repo-weekly-activity-report` — same agent class; no behavioural
  change expected, but `post_configure()` grows a background task that the
  scheduled reports share a process with.

---

## Impact & Integration

| Affected Component | Impact Type | Notes |
|---|---|---|
| `parrot/bots/github_reviewer.py` | modifies | `post_configure()` warm-up, per-repo lock, refresh in `review_pull_request()`, context injection in `_ask_llm_for_review()` |
| `parrot/conf.py` | extends | New `GITHUB_REVIEW_*` settings (cache dir, plane dir, enable flag, build timeout) |
| `parrot_tools/gittoolkit.py` | depends on | `clone_repo` / `pull_repo` used as-is; no change planned |
| `parrot/knowledge/wiki/cli.py` | depends on | Invoked as a subprocess via `--path`; no change planned |
| `parrot/knowledge/wiki/structural/toolkit.py` | depends on | Constructed with an explicit `root=` |
| `parrot/knowledge/wiki/toolkit.py` | depends on | Full `LLMWikiToolkit` surface attached (see risk in Open Questions) |
| `docs/github-reviewer.md` | modifies | Document the new settings and the degradation contract |
| Deployment | modifies | Server needs `git` (and optionally `gh`), the `wikitoolkit` script on PATH, and writable cache + plane directories |

---

## Code Context

### User-Provided Code

None — the owner's input was architectural (Rounds 0–3), captured in
Constraints and Open Questions.

### Verified Codebase References

#### Classes & Signatures

```python
# From packages/ai-parrot-tools/src/parrot_tools/gittoolkit.py:1590
async def clone_repo(
    self,
    repository: str,
    dest_dir: str,
    branch: Optional[str] = None,
    *,
    private: bool = False,
    depth: Optional[int] = None,
) -> Dict[str, Any]:
    """Returns {"path", "repository", "branch", "updated"}; never contains a token.
    If dest_dir already holds a clone, delegates to pull_repo()."""

# From packages/ai-parrot-tools/src/parrot_tools/gittoolkit.py:1653
async def pull_repo(self, repo_path: str, branch: Optional[str] = None) -> Dict[str, Any]:
    """git -C <repo_path> pull --ff-only; raises GitToolkitError if not a clone."""

# From packages/ai-parrot-tools/src/parrot_tools/gittoolkit.py:961
class GitToolkit(...):
    def __init__(
        self,
        default_repository: Optional[str] = None,
        default_branch: str = "main",
        github_token: Optional[str] = None,
        auth_type: Literal["pat", "github_app"] = "pat",
        app_id: Optional[int] = None,
        installation_id: Optional[int] = None,
        private_key: Optional[str] = None,
        private_key_path: Optional[str] = None,
        repositories: Optional[Dict[str, Union[RepositoryCredential, dict]]] = None,
        **kwargs: Any,
    ) -> None: ...

# From packages/ai-parrot/src/parrot/bots/github_reviewer.py:276
class GitHubReviewer(Agent):
    model = "gemini-3.5-flash"                                     # line 332
    self.repository = repository                                   # line 454
    self._reviewed_shas: Dict[Tuple[str, int], str] = {}           # line 487
    async def post_configure(self) -> None: ...                    # line 503
    def _attach_toolkit(self, toolkit: Any, name: str) -> None: ...# line 568
    def _build_git_toolkit(self) -> Optional[GitToolkit]: ...      # line 588
    async def handle_hook_event(self, event: HookEvent) -> Optional[Dict[str, Any]]: ...  # line 757
    async def review_pull_request(self, payload: Dict[str, Any]) -> Dict[str, Any]: ...   # line 788
    async def _fetch_diff(self, repo: str, pr_number: int) -> Tuple[str, bool, bool]: ... # line 998
    async def _ask_llm_for_review(self, *, payload, ticket_key, ticket,
                                  diff_text, diff_truncated, diff_available) -> PRReviewResult: ...  # line 1031

# From packages/ai-parrot/src/parrot/knowledge/wiki/structural/toolkit.py:26
class CodeStructuralToolkit(AbstractToolkit):
    tool_prefix: str = "code"                                      # line 42
    def __init__(self, root: Path | None = None,
                 store: BaseWikiStore | None = None,
                 config: WikiProjectConfig | None = None,
                 **kwargs: Any) -> None: ...                       # line 44
    async def symbol_lookup(...)                                   # line 101
    async def outline(...)                                         # line 127
    async def blast_radius(...)                                    # line 146

# From packages/ai-parrot/src/parrot/knowledge/wiki/toolkit.py:43
class LLMWikiToolkit(AbstractToolkit):
    tool_prefix: str = "wiki"
    def __init__(self, pageindex_toolkit, graphindex_toolkit, okf_toolkit,
                 config: WikiConfig, agent_id: str = "agent",
                 store: Optional[BaseWikiStore] = None,
                 confine_sources: bool = False, **kwargs) -> None: ...   # line 77

# From packages/ai-parrot/src/parrot/flows/dev_loop/wiki_search.py:27
class DevLoopWikiSearch:
    @classmethod
    def from_project(cls, root: Optional[Path] = None) -> Optional["DevLoopWikiSearch"]: ...  # line 40
    async def build_research_context(self, query: str,
                                     budget_tokens: int = 4000) -> Optional[str]: ...         # line 101

# From packages/ai-parrot/src/parrot/knowledge/wiki/project.py
def wiki_write_lock(store_dir: Path, timeout: float = 0.0) -> Iterator[bool]: ...   # line 76
def find_project_root(start: Path | None = None) -> Path | None: ...                # line 955
def load_project_config(root: Path) -> WikiProjectConfig: ...                       # line 982
def save_project_config(root: Path, config: WikiProjectConfig) -> Path: ...         # line 1007
def load_effective_config(root: Path, env: str | None = None) -> WikiEffectiveConfig: ...  # line 1170
def find_shared_root(start: Path | None = None) -> Path | None: ...                 # line 1457

class WikiProjectConfig(BaseModel):
    storage_dir: str = Field(default=f"{PARROT_DIR}/wiki")          # line 604
    backend: Literal["sqlite", "memory", "arangodb"] = "sqlite"     # line 605
    def storage_path(self, root: Path) -> Path:                     # line 748
        """Absolute storage_dir is returned as-is; otherwise root / storage_dir."""

# From packages/ai-parrot/src/parrot/knowledge/wiki/cli.py
path_option = click.option("--path", "path_", default=None,
                           help="Repo root (default: auto-detect).")  # line 149
def _find_repo_root(path: str | None) -> Path: ...                    # line 361 — uses find_project_root() ONLY when --path is absent
def build(path_, name, backend, force, no_git, quiet, no_export,
          no_graph, graph_kinds, vault_mode, no_push) -> None: ...    # line 1560 — "Deterministic and offline"
```

#### Verified Imports

```python
# Confirmed to resolve:
from parrot_tools.gittoolkit import GitToolkit, GitToolkitError          # gittoolkit.py:44, 961
from parrot.knowledge.wiki.structural.toolkit import CodeStructuralToolkit  # structural/toolkit.py:26
from parrot.knowledge.wiki.toolkit import LLMWikiToolkit                 # toolkit.py:43
from parrot.flows.dev_loop.wiki_search import DevLoopWikiSearch          # wiki_search.py:27
from parrot.knowledge.wiki.project import (
    WikiProjectConfig, find_project_root, load_effective_config,
    load_project_config, save_project_config, wiki_write_lock,
)                                                                         # project.py
from parrot.conf import GITHUB_REVIEW_REPOSITORY                          # conf.py:767
```

#### Key Attributes & Constants

- `GITHUB_REVIEW_REPOSITORY` → `str | None` (`conf.py:767`). Existing siblings:
  `GITHUB_REVIEW_TELEGRAM_CHAT_IDS` (750), `_PUBLIC_CHANNEL_ID` (758),
  `_WEBHOOK_SECRET` (761), `_WEBHOOK_PUBLIC_URL` (764), `_STALE_AFTER_HOURS` (770),
  `_JIRA_PROJECT` (773), `_MAX_DIFF_BYTES` (776), `_MAX_TICKET_BYTES` (780),
  `_WEEKLY_LOOKBACK_WEEKS` (783), `_SILENT_WEEKS_THRESHOLD` (786),
  `_USE_LLM_SUMMARY` (790).
- Console script: `wikitoolkit = "parrot.knowledge.wiki.entry:main"`
  (`packages/ai-parrot/pyproject.toml:204`).
- `GitHubReviewer.model` → `"gemini-3.5-flash"` (`github_reviewer.py:332`).
- `AbstractToolkit.get_tools()` / `get_tools_sync()` →
  `parrot/tools/toolkit.py:522` / `:640`.
- Existing clone tests to extend:
  `packages/ai-parrot-tools/tests/test_gittoolkit_clone.py` (8 tests, incl.
  idempotent-pull and token-scrubbing).

### Does NOT Exist (Anti-Hallucination)

- ~~`parrot.knowledge.wiki.build_wiki()`~~ / ~~`run_build()`~~ — there is **no**
  programmatic entry point for the repository-scan build pipeline. Its logic
  lives inside the click callback `build` (`cli.py:1560`) and its nested
  `_pipeline()`. (`build_wiki_tools` in `mcp_server.py:321` builds MCP *tool
  definitions*, not the graph; `build_graph` in `graphindex/loader.py:240` and
  `pageindex/okf/graph.py:240` are unrelated subsystems.)
- ~~`GitToolkit.checkout_ref()`~~ / ~~`clone_repo(..., sha=...)`~~ /
  ~~`clone_repo(..., ref=...)`~~ — `clone_repo` takes `branch`, not a SHA or a
  `refs/pull/<n>/head` ref. Fetching a PR head would be new code.
- ~~`GITHUB_REVIEW_WORKDIR`~~ / ~~`GITHUB_REVIEW_CACHE_DIR`~~ /
  ~~`GITHUB_REVIEW_WIKI_STORAGE`~~ — none of these exist in `conf.py` today;
  the spec introduces them (names not yet fixed).
- ~~Any wiki/clone/structural reference inside `github_reviewer.py`~~ — grep for
  `wiki|clone|structural` in that file returns **zero** hits. This is greenfield
  wiring, not an extension of existing plumbing.
- ~~`find_project_root(env=...)`~~ / an env var that overrides the wiki root —
  no `WIKI_ROOT`/`PARROT_WIKI_ROOT` setting exists. Explicit `--path` (CLI) or
  `root=` (toolkits) is the only override, and it is sufficient.
- ~~`CodeStructuralToolkit(repository=...)`~~ — it takes `root` / `store` /
  `config`, nothing repository-shaped.

---

## Parallelism Assessment

- **Internal parallelism**: moderate. Three fairly separable slices — (1) the
  clone/cache/lock layer, (2) the build-subprocess runner plus settings, (3) the
  read side (toolkit attachment + prompt injection). But (1)→(2)→(3) form a
  dependency chain, and all three land in the *same* file
  (`bots/github_reviewer.py`), so parallel worktrees would collide on it.
- **Cross-feature independence**: no overlap found with in-flight work.
  `new-codereviewers` (FEAT-270) is the dev-loop dispatcher gate, unrelated to
  this agent; `graphindex-core-seams` (FEAT-540) and `helixdb-provider`
  (FEAT-670) touch the graph-store seams but not `knowledge/wiki/cli.py` as a
  CLI consumer. Shared files to watch: `parrot/conf.py` (append-only; low
  collision risk) and `knowledge/wiki/cli.py` (read-only here — this feature
  does **not** modify it, which is precisely why Option C was deferred).
- **Recommended isolation**: `per-spec`.
- **Rationale**: one feature worktree, tasks sequential. The payload is
  concentrated in a single module with a strict dependency order; splitting it
  across worktrees would buy nothing and cost merge conflicts.

---

## Open Questions

- [x] Flow type and base branch — *Owner: Jesus Lara*: `type: feature`, `base_branch: dev`.
- [x] Build execution model — *Owner: Jesus Lara*: subprocess `wikitoolkit build --path <clone>`; do not refactor wikitoolkit core in this feature.
- [x] Clone/plane lifecycle — *Owner: Jesus Lara*: persistent per repository, refreshed incrementally (`clone_repo` → `pull_repo`, incremental ingest).
- [x] What the reviewer consumes — *Owner: Jesus Lara*: all three — `CodeStructuralToolkit` tools, prompt-injected ranked context, and the full `LLMWikiToolkit`.
- [x] Which ref is cloned — *Owner: Jesus Lara*: the repository's base branch only; PR head refs and forks are out of scope.
- [x] When clone/build run — *Owner: Jesus Lara*: warm-up in `post_configure()` (non-blocking) plus an incremental refresh per PR event.
- [x] Failure behaviour — *Owner: Jesus Lara*: degrade silently to today's diff-only review; log the error.
- [x] Where the plane lives — *Owner: Jesus Lara*: absolute `storage_dir` in a cache directory outside the clone.
- [x] Wiki write surface on third-party code — *Owner: Jesus Lara*: full `LLMWikiToolkit`, unrestricted (no `confine_sources`). **Recorded risk**: the reviewed repository is untrusted content, and the unrestricted surface includes ingest/export and page-write tools; if the plane is ever shared with the main ai-parrot wiki, a prompt-injected write becomes cross-repo. The spec should at minimum keep the reviewed repo's plane in its own isolated `storage_dir` (which the storage decision already does) and state this threat model explicitly.
- [x] Concurrency — *Owner: Jesus Lara*: one `asyncio.Lock` per repository; deliveries queue rather than skip.
- [ ] Exact setting names and defaults (cache dir, plane dir, enable flag, build timeout) — *Owner: Jesus Lara*
- [ ] Retention / GC: nothing in v1 reclaims clones or planes. Acceptable, or does the spec need a size cap or a prune-on-start? — *Owner: Jesus Lara*
- [ ] Recovery from a corrupted cache entry (not-a-clone, failed `pull --ff-only` after a force-push): automatic re-clone, or fail and alert? — *Owner: Jesus Lara*
- [ ] Clone depth: full history, or shallow? Shallow is cheaper but weakens git-based file discovery, and the standup/decisions planes want history. — *Owner: Jesus Lara*
- [ ] Prompt wording for the base-branch caveat, so the LLM never reports a symbol *added by the PR* as nonexistent. Needs an acceptance criterion. — *Owner: Jesus Lara*
- [ ] Subprocess output handling: the `wikitoolkit` CLI prints the navconfig banner on **stdout** before its own output, so stdout must not be parsed as structured data — exit code plus stderr only. Confirm `build` has no machine-readable output worth capturing (it writes `wiki_stats.json` to the plane). — *Owner: Jesus Lara*
- [ ] Should the warm-up be retried (backoff) after a transient failure, or is once-per-process correct? — *Owner: Jesus Lara*
- [ ] Multi-repo deployments: several `GitHubReviewer` subclasses in one process must share cache entries and locks keyed by repo slug — confirm the cache layout supports it from day one (it also keeps Option D viable later). — *Owner: Jesus Lara*
