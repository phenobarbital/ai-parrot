# TASK-2490: README & Makefile

**Feature**: FEAT-464 — Matrix Swarm Sample
**Spec**: `sdd/specs/matrix-swarm-sample.spec.md`
**Status**: pending
**Priority**: medium
**Estimated effort**: S (< 2h)
**Depends-on**: TASK-2488, TASK-2489
**Assigned-to**: unassigned

---

## Context

> This task creates the user-facing documentation and convenience tooling:
> a step-by-step README that takes a user from `git clone` to 4 agents live
> on Matrix, and a Makefile with targets for the full lifecycle.
>
> Implements Spec Module 4 (README & Makefile).

---

## Scope

- Create `examples/matrix_swarm/README.md` — step-by-step quickstart guide
  covering prerequisites, bootstrap, env configuration, running the demo,
  interacting with agents, and troubleshooting.
- Create `examples/matrix_swarm/Makefile` — convenience targets: `setup`,
  `start`, `stop`, `logs`, `demo`, `clean`.

**NOT in scope**:
- Agent definitions / .env.example (TASK-2488)
- Swarm config / demo script (TASK-2489)
- Tests (TASK-2491)
- Updates to `examples/matrix_crew/MATRIX_CREW_GUIDE.md` (FEAT-463)

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `examples/matrix_swarm/README.md` | CREATE | Step-by-step quickstart guide |
| `examples/matrix_swarm/Makefile` | CREATE | Convenience targets for lifecycle |

---

## Codebase Contract (Anti-Hallucination)

> **CRITICAL**: This section contains VERIFIED references to existing files and commands.
> Use these paths and commands VERBATIM — do not invent alternatives.

### Verified External References

```bash
# Docker compose stack (FEAT-463) — at repo root
docker-compose.matrix.yml           # Synapse + Postgres + Element + bridges

# Bootstrap script (FEAT-463) — at repo root
scripts/matrix/bootstrap.sh         # 6-step automated setup
# Supports: --dry-run, --bridges flags

# Docker config directory
docker/matrix/                      # synapse/, postgres/, element/, bridges/, .env.example

# The demo script (created by TASK-2489)
examples/matrix_swarm/swarm_demo.py  # python swarm_demo.py [--config CONFIG] [--agents AGENTS]
```

### Does NOT Exist

- ~~`examples/matrix_swarm/docker-compose.yml`~~ — the compose file is at the REPO ROOT (`docker-compose.matrix.yml`), NOT inside the sample directory
- ~~`examples/matrix_swarm/bootstrap.sh`~~ — the bootstrap script is at `scripts/matrix/bootstrap.sh`, NOT inside the sample directory
- ~~`make install`~~ — not a target; use `uv pip install -e ".[all]"` or `pip install ai-parrot[all]`

---

## Implementation Notes

### README Structure

The README should follow this outline:

```markdown
# Matrix Swarm Sample — Multi-Provider Agent Demo

## Overview
Brief: 4 agents, 4 LLM providers, collaborating via Matrix.

## Prerequisites
- Docker + Docker Compose (≥24.0)
- Python 3.11+
- uv (or pip)
- API keys for: OpenAI, Anthropic, Google GenAI, Nvidia NIM

## Quick Start

### 1. Install AI-Parrot
    uv pip install -e "../../[all]"

### 2. Bootstrap the Matrix Stack
    cd ../../  # repo root
    bash scripts/matrix/bootstrap.sh
    # or: make -C examples/matrix_swarm setup

### 3. Start the Matrix Homeserver
    docker compose -f docker-compose.matrix.yml up -d
    # or: make -C examples/matrix_swarm start

### 4. Configure Environment
    cp .env.example .env
    # Edit .env with your API keys and Matrix tokens

### 5. Run the Demo
    python swarm_demo.py
    # or: make -C examples/matrix_swarm demo

### 6. Interact
    Open http://localhost:8080 (Element Web), sign in, find the swarm room

## Architecture
Brief diagram of agent → LLM → Matrix flow

## Agent Profiles
Table of 4 agents with roles and providers

## Environment Variables
Table of all 7 vars with descriptions and where to find values

## Makefile Targets
Table of targets with descriptions

## Troubleshooting
Common issues: API key errors, Docker not running, port conflicts, room not found

## See Also
Links to MATRIX_CREW_GUIDE.md, docker-compose.matrix.yml, etc.
```

### Makefile Targets

```makefile
# All targets should reference paths relative to repo root
REPO_ROOT := $(shell git rev-parse --show-toplevel)
COMPOSE_FILE := $(REPO_ROOT)/docker-compose.matrix.yml

.PHONY: setup start stop logs demo clean

setup:      ## Bootstrap the Matrix homeserver (first-time setup)
	bash $(REPO_ROOT)/scripts/matrix/bootstrap.sh

start:      ## Start the Matrix stack (Synapse + Postgres + Element)
	docker compose -f $(COMPOSE_FILE) up -d

stop:       ## Stop the Matrix stack
	docker compose -f $(COMPOSE_FILE) stop

logs:       ## Tail logs from all Matrix services
	docker compose -f $(COMPOSE_FILE) logs -f

demo:       ## Run the swarm demo (requires .env with API keys)
	python swarm_demo.py

clean:      ## Stop and remove all Matrix containers + volumes
	docker compose -f $(COMPOSE_FILE) down -v
```

### Key Constraints

- All paths in README and Makefile must be correct relative to
  `examples/matrix_swarm/` — the compose file and bootstrap script are at
  the REPO ROOT, not in the sample directory.
- README must include links to each provider's API key creation page.
- Use Makefile `help` target pattern (if included) based on `##` comments.
- The Makefile must use tabs for indentation (make requirement).

### References in Codebase

- `examples/matrix_crew/MATRIX_CREW_GUIDE.md` — existing comprehensive guide (reference but don't modify)
- `docker-compose.matrix.yml` — compose services and ports
- `scripts/matrix/bootstrap.sh` — bootstrap flags and output format
- `docker/matrix/.env.example` — existing env template for docker stack

---

## Acceptance Criteria

- [ ] `examples/matrix_swarm/README.md` exists with all sections: prerequisites, setup, configure, run, interact, troubleshoot
- [ ] README references correct paths: `docker-compose.matrix.yml` (repo root), `scripts/matrix/bootstrap.sh` (repo root)
- [ ] README includes links to API key creation pages for all 4 providers
- [ ] `examples/matrix_swarm/Makefile` exists with targets: `setup`, `start`, `stop`, `logs`, `demo`, `clean`
- [ ] Makefile targets use correct paths relative to repo root
- [ ] Makefile uses tabs (not spaces) for recipe indentation
- [ ] `make -n -C examples/matrix_swarm setup start stop logs demo clean` reports all targets (dry-run)

---

## Test Specification

```python
# examples/matrix_swarm/tests/test_swarm_sample.py (subset)
import re
from pathlib import Path

SAMPLE_DIR = Path(__file__).parent.parent


def test_readme_exists():
    """README.md exists and has expected sections."""
    readme = (SAMPLE_DIR / "README.md").read_text()
    for section in ["Prerequisites", "Quick Start", "Troubleshooting"]:
        assert section.lower() in readme.lower(), f"Missing section: {section}"


def test_makefile_targets():
    """Makefile has all required targets."""
    makefile = (SAMPLE_DIR / "Makefile").read_text()
    for target in ["setup", "start", "stop", "logs", "demo", "clean"]:
        assert re.search(rf"^{target}\s*:", makefile, re.MULTILINE), (
            f"Missing target: {target}"
        )
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at the path listed above for full context
2. **Check dependencies** — TASK-2488 and TASK-2489 must be complete
3. **Verify the Codebase Contract** — before writing anything:
   - Confirm `docker-compose.matrix.yml` exists at repo root
   - Confirm `scripts/matrix/bootstrap.sh` exists and note its flags
   - Read `examples/matrix_crew/MATRIX_CREW_GUIDE.md` for style reference
   - Confirm `swarm_demo.py` argparse flags (from TASK-2489)
4. **Update status** in `sdd/tasks/index/matrix-swarm-sample.json` → `"in-progress"`
5. **Implement** following the scope and notes above
6. **Verify** all acceptance criteria are met
7. **Move this file** to `sdd/tasks/completed/TASK-2490-readme-and-makefile.md`
8. **Update index** → `"done"`
9. **Fill in the Completion Note** below

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**: <session or agent ID>
**Date**: YYYY-MM-DD
**Notes**: What was implemented, any deviations from scope, issues encountered.

**Deviations from spec**: none | describe if any
