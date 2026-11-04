---
id: F004
query_id: Q004
type: read
intent: "What language-neutral, committed SDD configuration already exists?"
executed_at: 2026-11-04T22:15:00Z
duration_ms: 0
parent_id: null
depth: 0
---

# F004 — `sdd/config.json` (`SddConfig`) is the committed, language-neutral team config

## Summary

`SddConfig` holds branch policy, tracker, reviewer, `test_command` and `projects`, with
`extra="forbid"`. `load_sdd_config` reads `<root>/sdd/config.json` and falls back to
defaults when the file is absent. No Python code executes `test_command`: it is stored,
validated, and used to downgrade one lint finding; the prompts tell the agent to run it.

## Citations

- path: `packages/ai-parrot/src/parrot/sdd/config.py`
  lines: 19-35
  symbol: `SddConfig`
  excerpt: |
    model_config = ConfigDict(extra="forbid")
    base_branch: str = "dev"
    staging_branch: str | None = None
    hotfix_base: str = "main"
    ledger_branch: str | None = None
    issue_tracker: Literal["jira", "none"] = "none"
    reviewer: Literal["codex", "none"] = "none"
    test_command: str | None = None
    projects: list[str] | None = None

- path: `packages/ai-parrot/src/parrot/sdd/config.py`
  lines: 106-125
  symbol: `load_sdd_config`
  excerpt: |
    base = root or find_repo_root()
    if base is None:
        return default_sdd_config()
    path = base / CONFIG_PATH
    if not path.is_file():
        return default_sdd_config()

- path: `packages/ai-parrot/src/parrot/sdd/scripts/check_task_graph.py`
  lines: 347-362
  symbol: `_check_validation_contract`
  excerpt: |
    if test_command:
        ...
        level="warning" if test_command else "error",

- path: `packages/ai-parrot/src/parrot/sdd/installer.py`
  lines: 858-868
  symbol: `_test_command_warning`
  excerpt: |
    if config.test_command is not None:
    ...
    "warning: sdd/config.json test_command is null — set it to the command that runs this repo's tests; "

## Notes

`grep -rn test_command --include=*.py` over `packages/ai-parrot/src/parrot` returns only
`sdd/config.py`, `sdd/installer.py`, `sdd/scripts/{check_task_graph,select_tests,
cache_test_contract,test_report}.py` and `self_/doctor.py`; none of them spawns the command.
`sdd/installer.py:45` notes the receipt is "committed with sdd/; .parrot/ is gitignored".
