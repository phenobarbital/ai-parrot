---
id: F002
query_id: Q002
type: tree
intent: Inventory remaining files under parrot/forms/
executed_at: 2026-05-28T13:11:03+02:00
depth: 0
---

# F002 — parrot/forms/ still contains 25 source files (~280K)

## Summary

The directory holds the legacy form implementation: top-level modules
(`schema.py`, `validators.py`, `cache.py`, `storage.py`, `registry.py`,
`constraints.py`, `options.py`, `style.py`, `types.py`), plus three
subpackages (`extractors/` with 4 modules, `renderers/` with 4 modules
+ a Jinja2 template, and `tools/` with 3 modules). All are real
implementation files, mirrors of what now exists in
`parrot_formdesigner.*` per FEAT-152.

## Citations

- path: `packages/ai-parrot/src/parrot/forms/`
  lines: —
  excerpt: |
    cache.py        constraints.py    options.py     style.py        types.py
    schema.py       validators.py     registry.py    storage.py      __init__.py
    extractors/
      __init__.py    jsonschema.py    pydantic.py    yaml.py    tool.py
    renderers/
      __init__.py    base.py    adaptive_card.py    html5.py    jsonschema.py
      templates/form.html.j2
    tools/
      __init__.py    create_form.py    database_form.py    request_form.py

## Notes

The Jinja2 template `renderers/templates/form.html.j2` is registered as
package-data in `packages/ai-parrot/pyproject.toml:542`
(`"parrot.forms.renderers" = ["templates/*.j2"]`). Removing the
directory also requires removing that entry. See F004.
