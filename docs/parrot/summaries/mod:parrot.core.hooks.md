---
type: Wiki Summary
title: parrot.core.hooks
id: mod:parrot.core.hooks
tags:
- summary
timestamp: '2026-07-16T08:34:12+00:00'
summary: External hooks system for AutonomousOrchestrator.
relates_to:
- concept: mod:parrot.core
  rel: references
---

# `parrot.core.hooks`

External hooks system for AutonomousOrchestrator.

All concrete hook imports are lazy to avoid pulling in heavy
transitive dependencies (asyncpg, watchdog, apscheduler, aioimaplib,
azure-identity, etc.) at package import time.
