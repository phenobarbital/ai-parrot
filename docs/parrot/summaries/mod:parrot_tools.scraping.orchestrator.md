---
type: Wiki Summary
title: parrot_tools.scraping.orchestrator
id: mod:parrot_tools.scraping.orchestrator
tags:
- summary
timestamp: '2026-07-16T08:34:12+00:00'
summary: ScrapingOrchestrator for AI-Parrot
relates_to:
- concept: class:parrot_tools.scraping.orchestrator.ScrapingMissionBuilder
  rel: defines
- concept: class:parrot_tools.scraping.orchestrator.ScrapingOrchestrator
  rel: defines
- concept: func:parrot_tools.scraping.orchestrator.example_ecommerce_scraping
  rel: defines
- concept: func:parrot_tools.scraping.orchestrator.example_news_monitoring
  rel: defines
- concept: func:parrot_tools.scraping.orchestrator.extract_price_number
  rel: defines
- concept: func:parrot_tools.scraping.orchestrator.integrate_with_knowledge_base
  rel: defines
- concept: mod:parrot.bots.scraper
  rel: references
- concept: mod:parrot.models.responses
  rel: references
- concept: mod:parrot.stores.kb
  rel: references
- concept: mod:parrot_loaders
  rel: references
- concept: mod:parrot_tools.scraping.models
  rel: references
- concept: mod:parrot_tools.scraping.tool
  rel: references
---

# `parrot_tools.scraping.orchestrator`

ScrapingOrchestrator for AI-Parrot
Complete integration layer that coordinates LLM-directed web scraping

## Classes

- **`ScrapingOrchestrator`** — High-level orchestrator that manages the complete LLM-directed scraping workflow.
- **`ScrapingMissionBuilder`** — Builder pattern for creating complex scraping missions

## Functions

- `async def example_ecommerce_scraping()` — Example: Scraping product information from e-commerce sites
- `async def example_news_monitoring()` — Example: Monitor news sites for specific topics
- `def extract_price_number(price_text: str) -> Optional[float]` — Helper function to extract numeric price from text
- `async def integrate_with_knowledge_base(kb_store: KnowledgeBaseStore)` — Example of full integration with AI-parrot knowledge base
