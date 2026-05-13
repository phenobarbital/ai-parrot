---
id: F001
title: CloudSploitToolkit.run_scan and CloudSploitExecutor.run_scan surfaces today
query: read packages/ai-parrot-tools/src/parrot_tools/cloudsploit/toolkit.py and executor.py
confidence: high
---

## Citations

- `packages/ai-parrot-tools/src/parrot_tools/cloudsploit/toolkit.py:43-83` —
  `async def run_scan(self, plugins=None, ignore_ok=False, suppress=None) -> ScanResult`.
  Calls `self.executor.run_scan(plugins=, ignore_ok=, suppress=)` only.
- `packages/ai-parrot-tools/src/parrot_tools/cloudsploit/toolkit.py:85-122` —
  `async def run_compliance_scan(self, framework, ignore_ok=True)`. Same parameter
  set, no config-file path.
- `packages/ai-parrot-tools/src/parrot_tools/cloudsploit/executor.py:311-336` —
  `CloudSploitExecutor.run_scan(plugins, ignore_ok, suppress, capture_collection)`
  forwards to `_run_with_outputs`.
- `packages/ai-parrot-tools/src/parrot_tools/cloudsploit/executor.py:338-360` —
  `run_compliance_scan` likewise.

## Summary

The toolkit's tool-facing `run_scan` is a thin pass-through to the executor.
Both methods currently lack any concept of a CloudSploit credentials config
file; credentials are *only* exposed through `CloudSploitConfig` fields that
get materialised as env vars in `_build_env_vars()`.
