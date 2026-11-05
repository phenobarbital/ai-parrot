# TASK-5194: Document installer defaults and worktree escape hatches

**Feature**: FEAT-804 — Installer portability gaps — one root, one portable rule
**Spec**: `sdd/specs/installer-portability-gaps.spec.md`
**Status**: done
**Priority**: high
**Estimated effort**: S (1–2h)
**Depends-on**: TASK-5190, TASK-5191
**Assigned-to**: unassigned

## Context

Implement the approved revision 0.4 of FEAT-804. This task owns the following bounded deliverable;
the dependency graph separates disjoint host implementations and serializes overlapping test writers.
Source references and literal edit anchors were verified at `62aaa17228` on 2026-11-05.

## Scope

- Update spec M6 global-runtime guidance and the three shipped bookstore skill strings.
- Document fresh launcher rule, sticky forms, explicit migrations, baked note, worktree refusal and --path.
- Keep markdown verification anchors and add toolkit portable flags; do not regenerate unrelated assets.

**NOT in scope**: worktree-root relocation (FEAT-802), wiki discovery redesign, non-Python worktree
provisioning, dependency additions, or edits outside the declared files. This is an implementation
task artifact; generation of this artifact makes no runtime changes.

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `docs/install/global-runtime.md` | MODIFY | Replace the stale baked-default and wikitoolkit-only stickiness paragraphs; retain all existing verify markers. |
| `packages/ai-parrot/src/parrot/knowledge/wiki/claude_code/bookstore_assets.py` | MODIFY | Keep the existing continuation and all other skill guidance intact; avoid recommending an implicitly refused worktree install. |
| `packages/ai-parrot/src/parrot/knowledge/wiki/codex/bookstore_assets.py` | MODIFY | Keep the existing continuation and all other skill guidance intact; avoid recommending an implicitly refused worktree install. |
| `packages/ai-parrot/src/parrot/knowledge/wiki/google/bookstore_assets.py` | MODIFY | Keep the existing continuation and all other skill guidance intact; avoid recommending an implicitly refused worktree install. |

## Codebase Contract (Anti-Hallucination)

### Verified Imports

Existing imports below resolve in the referenced source/test modules; `click`, `pytest` and
`pydantic` are already declared in the workspace pyproject files. Stdlib imports require no new
dependency. Imports explicitly marked with a task ID are future dependency contracts, not claims
that those symbols exist at planning HEAD. Preserve existing imports not shown in the blueprint.

```python
# Prose-only edits; no new imports.
```

### Existing Signatures to Use

```python
# packages/ai-parrot/src/parrot/cli/toolkits.py:180
def install(names: tuple[str, ...], hosts_: tuple[str, ...], yes: bool) -> None:

# packages/ai-parrot/src/parrot/cli/toolkits.py:245
def enable(names: tuple[str, ...], hosts_: tuple[str, ...], yes: bool) -> None:
```

### Does NOT Exist

- No new dependency, generated asset pipeline or worktree provisioning is part of this documentation task.

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {
      "path": "docs/install/global-runtime.md",
      "action": "MODIFY"
    },
    {
      "path": "packages/ai-parrot/src/parrot/knowledge/wiki/claude_code/bookstore_assets.py",
      "action": "MODIFY"
    },
    {
      "path": "packages/ai-parrot/src/parrot/knowledge/wiki/codex/bookstore_assets.py",
      "action": "MODIFY"
    },
    {
      "path": "packages/ai-parrot/src/parrot/knowledge/wiki/google/bookstore_assets.py",
      "action": "MODIFY"
    }
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot/src/parrot/cli/toolkits.py#install",
    "sym:packages/ai-parrot/src/parrot/cli/toolkits.py#enable"
  ]
}
```

## Implementation Notes

TASK-5190 supplies SDD --no-portable/root behavior and TASK-5191 supplies toolkit flags verified by the CLI-doc harness; host behavior is inherited through TASK-5189.

Use the approved stdlib-only launcher/decision structures from the spec. Keep public signatures
and existing ownership checks; use black (120 columns) and ruff for Python edits. New test functions
must have type hints and explanatory docstrings, matching production conventions. Keep HOME/PATH,
Google user-global config, credential probes and Git fixtures isolated under tmp_path. Never run
installers against the developer checkout/home as a test. Store test logs in artifacts/logs/.

## Implementation Blueprint

The blocks below are scoped edit plans, not wholesale replacements of existing files. CREATE
blocks are whole-file starting points; fill their bounded bodies before committing. Preserve
surrounding implementation and imports. No FILL IN or unfinished body may remain in implemented code.

### Steps (in order)

1. Revalidate listed anchors and prerequisite signatures — because dependencies or FEAT-802 may move adjacent code.
2. Apply the declared per-file edits in the order below — because caller and callee contracts must remain coherent.
3. Implement every bounded test case in Acceptance Criteria — because wiring-only spies do not verify emitted artifacts.
4. Run the Validation Commands and scoped lint — because the final state must preserve existing regression coverage.

### `docs/install/global-runtime.md` (MODIFY)

Anchor `The default stays baked absolute paths. `--portable` writes bare launcher commands (`wikitoolkit`, `parrot`,` — occurrences: 1; verified `docs/install/global-runtime.md:193`.

```text
<!-- verify: flag=toolkits install:--portable -->
<!-- verify: flag=toolkits enable:--portable -->

Fresh host configurations use portable commands when the managed launcher is on PATH.
Otherwise the installer writes baked paths and prints a note explaining how to migrate.
Existing managed configurations keep their form until --portable or --no-portable is supplied.

Run installers from the primary checkout. An implicit linked-worktree target is refused;
pass --path DIRECTORY to select a worktree deliberately. Toolkit install, uninstall,
enable and disable accept this override. Wiki configuration and initial builds remain
on the primary checkout while host assets are written into the selected checkout.
```

**Why**: Replace the stale baked-default and wikitoolkit-only stickiness paragraphs; retain all existing verify markers.

### `packages/ai-parrot/src/parrot/knowledge/wiki/claude_code/bookstore_assets.py` (MODIFY)

Anchor `If MCP is disconnected, run` — occurrences: 1; verified `packages/ai-parrot/src/parrot/knowledge/wiki/claude_code/bookstore_assets.py:50`.

```text
- If MCP is disconnected, run `parrot claude install --no-build` from the primary checkout
  (or pass `--path` to select the target deliberately),
```

**Why**: Keep the existing continuation and all other skill guidance intact; avoid recommending an implicitly refused worktree install.

### `packages/ai-parrot/src/parrot/knowledge/wiki/codex/bookstore_assets.py` (MODIFY)

Anchor `If MCP is disconnected, run` — occurrences: 1; verified `packages/ai-parrot/src/parrot/knowledge/wiki/codex/bookstore_assets.py:50`.

```text
- If MCP is disconnected, run `parrot codex install --no-build` from the primary checkout
  (or pass `--path` to select the target deliberately),
```

**Why**: Keep the existing continuation and all other skill guidance intact; avoid recommending an implicitly refused worktree install.

### `packages/ai-parrot/src/parrot/knowledge/wiki/google/bookstore_assets.py` (MODIFY)

Anchor `If MCP is disconnected, run` — occurrences: 1; verified `packages/ai-parrot/src/parrot/knowledge/wiki/google/bookstore_assets.py:60`.

```text
- If MCP is disconnected, run `parrot google install --no-build` from the primary checkout
  (or pass `--path` to select the target deliberately),
```

**Why**: Keep the existing continuation and all other skill guidance intact; avoid recommending an implicitly refused worktree install.

### FILL IN checklist

- [ ] `docs/install/global-runtime.md` — complete the bounded changes above and acceptance cases; retain unrelated behavior.
- [ ] `packages/ai-parrot/src/parrot/knowledge/wiki/claude_code/bookstore_assets.py` — complete the bounded changes above and acceptance cases; retain unrelated behavior.
- [ ] `packages/ai-parrot/src/parrot/knowledge/wiki/codex/bookstore_assets.py` — complete the bounded changes above and acceptance cases; retain unrelated behavior.
- [ ] `packages/ai-parrot/src/parrot/knowledge/wiki/google/bookstore_assets.py` — complete the bounded changes above and acceptance cases; retain unrelated behavior.

## Acceptance Criteria

- [ ] AC12: no stale default-stays-baked or wikitoolkit-only stickiness claim remains.
- [ ] All three bookstore assets mention primary checkout or explicit --path.
- [ ] Existing toolkit CLI tests pass, confirming documented portable and explicit-path options are available; manually verify the retained/additional markdown markers and three skill strings.

## Validation Commands

- `pytest packages/ai-parrot/tests/cli/test_toolkits_cli.py -q`

Run with the activated project environment and `PYTHONPATH=packages/ai-parrot/src`.
These commands are this task's relevant tests; the index carries the cached spec-wide contract.

## Test Specification

Use the cases and assertions in Acceptance Criteria and each test-file blueprint. Assert outputs,
exit statuses and before/after file snapshots as appropriate. Tests for malformed config and
worktree refusal must prove no unintended write; avoid network services and real user config.

## Agent Instructions

1. Use `$sdd-start TASK-5194` in the feature workflow; implementation belongs in its provisioned worktree.
2. Read the spec and verify dependencies are done in `sdd/tasks/index/installer-portability-gaps.json`.
3. Verify this contract before editing; refresh stale anchors explicitly rather than inventing interfaces.
4. Implement only declared files, complete every blueprint gap, run validation and scoped lint.
5. Commit only the implementation scope. Finalize through `scripts.sdd.finalize_task` with real
   TaskCompletionEvidence and exact implementation HEAD per docs/sdd/CODEX.md; never hand-edit
   the Completion Note or move this task to completed manually. Commit the resulting SDD state.

## Completion Note

Completed 2026-11-05 via sdd-worker orchestration.

- Seat: gpt-5.6-sol · Backend: codex · Attempts: 1 · Duration: 112s · Tokens: n/a.
- Wave merge-tier validation (5193+5194): 50 passed, 0 failed.
- Closure deviation: `coder_record_review` fails server-side (`CoderReview() argument after ** must be a mapping`), so no review EvidenceRef
  exists for `parrot sdd task finalize`; closed via `parrot sdd task close` with this hand-written note. Review/feedback NOT recorded; fix_commits: none.
