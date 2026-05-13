---
id: F005
title: Upstream CloudSploit --config CONFIG semantics
query: WebFetch raw.githubusercontent.com/aquasecurity/cloudsploit/master/README.md
confidence: high
---

## Citations

- aquasecurity/cloudsploit README §"CloudSploit Config File": the config
  file is a **JavaScript module** (copy of `config_example.js`) with
  per-cloud-provider sections (`azure: {...}`, `aws: {...}`). Each section
  exposes a `credential_file` option *or* inline keys.
- README §usage:
  > `usage: index.js [-h] --config CONFIG [--compliance {...}] [--plugin PLUGIN] ...`
  > `--config CONFIG    The path to a cloud provider credentials file.`

## Summary

`--config` accepts a path to a **JS file** (not JSON), traditionally named
`config.js`. The file's structure is provider-specific and supports both
inline credentials and nested file references. When the user supplies
`--config`, env-var credentials become moot — the JS module's exports take
precedence.

**Operational implication**: when running under Docker, the JS config file
must be readable inside the container. We need to mount the file (or its
directory) and pass the in-container path. The file is sensitive (it can
contain raw keys), so the mount should be **read-only** (`-v
host:container:ro`).
