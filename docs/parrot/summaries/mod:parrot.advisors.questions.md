---
type: Wiki Summary
title: parrot.advisors.questions
id: mod:parrot.advisors.questions
tags:
- summary
timestamp: '2026-07-14T22:20:21+00:00'
summary: Discriminant Question Generation for Product Selection.
relates_to:
- concept: class:parrot.advisors.questions.AnswerOption
  rel: defines
- concept: class:parrot.advisors.questions.AnswerType
  rel: defines
- concept: class:parrot.advisors.questions.CatalogAnalysis
  rel: defines
- concept: class:parrot.advisors.questions.DiscriminantQuestion
  rel: defines
- concept: class:parrot.advisors.questions.FeatureAnalysis
  rel: defines
- concept: class:parrot.advisors.questions.FeatureAnalyzer
  rel: defines
- concept: class:parrot.advisors.questions.GeneratedQuestion
  rel: defines
- concept: class:parrot.advisors.questions.QuestionCategory
  rel: defines
- concept: class:parrot.advisors.questions.QuestionGenerationResponse
  rel: defines
- concept: class:parrot.advisors.questions.QuestionSet
  rel: defines
- concept: class:parrot.advisors.questions.ValueMapping
  rel: defines
- concept: mod:parrot.advisors.models
  rel: references
---

# `parrot.advisors.questions`

Discriminant Question Generation for Product Selection.

This module handles:
- Analysis of product catalogs to identify discriminating features
- LLM-based generation of natural language questions
- Question prioritization based on elimination power
- Response mapping to filter criteria

## Classes

- **`AnswerType(str, Enum)`** — Type of expected answer from user.
- **`QuestionCategory(str, Enum)`** — Categories of discriminant questions.
- **`AnswerOption(BaseModel)`** — A single answer option for choice-type questions.
- **`ValueMapping(BaseModel)`** — Maps user responses to filter criteria.
- **`DiscriminantQuestion(BaseModel)`** — A question designed to filter/discriminate between products.
- **`QuestionSet(BaseModel)`** — Complete set of discriminant questions for a catalog.
- **`GeneratedQuestion(BaseModel)`** — Schema for LLM-generated question (subset of DiscriminantQuestion).
- **`QuestionGenerationResponse(BaseModel)`** — Complete response from LLM question generation.
- **`FeatureAnalysis(BaseModel)`** — Analysis of a single feature across the catalog.
- **`CatalogAnalysis(BaseModel)`** — Complete analysis of a product catalog.
- **`FeatureAnalyzer`** — Analyzes a product catalog to identify discriminating features.
