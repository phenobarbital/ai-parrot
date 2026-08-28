.PHONY: setup start stop logs demo clean help

# Paths relative to repo root (obtained via git)
REPO_ROOT := $(shell git rev-parse --show-toplevel)
COMPOSE_FILE := $(REPO_ROOT)/docker-compose.matrix.yml
BOOTSTRAP_SCRIPT := $(REPO_ROOT)/scripts/matrix/bootstrap.sh
SAMPLE_DIR := $(REPO_ROOT)/examples/matrix_swarm

# Default target: show help
help:
	@echo "Matrix Swarm Sample — Make Targets"
	@echo ""
	@grep -E '^[a-zA-Z_-]+:.*?## ' $(MAKEFILE_LIST) | sed 's/Makefile://' | awk 'BEGIN {FS = ":.*?## "}; {printf "  make %-20s %s\n", $$1, $$2}'
	@echo ""
	@echo "Run from repo root: cd $(REPO_ROOT)"
	@echo "Or run from sample dir: make -C examples/matrix_swarm <target>"

setup: ## Bootstrap the Matrix homeserver (first-time setup only)
	@echo "🚀 Bootstrapping Matrix stack..."
	bash $(BOOTSTRAP_SCRIPT)
	@echo "✓ Bootstrap complete. Run 'make start' next."

start: ## Start the Matrix stack (Synapse + Postgres + Element + bridges)
	@echo "🐳 Starting Matrix services..."
	docker compose -f $(COMPOSE_FILE) up -d
	@echo "✓ Services starting. Wait 10-30s for Synapse to be ready."
	@echo "  Element Web: http://localhost:8080"
	@echo "  Synapse: http://localhost:8008"

stop: ## Stop the Matrix stack (services remain, data preserved)
	@echo "⏹️  Stopping Matrix services..."
	docker compose -f $(COMPOSE_FILE) stop
	@echo "✓ Services stopped. Volumes preserved. Run 'make start' to resume."

logs: ## Tail logs from all Matrix services (Ctrl+C to exit)
	@echo "📋 Tailing logs from $(COMPOSE_FILE)..."
	docker compose -f $(COMPOSE_FILE) logs -f

demo: ## Run the swarm demo (requires .env configured with API keys)
	@if [ ! -f "$(SAMPLE_DIR)/.env" ]; then \
		echo "❌ .env not found. Run:"; \
		echo "  cd $(SAMPLE_DIR)"; \
		echo "  cp .env.example .env"; \
		echo "  # Edit .env with your API keys"; \
		exit 1; \
	fi
	@echo "🤖 Starting swarm demo..."
	@echo "   Check Element at http://localhost:8080"
	@echo "   Press Ctrl+C to stop"
	python $(SAMPLE_DIR)/swarm_demo.py

clean: ## Stop and remove all containers + volumes (CAUTION: data loss)
	@echo "🗑️  WARNING: This will delete all Matrix data!"
	@echo "   To proceed, run: make clean FORCE=yes"
	@if [ "$(FORCE)" != "yes" ]; then exit 1; fi
	@echo "Removing containers and volumes..."
	docker compose -f $(COMPOSE_FILE) down -v
	@echo "✓ Clean complete. Run 'make setup start' to rebuild."

.DEFAULT_GOAL := help
