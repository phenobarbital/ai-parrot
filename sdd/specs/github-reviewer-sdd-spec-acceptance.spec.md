---
type: feature
base_branch: dev
projects: [ai-parrot, ai-parrot-tools]
tags: [github-reviewer, sdd, pr-review, jira, gittoolkit]
---

# Feature Specification: GitHubReviewer — SDD Spec as a Second Acceptance-Criteria Source

**Feature ID**: FEAT-759
**Date**: 2026-10-27
**Author**: Jesus Lara
**Status**: draft
**Target version**: 1.3.0

---

## 1. Motivation & Business Requirements

### Problem Statement

`GitHubReviewer` (`packages/ai-parrot/src/parrot/bots/github_reviewer.py`) already
submits a **real GitHub PR review vote** — `APPROVE` / `REQUEST_CHANGES` / `COMMENT`
via `GitToolkit.submit_pr_review` (`POST /pulls/{pr}/reviews`) — not just an issue
comment. This is confirmed working in production on `Trocdigital/fieldsync`
(account `jleontrocglobal` cast `APPROVED` reviews on PR #548, #562, among
others).

But both review paths — `review_pull_request` (webhook-triggered) and
`strict_review_pull_request` (`/review_pr` on-demand, with the draft-on-block
gate) — can only build a verdict when `_extract_ticket_key` finds a
`NAV-<number>` Jira key in the PR title/body. When it does not, the PR falls
into the `no_ticket` branch, which posts a single explanatory **issue comment**
(`_notify_missing_ticket`) and casts **no review vote at all** — not even a
rejection. A correct, well-built PR that simply forgot (or never intended) to
reference a Jira ticket gets zero signal that an automated gate ran.

This is not hypothetical: `Trocdigital/fieldsync` PR #573
(`[Stacked on #572] FEAT-811: admin read/write for the programme validation
switches`) references this repo's own SDD convention — a `FEAT-<NNN>`
feature-spec id — instead of a Jira key, and received only the auto-comment,
no vote, while sibling PRs that do carry a `NAV-<number>` get approved
automatically. The repository already has a second, machine-readable source
of acceptance criteria for that PR: its own `sdd/specs/<slug>.spec.md` file,
section "## 5. Acceptance Criteria" — written by the same `/sdd-spec` workflow
that produced this very document. `GitHubReviewer` has GitHub API access
(`GitToolkit`) and could read that file directly; it currently does not try.

### Goals
- When no Jira ticket key is found in a PR's title/body, but an SDD
  `FEAT-<NNN>` id is, and that id resolves to a spec file (on the PR's base
  branch) with a non-empty Acceptance Criteria section, run the **same** LLM
  comparison and submit the **same kind of real GitHub review vote**
  (`APPROVE`/`REQUEST_CHANGES`, or `COMMENT` for the deferred-CI case in the
  strict gate) that the Jira path already produces.
- Keep Jira source selection and review behavior as-is when a Jira key is present — the spec path
  is a **fallback**, never a replacement, and never overrides a found Jira
  key, including on fetch failure. Reviewed outcome dictionaries gain only
  additive `requirement_source` metadata.
- Preserve today's `no_ticket` behavior (comment only, no vote) for a PR that
  has neither a usable Jira key nor a usable SDD spec.
- Make the decided requirement source observable on the result (so logs/
  Telegram alerts/tests can tell a Jira-sourced review from a spec-sourced
  one).

### Non-Goals (explicitly out of scope)
- Writing back to the spec file (e.g. checking off `[ ]` acceptance criteria
  boxes). This feature only **reads** the spec.
- Resolving a FEAT-id to a Jira ticket via `/sdd-tojira`'s exported key, or
  any other Jira cross-reference. If neither source resolves independently,
  the PR still falls through to `no_ticket`.
- Teaching `_ask_llm_for_review` (github_reviewer.py:1855-1960) anything new
  about SDD specs. It stays completely untouched — see §2 Overview for why.
- Any change to `JiraToolkit`, `jira_specialist.py`, or the Jira ticket
  extraction/fetch path (`_extract_ticket_key`, `_fetch_ticket`).
- A UI/dashboard for requirement-source telemetry. This spec only adds the
  data point (`requirement_source` on the result dict); consuming it is out
  of scope.

---

## 2. Architectural Design

### Overview

The design goal is **minimum blast radius**: `_ask_llm_for_review` — the
function that builds the LLM prompt and is most sensitive to regression — is
never touched. Instead, a new spec-sourced path produces a dict **shaped
exactly like the Jira ticket envelope** `_fetch_ticket` already returns
(`{"fields": {"summary": ..., "description": ..., <ac_field_id>: ...}}`), so
it is a drop-in substitute wherever `ticket` is passed to
`_ask_llm_for_review(ticket_key=..., ticket=..., ...)`. Only the two
`no_ticket` branches (`review_pull_request`, `strict_review_pull_request`)
change, to attempt this fallback before giving up.

Locating the right spec file is the one genuinely new problem, and it was
checked empirically rather than assumed: `GitToolkit.search_repo_code` (GitHub
Code Search) **only indexes a repository's configured default branch**
(confirmed in its own docstring, `parrot_tools/gittoolkit.py:2745`). The
motivating repository, `Trocdigital/fieldsync`, has its GitHub default branch
set to `main` (verified live via `gh api repos/Trocdigital/fieldsync --jq
.default_branch` → `main`), while its SDD specs are committed to `dev` per
this project's own `CLAUDE.md` branch policy. Code Search alone would
therefore **never** find a spec that lives only on `dev` — exactly the
situation of every open, unmerged feature PR. So Code Search is used only as
a cheap first-pass optimization (works when `base_ref` happens to be the
default branch, or once a spec has been promoted there); the ref-exact,
always-correct path is a **directory listing at the PR's own `base_ref`**,
which needs one small new capability on `GitToolkit` — it does not currently
exist (`list_directory_at_ref`/equivalent is absent; `get_file_content_at_ref`
only reads one known path, and GitHub's `contents/{path}` endpoint returns a
JSON **array** for a directory versus an **object** for a file, which
`_get_file_content_sync` does not handle).

### Component Diagram
```
review_pull_request() ──┐
strict_review_pull_      ├─► (no Jira key found) ─► _extract_feature_id()
request()                                              │
                                                        ▼
                                              _fetch_spec_requirement(repo, feature_id, base_ref)
                                                        │
                                            ┌───────────┴───────────┐
                                            ▼                       ▼
                                  _locate_spec_file()      (path resolved)
                                            │                       │
                              ┌─────────────┴─────────────┐         ▼
                              ▼                            ▼   GitToolkit.get_file_content_at_ref()
                 GitToolkit.search_repo_code()   GitToolkit.list_repo_directory()   │
                    (fast path, default-branch       (ref-exact fallback,          ▼
                     only, best-effort)               always correct)     _parse_spec_sections()
                                                                                    │
                                                                                    ▼
                                                              {"fields": {summary, description, ac_field}}
                                                                        (same shape _fetch_ticket returns)
                                                                                    │
                                                                                    ▼
                                                            _ask_llm_for_review(ticket_key=feature_id,
                                                                                 ticket=<above>, ...)
                                                                        (UNCHANGED — existing function)
```

### Integration Points

| Existing Component | Integration Type | Notes |
|---|---|---|
| `GitHubReviewer.review_pull_request` (github_reviewer.py:1523-1641) | extends | `no_ticket` branch (L1559-1574) tries the spec fallback before giving up |
| `GitHubReviewer.strict_review_pull_request` (github_reviewer.py:2593-2746) | extends | `no_ticket` branch (L2628-2634) does the same for the on-demand gate |
| `GitHubReviewer._ask_llm_for_review` (github_reviewer.py:1855-1960) | uses, unchanged | consumes the synthetic ticket-shaped dict exactly like a real Jira envelope |
| `GitHubReviewer._fetch_pr_payload` (github_reviewer.py:2125-2155) | extends | adds `base_ref` / `base_sha` keys from the already-fetched `pr` dict |
| `GitToolkit.search_repo_code` (parrot_tools/gittoolkit.py:2734) | uses, unchanged | fast-path lookup only (default branch) |
| `GitToolkit.get_file_content_at_ref` (parrot_tools/gittoolkit.py:2518) | uses, unchanged | reads the located spec's content at `base_ref` |
| `GitToolkit` (parrot_tools/gittoolkit.py) | extends | new `list_repo_directory` tool — ref-exact spec lookup when Code Search misses |
| `PRReviewResult` (github_reviewer.py:261-277) | extends | new optional `requirement_source` field, default `"jira"` (no behavior change for existing callers) |

### Data Models
```python
# packages/ai-parrot/src/parrot/bots/github_reviewer.py (modifies PRReviewResult, github_reviewer.py:261-277)
class PRReviewResult(BaseModel):
    """LLM-produced summary of a PR review."""
    jira_key: Optional[str] = None            # unchanged — reused as "the requirement key" (Jira or FEAT-id); never renamed, see §7
    discrepancies: List[Discrepancy] = Field(default_factory=list)   # unchanged
    summary: str                               # unchanged
    approve: bool                              # unchanged
    requirement_source: Literal["jira", "sdd_spec"] = "jira"   # NEW — additive, default preserves every existing call site and test

# packages/ai-parrot-tools/src/parrot_tools/gittoolkit.py (new, alongside FileContentResult/SearchCodeResult)
class RepoDirectoryEntry(BaseModel):
    """One entry returned by ``list_repo_directory``."""
    name: str
    path: str
    type: Literal["file", "dir"]

class RepoDirectoryListing(BaseModel):
    """Return payload for ``list_repo_directory``."""
    exists: bool
    path: str
    ref: str
    repository: str
    entries: List[RepoDirectoryEntry] = Field(default_factory=list)

class ListRepoDirectoryInput(BaseModel):
    """Input payload for ``list_repo_directory``."""
    path: str
    ref: str
    repository: Optional[str] = None
```

### New Public Interfaces
```python
# packages/ai-parrot-tools/src/parrot_tools/gittoolkit.py
class GitToolkit(AbstractToolkit):  # AbstractToolkit verified: parrot/tools/__init__.py (base machinery)
    @tool_schema(ListRepoDirectoryInput)
    async def list_repo_directory(
        self, path: str, ref: str, repository: Optional[str] = None,
    ) -> "RepoDirectoryListing":
        """List files/subdirectories at ``path`` for a given git ref.

        Mirrors ``get_file_content_at_ref``'s 404-as-not-exists handling
        (``exists=False``, empty ``entries``), but against GitHub's
        ``contents/{path}`` endpoint's **array** response shape for a
        directory (the existing method only handles the single-file
        **object** shape and must not be reused for this).
        """
```

---

## 3. Module Breakdown

#### Delegation-eligible modules

| Module | Eligible? | Decided patterns / exact contracts | Why not (if no) |
|---|---|---|---|
| M1: Feature-ID extraction | yes | regex sibling of `_ticket_key_regex`, new ctor kwargs with Jira-pattern defaults | — |
| M2: `GitToolkit.list_repo_directory` | yes | exact URL/response shape verified against `_get_file_content_sync`'s sibling pattern (gittoolkit.py:2401-2418) | — |
| M3: Spec location + parsing | yes | two-phase strategy (Code Search fast path, directory-listing fallback) fully decided below | — |
| M4: Wire the fallback into the two review entry points | no | needs a judgment call per call site on exactly which existing variables (`repo`, `payload`, `checks`) are already in scope at the `no_ticket` branch | the two call sites differ (strict gate also handles CI); wiring must not disturb their existing control flow |
| M5: `_fetch_pr_payload` base_ref/base_sha | yes | one-line sibling of the existing `head_sha` extraction | — |

### Module 1: Feature-ID extraction
- **Path**: `packages/ai-parrot/src/parrot/bots/github_reviewer.py`
- **Responsibility**: Find an SDD `FEAT-<NNN>` id in PR title/body, independently of (and only tried after) the Jira ticket key.
- **Depends on**: none
- **Interface Skeleton**:
  ```python
  # packages/ai-parrot/src/parrot/bots/github_reviewer.py (modifies github_reviewer.py:742, :826)
  def __init__(
      self,
      repository: str,
      *,
      jira_project: str = "NAV",                      # existing, unchanged
      sdd_feature_prefix: str = "FEAT",                # new — verified: conf.py:804 is the naming convention to mirror
      enable_sdd_spec_fallback: bool = True,           # new
      max_spec_scan_files: int = 500,                  # new — positive cap across both lookup phases (see §7 Known Risks)
      ...,
  ):
      """<unchanged docstring + new Args entries for the three kwargs above>."""
      ...
      self._ticket_key_regex = re.compile(rf"\b{re.escape(self.jira_project)}-\d+\b")  # existing: github_reviewer.py:826
      self._feature_id_regex = re.compile(rf"\b{re.escape(self.sdd_feature_prefix)}-\d+\b")  # new, sibling

  def _extract_feature_id(self, *texts: str) -> Optional[str]:
      """Same contract as :meth:`_extract_ticket_key` (github_reviewer.py:1514-1521), over ``_feature_id_regex``."""
  ```

### Module 2: `GitToolkit.list_repo_directory`
- **Path**: `packages/ai-parrot-tools/src/parrot_tools/gittoolkit.py`
- **Responsibility**: Ref-exact directory listing — the only way to find a spec file committed to a branch that is not the repository's GitHub default branch (Code Search cannot do this; verified empirically, see §2 Overview).
- **Depends on**: none (new, independent capability; follows `_get_file_content_sync`'s exact connection/auth/404 pattern)
- **Interface Skeleton**:
  ```python
  # packages/ai-parrot-tools/src/parrot_tools/gittoolkit.py (new, placed beside get_file_content_at_ref; anchor: gittoolkit.py:2599)
  def _list_repo_directory_sync(
      self, repository: Optional[str], path: str, ref: str,
  ) -> "RepoDirectoryListing":
      """Synchronous implementation of ``list_repo_directory``.

      Same endpoint as ``_get_file_content_sync`` (``GET contents/{path}?ref=``,
      verified: gittoolkit.py:2404-2407) but expects GitHub's **array**
      response for a directory; a 404 (path does not exist at ``ref``) is
      ``exists=False`` with empty ``entries``, mirroring
      ``FileContentResult``'s own 404 handling (gittoolkit.py:2408-2418) —
      never raised to the caller.
      """

  @tool_schema(ListRepoDirectoryInput)
  async def list_repo_directory(
      self, path: str, ref: str, repository: Optional[str] = None,
  ) -> "RepoDirectoryListing":
      """List files/subdirectories at ``path`` for a given git ref."""
  ```

### Module 3: Spec location + parsing
- **Path**: `packages/ai-parrot/src/parrot/bots/github_reviewer.py`
- **Responsibility**: Resolve a `FEAT-<NNN>` id to spec content, in the exact dict shape `_fetch_ticket` already returns, so `_ask_llm_for_review` needs no change.
- **Depends on**: Module 1 (`feature_id`), Module 2 (`list_repo_directory`), `GitToolkit.search_repo_code` (existing, unchanged), `GitToolkit.get_file_content_at_ref` (existing, unchanged)
- **Decided pattern — two-phase lookup** (not a free design choice for the implementer, fixed here because it is a real correctness-vs-cost tradeoff):
  1. **Fast path**: `search_repo_code(f'"{feature_id}" path:sdd/specs extension:md', repository=repo)`. A single hit with `error is None` is only a candidate. Require a direct child of `sdd/specs/` ending in `.spec.md`, read it with `get_file_content_at_ref` at the requested `ref`, and validate its exact `**Feature ID**: {feature_id}` metadata line outside fenced code. Match the entire line after trimming surrounding whitespace; an incidental mention or a prefix match such as `FEAT-81` versus `FEAT-811` is insufficient. Accept only an existing, readable, non-error, non-truncated text result with that header.
  2. **Fallback**: Search errors, zero/multiple hits, or a missing, unreadable, invalid or mismatched candidate trigger `list_repo_directory("sdd/specs", ref=ref, repository=repo)`. Visit direct file entries ending in `.spec.md` in lexicographic path order, applying the same read/header validation. Return the first validated match, else `None`. This is a deterministic first-match policy, not a repository-wide uniqueness guarantee.
  3. **Read budget and validation**: `max_spec_scan_files` is a positive integer and caps candidate file reads across both phases, including a rejected fast-path candidate. Reuse reads within the lookup rather than reading a rejected candidate twice. An empty `ref` returns `None` without GitHub calls. `_fetch_spec_requirement` must also validate the final content against the requested feature ID before parsing it; if a final reread fails validation, return `None`, never review against that content. A final reread adds at most one file-content call beyond the candidate budget.
- **Interface Skeleton**:
  ```python
  # packages/ai-parrot/src/parrot/bots/github_reviewer.py (new, placed beside _fetch_ticket; anchor: github_reviewer.py:1712)
  async def _locate_spec_file(self, repo: str, feature_id: str, ref: str) -> Optional[str]:
      """Resolve ``feature_id`` to a repo-relative ``sdd/specs/*.spec.md`` path at ``ref``.

      Two-phase: a Code-Search fast path (default-branch only), falling back
      to a ref-exact directory listing + per-file match. Returns ``None``
      when neither phase finds a validated match within the budget — never raises; a
      ``GitToolkitError`` from either GitHub call is logged and treated the
      same as "not found" (fail open to the existing no-op comment path).
      """

  @staticmethod
  def _parse_spec_sections(markdown: str) -> Dict[str, str]:
      """Split an `sdd/templates/spec.md`-shaped document on ``^## `` headings.

      Keys are the heading text lower-cased with any leading ``N. ``
      numeral stripped (e.g. ``"## 5. Acceptance Criteria"`` → key
      ``"acceptance criteria"``). Used to pull out the Motivation and
      Acceptance Criteria sections without depending on section numbers,
      which are not guaranteed stable across template revisions.
      """

  async def _fetch_spec_requirement(
      self, repo: str, feature_id: str, ref: str,
  ) -> Optional[Dict[str, Any]]:
      """Return a ``_fetch_ticket``-shaped dict sourced from an SDD spec, or ``None``.

      ``None`` on: no spec located (:meth:`_locate_spec_file` returned
      ``None``), the spec's own "Acceptance Criteria" section is absent, or
      it contains no substantive criteria after the boilerplate filtering
      defined below. Missing, errored, truncated, or feature-ID-mismatched
      final file content also returns ``None``.

      On success, returns
      ``{"fields": {"summary": <H1 title>, "description": <Motivation section
      text>, self._ac_field_id: <Acceptance Criteria section text>}}`` —
      byte-for-byte the shape :meth:`_fetch_ticket` returns
      (github_reviewer.py:1712-1749; ``_ac_field_id`` verified:
      github_reviewer.py:805), so the two call sites in Module 4 pass it to
      :meth:`_ask_llm_for_review` exactly as they pass a real Jira ``ticket``
      — that method (github_reviewer.py:1855-1960) is NOT modified by this
      feature.
      """
  ```

  **Acceptance Criteria filtering contract**: Normalize whitespace and checkbox
  state (`[ ]`, `[x]`, `[X]`) for comparison. Ignore blank lines, the template's
  introductory blockquote, Markdown separators, and HTML comments. Remove the
  template's generic bullets: ``All unit tests pass (`pytest tests/unit/ -v`)``,
  ``All integration tests pass (`pytest tests/integration/ -v`)``,
  ``Documentation updated in `docs/` ``, and `No breaking changes to existing public API`.
  Also remove unresolved `Criterion N` and
  `Performance benchmark: <metric> within <threshold>` placeholders. At least
  one remaining criterion is required. If none remain, return `None`; otherwise
  pass the remaining criteria (preserving their original text) as the AC field.
  A real feature criterion mixed with generic bullets is usable; an untouched
  template, a subset of its boilerplate, or the placeholder fixture below is not.
  Keep these template strings in the implementation/tests; reviewing another
  repository must not depend on reading this checkout's template at runtime.

### Module 4: Wire the fallback into the two review entry points
- **Path**: `packages/ai-parrot/src/parrot/bots/github_reviewer.py`
- **Responsibility**: In both entry points, attempt the spec fallback only when `_extract_ticket_key` returns `None`. A present Jira key always selects Jira, even if the fetch fails; preserve each entry point's `ticket_not_found` return and wiki-refresh lifecycle. Set `result.requirement_source` explicitly from the selected source, overriding any LLM-supplied value. Both manually constructed public outcome dictionaries must include `"requirement_source": requirement_source` after an LLM review, including strict approved/deferred/blocked outcomes and submission errors. Early returns without a review (`no_ticket`, `ticket_not_found`, `already_reviewed`, validation errors) remain unchanged.
- **Depends on**: Module 1, Module 3, Module 5 (needs `payload["base_ref"]`)
- **Interface Skeleton**:
  ```python
  # packages/ai-parrot/src/parrot/bots/github_reviewer.py (modifies review_pull_request, github_reviewer.py:1559-1574)
  # Decided control flow (both call sites, identical shape):
  #   ticket_key = self._extract_ticket_key(...)            # unchanged
  #   ticket = None
  #   if ticket_key:
  #       ticket = await self._fetch_ticket(ticket_key, ...)  # unchanged Jira path
  #   requirement_source = "jira"
  #   if not ticket_key and self.enable_sdd_spec_fallback:
  #       feature_id = self._extract_feature_id(payload.get("pr_body") or "", payload.get("pr_title") or "")
  #       if feature_id:
  #           ticket = await self._fetch_spec_requirement(repo, feature_id, str(payload.get("base_ref") or ""))
  #           if ticket is not None:
  #               ticket_key, requirement_source = feature_id, "sdd_spec"
  #   if ticket is None:
  #       <existing no_ticket / ticket_not_found branch — UNCHANGED>
  #   result = await self._ask_llm_for_review(..., ticket_key=ticket_key, ticket=ticket, ...)  # UNCHANGED call
  #   result.requirement_source = requirement_source
  #   outcome["requirement_source"] = requirement_source  # in both public outcome builders
  ```

### Module 5: `_fetch_pr_payload` base_ref / base_sha
- **Path**: `packages/ai-parrot/src/parrot/bots/github_reviewer.py`
- **Responsibility**: Thread the PR's base branch through the payload so Module 3/4 can read the spec at the right ref. The raw `pr` dict already carries this (verified: `GitToolkit._compare_pr_versions_sync` already reads `pr["base"]["sha"]` at gittoolkit.py:2618 from the same `get_pull_request` response) — this is a one-line sibling of the existing `head_sha` extraction, not a new API call.
- **Depends on**: none
- **Interface Skeleton**:
  ```python
  # packages/ai-parrot/src/parrot/bots/github_reviewer.py (modifies _fetch_pr_payload, github_reviewer.py:2146-2154)
  return {
      "repository": repo,
      "pr_number": pr_number,
      "pr_title": pr.get("title") or "",
      "pr_body": pr.get("body") or "",
      "pr_url": pr.get("html_url") or "",
      "head_sha": ((pr.get("head") or {}).get("sha")) or "",
      "base_ref": ((pr.get("base") or {}).get("ref")) or "",    # new
      "base_sha": ((pr.get("base") or {}).get("sha")) or "",    # new
      "author": ((pr.get("user") or {}).get("login")) or "",
      "draft": bool(pr.get("draft")),
      ...
  }
  ```
  The **webhook-triggered** path already receives `base_ref` from
  `GitHubWebhookHook._build_event_payload` in
  `packages/ai-parrot/src/parrot/core/hooks/github_webhook.py:191-205`
  for opened/reopened/synchronize events. No webhook source change is needed:
  this design reads at `base_ref`, not `base_sha`. The new manual payload's
  `base_sha` is metadata only; neither path promises an immutable snapshot.
  Cover the existing webhook builder in an integration regression so both
  entry paths resolve specs at the supplied base branch.

---

## 4. Test Specification

### Unit Tests
| Test | Module | Description |
|---|---|---|
| `test_extract_feature_id_matches_feat_prefix` | M1 | `FEAT-811` extracted from title/body; no match when absent |
| `test_extract_feature_id_does_not_shadow_jira` | M1/M4 | a PR with both a Jira key and a FEAT-id resolves via Jira, never attempts the spec fallback |
| `test_jira_fetch_failure_never_uses_spec` | M4 | Both IDs present; unavailable Jira toolkit, fetch error, or missing issue returns existing `ticket_not_found` in both entry points, with no spec lookup or review submission |
| `test_list_repo_directory_returns_entries` | M2 | mocked GitHub `contents/sdd/specs` array response → `RepoDirectoryListing.entries` |
| `test_list_repo_directory_404_is_not_exists` | M2 | 404 → `exists=False`, empty `entries`, no exception |
| `test_locate_spec_file_fast_path_code_search_hit` | M3 | Single candidate read at requested ref and exact metadata header validated before acceptance; no directory listing call |
| `test_locate_spec_file_rejects_invalid_search_candidate` | M3 | Incidental feature mention, prefix-only ID match, fenced example header, wrong extension/path, missing/renamed file, unreadable/error/truncated content all trigger bounded directory fallback |
| `test_locate_spec_file_budget_and_order` | M3 | Positive cap enforced across both phases; rejected candidate consumes budget and is not read twice; deterministic first-match order; empty ref performs no calls |
| `test_fetch_spec_requirement_revalidates_final_content` | M3 | Final read is missing, errored, truncated, or has a different feature header: return `None`, never submit a vote |
| `test_locate_spec_file_falls_back_on_rate_limited_search` | M3 | `search_repo_code` returns `error="rate_limited"` → directory-listing fallback exercised |
| `test_locate_spec_file_fallback_scans_and_matches` | M3 | directory listing + per-file `get_file_content_at_ref` finds the `**Feature ID**: FEAT-<NNN>` line |
| `test_fetch_spec_requirement_rejects_placeholder_ac` | M3 | Full untouched template, its generic-bullet subsets, empty/comment-only section, and placeholder fixture return `None`, including checked/whitespace variants |
| `test_fetch_spec_requirement_accepts_substantive_ac` | M3 | A real criterion mixed with template boilerplate is accepted; returned AC preserves real criterion text and excludes generic/placeholder bullets |
| `test_fetch_spec_requirement_shape_matches_fetch_ticket` | M3 | returned dict has exactly `{"fields": {"summary", "description", <ac_field_id>}}` |
| `test_review_pull_request_spec_fallback_approves` | M4 | no Jira key, resolvable spec, PR satisfies its AC → `submit_pr_review(event="APPROVE", ...)` called, `requirement_source="sdd_spec"` |
| `test_review_pull_request_no_source_unchanged` | M4 | neither Jira nor spec resolves → identical to today: `_notify_missing_ticket` only, no review submitted |
| `test_strict_review_pull_request_spec_fallback` | M4 | same as above through the strict/draft-on-block gate |
| `test_review_outcomes_expose_requirement_source` | M4 | Assert public returned dictionaries for Jira/spec reviews and strict approved/deferred/blocked/submission-error outcomes; LLM-supplied source cannot override selected source; early no-review outcomes unchanged |
| `test_fetch_pr_payload_includes_base_ref` | M5 | `_fetch_pr_payload` result carries `base_ref`/`base_sha` from a fixture `pr` dict |

### Integration Tests
| Test | Description |
|---|---|
| `test_review_pull_request_end_to_end_spec_sourced` | Full `review_pull_request` call with a fake `GitToolkit` (search miss → directory listing → file read) and a fake LLM client producing `approve=True`; asserts the real `submit_pr_review` call and its body. |
| `test_webhook_spec_review_uses_base_ref` | Build opened/reopened/synchronize payloads through the existing `GitHubWebhookHook._build_event_payload`; pass to reviewer with fake GitToolkit/LLM and assert spec reads use the supplied base branch and returned source is `sdd_spec`. |

### Validation Contract

tests:
- packages/ai-parrot/tests/bots/test_github_reviewer.py
markers: none

### Test Data / Fixtures
```python
# Minimal spec fixture used by M3 tests — mirrors sdd/templates/spec.md's shape
SPEC_FIXTURE_WITH_AC = """\
# Feature Specification: Example

**Feature ID**: FEAT-9001

## 1. Motivation & Business Requirements

Some motivation text.

## 5. Acceptance Criteria

- [ ] The thing actually works
- [ ] Tests pass
"""

SPEC_FIXTURE_PLACEHOLDER_AC = """\
# Feature Specification: Example

**Feature ID**: FEAT-9002

## 5. Acceptance Criteria

> This feature is complete when ALL of the following are true:

- [ ] All unit tests pass (`pytest tests/unit/ -v`)
- [ ] All integration tests pass (`pytest tests/integration/ -v`)
- [ ] Documentation updated in `docs/`
- [ ] No breaking changes to existing public API
- [ ] Performance benchmark: <metric> within <threshold>
- [ ] Criterion N
"""
```

---

## 5. Acceptance Criteria

> This feature is complete when ALL of the following are true:

- [ ] A PR whose title/body contains no `NAV-<number>` but does contain a
  `FEAT-<NNN>` id, where that id resolves (fast path or fallback) to a spec
  file on the PR's `base_ref` with a non-placeholder, non-empty Acceptance
  Criteria section, receives a real GitHub PR review vote
  (`APPROVE`/`REQUEST_CHANGES`/`COMMENT`) via `GitToolkit.submit_pr_review`
  — not merely an issue comment.
- [ ] A PR referencing a `NAV-<number>` Jira ticket is completely unaffected:
  same source selection and failure behavior as today, with only additive
  source metadata on reviewed outcomes. A Jira fetch failure never enables
  SDD fallback, even if a FEAT-id is also present. Every existing test in
  `test_github_reviewer.py` passes unmodified.
- [ ] A PR with neither a usable Jira key nor a usable SDD spec still falls
  through, byte-for-byte unchanged, to today's `no_ticket` /
  `_notify_missing_ticket` comment-only path.
- [ ] A PR whose FEAT-id cannot be resolved to any spec (Code Search miss
  **and** directory-listing miss), or resolves to a spec with an empty or
  placeholder Acceptance Criteria section, also falls through unchanged to
  the `no_ticket` path — never a silent, ungrounded approval.
- [ ] `PRReviewResult.requirement_source` is `"sdd_spec"` when the spec path
  decided the verdict and `"jira"` in every other case (including every
  existing call site, via the field's default). Both entry points explicitly
  stamp the selected source on the model and their returned reviewed outcome
  dictionaries, including strict deferred/blocked results and submission
  errors. Existing early returns without review remain unchanged.
- [ ] Search candidates are validated against the exact feature metadata at
  the requested ref; stale or mismatched hits trigger directory fallback.
  Unfilled template criteria are rejected even when generic bullets coexist
  with placeholders; substantive criteria mixed with boilerplate remain usable.
- [ ] Both `review_pull_request` and `strict_review_pull_request` support the
  fallback identically.
- [ ] `GitToolkit.list_repo_directory` correctly reports `exists=False` with
  empty `entries` on a 404 (directory absent at that ref), never raising.
- [ ] All new behavior is bounded by `self.max_spec_scan_files` — a
  pathologically large `sdd/specs/` directory cannot turn one PR review into
  an unbounded number of GitHub API calls. The cap covers candidate reads
  across both phases; a final validation reread adds at most one file-content
  call. File-content calls can internally make multiple HTTP requests.
- [ ] `enable_sdd_spec_fallback=False` disables spec lookup and source switching
  in both entry points. Existing Jira/no-ticket behavior is preserved, with
  additive `requirement_source="jira"` metadata on Jira-reviewed outcomes.

---

## 6. Codebase Contract

> **CRITICAL — Anti-Hallucination Anchor**

### Verified Imports
```python
from parrot_tools.gittoolkit import (          # verified: packages/ai-parrot/src/parrot/bots/github_reviewer.py:79-85
    ContributorStats,
    ContributorWeek,
    GitToolkit,
    StatsNotReadyError,
    WeeklyCodeFrequency,
)
# Module 4 needs two more names added to this same import block:
from parrot_tools.gittoolkit import (
    FileContentResult,       # verified: packages/ai-parrot-tools/src/parrot_tools/gittoolkit.py:493
    RepoDirectoryListing,    # NEW, this feature — packages/ai-parrot-tools/src/parrot_tools/gittoolkit.py
)
```

### Existing Class Signatures
```python
# packages/ai-parrot/src/parrot/bots/github_reviewer.py
class GitHubReviewer(Agent):                                        # Agent verified: parrot/bots/__init__.py (base machinery)
    def _extract_ticket_key(self, *texts: str) -> Optional[str]: ...        # line 1514
    async def _fetch_ticket(self, ticket_key: str, *, fields: Optional[str] = None) -> Optional[Dict[str, Any]]: ...  # line 1712
    async def _ask_llm_for_review(                                          # line 1855
        self, *, payload: Dict[str, Any], ticket_key: str, ticket: Dict[str, Any],
        diff_text: str, diff_truncated: bool, diff_available: bool, use_wiki: bool = True,
    ) -> PRReviewResult: ...
    async def _fetch_pr_payload(self, repo: str, pr_number: int) -> Optional[Dict[str, Any]]: ...  # line 2125
    self.git_toolkit: Optional[GitToolkit]                                  # line 828, set in post_configure (line 993-996)
    self._ac_field_id: str                                                  # line 805, default "customfield_10100"
    self._ticket_key_regex: re.Pattern                                      # line 826

class PRReviewResult(BaseModel):                                     # line 261
    jira_key: Optional[str] = None
    discrepancies: List[Discrepancy] = Field(default_factory=list)
    summary: str
    approve: bool

# packages/ai-parrot-tools/src/parrot_tools/gittoolkit.py
class GitToolkit:                                                    # (AbstractToolkit subclass, base machinery)
    async def search_repo_code(                                             # line 2734
        self, query: str, repository: Optional[str] = None, max_results: int = 20,
    ) -> "SearchCodeResult": ...                                            # SearchCodeResult: line 545, only indexes default branch (docstring, line 2745)
    async def get_file_content_at_ref(                                      # line 2518
        self, path: str, ref: str, repository: Optional[str] = None,
        start_line: Optional[int] = None, end_line: Optional[int] = None,
    ) -> "FileContentResult": ...                                           # FileContentResult: line 493
    def _get_file_content_sync(...) -> "FileContentResult": ...            # line 2362 — 404 handling pattern to mirror, lines 2406-2418
    @staticmethod
    def _request(method: str, url: str, token: str, *, expected: int, **kwargs: Any) -> requests.Response: ...  # line 1260, raises GitToolkitError on unexpected status
```

### Integration Points
| New Component | Connects To | Via | Verified At |
|---|---|---|---|
| `GitHubReviewer._fetch_spec_requirement` | `GitToolkit.get_file_content_at_ref` | method call | `gittoolkit.py:2518` |
| `GitHubReviewer._locate_spec_file` | `GitToolkit.search_repo_code` | method call | `gittoolkit.py:2734` |
| `GitHubReviewer._locate_spec_file` | `GitToolkit.list_repo_directory` (new) | method call | this spec, Module 2 |
| `review_pull_request` / `strict_review_pull_request` | `_ask_llm_for_review` | existing method call, UNCHANGED signature | `github_reviewer.py:1855` |

### Does NOT Exist (Anti-Hallucination)
- ~~`GitToolkit.list_directory` / `GitToolkit.list_files` / `GitToolkit.get_tree`~~ — none of these exist today; the capability this spec calls `list_repo_directory` must be created (Module 2).
- ~~`PRReviewResult.feature_id`~~ — this spec deliberately does NOT add a sibling field; `jira_key` is reused as the generic requirement key (see §7, resolved design decision).
- ~~`payload["base_ref"]` / `payload["base_sha"]`~~ — confirmed absent everywhere in `github_reviewer.py` today (`grep -c 'base_ref\|base_sha' github_reviewer.py` → 0 before this feature).
- ~~A `JIRA_USERS`-style roster entry for SDD specs~~ — no such mapping exists or is needed; spec-sourced reviews have no "assignee" concept analogous to a Jira ticket's assignee field, and `_notify_blocked_pr`'s DM path is untouched by this spec (it is only reached via `strict_review_pull_request`'s `verdict.mergeable is False` branch, which Module 4 does not change).

### Edit Sites (Blueprint Anchors)

> Verified against: `b4985b7d5` (origin/dev, 2026-10-27)

| File | Action | Verbatim anchor line | Verified at | Occurrences |
|---|---|---|---|---|
| `packages/ai-parrot/src/parrot/bots/github_reviewer.py` | MODIFY | `self._ticket_key_regex = re.compile(rf"\b{re.escape(self.jira_project)}-\d+\b")` | `github_reviewer.py:826` | 1 |
| `packages/ai-parrot/src/parrot/bots/github_reviewer.py` | MODIFY | `jira_project: str = "NAV",` | `github_reviewer.py:742` | 1 |
| `packages/ai-parrot/src/parrot/bots/github_reviewer.py` | MODIFY | ```\n        ticket_key = self._extract_ticket_key(payload.get("pr_body") or "", payload.get("pr_title") or "")\n        if not ticket_key:\n            self.logger.info(\n``` | `github_reviewer.py:1559-1561` (inside `review_pull_request`) | 1 (disambiguated by trailing `self.logger.info(`) |
| `packages/ai-parrot/src/parrot/bots/github_reviewer.py` | MODIFY | ```\n        ticket_key = self._extract_ticket_key(payload.get("pr_body") or "", payload.get("pr_title") or "")\n        if not ticket_key:\n            outcome: Dict[str, Any] = {"status": "no_ticket", "repository": repo, "pr_number": pr_number}\n``` | `github_reviewer.py:2628-2630` (inside `strict_review_pull_request`) | 1 (disambiguated by the `outcome: Dict[str, Any] = ...` line) |
| `packages/ai-parrot/src/parrot/bots/github_reviewer.py` | MODIFY | `            "head_sha": ((pr.get("head") or {}).get("sha")) or "",` | `github_reviewer.py:2152` (inside `_fetch_pr_payload`) | 1 |
| `packages/ai-parrot/src/parrot/bots/github_reviewer.py` | MODIFY | `class PRReviewResult(BaseModel):` | `github_reviewer.py:261` | 1 |
| `packages/ai-parrot/src/parrot/bots/github_reviewer.py` | MODIFY | `from parrot_tools.gittoolkit import (` | `github_reviewer.py:79` | 1 |
| `packages/ai-parrot-tools/src/parrot_tools/gittoolkit.py` | MODIFY | `    def _compare_pr_versions_sync(` | `gittoolkit.py:2599` | 1 |
| `packages/ai-parrot/src/parrot/core/hooks/github_webhook.py` | REUSE unchanged | `"base_ref": base.get("ref"),` | `github_webhook.py:205`, default pull-request event branch (also present in review-event branch at line 181) | 2; disambiguate by event branch |

---

## 7. Implementation Notes & Constraints

### Patterns to Follow
- Mirror `jira_project`'s constructor-kwarg pattern exactly for
  `sdd_feature_prefix` / `enable_sdd_spec_fallback` / `max_spec_scan_files`
  (verified: `github_reviewer.py:742`, conf-backed defaults the same way
  `GITHUB_REVIEW_JIRA_PROJECT` is, `conf.py:804`).
- `_locate_spec_file` / `_fetch_spec_requirement` must never raise out of a
  review — every `GitToolkitError` (network error, unexpected status, rate
  limit) is caught and logged, falling through to "spec not found" exactly
  like `_fetch_diff` and `_fetch_ticket` already do for their own failures
  (`github_reviewer.py:1737-1744`, `:1766-1773`).
- `list_repo_directory`'s 404 handling must copy `_get_file_content_sync`'s
  existing pattern verbatim (string-match on `"404"` in the raised
  `GitToolkitError`, `gittoolkit.py:2408-2418`) — do not invent a different
  error-detection mechanism for the new method.

### Resolved Design Decisions (binding — not open to the implementer)
- **`PRReviewResult.jira_key` is NOT renamed.** It has 29 references across
  `github_reviewer.py` and its test file; a rename is unjustified churn for
  an additive feature. It is reused as "the requirement's display key",
  which may be a Jira key or a `FEAT-<NNN>` id — every formatting helper
  that touches it (`_format_review_body`, `_format_deferred_body`,
  `_format_block_comment`, etc.) only interpolates it into Markdown/HTML
  text and never validates its shape, so this is safe.
- **`_ask_llm_for_review` is not modified.** The spec-sourced path produces
  a `_fetch_ticket`-shaped dict instead of generalizing that method's
  signature — see §2 Overview.
- **Code Search is a fast path, not the primary mechanism.** A directory
  listing at the PR's exact `base_ref` is mandatory as a fallback because
  the motivating repository's default branch (`main`) differs from its SDD
  base branch (`dev`) — verified live, not assumed (§2 Overview).
- **A placeholder/empty Acceptance Criteria section must not be treated as
  real criteria.** `_fetch_spec_requirement` returns `None` in that case,
  falling through to the unchanged `no_ticket` path rather than asking the
  LLM to approve against template boilerplate.

### Known Risks / Gotchas
- **Code Search is rate-limited separately** (30 req/min, per
  `search_repo_code`'s own docstring) and can return
  `error="rate_limited"` with `total_count=0` — this must be treated
  identically to "no match", triggering the directory-listing fallback, not
  an error surfaced to the PR.
- **Directory-listing fallback cost scales with `sdd/specs/` size** — one
  `get_file_content_at_ref` call per candidate file until a match is found;
  that helper can issue additional metadata/author HTTP requests internally.
  `max_spec_scan_files` bounds candidate reads across both phases, with at
  most one additional final validation read. It is not a wall-clock timeout.
  A repository with more specs
  than that cap simply cannot be resolved via the fallback past that point
  (acceptable: the existing review pipeline already measures ~60s per PR
  end-to-end, so this adds bounded, not unbounded, latency).
- **Base refs are mutable**: both entry paths use `base_ref`; webhook
  pull-request payloads already include it. `base_sha` added to the manual
  payload is not used for lookup. Validate final file identity before parsing,
  and return `None` on missing refs rather than falling back to the default
  branch. Immutable snapshot selection is outside this change.
- **Multi-tenant repos**: `GitHubReviewer` is subclassed one instance per
  repository. A repo that does not use the SDD workflow at all is
  unaffected as long as no PR title/body coincidentally matches
  `\bFEAT-\d+\b` — low probability, and even a false-positive match only
  ever *attempts* a spec lookup that then finds nothing, falling through
  unchanged.

### External Dependencies
None. This feature only adds one new method to the already-present
`GitToolkit` (no new package) and reuses existing GitHub REST endpoints
already called elsewhere in the same file (`contents/{path}`).

---

## 8. Open Questions

- [x] Webhook payload construction verified at
  `GitHubWebhookHook._build_event_payload` (`github_webhook.py:191-205`).
  Pull-request events already forward `base_ref`; `base_sha` is absent but
  not required by the chosen lookup contract. Reuse the builder unchanged.
- [ ] Should `enable_sdd_spec_fallback` default to `True` (as this spec
  proposes — it is a strictly bounded fallback that only ever fires when
  no Jira key was found) or `False` (opt-in per `GitHubReviewer`
  subclass, so a repo owner must deliberately turn it on)? — *Owner: Jesus
  Lara*.
- [x] Jira-key presence always wins, including unreadable/missing Jira
  tickets. The approved review correction preserves `ticket_not_found`
  rather than switching to SDD criteria on fetch failure.

---

## 9. Design Research Cross-Check

Status: skipped (no accepted exploration document exists for this spec —
this feature was scoped directly from a live production diagnosis in this
session, with no prior `/sdd-brainstorm` or `/sdd-proposal`; the `codex`
design-research seat only runs over an **accepted** exploration doc, per
`/sdd-spec` §3b preconditions).

---

## Worktree Strategy

- **Isolation**: one feature worktree,
  `feat-FEAT-759-github-reviewer-sdd-spec-acceptance`. All five modules land
  inside it; `/sdd-task`'s own sub-worktree-per-task machinery applies as
  usual.
- **Module dependency graph**:
  - M1 (feature-id extraction) → no deps.
  - M2 (`list_repo_directory`) → no deps; different package
    (`ai-parrot-tools`) from every other module.
  - M3 (spec location + parsing) → depends on M1 (needs `feature_id`) and M2
    (needs `list_repo_directory`).
  - M4 (wire into the two entry points) → depends on M1, M3, and M5 (needs
    `payload["base_ref"]`).
  - M5 (`_fetch_pr_payload` base_ref/base_sha) → no deps.
- **Shared files — the real constraint**: M1, M3, M4, and M5 all modify the
  **same single file**, `github_reviewer.py`. Despite the dependency graph
  above having edges only M3→M1/M2 and M4→M1/M3/M5, their tasks must still
  be **serialized** at the file level — concurrent edits to the same file by
  different sub-worktrees is what `/sdd-task` must avoid, not something this
  module graph's near-absence of edges would suggest. M2 is the only module
  genuinely free to run in parallel (different file, different package,
  zero dependents until M3).
- **Exclusive resources**: none (no migration, no lockfile, no extension
  rebuild).
- **Cross-feature dependencies**: none.

---

## Revision History

| Version | Date | Author | Change |
|---|---|---|---|
| 0.1 | 2026-10-27 | Jesus Lara | Initial draft, scoped from a live diagnosis of `Trocdigital/fieldsync` PR #573 (no review vote cast because the PR referenced an SDD `FEAT-811` id instead of a Jira `NAV-<number>` key) |
| 0.2 | 2026-10-27 | Codex | Address review: validate search candidates at target ref, preserve Jira precedence on fetch failure, expose source in public outcomes, reject complete template boilerplate, verify existing webhook base_ref contract, and specify regression coverage. |
