"""Package data: one ast-grep ``RuleSet`` YAML file per supported language.

This package intentionally ships no Python logic — it exists so the YAML
rule files (``typescript.yaml``, ``php.yaml``, ``rust.yaml``, ``perl.yaml``,
``python.yaml``) can be installed as package data (see
``[tool.setuptools.package-data]`` in ``packages/ai-parrot/pyproject.toml``)
and located at runtime via
:func:`importlib.resources.files("parrot.knowledge.wiki.languages.rules")`.
"""
