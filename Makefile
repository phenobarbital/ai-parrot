# AI-Parrot Makefile
# This Makefile provides a set of commands to manage the AI-Parrot project.

.PHONY: venv install install-core install-tools install-loaders install-codex-sdk-editable \
		develop develop-fast develop-ml setup dev release format lint test clean distclean lock sync \
		generate-registry check-registry \
		install-go install-whatsapp-bridge build-whatsapp-bridge \
		run-whatsapp-bridge docker-whatsapp-bridge install-tesseract install-gvisor

# Python version to use
PYTHON_VERSION := 3.11

# Enforce virtual environment usage
export PIP_REQUIRE_VIRTUALENV=true

# Auto-detect available tools
HAS_UV := $(shell command -v uv 2> /dev/null)
HAS_PIP := $(shell command -v pip 2> /dev/null)
HAS_NVIDIA := $(shell command -v nvidia-smi 2> /dev/null)
HAS_FFMPEG := $(shell command -v ffmpeg 2> /dev/null)

# Experimental OpenAI Codex SDK source install.
CODEX_SDK_VERSION ?= 0.1.11
CODEX_SDK_VENDOR_DIR ?= vendor
CODEX_SDK_DIR ?= $(CODEX_SDK_VENDOR_DIR)/openai-codex-sdk

# Detect OS
UNAME_S := $(shell uname -s)
ifeq ($(UNAME_S),Linux)
    OS_TYPE := Linux
    DISTRO := $(shell lsb_release -si 2>/dev/null || echo "Unknown")
endif
ifeq ($(UNAME_S),Darwin)
    OS_TYPE := MacOS
endif

# Install uv for faster workflows
install-uv:
	curl -LsSf https://astral.sh/uv/install.sh | sh
	@echo "uv installed! You may need to restart your shell or run 'source ~/.bashrc'"
	@echo "Then re-run make commands to use faster uv workflows"

install-codex-sdk-editable:
	@echo "Installing experimental openai-codex-sdk $(CODEX_SDK_VERSION) from source in editable mode..."
	mkdir -p $(CODEX_SDK_VENDOR_DIR)
	python -m pip download --no-binary=:all: --no-deps \
		--dest $(CODEX_SDK_VENDOR_DIR) openai-codex-sdk==$(CODEX_SDK_VERSION)
	python -c "import pathlib, shutil; p = pathlib.Path('$(CODEX_SDK_DIR)'); shutil.rmtree(p) if p.exists() else None"
	mkdir -p $(CODEX_SDK_DIR)
	tar -xzf $(CODEX_SDK_VENDOR_DIR)/openai_codex_sdk-$(CODEX_SDK_VERSION).tar.gz -C $(CODEX_SDK_DIR) --strip-components=1
	uv pip install -e $(CODEX_SDK_DIR)
	@echo "Experimental Codex SDK installed from $(CODEX_SDK_DIR)."

# Create virtual environment
venv:
	uv venv --python $(PYTHON_VERSION) .venv
	@echo 'run `source .venv/bin/activate` to start develop with Parrot'

# Check system dependencies for WhisperX
check-deps:
	@echo "Checking system dependencies..."
	@echo "OS: $(OS_TYPE)"
ifdef HAS_NVIDIA
	@echo "✓ NVIDIA GPU detected"
	@nvidia-smi --query-gpu=name,driver_version,memory.total --format=csv
else
	@echo "✗ No NVIDIA GPU detected (CPU mode will be used)"
endif
ifdef HAS_FFMPEG
	@echo "✓ FFmpeg installed"
else
	@echo "✗ FFmpeg not installed (required for audio processing)"
endif
	@echo ""
	@echo "CUDA/cuDNN status:"
	@ldconfig -p | grep -E "libcudnn|libcuda" || echo "No CUDA/cuDNN libraries found in ldconfig"

# Install system dependencies for WhisperX (Ubuntu/Debian)
install-system-deps:
ifeq ($(OS_TYPE),Linux)
	@echo "Installing system dependencies for WhisperX..."
	# Install FFmpeg
ifndef HAS_FFMPEG
	sudo apt-get update && sudo apt-get install -y ffmpeg libavutil-dev libavformat-dev libavcodec-dev
endif
	# Install CUDA dependencies if NVIDIA GPU is present
ifdef HAS_NVIDIA
	@echo "Installing CUDA dependencies..."
	# Check if libcudnn8 is already installed
	@if ! ldconfig -p | grep -q libcudnn; then \
		echo "Installing libcudnn8..."; \
		wget -q https://developer.download.nvidia.com/compute/cuda/repos/ubuntu2004/x86_64/cuda-ubuntu2004.pin; \
		sudo mv cuda-ubuntu2004.pin /etc/apt/preferences.d/cuda-repository-pin-600; \
		export last_public_key=3bf863cc; \
		sudo apt-key adv --fetch-keys https://developer.download.nvidia.com/compute/cuda/repos/ubuntu2004/x86_64/$$last_public_key.pub; \
		sudo add-apt-repository "deb https://developer.download.nvidia.com/compute/cuda/repos/ubuntu2004/x86_64/ /"; \
		sudo apt-get update; \
		sudo apt-get install -y libcudnn8 libcudnn8-dev; \
	else \
		echo "libcudnn8 already installed"; \
	fi
endif
else ifeq ($(OS_TYPE),MacOS)
	@echo "Installing system dependencies for MacOS..."
ifndef HAS_FFMPEG
	brew install ffmpeg
endif
else
	@echo "Unsupported OS. Please install FFmpeg and CUDA/cuDNN manually."
endif

# Install WhisperX with all dependencies
install-whisperx: install-system-deps
	@echo "Installing WhisperX and dependencies..."
	uv sync --extra whisperx
	@echo ""
	@echo "WhisperX installation complete!"
	@echo "Testing installation..."
	@python -c "import whisperx; print('✓ WhisperX imported successfully')" || echo "✗ WhisperX import failed"
	@python -c "import torch; print(f'✓ PyTorch {torch.__version__} with CUDA {torch.version.cuda if torch.cuda.is_available() else \"not available\"}')"
	@python -c "import torchaudio; print(f'✓ Torchaudio {torchaudio.__version__}')"

# ============================================================
# Workspace Install Targets (monorepo with uv workspaces)
# ============================================================

# Install production: core + tools (base deps only, no extras)
install:
	uv sync --frozen --no-dev --all-packages
	@echo "Production dependencies installed (core + tools + loaders, base deps)."
	@echo "Use 'make install-tools' or 'make install-loaders' for extras."

# Install only core package (minimal, no tools, no loaders)
install-core:
	uv sync --frozen --no-dev --package ai-parrot \
		--extra google --extra groq --extra openai --extra anthropic \
		--extra vectors --extra embeddings
	@echo "Core package installed with LLM clients and vector stores."

# Install core + tools with commonly used extras
install-tools:
	uv sync --frozen --no-dev --package ai-parrot-tools \
		--extra jira --extra slack --extra aws --extra docker \
		--extra git --extra analysis --extra excel
	@echo "Core + tools installed with common extras."

# Install core + tools with ALL extras
install-tools-all:
	uv sync --frozen --no-dev --package ai-parrot-tools --all-extras
	@echo "Core + tools installed with ALL extras."

# Install core + loaders with commonly used extras
install-loaders:
	uv sync --frozen --no-dev --package ai-parrot-loaders \
		--extra youtube --extra web --extra pdf
	@echo "Core + loaders installed with common extras."

# Install core + loaders with ALL extras (heavy: whisperx, pyannote, etc.)
install-loaders-all:
	uv sync --frozen --no-dev --package ai-parrot-loaders --all-extras
	@echo "Core + loaders installed with ALL extras (including heavy ML deps)."

# Install EVERYTHING with ALL extras (full monorepo)
# NOTE: `gemma4` is excluded — it pins transformers>=5.0 which conflicts with
# the `images`/`all` extras (transformers<5.0). Install it in a separate env.
install-all:
	uv sync --frozen --no-dev --all-packages --all-extras --no-extra gemma4
	uv pip install querysource
	@echo "All packages installed with ALL extras (except gemma4)."

# Generate lock files (uv only)
lock:
ifdef HAS_UV
	uv lock
else
	@echo "Lock files require uv. Install with: pip install uv"
endif

# ============================================================
# Development Install Targets
# ============================================================

# Install all packages in dev mode with all extras
# NOTE: `gemma4` is excluded — it pins transformers>=5.0 which conflicts with
# the `images`/`all` extras (transformers<5.0). Install it in a separate env.
develop:
	uv sync --all-packages --all-extras --no-extra gemma4
	uv pip install querysource
	@echo "Full development environment ready (all packages, all extras except gemma4, dev tools)."

# Fast dev install: all packages but skip heavy ML deps
# Uses core extras only + tools base deps (no torch/tensorflow/whisperx)
develop-fast:
	uv pip install "Cython==3.0.11" "setuptools>=67.6.1" "wheel>=0.44.0"
	uv sync --all-packages
	$(MAKE) build-inplace
	@echo "Fast dev environment ready (no heavy ML deps)."

# Full ML stack (slow install, requires GPU for optimal performance)
develop-ml:
	uv sync --package ai-parrot --extra embeddings --extra charts
	uv sync --package ai-parrot-loaders --extra audio
	@echo "ML development environment ready."

# Setup development environment from requirements file (if you still have one)
setup:
	uv pip install -r requirements/requirements-dev.txt

# Install in development mode using flit (if you want to keep flit)
dev:
	uv pip install flit
	flit install --symlink

# Test WhisperX installation
test-whisperx:
	@echo "Testing WhisperX installation..."
	@python -c "\
import sys; \
try: \
    import whisperx; \
    import torch; \
    import torchaudio; \
    print('✓ All WhisperX dependencies imported successfully'); \
    print(f'  PyTorch version: {torch.__version__}'); \
    print(f'  CUDA available: {torch.cuda.is_available()}'); \
    if torch.cuda.is_available(): \
        print(f'  CUDA version: {torch.version.cuda}'); \
        print(f'  cuDNN version: {torch.backends.cudnn.version()}'); \
    print(f'  Torchaudio version: {torchaudio.__version__}'); \
    sys.exit(0); \
except ImportError as e: \
    print(f'✗ Import error: {e}'); \
    sys.exit(1); \
except Exception as e: \
    print(f'✗ Error: {e}'); \
    sys.exit(1)"

# Run a simple WhisperX transcription test
test-whisperx-transcribe:
	@echo "Testing WhisperX transcription (requires an audio file)..."
	@python -c "\
import whisperx; \
import torch; \
device = 'cuda' if torch.cuda.is_available() else 'cpu'; \
print(f'Using device: {device}'); \
model = whisperx.load_model('tiny', device, compute_type='float16' if device == 'cuda' else 'float32'); \
print('✓ WhisperX model loaded successfully')"

# Build and publish all packages
release: lint test clean check-registry
	uv build --package ai-parrot
	uv build --package ai-parrot-tools
	uv build --package ai-parrot-loaders
	uv build --package ai-parrot-pipelines
	uv build --package parrot-formdesigner
	uv publish dist/ai_parrot-*.tar.gz dist/ai_parrot-*.whl
	uv publish dist/ai_parrot_tools-*.tar.gz dist/ai_parrot_tools-*.whl
	uv publish dist/ai_parrot_loaders-*.tar.gz dist/ai_parrot_loaders-*.whl
	uv publish dist/ai_parrot_pipelines-*.tar.gz dist/ai_parrot_pipelines-*.whl
	uv publish dist/parrot_formdesigner-*.tar.gz dist/parrot_formdesigner-*.whl

# Alternative release using flit
release-flit: lint test clean
	flit publish

# Format code (all packages)
format:
	uv run black packages/ai-parrot/src/parrot packages/ai-parrot-tools/src/parrot_tools packages/ai-parrot-loaders/src/parrot_loaders

# Lint code (all packages)
lint:
	uv run pylint --rcfile .pylint packages/ai-parrot/src/parrot/*.py
	uv run black --check packages/ai-parrot/src/parrot packages/ai-parrot-tools/src/parrot_tools

# Run tests with coverage
test:
	uv run pytest
	uv run mypy packages/ai-parrot/src/parrot/*.py

# Alternative test command using pytest directly
test-pytest:
	uv run pytest

# Add new dependency and update lock file
add:
	@if [ -z "$(pkg)" ]; then echo "Usage: make add pkg=package-name"; exit 1; fi
	uv add $(pkg)

# Add development dependency
add-dev:
	@if [ -z "$(pkg)" ]; then echo "Usage: make add-dev pkg=package-name"; exit 1; fi
	uv add --dev $(pkg)

# Remove dependency
remove:
	@if [ -z "$(pkg)" ]; then echo "Usage: make remove pkg=package-name"; exit 1; fi
	uv remove $(pkg)

# Compile Cython extensions using setup.py
build-cython:
	@echo "Compiling Cython extensions..."
	python setup.py build_ext

# Build Cython extensions in place (for development)
build-inplace:
	@echo "Building Cython extensions in place..."
	python setup.py build_ext --inplace

# Full build using uv (builds all workspace packages)
build: clean
	@echo "Building all workspace packages with uv..."
	uv build --package ai-parrot
	uv build --package ai-parrot-tools
	uv build --package ai-parrot-loaders
	uv build --package ai-parrot-pipelines
	uv build --package parrot-formdesigner

# ============================================================
# Tool Registry Management
# ============================================================

# Generate TOOL_REGISTRY from parrot_tools/ source
generate-registry:
	@echo "Scanning parrot_tools/ for tools and toolkits..."
	uv run python scripts/generate_tool_registry.py --verbose
	@echo "Registry updated."

# Check if TOOL_REGISTRY is up to date (for CI)
check-registry:
	uv run python scripts/generate_tool_registry.py --check

# Update all dependencies
update:
	uv lock --upgrade

# Show project info
info:
	uv tree

# Show GPU/CUDA info
cuda-info:
ifdef HAS_NVIDIA
	@echo "NVIDIA GPU Information:"
	@nvidia-smi
	@echo ""
	@echo "CUDA/cuDNN Libraries:"
	@python -c "\
import torch; \
print(f'PyTorch CUDA available: {torch.cuda.is_available()}'); \
if torch.cuda.is_available(): \
    print(f'CUDA version: {torch.version.cuda}'); \
    print(f'cuDNN version: {torch.backends.cudnn.version()}'); \
    print(f'Number of GPUs: {torch.cuda.device_count()}'); \
    for i in range(torch.cuda.device_count()): \
        print(f'GPU {i}: {torch.cuda.get_device_name(i)}')"
else
	@echo "No NVIDIA GPU detected"
endif

# Clean build artifacts
clean:
	rm -rf build/
	rm -rf dist/
	rm -rf *.egg-info/
	rm -rf bin/whatsapp-bridge
	rm -rf services/whatsapp-bridge/whatsapp-bridge
	find . -name "*.pyc" -delete
	find . -name "*.pyo" -delete
	find . -name "*.so" -delete
	find . -type d -name __pycache__ -delete
	find . -type f -name "*.pyc" -delete
	find . -name "__pycache__" -type d -exec rm -rf {} + 2>/dev/null || true
	@if command -v go >/dev/null 2>&1 && [ -d services/whatsapp-bridge ]; then \
		cd services/whatsapp-bridge && go clean; \
	fi
	@echo "Clean complete."

# Remove virtual environment
distclean:
	rm -rf .venv
	rm -rf uv.lock

# Version management
# Each package has its own independent version:
#   ai-parrot       -> packages/ai-parrot/src/parrot/version.py
#   ai-parrot-tools -> packages/ai-parrot-tools/src/parrot_tools/version.py
#   ai-parrot-loaders -> packages/ai-parrot-loaders/src/parrot_loaders/version.py
#
# bump-patch / bump-minor / bump-major bump the CORE package and sync
# the ai-parrot>= dependency in tools/loaders pyproject.toml.
# Use bump-patch-tools / bump-patch-loaders (etc.) for sub-packages.

VERSION_FILE := packages/ai-parrot/src/parrot/version.py
TOOLS_VERSION_FILE := packages/ai-parrot-tools/src/parrot_tools/version.py
LOADERS_VERSION_FILE := packages/ai-parrot-loaders/src/parrot_loaders/version.py
PIPELINES_VERSION_FILE := packages/ai-parrot-pipelines/src/parrot_pipelines/version.py
FORMDESIGNER_VERSION_FILE := packages/parrot-formdesigner/src/parrot/formdesigner/version.py

# Helper: bump a version file. Usage: $(call _bump,file,part)
# part: patch=2, minor=1, major=0
define _bump
	@python -c "import re; \
	content = open('$(1)').read(); \
	version = re.search(r'__version__ = \"(.+)\"', content).group(1); \
	parts = version.split('.'); \
	idx = $(2); \
	parts[idx] = str(int(parts[idx]) + 1); \
	parts[idx+1:] = ['0'] * len(parts[idx+1:]); \
	new_version = '.'.join(parts); \
	new_content = re.sub(r'__version__ = \".+\"', f'__version__ = \"{new_version}\"', content); \
	open('$(1)', 'w').write(new_content); \
	print(f'$(1): {version} → {new_version}')"
endef

# --- Core package (ai-parrot) ---
bump-patch:
	$(call _bump,$(VERSION_FILE),2)
	@$(MAKE) _sync-core-dep

bump-minor:
	$(call _bump,$(VERSION_FILE),1)
	@$(MAKE) _sync-core-dep

bump-major:
	$(call _bump,$(VERSION_FILE),0)
	@$(MAKE) _sync-core-dep

# --- Tools package (ai-parrot-tools) ---
bump-patch-tools:
	$(call _bump,$(TOOLS_VERSION_FILE),2)

bump-minor-tools:
	$(call _bump,$(TOOLS_VERSION_FILE),1)

bump-major-tools:
	$(call _bump,$(TOOLS_VERSION_FILE),0)

# --- Loaders package (ai-parrot-loaders) ---
bump-patch-loaders:
	$(call _bump,$(LOADERS_VERSION_FILE),2)

bump-minor-loaders:
	$(call _bump,$(LOADERS_VERSION_FILE),1)

bump-major-loaders:
	$(call _bump,$(LOADERS_VERSION_FILE),0)

# --- Pipelines package (ai-parrot-pipelines) ---
bump-patch-pipelines:
	$(call _bump,$(PIPELINES_VERSION_FILE),2)

bump-minor-pipelines:
	$(call _bump,$(PIPELINES_VERSION_FILE),1)

bump-major-pipelines:
	$(call _bump,$(PIPELINES_VERSION_FILE),0)

# --- Formdesigner package (parrot-formdesigner) ---
bump-patch-formdesigner:
	$(call _bump,$(FORMDESIGNER_VERSION_FILE),2)

bump-minor-formdesigner:
	$(call _bump,$(FORMDESIGNER_VERSION_FILE),1)

bump-major-formdesigner:
	$(call _bump,$(FORMDESIGNER_VERSION_FILE),0)

# --- Bump ALL packages at once (patch) ---
bump-all:
	$(call _bump,$(VERSION_FILE),2)
	$(call _bump,$(TOOLS_VERSION_FILE),2)
	$(call _bump,$(LOADERS_VERSION_FILE),2)
	$(call _bump,$(PIPELINES_VERSION_FILE),2)
	$(call _bump,$(FORMDESIGNER_VERSION_FILE),2)
	@$(MAKE) _sync-core-dep

# Sync ai-parrot>= dependency in tools/loaders pyproject.toml
# (does NOT touch their version.py — versions are independent)
_sync-core-dep:
	@python -c "import re, glob; \
	version = re.search(r'__version__ = \"(.+)\"', open('$(VERSION_FILE)').read()).group(1); \
	print(f'Syncing ai-parrot>={version} dependency...'); \
	[open(f, 'w').write(new) or print(f'  {f} -> ai-parrot>={version}') for f in glob.glob('packages/*/pyproject.toml') if (orig := open(f).read()) != (new := re.sub(r'ai-parrot>=[\d.]+', f'ai-parrot>={version}', orig))]"

# Install Go
install-go:
	@echo "Checking for Go installation..."
	@if command -v go >/dev/null 2>&1; then \
		echo "✅ Go already installed: $$(go version)"; \
	else \
		echo "Installing Go..."; \
		curl -LO https://go.dev/dl/go1.22.0.linux-amd64.tar.gz; \
		sudo rm -rf /usr/local/go; \
		sudo tar -C /usr/local -xzf go1.22.0.linux-amd64.tar.gz; \
		rm go1.22.0.linux-amd64.tar.gz; \
		echo 'export PATH=$$PATH:/usr/local/go/bin' >> ~/.profile; \
		echo "✅ Go installed. Run 'source ~/.profile' to update PATH"; \
	fi

# Install WhatsApp Bridge dependencies
install-whatsapp-bridge: install-go
	@echo "Installing WhatsApp Bridge dependencies..."
	@cd services/whatsapp-bridge && go mod download
	@echo "✅ WhatsApp Bridge dependencies installed"

# Build WhatsApp Bridge
build-whatsapp-bridge: install-whatsapp-bridge
	@echo "Building WhatsApp Bridge..."
	@mkdir -p bin
	@cd services/whatsapp-bridge && \
		go build -o ../../bin/whatsapp-bridge \
		-ldflags="-s -w" \
		.
	@echo "✅ WhatsApp Bridge built at bin/whatsapp-bridge"

# Run WhatsApp Bridge locally
run-whatsapp-bridge: build-whatsapp-bridge
	@echo "Starting WhatsApp Bridge..."
	@mkdir -p data/whatsapp
	@./bin/whatsapp-bridge

# Docker targets for WhatsApp Bridge
docker-whatsapp-bridge:
	@echo "Building WhatsApp Bridge Docker image..."
	@docker build -t ai-parrot/whatsapp-bridge -f services/whatsapp-bridge/Dockerfile services/whatsapp-bridge
	@echo "Stopping existing container (if any)..."
	@docker rm -f parrot-whatsapp-bridge 2>/dev/null || true
	@echo "Running WhatsApp Bridge in Docker (host network)..."
	@docker run -d \
		--name parrot-whatsapp-bridge \
		--network host \
		-v $$(pwd)/data/whatsapp:/app/data \
		-e REDIS_URL=redis://localhost:6379 \
		-e BRIDGE_PORT=8765 \
		-e CALLBACK_URL=$${CALLBACK_URL:-} \
		--restart unless-stopped \
		ai-parrot/whatsapp-bridge
	@echo "✅ WhatsApp Bridge running on http://localhost:8765"
	@echo "   View QR code: http://localhost:8765/qr"
	@echo "   Health check: http://localhost:8765/health"
	@echo "   Logs: docker logs -f parrot-whatsapp-bridge"

# Install GenMedia MCP Server
install-genmedia:
	@echo "Installing GenMedia MCP Server..."
	@if [ -d "vertex-ai-creative-studio" ]; then \
		echo "Repository already cloned, updating..."; \
		cd vertex-ai-creative-studio && git pull; \
	else \
		git clone https://github.com/GoogleCloudPlatform/vertex-ai-creative-studio.git; \
	fi
	cd vertex-ai-creative-studio/experiments/mcp-genmedia/mcp-genmedia-go && \
	GO_VER=$$(go version | awk '{print $$3}' | sed 's/go//' | cut -d. -f1,2) && \
	echo "Detected Go version: $$GO_VER. Updating go.mod and go.work files..." && \
	find . -name "go.mod" -exec sed -i "s/^go .*/go $$GO_VER/" {} + && \
	find . -name "go.mod" -exec sed -i "/^toolchain/d" {} + && \
	find . -name "go.work" -exec sed -i "s/^go .*/go $$GO_VER/" {} + && \
	if ! grep -q 'export PATH="$$PATH:$$HOME/go/bin"' $$HOME/.bashrc; then \
		echo 'export PATH="$$PATH:$$HOME/go/bin"' >> $$HOME/.bashrc; \
		echo "Added ~/go/bin to ~/.bashrc"; \
	fi; \
	python3 -c 'import subprocess, os; from navconfig import config; env = os.environ.copy(); env["PATH"] = env.get("PATH", "") + ":" + os.path.expanduser("~/go/bin"); subprocess.run(["bash", "install.sh"], env=env, check=True)'
	@echo "Cleaning up..."
	@rm -rf vertex-ai-creative-studio
	@echo "GenMedia MCP Server installed and cleanup complete."

# Install GitHub MCP Server
install-github:
	@echo "Installing GitHub MCP server..."
	npm install @modelcontextprotocol/server-github


# Install MCP Toolbox
install-toolbox:
	@echo "Installing MCP Toolbox..."
	@curl -L -o toolbox https://storage.googleapis.com/genai-toolbox/0.26.0/linux/amd64/toolbox
	@chmod +x toolbox
	@touch tools.yaml
	@./toolbox --version
	@echo "MCP Toolbox installed successfully."

# Run MCP Toolbox
run-toolbox:
	@./toolbox --tools-file tools.yaml

# Install Tesseract OCR (required for Docling with tesserocr)
install-tesseract:
ifeq ($(OS_TYPE),Linux)
	@echo "Installing Tesseract OCR dependencies..."
	-sudo apt-get update
	sudo apt-get install -y \
		tesseract-ocr \
		tesseract-ocr-eng \
		libtesseract-dev \
		libleptonica-dev \
		pkg-config
	@TESSDATA_PREFIX=$$(dpkg -L tesseract-ocr-eng | grep tessdata$$) && \
		echo "Set TESSDATA_PREFIX=$$TESSDATA_PREFIX"
	@echo "✅ Tesseract OCR installed successfully."
else ifeq ($(OS_TYPE),MacOS)
	@echo "Installing Tesseract OCR for MacOS..."
	brew install tesseract tesseract-lang
	@echo "✅ Tesseract OCR installed successfully."
else
	@echo "Unsupported OS. Please install Tesseract OCR manually."
endif

install-gvisor:
	@echo "Installing gVisor (runsc) on Ubuntu..."
	curl -fsSL https://gvisor.dev/archive.key | sudo gpg --dearmor -o /usr/share/keyrings/gvisor-archive-keyring.gpg
	echo "deb [arch=$$(dpkg --print-architecture) signed-by=/usr/share/keyrings/gvisor-archive-keyring.gpg] https://storage.googleapis.com/gvisor/releases release main" | sudo tee /etc/apt/sources.list.d/gvisor.list > /dev/null
	sudo apt-get update
	sudo apt install -y runsc
	@echo "✅ gVisor (runsc) installed successfully."

help:
	@echo "Available targets:"
	@echo ""
	@echo "  Workspace Install (production):"
	@echo "    install             - Install all packages (base deps, no extras)"
	@echo "    install-core        - Install only core (LLM clients + vectors)"
	@echo "    install-tools       - Install core + tools (common extras)"
	@echo "    install-tools-all   - Install core + tools (ALL extras)"
	@echo "    install-loaders     - Install core + loaders (common extras)"
	@echo "    install-loaders-all - Install core + loaders (ALL extras, heavy ML)"
	@echo "    install-all         - Install everything with ALL extras"
	@echo ""
	@echo "  Development:"
	@echo "    venv                - Create virtual environment"
	@echo "    develop             - Full dev install (all packages, all extras)"
	@echo "    develop-fast        - Fast dev install (no heavy ML deps)"
	@echo "    develop-ml          - Install heavy ML stack (torch, whisperx)"
	@echo ""
	@echo "  Registry & Build:"
	@echo "    generate-registry   - Regenerate TOOL_REGISTRY from source"
	@echo "    check-registry      - Check if TOOL_REGISTRY is up to date (CI)"
	@echo "    build               - Build all workspace packages"
	@echo "    release             - Build and publish all packages to PyPI"
	@echo ""
	@echo "  Quality:"
	@echo "    test                - Run tests"
	@echo "    test-pytest         - Run tests with pytest directly"
	@echo "    format              - Format code (black)"
	@echo "    lint                - Lint code (pylint + black check)"
	@echo ""
	@echo "  Version (independent per package):"
	@echo "    bump-patch          - Bump core patch version + sync dependency"
	@echo "    bump-minor          - Bump core minor version + sync dependency"
	@echo "    bump-major          - Bump core major version + sync dependency"
	@echo "    bump-patch-tools    - Bump tools patch version"
	@echo "    bump-patch-loaders  - Bump loaders patch version"
	@echo "    bump-patch-pipelines- Bump pipelines patch version"
	@echo "    bump-all            - Bump patch on ALL packages"
	@echo ""
	@echo "  Dependencies:"
	@echo "    lock                - Generate lock file"
	@echo "    update              - Update all dependencies"
	@echo "    info                - Show dependency tree"
	@echo "    clean               - Clean build artifacts"
	@echo ""
	@echo "  System / External:"
	@echo "    install-uv          - Install uv package manager"
	@echo "    install-codex-sdk-editable - Install experimental Codex SDK from source"
	@echo "    install-whisperx    - Install WhisperX with system deps"
	@echo "    check-deps          - Check system dependencies (GPU, FFmpeg)"
	@echo "    cuda-info           - Show GPU/CUDA information"
	@echo "    install-go          - Install Go toolchain"
	@echo "    install-genmedia    - Install GenMedia MCP Server"
	@echo "    install-tesseract   - Install Tesseract OCR"
	@echo "    install-gvisor      - Install gVisor sandbox runtime"
	@echo ""
	@echo "  WhatsApp Bridge:"
	@echo "    install-whatsapp-bridge  - Install dependencies"
	@echo "    build-whatsapp-bridge    - Build binary"
	@echo "    run-whatsapp-bridge      - Run locally"
	@echo "    docker-whatsapp-bridge   - Build and run in Docker"
	@echo ""
	@echo "Current setup: Python $(PYTHON_VERSION)"
