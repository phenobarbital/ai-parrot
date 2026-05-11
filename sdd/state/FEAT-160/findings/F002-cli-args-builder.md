---
id: F002
title: _build_cli_args never emits --config
query: read executor.py:_build_cli_args
confidence: high
---

## Citations

- `packages/ai-parrot-tools/src/parrot_tools/cloudsploit/executor.py:109-151` —
  Builds: `--json=`, `--console=none`, `--cloud=`, `--collection=`,
  `--compliance=`, `--plugin <p>`, `--ignore-ok`, `--suppress <s>`,
  `--govcloud`. No `--config` clause.
- `packages/ai-parrot-tools/src/parrot_tools/cloudsploit/executor.py:33-57` —
  `_build_env_vars()` exports AWS/GCP credentials so CloudSploit picks them
  up via the AWS SDK default credential chain. This is the *only* credential
  delivery path today.

## Summary

`--config` is the single hook CloudSploit exposes for "use this file instead
of env vars". The current builder has no provision for it. Adding one is a
contained edit (one new optional `config_path` parameter, one extra
`args.append(f"--config={config_path}")` line at the top of the args list so
it appears before `--cloud`).
