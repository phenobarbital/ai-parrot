---
id: F006
title: Existing executor tests pattern — argv inspection on _build_cli_args
query: read tests/cloudsploit/test_executor.py
confidence: high
---

## Citations

- `packages/ai-parrot-tools/tests/cloudsploit/test_executor.py:13-49` —
  Fixture-based tests build `CloudSploitConfig(...)` instances and either
  inspect `executor._build_cli_args(...)`/`_build_docker_command(...)`
  directly or assert env-var behaviour via `_build_env_vars()`.
- Same file: tests already cover govcloud flag, GCP provider, AWS profile,
  use_docker=False mode, and credential precedence — a precedent for how
  to test a new "config file overrides credentials" rule.

## Summary

Test additions can follow the same pure-Python pattern (no Docker spin-up
needed). Each new behaviour needs ~3 tests:
1. `config_file` argument flows through to `--config=<path>` in argv.
2. `config_file` from `CloudSploitConfig` is used when `run_scan(config=None)`.
3. When `config_file` is set, the volume-mount tuple appears in the
   constructed docker command.
