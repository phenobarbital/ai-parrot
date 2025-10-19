# AI-Parrot Configuration Guide

This document describes the most important configuration values for AI-Parrot. All configuration values are loaded from `.env` files in the `env/` folder using `navconfig`.

## Table of Contents

- [LLM API Keys](#llm-api-keys)
- [Database Configuration](#database-configuration)
- [Cache & Redis](#cache--redis)
- [Vector Databases](#vector-databases)
- [Microsoft Integration](#microsoft-integration)
- [Cloud Services](#cloud-services)
- [LLM Defaults](#llm-defaults)
- [Embedding Configuration](#embedding-configuration)
- [Directory Paths](#directory-paths)
- [HTTP Client](#http-client)
- [Additional Tools](#additional-tools)

---

## LLM API Keys

### Google GenAI
Configuration for Google's Generative AI (Gemini models).

- **`GOOGLE_API_KEY`**: API key for Google GenAI services
- **`VERTEX_PROJECT_ID`**: Google Cloud project ID for Vertex AI
- **`VERTEX_REGION`**: Region for Vertex AI deployment

### OpenAI
Configuration for OpenAI models (GPT-4, GPT-3.5, etc.).

- **`OPENAI_API_KEY`**: API key for OpenAI services
- **`OPENAI_ORGANIZATION`**: Optional organization ID for OpenAI

### Anthropic Claude
Configuration for Claude models.

- **`ANTHROPIC_API_KEY`**: API key for Claude/Anthropic services

### Groq
Configuration for Groq's fast inference platform.

- **`GROQ_API_KEY`**: API key for Groq services
- **`DEFAULT_GROQ_MODEL`**: Default model to use (default: `qwen/qwen3-32b`)

### HuggingFace
Configuration for HuggingFace models and embeddings.

- **`HUGGINGFACEHUB_API_TOKEN`**: API token for HuggingFace Hub access

---

## Database Configuration

### PostgreSQL
Primary database for structured data and PgVector.

- **`DBHOST`**: PostgreSQL host (default: `localhost`)
- **`DBUSER`**: Database username
- **`DBPWD`**: Database password
- **`DBNAME`**: Database name (default: `navigator`)
- **`DBPORT`**: PostgreSQL port (default: `5432`)

The connection string is automatically constructed as:
```
postgresql+asyncpg://{DBUSER}:{DBPWD}@{DBHOST}:{DBPORT}/{DBNAME}
```

### ScyllaDB
NoSQL database for high-performance distributed storage.

- **`SCYLLADB_DRIVER`**: Driver type (default: `scylladb`)
- **`SCYLLADB_HOST`**: ScyllaDB host (default: `localhost`)
- **`SCYLLADB_PORT`**: ScyllaDB port (default: `9042`)
- **`SCYLLADB_USERNAME`**: Username (default: `navigator`)
- **`SCYLLADB_PASSWORD`**: Password (default: `navigator`)
- **`SCYLLADB_KEYSPACE`**: Keyspace name (default: `navigator`)

### BigQuery
Google BigQuery configuration for analytics.

- **`BIGQUERY_CREDENTIALS`**: Path to BigQuery credentials JSON file
- **`BIGQUERY_PROJECT_ID`**: GCP project ID (default: `navigator`)
- **`BIGQUERY_DATASET`**: Default dataset name (default: `navigator`)

---

## Cache & Redis

Redis is used extensively for caching, conversation history, job management, and knowledge base storage.

### Core Redis Configuration
- **`CACHE_HOST`**: Redis host (inherited from Navigator config)
- **`CACHE_PORT`**: Redis port (inherited from Navigator config)

### Redis History
Used for storing conversation history and agent memory.

- **`REDIS_HISTORY_DB`**: Database number for conversation history (default: `3`)
- **`REDIS_HISTORY_URL`**: Automatically constructed as `redis://{CACHE_HOST}:{CACHE_PORT}/{REDIS_HISTORY_DB}`

**Usage**: The `RedisKnowledgeBase` class uses this for storing agent conversation memory and user preferences. JobManager and RQ (Redis Queue) use the base `CACHE_HOST` and `CACHE_PORT` for background task processing.

---

## Vector Databases

Vector stores are used for RAG (Retrieval-Augmented Generation) and semantic search.

### Milvus
High-performance vector database with advanced features.

- **`MILVUS_HOST`**: Milvus host (default: `localhost`)
- **`MILVUS_PROTOCOL`**: Protocol (default: `http`)
- **`MILVUS_PORT`**: Milvus port (default: `19530`)
- **`MILVUS_URL`**: Complete Milvus URL (overrides host/port if set)
- **`MILVUS_TOKEN`**: Authentication token
- **`MILVUS_USER`**: Username for authentication
- **`MILVUS_PASSWORD`**: Password for authentication
- **`MILVUS_SECURE`**: Enable secure connection (default: `false`)

**TLS/SSL Configuration**:
- **`MILVUS_SERVER_NAME`**: Server name for TLS
- **`MILVUS_CA_CERT`**: Path to CA certificate
- **`MILVUS_SERVER_CERT`**: Path to server certificate
- **`MILVUS_SERVER_KEY`**: Path to server key
- **`MILVUS_USE_TLSv2`**: Use TLS v1.2 (default: `false`)

### Qdrant
Alternative vector database with good performance.

- **`QDRANT_PROTOCOL`**: Protocol (default: `http`)
- **`QDRANT_HOST`**: Qdrant host (default: `localhost`)
- **`QDRANT_PORT`**: Qdrant port (default: `6333`)
- **`QDRANT_USE_HTTPS`**: Enable HTTPS (default: `false`)
- **`QDRANT_URL`**: Complete Qdrant URL (overrides other settings)
- **`QDRANT_CONN_TYPE`**: Connection type - `server` or `cloud` (default: `server`)

### ChromaDB
Lightweight vector database for development.

- **`CHROMADB_HOST`**: ChromaDB host (default: `localhost`)
- **`CHROMADB_PORT`**: ChromaDB port (default: `8000`)

---

## Microsoft Integration

### MS Teams Toolkit
Configuration for MS Teams bot and messaging integration. Used by the `MSTeamsToolkit` class for sending messages, creating chats, and managing Teams resources.

- **`MS_TEAMS_TENANT_ID`**: Azure AD tenant ID (required)
- **`MS_TEAMS_CLIENT_ID`**: Azure AD application client ID (required)
- **`MS_TEAMS_CLIENT_SECRET`**: Azure AD application secret (required for app-only auth)
- **`MS_TEAMS_USERNAME`**: Username for delegated authentication (required if `as_user=True`)
- **`MS_TEAMS_PASSWORD`**: Password for delegated authentication (required if `as_user=True`)

**Default Team/Channel**:
- **`MS_TEAMS_DEFAULT_TEAMS_ID`**: Default Teams team ID for notifications
- **`MS_TEAMS_DEFAULT_CHANNEL_ID`**: Default channel ID for notifications

**Note**: Teams authentication supports both application-only permissions (using client secret) and delegated user permissions (using username/password).

### Teams Notifications (Legacy)
Older notification system configuration.

- **`TEAMS_NOTIFY_TENANT_ID`**: Tenant ID for notifications
- **`TEAMS_NOTIFY_CLIENT_ID`**: Client ID for notifications
- **`TEAMS_NOTIFY_CLIENT_SECRET`**: Client secret for notifications
- **`TEAMS_NOTIFY_USERNAME`**: Username for notification service
- **`TEAMS_NOTIFY_PASSWORD`**: Password for notification service

### Office 365
General Office 365 integration.

- **`O365_CLIENT_ID`**: Office 365 application client ID
- **`O365_CLIENT_SECRET`**: Office 365 application secret
- **`O365_TENANT_ID`**: Office 365 tenant ID

### SharePoint
SharePoint-specific configuration.

- **`SHAREPOINT_APP_ID`**: SharePoint app ID
- **`SHAREPOINT_APP_SECRET`**: SharePoint app secret
- **`SHAREPOINT_TENANT_ID`**: SharePoint tenant ID
- **`SHAREPOINT_TENANT_NAME`**: SharePoint tenant name
- **`SHAREPOINT_SITE_ID`**: Default site ID
- **`SHAREPOINT_DEFAULT_HOST`**: Default SharePoint host

---

## Cloud Services

### Amazon AWS
AWS credentials for S3 and other services.

- **`AWS_REGION`**: AWS region (default: `us-east-1`)
- **`AWS_BUCKET`**: S3 bucket name (default: `static-files`)
- **`AWS_KEY`**: AWS access key ID
- **`AWS_SECRET`**: AWS secret access key

### Google Cloud Services
Additional Google services beyond GenAI.

- **`GOOGLE_SEARCH_API_KEY`**: API key for Google Custom Search
- **`GOOGLE_SEARCH_ENGINE_ID`**: Custom Search Engine ID
- **`GOOGLE_PLACES_API_KEY`**: API key for Google Places
- **`GOOGLE_CREDENTIALS_FILE`**: Path to Google service account credentials (default: `env/google/key.json`)

**Google Text-to-Speech**:
- **`GOOGLE_TTS_SERVICE`**: Path to TTS service credentials (default: `env/google/tts-service.json`)

**Google Analytics**:
- **`GA_SERVICE_ACCOUNT_NAME`**: Service account filename (default: `google.json`)
- **`GA_SERVICE_PATH`**: Path to service account files (default: `env/google/`)

---

## LLM Defaults

### Model Selection
- **`DEFAULT_LLM_MODEL`**: Default model across the application (default: `gemini-2.5-flash`)
- **`LLM_MODEL_NAME`**: Alias for model name (default: `gemini-2.5-pro`)
- **`LLM_TEMPERATURE`**: Default temperature for generation (default: `0.1`)

### Model-Specific Defaults
- **`DEFAULT_GROQ_MODEL`**: Default Groq model (default: `qwen/qwen3-32b`)

---

## Embedding Configuration

Settings for text embeddings used in RAG and semantic search.

### Device & Performance
- **`EMBEDDING_DEVICE`**: Device for embedding inference - `cpu` or `cuda` (default: `cpu`)
- **`CUDA_DEFAULT_DEVICE`**: CUDA device type (default: `cpu`)
- **`CUDA_DEFAULT_DEVICE_NUMBER`**: CUDA device number (default: `0`)
- **`MAX_VRAM_AVAILABLE`**: Maximum VRAM in MB (default: `20000`)
- **`RAM_AVAILABLE`**: Available RAM in MB (default: `819200`)
- **`MAX_BATCH_SIZE`**: Maximum batch size for processing (default: `2048`)

### Models
- **`EMBEDDING_DEFAULT_MODEL`**: Default embedding model from HuggingFace (default: `sentence-transformers/all-MiniLM-L12-v2`)
- **`KB_DEFAULT_MODEL`**: Default model for knowledge base operations (default: `sentence-transformers/paraphrase-MiniLM-L3-v2`)

### Storage
- **`HUGGINGFACE_EMBEDDING_CACHE_DIR`**: Cache directory for downloaded models (default: `{BASE_DIR}/model_cache/huggingface`)

---

## Directory Paths

Core application directories. Most paths are relative to `BASE_DIR` (project root).

### Application Directories
- **`PLUGINS_DIR`**: Plugins directory (default: `{BASE_DIR}/plugins`)
- **`STATIC_DIR`**: Static files directory (default: `{BASE_DIR}/static`)
- **`AGENTS_DIR`**: Agent definitions directory (default: `{BASE_DIR}/agents`)
- **`AGENTS_BOTS_PROMPT_DIR`**: Agent prompts directory (default: `{AGENTS_DIR}/prompts`)
- **`MCP_SERVER_DIR`**: MCP (Model Context Protocol) servers directory (default: `{BASE_DIR}/mcp_servers`)

### Static Content
- **`BASE_STATIC_URL`**: Base URL for static files (default: `http://localhost:5000/static`)

---

## HTTP Client

Configuration for async HTTP operations.

- **`HTTPCLIENT_MAX_SEMAPHORE`**: Maximum concurrent HTTP requests (default: `5`)
- **`HTTPCLIENT_MAX_WORKERS`**: Worker threads for HTTP operations (default: `1`)

---

## Additional Tools

### Weather
- **`OPENWEATHER_APPID`**: OpenWeatherMap API key

### Search
- **`SERPAPI_API_KEY`**: SerpAPI key for web search functionality

### Azure Bot
- **`ENABLE_AZURE_BOT`**: Enable Azure Bot Framework integration (default: `true`)

### Ethics
- **`ETHICAL_PRINCIPLE`**: Ethical guidelines for AI responses (default: `The model should only talk about ethical and legal things.`)

---

## Example Configuration File

Here's a minimal example `.env` file for the `env/` folder:

```env
# LLM API Keys
GOOGLE_API_KEY=your_google_api_key
OPENAI_API_KEY=your_openai_api_key
ANTHROPIC_API_KEY=your_anthropic_api_key
GROQ_API_KEY=your_groq_api_key

# Database
DBHOST=localhost
DBUSER=parrot_user
DBPWD=secure_password
DBNAME=parrot_db
DBPORT=5432

# Redis (from Navigator)
CACHE_HOST=localhost
CACHE_PORT=6379
REDIS_HISTORY_DB=3

# Vector Store (Milvus)
MILVUS_HOST=localhost
MILVUS_PORT=19530
MILVUS_USER=root
MILVUS_PASSWORD=milvus_password

# MS Teams Integration
MS_TEAMS_TENANT_ID=your-tenant-id
MS_TEAMS_CLIENT_ID=your-client-id
MS_TEAMS_CLIENT_SECRET=your-client-secret

# LLM Defaults
DEFAULT_LLM_MODEL=gemini-2.5-flash
LLM_TEMPERATURE=0.1

# Embeddings
EMBEDDING_DEVICE=cpu
EMBEDDING_DEFAULT_MODEL=sentence-transformers/all-MiniLM-L12-v2
```

---

## Notes

1. **Configuration Priority**: Values in environment files override default values in `conf.py`.

2. **Path Resolution**: File paths can be absolute or relative. Relative paths are resolved from `BASE_DIR`.

3. **Security**: Never commit `.env` files with sensitive credentials to version control.

4. **Dependencies**: Some features require specific configuration:
   - **JobManager & RQ**: Requires `CACHE_HOST` and `CACHE_PORT` for Redis
   - **MS Teams Toolkit**: Requires tenant ID, client ID, and either client secret (app-only) or username/password (delegated)
   - **Vector RAG**: Requires at least one vector database configured (PostgreSQL with PgVector, FAISS, Milvus, Qdrant, or ChromaDB)

5. **navconfig Integration**: Parrot uses `navconfig` for configuration management, which loads from `env/` folder by convention.
