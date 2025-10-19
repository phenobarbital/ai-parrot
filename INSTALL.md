# AI-Parrot Installation Guide

This guide walks you through installing AI-Parrot and all its dependencies.

## Table of Contents

- [Prerequisites](#prerequisites)
- [System Dependencies](#system-dependencies)
- [Python Environment Setup](#python-environment-setup)
- [Install AI-Parrot](#install-ai-parrot)
- [Initial Configuration](#initial-configuration)
- [PostgreSQL with pgVector](#postgresql-with-pgvector)
- [Spacy Setup](#spacy-setup)
- [WhisperX Setup](#whisperx-setup)
- [Process Management with Honcho](#process-management-with-honcho)
- [Verification](#verification)

---

## Prerequisites

### Operating System Requirements

AI-Parrot is primarily developed and tested on Linux systems, though it can run on macOS and Windows with WSL2.

**Recommended**:
- Ubuntu 22.04 LTS or newer
- Debian 12 (Bookworm) or newer
- Python 3.11 or higher
- At least 8GB RAM (16GB+ recommended for ML models)
- CUDA-compatible GPU (optional, but recommended for embedding/ML tasks)

### Required System Software

The following system packages are required:

- **Python 3.11+**: Full Python installation with development headers
- **FFmpeg**: Audio/video processing for speech recognition
- **PostgreSQL 15+**: Database with pgVector extension
- **Redis**: Caching and job queue management
- **GCC/Build tools**: For compiling Python extensions
- **Tesseract OCR**: Document text extraction
- **CUDA Toolkit** (optional): For GPU acceleration

---

## System Dependencies

### Debian/Ubuntu Systems

Install all required system dependencies:

```bash
sudo apt update
sudo apt install -y \
    gcc \
    python3.11-venv \
    python3.11-full \
    python3.11-dev \
    libmemcached-dev \
    zlib1g-dev \
    build-essential \
    libffi-dev \
    unixodbc \
    unixodbc-dev \
    libsqliteodbc \
    libev4 \
    libev-dev \
    ffmpeg \
    python3-pycuda \
    nvidia-cuda-toolkit \
    tesseract-ocr \
    libtesseract-dev \
    poppler-utils \
    tesseract-ocr-eng \
    tesseract-ocr-spa
```

**Package breakdown**:
- `gcc`, `build-essential`, `libffi-dev`: C compiler and development tools
- `python3.11-*`: Python interpreter, virtual environment, and headers
- `libmemcached-dev`, `zlib1g-dev`: Caching and compression libraries
- `unixodbc`, `unixodbc-dev`, `libsqliteodbc`: Database connectivity
- `libev4`, `libev-dev`: Event loop library for async operations
- `ffmpeg`: Audio/video processing
- `python3-pycuda`, `nvidia-cuda-toolkit`: GPU acceleration (optional)
- `tesseract-ocr*`, `libtesseract-dev`, `poppler-utils`: OCR and PDF processing

### Fedora/RHEL Systems

```bash
sudo dnf install -y \
    gcc \
    python3.11 \
    python3.11-devel \
    libmemcached-devel \
    zlib-devel \
    libffi-devel \
    unixODBC \
    unixODBC-devel \
    libev \
    libev-devel \
    ffmpeg \
    tesseract \
    tesseract-devel \
    tesseract-langpack-eng \
    tesseract-langpack-spa \
    poppler-utils
```

### macOS

```bash
# Install Homebrew if not already installed
/bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"

# Install dependencies
brew install \
    python@3.11 \
    libmemcached \
    zlib \
    libffi \
    unixodbc \
    libev \
    ffmpeg \
    tesseract \
    tesseract-lang \
    poppler
```

### Additional Requirements

**Redis Installation**:
```bash
# Debian/Ubuntu
sudo apt install redis-server
sudo systemctl enable redis-server
sudo systemctl start redis-server

# macOS
brew install redis
brew services start redis
```

**PostgreSQL Installation**:
```bash
# Debian/Ubuntu
sudo apt install postgresql postgresql-contrib

# macOS
brew install postgresql@15
brew services start postgresql@15
```

---

## Python Environment Setup

We use `uv` as the Python package manager for fast, reliable dependency management.

### Install uv

```bash
# Install uv using the official installer
curl -LsSf https://astral.sh/uv/install.sh | sh

# Or via pip
pip install uv
```

### Create Virtual Environment

```bash
# Create a new virtual environment with Python 3.11
uv venv --python 3.11 .venv

# Activate the virtual environment
source .venv/bin/activate  # Linux/macOS
# or
.venv\Scripts\activate     # Windows
```

**Verify activation**:
```bash
which python
# Should show: /path/to/your/project/.venv/bin/python

python --version
# Should show: Python 3.11.x
```

---

## Install AI-Parrot

### Basic Installation

Install AI-Parrot with core dependencies:

```bash
uv pip install ai-parrot
```

### Install with Optional Dependencies

AI-Parrot supports several optional feature sets. Install based on your needs:

```bash
# Install with all LLM providers
uv pip install ai-parrot[anthropic,openai,google,groq]

# Install with vector database support
uv pip install ai-parrot[milvus,chroma]

# Install with agent and loader support
uv pip install ai-parrot[agents,loaders]

# Install with image processing
uv pip install ai-parrot[images]

# Install everything (recommended for full features)
uv pip install ai-parrot[all]

# Development installation
uv pip install ai-parrot[dev]
```

**Feature groups**:
- `anthropic`: Claude API support
- `openai`: OpenAI GPT models support
- `google`: Google GenAI (Gemini) support
- `groq`: Groq inference support
- `milvus`: Milvus vector database
- `chroma`: ChromaDB vector database
- `agents`: Agent framework and tools
- `loaders`: Document loaders and processors
- `images`: Image processing and computer vision
- `all`: All optional features
- `dev`: Development tools (pytest, pylint, mypy, etc.)

---

## Initial Configuration

### Create Configuration Directories

AI-Parrot uses the `kardex` CLI tool to initialize the project structure:

```bash
# Create env/ and etc/ directories with default structure
kardex create
```

This command creates:
- `env/`: Directory for environment configuration files (`.env` files)
- `etc/`: Directory for additional configuration files
- Default configuration templates

### Directory Structure

After running `kardex create`, your project should look like:

```
your-project/
├── .venv/              # Virtual environment
├── env/                # Environment configuration
│   ├── .env            # Main environment file
│   └── google/         # Google service credentials
├── etc/                # Additional configuration
├── agents/             # Agent definitions (created on first use)
├── plugins/            # Custom plugins (optional)
└── static/             # Static files (optional)
```

### Configure Environment Variables

Edit `env/.env` with your configuration. See [CONFIGURATION.md](./CONFIGURATION.md) for detailed documentation of all variables.

**Minimal required configuration**:

```bash
# Edit the environment file
nano env/.env  # or use your preferred editor
```

Add at minimum:

```env
# LLM API Keys (at least one is required)
GOOGLE_API_KEY=your_google_api_key
# OPENAI_API_KEY=your_openai_api_key
# ANTHROPIC_API_KEY=your_anthropic_api_key
# GROQ_API_KEY=your_groq_api_key

# Database Configuration
DBHOST=localhost
DBUSER=parrot_user
DBPWD=secure_password
DBNAME=parrot_db
DBPORT=5432

# Redis Configuration
CACHE_HOST=localhost
CACHE_PORT=6379
REDIS_HISTORY_DB=3

# Default LLM Model
DEFAULT_LLM_MODEL=gemini-2.5-flash
LLM_TEMPERATURE=0.1
```

**For a complete configuration example**, refer to the [CONFIGURATION.md](./CONFIGURATION.md) file.

---

## PostgreSQL with pgVector

AI-Parrot uses PostgreSQL with the pgVector extension for semantic search and RAG capabilities.

### Install pgVector Extension

```bash
# Debian/Ubuntu
sudo apt install postgresql-15-pgvector

# From source (if not available in repos)
cd /tmp
git clone --branch v0.5.1 https://github.com/pgvector/pgvector.git
cd pgvector
make
sudo make install
```

### Create Database and User

```bash
# Connect to PostgreSQL as superuser
sudo -u postgres psql

# Create user
CREATE USER parrot_user WITH PASSWORD 'secure_password';

# Create database
CREATE DATABASE parrot_db OWNER parrot_user;

# Connect to the database
\c parrot_db

# Enable pgVector extension
CREATE EXTENSION IF NOT EXISTS vector;

# Grant privileges
GRANT ALL PRIVILEGES ON DATABASE parrot_db TO parrot_user;
GRANT ALL PRIVILEGES ON ALL TABLES IN SCHEMA public TO parrot_user;
GRANT ALL PRIVILEGES ON ALL SEQUENCES IN SCHEMA public TO parrot_user;

# Exit psql
\q
```

### Verify pgVector Installation

```bash
psql -U parrot_user -d parrot_db -c "SELECT * FROM pg_extension WHERE extname = 'vector';"
```

You should see the vector extension listed.

---

## Spacy Setup

Spacy is used for natural language processing and entity recognition.

### Install Spacy Packages

```bash
# Install spacy with transformers and lookups
uv pip install spacy-llm
uv pip install -U 'spacy[transformers,lookups]'
```

### Download Language Models

Install the language models you need:

```bash
# English models
python -m spacy download en_core_web_trf    # Transformer-based (best accuracy)
python -m spacy download en_core_web_sm     # Small model (faster)

# Spanish models
python -m spacy download es_dep_news_trf    # Transformer-based (best accuracy)
python -m spacy download es_dep_news_sm     # Small model (faster)

# Additional languages (optional)
# python -m spacy download fr_core_news_sm  # French
# python -m spacy download de_core_news_sm  # German
# python -m spacy download zh_core_web_sm   # Chinese
```

**Model size comparison**:
- `*_trf`: Transformer-based models (~500MB) - Highest accuracy
- `*_sm`: Small models (~10-50MB) - Faster inference
- `*_md`: Medium models (~50-150MB) - Balanced
- `*_lg`: Large models (~150-500MB) - Good accuracy

**Recommendation**: Use transformer models (`*_trf`) for production accuracy, small models (`*_sm`) for development speed.

### Verify Spacy Installation

```python
import spacy

# Test English model
nlp = spacy.load("en_core_web_sm")
doc = nlp("Apple is looking at buying U.K. startup for $1 billion")
for ent in doc.ents:
    print(ent.text, ent.label_)
```

---

## WhisperX Setup

WhisperX is used for accurate speech recognition with speaker diarization.

### Install WhisperX

WhisperX requires PyTorch with CUDA support for optimal performance:

```bash
# Install PyTorch with CUDA support (if you have NVIDIA GPU)
uv pip install torch torchvision torchaudio --index-url https://download.pytorch.org/whl/cu121

# Install WhisperX and dependencies
uv pip install whisperx==3.4.2
```

Or install the complete whisperx feature set:

```bash
uv pip install ai-parrot[whisperx]
```

This includes:
- `whisperx==3.4.2`
- `torch==2.6.0`
- `torchaudio==2.6.0`
- `torchvision==0.21.0`
- `pyannote-audio==3.4.0`
- Speaker diarization models

### Configure WhisperX

WhisperX models are downloaded automatically on first use. For manual download:

```bash
# Download base model
whisperx --model base --language en --output_dir ./models test.wav

# Available models: tiny, base, small, medium, large-v2, large-v3
```

### GPU Configuration

If using CUDA, verify GPU availability:

```python
import torch
print(f"CUDA available: {torch.cuda.is_available()}")
print(f"CUDA device: {torch.cuda.get_device_name(0)}")
```

Set in your `env/.env`:
```env
EMBEDDING_DEVICE=cuda
CUDA_DEFAULT_DEVICE=cuda
CUDA_DEFAULT_DEVICE_NUMBER=0
MAX_VRAM_AVAILABLE=20000  # Adjust based on your GPU
```

---

## Process Management with Honcho

Honcho is used to manage multiple processes (RQ workers and Parrot application) using a Procfile.

### Install Honcho

```bash
uv pip install honcho
```

### Create Procfile.dev

Create a `Procfile.dev` in your project root:

```bash
cat > Procfile.dev << 'EOF'
# AI-Parrot Process Configuration

# Redis Queue Worker - Handles background jobs
rq_worker: rq worker --url redis://localhost:6379/0 default high low

# AI-Parrot Main Application
parrot: python -m parrot.server --host 0.0.0.0 --port 5000

# Optional: Additional RQ worker for high-priority jobs
# rq_worker_priority: rq worker --url redis://localhost:6379/0 high

# Optional: RQ Dashboard for monitoring
# rq_dashboard: rq-dashboard --redis-url redis://localhost:6379/0
EOF
```

### Start All Services

```bash
# Start all processes defined in Procfile.dev
honcho start -f Procfile.dev
```

This will start:
- RQ worker for background job processing
- Parrot application server

### Individual Process Management

You can also start processes individually:

```bash
# Start only the RQ worker
honcho start rq_worker -f Procfile.dev

# Start only the Parrot application
honcho start parrot -f Procfile.dev
```

### Production Deployment

For production, use a process manager like `systemd` or `supervisord`:

**Example systemd service** (`/etc/systemd/system/parrot.service`):

```ini
[Unit]
Description=AI-Parrot Application
After=network.target postgresql.service redis.service

[Service]
Type=simple
User=parrot
WorkingDirectory=/opt/ai-parrot
Environment="PATH=/opt/ai-parrot/.venv/bin"
ExecStart=/opt/ai-parrot/.venv/bin/honcho start -f Procfile.dev
Restart=always
RestartSec=10

[Install]
WantedBy=multi-user.target
```

---

## Verification

### Verify Installation

Run the following checks to ensure everything is installed correctly:

```bash
# 1. Check Python version
python --version
# Should show: Python 3.11.x or higher

# 2. Check AI-Parrot installation
python -c "import parrot; print(parrot.__version__)"

# 3. Check Redis connection
redis-cli ping
# Should return: PONG

# 4. Check PostgreSQL connection
psql -U parrot_user -d parrot_db -c "SELECT version();"

# 5. Check pgVector extension
psql -U parrot_user -d parrot_db -c "SELECT * FROM pg_extension WHERE extname = 'vector';"

# 6. Check Spacy models
python -m spacy validate

# 7. Check GPU availability (if applicable)
python -c "import torch; print(f'CUDA: {torch.cuda.is_available()}')"
```

### Test Basic Functionality

Create a test script `test_install.py`:

```python
#!/usr/bin/env python
"""Test AI-Parrot installation."""
import asyncio
from parrot.clients.google import GoogleGenAIClient

async def test_basic_client():
    """Test basic LLM client functionality."""
    async with GoogleGenAIClient() as client:
        response = await client.ask("Say 'Installation successful!' if you can read this.")
        print(f"Response: {response.content}")
        print("✓ LLM client working correctly")

if __name__ == "__main__":
    asyncio.run(test_basic_client())
```

Run the test:
```bash
python test_install.py
```

### Common Issues

**Issue**: `ModuleNotFoundError: No module named 'parrot'`
- **Solution**: Ensure virtual environment is activated and ai-parrot is installed

**Issue**: `redis.exceptions.ConnectionError`
- **Solution**: Ensure Redis is running: `sudo systemctl start redis-server`

**Issue**: `psycopg2.OperationalError: connection refused`
- **Solution**: Ensure PostgreSQL is running: `sudo systemctl start postgresql`

**Issue**: `CUDA out of memory`
- **Solution**: Reduce batch sizes or switch to CPU mode in configuration

**Issue**: Spacy model not found
- **Solution**: Download the model: `python -m spacy download en_core_web_sm`

---

## Next Steps

After successful installation:

1. **Configure your LLM APIs**: Add API keys to `env/.env`
2. **Review Configuration**: Read [CONFIGURATION.md](./CONFIGURATION.md) for detailed settings
3. **Set up Vector Database**: Choose and configure Milvus, Qdrant, or ChromaDB
4. **Create your first agent**: Follow the agent creation guide
5. **Explore examples**: Check the `examples/` directory (if available)
6. **Read the documentation**: Visit the project documentation for advanced usage

---

## Support

For issues and questions:
- GitHub Issues: https://github.com/phenobarbital/ai-parrot/issues
- Documentation: https://github.com/phenobarbital/ai-parrot/
- Funding: https://paypal.me/phenobarbital

---

## License

AI-Parrot is open-source software. Check the LICENSE file for details.
