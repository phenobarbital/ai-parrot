# FEAT-553 spec/codebase review

Reviewed the working copy of `sdd/specs/sdd-coder-shared-conventions.spec.md` on 2026-09-12. Proposed components being absent is expected; findings below concern incompatible contracts, missing integration coverage, and contradictory acceptance requirements. No implementation or spec edits were made.

1. **[P1] The proposed lint hook does not guard every merge.**

   Spec lines 477–482 place the gate exclusively in `_run_attempt`, while G5 promises enforcement before a branch is eligible for merge. In `packages/ai-parrot/src/parrot/flows/dev_loop/sdd_coder/engine.py:524`, `_run_attempt` explicitly handles only MCP seats. Native tasks and manual re-merges use `merge()` at line 407, which calls `_consolidate()` directly. That path currently checks cleanliness and file fidelity before merging, without entering `_run_attempt`. A native task introducing a forbidden import, or a branch amended after its attempt check, can therefore merge without the deterministic gate. Keep attempt validation for the retry ladder, and also validate at the shared consolidation boundary; specify native failure behavior and test both entry points.

2. **[P1] Mandatory shell activation is impossible through the in-process command tool.**

   Spec line 256 requires `source .venv/bin/activate` first, and M1 adopts the existing Python rules unchanged. Those rules prohibit Python/uv commands before shell activation. However, `dispatchers/llm.py:922` explicitly says there is no shell; `_tool_run_command` at line 1724 rejects executables outside the allowlist, which contains neither `source` nor a shell. `_run_argv` at line 1955 uses `asyncio.create_subprocess_exec`, and `worktree_manager.py:146` creates only a Git worktree, without provisioning `.venv`. Make the shared rule describe the host-provided environment for these seats, and specify how the dispatcher supplies the interpreter/PATH; reserve shell activation instructions for interactive shells.

3. **[P2] The Black ban contradicts active repository tooling.**

   Spec lines 248–257 replace Black/isort with Ruff and treat the old formatting guidance as stale. `Makefile:398` still defines `format` using `uv run black`; `Makefile:402` defines `lint` using pylint and `black --check`. The root `pyproject.toml:67` declares Black and line 237 configures it. Ruff checking in the coder prompt does not establish a formatter migration. Either retain the current Black formatting convention or explicitly scope the tooling/configuration migration; the present module list changes neither the Makefile nor the root dependency/configuration declarations.

4. **[P2] Gemini aliases generate incompatible managed markers.**

   Spec lines 359–372 require the same markers across installer paths, but lines 400–404 interpolate the raw agent name. `knowledge/wiki/coding_agents.py:46` maps both `gemini` and `google` to `GEMINI.md`; the dedicated Google installer uses `google` markers. Thus `install("gemini")` followed by the Google installer produces two conventions blocks, and Google uninstall leaves the Gemini block behind. Applying the specified naming rule through the existing `_upsert` reproduced two blocks. Canonicalize `gemini` to `google` for conventions markers and test cross-installer updates/removal, not just repeated invocation of each installer.

5. **[P2] The Claude conventions block has no specified uninstall path.**

   Spec lines 362–370 add a Claude block and promise removal on uninstall; AC-6 repeats that lifecycle guarantee. The lightweight installer exposes only `install` and `hook` (`knowledge/wiki/cli.py:4651`), and `coding_agents.py` has no uninstall function. The existing `knowledge/wiki/claude_code/installer.py:643` uninstaller removes its wiki block but is absent from M3's files to modify. Add conventions removal to that existing uninstaller and cover preservation of surrounding prose, or explicitly narrow the lifecycle guarantee.

6. **[P2] M1 cannot pass its tests before M2 exists.**

   M1 declares no dependencies, but its test skeleton at spec line 267 imports `CODER_RULE_NAMES` from `parrot.flows.conventions`, which M2 creates. M2 in turn depends on M1, and the worktree strategy schedules M1 first. The module is absent in the current tree, so collecting M1's specified tests before M2 raises `ModuleNotFoundError`. Put the constants/module foundation in M1, move the dependent tests into M2, or combine those tasks; define an acyclic sequence with passing intermediate checks.

7. **[P2] The stale-prose assertion rejects the required generated block.**

   Spec line 523 requires the entire regenerated `AGENTS.md` to contain neither `black` nor `isort`. M1 line 252 requires both names in the forbidden/substitute table, and M3 injects that table into `AGENTS.md`. The test therefore fails for the required output. Restrict the assertion to prose outside managed conventions markers, or assert removal of the exact obsolete instructions.

Validated without changing the repository's Ruff configuration:

- Applied the exact proposed banned-api and grandfather rules through Ruff CLI configuration overrides: `packages/` and `scripts/` produced zero TID251 findings, exit 0.
- Existing Python/Cython/Rust rule twins are byte-identical and total 6,490 bytes, leaving 5,510 bytes for the fourth file under AC-3.
- Both existing library profile defaults are 24; the proposed 40-turn changes target the correct fields. The builder's existing 60-turn override is accurately identified by the spec.
- The named prompt builders and inheritance relationships match the proposed integration points.

Diagnostic lint output: `artifacts/logs/review_sdd_coder_shared_conventions.log`. This was a design review with targeted checks, not execution of the full application test suite or verification of the reported historical 35-turn failure.
