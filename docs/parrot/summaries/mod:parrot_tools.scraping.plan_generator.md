---
type: Wiki Summary
title: parrot_tools.scraping.plan_generator
id: mod:parrot_tools.scraping.plan_generator
tags:
- summary
timestamp: '2026-07-14T22:20:21+00:00'
summary: PlanGenerator — LLM-based scraping plan generation.
relates_to:
- concept: class:parrot_tools.scraping.plan_generator.PlanGenerator
  rel: defines
- concept: mod:parrot_tools.scraping.page_snapshot
  rel: references
- concept: mod:parrot_tools.scraping.plan
  rel: references
---

# `parrot_tools.scraping.plan_generator`

PlanGenerator — LLM-based scraping plan generation.

Builds a prompt from a page snapshot, calls the LLM client, and parses
the JSON response into a ScrapingPlan.

## Classes

- **`PlanGenerator`** — Generates ScrapingPlan from URL + objective using an LLM client.
