---
id: F004
title: CloudSploitConfig has no slot for a credentials-config file path
query: read models.py:CloudSploitConfig
confidence: high
---

## Citations

- `packages/ai-parrot-tools/src/parrot_tools/cloudsploit/models.py:81-161` —
  Pydantic model with: `docker_image`, `use_docker`, `cli_path`,
  `cloud_provider`, AWS keys/profile/region/session_token,
  `aws_sdk_load_config`, `gcp_project_id`, `gcp_credentials_path`,
  `timeout_seconds`, `govcloud`, `results_dir`.
- `packages/ai-parrot-tools/src/parrot_tools/cloudsploit/models.py:145-148` —
  `gcp_credentials_path` already establishes the precedent of carrying a
  filesystem path through `CloudSploitConfig` to be consumed by the runner.

## Summary

Adding a `config_file: Optional[str] = None` field to `CloudSploitConfig`
mirrors the existing `gcp_credentials_path` pattern. The model is the right
home for an "instance default" — a user can either set it once on the
toolkit or pass it per-call via `run_scan(config=...)`.
