---
kind: file
jira_key: null
fetched_at: 2026-06-04
summary_oneline: "ScrapingFlow: composable long-horizon scraping via TemplatePlan, ScrapingFlow DAG, and FlowExecutor"
---

Source file: sdd/proposals/scrapingflow.proposal.md (brainstorm document, Option A recommended)

Three new capabilities on top of existing WebScrapingToolkit:
1. TemplatePlan — parameterized plan templates with ParamSpec + bind()
2. ScrapingFlow — DAG of FlowNodes with data-dependency inputs and session affinity
3. FlowExecutor — in-engine execution over execute_plan_steps with BrowserContext lifecycle, fan-out, and checkpoint

Key constraints from source:
- ScrapingPlan stays immutable — parameterization built ABOVE it
- FlowExecutor runs inside the engine (not delegated to external agents)
- Data passes between stages as Python values (browser-independent)
- Resumable via checkpoints; failure at step N doesn't restart from 0
- Multi-window: multiple Pages within a BrowserContext; distinct contexts for isolation
- Reuse execute_plan_steps, ACTION_MAP, CrawlEngine queue/concurrency, PlanRegistry
- ScrapingFlow is Playwright-first; single-plan scrape() stays driver-agnostic

Existing code references (claimed in brainstorm, to be validated):
- packages/ai-parrot-tools/src/parrot_tools/scraping/executor.py :: execute_plan_steps
- packages/ai-parrot-tools/src/parrot_tools/scraping/extraction_models.py :: ExtractionPlan, ExtractedEntity
- packages/ai-parrot-tools/src/parrot_tools/scraping/models.py :: ACTION_MAP, ScrapingStep
- packages/ai-parrot-tools/src/parrot_tools/scraping/plan.py :: ScrapingPlan
- packages/ai-parrot-tools/src/parrot_tools/scraping/crawler.py :: CrawlEngine
- packages/ai-parrot-tools/src/parrot_tools/scraping/registry.py :: PlanRegistry
- packages/ai-parrot-tools/src/parrot_tools/scraping/__init__.py :: public exports
