---
id: F010
query_id: Q016
type: grep
intent: Identify the existing sibling-package redirector mechanism in core.
executed_at: 2026-05-28T00:00:00Z
duration_ms: 100
parent_id: null
depth: 0
---

# F010 — All existing siblings use `parrot_<name>.*` + sys.meta_path redirector

## Summary

Every sibling distribution (`ai-parrot-tools`, `ai-parrot-loaders`,
`parrot-formdesigner`, `ai-parrot-pipelines`) ships under its own
top-level (`parrot_tools.*`, `parrot_loaders.*`, `parrot_formdesigner.*`,
`parrot_pipelines.*`). Core's `parrot.tools.__init__.py` and
`parrot.loaders.__init__.py` install a `sys.meta_path` finder
(`_ParrotToolsRedirector`, `_ParrotLoadersRedirector`) that transparently
redirects `from parrot.tools.<x> import Y` to `parrot_tools.<x>` when
the submodule does not exist locally. This is the convention FEAT-201
explicitly breaks (the user wants modules to live directly under
`parrot.{embeddings,stores,rerankers}.*` via namespace extension, with
no redirector).

## Citations

- path: `packages/ai-parrot/src/parrot/tools/__init__.py`
  lines: 1-15
  symbol: `parrot.tools` module docstring + redirector intent
  excerpt: |
    """
    Tools infrastructure for building Agents.

    Resolution chain for tool imports:
    1. Core tools (always available — defined directly in this module)
    2. parrot_tools (ai-parrot-tools installed package)
    3. plugins.tools (user/deploy-time plugin directory)
    4. TOOL_REGISTRY (declarative registry from ai-parrot-tools)
    5. Legacy dynamic_import_helper (backward-compat submodule resolution)

    Submodule redirector:
      ``from parrot.tools.prophetforecast import X`` is transparently redirected
      to ``from parrot_tools.prophetforecast import X`` when no local submodule
      exists.  This is done via a sys.meta_path finder installed at import time.
    """

- path: `packages/ai-parrot/src/parrot/tools/__init__.py`
  lines: 50-65
  symbol: `_ParrotToolsRedirector` (sys.meta_path finder)
  excerpt: |
    class _ParrotToolsRedirector(importlib.abc.MetaPathFinder):
        """Redirect ``parrot.tools.<submodule>`` imports to ``parrot_tools.<submodule>``."""
        _PREFIX = "parrot.tools."
        _RESOLVING: set = set()  # guard against recursion

- path: `packages/ai-parrot/src/parrot/loaders/__init__.py`
  lines: 1-16
  symbol: `parrot.loaders` redirector (mirror pattern)
  excerpt: |
    """
    Document Loaders — load data from different sources for RAG.
    ...
    Submodule redirector:
      ``from parrot.loaders.audio import X`` is transparently redirected
      to ``from parrot_loaders.audio import X`` when no local submodule
      exists.  This is done via a sys.meta_path finder installed at import time.
    """

- path: `packages/parrot-formdesigner/src/parrot_formdesigner/__init__.py`
  lines: 1-9
  symbol: parrot_formdesigner top-level
  excerpt: |
    """parrot-formdesigner — Form design and rendering for AI-Parrot.

    Top-level imports are intentionally minimal. Consumers import from
    submodules:

        from parrot_formdesigner.core import FormSchema
        from parrot_formdesigner.api import setup_form_api
        from parrot_formdesigner.ui import setup_form_ui
    """

## Notes

- The user's decision (PEP 420 / namespace extension instead of
  parrot_<name>.* + redirector) means FEAT-201 does NOT need to install
  any meta_path finder in core. Imports such as
  `from parrot.stores.pgvector import PgVectorStore` resolve directly
  through Python's namespace-package machinery once the host's
  `parrot.stores.__init__.py` extends `__path__` (see F001 notes).
- This is **lighter-weight** than the existing precedent (no
  redirector, no registry script), at the cost of being a different
  convention from the other three sibling packages.
