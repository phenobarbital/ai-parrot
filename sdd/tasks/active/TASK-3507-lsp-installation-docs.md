# TASK-3507: Package explicit LSP configuration and operator documentation

**Feature**: FEAT-580 - SDD LSP Research Pilot
**Spec**: `sdd/specs/sdd-research-lsp.spec.md`
**Status**: pending
**Priority**: medium
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-3505, TASK-3506
**Assigned-to**: unassigned

## Context

Implement M4 of the approved specification: package explicit lsp configuration and operator documentation. The reported 13% cost, 12% token and 24% call reductions are hypotheses; only the specified evaluation can establish local benefit. Read the complete spec's contracts, acceptance criteria and relevant module before implementation.

## Scope

- Add discoverable lsp template with requires_dist ai-parrot-tools, requires_llm false, standalone class, nested kwargs.config.repo_root root placeholder and operator-unconfigured environment sentinel.
- Document explicit per-worktree install, interpreter/source roots, pinned executable provisioning, budgets, four tools and hash/column convention.
- Describe seat-specific visibility checks, baseline/delta workflow, immutable environment identity, fallbacks, unknown diagnostics and dynamic-Python limitations.
- Test template rendering, explicit config resolution and no startup/source scanning during import/list/install; never change the developer's actual host configuration.

**NOT in scope**: Provisioning/installing dependencies now, automatic host edits, managed skill rewrites and in-process dev-loop wiring.

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/mcp/_toolkit_templates/lsp.yaml` | CREATE | Explicit declarative configuration |
| `examples/lsp-mcp.yaml` | CREATE | Explicit declarative configuration |
| `docs/sdd/lsp-pilot.md` | CREATE | Operator-facing evidence or guidance |
| `packages/ai-parrot/tests/mcp/test_lsp_template.py` | CREATE | Acceptance and regression tests |

## Codebase Contract (Anti-Hallucination)

### Verified Imports

- `from parrot.mcp.toolkit_server import create_toolkit_mcp_server` — verified in `packages/ai-parrot/src/parrot/mcp/toolkit_server.py`; use only where relevant.
- `from parrot.mcp.toolkit_seed import available_templates, seed_toolkit_sections` — verified in `packages/ai-parrot/src/parrot/mcp/toolkit_seed.py`; use only where relevant.

### Existing Signatures to Use

- `create_toolkit_mcp_server` — `packages/ai-parrot/src/parrot/mcp/toolkit_server.py:29`: create_toolkit_mcp_server(name: str, root: Path = Path.cwd(), **overrides: Any) -> StdioMCPServer; imports under stdout redirection, constructs toolkit kwargs, filters and registers tools. Currently does not retain a resource owner.
- `available_templates` — `packages/ai-parrot/src/parrot/mcp/toolkit_seed.py:49`: available_templates() -> tuple[str, ...]; packaged YAML discovery.
- `seed_toolkit_sections` — `packages/ai-parrot/src/parrot/mcp/toolkit_seed.py:304`: seed_toolkit_sections(root: Path, names: Sequence[str]) -> SeedResult; does not overwrite existing sections, renders {{repo_root}} and reads requires_dist/requires_llm metadata.

### Dependency-produced contracts

- TASK-3505 supplies `packages/ai-parrot-tools/src/parrot_tools/lsp/toolkit.py`. Read its completed implementation and tests before consuming its API; these are planned deliverables, not verified existing symbols.
- TASK-3506 supplies `packages/ai-parrot/src/parrot/mcp/toolkit_server.py`, `packages/ai-parrot/src/parrot/mcp/local_cli.py`. Read its completed implementation and tests before consuming its API; these are planned deliverables, not verified existing symbols.

### Does NOT Exist

- The files marked CREATE are new task deliverables; do not assume their modules or exports already exist.
- Files marked MODIFY that are created by a prerequisite must be verified after that prerequisite lands.
- No existing LSP client, persistent diagnostic baseline API or five-arm pilot harness is established by the references above.
- Do not assume generic MCP transport implements LSP framing, or AST line spans provide identifier columns.
- Verify any additional symbol before use; do not invent provider adapters or methods.

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {
      "path": "packages/ai-parrot/src/parrot/mcp/_toolkit_templates/lsp.yaml",
      "action": "CREATE"
    },
    {
      "path": "examples/lsp-mcp.yaml",
      "action": "CREATE"
    },
    {
      "path": "docs/sdd/lsp-pilot.md",
      "action": "CREATE"
    },
    {
      "path": "packages/ai-parrot/tests/mcp/test_lsp_template.py",
      "action": "CREATE"
    }
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot/src/parrot/mcp/toolkit_server.py#create_toolkit_mcp_server",
    "sym:packages/ai-parrot/src/parrot/mcp/toolkit_seed.py#available_templates",
    "sym:packages/ai-parrot/src/parrot/mcp/toolkit_seed.py#seed_toolkit_sections"
  ]
}
```

## Implementation Notes

- Follow the uv workspace source layout, strict type hints and async-first resource ownership. Use stdlib and already-declared Pydantic; do not add dependencies without authorization.
- Keep changes within the target table. If implementation reveals an additional target or a conflict with project conventions, report it before expanding scope.
- May run alongside tasks outside its dependency chain with disjoint targets. Requires TASK-3505, TASK-3506 for the contracts and deliverables described below.
- Activate the main repository virtual environment when using a shell in a worktree; do not create a worktree venv. Store test output in `artifacts/logs/`.
- Format touched Python with black and run ruff for touched Python files. These supplement the file-level test contract below.

## Implementation Blueprint

The following are required interfaces or artifact contracts, not claims that the symbols already exist:

- `Template class: parrot_tools.lsp.toolkit.LSPToolkit; kwargs.config contains the LSPConfig payload.`
- `Use existing template loader/seed_toolkit_sections; no new installer command or registry.`

1. Follow the existing packaged YAML header and root-placeholder mechanism; provide a complete example with safe sentinel defaults.
2. Write deployment and per-seat/per-worktree validation instructions, including real-server test prerequisites and isolation limits.
3. Test discovery, root rendering, no automatic enablement and no child process on listing; check exactly four exposed methods after configured creation.

Use complete implementations, with no placeholder methods or unfinished public tools. Test fixtures must be deterministic and independent of live providers unless explicitly opted in.

## Acceptance Criteria

- [ ] Add discoverable lsp template with requires_dist ai-parrot-tools, requires_llm false, standalone class, nested kwargs.config.repo_root root placeholder and operator-unconfigured environment sentinel.
- [ ] Document explicit per-worktree install, interpreter/source roots, pinned executable provisioning, budgets, four tools and hash/column convention.
- [ ] Describe seat-specific visibility checks, baseline/delta workflow, immutable environment identity, fallbacks, unknown diagnostics and dynamic-Python limitations.
- [ ] Test template rendering, explicit config resolution and no startup/source scanning during import/list/install; never change the developer's actual host configuration.
- [ ] All target files are complete and file-level validation passes.
- [ ] No unrelated files or actual developer host configuration are changed.
- [ ] Failures, unavailable prerequisites and verification limitations are recorded honestly in the completion note.

## Validation Commands

- `pytest packages/ai-parrot/tests/mcp/test_lsp_template.py -q`

## Test Specification

- `test_template_is_explicit_and_root_scoped`: cover the corresponding scope invariant with both successful and adversarial inputs.
- `test_lsp_template_no_startup_on_install_or_list`: cover the corresponding scope invariant with both successful and adversarial inputs.
- `test_example_configuration_and_tool_names`: cover the corresponding scope invariant with both successful and adversarial inputs.

## Agent Instructions

1. Read the approved spec and this task; verify prerequisites in `sdd/tasks/index/sdd-research-lsp.json`.
2. Mark only this task in-progress with assignment/start timestamp before implementing.
3. Reverify existing and dependency-produced contracts; follow the file scope and update the task first if an approved scope correction is needed.
4. Implement and run the validation above; record actual results and any external blockers.
5. Run the required SDD review, then commit only task-scoped implementation plus this task and its per-spec index state. Do not use the historical monolithic index.
6. Mark done only when every acceptance criterion is satisfied. Leave blocked external execution unfinished.

## Completion Note

Not completed. The implementing agent must record changed behavior, validation results, commit, review outcome and remaining limitations here.
