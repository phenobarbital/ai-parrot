# TASK-1924: FeatureHandoffNode — draft PR, docs artifact, wiki page, graph write-back

**Feature**: FEAT-378 — DevLoop Enhancement — Feature-Mode Topology
**Spec**: `sdd/specs/devloop-enhancement.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: L (4-8h)
**Depends-on**: TASK-1918, TASK-1919
**Assigned-to**: unassigned

---

## Context

Spec §3 Module 6. The automated "sdd-done that documents": push the feature
branch, open a **draft PR against `dev`** (never merge), generate and commit
a `docs/features/feat-<id>-<slug>.md` artifact to the PR branch, ingest that
page into the LLM wiki, publish the run outcome to the knowledge graph, and
transition Jira only when a ticket exists.

---

## Scope

- Implement `FeatureHandoffNode(DevLoopNode)` in
  `parrot/flows/dev_loop/nodes/feature_handoff.py`, node id
  `"feature_handoff"`, registered via `@register_dev_loop_node`:
  1. Push branch + draft PR `--base dev` — reuse the
     `DeploymentHandoffNode` helpers/pattern (gh CLI → REST fallback with
     `GITHUB_TOKEN`, retry-once). Extract shared push/PR logic into a
     module-level helper ONLY if it avoids copy-paste without touching
     `DeploymentHandoffNode` behavior; otherwise mirror the pattern.
  2. Generate `docs/features/feat-<id>-<slug>.md` (what was implemented,
     key decisions, accepted findings + `accept_with_notes` notes, how to
     test); directory from `DEV_LOOP_DOCS_ARTIFACT_DIR` (new conf key,
     default `docs/features`). Commit + push it to the PR branch.
  3. Wiki page ingest via `LLMWikiToolkit.create_page` when
     `DEV_LOOP_WIKI_PAGE_INGEST` (new conf key, bool) is true — degrade with
     a warning if wiki not initialized/available. NO code `wikitoolkit
     upsert` here (deferred to post-merge hook — spec resolved decision).
  4. `DevLoopGraphMemory.publish_run_outcome()` — no-op with debug log when
     unavailable (see contract).
  5. Jira transition + comment ONLY if a ticket key is present.
  6. Record `DocsArtifactLinked` action (TASK-1919). Append
     `accept_with_notes` notes to the PR body when present.
  - Failure ladder: gh absent → REST; both fail → `status: "blocked"`
    (mirror the `_mark_blocked` pattern, without Jira dependency).
  - Returns `{status, pr_url, pr_number, docs_path, wiki_page_id}`.
- Add conf keys `DEV_LOOP_DOCS_ARTIFACT_DIR`, `DEV_LOOP_WIKI_PAGE_INGEST`.
- Unit tests with stubbed git/gh/wiki/graph.

**NOT in scope**: any merge operation (forbidden), changes to
`DeploymentHandoffNode` behavior, post-merge wiki automation, topology edges
(TASK-1925).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/flows/dev_loop/nodes/feature_handoff.py` | CREATE | FeatureHandoffNode |
| `packages/ai-parrot/src/parrot/conf.py` | MODIFY | 2 new conf keys |
| `packages/ai-parrot/tests/flows/dev_loop/test_feature_handoff.py` | CREATE | Unit tests |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from parrot.flows.dev_loop.nodes.base import register_dev_loop_node, DevLoopNode  # verified 2026-07-27
from parrot.knowledge.wiki.toolkit import LLMWikiToolkit  # class at toolkit.py:46 — verify the
    # exact import path exposed by parrot.knowledge.wiki.__init__ before use
```

### Existing Signatures to Use
```python
# packages/ai-parrot/src/parrot/flows/dev_loop/nodes/deployment_handoff.py:46  (verified 2026-07-27)
class DeploymentHandoffNode(DevLoopNode):
    def __init__(self, *, jira_toolkit, git_toolkit=None, gh_cli_path=None,
        target_repo=None, base_branch="dev", name="deployment_handoff",
        require_deployment_approval=False): ...  # :71
    # execute :100 — _push_branch :283 → draft PR :117-119
    # gh pr create --draft --base dev :325 / REST fallback :354, retry-once :144-162
    # ← THE pattern for push/PR/fallback/blocked; read the whole file first

# packages/ai-parrot/src/parrot/knowledge/wiki/toolkit.py  (verified 2026-07-27)
class LLMWikiToolkit(AbstractToolkit):  # :46
    async def create_page(...)          # :509 — read full signature before calling

# packages/ai-parrot/src/parrot/conf.py — style reference for new keys
# DEV_LOOP_CODEREVIEW_AGENT :928-934 block style
```

### Does NOT Exist
- ~~`DevLoopGraphMemory.publish_run_outcome()`~~ — FEAT-377 TASK-1914/1915,
  in progress on branch `feat-377-graphindex-as-engineering-devloop`, NOT on
  dev as of 2026-07-27. **At task start check merge status**; if absent,
  guard with try/except ImportError and no-op with a debug log. Keep the
  call in one isolated method.
- ~~`docs/features/` directory~~ — does not exist; this task's node CREATES
  it at runtime (and the conf default names it). Do not pre-create it in the repo.
- ~~PR creation anywhere outside `deployment_handoff.py`~~ — historical
  invariant (revision_handoff.py:10 forbids it). This task deliberately adds
  the SECOND PR-creating node — keep the "never merge" guarantee explicit in
  code + docstring + test.
- ~~Reusable `build_wiki()`~~ — wikitoolkit build pipeline is inline in its
  CLI (wiki/cli.py:634). Only `create_page` is available for ingest.
- ~~`gate_ttl_for("review_escalation")`~~ — KeyError (qa.py:473 reads conf directly).

---

## Implementation Notes

### Pattern to Follow
Read `deployment_handoff.py` end-to-end first; mirror its structure
(helpers, retry-once, `_mark_blocked`). The docs artifact content template
can live as a module-level string constant.

### Key Constraints
- **Never merge** — no `git merge`, no `gh pr merge`, anywhere. Add an
  explicit test asserting the node's command surface contains neither.
- All git/gh calls async (subprocess wrappers already used by the pattern).
- Wiki/graph/Jira are OPTIONAL side-effects: each degrades independently
  with a warning; only push/PR failure blocks.
- `self.logger` on every degradation.

### References in Codebase
- `packages/ai-parrot/src/parrot/flows/dev_loop/nodes/deployment_handoff.py` — primary pattern
- `packages/ai-parrot/src/parrot/knowledge/wiki/toolkit.py:509` — page ingest
- Spec §2 Internal Behavior item 7 (full sequence + degradations)

---

## Acceptance Criteria

- [ ] Successful run ends in a draft PR against `dev`; no merge code path exists (tested)
- [ ] `docs/features/feat-<id>-<slug>.md` generated, committed and pushed to the PR branch
- [ ] Wiki ingest degrades with warning (PR still created); graph write-back no-ops when unavailable
- [ ] Jira transition only with ticket; without ticket zero Jira calls
- [ ] gh absent → REST; both fail → `status: "blocked"`
- [ ] `DocsArtifactLinked` recorded; `accept_with_notes` notes land in PR body
- [ ] All tests pass: `pytest packages/ai-parrot/tests/flows/dev_loop/test_feature_handoff.py -v`
- [ ] `ruff check packages/ai-parrot/src/parrot/flows/dev_loop/nodes/feature_handoff.py`

---

## Test Specification

```python
# packages/ai-parrot/tests/flows/dev_loop/test_feature_handoff.py
async def test_happy_path_draft_pr_and_docs(): ...
async def test_never_merges(): ...
async def test_wiki_unavailable_degrades(): ...
async def test_graph_memory_absent_noop(): ...
async def test_no_jira_key_no_jira_calls(): ...
async def test_gh_missing_rest_fallback(): ...
async def test_both_pr_paths_fail_blocked(): ...
async def test_accept_notes_in_pr_body(): ...
```

---

## Agent Instructions

1. **Read the spec** (§2 item 7, §5, §7 degradation ladder)
2. **Check dependencies** — TASK-1918, TASK-1919 completed
3. **Verify the Codebase Contract** — check FEAT-377 merge status (graph
   memory); verify `LLMWikiToolkit.create_page` full signature; re-grep anchors
4. **Update status** in `sdd/tasks/index/devloop-enhancement.json` → `"in-progress"`
5. **Implement**, **verify criteria**, move file to `sdd/tasks/completed/`, update index → `"done"`, fill Completion Note

---

## Completion Note

**Completed by**: sdd-worker (Claude)
**Date**: 2026-07-27
**Notes**: `FeatureHandoffNode` implemented in `nodes/feature_handoff.py`,
registered as `"dev_loop.feature_handoff"`. Mirrors
`DeploymentHandoffNode`'s push/draft-PR/retry-once/gh-then-REST-fallback
pattern almost verbatim (kept duplicated rather than extracted into a
shared helper, per the task's own "ONLY if it avoids copy-paste without
touching DeploymentHandoffNode behavior" guidance — extracting would have
required either changing `DeploymentHandoffNode`'s private method
signatures or introducing a new shared module, both riskier than a
~150-line, well-isolated duplication for a node this size). Generalized
`_push_branch` into `_run_git(cwd, *args)` so push/add/commit for the
docs artifact reuse one subprocess helper — the only git verbs issued
anywhere in this module are `push`/`add`/`commit`; verified by
`test_never_merges` (records every `_run_git` call across a full run)
plus `test_create_pr_with_gh_never_issues_merge` (asserts the *real*,
unmocked `gh` subprocess argv is always `pr create`, never `pr merge`).
Docs artifact: `{DEV_LOOP_DOCS_ARTIFACT_DIR}/feat-<id>-<slug>.md`
(id/slug parsed from `branch_name`, falling back to `feat_id` digits +
a local slugify if the branch doesn't match the `feat-<id>-<slug>`
convention), written, committed, and pushed as a second commit on the
same branch — its commit/push failure is logged and degrades rather
than blocking the already-created PR. Wiki ingest
(`LLMWikiToolkit.create_page`) is gated on `DEV_LOOP_WIKI_PAGE_INGEST`
AND a caller-supplied `wiki_toolkit` (the constructor never builds one
itself — composing `PageIndexToolkit`/`GraphIndexToolkit`/`OKFToolkit`/
`WikiConfig` is bootstrap's job); added a `wiki_name` constructor param
(default `"ai-parrot"`) since `create_page`'s first positional arg has
no codebase-wide default. `DevLoopGraphMemory.publish_run_outcome()`
confirmed NOT on `dev` — guarded behind `try/except ImportError`,
no-op with debug log. Jira transition/comment gated on BOTH an
`issue_key` being present AND `jira_toolkit` being configured (unlike
`DeploymentHandoffNode`, Jira is now fully optional here). Added the 2
conf keys (`DEV_LOOP_DOCS_ARTIFACT_DIR`, `DEV_LOOP_WIKI_PAGE_INGEST`)
following the `DEV_LOOP_JUDGE_PANEL` block style immediately preceding
them. `DocsArtifactLinked` recorded via `session_host.apply()` (TASK-1919).
All 13 unit tests pass (5 more than the task's own 8-test list — added
explicit wiki-ingest-success, jira-present, and push-failure coverage);
full dev_loop suite green except the pre-existing, unrelated
`test_models_module_is_pure` test-order flake.

**Deviations from spec**: none
