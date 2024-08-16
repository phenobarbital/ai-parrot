from pathlib import Path
from navconfig import config, BASE_DIR
from navconfig.logging import logging
from navigator.conf import default_dsn, CACHE_HOST, CACHE_PORT


# disable debug on some libraries:
logging.getLogger(name='httpcore').setLevel(logging.INFO)
logging.getLogger(name='httpx').setLevel(logging.INFO)
logging.getLogger(name='groq').setLevel(logging.INFO)
logging.getLogger(name='h5py').setLevel(logging.INFO)
logging.getLogger(name='tensorflow').setLevel(logging.INFO)
logging.getLogger(name='selenium.webdriver').setLevel(logging.WARNING)
logging.getLogger(name='selenium').setLevel(logging.INFO)


# Static directory
STATIC_DIR = config.get('STATIC_DIR', fallback=BASE_DIR.joinpath('static'))
if isinstance(STATIC_DIR, str):
    STATIC_DIR = Path(STATIC_DIR)

# LLM Model
DEFAULT_LLM_MODEL_NAME = config.get('LLM_MODEL_NAME', fallback='gemini-pro')


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
REDIS_HISTORY_DB = config.get('REDIS_HISTORY_DB', fallback=3)
REDIS_HISTORY_URL = f"redis://{CACHE_HOST}:{CACHE_PORT}/{REDIS_HISTORY_DB}"

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


# Embedding Device:
EMBEDDING_DEVICE = config.get('EMBEDDING_DEVICE', fallback='cpu')
EMBEDDING_DEFAULT_MODEL = config.get(
    'EMBEDDING_DEFAULT_MODEL',
    fallback='thenlper/gte-base'
)
MAX_VRAM_AVAILABLE = config.get('MAX_VRAM_AVAILABLE', fallback=20000)
RAM_AVAILABLE = config.get('RAM_AVAILABLE', fallback=819200)
CUDA_DEFAULT_DEVICE = config.get('CUDA_DEFAULT_DEVICE', fallback=0)
MAX_BATCH_SIZE = config.get('MAX_BATCH_SIZE', fallback=768)

# Enable Teams Bot:
ENABLE_AZURE_BOT = config.getboolean('ENABLE_AZURE_BOT', fallback=True)

## Google API:
GOOGLE_API_KEY = config.get('GOOGLE_API_KEY')
### Google Service Credentials:
GA_SERVICE_ACCOUNT_NAME = config.get('GA_SERVICE_ACCOUNT_NAME', fallback="google.json")
GA_SERVICE_PATH = config.get('GA_SERVICE_PATH', fallback="env/google/")

# Ethical Principle:
ETHICAL_PRINCIPLE = config.get(
    'ETHICAL_PRINCIPLE',
    fallback='The model should only talk about ethical and legal things.'
)
