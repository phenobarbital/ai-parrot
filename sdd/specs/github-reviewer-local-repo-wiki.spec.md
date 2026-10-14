---
# SDD flow type and base branch (FEAT-145).
# - type: feature  (default)  → base_branch: dev (or any non-main branch)
# - type: hotfix              → base_branch MUST be: main
type: feature
base_branch: dev
projects: [ai-parrot, ai-parrot-tools]
tags: [github-reviewer, wikitoolkit, code-review, gittoolkit, knowledge-graph]
---

# Feature Specification: GitHubReviewer local clone + wikitoolkit graph

**Feature ID**: FEAT-672
**Date**: 2026-10-15
**Author**: Jesus Lara
**Status**: draft
**Target version**: next

---

## 1. Motivation & Business Requirements

### Problem Statement

`GitHubReviewer` reviews a pull request with exactly two inputs: the Jira
ticket (summary, description, acceptance criteria) and the PR **diff** fetched
from the GitHub API (`_fetch_diff`, `github_reviewer.py:998`). It never sees
the repository the diff belongs to, which makes a whole class of findings
structurally impossible — "this changes a function with 40 callers", "this
duplicates a helper two modules over", "this toolkit ignores the convention
every sibling follows", "the symbol this patch calls does not exist".

The repository already owns the machinery that answers those questions: the
**wikitoolkit** knowledge graph (ranked page stubs, symbol lookup, code
outline, blast radius). It is built from a *local* checkout, and the reviewer
has none: `find_project_root()` (`project.py:955`) walks up from the CWD, and
the reviewer is a long-lived agent in an aiohttp/gunicorn server whose CWD is
wherever the server was started.

Both halves already exist. `GitToolkit.clone_repo()` shipped with FEAT-250
(`gittoolkit.py:1590`), idempotent and token-scrubbed; every wikitoolkit CLI
command already takes `--path` (`cli.py:149`), so `find_project_root()` is only
a fallback and needs no change. What is missing is the wiring between them —
plus the handful of correctness gaps the design cross-check surfaced (§9).

### Goals

- G1. Maintain one authenticated, idempotently refreshed local clone per
  watched repository, in a server-side cache keyed by repository slug.
- G2. Build and refresh a wikitoolkit plane over that clone, stored **outside**
  the clone, serialized per repository across processes.
- G3. Give the review LLM structural context: `CodeStructuralToolkit` tools,
  the full `LLMWikiToolkit` (with `confine_sources=True`), and a bounded,
  clearly-labelled context block injected into the review prompt.
- G4. Never block a review: every failure in G1–G3 degrades to today's
  diff-only review, with the failure logged.
- G5. Bound disk usage with a size cap and LRU eviction over cache entries.

### Non-Goals (explicitly out of scope)

- Cloning or checking out **PR head refs**, including fork heads
  (`refs/pull/<n>/head`). The graph answers base-branch questions only; the
  proposed code still arrives as the diff. Rejected in brainstorm §Constraints.
- Extracting a programmatic `build_wiki()` from the CLI — brainstorm Option C,
  deliberately deferred: it is a wikitoolkit-core refactor with a far larger
  blast radius than this enrichment. This feature adds only a narrow
  `--storage-dir` flag to the existing command (§3 M1).
- A shared wiki-cache sidecar / ArangoDB-backed multi-reader service —
  brainstorm Option D, the right architecture at N repositories and M reader
  processes, premature at one of each. The cache layout here stays compatible
  with it.
- Any change to how the diff itself is fetched, clamped or reviewed.

---

## 2. Architectural Design

### Overview

A new `RepoWikiCache` owns a per-repository cache directory holding three
things: the clone, the wiki plane, and a cross-process lock file. On agent
startup `post_configure()` schedules a **warm-up task** (owned, logged and
cancelled on shutdown) that clones the repository and builds its plane. On
every PR event, `review_pull_request()` refreshes the same pair — `clone_repo`
fast-forwards an existing clone, and the build re-ingests only stale files —
before the LLM is asked anything.

Because `wikitoolkit build` persists the repository's config unconditionally
(`save_project_config`, `cli.py:1724`), a plane outside the clone cannot be
expressed with `--path` alone. The feature therefore adds one additive flag,
`wikitoolkit build --storage-dir <abs>`: a run-scoped override that is **never
written back** to the scanned repository's `.parrot/wiki.json` and suppresses
the env-overlay auto-generation for that run. That single flag is the whole
wikitoolkit-core surface this feature touches. The build also always runs
`--no-export --no-graph`: the reviewer reads the SQLite plane only, and the
OKF bundle alone is 72,732 files on ai-parrot.

Serialization is two-layered because the deployment is gunicorn with multiple
workers: an in-process `asyncio.Lock` coalesces concurrent coroutines, and an
`fcntl`-based advisory lock file (the same mechanism as `wiki_write_lock`,
`project.py:76`, but async-friendly and scoped to the cache entry) serializes
across worker processes. The build subprocess still takes the store's own
writer lock internally; the two never share a lock file.

On the read side the reviewer attaches `CodeStructuralToolkit(root=<clone>)`
and a headless `LLMWikiToolkit(None, None, None, WikiConfig(...),
confine_sources=True)` — the composition pattern already proven at
`cli/devloop/bootstrap.py:515` — and splices a token-budgeted context block
into the question built by `_ask_llm_for_review()`. That block is explicitly
labelled as a **base-branch snapshot**, so the model never reports a symbol the
PR itself adds as nonexistent.

### Component Diagram

```
post_configure() ──schedules──→ warm-up task ─┐
                                              ├──→ RepoWikiCache.ensure_fresh(repo)
review_pull_request() ──awaits───────────────┘          │
                                                        ├─ repo_lock (fcntl, cross-process)
                                                        ├─ asyncio.Lock (in-process)
                                                        ├─ GitToolkit.clone_repo / pull_repo
                                                        │     └─ validate origin + branch,
                                                        │        auto re-clone once
                                                        ├─ WikiBuildRunner.run()
                                                        │     └─ wikitoolkit build --path <clone>
                                                        │        --storage-dir <plane> (timeout, killable)
                                                        └─ LRU eviction (size cap)
                                                               │
_ask_llm_for_review() ←──bounded context block──── RepoWikiCache paths
          │
          ├─ CodeStructuralToolkit(root=<clone>)      ─┐
          └─ LLMWikiToolkit(confine_sources=True)      ├→ _attach_toolkit() → sync_tools()
                                                       ─┘
```

### Integration Points

| Existing Component | Integration Type | Notes |
|---|---|---|
| `GitHubReviewer.post_configure()` | modifies | Schedules + owns the warm-up task; cancels it on shutdown (`github_reviewer.py:503`) |
| `GitHubReviewer.review_pull_request()` | modifies | Refreshes the cache before the LLM call (`github_reviewer.py:788`) |
| `GitHubReviewer._ask_llm_for_review()` | modifies | Injects the labelled context block (`github_reviewer.py:1031`) |
| `GitHubReviewer._attach_toolkit()` | uses | Registers the two wiki toolkits, unchanged (`github_reviewer.py:568`) |
| `GitToolkit.clone_repo` / `pull_repo` | extends | Gains `timeout` and `prefer_gh`; existing call sites keep today's behaviour |
| `wikitoolkit build` | extends | Gains `--storage-dir`; absent ⇒ byte-identical behaviour to today |
| `CodeStructuralToolkit` | uses | Constructed with explicit `root=` (`structural/toolkit.py:44`) |
| `LLMWikiToolkit` | uses | Headless composition + `confine_sources=True` (`toolkit.py:77`) |
| `parrot.conf` | extends | Seven new `GITHUB_REVIEW_*` settings, append-only |
| `docs/github-reviewer.md` | modifies | New settings + the degradation contract |

### Data Models

```python
# packages/ai-parrot/src/parrot/knowledge/wiki/repo_cache.py  (new)
class RepoCachePaths(BaseModel):
    """Resolved on-disk layout for one repository slug."""

    slug: str            # canonical "owner-repo", lowercased
    repository: str      # canonical "owner/name"
    clone_dir: Path      # <cache>/repos/<slug>
    plane_dir: Path      # <cache>/planes/<slug>   — absolute --storage-dir
    lock_path: Path      # <cache>/locks/<slug>.lock


class BuildOutcome(BaseModel):
    """Result of one `wikitoolkit build` subprocess run."""

    ok: bool
    returncode: int
    timed_out: bool
    duration_s: float
    stderr_tail: str     # last N lines, token-scrubbed; stdout is NEVER parsed
```

### New Public Interfaces

```python
class RepoWikiCache:
    """Maintain a local clone + wiki plane per remote repository."""

    async def ensure_fresh(self, repository: str) -> Optional[RepoCachePaths]:
        """Clone-or-refresh and (re)build. Returns None on any failure."""

    def context_root(self, repository: str) -> Optional[Path]:
        """The clone root when a usable plane exists, else None."""
```

---

## 3. Module Breakdown

#### Delegation-eligible modules

| Module | Eligible? | Decided patterns / exact contracts | Why not (if no) |
|---|---|---|---|
| M1: `--storage-dir` build flag | yes | Option name, non-persistence rule, absolute-path validation, error text all fixed below | — |
| M2: `RepoWikiCache` | no | Layout, locking and eviction are fixed, but clone-validation ordering and the re-clone trigger set need judgement | Recovery semantics interact with LRU eviction |
| M3: `WikiBuildRunner` | yes | Argv, timeout/kill sequence, `BuildOutcome` fields, last-good marker format fixed | — |
| M4: GitToolkit `timeout` / `prefer_gh` | yes | Signature additions are backwards-compatible defaults; kill sequence mirrors M3 | — |
| M5: Reviewer wiring | no | Task ownership, cancellation and toolkit attachment order are design decisions in a 1700-line agent | Interacts with webhook lifecycle |
| M6: Prompt context injection | yes | Budget, label wording and splice point fixed below | — |
| M7: Docs | yes | Table rows + degradation paragraph | — |

### Module 1: `wikitoolkit build --storage-dir`
- **Path**: `packages/ai-parrot/src/parrot/knowledge/wiki/cli.py`
- **Responsibility**: let a caller place the plane outside the scanned
  repository without mutating that repository's config.
- **Depends on**: nothing in this spec.
- **Interface Skeleton**:
  ```python
  # packages/ai-parrot/src/parrot/knowledge/wiki/cli.py  (modifies cli.py:1554 option block,
  #   cli.py:1560 callback, cli.py:1724 persistence)
  @click.option(
      "--storage-dir",
      "storage_dir",
      default=None,
      help="Absolute directory for the wiki plane. Overrides the repo's "
           "storage_dir for THIS RUN ONLY and is never persisted.",
  )
  def build(
      path_: str | None,
      name: str | None,
      backend: str | None,
      force: bool,
      no_git: bool,
      quiet: bool,
      no_export: bool,
      no_graph: bool,
      graph_kinds: str,
      vault_mode: bool | None,
      no_push: bool,
      storage_dir: str | None,          # NEW
  ) -> None:
      """...

      When ``storage_dir`` is given it MUST be absolute (ClickException
      otherwise). The run then:
        * sets ``config.storage_dir`` to it before ``config.storage_path(root)``
          is read — storage_path() already returns an absolute value as-is
          (verified: project.py:748);
        * SKIPS ``save_project_config(root, base_config)`` (verified: cli.py:1724)
          and the env-overlay auto-generation that follows it, so the scanned
          repository's ``.parrot/`` is never written to;
        * is otherwise byte-identical to a run without the flag.
      """
  ```

### Module 2: `RepoWikiCache`
- **Path**: `packages/ai-parrot/src/parrot/knowledge/wiki/repo_cache.py` *(new)*
- **Responsibility**: cache layout, cross-process + in-process locking, clone
  validation and recovery, LRU eviction.
- **Depends on**: M3 (build runner), M4 (GitToolkit additions).
- **Interface Skeleton**:
  ```python
  # packages/ai-parrot/src/parrot/knowledge/wiki/repo_cache.py  (new)
  @asynccontextmanager
  async def repo_lock(lock_path: Path, *, timeout: float) -> AsyncIterator[bool]:
      """Advisory cross-process lock, async-friendly.

      Same fcntl.flock(LOCK_EX | LOCK_NB) contract as wiki_write_lock
      (verified: project.py:76) but retries with ``await asyncio.sleep`` instead
      of ``time.sleep``, so it never blocks the event loop. Yields False when
      another process holds it. No-ops (yields True) where fcntl is absent.
      """

  class RepoWikiCache:
      """Maintain a local clone + wiki plane per remote repository."""

      def __init__(
          self,
          git_toolkit: Any,                     # GitToolkit; verified: gittoolkit.py:961
          cache_dir: Path,
          *,
          max_bytes: int = 5 * 1024**3,
          clone_branch: Optional[str] = None,   # None → the remote's default HEAD
          clone_depth: Optional[int] = None,    # None → full history
          build_timeout: float = 900.0,
          lock_timeout: float = 600.0,
          logger: Optional[logging.Logger] = None,
      ) -> None:
          """..."""

      def paths_for(self, repository: str) -> RepoCachePaths:
          """Canonicalize ``owner/name`` → slug and resolve the three paths.

          Raises ValueError for anything that is not a bare ``owner/name``
          slug — a URL or registry alias is rejected here, never silently
          mapped onto another cache entry.
          """

      async def ensure_fresh(self, repository: str) -> Optional[RepoCachePaths]:
          """Refresh clone + plane under both locks. Never raises.

          Returns the paths when a usable plane exists (last-good marker
          present), None on any failure — the caller degrades.
          """

      async def _ensure_clone(self, paths: RepoCachePaths) -> None:
          """Clone, or validate-and-fast-forward an existing clone.

          Validates that ``git -C <clone> remote get-url origin`` matches the
          expected slug and that the checked-out branch is the tracked one
          (clone_repo treats ANY dir with .git as the cache — verified:
          gittoolkit.py:1619; pull_repo never checks out — verified:
          gittoolkit.py:1671). On mismatch, corruption, or a failed
          ``pull --ff-only``, removes the entry and re-clones EXACTLY ONCE.
          """

      def _evict_if_needed(self, *, keep: Optional[str] = None) -> list[str]:
          """Drop least-recently-used (clone, plane, lock) triples until the
          cache total is within ``max_bytes``. Returns the evicted slugs.

          Never evicts (a) an entry whose lock is currently held, or (b)
          ``keep`` — the slug being refreshed right now — so a cache that is
          already at the cap cannot evict the very entry it just rebuilt.
          When a SINGLE entry exceeds ``max_bytes`` on its own, logs a
          warning naming the slug and its size and evicts nothing: thrashing
          (evict → re-clone → evict) is worse than exceeding the cap, and the
          operator needs to see that the cap is mis-sized. Measured
          reference: ai-parrot is ~620 MB of clone + ~538 MB of wiki.db."""
  ```

### Module 3: `WikiBuildRunner`
- **Path**: `packages/ai-parrot/src/parrot/knowledge/wiki/repo_build.py` *(new)*
- **Responsibility**: run `wikitoolkit build` as a killable subprocess and
  record whether the resulting plane is trustworthy.
- **Depends on**: M1 (the `--storage-dir` flag).
- **Interface Skeleton**:
  ```python
  # packages/ai-parrot/src/parrot/knowledge/wiki/repo_build.py  (new)
  LAST_GOOD_FILENAME = ".last_good_build.json"

  class WikiBuildRunner:
      """Run `wikitoolkit build` over a clone, into an external plane."""

      def __init__(self, *, executable: str = "wikitoolkit", timeout: float = 900.0,
                   logger: Optional[logging.Logger] = None) -> None: ...

      async def run(self, clone_dir: Path, plane_dir: Path, *, quiet: bool = True,
                    force: bool = False) -> BuildOutcome:
          """Spawn the build subprocess.

          Argv:
              wikitoolkit build --path <clone> --storage-dir <plane>
                                --no-export --no-graph [-q] [--force]

          ``--no-export --no-graph`` are NOT optional: the reviewer reads the
          SQLite retrieval plane only, and ``is_built()`` probes nothing but
          ``wiki.db`` (verified: project.py:785). On ai-parrot the OKF bundle
          is 72,732 files / ~251 MB and graph.html/json another ~32 MB, none
          of which any reviewer tool reads — skipping them removes ~570 MB
          per repository and the IO of writing 72k files per build.

          ``force`` re-ingests every file (see §8 Q1): it is passed when the
          previous build for this plane did not complete, because the
          incremental manifest of a half-written plane cannot be trusted.

          stdout is captured but NEVER parsed — the navconfig banner precedes
          any output. Success/failure is the exit code; stderr's tail is kept
          for the log. On timeout the child is terminated, then killed after a
          grace period, and reaped, so no orphan survives (GitToolkit's own
          runner has no timeout — verified: gittoolkit.py:1576).
          """

      def mark_build_started(self, plane_dir: Path) -> None:
          """Record that a build is in flight, BEFORE spawning it.

          A marker left in the ``started`` state (process killed, machine
          rebooted) is what makes the next run pass ``force=True``."""

      def mark_last_good(self, plane_dir: Path, outcome: BuildOutcome) -> None:
          """Flip LAST_GOOD_FILENAME to ``complete`` (utc timestamp + duration)
          after a successful build."""

      def last_good(self, plane_dir: Path) -> Optional[datetime]:
          """Completion time of the last COMPLETE build, else None.

          A plane with no marker, or one still in the ``started`` state, is
          treated as unusable: a build that dies mid-ingest leaves the SQLite
          plane partially written."""

      def needs_force(self, plane_dir: Path) -> bool:
          """True when the previous build for this plane never completed, so
          the next one must re-ingest everything instead of trusting the
          hash/mtime manifest (verified: unchanged files are skipped unless
          ``force`` — cli.py:770)."""
  ```

### Module 4: GitToolkit clone hardening
- **Path**: `packages/ai-parrot-tools/src/parrot_tools/gittoolkit.py`
- **Responsibility**: make the clone path timeout-able and keep private
  authentication deterministic.
- **Depends on**: nothing in this spec.
- **Interface Skeleton**:
  ```python
  # packages/ai-parrot-tools/src/parrot_tools/gittoolkit.py
  #   (modifies gittoolkit.py:1576, :1590, :1653)
  @staticmethod
  async def _run_subprocess(argv: List[str], timeout: Optional[float] = None) -> tuple[int, str, str]:
      """Run ``argv``; return ``(returncode, stdout, stderr)``.

      With ``timeout``, terminate → kill → reap the child and return
      ``(-9, "", "<timed out after Ns>")``. Default None keeps today's
      unbounded behaviour for every existing caller.
      """

  async def clone_repo(
      self,
      repository: str,
      dest_dir: str,
      branch: Optional[str] = None,
      *,
      private: bool = False,
      depth: Optional[int] = None,
      timeout: Optional[float] = None,      # NEW
      prefer_gh: bool = True,               # NEW — False forces the token-in-URL path
  ) -> Dict[str, Any]:
      """...

      ``prefer_gh=False`` skips the ``gh repo clone`` branch even when the
      binary exists: ``gh`` never sees the PAT / App token this toolkit holds
      (verified: gittoolkit.py:1627), so an installed-but-unauthenticated
      ``gh`` would otherwise fail a private clone that the token could serve.
      """

  async def pull_repo(
      self,
      repo_path: str,
      branch: Optional[str] = None,
      *,
      timeout: Optional[float] = None,      # NEW
  ) -> Dict[str, Any]:
      """..."""
  ```

### Module 5: Reviewer wiring + settings
- **Path**: `packages/ai-parrot/src/parrot/bots/github_reviewer.py`,
  `packages/ai-parrot/src/parrot/conf.py`
- **Responsibility**: own the warm-up task, refresh per event, attach the
  toolkits, canonicalize repository identity.
- **Depends on**: M2, M3.
- **Interface Skeleton**:
  ```python
  # packages/ai-parrot/src/parrot/conf.py  (appends after conf.py:790)
  GITHUB_REVIEW_WIKI_ENABLED: bool = config.getboolean("GITHUB_REVIEW_WIKI_ENABLED", fallback=False)
  GITHUB_REVIEW_CACHE_DIR: str = config.get(
      "GITHUB_REVIEW_CACHE_DIR", fallback="~/.cache/parrot/github-reviewer")
  GITHUB_REVIEW_CLONE_BRANCH: str | None = config.get("GITHUB_REVIEW_CLONE_BRANCH", fallback=None)
  GITHUB_REVIEW_CLONE_DEPTH: int | None = config.getint("GITHUB_REVIEW_CLONE_DEPTH", fallback=None)
  GITHUB_REVIEW_CACHE_MAX_BYTES: int = config.getint(
      "GITHUB_REVIEW_CACHE_MAX_BYTES", fallback=5 * 1024**3)
  GITHUB_REVIEW_BUILD_TIMEOUT: int = config.getint("GITHUB_REVIEW_BUILD_TIMEOUT", fallback=900)
  GITHUB_REVIEW_WIKI_CONTEXT_TOKENS: int = config.getint(
      "GITHUB_REVIEW_WIKI_CONTEXT_TOKENS", fallback=4000)

  # packages/ai-parrot/src/parrot/bots/github_reviewer.py  (modifies :503, :518, :788)
  class GitHubReviewer(Agent):
      _wiki_cache: Optional["RepoWikiCache"]
      _wiki_warmup_task: Optional[asyncio.Task]
      _wiki_toolkits_attached: bool

      def _build_wiki_cache(self) -> Optional["RepoWikiCache"]:
          """Build the cache from conf, or None when disabled/misconfigured.

          Fails closed and logs — mirrors _build_git_toolkit (verified:
          github_reviewer.py:588)."""

      async def _schedule_wiki_warmup(self) -> None:
          """Create, store and name the warm-up task; log its exception via a
          done-callback so a failure is never swallowed."""

      async def _shutdown_wiki_warmup(self) -> None:
          """Cancel and await the warm-up task (idempotent)."""

      async def _refresh_wiki_context(self, repository: str) -> Optional[Path]:
          """ensure_fresh() for THIS agent's repository only.

          ``review_pull_request`` reads ``payload.get("repository") or
          self.repository`` (verified: github_reviewer.py:809); enrichment
          ignores the payload value unless it canonicalizes to self.repository,
          so a manual payload can never select another cache entry."""

      def _attach_wiki_toolkits(self, clone_root: Path) -> None:
          """Attach CodeStructuralToolkit(root=clone_root) and a headless
          LLMWikiToolkit(None, None, None, WikiConfig(...), confine_sources=True)
          through _attach_toolkit(), exactly once per process."""
  ```

### Module 6: Bounded, labelled context injection
- **Path**: `packages/ai-parrot/src/parrot/bots/github_reviewer.py`
- **Responsibility**: splice ranked wiki context into the review question
  without crowding out the diff, and state what the graph does not know.
- **Depends on**: M5.
- **Interface Skeleton**:
  ```python
  # packages/ai-parrot/src/parrot/bots/github_reviewer.py  (modifies :1031 question assembly)
  _WIKI_CONTEXT_HEADER = (
      "=== Codebase context (knowledge graph) ===\n"
      "SNAPSHOT OF BRANCH {branch} AT {built_at} — it does NOT contain this "
      "PR's changes. A symbol introduced by this PR is EXPECTED to be absent "
      "here; never report such a symbol as nonexistent on that basis."
  )

  async def _build_wiki_context(self, payload: Dict[str, Any], diff_text: str) -> Optional[str]:
      """Ranked, token-budgeted context for this PR, or None.

      Query is derived from the PR title plus the paths touched by the diff.
      Hard-capped at GITHUB_REVIEW_WIKI_CONTEXT_TOKENS, truncated with the
      wiki's own budgeting helpers (verified: context.py pack_results /
      truncate_to_tokens, used the same way by DevLoopWikiSearch —
      wiki_search.py:101). Never raises."""
  ```

### Module 7: Documentation
- **Path**: `docs/github-reviewer.md`
- **Responsibility**: document the seven settings, the cache layout, the
  degradation contract and the base-branch caveat.
- **Depends on**: M1–M6.
- **Interface Skeleton**: *(documentation only — new rows in the env-var table
  at `docs/github-reviewer.md:110` and a "Codebase context" section)*

---

## 4. Test Specification

### Unit Tests

| Test | Module | Description |
|---|---|---|
| `test_build_storage_dir_overrides_plane_location` | M1 | `--storage-dir` places the plane at the absolute path, not `<root>/.parrot/wiki` |
| `test_build_storage_dir_does_not_persist_config` | M1 | After the run, the scanned repo has no new/changed `.parrot/wiki.json` and no env overlay |
| `test_build_storage_dir_rejects_relative_path` | M1 | A relative value raises `ClickException` |
| `test_build_without_storage_dir_unchanged` | M1 | Omitting the flag keeps today's persistence behaviour |
| `test_paths_for_canonicalizes_slug` | M2 | `Owner/Name` → `owner-name`; URL or alias raises `ValueError` |
| `test_repo_lock_is_exclusive_across_processes` | M2 | Second acquirer gets `False` while the first holds it |
| `test_repo_lock_does_not_block_event_loop` | M2 | A contended acquire with timeout still lets other coroutines run |
| `test_ensure_clone_validates_origin_and_branch` | M2 | A cache dir pointing at another remote is detected |
| `test_ensure_clone_reclones_once_on_corruption` | M2 | Not-a-clone and failed `pull --ff-only` both re-clone exactly once, then give up |
| `test_evict_lru_respects_size_cap` | M2 | Oldest-used entries dropped until under cap; locked entries skipped |
| `test_evict_never_drops_entry_being_refreshed` | M2 | `keep=` slug survives even when the cache is over cap |
| `test_single_oversized_entry_warns_without_evicting` | M2 | One entry larger than the cap logs a warning and evicts nothing (no thrash) |
| `test_ensure_fresh_returns_none_on_any_failure` | M2 | Clone error, build error and timeout all return `None` without raising |
| `test_build_runner_argv` | M3 | Exact argv incl. `--path`, `--storage-dir`, `--no-export`, `--no-graph`, `-q` |
| `test_build_runner_omits_export_and_graph` | M3 | No OKF bundle and no `graph.html` land in the plane after a run |
| `test_needs_force_after_incomplete_build` | M3 | A marker left in `started` ⇒ `needs_force()` is True and the next argv carries `--force` |
| `test_build_runner_never_parses_stdout` | M3 | A navconfig banner on stdout does not affect the outcome |
| `test_build_runner_timeout_kills_child` | M3 | Hung child is terminated, killed and reaped; `timed_out=True` |
| `test_last_good_marker_roundtrip` | M3 | Marker written only after success; absent marker ⇒ plane unusable |
| `test_run_subprocess_timeout_reaps_child` | M4 | `_run_subprocess(timeout=…)` leaves no orphan |
| `test_clone_repo_prefer_gh_false_uses_token_url` | M4 | With `gh` present and `prefer_gh=False`, argv is the token-in-URL `git clone` |
| `test_clone_repo_timeout_propagates` | M4 | Timeout reaches `_run_subprocess` |
| `test_wiki_cache_disabled_by_default` | M5 | `GITHUB_REVIEW_WIKI_ENABLED` unset ⇒ no cache, no warm-up task |
| `test_warmup_task_is_owned_and_cancelled` | M5 | Task stored, named, exception logged, cancelled on shutdown |
| `test_enrichment_ignores_foreign_payload_repository` | M5 | A payload naming another repo does not touch its cache entry |
| `test_toolkits_attached_once` | M5 | Repeated refreshes do not re-register tools |
| `test_llm_wiki_toolkit_confines_sources` | M5 | Constructed with `confine_sources=True` |
| `test_wiki_context_respects_token_budget` | M6 | Block never exceeds `GITHUB_REVIEW_WIKI_CONTEXT_TOKENS` |
| `test_wiki_context_carries_base_branch_label` | M6 | Header names the branch and the "PR symbols may be absent" caveat |
| `test_review_prompt_unchanged_without_context` | M6 | With no plane, the question is byte-identical to today's |

### Integration Tests

| Test | Description |
|---|---|
| `test_fresh_clone_then_build_then_review` | Empty cache → clone a local fixture repo → build → review sees structural tools |
| `test_second_delivery_reuses_clone` | Second event fast-forwards instead of re-cloning; build is incremental |
| `test_concurrent_deliveries_serialize` | Two concurrent events for one repo produce one build, not a lock error |
| `test_build_failure_degrades_to_diff_only` | Non-zero build exit ⇒ review still completes with today's prompt |
| `test_partial_plane_is_not_attached` | A plane without a current last-good marker is not used |
| `test_private_clone_uses_token_when_gh_unauthenticated` | `gh` present but unusable ⇒ token path still clones |

### Test Data / Fixtures

```python
@pytest.fixture
def local_origin(tmp_path) -> Path:
    """A bare git repo with two commits on its default branch, usable as a
    clone source so no test touches the network."""

@pytest.fixture
def cache_dir(tmp_path) -> Path:
    """Isolated GITHUB_REVIEW_CACHE_DIR with repos/ planes/ locks/."""

@pytest.fixture
def fake_wikitoolkit(tmp_path) -> Path:
    """Executable stub that prints a navconfig-style banner on stdout and
    exits with a configurable code, so build outcomes are deterministic."""
```

Test locations: `packages/ai-parrot/tests/knowledge/wiki/test_repo_cache.py`,
`.../test_repo_build.py`, `.../test_cli_build_storage_dir.py`;
`packages/ai-parrot/tests/bots/test_github_reviewer.py` (extended);
`packages/ai-parrot-tools/tests/test_gittoolkit_clone.py` (extended).

---

## 5. Acceptance Criteria

> This feature is complete when ALL of the following are true:

- [ ] **AC-1** `wikitoolkit build --path <clone> --storage-dir <abs>` writes the plane at `<abs>` and leaves the scanned repository's `.parrot/` untouched (no `wiki.json` write, no overlay generation); omitting the flag is behaviourally unchanged.
- [ ] **AC-2** With `GITHUB_REVIEW_WIKI_ENABLED` unset, the reviewer's behaviour and review prompt are byte-identical to today's.
- [ ] **AC-3** The clone tracks the reviewed repository's own default branch (or `GITHUB_REVIEW_CLONE_BRANCH` when set) — never the `GIT_DEFAULT_BRANCH` fallback of `"main"` — and the branch is reported in the injected context header.
- [ ] **AC-4** A cache entry whose origin URL or checked-out branch does not match is detected and re-cloned exactly once; a second failure degrades instead of looping.
- [ ] **AC-5** The warm-up task is stored on the agent, logs its own exceptions, and is cancelled and awaited on shutdown; no orphaned `git`/`wikitoolkit` child survives a reload.
- [ ] **AC-6** A build exceeding `GITHUB_REVIEW_BUILD_TIMEOUT` is terminated, killed and reaped, and reported as `timed_out` distinctly from an ordinary non-zero exit.
- [ ] **AC-7** Enrichment never acts on a repository other than `self.repository`, whatever the payload says.
- [ ] **AC-8** The injected context block never exceeds `GITHUB_REVIEW_WIKI_CONTEXT_TOKENS` and always carries the base-branch snapshot caveat.
- [ ] **AC-9** Clone failure, build failure, build timeout, missing `wikitoolkit` binary, and a plane without a last-good marker each degrade to the diff-only review, with one log line and no exception escaping.
- [ ] **AC-10** Cache total stays within `GITHUB_REVIEW_CACHE_MAX_BYTES` via LRU eviction; neither a locked entry nor the entry being refreshed is ever evicted, and a single over-cap entry is warned about rather than thrashed.
- [ ] **AC-15** The build subprocess always passes `--no-export --no-graph`; no OKF bundle or `graph.html` is produced for a reviewed repository.
- [ ] **AC-16** A build that does not complete leaves its marker in the `started` state, the plane is not attached, and the next build for that plane runs with `--force`.
- [ ] **AC-11** Two concurrent deliveries for one repository, in one process and across two processes, produce one build and no lock error.
- [ ] **AC-12** `LLMWikiToolkit` is constructed with `confine_sources=True`; `CodeStructuralToolkit` with an explicit `root=`.
- [ ] **AC-13** `ruff check` clean on changed files; new unit + integration tests pass.
- [ ] **AC-14** `docs/github-reviewer.md` documents the seven settings, the cache layout, the degradation contract and the base-branch caveat.

---

## 6. Codebase Contract

### Verified Imports

```python
from parrot_tools.gittoolkit import GitToolkit, GitToolkitError          # verified: gittoolkit.py:961, :44
from parrot.knowledge.wiki.structural.toolkit import CodeStructuralToolkit  # verified: structural/toolkit.py:26
from parrot.knowledge.wiki.toolkit import LLMWikiToolkit                 # verified: toolkit.py:43
from parrot.knowledge.wiki.models import WikiConfig                      # verified: models.py:54
from parrot.knowledge.wiki.project import (
    WikiProjectConfig,          # verified: project.py (storage_dir :604, storage_path :748)
    load_effective_config,      # verified: project.py:1170
    load_project_config,        # verified: project.py:982
    save_project_config,        # verified: project.py:1007
    wiki_write_lock,            # verified: project.py:76
)
from parrot.flows.dev_loop.wiki_search import DevLoopWikiSearch          # verified: wiki_search.py:27
from parrot.conf import GITHUB_REVIEW_REPOSITORY                         # verified: conf.py:767
```

### Existing Class Signatures

```python
# packages/ai-parrot-tools/src/parrot_tools/gittoolkit.py
class GitToolkit(...):
    input_class = GitToolkitInput                                        # line 957
    _blob_cache: _FileBlobCache                                          # line 959
    def __init__(self, default_repository=None, default_branch="main", github_token=None,
                 auth_type="pat", app_id=None, installation_id=None, private_key=None,
                 private_key_path=None, repositories=None, **kwargs) -> None:   # line 961
    @staticmethod
    async def _run_subprocess(argv: List[str]) -> tuple[int, str, str]:  # line 1576 — NO timeout today
    async def clone_repo(self, repository: str, dest_dir: str, branch: Optional[str] = None, *,
                         private: bool = False, depth: Optional[int] = None) -> Dict[str, Any]:  # line 1590
        # line 1619: `if os.path.isdir(os.path.join(dest_dir, ".git")): return await self.pull_repo(...)`
        # line 1627: `if private and self._gh_available(): argv = ["gh", "repo", "clone", ...]`
    async def pull_repo(self, repo_path: str, branch: Optional[str] = None) -> Dict[str, Any]:  # line 1653
        # line 1673: argv = ["git", "-C", repo_path, "pull", "--ff-only"]  — no checkout, no remote check

# packages/ai-parrot/src/parrot/bots/github_reviewer.py
class GitHubReviewer(Agent):
    model = "gemini-3.5-flash"                                           # line 332
    def __init__(self, repository: str, *, jira_project: str = "NAV", alert_chat_ids=None,
                 public_channel_id=None, webhook_public_url=None, webhook_secret=None,
                 stale_after_hours: int = 24, max_diff_bytes: int = 50_000,
                 max_ticket_bytes: int = 20_000, silent_weeks_threshold: int = 3,
                 top_n_contributors: int = 10, use_llm_summary: bool = False,
                 max_review_tool_calls: Optional[int] = None, **kwargs) -> None:   # line 430
    self.repository = repository                                         # line 454
    self._reviewed_shas: Dict[Tuple[str, int], str] = {}                 # line 487
    async def post_configure(self) -> None:                              # line 503
    def _attach_toolkit(self, toolkit: Any, name: str) -> None:          # line 568
    def _build_git_toolkit(self) -> Optional[GitToolkit]:                # line 588
    async def review_pull_request(self, payload: Dict[str, Any]) -> Dict[str, Any]:   # line 788
    async def _fetch_diff(self, repo: str, pr_number: int) -> Tuple[str, bool, bool]:  # line 998
    async def _ask_llm_for_review(self, *, payload, ticket_key, ticket, diff_text,
                                  diff_truncated, diff_available) -> PRReviewResult:   # line 1031

# packages/ai-parrot/src/parrot/knowledge/wiki/structural/toolkit.py
class CodeStructuralToolkit(AbstractToolkit):
    tool_prefix: str = "code"                                            # line 42
    def __init__(self, root: Path | None = None, store: BaseWikiStore | None = None,
                 config: WikiProjectConfig | None = None, **kwargs) -> None:   # line 44
    async def symbol_lookup(...)   # line 101
    async def outline(...)         # line 127
    async def blast_radius(...)    # line 146

# packages/ai-parrot/src/parrot/knowledge/wiki/toolkit.py
class LLMWikiToolkit(AbstractToolkit):                                   # line 43
    def __init__(self, pageindex_toolkit, graphindex_toolkit, okf_toolkit,
                 config: WikiConfig, agent_id: str = "agent",
                 store: Optional[BaseWikiStore] = None,
                 confine_sources: bool = False, **kwargs) -> None:       # line 77

# packages/ai-parrot/src/parrot/knowledge/wiki/project.py
LOCK_FILENAME = "wiki.lock"                                              # line 51
def wiki_write_lock(store_dir: Path, timeout: float = 0.0) -> Iterator[bool]:  # line 76
    # fcntl.flock(LOCK_EX | LOCK_NB) + time.sleep retry — blocking; no-op without fcntl
def find_project_root(start: Path | None = None) -> Path | None:         # line 955
class WikiProjectConfig(BaseModel):
    storage_dir: str = Field(default=f"{PARROT_DIR}/wiki")               # line 604
    backend: Literal["sqlite", "memory", "arangodb"] = "sqlite"          # line 605
    def storage_path(self, root: Path) -> Path:                          # line 748 — absolute returned as-is

# packages/ai-parrot/src/parrot/knowledge/wiki/cli.py
path_option = click.option("--path", "path_", default=None, ...)         # line 149
def _find_repo_root(path: str | None) -> Path                            # line 361 — find_project_root only when --path absent
def build(path_, name, backend, force, no_git, quiet, no_export, no_graph,
          graph_kinds, vault_mode, no_push) -> None                      # line 1560 — "Deterministic and offline"
    save_project_config(root, base_config)                               # line 1724 — UNCONDITIONAL after the pipeline
    # followed by env-overlay auto-generation when effective.overlay_path is None

# packages/ai-parrot/src/parrot/cli/devloop/bootstrap.py
def _build_wiki_toolkit() -> Any:                                        # line 515
    return LLMWikiToolkit(None, None, None, wiki_config, agent_id="dev-flow-headless")  # line 548
    # the headless-composition precedent: the three sub-toolkits may be None
```

### Integration Points

| New Component | Connects To | Via | Verified At |
|---|---|---|---|
| `RepoWikiCache` | `GitToolkit.clone_repo()` | method call | `gittoolkit.py:1590` |
| `RepoWikiCache` | `GitToolkit.pull_repo()` | method call | `gittoolkit.py:1653` |
| `WikiBuildRunner` | `wikitoolkit build` | subprocess (`parrot.knowledge.wiki.entry:main`) | `packages/ai-parrot/pyproject.toml:204` |
| `GitHubReviewer._build_wiki_cache` | `conf.GITHUB_REVIEW_*` | module attrs | `conf.py:750-790` |
| `GitHubReviewer._attach_wiki_toolkits` | `_attach_toolkit()` | method call | `github_reviewer.py:568` |
| `GitHubReviewer._attach_wiki_toolkits` | `CodeStructuralToolkit(root=…)` | constructor | `structural/toolkit.py:44` |
| `GitHubReviewer._attach_wiki_toolkits` | `LLMWikiToolkit(None, None, None, WikiConfig(…))` | constructor | `toolkit.py:77`, pattern at `bootstrap.py:548` |
| `GitHubReviewer._build_wiki_context` | `_ask_llm_for_review()` question | string splice | `github_reviewer.py:1069` |

### Does NOT Exist (Anti-Hallucination)

- ~~`parrot.knowledge.wiki.build_wiki()`~~ / ~~`run_build()`~~ — no programmatic entry point for the repository-scan build exists; the logic is inside the click callback `build` (`cli.py:1560`) and its nested `_pipeline()`. (`build_wiki_tools` at `mcp_server.py:321` builds MCP tool *definitions*; `build_graph` at `graphindex/loader.py:240` and `pageindex/okf/graph.py:240` are other subsystems.)
- ~~`wikitoolkit build --storage-dir`~~ — **does not exist yet**; M1 adds it. Today the only root control is `--path` (`cli.py:149`).
- ~~`GitToolkit.checkout_ref()`~~ / ~~`clone_repo(..., sha=…)`~~ / ~~`clone_repo(..., ref=…)`~~ — `clone_repo` takes `branch` only; fetching a PR head would be new code (explicit Non-Goal).
- ~~`GitToolkit._run_subprocess(argv, timeout=…)`~~ — no timeout parameter today (`gittoolkit.py:1576`); M4 adds it.
- ~~`GITHUB_REVIEW_WIKI_ENABLED`~~, ~~`GITHUB_REVIEW_CACHE_DIR`~~, ~~`GITHUB_REVIEW_CLONE_BRANCH`~~, ~~`GITHUB_REVIEW_CLONE_DEPTH`~~, ~~`GITHUB_REVIEW_CACHE_MAX_BYTES`~~, ~~`GITHUB_REVIEW_BUILD_TIMEOUT`~~, ~~`GITHUB_REVIEW_WIKI_CONTEXT_TOKENS`~~ — none exist in `conf.py` today; M5 adds all seven.
- ~~Any `wiki` / `clone` / `structural` reference in `github_reviewer.py`~~ — grep returns zero hits at `83517df71`. This is greenfield wiring.
- ~~`WIKI_ROOT`~~ / ~~`PARROT_WIKI_ROOT`~~ env override — no env var overrides the wiki project root; explicit `--path` / `root=` is the only mechanism.
- ~~`CodeStructuralToolkit(repository=…)`~~ — it takes `root` / `store` / `config` only.
- ~~`parrot/knowledge/wiki/repo_cache.py`~~ / ~~`repo_build.py`~~ — do not exist (`repo_scan.py` is a different module); M2/M3 create them.

### Edit Sites (Blueprint Anchors)

Verified against: `83517df71`

| File | Action | Verbatim anchor line | Verified at | Occurrences |
|---|---|---|---|---|
| `packages/ai-parrot/src/parrot/knowledge/wiki/cli.py` | MODIFY | `def build(` | `cli.py:1560` | 1 |
| `packages/ai-parrot/src/parrot/knowledge/wiki/cli.py` | MODIFY | `        save_project_config(root, base_config)` | `cli.py:1724` | 1 |
| `packages/ai-parrot-tools/src/parrot_tools/gittoolkit.py` | MODIFY | `    async def _run_subprocess(argv: List[str]) -> tuple[int, str, str]:` | `gittoolkit.py:1576` | 1 |
| `packages/ai-parrot-tools/src/parrot_tools/gittoolkit.py` | MODIFY | `    async def clone_repo(` | `gittoolkit.py:1590` | 1 |
| `packages/ai-parrot-tools/src/parrot_tools/gittoolkit.py` | MODIFY | `    async def pull_repo(` | `gittoolkit.py:1653` | 1 |
| `packages/ai-parrot/src/parrot/conf.py` | MODIFY | `GITHUB_REVIEW_USE_LLM_SUMMARY: bool = config.getboolean("GITHUB_REVIEW_USE_LLM_SUMMARY", fallback=False)` | `conf.py:790` | 1 |
| `packages/ai-parrot/src/parrot/bots/github_reviewer.py` | MODIFY | `        self.git_toolkit = self._build_git_toolkit()` | `github_reviewer.py:518` | 1 |
| `packages/ai-parrot/src/parrot/bots/github_reviewer.py` | MODIFY | `        ticket_key = self._extract_ticket_key(payload.get("pr_body") or "", payload.get("pr_title") or "")` | `github_reviewer.py:824` | 1 |
| `packages/ai-parrot/src/parrot/bots/github_reviewer.py` | MODIFY | `            "Compare them and return a PRReviewResult JSON object."` | `github_reviewer.py:1069` | 1 |
| `packages/ai-parrot/src/parrot/knowledge/wiki/repo_cache.py` | CREATE | — | — | — |
| `packages/ai-parrot/src/parrot/knowledge/wiki/repo_build.py` | CREATE | — | — | — |
| `packages/ai-parrot/tests/knowledge/wiki/test_repo_cache.py` | CREATE | — | — | — |
| `packages/ai-parrot/tests/knowledge/wiki/test_repo_build.py` | CREATE | — | — | — |
| `packages/ai-parrot/tests/knowledge/wiki/test_cli_build_storage_dir.py` | CREATE | — | — | — |
| `packages/ai-parrot/tests/bots/test_github_reviewer.py` | MODIFY | `(unverified — check before use)` — extend with the M5/M6 cases | `tests/bots/test_github_reviewer.py` | — |
| `packages/ai-parrot-tools/tests/test_gittoolkit_clone.py` | MODIFY | `async def test_clone_repo_idempotent_pulls(tmp_path):` | `test_gittoolkit_clone.py:99` | 1 |
| `docs/github-reviewer.md` | MODIFY | the env-var table row naming `GITHUB_REVIEW_REPOSITORY` (append the seven new rows after it) | `docs/github-reviewer.md:110` | 1 |

---

## 7. Implementation Notes & Constraints

### Patterns to Follow

- Async-first: `asyncio.create_subprocess_exec` (pattern at
  `flows/dev_loop/webhook.py:83`), never a blocking `subprocess.run`.
- Fail-closed construction mirroring `_build_git_toolkit` (`github_reviewer.py:588`):
  log the error, return `None`, let the caller degrade.
- Degradation contract mirroring `DevLoopWikiSearch.from_project`
  (`wiki_search.py:40`): return `None`, never raise, never block the caller.
- Pydantic v2 models for `RepoCachePaths` / `BuildOutcome`; `self.logger`, never `print`.
- `aiohttp` only — this feature makes no HTTP calls of its own.
- Touch only the files in the Edit Sites table; no refactor of `cli.py`'s build
  pipeline (that is the deferred Option C).

### Known Risks / Gotchas

- **The plane can be left partially written.** The build ingests incrementally
  inside the writer lock, so a crash mid-build leaves a half-updated SQLite
  plane. Mitigation (§8 Q1, resolved): a marker written *before* the build and
  flipped to `complete` after it — an unfinished marker both keeps the plane
  from being attached and forces the next build to run with `--force`, so the
  untrustworthy incremental manifest is discarded instead of being extended.
  A generation-swap publish was rejected: it would copy ~538 MB per webhook
  delivery to protect against a rare crash.
- **`gh` present but unauthenticated** silently breaks private clones because
  `gh` never sees the toolkit's PAT / App token (`gittoolkit.py:1627`).
  Mitigation: the reviewer always passes `prefer_gh=False` (M4).
- **`pull --ff-only` does not checkout and does not verify the remote**
  (`gittoolkit.py:1671-1673`), and `clone_repo` treats any `.git` directory as
  the right cache (`:1619`). Mitigation: M2 validates origin + branch before
  trusting an entry.
- **`asyncio.Lock` is not enough under gunicorn** (multiple worker processes).
  Mitigation: the fcntl lock file; the in-process lock stays only as a
  coalescing optimization.
- **`wiki_write_lock`'s retry loop uses `time.sleep`** (`project.py:76`) — it
  must never be called with a non-zero timeout from the event loop. M2 uses its
  own async variant.
- **stdout is unusable as data**: the navconfig banner precedes any CLI output.
  Exit code + stderr only; build statistics come from `wiki_stats.json` in the
  plane.
- **The graph is a base-branch snapshot.** Without the labelled header a model
  will confidently report a PR-added symbol as nonexistent. AC-8 makes the label
  non-optional.
- **Third-party code is untrusted input.** The reviewed repository's content
  reaches the LLM, which holds a write-capable wiki surface. Mitigation:
  `confine_sources=True` (owner decision) plus a plane isolated per repository;
  the reviewer's plane is never the ai-parrot wiki plane.
- **Disk**: clones plus planes grow with the number of watched repositories;
  LRU eviction (AC-10) is the only reclaim path. Measured on ai-parrot: a full
  clone is ~620 MB (388 MB pack + 233 MB checkout) and the lean plane ~538 MB,
  so ~1.2 GB per repository — the 5 GiB default holds roughly four. A
  deployment watching more must raise `GITHUB_REVIEW_CACHE_MAX_BYTES` or it
  will re-clone on every rotation.
- **PATH coupling**: the server process must resolve the `wikitoolkit` console
  script. A missing binary disables enrichment for the process lifetime (logged
  once, AC-9).

### External Dependencies

| Package | Version | Reason |
|---|---|---|
| — | — | No new Python dependency. `git` (required) and optionally `gh` must exist on the server; `wikitoolkit` already ships in core (`pyproject.toml:204`). |

---

## 8. Open Questions

- [x] Flow type and base branch — *Resolved in brainstorm*: `type: feature`, `base_branch: dev`.
- [x] Build execution model — *Resolved in brainstorm*: subprocess `wikitoolkit build`, no core refactor (§2 Overview, §3 M1).
- [x] Clone/plane lifecycle — *Resolved in brainstorm*: persistent per repository, refreshed incrementally (§2 Overview, §3 M2).
- [x] What the reviewer consumes — *Resolved in brainstorm*: structural tools + injected context + full `LLMWikiToolkit` (§3 M5, M6).
- [x] Which ref is cloned — *Resolved in brainstorm*: base branch only; PR heads and forks are a Non-Goal (§1).
- [x] When clone/build run — *Resolved in brainstorm*: non-blocking warm-up in `post_configure()` + per-event refresh (§3 M5, AC-5).
- [x] Failure behaviour — *Resolved in brainstorm*: degrade to the diff-only review, log it (§5 AC-9).
- [x] Where the plane lives — *Resolved in brainstorm*: absolute storage outside the clone (§3 M1, AC-1).
- [x] Wiki write surface — *Resolved in brainstorm, revised after S7*: full tool surface **with `confine_sources=True`** (§3 M5, AC-12, §7 Risks).
- [x] Concurrency — *Resolved in brainstorm, refined by S2*: per-repository serialization, implemented as a cross-process fcntl lock plus an in-process `asyncio.Lock` (§3 M2, AC-11).
- [x] Clone depth — *Resolved in brainstorm*: `GITHUB_REVIEW_CLONE_DEPTH`, default full history (§3 M5).
- [x] Retention / GC — *Resolved in brainstorm*: size cap with LRU eviction (§3 M2, AC-10).
- [x] Corrupted cache entry — *Resolved in brainstorm, sharpened by S3*: validate origin + branch, auto re-clone exactly once, then degrade (§3 M2, AC-4).
- [x] Subprocess output handling — *Resolved*: exit code + stderr only; `wiki_stats.json` for data (§3 M3, §7 Risks).
- [x] Warm-up retry — *Resolved*: no backoff loop; the per-event refresh is the retry (§3 M5).
- [x] Multi-repo deployments — *Resolved*: cache entries and locks keyed by repository slug, never by agent instance (§3 M2).
- [x] How to place the plane outside the clone — *Resolved by owner after S1*: add `--storage-dir` to `wikitoolkit build` rather than seeding a config into the clone (§3 M1, AC-1).
- [x] **Q1** — Partial plane after a failed build — *Owner: Jesus Lara*: marker written before the build plus a `--force` rebuild on the next run after an incomplete one. Generation-swap rejected — it would copy ~538 MB per delivery to guard against a rare crash (§3 M3, AC-16, §7).
- [x] **Q2** — Programmatic `build_wiki()` — *Owner: Jesus Lara*: closed for now. `--storage-dir` removes the blocking motivation; the remaining reasons (testing without a subprocess, PATH coupling) do not justify a wikitoolkit-core refactor until a second in-process caller exists. Filed in the work ledger instead of staying open here.
- [x] **Q3** — Cache cap — *Owner: Jesus Lara*: 5 GiB stays the default (~4 repositories at the measured ~1.2 GB each). The anti-thrash guard in `_evict_if_needed` (never evict the entry just refreshed; warn instead of evicting when one entry alone exceeds the cap) is what makes a tight cap safe (§3 M2, AC-10).

---

## 9. Design Research Cross-Check

> Independent design opinion from the `codex` seat over the **accepted brainstorm**
> (never over this spec). Model: `gpt-5.6-luna` (codex-cli 0.162.1) · Status: completed
> · Transcript: `sdd/state/FEAT-672/design_research/`
> All 12 `affected_paths` sets passed containment + existence checks, and each claim
> was spot-checked in the cited source before disposition.

| # | Suggestion (kind) | Disposition | Reason | Landed in |
|---|---|---|---|---|
| S1 | Make external storage an explicit build input (architecture) | CONFIRM | Verified: `build` calls `save_project_config` unconditionally (`cli.py:1724`), so `--path` alone cannot place the plane outside the clone. Owner chose the additive flag. | §2 Overview, §3 M1, AC-1 |
| S2 | Lock shared across processes, not just coroutines (architecture) | CONFIRM | Correct for gunicorn's multi-worker deployment; refines rather than reverses the owner's serialization decision. | §3 M2, AC-11, §7 |
| S3 | Validate the cached clone's remote and branch (risk) | CONFIRM | Verified at `gittoolkit.py:1619` and `:1671` — any `.git` dir is trusted and `pull` never checks out. | §3 M2, AC-4 |
| S4 | Do not let incidental `gh` break private auth (risk) | CONFIRM | Verified at `gittoolkit.py:1627`: `gh` is preferred whenever present and never sees the toolkit's token. | §3 M4, §7 |
| S5 | Cancellable subprocess timeouts (risk) | CONFIRM | Verified at `gittoolkit.py:1576`: `communicate()` with no timeout; `wait_for` alone would orphan the child. | §3 M3, M4, AC-6 |
| S6 | Preserve a last-known-good plane (architecture) | CONFIRM (reduced) | Real: the build writes in place under the lock. Adopted as a before/after marker plus a forced rebuild after an incomplete build; generation-swap rejected on cost (~538 MB copied per delivery). | §3 M3, AC-16, §7 |
| S7 | Treat the full wiki surface as a mutation capability (risk) | CONFIRM (owner variant) | Independent second flag on a deliberate owner decision; owner kept the full surface but enabled `confine_sources=True`. | §3 M5, AC-12, §7 |
| S8 | Canonicalize repository identity (api) | CONFIRM | Verified at `github_reviewer.py:809`: `payload.get("repository") or self.repository`. | §3 M5, AC-7 |
| S9 | Resolve the dev-vs-main branch contract (api) | CONFIRM | Verified at `github_reviewer.py:601` and `gittoolkit.py:961`: both default to `"main"`. | §3 M2, M5, AC-3 |
| S10 | Bound and label injected context (api) | CONFIRM | Makes the brainstorm's sharpest edge an acceptance criterion instead of prose. | §3 M6, AC-8 |
| S11 | Deterministic degradation and lifecycle tests (testing) | CONFIRM | The listed gaps are exactly the paths this feature adds. | §4 |
| S12 | Own and cancel warm-up tasks (architecture) | CONFIRM | Verified: `post_configure` (`:503`) owns no background task today. | §3 M5, AC-5 |

Summary: **12** confirmed · **0** rejected · **0** escalated.
S1 and S7 were routed to the owner before drafting, because they touched
decisions already resolved in the brainstorm; both answers are folded in above.

---

## Worktree Strategy

- **Isolation**: ONE feature worktree for FEAT-672
  (`.claude/worktrees/feat-FEAT-672-github-reviewer-local-repo-wiki`); the
  `sdd-coder` engine gives each task its own sub-worktree inside it.
- **Module dependency graph**:
  - M3 → M1 (the build runner's argv uses `--storage-dir`, added by M1)
  - M2 → M3 (`RepoWikiCache.ensure_fresh` calls `WikiBuildRunner.run`)
  - M2 → M4 (clone/pull calls pass `timeout=` and `prefer_gh=`)
  - M5 → M2, M3 (builds the cache, reads the last-good marker)
  - M6 → M5 (injection needs the attached toolkits and the resolved root)
  - M7 → M1, M5 (documents the flag and the settings)
  - M1 and M4 have no edge between them and are expected to run concurrently.
- **Shared files**: `packages/ai-parrot/src/parrot/bots/github_reviewer.py` is
  modified by M5 and M6 → those tasks serialize.
  `packages/ai-parrot-tools/src/parrot_tools/gittoolkit.py` is M4 only.
- **Exclusive resources**: none. No migration, no lockfile, no extension
  rebuild. Tests must not share a cache directory — each uses the `cache_dir`
  fixture under `tmp_path`.
- **Cross-feature dependencies**: none. FEAT-540 (graphindex core seams) and
  FEAT-670 (helixdb provider) touch graph-store seams, not
  `knowledge/wiki/cli.py` as a CLI consumer; this spec adds one option to that
  file and nothing else.

---

## Revision History

| Version | Date | Author | Change |
|---|---|---|---|
| 0.1 | 2026-10-15 | Jesus Lara | Initial draft from the accepted brainstorm; 12 codex design-research suggestions folded in (§9) |
| 0.2 | 2026-10-15 | Jesus Lara | Resolved §8 Q1–Q3; lean build (`--no-export --no-graph`), before/after build marker + forced rebuild, eviction anti-thrash guard; AC-15/AC-16 added |
