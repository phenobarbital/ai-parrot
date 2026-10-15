<!--
  sdd/templates/design_research.prompt.md — neutral design-research brief (FEAT-545).
  Rendered by /sdd-spec section 3b and piped to `codex exec ... --output-schema
  design_research.schema.json`.
  FORBIDDEN INPUTS: never paste the spec draft, the spec author's reasoning, a preferred
  conclusion, or any text written by the model that will author the spec. The brief carries
  ONLY the accepted exploration document (brainstorm/proposal) and verified code anchors.
  Placeholders (double-curly-brace tokens, deliberately NOT written with literal braces in
  this comment — a renderer that does a naive whole-document string replace must not also
  rewrite this sentence): problem_statement, constraints_and_goals,
  recommended_option_or_scope, code_context_paths, open_questions, question.
-->
# Independent design review — read-only

You are an independent design reviewer for **ai-parrot**, an async-first Python
framework for AI agents (aiohttp, Pydantic v2, `uv` workspace under `packages/`).
You have read-only access to the repository in your working directory.

## Rules
1. Read the code you cite. Every `affected_paths` entry must be a repo-relative
   path you actually opened; suggestions with unverifiable paths are discarded.
2. Judge the design intent below against what exists in the repository: what is
   missing, what is risky, what would be simpler, what the codebase already
   provides that the intent re-invents.
3. Do not restate the intent, do not praise it, do not write code. Propose at
   most 12 concrete, falsifiable suggestions, each tagged with a kind
   (`architecture` | `api` | `testing` | `risk` | `alternative`), a risk level and
   your confidence.
4. Output exactly ONE JSON object conforming to the schema you were given — no
   markdown fences, no prose before or after.

## Accepted design intent (verbatim from the exploration document)

### Problem statement
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

### Constraints and goals
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

### Recommended option / probable scope
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

--- Recommended Option body ---

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

### Verified code anchors (paths only — open them yourself)
packages/ai-parrot-tools/src/parrot_tools/gittoolkit.py
packages/ai-parrot-tools/tests/test_gittoolkit_clone.py
packages/ai-parrot/pyproject.toml
packages/ai-parrot/src/parrot/bots/github_reviewer.py
packages/ai-parrot/src/parrot/flows/dev_loop/wiki_search.py
packages/ai-parrot/src/parrot/knowledge/wiki/cli.py
packages/ai-parrot/src/parrot/knowledge/wiki/project.py
packages/ai-parrot/src/parrot/knowledge/wiki/structural/toolkit.py
packages/ai-parrot/src/parrot/knowledge/wiki/toolkit.py

### Questions still open in the exploration document
- [ ] Exact setting names and defaults (cache dir, plane dir, enable flag, build timeout) — *Owner: Jesus Lara*
- [ ] Prompt wording for the base-branch caveat, so the LLM never reports a symbol *added by the PR* as nonexistent. Needs an acceptance criterion. — *Owner: Jesus Lara*

## Question
Given this accepted design intent and these verified code anchors, how would you build it? What is missing, risky, or better done another way?
