---
type: Wiki Overview
title: Run Python Command
id: doc:agent-workflows-run-python-command-md
tags:
- overview
timestamp: '2026-07-14T22:20:21+00:00'
summary: 'description: Run a Python command inside the virtual environment'
---

---
description: Run a Python command inside the virtual environment
---

1. Check if the virtual environment exists in `.venv`.
2. If it does not exist, run `uv venv` to create it.
3. Activate the virtual environment:
   ```bash
   source .venv/bin/activate
   ```
4. Run the desired command.

**Alternative:**
You can use the helper script `scripts/run_in_venv.sh`:
```bash
./scripts/run_in_venv.sh <your_command>
```

**Example:**
```bash
./scripts/run_in_venv.sh python -m pytest tests/
```
