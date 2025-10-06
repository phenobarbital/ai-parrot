# Class Catalog by Module

[Back to README](../README.md)

This catalog lists primary classes across the `parrot` package based on the current codebase. Short descriptions come from docstrings or module context. See source for details.

## parrot/bots
- `AbstractBot` (`parrot/bots/abstract.py`): Base bot orchestration (LLM, tools, memory, context).
- `Chatbot` (`parrot/bots/chatbot.py`): Core conversational bot built on `AbstractBot`.
- `BasicAgent` (`parrot/bots/agent.py`): Lightweight agent with tool execution.
- `NextStop` (`parrot/bots/nextstop.py`): Agent implementation for NextStop reports (visit reports, scripts, PDFs, podcasts) with specific prompts and toolkits.

### Database Agents
- `AbstractDBAgent` (`parrot/bots/db/dbagent.py`): Base class for DB-enabled agents.
- `SQLDbAgent` (`parrot/bots/db/sqlagent.py`): SQL database agent.
- `ElasticDbAgent` (`parrot/bots/db/elastic.py`): Elasticsearch agent.
- `InfluxDBAgent` (`parrot/bots/db/influx.py`): InfluxDB agent.
- `MultiDatabaseAgent` (`parrot/bots/db/multi.py`): Multi‑DB orchestrator.

## parrot/clients
- `AbstractClient` (`parrot/clients/base.py`): LLM client abstraction (streaming, retries, tools).
- `GoogleGenAIClient` (`parrot/clients/google.py`)
- `OpenAIClient` (`parrot/clients/gpt.py`)
- `ClaudeClient` (`parrot/clients/claude.py`)
- `GroqClient` (`parrot/clients/groq.py`)
- `VertexAIClient` (`parrot/clients/vertex.py`)
- `TransformersClient` (`parrot/clients/hf.py`)

## parrot/tools (Framework)
- `AbstractTool` (`parrot/tools/abstract.py`): Unified tool interface.
- `ToolInfo`, `ToolRegistry` (`parrot/tools/abstract.py`): Tool metadata and registry.
- `ToolDefinition`, `ToolFormat`, `ToolSchemaAdapter`, `ToolManager` (`parrot/tools/manager.py`): Tool wiring and schema adapters.
- `AbstractToolkit` (`parrot/tools/toolkit.py`): Group tools under a domain.

## parrot/tools (Selected Implementations)
- `PythonREPLTool` (`parrot/tools/pythonrepl.py`)
- `GoogleSearchTool`, `GoogleSiteSearchTool`, `GoogleLocationTool`, `GoogleRoutesTool` (`parrot/tools/google.py`)
- `DuckDuckGoToolkit` (`parrot/tools/ddgo.py`)
- `CorrelationAnalysisTool` (`parrot/tools/correlationanalysis.py`)
- `PDFPrintTool` (`parrot/tools/pdfprint.py`)
- `GoogleVoiceTool` (`parrot/tools/gvoice.py`)
- `PowerPointTool` (`parrot/tools/ppt.py`)
- `MSWordTool`, `WordToMarkdownTool` (`parrot/tools/msword.py`)
- `ExcelTool`, `DataFrameToExcelTool` (`parrot/tools/excel.py`)
- `QuerySourceTool` (`parrot/tools/qsource.py`)
- `OpenWeatherTool` (`parrot/tools/openweather.py`)
- `QuickEdaTool` (`parrot/tools/quickeda.py`)
- `SeasonalDetectionTool` (`parrot/tools/seasonaldetection.py`)
- `ToolkitTool` (`parrot/tools/toolkit.py`)

## parrot/handlers
- `BotModel`, `ChatbotUsage`, `ChatbotFeedback`, `PromptLibrary` (`parrot/handlers/models.py`)
- `ChatHandler`, `BotHandler`, `BotManagement` (`parrot/handlers/chat.py`)
- `PromptLibraryManagement`, `ChatbotUsageHandler`, `ChatbotFeedbackHandler`, `ChatbotSharingQuestion`, `ToolList` (`parrot/handlers/bots.py`)
- `AgentManager` (`parrot/handlers/agents/manager.py`)
 - `AgentHandler` (`parrot/handlers/agents/abstract.py`): Abstract REST handler for AI agents. Registers routes, wires `BackgroundService` with Redis tracker, exposes `register_background_task`, `get_task_status`, and `find_jobs`. Also provides auth decorators and helper utilities.
 - `RedisWriter` (`parrot/handlers/agents/abstract.py`): Thin AsyncDB wrapper for Redis using `CACHE_URL`.
 - `JobWSManager` (`parrot/handlers/agents/abstract.py`): WebSocket manager that can notify users when a job finishes.

## resources/nextstop
- `NextStopAgent` (`resources/nextstop/handler.py`): HTTP handler exposing NextStop API at `/api/v1/agents/nextstop`. Accepts POST to enqueue background jobs (store/manager/employee/query flows), exposes `get_results`, `get_agent_status`, and `find_jobs` endpoints, and persists results to Postgres/BigQuery stores depending on configuration.
- `NextStopStore` (`resources/nextstop/models.py`): AsyncDB `Model` mapping to `troc.nextstop_responses` with fields for content, data, documents, paths, attributes, and metadata.

## parrot/interfaces
- Image plugins (`parrot/interfaces/images/plugins/*`): `AnalysisPlugin`, `ClassifyBase`, `ClassificationPlugin`, `DetectionPlugin`

## parrot/stores
- `AbstractStore` (`parrot/stores/abstract.py`)
- `PgVectorStore` (`parrot/stores/postgres.py`)
- `BigQueryStore` (`parrot/stores/bigquery.py`)

## parrot/loaders
- `AbstractLoader` (base); `PDFMarkdownLoader`, `PDFTablesLoader`, `PDFLoader`, `MarkdownLoader`, `MSWordLoader`, `ExcelLoader`, `HTMLLoader`, `CSVLoader`, `EpubLoader`, `WebLoader`, `AudioLoader`, `VideoLoader`, `VimeoLoader`, `YoutubeLoader`, `VideoLocalLoader`, `QAFileLoader`, `PowerPointLoader`.

## parrot/models
- Messaging: `AIMessage`, `AgentResponse`, `AIMessageFactory` (`parrot/models/responses.py`).
- Outputs: `StructuredOutputConfig`, `BoundingBox`, `ObjectDetectionResult`, `ImageGenerationPrompt`, `SpeakerConfig`, `SpeechGenerationPrompt`, `VideoGenerationPrompt`, `SentimentAnalysis`, `ProductReview` (`parrot/models/outputs.py`).
- Detections/Compliance: `DetectionBox`, `ShelfRegion`, `IdentifiedProduct`, `BrandDetectionConfig`, `CategoryDetectionConfig`, `ShelfProduct`, `ShelfConfig`, `TextRequirement`, `AdvertisementEndcap`, `AisleConfig`, `PlanogramDescription`, `PlanogramConfigBuilder`, `ComplianceStatus`, `TextComplianceResult`, `ComplianceResult`, `TextMatcher`.

---
If a class is missing, it may be internal or abstract with limited surface. Refer to source files for implementation specifics.


