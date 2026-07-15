---
type: Wiki Summary
title: parrot_tools.scraping.flow_executor
id: mod:parrot_tools.scraping.flow_executor
tags:
- summary
timestamp: '2026-07-14T22:20:21+00:00'
summary: FlowExecutor — orchestration engine for ScrapingFlow execution.
relates_to:
- concept: class:parrot_tools.scraping.flow_executor.FlowExecutor
  rel: defines
- concept: mod:parrot_tools.scraping.base_registry
  rel: references
- concept: mod:parrot_tools.scraping.drivers.page_driver
  rel: references
- concept: mod:parrot_tools.scraping.executor
  rel: references
- concept: mod:parrot_tools.scraping.flow_models
  rel: references
- concept: mod:parrot_tools.scraping.models
  rel: references
- concept: mod:parrot_tools.scraping.plan
  rel: references
- concept: mod:parrot_tools.scraping.plan_io
  rel: references
- concept: mod:parrot_tools.scraping.session_manager
  rel: references
- concept: mod:parrot_tools.scraping.template_plan
  rel: references
- concept: mod:parrot_tools.scraping.toolkit_models
  rel: references
---

# `parrot_tools.scraping.flow_executor`

FlowExecutor — orchestration engine for ScrapingFlow execution.

Ties together the FEAT-222 layers: topological ordering (:class:`ScrapingFlow`),
template binding (:class:`TemplatePlan`), session/page management
(:class:`SessionManager` + :class:`PageDriver`), per-node execution
(``execute_plan_steps``), data-dependency input resolution, fan-out, per-node
error policies, and checkpoint persistence/resumption (FEAT-222, Module 8).

## Classes

- **`FlowExecutor`** — Orchestrate end-to-end execution of a :class:`ScrapingFlow`.
