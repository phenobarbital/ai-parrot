# Design Research Triage — expose-local-mcp-tools (FEAT-570)

Model: gpt-5.6-luna · codex-cli 0.154.0 · reasoning_effort=high
10 suggestions, schema-valid. All 31 `affected_paths` passed containment + existence checks.

| # | Suggestion (kind) | Disposition | Reason | Landed in |
|---|---|---|---|---|
| S1 | Add toolkit-only host reconciliation (architecture) | CONFIRM | Verified: all three `_install_mcp*` also (re)write the wikitoolkit entry — `claude_code/installer.py:462`, `google/installer.py:148-160`, `codex/installer.py:110`. Calling them from `parrot toolkits` would mutate an artifact this command does not own. | §2 Overview, §3 M2 |
| S2 | Model host asymmetry explicitly (architecture) | CONFIRM | Verified: Codex has no `_is_managed_toolkit_entry` — it detects collisions via `_existing_table_names` + a marker block; Claude and Google each have their own. Importing private helpers as if symmetric would not compile against Codex. | §3 M1 (HostAdapter) |
| S3 | Handle Claude approvals selectively (risk) | CONFIRM | Verified: `_managed_server_names` seeds `names = ["wikitoolkit"]` (installer.py:332), so naive reuse would authorize wikitoolkit from `parrot toolkits`. Partial correction: `_uninstall_mcp_approval(root, removed_toolkit_names)` (installer.py:371) IS already name-selective. | §3 M2, §7 Risks |
| S4 | Preflight mutations before seeding (risk) | CONFIRM | Verified: `seed_toolkit_sections` swallows `ValueError` on load (toolkit_seed.py:~200), appends, and only fails on reload; and it seeds valid names while merely reporting `unknown`. | §3 M4, §5 AC |
| S5 | Choose a real comment-preserving YAML strategy (api) | CONFIRM | Verified: no `ruamel` in `packages/ai-parrot/pyproject.toml`; seeding is append-only text. Decision: narrowly-scoped lexical editor, no new core dependency. | §3 M4, §7 Patterns |
| S6 | Make dependency availability metadata explicit (api) | CONFIRM | Verified: `_META_PREFIX` parser handles only `summary:` / `requires_llm:` (toolkit_seed.py:83-89). Adds `requires_dist:` + a non-importing `find_spec` availability probe. | §3 M5, §3 M6 |
| S7 | Derive database-toolkit info from the actual contract (api) | REJECT | Premise is false. `DatabaseQueryToolkit` defines `validate_query` (toolkit.py:265); `validate_database_query` does not exist anywhere in `parrot/tools/databasequery/`. The brainstorm's `dq_validate_query` is correct. The suites it cites (`packages/ai-parrot/tests/tools/databasequery/test_toolkit.py:32`, `test_toolkit_abstracttoolkit_contract.py:32`) assert an ungeneratable name and contradict `tests/tools/test_database_toolkit_parity.py:59,63`. Recorded as a pre-existing defect, out of scope. | §7 Risks (note) |
| S8 | Define Google's target and state precisely (risk) | ESCALATE | Verified and independently found: Google writes BOTH `~/.gemini/config/mcp_config.json` (user-global, `google/assets.py:59-61`) and `.agents/plugins/parrot/mcp_config.json` (repo, `google/installer.py:214`). "All detected hosts" cannot mean the same thing for a user-global file. Needs an owner decision. | §8 Q1 |
| S9 | Audit all builtin consumers in the same change (risk) | CONFIRM | Verified: `examples/dev_loop/mcp_wiring.py`, `local_cli.py:35` docstring, `docs/mcp-local-toolkits.md`, `examples/mcp-toolkits.yaml`, `.mcp.json` all assume implicit builtins. | §3 M9, §5 AC |
| S10 | Add a cross-host command matrix before removing old flags (testing) | CONFIRM | Verified: `test_installer_mcp.py` is the only suite covering the `--toolkits` flags; Codex/Google suites cover conventions, not toolkit reconciliation. | §4, §3 M10 |

Summary: **8** confirmed · **1** rejected · **1** escalated.
