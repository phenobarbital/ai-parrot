import sys
import os
import base64
from pathlib import Path
from navconfig import config, BASE_DIR
from navconfig.logging import logging


# # disable debug on some libraries:
# logging.getLogger(name='httpcore').setLevel(logging.INFO)
# logging.getLogger(name='httpx').setLevel(logging.INFO)
# logging.getLogger(name='groq').setLevel(logging.INFO)
# logging.getLogger(name='selenium.webdriver').setLevel(logging.WARNING)
# logging.getLogger(name='selenium').setLevel(logging.INFO)
# logging.getLogger(name='matplotlib').setLevel(logging.WARNING)
# logging.getLogger(name='PIL').setLevel(logging.INFO)
logging.getLogger("grpc").setLevel(logging.ERROR)
os.environ['GRPC_VERBOSITY'] = 'ERROR'
# Silence botocore/aiobotocore DEBUG noise (hook rewrites, event renames,
# HTTP request dumps). `interfaces/aws.py` does the same but imports later;
# setting it here kills the noise at the earliest possible moment.
logging.getLogger("botocore").setLevel(logging.INFO)
logging.getLogger("aiobotocore").setLevel(logging.INFO)
# Silence JAX/XLA compilation diagnostics when the app root logger runs at DEBUG.
logging.getLogger("jax").setLevel(logging.WARNING)
logging.getLogger("jaxlib").setLevel(logging.WARNING)
logging.getLogger("absl").setLevel(logging.WARNING)
# logging.getLogger("weasyprint").setLevel(logging.ERROR)  # Suppress WeasyPrint warnings
# # Suppress tiktoken warnings
# logging.getLogger("tiktoken").setLevel(logging.ERROR)
# logging.getLogger("fontTools").setLevel(logging.ERROR)

# Project Root:
PROJECT_ROOT = BASE_DIR
# Plugins Directory:
PLUGINS_DIR = config.get('PLUGINS_DIR', fallback=BASE_DIR.joinpath('plugins'))
if isinstance(PLUGINS_DIR, str):
    PLUGINS_DIR = Path(PLUGINS_DIR).resolve()
if not PLUGINS_DIR.exists():
    PLUGINS_DIR.mkdir(parents=True, exist_ok=True)

# Static directory
STATIC_DIR = config.get('STATIC_DIR', fallback=BASE_DIR.joinpath('static'))
if isinstance(STATIC_DIR, str):
    STATIC_DIR = Path(STATIC_DIR)

# Output directory (default base for tool-generated files)
OUTPUT_DIR = Path(
    config.get('OUTPUT_DIR', fallback=BASE_DIR.joinpath('outputs'))
)
if not OUTPUT_DIR.is_absolute():
    OUTPUT_DIR = BASE_DIR.joinpath(OUTPUT_DIR)
if not OUTPUT_DIR.exists():
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)


# Main Database:
# DB Default (database used for interaction (rw))
DBHOST = config.get('DBHOST', fallback='localhost')
DBUSER = config.get('DBUSER')
DBPWD = config.get('DBPWD')
DBNAME = config.get('DBNAME', fallback='navigator')
DBPORT = config.get('DBPORT', fallback=5432)
if DBUSER:
    _pwd = f":{DBPWD}" if DBPWD else ""
    default_dsn = f'postgres://{DBUSER}{_pwd}@{DBHOST}:{DBPORT}/{DBNAME}'
    async_default_dsn = f'postgresql+asyncpg://{DBUSER}{_pwd}@{DBHOST}:{DBPORT}/{DBNAME}'
    sqlalchemy_url = f'postgresql://{DBUSER}{_pwd}@{DBHOST}:{DBPORT}/{DBNAME}'
else:
    default_dsn = None
    async_default_dsn = None
    sqlalchemy_url = None

# Redis:
CACHE_HOST = config.get('CACHE_HOST', fallback='localhost')
CACHE_PORT = config.get('CACHE_PORT', fallback=6379)
CACHE_DB = config.get('CACHEDB', fallback=2)
CACHE_URL = f"redis://{CACHE_HOST}:{CACHE_PORT}/{CACHE_DB}"

REDIS_HOST = config.get('REDIS_HOST', fallback='localhost')
REDIS_PORT = config.get('REDIS_PORT', fallback=6379)
REDIS_DB = config.get('REDIS_DB', fallback=1)
REDIS_URL = f"redis://{REDIS_HOST}:{REDIS_PORT}/{REDIS_DB}"


# Environment
ENVIRONMENT = config.get("ENVIRONMENT", fallback="development")
ENABLE_SWAGGER = config.getboolean("ENABLE_SWAGGER", fallback=False)
ENABLE_DASHBOARDS = config.getboolean("ENABLE_DASHBOARDS", fallback=False)
ENABLE_CREWS = config.getboolean("ENABLE_CREWS", fallback=False)
ENABLE_DATABASE_BOTS = config.getboolean("ENABLE_DATABASE_BOTS", fallback=False)
ENABLE_REGISTRY_BOTS = config.getboolean("ENABLE_REGISTRY_BOTS", fallback=True)
# FEAT-249: enable the Redis structured-output transport (re-broadcasts
# structured outputs from any ai-parrot worker to the AgentChat UI over Redis).
# Renamed from ENABLE_LIVEAVATAR_VOICE (FEAT-243) — operators upgrading must
# rename the env var in their deployment config.
ENABLE_STRUCTURED_OUTPUT_TRANSPORT = config.getboolean(
    "ENABLE_STRUCTURED_OUTPUT_TRANSPORT", fallback=False
)

# Bot Model Table Configuration:
PARROT_BOTS_TABLE = config.get('PARROT_BOTS_TABLE', fallback='ai_bots')
PARROT_SCHEMA = config.get('PARROT_SCHEMA', fallback='navigator')


# Planogram images directory
PLANOGRAM_FOLDER = Path(
    config.get('PLANOGRAM_FOLDER', fallback=BASE_DIR.joinpath('images'))
)
if not PLANOGRAM_FOLDER.is_absolute():
    PLANOGRAM_FOLDER = BASE_DIR.joinpath(PLANOGRAM_FOLDER)

# ── Ontology Configuration ──
# Base directory for ontology YAML files (base + domains + clients).
ONTOLOGY_DIR = Path(
    config.get('ONTOLOGY_DIR', fallback=BASE_DIR.joinpath('ontologies'))
)
if isinstance(ONTOLOGY_DIR, str):
    ONTOLOGY_DIR = Path(ONTOLOGY_DIR).resolve()
if not ONTOLOGY_DIR.exists():
    ONTOLOGY_DIR.mkdir(parents=True, exist_ok=True)

# Base ontology filename — foundational layer all tenants inherit.
ONTOLOGY_BASE_FILE = config.get('ONTOLOGY_BASE_FILE', fallback='base.ontology.yaml')

# Subdirectory for domain-specific ontology extensions.
ONTOLOGY_DOMAINS_DIR = config.get('ONTOLOGY_DOMAINS_DIR', fallback='domains')

# Subdirectory for client-specific ontology overrides.
ONTOLOGY_CLIENTS_DIR = config.get('ONTOLOGY_CLIENTS_DIR', fallback='clients')

# Global on/off switch for ontology-based RAG.
ENABLE_ONTOLOGY_RAG = config.getboolean('ENABLE_ONTOLOGY_RAG', fallback=False)

# ArangoDB database naming template per tenant ({tenant} is replaced at runtime).
ONTOLOGY_DB_TEMPLATE = config.get('ONTOLOGY_DB_TEMPLATE', fallback='{tenant}_ontology')

# PgVector schema naming template per tenant.
ONTOLOGY_PGVECTOR_SCHEMA_TEMPLATE = config.get(
    'ONTOLOGY_PGVECTOR_SCHEMA_TEMPLATE', fallback='{tenant}'
)

# Redis key prefix for ontology traversal cache.
ONTOLOGY_CACHE_PREFIX = config.get('ONTOLOGY_CACHE_PREFIX', fallback='parrot:ontology')

# TTL for cached pipeline results in seconds (86400 = 24h, aligned with CRON refresh).
ONTOLOGY_CACHE_TTL = config.getint('ONTOLOGY_CACHE_TTL', fallback=86400)

# Maximum depth for dynamic AQL traversals generated by the LLM (security guardrail).
ONTOLOGY_MAX_TRAVERSAL_DEPTH = config.getint('ONTOLOGY_MAX_TRAVERSAL_DEPTH', fallback=4)

# LLM model for dynamic AQL generation and intent detection.
ONTOLOGY_AQL_MODEL = config.get('ONTOLOGY_AQL_MODEL', fallback='gemini-2.5-flash')

# Directory for review queue JSON files (ambiguous relation matches).
# Defaults to {ONTOLOGY_DIR}/review/ at runtime when None.
ONTOLOGY_REVIEW_DIR = config.get('ONTOLOGY_REVIEW_DIR', fallback=None)
if ONTOLOGY_REVIEW_DIR is not None:
    ONTOLOGY_REVIEW_DIR = Path(ONTOLOGY_REVIEW_DIR).resolve()

# Agents Directory
AGENTS_DIR = config.get('AGENTS_DIR', fallback=BASE_DIR.joinpath('agents'))
if isinstance(AGENTS_DIR, str):
    AGENTS_DIR = Path(AGENTS_DIR).resolve()
if not AGENTS_DIR.exists():
    AGENTS_DIR.mkdir(parents=True, exist_ok=True)

# Add AGENTS_DIR to sys.path for direct imports (e.g., from agents.troc import ...)
# Remove if already present to avoid duplicates, then insert at position 0
# This ensures AGENTS_DIR takes precedence over PLUGINS_DIR even if plugins/__init__.py
# has already inserted PLUGINS_DIR at position 0
agents_dir_str = str(AGENTS_DIR)
if agents_dir_str in sys.path:
    sys.path.remove(agents_dir_str)
sys.path.insert(0, agents_dir_str)


# MCP Server Directory:
MCP_SERVER_DIR = config.get(
    'MCP_SERVER_DIR',
    fallback=BASE_DIR.joinpath('mcp_servers')
)
if isinstance(MCP_SERVER_DIR, str):
    MCP_SERVER_DIR = Path(MCP_SERVER_DIR).resolve()
if not MCP_SERVER_DIR.exists():
    MCP_SERVER_DIR.mkdir(parents=True, exist_ok=True)

# Agent Context Directory (FEAT-181: per-agent context files for prompt caching)
# Each agent can have a Markdown context file at <AGENT_CONTEXT_DIR>/<agent_id>.md.
# AgentContextLoader reads and mtime-caches these files for injection into the
# CONFIGURE-phase prompt layer when prompt_caching=True.
# NOTE: The directory is NOT created here at import time to avoid side effects in
# read-only container filesystems and test environments. Creation is deferred to
# load_agent_context() in parrot/bots/prompts/agent_context.py.
AGENT_CONTEXT_DIR = config.get(
    'AGENT_CONTEXT_DIR',
    fallback=BASE_DIR.joinpath('agent_context')
)
if isinstance(AGENT_CONTEXT_DIR, str):
    AGENT_CONTEXT_DIR = Path(AGENT_CONTEXT_DIR).resolve()

# Docker file location (for generated docker-compose files, Dockerfiles, etc.)
DOCKER_FILE_LOCATION = config.get(
    'DOCKER_FILE_LOCATION',
    fallback=BASE_DIR.joinpath('docker')
)
if isinstance(DOCKER_FILE_LOCATION, str):
    DOCKER_FILE_LOCATION = Path(DOCKER_FILE_LOCATION).resolve()

# Per-bot cleanup timeout in seconds (FEAT-114 — bot-cleanup-lifecycle).
# Each bot's cleanup() coroutine is bounded by this value during aiohttp
# on_cleanup. A timeout is logged as a warning and does not block others.
BOT_CLEANUP_TIMEOUT = config.getint('BOT_CLEANUP_TIMEOUT', fallback=20)

# MCP Server defaults
MCP_SERVER_TRANSPORT = config.get('MCP_SERVER_TRANSPORT', fallback='http')
MCP_SERVER_HOST = config.get('MCP_SERVER_HOST', fallback='127.0.0.1')
MCP_SERVER_PORT = config.getint('MCP_SERVER_PORT', fallback=9090)
MCP_SERVER_NAME = config.get('MCP_SERVER_NAME', fallback='ai-parrot-tools')
MCP_SERVER_DESCRIPTION = config.get(
    'MCP_SERVER_DESCRIPTION',
    fallback='AI-Parrot MCP Tooling'
)
MCP_SERVER_LOG_LEVEL = config.get('MCP_SERVER_LOG_LEVEL', fallback='INFO')

# Default tools that should be started with the MCP server
MCP_STARTED_TOOLS = {
    # 'MSTeamsToolkit': 'parrot.tools.msteams',
    # 'PDFPrintTool': 'parrot.tools.pdfprint',
    'JiraToolkit': 'parrot.tools.jiratoolkit',
}

# Agents-Bots Prompt directory:
AGENTS_BOTS_PROMPT_DIR = config.get(
    'AGENTS_BOTS_PROMPT_DIR',
    fallback=AGENTS_DIR.joinpath('prompts')
)
if isinstance(AGENTS_BOTS_PROMPT_DIR, str):
    AGENTS_BOTS_PROMPT_DIR = Path(AGENTS_BOTS_PROMPT_DIR).resolve()
if not AGENTS_BOTS_PROMPT_DIR.exists():
    AGENTS_BOTS_PROMPT_DIR.mkdir(parents=True, exist_ok=True)

# LLM Model
DEFAULT_LLM_MODEL_NAME = config.get('LLM_MODEL_NAME', fallback='gemini-2.5-pro')


## MILVUS DB ##:
MILVUS_HOST = config.get('MILVUS_HOST', fallback='localhost')
MILVUS_PROTOCOL = config.get('MILVUS_PROTOCOL', fallback='http')
MILVUS_PORT = config.get('MILVUS_PORT', fallback=19530)
MILVUS_URL = config.get('MILVUS_URL')
MILVUS_TOKEN = config.get('MILVUS_TOKEN')
MILVUS_USER = config.get('MILVUS_USER')
MILVUS_PASSWORD = config.get('MILVUS_PASSWORD')
MILVUS_SECURE = config.getboolean('MILVUS_SECURE', fallback=False)
MILVUS_SERVER_NAME = config.get(
    'MILVUS_SERVER_NAME'
)
MILVUS_CA_CERT = config.get('MILVUS_CA_CERT', fallback=None)
MILVUS_SERVER_CERT = config.get('MILVUS_SERVER_CERT', fallback=None)
MILVUS_SERVER_KEY = config.get('MILVUS_SERVER_KEY', fallback=None)
MILVUS_USE_TLSv2 = config.getboolean('MILVUS_USE_TLSv2', fallback=False)

# Postgres Database:
DBHOST = config.get("DBHOST", fallback="localhost")
DBUSER = config.get("DBUSER")
DBPWD = config.get("DBPWD")
DBNAME = config.get("DBNAME", fallback="navigator")
DBPORT = config.get("DBPORT", fallback=5432)
# sqlalchemy+asyncpg connector:
if DBUSER:
    default_sqlalchemy_pg = f"postgresql+asyncpg://{DBUSER}:{DBPWD}@{DBHOST}:{DBPORT}/{DBNAME}"
else:
    default_sqlalchemy_pg = None

PG_USER = config.get('PG_USER', fallback=DBUSER)
PG_PWD = config.get('PG_PWD', fallback=DBPWD)
PG_HOST = config.get('PG_HOST', fallback=DBHOST)
PG_PORT = config.get('PG_PORT', fallback=DBPORT)
PG_DATABASE = config.get('PG_DATABASE', fallback=DBNAME)

# asyncpg url for sqlalchemy:
if PG_USER:
    asyncpg_sqlalchemy_url = f"postgresql+asyncpg://{PG_USER}:{PG_PWD}@{PG_HOST}:{PG_PORT}/{PG_DATABASE}"
else:
    asyncpg_sqlalchemy_url = None

# ScyllaDB Database:
SCYLLADB_DRIVER = config.get('SCYLLADB_DRIVER', fallback='scylladb')
SCYLLADB_HOST = config.get('SCYLLADB_HOST', fallback='localhost')
SCYLLADB_PORT = config.getint('SCYLLADB_PORT', fallback=9042)
SCYLLADB_USERNAME = config.get('SCYLLADB_USERNAME', fallback='navigator')
SCYLLADB_PASSWORD = config.get('SCYLLADB_PASSWORD', fallback='navigator')
SCYLLADB_KEYSPACE = config.get('SCYLLADB_KEYSPACE', fallback='navigator')


# BigQuery Configuration:
BIGQUERY_CREDENTIALS = config.get('BIGQUERY_CREDENTIALS')
BIGQUERY_PROJECT_ID = config.get('BIGQUERY_PROJECT_ID', fallback='navigator')
BIGQUERY_DATASET = config.get('BIGQUERY_DATASET', fallback='navigator')

# Redis History Configuration:
REDIS_HOST = config.get('REDIS_HOST', fallback='localhost')
REDIS_PORT = config.get('REDIS_PORT', fallback=6379)
REDIS_DB = config.get('REDIS_DB', fallback=1)
REDIS_URL = config.get('REDIS_URL', fallback=f"redis://{REDIS_HOST}:{REDIS_PORT}/{REDIS_DB}")

# Crew/flow execution result storage (FEAT-147)
CREW_RESULT_STORAGE = config.get('CREW_RESULT_STORAGE', fallback='documentdb')
CREW_RESULT_STORAGE_PG_DSN = config.get('CREW_RESULT_STORAGE_PG_DSN', fallback=default_dsn)
CREW_RESULT_STORAGE_REDIS_URL = config.get('CREW_RESULT_STORAGE_REDIS_URL', fallback=REDIS_URL)
CREW_RESULT_STORAGE_REDIS_TTL = int(config.get('CREW_RESULT_STORAGE_REDIS_TTL', fallback=604800))

REDIS_HISTORY_DB = config.get('REDIS_HISTORY_DB', fallback=3)
REDIS_HISTORY_URL = f"redis://{REDIS_HOST}:{REDIS_PORT}/{REDIS_HISTORY_DB}"
REDIS_SERVICES_URL = f"redis://{REDIS_HOST}:{REDIS_PORT}/4"
REDIS_DATASET_DB = config.get('REDIS_DATASET_DB', fallback=3)
REDIS_DATASET_URL = f"redis://{REDIS_HOST}:{REDIS_PORT}/{REDIS_DATASET_DB}"

def resolve_cert(crt):
    cert = Path(crt)
    if not cert.is_absolute():
        cert = BASE_DIR.joinpath(cert)
    else:
        cert.resolve()
    return cert

if MILVUS_SERVER_CERT:
    MILVUS_SERVER_CERT = str(resolve_cert(MILVUS_SERVER_CERT))
if MILVUS_CA_CERT:
    MILVUS_CA_CERT = str(resolve_cert(MILVUS_CA_CERT))
if MILVUS_SERVER_KEY:
    MILVUS_SERVER_KEY = str(resolve_cert(MILVUS_SERVER_KEY))

# QDRANT:
QDRANT_PROTOCOL = config.get('QDRANT_PROTOCOL', fallback='http')
QDRANT_HOST = config.get('QDRANT_HOST', fallback='localhost')
QDRANT_PORT = config.get('QDRANT_PORT', fallback=6333)
QDRANT_USE_HTTPS = config.getboolean('QDRANT_USE_HTTPS', fallback=False)
QDRANT_URL = config.get('QDRANT_URL')
# QDRANT Connection Type: server or cloud
QDRANT_CONN_TYPE = config.get('QDRANT_CONN_TYPE', fallback='server')

# ChromaDB:
CHROMADB_HOST = config.get('CHROMADB_HOST', fallback='localhost')
CHROMADB_PORT = config.get('CHROMADB_PORT', fallback=8000)

# Embedding Device:
EMBEDDING_DEVICE = config.get('EMBEDDING_DEVICE', fallback='cpu')
EMBEDDING_DEFAULT_MODEL = config.get(
    'EMBEDDING_DEFAULT_MODEL',
    fallback='sentence-transformers/all-mpnet-base-v2'
)
EMBEDDING_REGISTRY_MAX_MODELS = int(
    os.getenv('EMBEDDING_REGISTRY_MAX_MODELS', '10')
)
KB_DEFAULT_MODEL = config.get(
    'KB_DEFAULT_MODEL',
    fallback='sentence-transformers/paraphrase-MiniLM-L3-v2'
)
HUGGINGFACE_EMBEDDING_CACHE_DIR = config.get(
    'HUGGINGFACE_EMBEDDING_CACHE_DIR',
    fallback=BASE_DIR.joinpath('model_cache', 'huggingface')
)
# Propagate the app-level cache dir to the *standard* HuggingFace env var so
# the whole HF stack (huggingface_hub, transformers, sentence-transformers)
# downloads into this directory — not only the `cache_folder` kwarg we pass to
# SentenceTransformer. Without this, hub snapshots land in the user's default
# ~/.cache/huggingface/hub regardless of HUGGINGFACE_EMBEDDING_CACHE_DIR.
#
# IMPORTANT: huggingface_hub freezes HF_HUB_CACHE at import time, so this MUST
# run before any HF library is imported. conf.py loads early enough to satisfy
# that. `setdefault` lets an explicitly-set HF_HOME in the environment win.
os.environ.setdefault('HF_HOME', str(HUGGINGFACE_EMBEDDING_CACHE_DIR))
HUGGINGFACEHUB_API_TOKEN = config.get('HUGGINGFACEHUB_API_TOKEN')
MAX_VRAM_AVAILABLE = config.get('MAX_VRAM_AVAILABLE', fallback=20000)
RAM_AVAILABLE = config.get('RAM_AVAILABLE', fallback=819200)
CUDA_DEFAULT_DEVICE = config.get('CUDA_DEFAULT_DEVICE', fallback='cpu')
CUDA_DEFAULT_DEVICE_NUMBER = config.getint('CUDA_DEFAULT_DEVICE_NUMBER', fallback=0)
MAX_BATCH_SIZE = config.get('MAX_BATCH_SIZE', fallback=2048)

# Enable Teams Bot:
ENABLE_AZURE_BOT = config.getboolean('ENABLE_AZURE_BOT', fallback=True)

## Google Services:
GOOGLE_API_KEY = config.get('GOOGLE_API_KEY')
### Google Service Credentials:
GA_SERVICE_ACCOUNT_NAME = config.get('GA_SERVICE_ACCOUNT_NAME', fallback="google.json")
GA_SERVICE_PATH = config.get('GA_SERVICE_PATH', fallback="env/google/")
if isinstance(GA_SERVICE_PATH, str):
    GA_SERVICE_PATH = Path(GA_SERVICE_PATH)

GOOGLE_TTS_SERVICE = config.get(
    'GOOGLE_TTS_SERVICE',
    fallback=GA_SERVICE_PATH.joinpath('tts-service.json')
)
if isinstance(GOOGLE_TTS_SERVICE, str):
    GOOGLE_TTS_SERVICE = Path(GOOGLE_TTS_SERVICE)
if not GOOGLE_TTS_SERVICE.is_absolute():
    GOOGLE_TTS_SERVICE = BASE_DIR.joinpath(GOOGLE_TTS_SERVICE)
if not GOOGLE_TTS_SERVICE.exists():
    GOOGLE_TTS_SERVICE = None

# BASE STATIC:
BASE_STATIC_URL = config.get(
    'BASE_STATIC_URL',
    fallback='http://localhost:5000/static'
)

# Google SerpAPI:
SERPAPI_API_KEY = config.get('SERPAPI_API_KEY')

# Groq API Key:
GROQ_API_KEY = config.get('GROQ_API_KEY')
DEFAULT_GROQ_MODEL = config.get('DEFAULT_GROQ_MODEL', fallback='qwen/qwen3-32b')

# Ethical Principle:
ETHICAL_PRINCIPLE = config.get(
    'ETHICAL_PRINCIPLE',
    fallback='The model should only talk about ethical and legal things.'
)

# Embedding Configuration:

# VERTEX
VERTEX_PROJECT_ID = config.get('VERTEX_PROJECT_ID')
VERTEX_REGION = config.get('VERTEX_REGION')

# OpenAI:
OPENAI_API_KEY = config.get('OPENAI_API_KEY')
OPENAI_ORGANIZATION = config.get('OPENAI_ORGANIZATION')

## HTTPClioent
HTTPCLIENT_MAX_SEMAPHORE = config.getint("HTTPCLIENT_MAX_SEMAPHORE", fallback=5)
HTTPCLIENT_MAX_WORKERS = config.getint("HTTPCLIENT_MAX_WORKERS", fallback=1)

## Google API:
GOOGLE_API_KEY = config.get('GOOGLE_API_KEY')
GOOGLE_SEARCH_API_KEY = config.get('GOOGLE_SEARCH_API_KEY')
GOOGLE_SEARCH_ENGINE_ID = config.get('GOOGLE_SEARCH_ENGINE_ID')
GOOGLE_PLACES_API_KEY = config.get('GOOGLE_PLACES_API_KEY')
GOOGLE_CREDENTIALS_FILE = Path(
    config.get(
        'GOOGLE_CREDENTIALS_FILE',
        fallback=BASE_DIR.joinpath('env', 'google', 'key.json')
    )
)

## LLM default config:
from .models.google import GoogleModel
DEFAULT_LLM_MODEL = config.get(
    'LLM_MODEL', fallback=GoogleModel.GEMINI_FLASH_LATEST.value
)
DEFAULT_LLM_TEMPERATURE = config.get('LLM_TEMPERATURE', fallback=0.1)

"""
Amazon AWS Credentials
"""
aws_region = config.get("AWS_REGION", fallback="us-east-1")
aws_bucket = config.get("AWS_BUCKET", fallback="static-files")
aws_key = config.get("AWS_KEY")
aws_secret = config.get("AWS_SECRET")

AWS_ACCESS_KEY = config.get("AWS_ACCESS_KEY", fallback=aws_key)
AWS_SECRET_KEY = config.get("AWS_SECRET_KEY", fallback=aws_secret)
AWS_REGION_NAME = config.get("AWS_REGION_NAME", fallback=aws_region)
AWS_DEFAULT_CLOUDWATCH_LOG_GROUP = config.get(
    "AWS_DEFAULT_CLOUDWATCH_LOG_GROUP",
    fallback="/parrot/logs"
)
# ── Anthropic Bedrock-specific AWS settings ────────────────────────────────
# FEAT-232: Anthropic AWS Bedrock / AWS-workspace extras.
# AWS_SESSION_TOKEN — optional STS session token for temporary credentials.
# ANTHROPIC_AWS_WORKSPACE_ID — Claude-on-AWS workspace ID (SDK param: workspace_id).
# BEDROCK_AWS_REGION — Bedrock-specific region; avoids polluting from general
#   AWS_REGION_NAME used by other services (e.g., DynamoDB in eu-west-1).
#   When unset, boto3 resolves the region via instance-metadata / env chain.
AWS_SESSION_TOKEN = config.get("AWS_SESSION_TOKEN", fallback=None)
ANTHROPIC_AWS_WORKSPACE_ID = config.get("ANTHROPIC_AWS_WORKSPACE_ID", fallback=None)
BEDROCK_AWS_REGION = config.get("BEDROCK_AWS_REGION", fallback=None)

# Backend (DynamoDB) credentials — kept separate from the general AWS_ACCESS_KEY/
# AWS_SECRET_KEY so that the conversations/artifacts backend can run against a
# different AWS account/role than S3 and other services. See storage backend
# factory for the resolution order.
BACKEND_AWS_ACCESS_KEY = config.get("BACKEND_AWS_ACCESS_KEY", fallback=None)
BACKEND_AWS_SECRET_KEY = config.get("BACKEND_AWS_SECRET_KEY", fallback=None)
BACKEND_AWS_REGION = config.get("BACKEND_AWS_REGION", fallback=aws_region)

AWS_CREDENTIALS = {
    "default": {
        "use_credentials": config.get("aws_credentials", fallback=False),
        "aws_key": aws_key,
        "aws_secret": aws_secret,
        "region_name": aws_region,
        "bucket_name": aws_bucket,
    },
    "monitoring": {
        "use_credentials": config.get("aws_monitor_credentials", fallback=True),
        "aws_key": AWS_ACCESS_KEY,
        "aws_secret": AWS_SECRET_KEY,
        "region_name": AWS_REGION_NAME,
    },
    "cloudwatch": {
        "use_credentials": True,
        "aws_key": config.get("AWS_CLOUDWATCH_KEY"),
        "aws_secret": config.get("AWS_CLOUDWATCH_SECRET"),
        "region_name": config.get("AWS_CLOUDWATCH_REGION", fallback="us-east-1"),
    },
    "backend": {
        "use_credentials": bool(BACKEND_AWS_ACCESS_KEY and BACKEND_AWS_SECRET_KEY),
        "aws_key": BACKEND_AWS_ACCESS_KEY,
        "aws_secret": BACKEND_AWS_SECRET_KEY,
        "region_name": BACKEND_AWS_REGION,
    },
    "security": {
        "use_credentials": True,
        "aws_key": config.get("AWS_ACCESS_SECURITY_KEY_ID"),
        "aws_secret": config.get("AWS_SECRET_SECURITY_KEY"),
        "region_name": config.get("AWS_ACCESS_SECURITY_REGION", fallback="us-east-2"),
    },
    "security_bucket": {
        "use_credentials": True,
        "aws_key": config.get("AWS_ACCESS_SECURITY_KEY_ID"),
        "aws_secret": config.get("AWS_SECRET_SECURITY_KEY"),
        "region_name": config.get("AWS_SECURITY_REGION", fallback="us-east-2"),
        "bucket_name": config.get("AWS_SECURITY_BUCKET_NAME"),
    },
}

"""
DynamoDB & S3 Artifact Configuration (FEAT-103)
"""
DYNAMODB_CONVERSATIONS_TABLE = config.get(
    "DYNAMODB_CONVERSATIONS_TABLE", fallback="parrot-conversations"
)
DYNAMODB_ARTIFACTS_TABLE = config.get(
    "DYNAMODB_ARTIFACTS_TABLE", fallback="parrot-artifacts"
)
DYNAMODB_REGION = config.get("DYNAMODB_REGION", fallback=BACKEND_AWS_REGION)
DYNAMODB_ENDPOINT_URL = config.get("DYNAMODB_ENDPOINT_URL", fallback=None)
# Optional: name a profile in AWS_CREDENTIALS to use for DynamoDB. When unset,
# the backend factory falls back to BACKEND_AWS_* env vars, then to boto3's
# default credential chain (IAM role / ~/.aws/credentials).
DYNAMODB_AWS_PROFILE = config.get("DYNAMODB_AWS_PROFILE", fallback=None)
S3_ARTIFACT_BUCKET = config.get("S3_ARTIFACT_BUCKET", fallback=aws_bucket)

# --- Pluggable Storage Backends (FEAT-116) ---
# Default: sqlite — zero-dependency, works without AWS credentials or Docker.
# AWS production deployments must explicitly set PARROT_STORAGE_BACKEND=dynamodb.
_parrot_home_default = str(Path.home() / ".parrot")
PARROT_STORAGE_BACKEND = config.get("PARROT_STORAGE_BACKEND", fallback="sqlite")
PARROT_SQLITE_PATH = config.get(
    "PARROT_SQLITE_PATH",
    fallback=str(Path(_parrot_home_default) / "parrot.db"),
)
PARROT_POSTGRES_DSN = config.get("PARROT_POSTGRES_DSN", fallback=None)
PARROT_MONGODB_DSN = config.get("PARROT_MONGODB_DSN", fallback=None)
PARROT_OVERFLOW_STORE = config.get("PARROT_OVERFLOW_STORE", fallback=None)
PARROT_OVERFLOW_BUCKET = config.get("PARROT_OVERFLOW_BUCKET", fallback=None)
PARROT_OVERFLOW_LOCAL_PATH = config.get(
    "PARROT_OVERFLOW_LOCAL_PATH",
    fallback=str(Path(_parrot_home_default) / "artifacts"),
)
PARROT_STORAGE_METRICS = config.get("PARROT_STORAGE_METRICS", fallback=None)

## Tools:
OPENWEATHER_APPID = config.get('OPENWEATHER_APPID')

# NOTIFICATIONS:
TEAMS_NOTIFY_TENANT_ID = config.get("TEAMS_NOTIFY_TENANT_ID")
TEAMS_NOTIFY_CLIENT_ID = config.get("TEAMS_NOTIFY_CLIENT_ID")
TEAMS_NOTIFY_CLIENT_SECRET = config.get("TEAMS_NOTIFY_CLIENT_SECRET")
TEAMS_NOTIFY_USERNAME = config.get("TEAMS_NOTIFY_USERNAME")
TEAMS_NOTIFY_PASSWORD = config.get("TEAMS_NOTIFY_PASSWORD")
MS_TEAMS_DEFAULT_TEAMS_ID = config.get("MS_TEAMS_DEFAULT_TEAMS_ID")
MS_TEAMS_DEFAULT_CHANNEL_ID = config.get("MS_TEAMS_DEFAULT_CHANNEL_ID")

## MS Teams Toolkit:
MS_TEAMS_CLIENT_SECRET = config.get('MS_TEAMS_CLIENT_SECRET')
MS_TEAMS_CLIENT_ID = config.get('MS_TEAMS_CLIENT_ID')
MS_TEAMS_TENANT_ID = config.get('MS_TEAMS_TENANT_ID')
MS_TEAMS_USERNAME = config.get('TEAMS_NOTIFY_USERNAME')
MS_TEAMS_PASSWORD = config.get('TEAMS_NOTIFY_PASSWORD')

## Office 365:
O365_CLIENT_ID = config.get('O365_CLIENT_ID')
O365_CLIENT_SECRET = config.get('O365_CLIENT_SECRET')
O365_TENANT_ID = config.get('O365_TENANT_ID')
# Delegated OAuth2 (3LO) for the Office365Toolkit / OperatorAgent flow.
O365_REDIRECT_URI = config.get(
    'O365_REDIRECT_URI',
    fallback='http://localhost:5000/api/auth/oauth2/o365/callback',
)
OAUTH2_REDIS_URL = config.get(
    'OAUTH2_REDIS_URL',
    fallback='redis://localhost:6379/4',
)

# Sharepoint:
SHAREPOINT_APP_ID = config.get('SHAREPOINT_APP_ID')
SHAREPOINT_APP_SECRET = config.get('SHAREPOINT_APP_SECRET')
SHAREPOINT_TENANT_ID = config.get('SHAREPOINT_TENANT_ID')
SHAREPOINT_TENANT_NAME = config.get('SHAREPOINT_TENANT_NAME')
SHAREPOINT_SITE_ID = config.get('SHAREPOINT_SITE_ID')
SHAREPOINT_DEFAULT_HOST = config.get('SHAREPOINT_DEFAULT_HOST')

# Employee Hierarchy Configuration:
EMPLOYEES_TABLE = config.get('EMPLOYEES_TABLE', fallback='troc.troc_employees')

# Workday SOAP settings
WORKDAY_DEFAULT_TENANT = config.get('WORKDAY_DEFAULT_TENANT', fallback='nav')
WORKDAY_CLIENT_ID = config.get("WORKDAY_CLIENT_ID")
WORKDAY_CLIENT_SECRET = config.get("WORKDAY_CLIENT_SECRET")
WORKDAY_TOKEN_URL = config.get("WORKDAY_TOKEN_URL")
WORKDAY_WSDL_PATH = config.get(
    "WORKDAY_WSDL_PATH",
    fallback=BASE_DIR.joinpath("env", "workday", "staffing_custom_44_2.wsdl")
)
WORKDAY_WSDL_TIME = config.get(
    "WORKDAY_WSDL_TIME",
    fallback=BASE_DIR.joinpath("env", "workday", "timetracking_custom_44_2.wsdl")
)
WORKDAY_WSDL_HUMAN_RESOURCES = config.get(
    "WORKDAY_WSDL_HUMAN_RESOURCES",
    fallback=BASE_DIR.joinpath("env", "workday", "humanresources_troc_44_2.wsdl")
)
WORKDAY_WSDL_FINANCIAL_MANAGEMENT = config.get(
    "WORKDAY_WSDL_FINANCIAL_MANAGEMENT",
    fallback=BASE_DIR.joinpath("env", "workday", "financial_management_45.wsdl")
)
WORKDAY_WSDL_RECRUITING = config.get(
    "WORKDAY_WSDL_RECRUITING",
    fallback=BASE_DIR.joinpath("env", "workday", "recruiting_44_2.wsdl")
)
WORKDAY_WSDL_ABSENCE_MANAGEMENT = config.get(
    "WORKDAY_WSDL_ABSENCE_MANAGEMENT",
    fallback=BASE_DIR.joinpath("env", "workday", "absence_management_45_custom.wsdl")
)
WORKDAY_WSDL_PAYROLL = config.get(
    "WORKDAY_WSDL_PAYROLL",
    fallback=BASE_DIR.joinpath("env", "workday", "payroll_v45_2.wsdl")
)
WORKDAY_WSDL_INTEGRATIONS = config.get(
    "WORKDAY_WSDL_INTEGRATIONS",
    fallback=BASE_DIR.joinpath("env", "workday", "integrations_45.wsdl")
)
WORKDAY_WSDL_CUSTOM_PUNCH_FIELD_REPORT = config.get(
    "WORKDAY_WSDL_CUSTOM_PUNCH_FIELD_REPORT",
    fallback=BASE_DIR.joinpath("env", "workday", "custom_punch_field_report_nav.wsdl")
)
WORKDAY_WSDL_TIME_BLOCK_REPORT = config.get(
    "WORKDAY_WSDL_TIME_BLOCK_REPORT",
    fallback=BASE_DIR.joinpath("env", "workday", "extract_time_blocks_navigator.wsdl")
)
WORKDAY_REFRESH_TOKEN = config.get("WORKDAY_REFRESH_TOKEN", fallback=None)
WORKDAY_REPORT_USERNAME = config.get("WORKDAY_REPORT_USERNAME", fallback=None)
WORKDAY_REPORT_PASSWORD = config.get("WORKDAY_REPORT_PASSWORD", fallback=None)
WORKDAY_REPORT_PASSWORD_BASE64 = config.get("WORKDAY_REPORT_PASSWORD_BASE64", fallback=None)
if WORKDAY_REPORT_PASSWORD_BASE64 and not WORKDAY_REPORT_PASSWORD:
    WORKDAY_REPORT_PASSWORD = base64.b64decode(WORKDAY_REPORT_PASSWORD_BASE64).decode("utf-8")
WORKDAY_REPORT_OWNER = config.get("WORKDAY_REPORT_OWNER", fallback=None)
WORKDAY_URL = config.get("WORKDAY_URL", fallback="https://services1.wd501.myworkday.com")

WORKDAY_WSDL_PATHS = {
    "human_resources": WORKDAY_WSDL_HUMAN_RESOURCES,
    "absence_management": WORKDAY_WSDL_ABSENCE_MANAGEMENT,
    "time_tracking": WORKDAY_WSDL_TIME,
    "staffing": WORKDAY_WSDL_PATH,
    "financial_management": WORKDAY_WSDL_FINANCIAL_MANAGEMENT,
    "recruiting": WORKDAY_WSDL_RECRUITING,
    "payroll": WORKDAY_WSDL_PAYROLL
}

# NetSuite MCP settings (OAuth2 Client Credentials M2M + certificate)
NETSUITE_ACCOUNT_ID = config.get("NETSUITE_ACCOUNT_ID")
NETSUITE_CLIENT_ID = config.get("NETSUITE_CLIENT_ID")
NETSUITE_CERTIFICATE_ID = config.get("NETSUITE_CERTIFICATE_ID")
NETSUITE_PRIVATE_KEY_PATH = config.get("NETSUITE_PRIVATE_KEY_PATH")

# Final sys.path adjustment: Ensure AGENTS_DIR takes precedence over PLUGINS_DIR
# This is necessary because parrot.plugins.__init__.py may have inserted PLUGINS_DIR
# at position 0 during module loading (after our initial AGENTS_DIR insertion above)
if agents_dir_str in sys.path:
    sys.path.remove(agents_dir_str)
sys.path.insert(0, agents_dir_str)


# WhatsApp Bridge:
WHATSAPP_BRIDGE_ENABLED = config.get(
    'WHATSAPP_BRIDGE_ENABLED',
    fallback=True
)
WHATSAPP_BRIDGE_URL = config.get(
    'WHATSAPP_BRIDGE_URL',
    fallback='http://localhost:8765'
)
WHATSAPP_ALLOWED_PHONES = config.get(
    'WHATSAPP_ALLOWED_PHONES',
    fallback=None  # None = allow all
)
WHATSAPP_ALLOWED_GROUPS = config.get(
    'WHATSAPP_ALLOWED_GROUPS',
    fallback=None  # None = allow all
)
WHATSAPP_COMMAND_PREFIX = config.get(
    'WHATSAPP_COMMAND_PREFIX',
    fallback=''  # Empty = no prefix required
)

JIRA_USERS = [
    {
        "id": "35",
        "name": "Jesus Lara",
        "jira_username": "jesuslarag@gmail.com",
        "telegram_chat_id": "286137732",
        "manager_chat_id": "286137732",
        "username": "jlara@trocglobal.com"
    }
]
JIRA_CLIENT_ID = config.get("JIRA_CLIENT_ID")
JIRA_CLIENT_SECRET = config.get("JIRA_CLIENT_SECRET")
JIRA_REDIRECT_URI = config.get("JIRA_REDIRECT_URI")
JIRA_OAUTH_REDIS_URL = config.get("JIRA_OAUTH_REDIS_URL", fallback="redis://localhost:6379/4")
# OAuth2 web-channel origin allowlist — comma-separated string or list.
# Used by IntegrationsHandler and jira_oauth_callback to validate that the
# popup's window.opener.postMessage target origin is trusted.
WEB_OAUTH_ALLOWED_ORIGINS = config.get("WEB_OAUTH_ALLOWED_ORIGINS", fallback=[])
if isinstance(WEB_OAUTH_ALLOWED_ORIGINS, str):
    WEB_OAUTH_ALLOWED_ORIGINS = [
        o.strip() for o in WEB_OAUTH_ALLOWED_ORIGINS.split(",") if o.strip()
    ]
JIRA_ALLOWED_REPORTERS: list[str] = config.getlist(
    "JIRA_ALLOWED_REPORTERS",
    fallback=[],
) or ["jesuslarag@gmail.com"]
JIRA_DEFAULT_REPORTER: str | None = config.get(
    "JIRA_DEFAULT_REPORTER",
    fallback="jesuslarag@gmail.com",
)

# ── GitHub Reviewer Agent ──
# Comma-separated list of Telegram chat IDs notified when a PR review finds
# discrepancies against the linked Jira ticket. Integers only.
_raw_pr_chat_ids = config.getlist(
    "GITHUB_REVIEW_TELEGRAM_CHAT_IDS", fallback=[]
) or []
GITHUB_REVIEW_TELEGRAM_CHAT_IDS: list[int] = []
for _chat_id in _raw_pr_chat_ids:
    try:
        GITHUB_REVIEW_TELEGRAM_CHAT_IDS.append(int(str(_chat_id).strip()))
    except (TypeError, ValueError):
        continue
# Telegram chat / channel ID receiving the daily stale-PR summary. Accepts
# either a numeric chat_id (e.g. -1001234567890) or a public @username.
GITHUB_REVIEW_PUBLIC_CHANNEL_ID: str | None = config.get(
    "GITHUB_REVIEW_PUBLIC_CHANNEL_ID", fallback=None
)
# Shared secret used by GitHub to sign webhook deliveries. Required when
# HMAC verification is enabled on the GitHubWebhookHook.
GITHUB_REVIEW_WEBHOOK_SECRET: str | None = config.get(
    "GITHUB_REVIEW_WEBHOOK_SECRET", fallback=None
)
# Public HTTPS URL of the GitHubWebhookHook endpoint, used by the agent to
# auto-subscribe via the GitHub API when the PAT has admin:repo_hook scope.
GITHUB_REVIEW_WEBHOOK_PUBLIC_URL: str | None = config.get(
    "GITHUB_REVIEW_WEBHOOK_PUBLIC_URL", fallback=None
)
# Default GitHub repository in 'owner/name' format watched by the default
# GitHubReviewer subclass. Multiple repositories = multiple subclasses.
GITHUB_REVIEW_REPOSITORY: str | None = config.get(
    "GITHUB_REVIEW_REPOSITORY", fallback=None
)
# Hours an open PR must remain unattended before the daily report announces
# it to the public Telegram channel.
GITHUB_REVIEW_STALE_AFTER_HOURS: int = config.getint(
    "GITHUB_REVIEW_STALE_AFTER_HOURS", fallback=24
)
# Jira project key whose tickets the watched repository references. Drives
# the `<PROJECT>-\d+` regex that extracts ticket keys from PR titles/bodies.
GITHUB_REVIEW_JIRA_PROJECT: str = config.get(
    "GITHUB_REVIEW_JIRA_PROJECT", fallback="NAV"
)
# Per-prompt clamp on the diff fed to the reviewer LLM. Larger diffs are
# truncated and the prompt notes the truncation so the model accounts for it.
GITHUB_REVIEW_MAX_DIFF_BYTES: int = config.getint(
    "GITHUB_REVIEW_MAX_DIFF_BYTES", fallback=50_000
)
# Per-field clamp on the Jira description and acceptance-criteria text
# spliced into the LLM prompt. Prevents a single oversized ticket from
# blowing the model's context window.
GITHUB_REVIEW_MAX_TICKET_BYTES: int = config.getint(
    "GITHUB_REVIEW_MAX_TICKET_BYTES", fallback=20_000
)

# Number of past weeks to consider when computing "silent contributors".
GITHUB_REVIEW_WEEKLY_LOOKBACK_WEEKS: int = config.getint(
    "GITHUB_REVIEW_WEEKLY_LOOKBACK_WEEKS", fallback=4
)
# A contributor with zero commits across this many consecutive recent
# weeks is flagged in the weekly activity report as silent.
GITHUB_REVIEW_SILENT_WEEKS_THRESHOLD: int = config.getint(
    "GITHUB_REVIEW_SILENT_WEEKS_THRESHOLD", fallback=3
)
# When True, the weekly report prose is generated by the agent's LLM.
# Numbers always come from the structured summary; only the wording varies.
# Falls back to the templated body on any LLM failure.
GITHUB_REVIEW_USE_LLM_SUMMARY: bool = config.getboolean(
    "GITHUB_REVIEW_USE_LLM_SUMMARY", fallback=False
)

## Vector Store Handler:
VECTOR_HANDLER_MAX_FILE_SIZE = config.getint(
    'VECTOR_HANDLER_MAX_FILE_SIZE',
    fallback=25 * 1024 * 1024  # 25MB
)

## Infographic Render Endpoint (FEAT-327): template source directories for
## the server-owned, bot-less InfographicToolkit used by
## POST /api/v1/agents/infographic/render (data-splice/jinja HTML sources —
## NOT the block-spec metadata registry `parrot.helpers.infographics` uses
## for the pre-render 404 check; the two are intentionally separate
## registries, see docs/api/infographic_render.md's Known Limitation).
## Comma-separated list of directories; empty by default — the render
## route logs a loud warning and every render request fails with
## TEMPLATE_ENGINE_UNSET until this is configured for a deployment.
INFOGRAPHIC_RENDER_TEMPLATE_DIRS: list[str] = config.getlist(
    "INFOGRAPHIC_RENDER_TEMPLATE_DIRS", fallback=[]
)

## Security:
AWS_ACCESS_KEY_ID = config.get("AWS_ACCESS_KEY_ID", fallback=AWS_ACCESS_KEY)
AWS_SECRET_ACCESS_KEY = config.get("AWS_SECRET_ACCESS_KEY", fallback=AWS_SECRET_KEY)
AWS_DEFAULT_REGION = config.get("AWS_DEFAULT_REGION", fallback=AWS_REGION_NAME)

# ── Odoo ERP (JSON-RPC 2.0) ──
ODOO_URL = config.get("ODOO_URL", fallback=None)
ODOO_DATABASE = config.get("ODOO_DATABASE", fallback=None)
ODOO_USERNAME = config.get("ODOO_USERNAME", fallback=None)
ODOO_PASSWORD = config.get("ODOO_PASSWORD", fallback=None)
ODOO_TIMEOUT = config.getint("ODOO_TIMEOUT", fallback=30)
ODOO_VERIFY_SSL = config.getboolean("ODOO_VERIFY_SSL", fallback=True)

# ── Zammad Helpdesk (REST API v1) ──
ZAMMAD_INSTANCE = config.get("ZAMMAD_INSTANCE", fallback=None)
ZAMMAD_TOKEN = config.get("ZAMMAD_TOKEN", fallback=None)
ZAMMAD_DEFAULT_CUSTOMER = config.get("ZAMMAD_DEFAULT_CUSTOMER", fallback=None)
ZAMMAD_DEFAULT_GROUP = config.get("ZAMMAD_DEFAULT_GROUP", fallback=None)
ZAMMAD_DEFAULT_CATALOG = config.get("ZAMMAD_DEFAULT_CATALOG", fallback=None)
ZAMMAD_ORGANIZATION = config.get("ZAMMAD_ORGANIZATION", fallback=None)
ZAMMAD_DEFAULT_ROLE = config.get("ZAMMAD_DEFAULT_ROLE", fallback="Customer")

# ── Dev-Loop Orchestration (FEAT-129) ──
# Two-level concurrency control: dispatcher-side and orchestrator-side caps.
CLAUDE_CODE_MAX_CONCURRENT_DISPATCHES: int = config.getint(
    "CLAUDE_CODE_MAX_CONCURRENT_DISPATCHES", fallback=3
)
FLOW_MAX_CONCURRENT_RUNS: int = config.getint(
    "FLOW_MAX_CONCURRENT_RUNS", fallback=5
)
# Service-account Jira accountId used by the dev-loop bot when posting
# comments / attachments / transitions. Empty string by default; downstream
# code MUST tolerate the empty default (no error at import time).
FLOW_BOT_JIRA_ACCOUNT_ID: str = config.get(
    "FLOW_BOT_JIRA_ACCOUNT_ID", fallback=""
)
# Absolute path under which feature worktrees are created.
# Defaults to BASE_DIR/.claude/worktrees so the location is deterministic
# regardless of the process's launch directory (FEAT-253 G1).
# A relative value from the environment is joined onto BASE_DIR;
# an absolute value is honored verbatim (R1 backward-compat).
_wt: str = config.get(
    "WORKTREE_BASE_PATH", fallback=str(BASE_DIR / ".claude/worktrees")
)
WORKTREE_BASE_PATH: str = (
    os.path.normpath(_wt) if os.path.isabs(_wt)
    else os.path.normpath(str(BASE_DIR / _wt))
)
# Redis stream retention for both flow and dispatch streams (default 7 days).
FLOW_STREAM_TTL_SECONDS: int = config.getint(
    "FLOW_STREAM_TTL_SECONDS", fallback=604800
)
# Allow-list of command heads acceptable in ShellCriterion.command. The
# default covers the four lint/test command heads documented in the spec.
ACCEPTANCE_CRITERION_ALLOWLIST: list[str] = config.getlist(
    "ACCEPTANCE_CRITERION_ALLOWLIST",
    fallback=["task", "flowtask", "pytest", "ruff", "mypy", "pylint"],
) or ["task", "flowtask", "pytest", "ruff", "mypy", "pylint"]
# Plan-summary LLM override (FEAT-132). Empty string means "fall back to
# DEV_LOOP_SUMMARY_LLM" — see _plan_llm_default() in nodes/research.py.
# Set to any LLMFactory-compatible model string to pin a separate model
# for plan-summary generation without affecting log summarisation.
DEV_LOOP_PLAN_LLM: str = config.get(
    "DEV_LOOP_PLAN_LLM", fallback=""
)
# Repositories the dev-loop run clones/pulls before Development (FEAT-250).
# Raw value parsed into RepoSpec objects by the flow config — NOT here (conf.py
# must not import dev_loop). Each entry may be an "owner/name" slug or a JSON
# object string; an empty list disables repo provisioning.
DEV_LOOP_REPOS: list[str] = config.getlist("DEV_LOOP_REPOS", fallback=[]) or []
# Absolute path for dev-loop clones (FEAT-253 G1).
# Defaults to BASE_DIR/.claude/worktrees/repos (under WORKTREE_BASE_PATH) so
# the dispatcher's cwd-safety guard (_enforce_cwd_under_worktree_base) passes.
# Same relative→join / absolute→verbatim rule as WORKTREE_BASE_PATH.
_repos: str = config.get(
    "DEV_LOOP_REPO_BASE_PATH",
    fallback=str(BASE_DIR / ".claude/worktrees/repos"),
)
DEV_LOOP_REPO_BASE_PATH: str = (
    os.path.normpath(_repos) if os.path.isabs(_repos)
    else os.path.normpath(str(BASE_DIR / _repos))
)
# What kind of PR feedback triggers a revision-mode run (FEAT-250):
#   "changes_requested" (default) — human, non-bot, change-requesting reviews,
#   "any_comment" — any non-bot human comment,
#   "command" — only comments with the /revise prefix.
DEV_LOOP_REVISION_TRIGGER: str = config.get(
    "DEV_LOOP_REVISION_TRIGGER", fallback="changes_requested"
)
# Model used by the additive sdd-codereview QA gate (FEAT-250).
DEV_LOOP_CODEREVIEW_MODEL: str = config.get(
    "DEV_LOOP_CODEREVIEW_MODEL", fallback="claude-sonnet-4-6"
)
# Which code-review dispatcher backs the QA node's code-review gate
# (FEAT-270): "claude-code" (default), "codex", or "gemini". Selected via
# ``CodeReviewDispatcherFactory.create()`` at server startup.
DEV_LOOP_CODEREVIEW_AGENT: str = config.get(
    "DEV_LOOP_CODEREVIEW_AGENT", fallback="claude-code"
)

# Jira transition labels the dev-loop applies at each hand-off point. Every
# Jira project ships its own workflow, so each setting is an *ordered list of
# candidate labels* (most specific first); the dev-loop tries them against the
# issue's live available-transitions and applies the first that resolves. This
# keeps the flow working across projects with no config, while letting an
# operator pin exact labels via env when the defaults don't cover their
# workflow. Matching is alias/substring-tolerant (jira_transition_issue).
DEV_LOOP_JIRA_TRANSITIONS_READY: list[str] = config.getlist(
    "DEV_LOOP_JIRA_TRANSITIONS_READY",
    fallback=["Ready to Deploy", "Resolve Issue", "Resolved", "Done", "Close Issue", "Closed"],
) or ["Ready to Deploy", "Resolve Issue", "Resolved", "Done", "Close Issue", "Closed"]
DEV_LOOP_JIRA_TRANSITIONS_BLOCKED: list[str] = config.getlist(
    "DEV_LOOP_JIRA_TRANSITIONS_BLOCKED",
    fallback=["Deployment Blocked", "Blocked", "Blocked for Requirements", "On Hold", "Stop Progress"],
) or ["Deployment Blocked", "Blocked", "Blocked for Requirements", "On Hold", "Stop Progress"]
DEV_LOOP_JIRA_TRANSITIONS_REVISION: list[str] = config.getlist(
    "DEV_LOOP_JIRA_TRANSITIONS_REVISION",
    fallback=["In Review – revised", "In Review", "Resolve Issue", "In Progress", "Reopen"],
) or ["In Review – revised", "In Review", "Resolve Issue", "In Progress", "Reopen"]

# AHP-style session state / HITL approval gates (FEAT-322). Per-kind gate
# TTLs in seconds (read via ``runner.gate_ttl_for(kind)`` — conf stays out
# of the transport-free ``session_state`` module); per-gate overrides are
# still possible via ``SessionHost.open_gate(ttl_seconds=...)``. Defaults
# match the brainstorm-resolved policy (spec §8): deployment/manual/revision
# gates are fail-closed (long TTL, escalate on expiry); plan_approval is
# fail-open (short TTL, auto-approved by "system:ttl-auto-approve").
DEV_LOOP_GATE_TTL_DEPLOYMENT: int = config.getint(
    "DEV_LOOP_GATE_TTL_DEPLOYMENT", fallback=86400  # 24h, fail-closed
)
DEV_LOOP_GATE_TTL_MANUAL: int = config.getint(
    "DEV_LOOP_GATE_TTL_MANUAL", fallback=259200  # 72h, fail-closed
)
DEV_LOOP_GATE_TTL_REVISION: int = config.getint(
    "DEV_LOOP_GATE_TTL_REVISION", fallback=86400  # 24h, fail-closed
)
DEV_LOOP_GATE_TTL_PLAN: int = config.getint(
    "DEV_LOOP_GATE_TTL_PLAN", fallback=14400  # 4h, fail-open
)
# Retention window for the operational ``flow:{run_id}:actions`` stream
# (XADD MAXLEN ~100000 during the run); the terminal Snapshot is the
# durable audit record — the stream itself is swept after this many days.
DEV_LOOP_ACTIONS_RETENTION_DAYS: int = config.getint(
    "DEV_LOOP_ACTIONS_RETENTION_DAYS", fallback=7
)

# ---------------------------------------------------------------------------
# Remote Tool Executors (parrot.tools.executors)
# ---------------------------------------------------------------------------
# Qworker service — used by QworkerToolExecutor(transport="http").
QWORKER_URL: str = config.get("QWORKER_URL", fallback="")
QWORKER_API_TOKEN: str = config.get("QWORKER_API_TOKEN", fallback="")
QWORKER_TIMEOUT: int = config.getint("QWORKER_TIMEOUT", fallback=300)

# Kubernetes — used by K8sToolExecutor. K8S_KUBECONFIG_PATH defaults
# to None so the executor falls back to in-cluster config when set,
# then to ~/.kube/config.
K8S_KUBECONFIG_PATH: str = config.get("K8S_KUBECONFIG_PATH", fallback="") or None
K8S_NAMESPACE: str = config.get("K8S_NAMESPACE", fallback="parrot-tools")
K8S_TOOL_IMAGE: str = config.get("K8S_TOOL_IMAGE", fallback="parrot-tools:latest")
K8S_JOB_TTL_SECONDS: int = config.getint("K8S_JOB_TTL_SECONDS", fallback=60)

# Docker — used by DockerToolExecutor. DOCKER_HOST empty means the
# client auto-detects (DOCKER_HOST env var, then the default unix
# socket). DOCKER_TOOL_IMAGE shares the worker image with the K8s
# executor. Mode "warm" reuses one container across calls; "ephemeral"
# creates one per call.
DOCKER_HOST: str = config.get("DOCKER_HOST", fallback="")
DOCKER_TOOL_IMAGE: str = config.get("DOCKER_TOOL_IMAGE", fallback="parrot-tools:latest")
DOCKER_EXECUTOR_MODE: str = config.get("DOCKER_EXECUTOR_MODE", fallback="warm")
DOCKER_IDLE_TTL_SECONDS: int = config.getint("DOCKER_IDLE_TTL_SECONDS", fallback=300)
DOCKER_NETWORK_MODE: str = config.get("DOCKER_NETWORK_MODE", fallback="bridge")

# Base URL the worker posts opt-in webhook deliveries to. Empty string
# disables async delivery.
TOOL_EXECUTOR_WEBHOOK_BASE_URL: str = config.get(
    "TOOL_EXECUTOR_WEBHOOK_BASE_URL", fallback=""
)
