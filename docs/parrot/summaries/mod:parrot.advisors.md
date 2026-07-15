---
type: Wiki Summary
title: parrot.advisors
id: mod:parrot.advisors
tags:
- summary
timestamp: '2026-07-14T22:20:21+00:00'
summary: Product Advisor - AI-powered product recommendation system.
relates_to:
- concept: mod:parrot
  rel: references
- concept: mod:parrot.manager
  rel: references
- concept: mod:parrot.models
  rel: references
- concept: mod:parrot.tools
  rel: references
---

# `parrot.advisors`

Product Advisor - AI-powered product recommendation system.

This package provides:
- ProductAdvisorMixin: Mixin to add product advisor capabilities to bots
- ProductCatalog: Product storage with hybrid search
- QuestionSet/QuestionGenerator: Discriminant question generation
- SelectionStateManager: Redis-based state with undo/redo support

Usage with BaseBot:
    from parrot.advisors import ProductAdvisorMixin, ProductCatalog
    from parrot.bots import BaseBot

    class ProductBot(ProductAdvisorMixin, BaseBot):
        pass

    catalog = ProductCatalog(catalog_id="my_products")
    await catalog.initialize()

    bot = ProductBot(
        name="Product Advisor",
        llm="google:gemini-3.1-flash-lite-preview",
        catalog=catalog,
    )
    await bot.configure()
    await bot.configure_advisor()
