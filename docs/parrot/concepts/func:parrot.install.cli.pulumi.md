---
type: Concept
title: pulumi()
id: func:parrot.install.cli.pulumi
tags:
- concept
timestamp: '2026-07-16T08:34:12+00:00'
summary: Install Pulumi CLI and optionally the Docker provider.
---

# pulumi

```python
def pulumi(verbose, with_docker)
```

Install Pulumi CLI and optionally the Docker provider.

Installs the Pulumi CLI using the official installer script.
Use --with-docker to also install the pulumi_docker Python package
for programmatic Docker container deployments.

Examples:
    parrot install pulumi
    parrot install pulumi --with-docker
    parrot install pulumi --verbose --with-docker
