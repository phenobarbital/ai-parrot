# Language-Agnostic Validation Runners (FEAT-709)

## Overview

Validation runners provide a language-agnostic way to execute tests and return structured verdicts. The system supports multiple test frameworks through adapter protocols, enabling validation beyond just pytest.

## Runner Configuration

Runner configuration is defined in `.parrot/test_runners.tomL` at the repository root. This is the only extension point for adding new runners or configuring existing ones.

Example configuration:
```toml
[runners.pytest]
timeout_s = 60

[runners.vitest]
cwd = "packages/ai-parrot-server/ui"
timeout_s = 120

[runners.cargo]
timeout_s = 300

[runners.parrot-e2e]
tiers = ["merge", "feature"]

[extensions]
# kind = "dotted.module:AdapterClass"
```

## Supported Runners

### Pytest (Python)
- **Kind**: `pytest`
- **Default tiers**: All (`task`, `merge`, `feature`)
- **Report format**: JUnit XML
- **Timeout**: 60 seconds (configurable)

### Vitest (TypeScript/Javascript)
- **Kind**: `vitest`
- **Default tiers**: All (`task`, `merge`, `feature`)
- **Report format**: JUnit XML
- **Timeout**: 120 seconds (configurable)
- **Working directory**: Configurable via `cwd` setting

### Cargo (Rust)
- **Kind**: `cargo`
- **Default tiers**: All (`task`, `merge`, `feature`)
- **Report format**: Libtest text output
- **Timeout**: 300 seconds (configurable)

### Parrot E2E
- **Kind**: `parrot-e2e`
- **Default tiers**: `merge`, `feature` only
- **Report format**: Custom JSON verdict
- **Timeout**: Configurable

## Verdict Schema

Validation runners return a structured verdict in JSON format:

```json
{
  "schema": 1,
  "status": "passed|failed|timed_out|unavailable|blocked",
  "tier": "task|merge|feature",
  "runners": [
    {
      "runner": "pytest|vitest|cargo|parrot-e2e",
      "suite": "<runner>:<distribution>",
      "tests": 0,
      "passed": 0,
      "failed": 0,
      "errors": 0,
      "skipped": 0,
      "cached": 0,
      "duration_s": 0.0,
      "exit_code": 0,
      "status": "passed|failed|timed_out|no_report|unavailable"
    }
  ],
  "failures": [
    {
      "runner": "pytest|vitest|cargo|parrot-e2e",
      "nodeid": "test_identifier",
      "verdict": "new_red|baseline_red|unknown",
      "excerpt": "failure excerpt text"
    }
  ],
  "cached": ["target1", "target2"],
  "notes": ["note1", "note2"],
  "evidence": ["path/to/report1", "path/to/report2"]
}
```

## Tiers

Each runner can be configured to operate in specific tiers:

- **Task tier**: Runs during individual task validation
- **Merge tier**: Runs during merge validation
- **Feature tier**: Runs during feature-level validation

## Cache and Baseline Behavior

Only pytest targets participate in green cache and baseline classification. Non-pytest runners:
- Have no cache support
- Failures are classified as `unknown`
- Gate on any red result (no baseline comparison)

## Validation Process

1. **Task Tier Execution**: Seats use `run_validation` tool or Bash commands that are rewritten to verdict commands
2. **Engine Gate**: After commit, the engine re-runs validation and gates on red results
3. **Same-Seat Repair**: Red gates re-dispatch the same seat once with the verdict for repair
4. **Verdict Return**: Only structured verdict data is returned to seats, never raw test output

## Command Usage

### MCP Seats
```python
# Available as a tool when validation capability is bound
run_validation(targets=["specific_test.py::test_name"])
```

### Native Seats
```bash
# Lone runner commands are rewritten to verdict commands
pytest tests/  # Rewritten to: python scripts/sdd/select_tests.py --tier task --run --verdict --worktree .
```

## Error Handling

- **Timeouts**: Individual runner timeouts and overall validation timeouts are enforced
- **Unavailable Runners**: Missing binaries or configuration errors result in `unavailable` status
- **Parse Failures**: Malformed reports result in `no_report` status
- **Guard Rules**: Over-broad commands are blocked or rewritten appropriately