---
id: F001
query_id: Q001
type: read
intent: Confirm parrot.forms shim shape and fallback branch
executed_at: 2026-05-28T13:11:03+02:00
depth: 0
---

# F001 — parrot.forms is a TWO-BRANCH shim with local fallback

## Summary

`packages/ai-parrot/src/parrot/forms/__init__.py` (90 lines) is documented as a
"backward-compatible re-export shim" but in practice it has **two branches**:
a `try:` block that imports from `parrot_formdesigner.{core,extractors,renderers,services,tools}`,
and an `except ImportError:` fallback that imports from local modules
(`.constraints`, `.options`, `.schema`, `.style`, `.types`, `.validators`,
`.extractors.pydantic`, `.registry`, `.cache`, `.storage`,
`.tools.{request_form,create_form,database_form}`). The fallback is live code,
not stubs.

## Citations

- path: `packages/ai-parrot/src/parrot/forms/__init__.py`
  lines: 14-71
  symbol: `try` branch
  excerpt: |
    try:
        from parrot_formdesigner.core import (...)
        from parrot_formdesigner.extractors import (...)
        from parrot_formdesigner.renderers import (...)
        from parrot_formdesigner.services import (...)
        from parrot_formdesigner.tools import (...)

- path: `packages/ai-parrot/src/parrot/forms/__init__.py`
  lines: 71-90
  symbol: `except ImportError` fallback
  excerpt: |
    except ImportError:
        from .constraints import (...)
        from .options import FieldOption, OptionsSource
        from .schema import (...)
        from .style import (...)
        from .validators import FormValidator, ValidationResult
        from .extractors.pydantic import PydanticExtractor
        from .registry import FormRegistry, FormStorage
        ...

## Notes

The shim only protects callers that go through `from parrot.forms import …`.
Callers using submodule paths (`parrot.forms.renderers`, `parrot.forms.validators`,
`parrot.forms.extractors.tool`, `parrot.forms.tools`) bypass `__init__.py`
entirely — they always hit the local fallback code, regardless of whether
`parrot-formdesigner` is installed. See F003.
