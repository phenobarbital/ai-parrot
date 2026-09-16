---
type: feature
base_branch: dev
---

# Feature Specification: CI Test-Failure Root-Cause Remediation

**Feature ID**: FEAT-562
**Date**: 2026-09-15
**Author**: Claude Sonnet 5, on behalf of amartinez@trocglobal.com
**Status**: draft
**Target version**: n/a (CI/test infrastructure fix, no package version bump)

---

## 1. Motivation & Business Requirements

### Problem Statement

Three CI jobs on `dev` are currently red: `Test wikitoolkit with
wiki-languages + wiki-structural extras`, `Test tool-optimizations FEAT-543
(Python 3.11)`, and `Test ai-parrot (Python 3.12/3.11)`. The user's explicit
requirement is that fixes must be **grounded in a confirmed root cause and
must never weaken a test's assertions just to turn it green** — if a test
fails because production code (or docs) regressed, the fix is in the source;
if a test fails because it lagged a legitimate, already-shipped change, the
fix is in the test, done properly (not a one-line assertion loosen).

This spec is the direct continuation of `sdd/proposals/
ci-test-failures-root-cause-remediation.proposal.md` (FEAT-568, mode:
investigation), which independently re-verified a supplied GitHub Copilot
analysis against live `gh run` data and git history rather than trusting it,
and additionally performed further codebase research during this spec's own
drafting (§2b below) that reclassified two of the proposal's flagged
"unexplained" errors and surfaced the true scope of the largest bucket.

> **Revision 0.2 note (review pass).** A second, adversarial read of this
> spec against the support documents (`sdd/proposals/
> ci-test-failures-root-cause-remediation.proposal.md`, `sdd/state/FEAT-568/
> findings/*`) found three of M2's file-list entries were **mis-categorized**
> — `test_mediagen_handler.py`, `test_understanding_handler.py`,
> `test_understanding_integration.py`, and `test_policy_rules_integration.py`
> fail for a reason that has nothing to do with a missing satellite package
> (see the new **Module 8** below) — and surfaced a **brand-new, unrelated
> CI regression** that appeared on `dev` after this spec was first drafted
> (see the addendum at the end of §1). Both are now reflected below; nothing
> in the original M1/M3/M4/M5/M6/M7 analysis needed to change.

### Goals

- Fix the confirmed, root-caused defect behind each of the three red CI
  jobs, without loosening any test assertion that is still correctly
  describing intended behavior.
- Where a test itself is stale (asserts against a symbol/version/contract
  that a *later, legitimate* feature already changed), update the test to
  track the new reality — with a real rewrite where the old API is gone, not
  a relabeled literal.
- Where production code (or `.claude/agents/sdd-worker.md`, which is
  operational documentation the same test-validity bar applies to) has
  regressed, restore/fix it.
- Extend the codebase's own established graceful-degradation pattern
  (`test-wiki-extras` / `test-wiki-luau-fallback`, FEAT-498/FEAT-532) to the
  much larger set of optional-satellite test surfaces that currently lack it,
  instead of inventing a new pattern.
- Add real CI coverage for the 15 `ai-parrot-client-*` packages (FEAT-523),
  which currently have **zero** CI signal.

### Non-Goals (explicitly out of scope)

- **Full, literal 100% green on `test-core`.** During this spec's own
  research (§2b), several additional `test-core` failures were found that
  are unrelated, pre-existing, and not part of the CI-configuration/
  regression story this spec addresses:
  `TypeError: PostgresToolkit.__init__() missing 1 required positional
  argument: 'dsn'` (a test-fixture bug, 11 occurrences),
  `TypeError: __class__ assignment only supported for mutable types...` and
  `TypeError: '>=' not supported between instances of 'float' and
  'MagicMock'` (mock-authoring bugs, 11 + 7 occurrences),
  `RuntimeError: There is no current event loop in thread 'MainThread'` (1),
  and an object-equality assertion in
  `tests/integrations/test_msagentsdk/test_integration.py` (1). None of
  these trace to any change this spec's modules touch; each needs its own
  independent investigation and is intentionally left alone here rather than
  guessed at.
  A `pydantic_core.ValidationError` for `IdentifiedProduct` (3 occurrences,
  `tests/pipelines/test_endcap_no_shelves.py`) was **originally listed here
  too, but downgraded during this spec's review pass**: that exact file is
  now known (§3/M2) to belong to `ai-parrot-pipelines`, a satellite `test-
  core` never syncs — so this ValidationError may simply be an artifact of
  running that test suite against an incomplete environment, not an
  independent bug. **Do not assume either way** — re-check it once M2's new
  CI job installs `ai-parrot-pipelines` properly; only re-file it here as a
  confirmed independent Non-Goal if it still reproduces with the satellite
  correctly installed.
- Redesigning `TargetedWriterToolkit`/FEAT-543's delegation architecture, or
  FEAT-549's Orchestrator Loop. M4 below is a restoration of previously
  shipped, tested content — not a redesign of either.
- Adding CI coverage for satellite packages this investigation did not find
  failing tests for (`ai-parrot-advisors`, `ai-parrot-pipelines`,
  `ai-parrot-openlit-bridge`, `parrot-formdesigner`, etc.). Real gap, but a
  separate initiative.
- Re-litigating the FEAT-451 wiki-ingestion design. M3 restores what that
  spec already documented as the intended state (`pymupdf` "already a core
  dependency") — it does not redesign `DocumentAcquirer`.

> ### ⚠️ Addendum (review pass, time-sensitive) — a NEW, unrelated CI
> ### regression appeared after this spec was drafted
>
> As of the CI run on this spec's own commit (`ac47689eb3`, run
> `35047661607`), **`Lint & Registry Check`, `Test ai-parrot-tools (3.11)`,
> `Test ai-parrot-loaders (3.11)`, and `Test Luau bounded heuristic fallback`
> are now ALSO failing** — all four were green when the FEAT-568 proposal and
> this spec's first draft were researched (run `35037813473`). Root cause
> (verified via the job log): every `uv sync` step in the workflow now fails
> with
> ```
> error: No solution found when resolving dependencies for split (markers:
> python_full_version >= '3.13' and platform_machine != 'aarch64' and
> sys_platform == 'linux')
>   cause: Because only navigator-session<=0.10.2 is available and
>   ai-parrot depends on navigator-session>=1.0.0, we can conclude that
>   ai-parrot's requirements are unsatisfiable.
> ```
> This is a **second, unrelated resolver-unsat regression**, same general
> shape as the already-fixed `async-notify`/aarch64 one (F001), but on a
> different axis (Python 3.13 support, not CPU architecture) and a different
> package. It was introduced by `cd8690390` (`feat(vault-crypto-hardening):
> TASK-085 — pin navigator-session>=1.0.0`), which landed on `dev` between
> this spec's proposal phase and its drafting — **not** by anything M1-M8
> here touch.
>
> **This is explicitly out of scope for FEAT-562.** It needs its own
> immediate fix (most likely: `navigator-session`'s upstream needs a
> Python-3.13-compatible release before the pin can land, or the pin needs a
> version-specific marker the way `async-notify` already has one) — but it
> is flagged here, prominently, so that whoever implements this spec does
> not mistake "CI is still red after M1-M8 land" for a failure of this spec:
> re-run `gh run list --workflow=ci.yml --branch dev` before and after
> implementing, and expect this specific resolver error to require a
> **separate** fix landing first (or concurrently) for the full CI matrix to
> go green.

---

## 2. Architectural Design

### Overview

Eight independent modules, each fixing exactly one confirmed root cause.
None of them share a target file with another (§2b's "Shared files" note
covers the one apparent exception, `.github/workflows/ci.yml`, which only
M2 touches). None of them introduces a new public component — every module
is a bug fix (source, docs, or test) grounded in a specific, cited piece of
evidence gathered by direct inspection of this repository's current `dev`
HEAD (not the supplied Copilot transcript, which was independently
re-verified and in two places found to be incomplete or superseded).
**M8 was added during this spec's review pass** — it was originally, and
incorrectly, folded into M2's file list as a satellite-gap case; the review
found it is a different, unrelated bug (see M8).

### Component Diagram

```
M1 (crew.py tqdm)         ──┐
M2 (extras/CI gating)      ─┼─→  test-core / test-wiki-extras go green
M3 (pymupdf → core dep)    ─┘         (independent fixes, no shared edges)

M4 (sdd-worker.md restore) ──→  test-tool-optimizations goes green

M5 (wiki SCHEMA_VERSION)   ──┐
M6 (BASE_CSS rewrite)       ─┤
M7 (DatabaseAgent/netsuite) ─┼─→  further test-core error-volume reduction
M8 (stale mock-patch targets)┘        (independent, lower-confidence fixes)
```

### Integration Points

| Existing Component | Integration Type | Notes |
|---|---|---|
| `parrot.bots.flows.crew.crew.AgentCrew` | modifies import | M1 — guard, no behavior change when `tqdm` is present |
| `.github/workflows/ci.yml` jobs | extends | M2 — new job + `pytest.importorskip`/marker guards in existing test files |
| `ai-parrot` core `[project.dependencies]` | extends | M3 — adds `pymupdf`, `pymupdf4llm` |
| `.claude/agents/sdd-worker.md` | modifies | M4 — restores dropped section |
| `parrot.knowledge.wiki.store.SQLiteWikiStore._migrate_fts` | uses (test only) | M5 — asserted against, not modified |
| `parrot.outputs.formats.assets.design_system.DesignSystem.stylesheet` | uses (test only) | M6 — asserted against, not modified |

### Data Models

None — this spec introduces no new data structures. All eight modules are
fixes to existing code, docs, or tests.

### New Public Interfaces

None.

---

## 3. Module Breakdown

#### Delegation-eligible modules

| Module | Eligible? | Decided patterns / exact contracts | Why not (if no) |
|---|---|---|---|
| M1: tqdm lazy import | yes | Exact guard pattern fixed in §3/M1 below (try/except at import time, `async_tqdm = None` fallback, degrade `use_tqdm` at runtime if unavailable) | — |
| M2: extras/CI gating | yes | New CI job YAML fully specified (§3/M2); guard pattern (`pytest.importorskip`) fixed; file list is a **minimum floor**, not exhaustive — the task must re-run test-core's collection locally/in CI to catch every occurrence sharing this shape | Guard mechanics are mechanical; enumerating every file requires running the suite, which is still mechanical, not a design decision |
| M3: pymupdf → core dep | yes | Exact `pyproject.toml` edit fixed (§3/M3) | — |
| M4: sdd-worker.md restore | yes | Exact section text fixed, sourced verbatim from `.claude/commands/sdd-start.md`'s current wording, adapted only for step-lettering (§3/M4) | — |
| M5: wiki SCHEMA_VERSION test | yes | Exact assertion fix + additional `_migrate_fts` coverage contract fixed (§3/M5) | — |
| M6: BASE_CSS test rewrite | no | Only the target API is fixed (`DesignSystem.stylesheet(theme_cfg, layout="report", paged=False)`); which of ~15 assertions in a 1300-line file need which specific replacement string requires case-by-case judgment | Each assertion currently probes a specific literal CSS string; deciding whether the *equivalent* string still exists in the composed report-layout sheet (vs. having moved, merged, or genuinely dropped) is a design judgment, not mechanical substitution |
| M7: DatabaseAgent/netsuite drift | no | Root cause not established in this spec (§3/M7 states exactly what is known and unknown) | Diagnosis-first task; no fix can be specified before the cause is found |
| M8: stale mock-patch targets | yes | Exact patch-target correction fixed per file (§3/M8); root cause and correct replacement pattern fully verified | — |

### Module 1: Guard the `tqdm` import in `crew.py`

- **Path**: `packages/ai-parrot/src/parrot/bots/flows/crew/crew.py`
- **Responsibility**: Stop `tqdm`'s absence from breaking the import of
  `parrot.bots.flows` (and everything that transitively imports it — this
  single fix also resolves the `ImportError: cannot import name 'flows'
  from 'parrot.bots'` cascade seen in `tests/bots/flows/core/storage/
  test_execution_document.py::test_no_llm_client_import` and others, which
  is the exact same failure surfacing through a different import path, not
  a second bug).
- **Depends on**: nothing.
- **Interface Skeleton** *(current → required shape; no new class)*:
  ```python
  # packages/ai-parrot/src/parrot/bots/flows/crew/crew.py
  # CURRENT (line 44, unconditional — verified: crew.py:44):
  #     from tqdm.asyncio import tqdm as async_tqdm
  #
  # REQUIRED (guarded — tqdm is a cosmetic progress bar; its only call site
  # is already conditional on `self.use_tqdm`, verified: crew.py:227,
  # crew.py:4159-4164):
  try:
      from tqdm.asyncio import tqdm as async_tqdm  # verified: crew.py:44 (existing line, now guarded)
  except ImportError:
      async_tqdm = None  # noqa: N816 — sentinel, checked at the one call site below

  # At the existing call site (verified: crew.py:4159), degrade instead of
  # crashing when the import failed:
  #     if self.use_tqdm and async_tqdm is not None:
  #         chunk_iterator = async_tqdm(enumerate(chunks, 1), total=len(chunks), desc="Summarizing chunks")
  #     else:
  #         chunk_iterator = enumerate(chunks, 1)
  ```
- **Acceptance criteria for this module**:
  - A new unit test simulates `tqdm` being absent WITHOUT uninstalling it
    from the shared dev `.venv` (which the task must not touch — worktrees
    share one editable-installed venv, per `.claude/rules/
    worktree-management.md` §4): use
    `monkeypatch.setitem(sys.modules, "tqdm.asyncio", None)` combined with
    `importlib.reload(parrot.bots.flows.crew.crew)` inside the test (the
    standard technique for exercising an import-guard branch without a real
    uninstall), and assert the reload succeeds and `async_tqdm is None`
    afterward. Reload the module back (or run in a subprocess) so the
    monkeypatch doesn't leak into other tests in the same session.
  - With `async_tqdm` patched to `None` (no reload needed for this one —
    patch the module attribute directly) and `self.use_tqdm=True`, the
    summarization call path does not raise; it falls back to the plain
    `enumerate` branch used elsewhere in the same method (verified:
    `crew.py:4164`).
  - No change in behavior when `tqdm` **is** installed (existing
    `use_tqdm=True` tests, if any, continue to pass unchanged).

### Module 2: Extend graceful-degradation to optional-satellite tests + add real CI coverage

- **Path (new)**: `.github/workflows/ci.yml` (new job)
- **Path (modifies)**: every test file listed below, plus any sharing the
  same shape found while running the suite (§ Delegation-eligible table)
- **Responsibility**: (a) guard every test module that imports an optional
  satellite's namespace so `test-core`'s bare-core sweep degrades cleanly
  instead of hard-failing collection — **zero change to what any test
  asserts once its extra IS present**; (b) add one new CI job that actually
  installs those satellites and runs the guarded tests for real, with an
  explicit "nothing was silently skipped" gate, mirroring
  `test-wiki-extras`/`test-wiki-luau-fallback` (verified:
  `.github/workflows/ci.yml:140-286`).
- **Depends on**: nothing (independent of M1/M3/M4/M5/M6/M7/M8; different
  files).

#### 2a. Confirmed file list (minimum floor — see delegation table)

| File | Needs (extra/package) | Verified |
|---|---|---|
| `tests/clients/test_bridged_hitl.py` | `ai-parrot-client-anthropic` | `parrot.clients.anthropic.claude_agent_bridge` — CI log |
| `tests/clients/test_google_fallback.py`, `test_google_function_name_sanitization.py` | `ai-parrot-client-google` | `parrot.clients.google.client` — CI log |
| `tests/clients/test_meta_client.py`, `test_meta_grounding.py`, `test_meta_models.py`, `test_meta_responses.py`, `test_meta_tool_search.py` | `ai-parrot-client-meta` | `parrot.clients.meta` — CI log |
| `tests/clients/test_moonshot_client.py` | `ai-parrot-client-moonshot` | `parrot.clients.moonshot` — CI log |
| `tests/clients/test_openai_base_parity.py`, `test_openai_fallback.py`, `test_openai_compatible_defaults.py`, `test_client_fallback.py` | `ai-parrot-client-openai` / `-anthropic` (mixed, see log) | `parrot.clients.openai` / `.anthropic` — CI log |
| `tests/handlers/test_document_understanding_integration.py`, `tests/integration/test_claude_agent_tool_bridge.py` | `ai-parrot-client-google` / `-anthropic` | CI log |
| `tests/integration/test_crew_infographic_e2e.py`, `tests/integration/test_saved_executions_flow.py`, `tests/test_crew_hooks.py`, `tests/bots/flows/core/storage/test_agentcrew_lifecycle.py`, `test_crew_agent_persistence.py`, `test_execution_wiki_wiring.py`, `test_integration.py`, `test_agentsflow_lifecycle.py` | already fixed by **M1** — confirm these do NOT ALSO need a guard once M1 lands; if any still fail post-M1 for an unrelated reason, add a guard here | tqdm cascade — CI log |
| `tests/mcp/test_oauth2_e2e.py`, `test_oauth2_integration.py`, `test_oauth2_storage.py`, `tests/auth/test_mcp_oauth2_provider.py` | third-party `mcp` SDK | CI log |
| `tests/integration/oauth2/` (whole dir) | `ai-parrot-integrations` | CI log |
| `tests/unit/test_faiss_s3.py` | `ai-parrot-embeddings` (moved there by `cd320f0c77`, TASK-1335 — verified: `git log --follow`; no `--extra` needed — its own `faiss` extra is empty/name-only, `faiss-cpu` itself is already an unconditional `ai-parrot` core dependency, verified: `packages/ai-parrot/pyproject.toml:162`) | CI log + git history |
| `tests/test_fireflies_wiki_agent.py` (dynamically loads `agents/fireflies_wiki.py:79`) | `ai-parrot-server[scheduler]` (`apscheduler`) | CI log; self-diagnosing error at `packages/ai-parrot/src/parrot/_imports.py:224` already names this exact cause |
| `tests/pipelines/` (at least `test_endcap_no_shelves.py`) | `ai-parrot-pipelines` (`parrot_pipelines`) — found during this spec's review pass, was missing from the original list entirely | CI log (`pydantic_core.ValidationError: 1 validation error for IdentifiedProduct`, traced to `packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/types/endcap_no_shelves_promotional.py:630`) |
| `tests/scripts/test_generate_a2ui_css.py::test_generate_a2ui_css_vendor_check` | `ai-parrot-visualizations[map]` (`folium`) — already synced by the separate `Lint & Registry Check` job (verified: `ci.yml:56-57`) for its OWN vendored-asset check; this test only needs a guard here, not a second sync of the same extra in this new job | CI log |
| `tests/knowledge/wiki/languages/test_outline_parity.py`, `tests/knowledge/wiki/structural/test_tools.py`, `tests/knowledge/wiki/test_cli_symbols.py`, `tests/knowledge/wiki/test_structural_e2e.py` | `wiki-structural` extra (ast-grep-py) — these assert the **extra-present** behavior unconditionally, unlike the Luau tests' `pytest.mark.skipif(get_parser(...) is None, ...)` pattern at `tests/knowledge/wiki/languages/test_luau.py` (verified pattern) | CI log |

**Explicitly NOT in this list — reclassified to Module 8 during this
spec's review pass**: `tests/handlers/test_mediagen_handler.py`,
`tests/handlers/test_understanding_handler.py`,
`tests/handlers/test_understanding_integration.py`, and
`tests/auth/test_policy_rules_integration.py`. All four were originally
(and incorrectly) placed in this table as "satellite gap" cases. They are
not: see M8 for why installing a satellite would not fix any of them.

For every file above, follow the **existing repo convention**, not a new
one: `pytest.importorskip("<module>")` at module scope for a straight
missing-module case, or the `pytest.mark.skipif(<probe>() is None, ...)`
pattern already used for Luau (verified:
`tests/knowledge/wiki/languages/test_luau.py`) when the seam has its own
availability probe. **Never** convert a hard failure into a silent pass by
weakening an assertion — a skip is not a pass, and the new CI job in §2b
must prove it still runs for real.

#### 2b. New CI job

- **Interface Skeleton** *(new `ci.yml` job, YAML — not Python, no
  "signature" in the usual sense, but the exact contract this job must
  satisfy)*:
  ```yaml
  # .github/workflows/ci.yml  (new job, pattern verified against
  # test-wiki-extras/test-wiki-luau-fallback at ci.yml:140-286)
  test-optional-integrations:
    name: "Test optional integrations (LLM clients + scheduler + oauth2 + mcp + embeddings)"
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v6
      - uses: actions/setup-python@v6
        with:
          python-version: "3.12"
      - uses: astral-sh/setup-uv@v4
        with:
          version: "latest"
      # ONE combined sync call. `uv sync` performs an EXACT sync by default
      # (verified: `uv help sync` — "uv removes packages that are not
      # declared as dependencies of the project"); splitting this into
      # several sequential `uv sync` invocations would have each call
      # UNDO the packages the previous call just installed. Every
      # `--package`/`--extra` this job needs MUST stay in this one command.
      - name: Sync ai-parrot + every optional-integration satellite
        run: |
          uv sync --package ai-parrot --extra mcp \
            --package ai-parrot-client-amazon --package ai-parrot-client-anthropic \
            --package ai-parrot-client-gemma4 --package ai-parrot-client-google \
            --package ai-parrot-client-grok --package ai-parrot-client-groq \
            --package ai-parrot-client-hf --package ai-parrot-client-local \
            --package ai-parrot-client-meta --package ai-parrot-client-moonshot \
            --package ai-parrot-client-nvidia --package ai-parrot-client-openai \
            --package ai-parrot-client-openrouter --package ai-parrot-client-vllm \
            --package ai-parrot-client-zai \
            --package ai-parrot-server --extra scheduler \
            --package ai-parrot-integrations \
            --package ai-parrot-embeddings \
            --package ai-parrot-pipelines
      - name: Scaffold NavConfig environment
        run: mkdir -p env/dev && touch env/dev/.env
      - name: Run optional-integration tests with every satellite installed
        run: |
          uv run pytest tests/clients/ tests/mcp/ tests/integration/oauth2/ \
            tests/unit/test_faiss_s3.py tests/test_fireflies_wiki_agent.py \
            tests/auth/test_mcp_oauth2_provider.py tests/pipelines/ \
            -q --tb=short 2>&1 | tee /tmp/optional-integrations.log
      # Luau-style gate (verified pattern: ci.yml:208-218) — a skip here can
      # only mean a regression in this job's own sync step, never "the
      # satellite was never really installed".
      - name: Confirm nothing was silently skipped
        run: |
          if grep -q "SKIPPED" /tmp/optional-integrations.log; then
            echo "::error::A guarded test was skipped even though this job installs every satellite it needs."
            exit 1
          fi
  ```
  `mcp` (the third-party SDK, needed by `tests/mcp/*` and
  `tests/auth/test_mcp_oauth2_provider.py`) and `googleapiclient` are BOTH
  provided by `ai-parrot`'s own `mcp` extra (verified:
  `packages/ai-parrot/pyproject.toml:459-478` — `mcp = [..., "mcp>=1.28.1,<2",
  ..., "google-api-python-client>=2.151.0", ...]`) — resolved during this
  review pass; the original draft had left these two as an open TODO. Do
  **not** rely on `ai-parrot-client-openai`'s own `bridge` extra for `mcp` —
  that extra is NOT requested by this job's `--package
  ai-parrot-client-openai` (no `--extra bridge`), so it would not be
  installed even though the package name might suggest otherwise.

  **Not empirically verified in this spec**: whether `uv sync` correctly
  scopes an `--extra` name to the specific `--package` that declares it when
  several `--package` flags are given in one call (here, `mcp` on `ai-parrot`
  and `scheduler` on both `ai-parrot` and `ai-parrot-server`, which happen to
  share the extra name and an identical pin, so any ambiguity is harmless
  either way). This was **not** run live in this pass — doing so would sync
  the shared worktree `.venv` used by other sessions (`.claude/rules/
  worktree-management.md` §4 forbids `uv sync` disturbances of that kind
  outside a throwaway environment). The implementing task MUST dry-run this
  exact command (isolated venv, or a draft PR) before merging, and adjust
  the flag grouping if `uv` reports an error rather than assume the snippet
  above is correct as written.

- **Acceptance criteria for this module**:
  - `test-core` (bare `uv sync --package ai-parrot`) no longer fails
    collection on any file in §2a's list — each degrades to a real,
    reported `SKIPPED`, not an `ERROR`.
  - The new `test-optional-integrations` job passes, and its "Confirm
    nothing was silently skipped" step is green.
  - `test-wiki-extras` no longer fails on the ast-grep-related assertions
    listed in §2a (those tests either gain the same skip-guard as Luau, or
    — if `wiki-structural` genuinely IS installed in that job already,
    verified: `ci.yml:172` — the assertions there should already pass once
    M1's tqdm cascade stops masking them; confirm which is true before
    choosing the fix).

### Module 3: Promote `pymupdf`/`pymupdf4llm` to `ai-parrot` core dependencies

- **Path**: `packages/ai-parrot/pyproject.toml`
- **Responsibility**: Resolve the confirmed contradiction between
  `sdd/specs/wikitoolkit-ingest-documents.spec.md` (FEAT-451), which twice
  states these packages are "already a core dependency" (verified: spec
  lines 388, 797), and the actual `pyproject.toml`, where they only appear
  under the `bookstore` extra (verified: `pyproject.toml` line ~319) and a
  catch-all extra (~line 407). **Decision made in this spec**: restore the
  FEAT-451 spec's stated design intent (Option A from the proposal) —
  promote both to `[project.dependencies]`. This is the more conservative
  choice: it makes an already-accepted, already-written spec's own words
  true, rather than reopening FEAT-451's design. **Precedent confirmed
  during this spec's review pass**: `faiss-cpu>=1.9.0` — a comparably heavy
  native dependency backing a comparably optional feature (vector search)
  — is ALREADY an unconditional core dependency of `ai-parrot` (verified:
  `packages/ai-parrot/pyproject.toml:162`), so promoting `pymupdf` is
  consistent with existing practice, not a new category of exception.
- **Depends on**: nothing.
- **Interface Skeleton** *(pyproject.toml diff shape, not Python)*:
  ```toml
  # packages/ai-parrot/pyproject.toml
  # Move these two lines OUT of the `bookstore` extra (verified: line ~319)
  # and INTO [project.dependencies] (verified block starts pyproject.toml:34).
  # Do not duplicate the pin already present in the catch-all extra
  # (~line 407, "pymupdf==1.27.1" / "pymupdf4llm==0.0.27") — reconcile to
  # ONE version constraint used everywhere pymupdf is now referenced.
  dependencies = [
      # ... existing entries ...
      "pymupdf>=1.27",
      "pymupdf4llm>=0.0.27",
  ]
  ```
- **Acceptance criteria for this module**:
  - `uv sync --package ai-parrot` (no extras) installs `pymupdf`/
    `pymupdf4llm`.
  - `tests/knowledge/wiki/test_documents.py`, `test_cli.py::
    TestIngestSourceArgument`, `test_integration.py::
    TestFeat451DocumentIngestEndToEnd` collect and pass under
    `test-wiki-extras` (`wiki-languages` + `wiki-structural`, no
    `bookstore`) and under `test-core` (no extras at all).
  - `uv lock` resolves cleanly (no new conflicts introduced by moving these
    two packages to unconditional).

### Module 4: Restore the delegation section in `.claude/agents/sdd-worker.md`

- **Path**: `.claude/agents/sdd-worker.md`
- **Responsibility**: Reinsert the `### b2) Delegated implementation`
  section (dropped by commit `26de90a91`, TASK-3124's Orchestrator Loop
  rewrite, without replacement — verified via `git show 26de90a91 --
  .claude/agents/sdd-worker.md`) into the current "Fallback: Sequential
  Loop", between `### b) Verify Codebase Contract` (verified: current line
  327) and `### c) Implement` (verified: current line 337).
- **Depends on**: nothing.
- **Interface Skeleton** *(markdown section to insert — content sourced
  verbatim from the ORIGINAL addition to THIS file, commit `461b74c2e`
  (`feat(tool-optimizations): TASK-3090 …`), retrieved via `git show
  461b74c2e -- .claude/agents/sdd-worker.md`; this is the exact text
  `26de90a91` deleted. **Correction (review pass)**: the first draft of this
  spec mis-cited this block as "sourced from `.claude/commands/
  sdd-start.md`" — that sibling doc's CURRENT wording has since drifted
  slightly (numbered steps 1-8, "Otherwise implement the task yourself — the
  normal route is the default" instead of "A task without one takes the
  normal route in step (c) — that is the default, not a failure"). Restore
  the text below — sdd-worker.md's OWN original wording — not sdd-start.md's
  current one; both are semantically equivalent, but the anti-hallucination
  contract requires citing the actual source, not a plausible-looking one)*:
  ```markdown
  ### b2) Delegated implementation (ONLY when a Delegation Contract exists)

  Skip this entire step unless the task file contains a `## Delegation Contract`
  section AND the `parrot-targeted-writer` MCP server is available. A task
  without one takes the normal route in step (c) — that is the default, not a
  failure.

  1. Call MCP tool `writer_generate` (server `parrot-targeted-writer`) with `task_path`.
  2. On `status: error` with a contract code (`stale_target`, `missing_block`,
     `placeholder_code`, `underspecified_create`, …): fix the packet in the task file
     (refresh hashes with `sha256sum`, complete the design) and retry once, or implement
     the task yourself in step (c). **Never silently invokes another coder** — no other
     coding tool is substituted when delegation fails.
  3. On `ok`: read `data.patch_path` with `source_read` in ranges of at most 350 lines and
     review EVERY hunk against the task's Codebase Contract. Never apply a patch you have
     not fully read. If a hunk is wrong, do not apply: fix the packet/blocks and regenerate
     at most once more, else implement normally.
  4. Call `writer_apply` with `artifact_id` and `reviewed_sha256 = data.patch_sha256`
     (verify it equals `sha256sum artifacts/tool-optimizations/<id>/patch.diff`).
  5. Run the task's acceptance tests yourself in step (e). The writer never runs tests, and
     a model's claim that tests passed is not execution evidence.
  6. SDD state is never delegated: the index and task files are edited only by you,
     in step (g).
  ```
  Also add the checklist line to the existing verification checklist block
  (verified current location: inside step d)'s `VERIFICATION CHECKLIST for
  TASK-<NNN>:` block, lines 344-352 — step d) itself sits between step c)
  Implement and step e) Validate):
  ```
  □ Delegated patch hunks were all reviewed before writer_apply?
  ```
- **Acceptance criteria for this module**:
  - `pytest packages/ai-parrot-tools/tests/tool_optimizations/
    test_sdd_contracts.py -k sdd-worker -q` — all 4 previously-failing
    parametrized cases (`test_review_happens_before_apply[sdd-worker]`,
    `test_sdd_worker_has_the_delegated_step_and_checklist_line`,
    `test_documents_state_that_sdd_files_are_never_delegated[worker]`,
    `test_documents_forbid_substituting_another_coder[worker]`) pass.
  - The full `test-tool-optimizations` suite passes on both Python 3.11 and
    3.12 (currently 418 passed / 4 failed / 1 skipped — expect 422 passed /
    0 failed / 1 skipped).
  - No other content in `.claude/agents/sdd-worker.md` changes — this is a
    pure restoration, not a rewrite of the Orchestrator Loop.

### Module 5: Fix the stale schema-version assertion in the wiki migration test

- **Path**: `tests/knowledge/wiki/test_store_migration_v2.py`
- **Responsibility**: `SCHEMA_VERSION` is `"3"` today (bumped from `"2"` by
  commit `a26ff2824e`, "fix(wiki): external-content FTS5...", which added
  `SQLiteWikiStore._migrate_fts` — verified via `git show a26ff2824e --
  packages/ai-parrot/src/parrot/knowledge/wiki/store.py`). The test still
  hardcodes the old target version (verified: line 75,
  `assert row[0] == SCHEMA_VERSION == "2"`). Fix by asserting against the
  live `SCHEMA_VERSION` import (already imported at line 16) and add real
  coverage for the 2→3 step (`_migrate_fts`) so the fix is a genuine
  extension of test coverage, not a relabeled literal.
- **Depends on**: nothing.
- **Interface Skeleton** *(test-file diff shape)*:
  ```python
  # tests/knowledge/wiki/test_store_migration_v2.py
  # CURRENT (line 75, verified):
  #     assert row[0] == SCHEMA_VERSION == "2"
  #
  # REQUIRED: assert against the live constant only (it already equals "3";
  # do not hardcode the new number either — that just moves the staleness
  # forward to the next bump):
  #     assert row[0] == SCHEMA_VERSION
  #
  # AND add a new test in the same file/class exercising the 2->3 step
  # specifically, e.g. (illustrative shape, not literal body — task designs
  # the fixture):
  #     async def test_migrate_fts_upgrades_v2_plane_to_v3(v2_db_fixture):
  #         """Exercises SQLiteWikiStore._migrate_fts, added by a26ff2824e."""
  #         ...
  ```
- **Acceptance criteria for this module**:
  - `pytest tests/knowledge/wiki/test_store_migration_v2.py -q` passes.
  - The file gains at least one assertion that specifically exercises
    `_migrate_fts` (verified: `packages/ai-parrot/src/parrot/knowledge/
    wiki/store.py`, method added by commit `a26ff2824e`) — not just the
    v1→v2 path already covered.
  - A future `SCHEMA_VERSION` bump does not require touching this file's
    assertions again (only new fixtures/migration-specific tests, if any).

### Module 6: Rewrite the `BASE_CSS`-based assertions in `test_infographic_html.py`

- **Path**: `tests/test_infographic_html.py`
- **Responsibility**: `BASE_CSS` was removed from `parrot.outputs.formats.
  infographic_html` by FEAT-493/TASK-2712, replaced by
  `DesignSystem.stylesheet(theme_cfg, layout_name)` (verified:
  `packages/ai-parrot-visualizations/src/parrot/outputs/formats/
  infographic_html.py` lines 320-321, 419-420 — explicit docstring mentions
  of "the legacy `BASE_CSS`, now `layout-report.css`"). The `"report"`
  layout is documented as the one reproducing the old look. This module's
  ~15 `BASE_CSS`-based assertions (verified: lines 54, 324, 338-343, and
  more through at least line 1325) need translating to the new composer —
  case by case, since some assertions may target CSS that moved between
  `_BASE_CSS`/`_COMPONENTS_CSS`/`_EDITORIAL_CSS`/the `report` layout sheet
  (verified: `packages/ai-parrot-visualizations/src/parrot/outputs/
  formats/assets/design_system/__init__.py` lines 52-83), not necessarily
  all landing in one place.
- **Depends on**: nothing.
- **Interface Skeleton** *(the target API this file must import instead)*:
  ```python
  # tests/test_infographic_html.py
  # CURRENT (line 54, verified):
  #     from parrot.outputs.formats.infographic_html import BASE_CSS, InfographicHTMLRenderer
  #
  # REQUIRED:
  from parrot.outputs.formats.assets.design_system import DesignSystem  # verified: design_system/__init__.py:91
  from parrot.models.infographic import theme_registry  # verified: design_system/__init__.py:24 (same import DesignSystem itself uses)

  # DesignSystem.stylesheet signature (verified: design_system/__init__.py:100-108):
  #     @classmethod
  #     def stylesheet(cls, theme: "str | ThemeConfig | None" = None,
  #                     layout: str | None = None, *, paged: bool | None = None) -> str: ...
  #
  # Replacement for every current `BASE_CSS` reference (illustrative — task
  # decides per-assertion whether `paged=False` or the default derived value
  # is correct for that specific historical check):
  #     css = DesignSystem.stylesheet(theme_registry.get("light"), layout="report", paged=False)
  ```
- **Acceptance criteria for this module**:
  - No reference to the removed `BASE_CSS` symbol remains in this file.
  - `pytest tests/test_infographic_html.py -q` passes.
  - Every existing assertion's *intent* is preserved (e.g.
    `test_no_literal_colors_in_base_css`, `test_callout_colors_use_
    variables`, `test_print_styles_untouched` must still verify the same
    design properties — no literal colors, callout CSS variables present,
    print media rules intact — against the composed `report`-layout sheet).
    Where an old assertion's target genuinely no longer applies (e.g. a
    rule that moved to a *different* layout, or was intentionally dropped
    by FEAT-493), that must be a documented, deliberate removal in the
    task's Completion Note — never a silent deletion.

### Module 7: Diagnose (then fix) the remaining unexplained `test-core` collection errors

- **Path**: `tests/unit/test_database_agent.py`, `tests/manager/
  test_botmanager_wiring.py` (5 occurrences total, `DatabaseAgentToolkit`/
  `DatabaseAgent` import errors); one `create_netsuite_mcp_server() got an
  unexpected keyword argument 'token_store'` (1 occurrence, file not yet
  identified in this spec — `grep` the CI log for it).
- **Responsibility**: This spec explicitly does **not** know the root cause
  yet. What was verified:
  - `parrot.bots.database.toolkits.DatabaseAgentToolkit` and
    `parrot.bots.database.agent.DatabaseAgent` both genuinely exist in the
    source (verified: `packages/ai-parrot/src/parrot/bots/database/
    toolkits/_internal.py:45`, `packages/ai-parrot/src/parrot/bots/
    database/agent.py:105`), and none of the modules in their import chain
    (`toolkits/base.py`, `sql.py`, `postgres.py`, `bigquery.py`,
    `influx.py`, `elastic.py`, `documentdb.py`, `_internal.py`) import
    anything obviously optional/satellite-gated.
  - `tests/unit/test_database_agent.py:16` uses a non-standard dynamic
    module-loading pattern (`_spec.loader.exec_module(_mod)`) rather than a
    plain `import` — the `(unknown location)` qualifier on the
    `DatabaseAgentToolkit` `ImportError` is consistent with (but not proven
    to be caused by) that custom loader interacting badly with relative
    imports inside the dynamically-loaded module.
  - This does **not** match the M1 (tqdm) or M2 (satellite) shape — it is
    reported here, honestly, as unresolved rather than guessed.
- **Depends on**: nothing (independent of all other modules; different
  files).
- **Interface Skeleton**: none — this module is a diagnosis task. No fix is
  specified until the cause is found.
- **Acceptance criteria for this module**:
  - A concrete root cause is written into the task's Completion Note,
    with evidence (a minimal local repro is strongly preferred over log
    reading alone, e.g. reproducing the exact `uv sync --package
    ai-parrot` + `pytest tests/unit/test_database_agent.py` combination in
    an isolated environment).
  - Either the fix is applied and `pytest tests/unit/test_database_agent.py
    tests/manager/test_botmanager_wiring.py -q` passes, **or**, if the true
    cause is determined to be out of this spec's scope (e.g. a pre-existing
    CI-runner caching artifact unrelated to any of M1-M6), that
    determination is recorded with evidence and the item is explicitly
    deferred (not silently dropped) — filed as its own follow-up per the
    SDD ledger convention (`code-reviewer`/`/sdd-done` step).
  - Same treatment for the `create_netsuite_mcp_server(token_store=...)`
    signature-mismatch occurrence: locate its call site and its current
    real signature, and either fix the call/signature drift or file it.

### Module 8: Fix stale mock-patch targets left behind by two unrelated refactors

- **Path**: `tests/handlers/test_mediagen_handler.py`,
  `tests/handlers/test_understanding_handler.py`,
  `tests/handlers/test_understanding_integration.py`,
  `tests/auth/test_policy_rules_integration.py`.
- **Responsibility**: **Added during this spec's review pass** — the
  original draft mis-filed these four files under M2 as a "satellite
  absent" case. They are not: installing `ai-parrot-client-google` would
  **not** fix any of them, because the code they test was deliberately
  refactored to stop exposing the names these tests try to patch, and the
  tests were never updated to match — the same "test lagged a legitimate,
  already-shipped change" shape as M5/M6, just discovered later.
  - `test_mediagen_handler.py` and `test_understanding_handler.py`/
    `test_understanding_integration.py` each define
    `HANDLER_PATH = "parrot.handlers.<mediagen|understanding>.GoogleGenAIClient"`
    and call `unittest.mock.patch(HANDLER_PATH)`. This target has not
    existed at module scope since FEAT-523 (TASK-2846) — verified: both
    `packages/ai-parrot-server/src/parrot/handlers/mediagen.py:90` and
    `packages/ai-parrot-server/src/parrot/handlers/understanding.py:213` now
    read `from parrot.clients.google import GoogleGenAIClient` **inside the
    handler method body**, with an explicit comment at `understanding.py:
    210-211`: *"FEAT-523 (TASK-2846): lazy import — core must not import a
    provider module at module scope (AC-3)."* `unittest.mock.patch` can only
    replace a name bound at module scope; patching a function-local import
    target raises exactly the observed `AttributeError: <module ...> does
    not have the attribute 'GoogleGenAIClient'` — **regardless of whether
    `ai-parrot-client-google` is installed**. Confirmed via `git log -p`
    that the module-level import existed before FEAT-523 and was
    deliberately removed by it.
  - `test_policy_rules_integration.py` patches
    `parrot.handlers.bots._EvalContext`. `bots.py` used to hold a
    module-level `_EvalContext = None` fallback (same pattern still used
    today by `packages/ai-parrot/src/parrot/bots/abstract.py:157-164`), but
    commit `322b3d0674` (`feat(saas-auth-hardening): TASK-2321 —
    consolidate eval-context builders into parrot/auth/eval_context.py`)
    removed it and replaced it with a delegated call to
    `parrot.auth.eval_context.build_eval_context()` (verified:
    `packages/ai-parrot-server/src/parrot/handlers/bots.py:16`, `from
    parrot.auth.eval_context import build_eval_context as
    _core_build_eval_context`; `packages/ai-parrot/src/parrot/auth/
    eval_context.py:23`, `async def build_eval_context(request:
    web.Request) -> object | None`). An unrelated feature from M1-M7's
    causes (`saas-auth-hardening`, not FEAT-523/FEAT-549/FEAT-493/FEAT-557).
- **Depends on**: nothing (independent of all other modules; different
  files).
- **Interface Skeleton** *(the correction pattern — not a new component)*:
  ```python
  # tests/handlers/test_mediagen_handler.py, test_understanding_handler.py,
  # test_understanding_integration.py
  # CURRENT (verified, e.g. test_understanding_handler.py:16):
  #     HANDLER_PATH = "parrot.handlers.understanding.GoogleGenAIClient"
  #
  # REQUIRED: patch the actual source the lazy `from X import Y` resolves
  # against at call time — patching the SOURCE attribute is visible to a
  # function-local import precisely because that import re-reads the
  # attribute from the source module every time it runs:
  #     HANDLER_PATH = "parrot.clients.google.GoogleGenAIClient"
  # (verify this is genuinely the resolution path — `parrot.clients.google`
  # re-exports `GoogleGenAIClient` per its own `__init__.py`; confirm with
  # `python -c "from parrot.clients.google import GoogleGenAIClient"`
  # before assuming the dotted path above is import-safe to patch).
  # This also means these three files now need an `ai-parrot-client-google`
  # sync to even LOCATE the patch target — add them to Module 2's new
  # `test-optional-integrations` job (§3/M2) alongside a
  # `pytest.importorskip("parrot.clients.google")` guard for `test-core`.

  # tests/auth/test_policy_rules_integration.py
  # CURRENT (verified, 4 occurrences):
  #     patch('parrot.handlers.bots._EvalContext', MagicMock(...))
  #
  # REQUIRED: patch what bots.py actually calls today —
  #     patch('parrot.handlers.bots._core_build_eval_context', ...)
  # (verified import alias: packages/ai-parrot-server/src/parrot/handlers/
  # bots.py:16) — or patch `parrot.auth.eval_context.build_eval_context`
  # at its source, whichever the test's assertions on the mocked object's
  # call signature/return shape actually require; read what each of the 4
  # call sites expects `_EvalContext(...)` to return before choosing.
  ```
- **Acceptance criteria for this module**:
  - `pytest tests/handlers/test_mediagen_handler.py
    tests/handlers/test_understanding_handler.py
    tests/handlers/test_understanding_integration.py
    tests/auth/test_policy_rules_integration.py -q` passes under the new
    `test-optional-integrations` job (M2) with `ai-parrot-client-google`
    installed.
  - The same four files degrade to `SKIPPED` (not `ERROR`) under bare
    `test-core`, via the same `pytest.importorskip` convention as M2.
  - No change to what any test asserts about handler *behavior* — only the
    patch target changes, because the code being tested is unchanged; this
    is purely correcting test plumbing that fell out of sync with a
    deliberate lazy-import refactor.

---

## 4. Test Specification

### Unit Tests

| Test | Module | Description |
|---|---|---|
| `monkeypatch`-simulated tqdm-absence unit test + reload (see M1's acceptance criteria) | M1 | Import succeeds without `tqdm`; falls back cleanly |
| `pytest tests/clients/ tests/mcp/ tests/integration/oauth2/ tests/unit/test_faiss_s3.py tests/test_fireflies_wiki_agent.py tests/pipelines/ tests/scripts/test_generate_a2ui_css.py -q` (bare core) | M2 | Every listed file reports `SKIPPED`, never `ERROR` |
| `pytest tests/clients/ ... -q` (new `test-optional-integrations` job, all satellites installed) | M2 | All pass, none skipped |
| `pytest tests/knowledge/wiki/test_documents.py tests/knowledge/wiki/test_cli.py tests/knowledge/wiki/test_integration.py -q` | M3 | Pass under `test-wiki-extras` AND `test-core` (no extras at all) |
| `pytest packages/ai-parrot-tools/tests/tool_optimizations/test_sdd_contracts.py -q` | M4 | 422 passed / 0 failed / 1 skipped |
| `pytest tests/knowledge/wiki/test_store_migration_v2.py -q` | M5 | Passes; includes new `_migrate_fts` coverage |
| `pytest tests/test_infographic_html.py -q` | M6 | Passes; no `BASE_CSS` reference remains |
| `pytest tests/unit/test_database_agent.py tests/manager/test_botmanager_wiring.py -q` | M7 | Passes, or deferred with evidence |
| `pytest tests/handlers/test_mediagen_handler.py tests/handlers/test_understanding_handler.py tests/handlers/test_understanding_integration.py tests/auth/test_policy_rules_integration.py -q` | M8 | Passes under `test-optional-integrations`; `SKIPPED` (not `ERROR`) under bare `test-core` |

### Integration Tests

| Test | Description |
|---|---|
| Full `test-core` CI job (`.github/workflows/ci.yml`, both Python 3.11/3.12 legs) | Goes from failing (277-319 errors/failures) to passing modulo the explicit Non-Goals list in §1 — **and modulo the unrelated `navigator-session`/py3.13 resolver regression flagged in §1's addendum**, which may independently block this job's `uv sync` step regardless of M1-M8 |
| Full `test-wiki-extras` CI job | Goes green |
| Full `test-tool-optimizations` CI job (both Python legs) | Goes green |
| New `test-optional-integrations` CI job | Green, including its "nothing silently skipped" gate |

### Test Data / Fixtures

No new fixtures required beyond what M5 needs for its `_migrate_fts`
coverage (a `wiki_v2.db`-shaped fixture, or an in-place upgrade of the
existing `wiki_v1.db` fixture through both migration steps — task's
choice, consistent with the existing `v1_db` fixture pattern already in
`test_store_migration_v2.py`).

---

## 5. Acceptance Criteria

> This feature is complete when ALL of the following are true:

- [ ] `test-core` (Python 3.11 and 3.12) no longer fails on any of: the
      `tqdm` import cascade (M1), any file in M2's confirmed list (M2), the
      `pymupdf` collection errors (M3), the `test_store_migration_v2.py`
      assertion (M5), the `BASE_CSS` import error (M6), or the four
      stale-mock-target failures (M8) — modulo the explicit residual items
      named in §1 Non-Goals, M7's diagnose-or-defer outcome, and the
      unrelated `navigator-session`/py3.13 resolver regression flagged in
      §1's addendum (a separate, already-tracked blocker, not this spec's
      to fix).
- [ ] `test-wiki-extras` passes in full.
- [ ] `test-tool-optimizations` passes in full on both Python legs.
- [ ] A new `test-optional-integrations` CI job exists, passes, and its
      "nothing silently skipped" gate is green.
- [ ] No test assertion was weakened, relaxed, or deleted to make a job
      pass, except where §3 explicitly documents that the old assertion's
      target no longer exists and the replacement is recorded as a
      deliberate, evidenced decision (M6's per-assertion translations, M5's
      switch from a hardcoded literal to the live constant, M8's patch-target
      corrections).
- [ ] `uv lock` / `uv sync --all-packages` still resolves cleanly after M3's
      dependency move (no new conflicts), **and** the new `test-optional-
      integrations` sync command in M2 was actually dry-run (not merely
      inspected) before this criterion is marked done.
- [ ] M7 ends in either a genuine fix with a passing test, or an explicitly
      recorded, evidenced deferral — never a silent skip.

---

## 6. Codebase Contract

> **CRITICAL — Anti-Hallucination Anchor**
> This section is the single source of truth for what exists in the
> codebase. Implementation agents MUST NOT reference imports, attributes,
> or methods not listed here without first verifying they exist via `grep`
> or `read`.

### Verified Imports

```python
from tqdm.asyncio import tqdm as async_tqdm  # verified: packages/ai-parrot/src/parrot/bots/flows/crew/crew.py:44
from parrot.knowledge.wiki.store import SCHEMA_VERSION, SQLiteWikiStore  # verified: tests/knowledge/wiki/test_store_migration_v2.py:16
from parrot.outputs.formats.assets.design_system import DesignSystem  # verified: packages/ai-parrot-visualizations/src/parrot/outputs/formats/assets/design_system/__init__.py:91
from parrot.models.infographic import ThemeConfig, theme_registry  # verified: design_system/__init__.py:24
from parrot.bots.database.toolkits import DatabaseAgentToolkit  # verified: packages/ai-parrot/src/parrot/bots/database/toolkits/__init__.py:16
from parrot.bots.database.agent import DatabaseAgent  # verified: packages/ai-parrot/src/parrot/bots/database/agent.py:105
from parrot.auth.eval_context import build_eval_context  # verified: packages/ai-parrot/src/parrot/auth/eval_context.py:23 (async def, returns object | None)
```

### Existing Class Signatures

```python
# packages/ai-parrot/src/parrot/bots/flows/crew/crew.py
class AgentCrew(PersistenceMixin, SynthesisMixin):  # verified: crew.py:109 (the file's only class)
    use_tqdm: bool  # line 227, kwargs.get("use_tqdm", True)
    # call site using async_tqdm: lines 4159-4164

# packages/ai-parrot-visualizations/src/parrot/outputs/formats/assets/design_system/__init__.py
class DesignSystem:
    LAYOUTS: ClassVar[frozenset[str]]  # {"report", "analytics", "print"} — line 96
    DEFAULT_LAYOUT: ClassVar[str]  # "analytics" — line 98
    @classmethod
    def stylesheet(cls, theme: "str | ThemeConfig | None" = None,
                    layout: str | None = None, *, paged: bool | None = None) -> str: ...  # line 100

# packages/ai-parrot/src/parrot/knowledge/wiki/store.py
SCHEMA_VERSION = "3"  # line 50
class SQLiteWikiStore:
    async def _migrate_fts(self, conn) -> None: ...  # added by commit a26ff2824e

# packages/ai-parrot-server/src/parrot/handlers/mediagen.py, understanding.py
# (M8): GoogleGenAIClient is imported INSIDE the handler method, not at module
# scope — verified: mediagen.py:90, understanding.py:213 (explicit comment
# at understanding.py:210-211 citing FEAT-523 TASK-2846, AC-3).

# packages/ai-parrot-server/src/parrot/handlers/bots.py
# (M8): line 16, `from parrot.auth.eval_context import build_eval_context as
# _core_build_eval_context` — this is the CURRENT delegation target;
# `_EvalContext` was removed from this file's module scope by commit
# 322b3d0674 (feat(saas-auth-hardening): TASK-2321).
```

### Integration Points

| New Component | Connects To | Via | Verified At |
|---|---|---|---|
| M1's guarded import | `AgentCrew`'s existing `use_tqdm` flag | runtime `if self.use_tqdm and async_tqdm is not None:` | `crew.py:227`, `4159` |
| M2's new CI job | `ai-parrot-client-*` (15 packages), `ai-parrot-server[scheduler]`, `ai-parrot-integrations`, `ai-parrot-embeddings`, `ai-parrot-pipelines`, `ai-parrot[mcp]` | `uv sync --package ...` (ONE combined call — see M2's caveat on `uv sync`'s exact-sync semantics) | `sdd/tasks/index/pep-420-llm-clients.json` (FEAT-523, all 15 packages `"done"`); `packages/ai-parrot/pyproject.toml:459` (`mcp` extra) |
| M3's promoted dependency | `DocumentAcquirer` PDF page-count path | already-existing call, per FEAT-451 spec | `sdd/specs/wikitoolkit-ingest-documents.spec.md:388` |
| M4's restored section | commit `461b74c2e`'s original addition to THIS file (not a different doc) | verbatim content reuse | `git show 461b74c2e -- .claude/agents/sdd-worker.md` |
| M8's corrected patch targets | `parrot.clients.google.GoogleGenAIClient` (source of the lazy import); `parrot.handlers.bots._core_build_eval_context` / `parrot.auth.eval_context.build_eval_context` | `unittest.mock.patch` retargeting | `mediagen.py:90`, `understanding.py:213`, `bots.py:16`, `eval_context.py:23` |

### Does NOT Exist (Anti-Hallucination)

- ~~`parrot.outputs.formats.infographic_html.BASE_CSS`~~ — removed by
  FEAT-493/TASK-2712. Do not reference it in the rewritten test.
- ~~`packages/ai-parrot/src/parrot/clients/google/*.py`,
  `.../clients/anthropic/*.py`, etc.~~ — emptied by FEAT-523; these now
  live ONLY in the `ai-parrot-client-*` satellite packages.
- ~~`packages/ai-parrot/src/parrot/stores/faiss_store.py`~~ — moved to
  `packages/ai-parrot-embeddings/src/parrot/stores/faiss_store.py` by
  commit `cd320f0c77` (TASK-1335). A CI log from one specific run showed an
  `ImportError` citing the OLD core path as if the file still existed
  there — this is very likely a stale `uv`/editable-install cache artifact
  on that particular runner, not a real file; do not "restore" a file at
  the old core path to fix this.
- ~~A `state.schema.json` / `research_plan.schema.json` in
  `sdd/templates/`~~ — referenced by `/sdd-proposal`'s own command text but
  not present in this repo (noted in FEAT-568's proposal §7). Unrelated to
  this spec's modules; do not create these unless asked.
- ~~`parrot.handlers.mediagen.GoogleGenAIClient`,
  `parrot.handlers.understanding.GoogleGenAIClient`~~ (M8) — these names
  are never bound at module scope; the import is function-local
  (`mediagen.py:90`, `understanding.py:213`). Do not add a module-level
  import to "fix" this — that would reintroduce the hard dependency FEAT-523
  TASK-2846 deliberately removed (per its own `AC-3` comment). Fix the
  tests' patch target instead.
- ~~`parrot.handlers.bots._EvalContext`~~ (M8) — removed by commit
  `322b3d0674`; `bots.py` now delegates to
  `parrot.auth.eval_context.build_eval_context()` (imported as
  `_core_build_eval_context`). Do not reintroduce `_EvalContext` in
  `bots.py` to satisfy the old patch target — fix the test instead.

---

## 7. Implementation Notes & Constraints

### Patterns to Follow

- **Graceful degradation over hard failure**, the established convention:
  `pytest.importorskip(...)` or `pytest.mark.skipif(<probe> is None, ...)`
  — never a bare `try/except: pass` around an entire test body. See
  `tests/knowledge/wiki/languages/test_luau.py` for the reference pattern
  (verified, FEAT-532).
  Any job asserting the "extra present" path must also assert nothing was
  silently skipped — see `ci.yml:208-218` (verified, FEAT-532) for the
  reference gate shape reused in M2.
- **Cosmetic-feature imports are guarded, not required.** M1's fix pattern
  (try/except at import time, runtime fallback) is the template for any
  future "optional nicety" dependency — do not promote every such package
  to a hard dependency by default; M3 is the exception because the FEAT-451
  spec explicitly already called `pymupdf` core, not a new precedent for
  optional niceties in general.
- **Restoring dropped content must be a verbatim restoration**, not a
  paraphrase — M4 exists because a paraphrase-free git-diff comparison is
  what proved this was a regression rather than an intentional removal.

### Known Risks / Gotchas

- **M2's file list is a floor, not a ceiling.** The CI log analysis behind
  this spec covered one specific run; a full, current `test-core` run may
  surface additional files sharing the same shape. The implementing task
  MUST re-run collection and diff against this list, not treat it as
  exhaustive.
- **M3 risks a resolver conflict.** Promoting `pymupdf`/`pymupdf4llm` to
  unconditional core dependencies changes what `uv sync --package
  ai-parrot` pulls in for every consumer, including CI jobs that don't
  currently need it. Re-run `uv lock` and confirm no new `environments`
  split appears (see the already-fixed `async-notify`/aarch64 precedent —
  do not let a similar issue reappear silently).
  **PostgresToolkit** already needs a `dsn` argument bug (M7 Non-Goal) is
  unrelated but proves DB-related tests in this suite are not fully clean
  even outside this spec's scope — don't assume test-core's log is only
  ever the issues named in this spec after M1-M8 land; do a final, honest
  re-check.
- **M6 is the highest-judgment module.** Do not rush it; a mistranslated
  assertion (e.g. asserting a CSS rule against the wrong layout) would
  silently stop testing what it used to test — precisely the failure mode
  the user explicitly warned against.
- **M2's combined `uv sync` command was not empirically dry-run in this
  spec** (see M2's own caveat) — treat the exact flag grouping as a strong
  hypothesis, not a guarantee. If `uv` rejects the multi-`--package`/
  `--extra` combination, the fallback is to give `ai-parrot`'s `mcp`/
  `scheduler`-adjacent extras their own explicit pairing rather than
  guessing further; do not silently drop packages from the list to make the
  command merely "run" — that would quietly reintroduce a satellite gap
  this module exists to close.
- **A category of bug this spec's review pass uncovered (M8) generalizes
  beyond the four files named there**: `unittest.mock.patch("module.Name")`
  only works when `Name` is bound at `module`'s top level. Anywhere a
  handler does a FEAT-523-style lazy, function-local provider import (the
  `AC-3` pattern), any existing test patching the OLD module-level path is
  silently broken the same way, independent of whether the satellite is
  installed. M8's file list, like M2's, should be treated as a floor — a
  `grep -rn 'patch("parrot.handlers' tests/` sweep (or equivalent for other
  lazily-imported provider names) may find more.

### External Dependencies

| Package | Version | Reason |
|---|---|---|
| `pymupdf` | `>=1.27` | M3 — promoted from `bookstore` extra to core; already used at runtime by `DocumentAcquirer` |
| `pymupdf4llm` | `>=0.0.27` | M3 — same |

---

## 8. Open Questions

- [x] **Should `pymupdf`/`pymupdf4llm` become unconditional core
  dependencies of `ai-parrot`, or should wiki PDF ingestion degrade
  gracefully and the spec's claim be corrected instead?** — *Resolved in
  this spec (M3)*: promote to core dependencies, per FEAT-451's own
  documented assumption. This is the more conservative choice — it makes
  an already-accepted spec's own words true rather than reopening that
  spec's design.

- [x] **Should the new CI coverage for the 15 `ai-parrot-client-*`
  satellites be one combined job, or per-provider jobs?** — *Resolved in
  this spec (M2)*: one combined job (`test-optional-integrations`),
  matching the `test-wiki-extras` precedent's cost/signal tradeoff. It also
  absorbs `ai-parrot-server[scheduler]`, `ai-parrot-integrations`,
  `ai-parrot-embeddings`, `ai-parrot-pipelines` (added during this spec's
  review pass), and `ai-parrot[mcp]` (which also supplies `googleapiclient`
  — resolved during the review pass, was an open TODO in the first draft),
  since all share the exact same "satellite never synced by test-core"
  shape.

- [ ] **Should the M7 items (`DatabaseAgent`/`DatabaseAgentToolkit`,
  `create_netsuite_mcp_server`) be fixed within this spec's implementation
  pass, or deferred to a follow-up once diagnosed?** — *Owner*: implementing
  task / reviewer. *Plausible answers*: a) fix in place once root-caused
  (preferred, if the cause turns out simple) · b) defer with an SDD ledger
  entry if the cause is a CI-runner-specific artifact unrelated to any
  in-repo change.

---

## 9. Design Research Cross-Check

> Independent design opinion from the `codex` seat over the accepted
> exploration doc.

**Status: skipped** (`sdd/proposals/ci-test-failures-root-cause-
remediation.proposal.md`'s frontmatter carries `status: review`, not
`accepted` — the §3b precondition requires an accepted exploration
document; this proposal's three open questions were resolved directly in
this spec instead, per §8 above, since they were narrow implementation
choices rather than a design fork needing external review).

---

## Revision History

| Version | Date | Author | Change |
|---|---|---|---|
| 0.1 | 2026-09-15 | Claude Sonnet 5 | Initial draft, from FEAT-568 proposal + additional spec-time codebase research (reclassified 2 previously-"unexplained" errors into M1/M2, surfaced M2's true scope, identified M7's residual unknowns) |
| 0.2 | 2026-09-16 | Claude Opus 4.8 (review pass) | Adversarial re-review against the proposal + findings. Fixes: (1) added Module 8 — 4 files wrongly filed under M2 as "satellite gap" are actually stale `unittest.mock.patch` targets left by two unrelated refactors (FEAT-523 TASK-2846's lazy-import AC-3, and `saas-auth-hardening` TASK-2321's eval-context consolidation); (2) resolved the `mcp`/`googleapiclient` sourcing TODO (`ai-parrot[mcp]` extra) and wired it into M2's job; (3) added `ai-parrot-pipelines` and the a2ui-css/folium file to M2's list, both missing from the first draft; (4) corrected M1's Codebase Contract (`AgentCrew`, not a placeholder `CrewClass`) and M4's citation (sourced from commit `461b74c2e`, not `.claude/commands/sdd-start.md`, whose current wording has since drifted); (5) added an explicit uv-sync exact-sync-semantics caveat to M2's CI job snippet, since the multi-package/extra combination was not empirically verified; (6) softened the M7 Non-Goals' `IdentifiedProduct` classification pending re-check after M2 lands; (7) flagged a brand-new, unrelated `navigator-session`/Python-3.13 resolver regression that appeared on `dev` after the first draft, explicitly out of this spec's scope but noted so implementers aren't misled about residual CI redness. |
