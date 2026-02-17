# 🧠 AI-Optimized Project Context: Antigravity Workspace

## 1. Executive Summary & Core Mission

**Core Philosophy: "Cognitive-First" & "Artifact-First"**
The agent must not just execute tasks but *think* like a senior engineer. This is achieved through a mandatory "Think-Act-Reflect" loop.

1.  **Think (Plan):** Before any complex coding, the agent MUST generate a plan in `artifacts/plan_[task_id].md`. This enforces structured thinking.
2.  **Act (Execute):** Write clean, modular, and well-documented code following the project's strict standards.
3.  **Reflect (Verify):** The agent is responsible for verifying its work, primarily by running `pytest` after making changes. All evidence (logs, test results) is stored in `artifacts/logs/`.

---

## 2. Environment, DevOps, and Project Structure

*   `.agent/`: Core AI rules and persona. **(Crucial for agent behavior)**.
    *   `rules.md`: The Agent's Constitution and Directive.
    *   `rules/python-development.md`: Specific standards for Python development (uv, venv, libraries).
*   `artifacts/`: All agent-generated outputs (plans, logs, screenshots).
*   `tests/`: The `pytest` test suite.
