---
type: Wiki Summary
title: parrot.install.cli
id: mod:parrot.install.cli
tags:
- summary
timestamp: '2026-07-16T08:34:12+00:00'
summary: CLI commands for installing external tools via Docker.
relates_to:
- concept: func:parrot.install.cli.cloudsploit
  rel: defines
- concept: func:parrot.install.cli.install
  rel: defines
- concept: func:parrot.install.cli.prowler
  rel: defines
- concept: func:parrot.install.cli.pulumi
  rel: defines
- concept: func:parrot.install.cli.scoutsuite
  rel: defines
---

# `parrot.install.cli`

CLI commands for installing external tools via Docker.

## Functions

- `def install(ctx)` — Install external tools and services (e.g., CloudSploit, Prowler).
- `def cloudsploit(verbose)` — Install CloudSploit by cloning its repo, patching, and building a Docker image.
- `def prowler(verbose)` — Install Prowler by pulling its latest Docker image.
- `def scoutsuite(verbose)` — Install ScoutSuite by running uv pip install.
- `def pulumi(verbose, with_docker)` — Install Pulumi CLI and optionally the Docker provider.
