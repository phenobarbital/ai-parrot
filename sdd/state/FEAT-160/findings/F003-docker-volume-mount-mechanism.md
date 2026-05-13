---
id: F003
title: Docker volume mount already supports arbitrary host→container mappings
query: read executor.py:_build_docker_command and _run_with_outputs
confidence: high
---

## Citations

- `packages/ai-parrot-tools/src/parrot_tools/cloudsploit/executor.py:59-83` —
  `_build_docker_command(args, volume_mount=None)` accepts a single
  `(host_dir, container_dir)` tuple and emits `-v host:container`.
- `packages/ai-parrot-tools/src/parrot_tools/cloudsploit/executor.py:263-292` —
  `_run_with_outputs` is the sole caller and uses the slot to mount the
  temp output dir (`_DOCKER_OUTPUT_MOUNT = "/cloudsploit/output"`).
- `packages/ai-parrot-tools/src/parrot_tools/cloudsploit/executor.py:186-231` —
  `execute()` propagates the `volume_mount` argument unchanged into
  `_build_docker_command`.

## Summary

The existing `volume_mount` tuple is already wired through `execute →
_build_docker_command`. **Constraint**: it accepts exactly one tuple, so to
mount BOTH the output dir AND the config file we either (a) widen the API
to `list[tuple[str, str]]`, or (b) mount the directory containing the
config file under a fixed path like `/cloudsploit/config/` and let
CloudSploit read it as `/cloudsploit/config/<basename>`. Option (a) is the
cleaner internal change; option (b) keeps the API surface smaller.

Either way, the config-file path passed to `--config=` must be the
**in-container** path, not the host path.
