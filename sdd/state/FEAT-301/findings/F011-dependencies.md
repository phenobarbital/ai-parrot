---
id: F011
query: Dependency availability
type: read
---

orjson: declared in ai-parrot pyproject.toml (>=3.9). OK.
markdown_it: NOT declared as direct dependency. Transitive via markdown-it-py (v4.2.0). RISK.
markupsafe: NOT declared as direct dependency. Transitive via Jinja2 (v3.0.3). RISK.
jsonschema: NOT declared in any infographic-related pyproject.toml. Available (v4.26.0). RISK.

All three undeclared deps are available at runtime but should be declared explicitly
in ai-parrot-visualizations pyproject.toml to avoid breakage if transitive deps change.
