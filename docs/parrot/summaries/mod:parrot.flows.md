---
type: Wiki Summary
title: parrot.flows
id: mod:parrot.flows
tags:
- summary
timestamp: '2026-07-16T08:34:12+00:00'
summary: Application-level flows for AI-Parrot.
---

# `parrot.flows`

Application-level flows for AI-Parrot.

This namespace hosts higher-level orchestration flows built on top of the
``parrot.bots.flow`` FSM primitive. Each subpackage (e.g. ``dev_loop``)
implements a specific multi-node flow tailored to a use case.
