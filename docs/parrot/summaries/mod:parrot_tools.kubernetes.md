---
type: Wiki Summary
title: parrot_tools.kubernetes
id: mod:parrot_tools.kubernetes
tags:
- summary
timestamp: '2026-07-14T22:20:21+00:00'
summary: Kubernetes Toolkit for AI-Parrot agents.
relates_to:
- concept: mod:parrot_tools
  rel: references
- concept: mod:parrot_tools.toolkit
  rel: references
---

# `parrot_tools.kubernetes`

Kubernetes Toolkit for AI-Parrot agents.

Provides kubectl-like cluster management operations as agent tools.
Read operations (list_pods, get_logs, describe, get) require no grant.
Mutating operations (apply_manifest, scale_deployment, delete_resource,
rollout_restart) carry routing_meta["requires_grant"] = True for FEAT-211
governance integration.
