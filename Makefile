# Modern Makefile using uv for fast Python package management

.PHONY: venv install develop setup dev release format lint test clean distclean lock sync

# Python version to use
PYTHON_VERSION := 3.11

# Auto-detect available tools
HAS_UV := $(shell command -v uv 2> /dev/null)
HAS_PIP := $(shell command -v pip 2> /dev/null)

# Create virtual environment
venv:
	uv venv --python $(PYTHON_VERSION) .venv
	@echo 'run `source .venv/bin/activate` to start develop with Parrot'

# Generate lock files (uv only)
lock:
ifdef HAS_UV
	uv lock
else
	@echo "Lock files require uv. Install with: pip install uv"
endif

# Install uv for faster workflows
install-uv:
	curl -LsSf https://astral.sh/uv/install.sh | sh
	@echo "uv installed! You may need to restart your shell or run 'source ~/.bashrc'"
	@echo "Then re-run make commands to use faster uv workflows"

# Install production dependencies using lock file
install:
	uv sync --frozen --no-dev --extra google --extra milvus --extra groq --extra agents --extra vector --extra images --extra loaders --extra openai --extra anthropic

# Install all dependencies including dev dependencies
develop:
	uv sync --frozen --extra all --extra dev

# Alternative: install without lock file (faster for development)
develop-fast:
	uv pip install -e .[all,dev]

# Setup development environment from requirements file (if you still have one)
setup:
	uv pip install -r requirements/requirements-dev.txt

# Install in development mode using flit (if you want to keep flit)
dev:
	uv pip install flit
	flit install --symlink

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

# Update all dependencies
update:
	uv lock --upgrade

# Show project info
info:
	uv tree

# Clean build artifacts
clean:
	rm -rf build/
	rm -rf dist/
	rm -rf *.egg-info/
	find . -type d -name __pycache__ -delete
	find . -type f -name "*.pyc" -delete

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

help:
	@echo "Available targets:"
	@echo "  venv         - Create virtual environment"
	@echo "  install      - Install production dependencies"
	@echo "  develop      - Install development dependencies"
	@echo "  build        - Build package"
	@echo "  release      - Build and publish package"
	@echo "  test         - Run tests"
	@echo "  format       - Format code"
	@echo "  lint         - Lint code"
	@echo "  clean        - Clean build artifacts"
	@echo "  detect-tools - Show detected tools"
	@echo "  install-uv   - Install uv for faster workflows"
	@echo ""
	@echo "Current setup: $(TOOL_INFO)"
