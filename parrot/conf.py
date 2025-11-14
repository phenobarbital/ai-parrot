from pathlib import Path
from navconfig import config, BASE_DIR
from navconfig.logging import logging
from navigator.conf import default_dsn, CACHE_HOST, CACHE_PORT


# disable debug on some libraries:
logging.getLogger(name='httpcore').setLevel(logging.INFO)
logging.getLogger(name='httpx').setLevel(logging.INFO)
logging.getLogger(name='groq').setLevel(logging.INFO)
logging.getLogger(name='selenium.webdriver').setLevel(logging.WARNING)
logging.getLogger(name='selenium').setLevel(logging.INFO)
logging.getLogger(name='matplotlib').setLevel(logging.WARNING)
logging.getLogger(name='PIL').setLevel(logging.INFO)
logging.getLogger("grpc").setLevel(logging.CRITICAL)
logging.getLogger("weasyprint").setLevel(logging.ERROR)  # Suppress WeasyPrint warnings
# Suppress tiktoken warnings
logging.getLogger("tiktoken").setLevel(logging.ERROR)
logging.getLogger("fontTools").setLevel(logging.ERROR)

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


# Environment
ENVIRONMENT = config.get("ENVIRONMENT", fallback="development")
ENABLE_SWAGGER = config.getboolean("ENABLE_SWAGGER", fallback=True)


# Agents Directory
AGENTS_DIR = config.get('AGENTS_DIR', fallback=BASE_DIR.joinpath('agents'))
if isinstance(AGENTS_DIR, str):
    AGENTS_DIR = Path(AGENTS_DIR).resolve()
if not AGENTS_DIR.exists():
    AGENTS_DIR.mkdir(parents=True, exist_ok=True)


# MCP Server Directory:
MCP_SERVER_DIR = config.get(
    'MCP_SERVER_DIR',
    fallback=BASE_DIR.joinpath('mcp_servers')
)
if isinstance(MCP_SERVER_DIR, str):
    MCP_SERVER_DIR = Path(MCP_SERVER_DIR).resolve()
if not MCP_SERVER_DIR.exists():
    MCP_SERVER_DIR.mkdir(parents=True, exist_ok=True)

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
    'MSTeamsToolkit': 'parrot.tools.msteams',
    'PDFPrintTool': 'parrot.tools.pdfprint',
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
default_sqlalchemy_pg = f"postgresql+asyncpg://{DBUSER}:{DBPWD}@{DBHOST}:{DBPORT}/{DBNAME}"

# ScyllaDB Database:
SCYLLADB_DRIVER = config.get('SCYLLADB_DRIVER', fallback='scylladb')
SCYLLADB_HOST = config.get('SCYLLADB_HOST', fallback='localhost')
SCYLLADB_PORT = int(config.get('SCYLLADB_PORT', fallback=9042))
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
REDIS_HISTORY_DB = config.get('REDIS_HISTORY_DB', fallback=3)
REDIS_HISTORY_URL = f"redis://{REDIS_HOST}:{REDIS_PORT}/{REDIS_HISTORY_DB}"
REDIS_SERVICES_URL = f"redis://{REDIS_HOST}:{REDIS_PORT}/4"

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
    fallback='sentence-transformers/all-MiniLM-L12-v2'
)
KB_DEFAULT_MODEL = config.get(
    'KB_DEFAULT_MODEL',
    fallback='sentence-transformers/paraphrase-MiniLM-L3-v2'
)
HUGGINGFACE_EMBEDDING_CACHE_DIR = config.get(
    'HUGGINGFACE_EMBEDDING_CACHE_DIR',
    fallback=BASE_DIR.joinpath('model_cache', 'huggingface')
)
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
DEFAULT_LLM_MODEL = config.get('LLM_MODEL', fallback='gemini-2.5-flash')
DEFAULT_LLM_TEMPERATURE = config.get('LLM_TEMPERATURE', fallback=0.1)

"""
Amazon AWS Credentials
"""
aws_region = config.get("AWS_REGION", fallback="us-east-1")
aws_bucket = config.get("AWS_BUCKET", fallback="static-files")
aws_key = config.get("AWS_KEY")
aws_secret = config.get("AWS_SECRET")

AWS_CREDENTIALS = {
    "default": {
        "use_credentials": config.get("aws_credentials", fallback=False),
        "aws_key": aws_key,
        "aws_secret": aws_secret,
        "region_name": aws_region,
        "bucket_name": aws_bucket,
    },
}

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
    fallback=BASE_DIR.joinpath("env", "workday", "absense_management_45_custom.wsdl")
)
WORKDAY_REFRESH_TOKEN = config.get("WORKDAY_REFRESH_TOKEN", fallback=None)
