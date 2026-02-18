# AI-Parrot Makefile
# This Makefile provides a set of commands to manage the AI-Parrot project.

.PHONY: venv install develop setup dev release format lint test clean distclean lock sync \
		install-go install-whatsapp-bridge build-whatsapp-bridge \
		run-whatsapp-bridge docker-whatsapp-bridge install-tesseract

# Python version to use
PYTHON_VERSION := 3.11

# Enforce virtual environment usage
export PIP_REQUIRE_VIRTUALENV=true

# Auto-detect available tools
HAS_UV := $(shell command -v uv 2> /dev/null)
HAS_PIP := $(shell command -v pip 2> /dev/null)
HAS_NVIDIA := $(shell command -v nvidia-smi 2> /dev/null)
HAS_FFMPEG := $(shell command -v ffmpeg 2> /dev/null)

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

# Install production dependencies using lock file
install:
	uv sync --frozen --no-dev --extra google --extra groq --extra agents \
	        --extra vectors --extra images --extra loaders --extra openai \
			--extra anthropic
	uv pip install querysource
	@echo "Production dependencies installed. Use 'make develop' for development setup."

# Generate lock files (uv only)
lock:
ifdef HAS_UV
	uv lock
else
	@echo "Lock files require uv. Install with: pip install uv"
endif

# Install all dependencies including dev dependencies
develop:
	uv pip install --no-build-isolation -e .
	uv pip install ai-parrot[all,dev]

# Alternative: install without lock file (faster for development)
# Excludes heavy ML deps (torch, tensorflow, whisperx) and uses no-build-isolation for speed
develop-fast:
	uv pip install "Cython==3.0.11" "setuptools>=67.6.1" "wheel>=0.44.0"
	uv pip install --no-build-isolation -e .
	uv pip install ai-parrot[all-fast,dev]
	$(MAKE) build-inplace

# Full ML stack (slow install, requires GPU for optimal performance)
develop-ml:
	uv pip install -e .[vectors,images,whisperx]

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

# Build and publish release
release: lint test clean
	uv build
	uv publish

# Alternative release using flit
release-flit: lint test clean
	flit publish

# Format code
format:
	uv run black parrot

# Lint code
lint:
	uv run pylint --rcfile .pylint parrot/*.py
	uv run black --check parrot

# Run tests with coverage
test:
	uv run coverage run -m parrot.tests
	uv run coverage report
	uv run mypy parrot/*.py

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

# Full build using uv
build: clean
	@echo "Building package with uv..."
	uv build

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
bump-patch:
	@python -c "import re; \
	content = open('parrot/version.py').read(); \
	version = re.search(r'__version__ = \"(.+)\"', content).group(1); \
	parts = version.split('.'); \
	parts[2] = str(int(parts[2]) + 1); \
	new_version = '.'.join(parts); \
	new_content = re.sub(r'__version__ = \".+\"', f'__version__ = \"{new_version}\"', content); \
	open('parrot/version.py', 'w').write(new_content); \
	print(f'Version bumped to {new_version}')"

bump-minor:
	@python -c "import re; \
	content = open('parrot/version.py').read(); \
	version = re.search(r'__version__ = \"(.+)\"', content).group(1); \
	parts = version.split('.'); \
	parts[1] = str(int(parts[1]) + 1); \
	parts[2] = '0'; \
	new_version = '.'.join(parts); \
	new_content = re.sub(r'__version__ = \".+\"', f'__version__ = \"{new_version}\"', content); \
	open('parrot/version.py', 'w').write(new_content); \
	print(f'Version bumped to {new_version}')"

bump-major:
	@python -c "import re; \
	content = open('parrot/version.py').read(); \
	version = re.search(r'__version__ = \"(.+)\"', content).group(1); \
	parts = version.split('.'); \
	parts[0] = str(int(parts[0]) + 1); \
	parts[1] = '0'; \
	parts[2] = '0'; \
	new_version = '.'.join(parts); \
	new_content = re.sub(r'__version__ = \".+\"', f'__version__ = \"{new_version}\"', content); \
	open('parrot/version.py', 'w').write(new_content); \
	print(f'Version bumped to {new_version}')"

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

help:
	@echo "Available targets:"
	@echo "  venv              - Create virtual environment"
	@echo "  install           - Install production dependencies"
	@echo "  develop           - Install development dependencies"
	@echo "  develop-fast      - Fast dev install (no torch/tensorflow/whisperx)"
	@echo "  develop-ml        - Install heavy ML stack (torch, tensorflow, whisperx)"
	@echo "  install-whisperx  - Install WhisperX with system dependencies"
	@echo "  test-whisperx     - Test WhisperX installation"
	@echo "  check-deps        - Check system dependencies"
	@echo "  cuda-info         - Show GPU/CUDA information"
	@echo "  build             - Build package"
	@echo "  release           - Build and publish package"
	@echo "  test              - Run tests"
	@echo "  format            - Format code"
	@echo "  lint              - Lint code"
	@echo "  clean             - Clean build artifacts"
	@echo "  install-uv        - Install uv for faster workflows"
	@echo "  install-go        - Install Go toolchain"
	@echo "  install-genmedia  - Install GenMedia MCP Server"
	@echo "  install-tesseract - Install Tesseract OCR for Docling"
	@echo ""
	@echo "WhatsApp Bridge:"
	@echo "  install-whatsapp-bridge  - Install WhatsApp Bridge dependencies"
	@echo "  build-whatsapp-bridge    - Build WhatsApp Bridge binary"
	@echo "  run-whatsapp-bridge      - Run WhatsApp Bridge locally"
	@echo "  docker-whatsapp-bridge   - Build and run WhatsApp Bridge in Docker"
	@echo ""
	@echo "WhisperX specific:"
	@echo "  install-system-deps    - Install FFmpeg and CUDA dependencies"
	@echo "  test-whisperx-transcribe - Test WhisperX model loading"
	@echo ""
	@echo "Current setup: Python $(PYTHON_VERSION)"
