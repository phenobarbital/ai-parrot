---
type: Wiki Summary
title: parrot_tools.scraping.template_plan
id: mod:parrot_tools.scraping.template_plan
tags:
- summary
timestamp: '2026-07-14T22:20:21+00:00'
summary: TemplatePlan & ParamSpec — parameterized scraping plan templates.
relates_to:
- concept: class:parrot_tools.scraping.template_plan.ParamSpec
  rel: defines
- concept: class:parrot_tools.scraping.template_plan.TemplatePlan
  rel: defines
- concept: mod:parrot_tools.scraping.plan
  rel: references
---

# `parrot_tools.scraping.template_plan`

TemplatePlan & ParamSpec — parameterized scraping plan templates.

A :class:`TemplatePlan` is a reusable, parameterized template that produces a
concrete :class:`ScrapingPlan` via :meth:`TemplatePlan.bind`.  Parameters are
declared with typed :class:`ParamSpec` entries; ``{{param}}`` placeholders in
the URL, objective, and step templates are rendered at bind time (FEAT-222,
Module 1).

Placeholder convention:
    - ``{{param}}`` (double braces) — rendered by ``bind()``.
    - ``{index}`` / ``{i}`` (single braces) — Loop's convention; passed
      through unchanged so the two layers never collide.

Rendering uses ``re.sub`` rather than ``str.format()`` so unrelated braces
(CSS selectors, JSON) never raise ``KeyError``.

## Classes

- **`ParamSpec(BaseModel)`** — Typed parameter definition for a :class:`TemplatePlan`.
- **`TemplatePlan(BaseModel)`** — Parameterized plan template that produces ``ScrapingPlan``s via ``bind()``.
