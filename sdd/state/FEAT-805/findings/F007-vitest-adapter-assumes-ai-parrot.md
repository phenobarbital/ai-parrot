---
id: F007
query_id: Q007
type: read
intent: "Does the built-in vitest runner work in a repository that is not ai-parrot?"
executed_at: 2026-11-04T22:36:00Z
duration_ms: 0
parent_id: F006
depth: 1
---

# F007 — The vitest adapter requires a TOML `cwd`, always runs `pnpm exec`, and defaults to `admin-ui`

## Summary

`vitest.py` indexes `settings["cwd"]` without a default, and the planner passes
`registry.settings_for(runner)` (the TOML settings) to every non-pytest adapter. With
the TOML missing (F006) the adapter has no `cwd`. The invocation is hard-wired to
`pnpm exec vitest run`, the distribution label defaults to ai-parrot's `"admin-ui"`, and
source→test mapping covers only `.svelte.ts`, `.svelte` and `.ts`.

## Citations

- path: `packages/ai-parrot/src/parrot/flows/dev_loop/test_scope/runners/vitest.py`
  lines: 13-86
  symbol: `ADAPTER`
  excerpt: |
    _SOURCE_SUFFIXES = (".svelte.ts", ".svelte", ".ts")
    binaries = ("pnpm", "vitest")
    cwd = (worktree / settings["cwd"]).resolve()
    return settings.get("distribution", "admin-ui")
    argv = ("pnpm", "exec", "vitest", "run", "--reporter=junit", f"--outputFile={report_path}", *paths)
    cwd=settings["cwd"],

- path: `packages/ai-parrot/src/parrot/flows/dev_loop/test_scope/runners/vitest.py`
  lines: 116-121
  symbol: null
  excerpt: |
    """Validate that the configured UI directory contains ``package.json``."""
    if not (worktree / cwd / "package.json").is_file():
        return [f"vitest: package.json not found in cwd {cwd!r}"]

- path: `packages/ai-parrot/src/parrot/flows/dev_loop/test_scope/planner.py`
  lines: 99-106
  symbol: null
  excerpt: |
    adapter = registry.adapter_for_kind(runner)
    settings = registry.settings_for(runner)
    if runner != "pytest":
        invocations.append(
            adapter.invocation(

## Notes

Lane report (not executed here): the missing key surfaces as `error: 'cwd'`, exit 2, via
`sdd/scripts/select_tests.py:397-404`; baseline classification is pytest-only
(`test_scope/baseline.py:214-217`). A root-level SvelteKit repository needs `cwd = "."`.
`navigator-frontend-next` uses pnpm, so the `pnpm exec` wiring works there; npm/yarn
repositories are not covered.
