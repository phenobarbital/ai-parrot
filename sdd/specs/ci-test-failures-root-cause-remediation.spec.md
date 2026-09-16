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
drafting that reclassified two of the proposal's flagged
"unexplained" errors and surfaced the true scope of the largest bucket.

> **Historical revision 0.2 note (superseded where stated below).** A second, adversarial read of this
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

> **Revision 0.3 (accepted decision review).** Supersedes the 0.2 decisions
> on M2/M3/M8: establish the actual CI environment before classifying
> failures, require complete test-to-job coverage and structured skip
> checks, retain optional document dependencies, and patch the async
> eval-context alias where it is used. The resolver fix is a prerequisite
> for final validation, not an exception permitting completion without it.

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
  research, several additional `test-core` failures were found that
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
  The `IdentifiedProduct` ValidationError in
  `tests/pipelines/test_endcap_no_shelves.py` remains **unclassified**.
  A validation failure inside satellite code is not evidence of an absent
  satellite. The current unscoped `uv run` installs workspace-root
  dependencies, including pipelines (M2). Reproduce with an inventory of
  installed distributions, then fix the confirmed cause or record an
  evidenced deferral. Do not add a skip to conceal a model/fixture failure.
- Redesigning `TargetedWriterToolkit`/FEAT-543's delegation architecture, or
  FEAT-549's Orchestrator Loop. M4 below is a restoration of previously
  shipped, tested content — not a redesign of either.
- Adding CI coverage for satellite packages this investigation did not find
  failing tests for (`ai-parrot-advisors`,
  `ai-parrot-openlit-bridge`, `parrot-formdesigner`, etc.). Real gap, but a
  separate initiative.
- Redesigning `DocumentAcquirer` or making document dependencies mandatory
  for all core consumers. M3 retains the optional loader boundary; the
  older FEAT-451 claim that PyMuPDF is already core is not a packaging contract.

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

**Validation prerequisite:** record the separately tracked resolver fix and
its passing sync evidence before final acceptance. Work on M1–M8 may proceed
in parallel, but a resolver-blocked job is unvalidated, not passed or waived.
Run each intended job installation in a disposable environment once the fix
lands; preserve logs and the tested commit. Do not weaken the security-related
dependency floor merely to make this specification executable.

---

## 2. Architectural Design

### Overview

Eight modules cover confirmed fixes and explicitly unresolved diagnosis.
M2 owns `.github/workflows/ci.yml`, the coverage inventory, and its result
gate; M3 and M8 supply their required test selections and dependency profiles
to M2. M2 must validate after M1 removes the import cascade. M7 remains
diagnosis-first. These modules are not independent merely because most
source files differ; their CI acceptance depends on the same environments.
**M8 was added during this spec's review pass** — it was originally, and
incorrectly, folded into M2's file list as a satellite-gap case; the review
found it is a different, unrelated bug (see M8).

### Component Diagram

```
M1 (crew.py tqdm)         ──┐
M2 (environment/coverage)  ─┼─→  scoped failures removed, coverage verified
M3 (optional documents)   ─┘         (M2 owns shared workflow changes)

M4 (sdd-worker.md restore) ──→  test-tool-optimizations goes green

M5 (wiki SCHEMA_VERSION)   ──┐
M6 (BASE_CSS rewrite)       ─┤
M7 (DatabaseAgent/netsuite) ─┼─→  further test-core error-volume reduction
M8 (stale mock-patch targets)┘        (M7 requires further diagnosis)
```

### Integration Points

| Existing Component | Integration Type | Notes |
|---|---|---|
| `parrot.bots.flows.crew.crew.AgentCrew` | modifies import | M1 — guard, no behavior change when `tqdm` is present |
| `.github/workflows/ci.yml` jobs | extends | M2 — new job + `pytest.importorskip`/marker guards in existing test files |
| Optional document tests and loader extras | configures | M3 — preserves core absence coverage; M2 installs `ai-parrot-loaders[documents]` for ingestion coverage |
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
| M2: environment/coverage | no | Environment and coverage contract fixed below; exact profiles and failure classifications require isolated execution | Collection and skip reasons must be diagnosed before guards are assigned |
| M3: optional documents | no | Retain extras; separate installed-document tests from core/absence tests | Mixed test modules require per-test dependency classification |
| M4: sdd-worker.md restore | yes | Exact section text sourced from this file's original addition in commit `461b74c2e` (§3/M4) | — |
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

### Module 2: Establish CI environments, guard confirmed optional tests, and close coverage gaps

- **Paths**: `.github/workflows/ci.yml`; the test files classified below;
  `scripts/ci/` for a new deterministic coverage inventory/result checker
  and focused checker tests (exact filenames recorded in the implementing task).
- **Responsibility**: preserve explicit installation profiles through test
  execution, diagnose failures within those profiles, and ensure every
  optional test guarded in core runs in a job with its dependencies installed.
- **Dependencies**: M1 before final failure classification; M3/M8 test
  selections before completing the coverage inventory; resolver prerequisite
  in §1 before installation evidence and final validation.

#### 2a. Environment contract — required before classifying failures

The existing `test-core` job is **not a verified core-only environment**:
`uv sync --package ai-parrot` is followed by `uv run pytest` at the workspace
root. Root `pyproject.toml` directly depends on loaders, embeddings,
visualizations, pipelines, integrations, server, tools, advisors, and navrules.
Unscoped `uv run` automatically syncs that root project and adds its required
packages. It uses inexact syncing by default, so this is not a claim that it
removes the previously installed extras. See the
[uv synchronization contract](https://docs.astral.sh/uv/concepts/projects/sync/).
The historical logs therefore do not establish that these satellites were absent.

M2 must:

1. Define explicit package/extra profiles for core, wiki extras, wiki fallback,
   and optional integrations. Run each profile in a clean disposable environment,
   never by syncing the shared development `.venv`.
2. Perform one combined sync per profile, then use `uv run --no-sync` for
   all probes, collection, and execution steps in that environment. Apply
   this boundary to existing CI jobs that sync a scoped package before
   invoking unscoped `uv run`; preserve their intended package/extra selections.
3. Save the Python/uv versions, tested commit, installed distribution inventory,
   and relevant module origins under `artifacts/logs/`. Assert the intended
   absent/present dependencies immediately before pytest. Account for
   transitive dependencies; a profile is not "bare" solely because it has no extras.
4. Reproduce and classify each failure as missing distribution/extra, broken
   import within an installed package, stale contract, or behavioral failure.
   `IdentifiedProduct` validation errors must be diagnosed, not presumed to be
   installation failures. M7-style evidenced deferral is permitted for a
   confirmed independent defect; the affected required CI job still cannot
   be marked passed while it fails.
5. Add absence guards only for a confirmed missing optional dependency.
   Do not catch arbitrary import failures from the code under test. Probe
   distribution/dependency availability narrowly, then import the target
   normally so broken installed code remains a failure. Mixed modules must
   retain dependency-independent tests in core; use per-test/fixture guards
   rather than skipping the whole module.

The following is a **candidate inventory**, not proof of missing packages or
an exhaustive list. The implementing task records exact node IDs, reasons,
installation profiles, and installed-dependency job ownership before completion.

#### 2b. Required test-to-job mapping

| Test surface | Required dependency/profile | Job that must execute installed-dependency tests |
|---|---|---|
| `tests/clients/` offline tests | All 15 `ai-parrot-client-*` distributions; audited provider extras | `test-optional-integrations` |
| `packages/ai-parrot-client-*/tests/` for all 15 providers | Same; execute each package suite separately if collection names/configuration collide | `test-optional-integrations`, one result artifact per provider |
| `tests/handlers/test_document_understanding_integration.py`, `tests/integration/test_claude_agent_tool_bridge.py` | Google/Anthropic clients and required server/bridge dependencies | `test-optional-integrations` |
| `tests/handlers/test_mediagen_handler.py`, `test_understanding_handler.py`, `test_understanding_integration.py` (M8) | Server + Google client; corrected provider patch target | `test-optional-integrations` |
| `tests/auth/test_policy_rules_integration.py` (M8) | Server/auth; no Google dependency for policy-only tests | `test-optional-integrations`; core-compatible cases also stay in core |
| `tests/mcp/test_oauth2_e2e.py`, `test_oauth2_integration.py`, `test_oauth2_storage.py`, `tests/auth/test_mcp_oauth2_provider.py` | `ai-parrot[mcp]` | `test-optional-integrations` (run the offline `tests/mcp/` selection) |
| `tests/integration/oauth2/` | `ai-parrot-integrations` and audited OAuth dependencies | `test-optional-integrations` |
| `tests/unit/test_faiss_s3.py` | `ai-parrot-embeddings` and required backend dependencies | `test-optional-integrations` |
| `tests/test_fireflies_wiki_agent.py` | `ai-parrot-server[scheduler]` and dependencies of the dynamically loaded agent | `test-optional-integrations` |
| `tests/pipelines/`, including `test_endcap_no_shelves.py` | `ai-parrot-pipelines`; diagnose validation errors separately | `test-optional-integrations` |
| `tests/scripts/test_generate_a2ui_css.py::test_generate_a2ui_css_vendor_check` | `ai-parrot-visualizations[map]`; provision Node if the test invokes asset generation | `lint-and-registry` must execute this exact test as well as its existing asset checks |
| `tests/knowledge/wiki/languages/test_outline_parity.py`, `tests/knowledge/wiki/structural/test_tools.py`, `tests/knowledge/wiki/test_cli_symbols.py`, `tests/knowledge/wiki/test_structural_e2e.py` | `wiki-structural`/`wiki-languages` as required per case | `test-wiki-extras`; retain applicable fallback cases in core |
| Document-dependent cases in `tests/knowledge/wiki/test_documents.py`, `test_cli.py`, `test_integration.py` (M3) | `ai-parrot-loaders[documents]` plus wiki extras | `test-wiki-extras`; core runs plaintext and missing-loader cases |
| `tests/integration/test_crew_infographic_e2e.py`, `test_saved_executions_flow.py`, `tests/test_crew_hooks.py`, and `tests/bots/flows/core/storage/` lifecycle/persistence/wiki/integration suites previously attributed to tqdm | Re-run after M1; add optional guards only with new dependency evidence | Core for dependency-independent cases; every newly guarded case assigned an installed-dependency job before merge |

The inventory must be checked against collection/results, not merely stored
as documentation. Every new guard must have an installed-dependency owner;
missing files, empty required selections, missing provider reports, or an
expected case disappearing through deselection must fail validation. Each
provider must execute a nonzero required selection; installing its package
alone is not coverage. Record exact deselections and rationale as well.

#### 2c. Installation and execution design

Keep one combined optional-integrations job initially, using Python 3.12.
It installs core with `mcp`, all 15 client packages (amazon, anthropic,
gemma4, google, grok, groq, hf, local, meta, moonshot, nvidia, openai,
openrouter, vllm, zai), server with `scheduler`, integrations, embeddings,
and pipelines. Add only the extras proven necessary by the offline inventory.
`ai-parrot[mcp]` declares both `mcp` and `google-api-python-client`; installing
an OpenAI client alone does not request its `bridge` extra.

One combined sync avoids successive exact syncs undoing earlier selections.
The multi-package/extra command must be executed in a disposable environment
and its resulting inventory verified; do not assume extras are associated
with a package by argument adjacency. Do not drop a required package to make
resolution pass. Pin/use the validated uv version in the workflow.

After sync and NavConfig scaffolding, run the root selections from §2b and
each provider-local suite through `uv run --no-sync pytest`, with a distinct
`--junitxml=artifacts/logs/<selection>.xml` report. Explicitly deselect live
provider/network/CLI-dependent cases using audited markers or exact node IDs;
register any missing marker used by the inventory because strict markers are
enabled. `tests/clients/test_anthropic_sdk_097.py::test_anthropic_live_smoke`
is an existing credential-gated example, and `test_claude_agent.py` also has
an external-CLI smoke test. No credentials or live services are required for
this offline gate. Do not label newly failing offline tests as live to exclude them.

Preserve pytest's exit status, including collection errors and zero-test exits.
If output is piped through `tee`, require `shell: bash` and `set -o pipefail`.
Write logs and XML under `artifacts/logs/` and upload them with `if: always()`.
The existing wiki/map jobs must produce equivalent reports for their assigned
required selections; successful checks in another job are not substitutes for
executing the mapped test itself.

#### 2d. Structured result gate

Replace the proposed `grep "SKIPPED"` check with a stdlib XML result checker
owned by M2. A review reproduction using the repository pytest configuration
reported `1 passed, 1 skipped` for a module-level `importorskip`, with no
uppercase `SKIPPED`; textual progress output is not a reliable interface.

The checker must fail on missing/malformed reports, failures/errors, zero
executed required tests, missing inventory coverage, and unexpected skips,
including collection/module-level skips. Scope zero-skip enforcement to
mandatory offline selections. Pre-existing non-applicable parameter cases
may have narrowly recorded exceptions by node ID and reason, reviewed before
implementation; no blanket module/provider allowance is acceptable. Live
cases are explicitly deselected and accounted for separately, not treated as
missing-dependency skips. The inventory/result mapping must handle pytest's
JUnit representation of collection skips as well as ordinary test cases.

Test the checker with deterministic fixtures for ordinary pass, module-level
skip, test-level skip, expected exception, unexpected exception, collection
error, missing report, malformed XML, and empty/missing required coverage.
Also demonstrate the gate fails when a required optional dependency is absent
and passes when that same selection executes with the dependency installed.
Apply this structured gate to the mapped wiki/map selections as well.

- **Acceptance criteria**:
  - The intended dependency profile survives through execution; inventories
    prove presence/absence and logs reproduce each classification.
  - Genuine absence causes a reported skip only for dependent tests; core
    tests and installed-package import/behavior failures remain visible.
  - All §2b selections have executed evidence, including all 15 package-local
    client suites and M8 files; no guard loses its installed-dependency coverage.
  - Mandatory offline selections pass with no unexpected skips; audited live
    exclusions and narrow applicability exceptions are reported separately.
  - The new job and structured gate pass after the resolver prerequisite;
    a blocked sync or unrelated failure is not accepted as a passing job.

### Module 3: Preserve optional document dependencies and test both installation modes

- **Paths**: document-related tests/fixtures in
  `tests/knowledge/wiki/test_documents.py`, `test_cli.py`, and
  `test_integration.py`; M2 owns their workflow/profile changes.
- **Responsibility**: keep `pymupdf` and `pymupdf4llm` optional. Do not move
  them into core dependencies to reconcile an older spec sentence.
  `DocumentAcquirer._acquire_binary` imports `parrot_loaders.factory`
  before extraction and raises `DocumentAcquisitionError` when loaders are
  absent. Installing only PyMuPDF cannot satisfy that runtime path.
- **Depends on**: M2's explicit environment profiles and result gate.
- **Decision**: install the existing `ai-parrot-loaders[documents]` extra
  for document ingestion coverage. Its declaration includes PyMuPDF,
  pymupdf4llm, python-docx, and the ebook extra. Verify the actual PDF loader
  resolves and extracts the fixture; successful package imports alone are
  insufficient. Any further packaging defect found is diagnosed explicitly,
  not hidden by a fallback loader or weakened assertions.

`test-wiki-extras` must install that loader profile together with
`ai-parrot[wiki-languages,wiki-structural]` in its single combined sync,
then execute using `uv run --no-sync`. M2 must verify multi-package extras
and inventory in isolation. This revises the wiki job's installation profile;
its Luau/structural required coverage must remain intact.

In true core-only mode, keep plaintext ingestion, metadata/URL logic that
needs no loader, and explicit missing-loader behavior tests active. Guard
only fixtures/cases requiring real document extraction or PDF creation;
never module-skip the mixed wiki test files. Preserve tests that deliberately
simulate missing loaders even in the installed-document profile.

- **Acceptance criteria**:
  - No new unconditional PDF dependencies are added to core.
  - Core-only collection succeeds; independent tests and missing-loader
    error assertions execute, while only document-dependent cases skip.
  - With `ai-parrot-loaders[documents]` installed, the mapped document tests
    pass and the structured gate confirms no unexpected document skips.
  - PDF extraction, nonempty text, page count, and error-path assertions keep
    their original behavioral intent. Missing loaders produce the existing
    actionable `DocumentAcquisitionError`; they are not treated as success.
  - Both environments are verified independently with M2 inventories and
    results after the resolver prerequisite is satisfied.

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
- **Depends on**: M2's environment inventory for reliable reproduction;
  source-level diagnosis may proceed before final CI validation.
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
- **Depends on**: M2 for installed server/provider coverage and dependency
  guards; behavioral corrections remain owned by M8.
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
  # Two handler occurrences currently patch the removed bots._EvalContext.
  # Patch the async callable at its bound lookup location instead:
  #     patch("parrot.handlers.bots._core_build_eval_context",
  #           new=AsyncMock(return_value=eval_context))
  # Use a context fixture compatible with the existing evaluator assertions.
  # Do NOT patch parrot.auth.eval_context.build_eval_context after bots.py
  # has imported it: that does not replace bots.py's already-bound alias.
  # The other two occurrences patch _bots_abstract._EvalContext, which still
  # exists and is called synchronously. Preserve those MagicMock patches.
  ```
- **Acceptance criteria for this module**:
  - All four listed files execute in M2's installed-dependency job and pass
    its inventory/result gate; adding dependencies without running them is
    insufficient.
  - Google-dependent handler cases skip only when their required provider
    or server is genuinely absent. Policy-only tests must not be gated on
    Google; guard server-dependent cases only if the server is absent and
    keep core-compatible `AbstractBot` cases active.
  - The two handler tests use `AsyncMock` at
    `parrot.handlers.bots._core_build_eval_context`, assert it was awaited
    with the request, and retain the filtering/authorization assertions.
  - The two `_bots_abstract._EvalContext` patches remain synchronous and
    unchanged unless independent evidence establishes a separate defect.
  - No production import is restored to accommodate stale tests, and no
    authorization/handler behavior assertion is weakened.

---

## 4. Test Specification

### Unit Tests

| Test | Module | Description |
|---|---|---|
| `monkeypatch`-simulated tqdm-absence unit test + reload (see M1's acceptance criteria) | M1 | Import succeeds without `tqdm`; falls back cleanly |
| M2 §2b inventory under verified core-only profile | M2 | Only absent-dependency cases skip; independent cases execute; broken installed imports fail |
| M2 §2b installed-dependency selections, including each provider-local suite | M2 | Required offline cases pass, nonzero coverage per provider, no unexpected skips; live exclusions reported |
| Structured result-checker fixtures (§3/M2/2d) | M2 | Detect missing coverage, malformed/missing reports, failures, and both collection and test skips |
| `tests/knowledge/wiki/test_documents.py`, `test_cli.py`, `test_integration.py` in two profiles | M3 | Core runs independent/missing-loader cases; wiki extras with `ai-parrot-loaders[documents]` runs document cases |
| `pytest packages/ai-parrot-tools/tests/tool_optimizations/test_sdd_contracts.py -q` | M4 | 422 passed / 0 failed / 1 skipped |
| `pytest tests/knowledge/wiki/test_store_migration_v2.py -q` | M5 | Passes; includes new `_migrate_fts` coverage |
| `pytest tests/test_infographic_html.py -q` | M6 | Passes; no `BASE_CSS` reference remains |
| `pytest tests/unit/test_database_agent.py tests/manager/test_botmanager_wiring.py -q` | M7 | Passes, or deferred with evidence |
| M8's four handler/auth files | M8 | Execute and pass in optional integrations; in core guard only truly dependent cases, never policy tests on Google availability |

### Integration Tests

| Test | Description |
|---|---|
| Full `test-core` CI job (both Python 3.11/3.12 legs) | After successful profile installation, scoped failures removed; residual Non-Goals reported by exact node ID/cause, not described as a green job |
| Full `test-wiki-extras` CI job | Goes green |
| Full `test-tool-optimizations` CI job (both Python legs) | Goes green |
| New `test-optional-integrations` CI job | Green, including structured coverage/skip gate and all provider-local suite reports |

### Test Data / Fixtures

M2 needs deterministic result-checker fixtures described in §3/2d. M3
scopes existing document fixtures to the cases needing optional dependencies.
M5 needs a v2-shaped database fixture, or an upgrade of the existing v1
fixture through both migration steps. M8 reuses compatible request/context
fixtures with async mocks for the handler seam.

---

## 5. Acceptance Criteria

> This feature is complete when ALL of the following are true:

- [ ] The separate resolver fix has landed and every intended CI profile
      installs successfully in isolation on the tested commit. Preserve the
      fix reference and logs; resolver-blocked execution is not a waiver.
- [ ] M2's scoped profiles are preserved with `uv run --no-sync`, with
      installed-distribution and module-origin evidence before testing.
- [ ] `test-core` (Python 3.11 and 3.12) no longer has the scoped M1–M8
      failures. Only proven optional-dependency absences skip. Residual
      failures are individually evidenced against §1 Non-Goals/M7; a red
      full job is still reported as red, not "passing modulo" those items.
- [ ] `test-wiki-extras` passes with the document loader extras and its
      mapped structural/document selections pass the structured result gate.
- [ ] `test-tool-optimizations` passes in full on both Python legs.
- [ ] `test-optional-integrations` passes, including all §3/2b assigned
      root tests, M8 files, and all 15 provider-local suites with nonzero
      required execution and no unexpected skips.
- [ ] The coverage inventory accounts for every added guard, expected case,
      live deselection, and narrow applicability exception; missing report,
      module-level skip, or missing required coverage fails the gate.
- [ ] The map/vendor test itself executes in `lint-and-registry` with its
      dependencies and a passing structured result gate.
- [ ] No behavioral assertion is weakened to turn CI green. M5/M6 translations
      and M8 mock corrections retain their documented intent.
- [ ] PDF dependencies remain optional; core absence behavior and installed
      document extraction both have executed coverage (M3).
- [ ] Combined profile syncs are actually exercised in disposable environments,
      including applicable Python legs; no new resolver conflict is introduced.
- [ ] M7 and the unclassified pipeline validation error end in a confirmed
      fix or evidenced, explicitly tracked deferral. A deferral does not
      waive the separate requirement for a required installed-dependency job
      to pass; blocking independent fixes must land before final acceptance.

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
| M2's new CI job | `ai-parrot-client-*` (15 packages), `ai-parrot-server[scheduler]`, `ai-parrot-integrations`, `ai-parrot-embeddings`, `ai-parrot-pipelines`, `ai-parrot[mcp]` | `uv sync --package ...` (one validated combined profile), followed by `uv run --no-sync` | `sdd/tasks/index/pep-420-llm-clients.json` (FEAT-523, all 15 packages `"done"`); `packages/ai-parrot/pyproject.toml:459` (`mcp` extra) |
| M3's optional document profile | `DocumentAcquirer` extraction via `parrot_loaders.factory` | M2 installs `ai-parrot-loaders[documents]`; core keeps absence coverage | `documents.py::_acquire_binary`; `packages/ai-parrot-loaders/pyproject.toml` documents extra |
| M4's restored section | commit `461b74c2e`'s original addition to THIS file (not a different doc) | verbatim content reuse | `git show 461b74c2e -- .claude/agents/sdd-worker.md` |
| M8's corrected patch targets | `parrot.clients.google.GoogleGenAIClient` (source of the lazy import); `parrot.handlers.bots._core_build_eval_context` | Source patch for lazy provider import; `AsyncMock` at the bound handler alias | `mediagen.py:90`, `understanding.py:213`, `bots.py:16`, `eval_context.py:23` |

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
  Probe only the missing dependency, not arbitrary import failures inside
  installed code. An installed-dependency job must prove required execution
  with M2's structured gate; copying Luau's text grep is insufficient.
- **Optional features stay optional.** Guard M1's cosmetic progress bar;
  keep M3's document loaders and PDF libraries in extras. Historical spec
  wording alone does not justify an unconditional dependency.
- **Restoring dropped content must be a verbatim restoration**, not a
  paraphrase — M4 exists because a paraphrase-free git-diff comparison is
  what proved this was a regression rather than an intentional removal.

### Known Risks / Gotchas

- **M2's file list is a floor, not a ceiling.** The CI log analysis behind
  this spec covered one specific run; a full, current `test-core` run may
  surface additional files sharing the same shape. The implementing task
  MUST re-run collection and diff against this list, not treat it as
  exhaustive.
- **True core isolation may expose additional failures.** Historical logs
  came from unscoped `uv run`, not a proven core-only profile. Reclassify
  with environment evidence; do not turn every newly exposed failure into
  a guard. M3's PDF tests require the loader distribution, not just PyMuPDF.
- **M6 is the highest-judgment module.** Do not rush it; a mistranslated
  assertion (e.g. asserting a CSS rule against the wrong layout) would
  silently stop testing what it used to test — precisely the failure mode
  the user explicitly warned against.
- **Combined profile installations remain an execution prerequisite.**
  Validate multi-package/extra behavior with the pinned uv version and save
  inventories. Never rely on package/extra argument adjacency, successive
  exact syncs, or a later root sync to fill missing profile dependencies.
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

No new runtime dependency is introduced by this revision. Existing
`ai-parrot-loaders[documents]` supplies `pymupdf>=1.27`,
`pymupdf4llm>=0.0.27`, and the document/ebook dependencies to the installed
wiki profile. M2's result checker uses the Python standard library.

---

## 8. Open Questions

- [x] **Promote PDF libraries to core?** — No. The accepted revision retains
  optional loader/document dependencies and tests both absence and installed
  extraction. FEAT-451's historical wording is superseded for this decision.
- [x] **One combined provider job or per-provider jobs?** — Start with one
  combined installed profile, but execute and report each provider-local
  suite independently as well as the mapped root tests. Split jobs later
  only if measured runtime or genuine dependency incompatibility requires it.
- [x] **Can a green skip gate prove coverage?** — Only with structured reports
  checked against required selections and audited exclusions. Text grep and
  installation alone are insufficient.

- [ ] **Should the M7 items (`DatabaseAgent`/`DatabaseAgentToolkit`,
  `create_netsuite_mcp_server`) be fixed within this spec's implementation
  pass, or deferred to a follow-up once diagnosed?** — *Owner*: implementing
  task / reviewer. *Plausible answers*: a) fix in place once root-caused
  (preferred, if the cause turns out simple) · b) defer with an SDD ledger
  entry if the cause is a CI-runner-specific artifact unrelated to any
  in-repo change.

---

## 9. Design Research Cross-Check

> User-requested decision review of this specification against repository
> source and CI configuration; this does not change the proposal's status.

**Status: reviewed; changes accepted by the user (2026-09-16).**
The decision review found five issues: unverified core environment isolation,
an ineffective blanket skip gate, incomplete installed-dependency coverage,
unjustified/incomplete PDF dependency promotion, and an ineffective alternate
mock target. Revision 0.3 incorporates those findings plus the explicit
resolver validation prerequisite. Source inspection and a focused pytest
skip reproduction support the findings; a full CI rerun and profile sync
validation remain implementation acceptance requirements.

---

## Revision History

| Version | Date | Author | Change |
|---|---|---|---|
| 0.1 | 2026-09-15 | Claude Sonnet 5 | Initial draft, from FEAT-568 proposal + additional spec-time codebase research (reclassified 2 previously-"unexplained" errors into M1/M2, surfaced M2's true scope, identified M7's residual unknowns) |
| 0.2 | 2026-09-16 | Claude Opus 4.8 (review pass) | Adversarial re-review against the proposal + findings. Fixes: (1) added Module 8 — 4 files wrongly filed under M2 as "satellite gap" are actually stale `unittest.mock.patch` targets left by two unrelated refactors (FEAT-523 TASK-2846's lazy-import AC-3, and `saas-auth-hardening` TASK-2321's eval-context consolidation); (2) resolved the `mcp`/`googleapiclient` sourcing TODO (`ai-parrot[mcp]` extra) and wired it into M2's job; (3) added `ai-parrot-pipelines` and the a2ui-css/folium file to M2's list, both missing from the first draft; (4) corrected M1's Codebase Contract (`AgentCrew`, not a placeholder `CrewClass`) and M4's citation (sourced from commit `461b74c2e`, not `.claude/commands/sdd-start.md`, whose current wording has since drifted); (5) added an explicit uv-sync exact-sync-semantics caveat to M2's CI job snippet, since the multi-package/extra combination was not empirically verified; (6) softened the M7 Non-Goals' `IdentifiedProduct` classification pending re-check after M2 lands; (7) flagged a brand-new, unrelated `navigator-session`/Python-3.13 resolver regression that appeared on `dev` after the first draft, explicitly out of this spec's scope but noted so implementers aren't misled about residual CI redness. |
| 0.3 | 2026-09-16 | Codex, user-approved decision review | Preserve explicit CI environments; require inventory-backed classification and complete test-to-job mapping, including all provider-local suites; replace text skip grep with structured coverage checks and audited offline selections; retain optional document dependencies and both installation modes; require AsyncMock at the bound handler alias while preserving AbstractBot patches; make resolver remediation a validation prerequisite. |
