---
type: Wiki Summary
title: parrot.tools.executors.k8s
id: mod:parrot.tools.executors.k8s
tags:
- summary
timestamp: '2026-07-14T22:20:21+00:00'
summary: Kubernetes-backed remote tool executor.
relates_to:
- concept: class:parrot.tools.executors.k8s.K8sToolExecutor
  rel: defines
- concept: mod:parrot.conf
  rel: references
- concept: mod:parrot.tools.abstract
  rel: references
- concept: mod:parrot.tools.executors.abstract
  rel: references
---

# `parrot.tools.executors.k8s`

Kubernetes-backed remote tool executor.

Submits the envelope as a single-shot ``batch/v1 Job`` running the
``parrot-tools`` image. The image's entrypoint is
``python -m parrot.cli.tool_worker --envelope -`` which reads the
envelope JSON from stdin and prints the resulting ``ToolResult`` JSON
to stdout. The executor tails the pod's logs to read that result, then
deletes the Job so Kubernetes reclaims the pod.

This module's heavy dependency (``kubernetes_asyncio``) is only
imported when an executor instance is constructed, so projects that
never use the K8s executor are not forced to install the client.

## Classes

- **`K8sToolExecutor(AbstractToolExecutor)`** — Runs the envelope inside an ephemeral Kubernetes Job.
