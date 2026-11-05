# samplepkg.lazy

A namespace package whose public names resolve lazily.

``__all__`` names nothing that static analysis can see on this module: every export is
fetched from a submodule on first attribute access, exactly like ``parrot.auth``.

## Exports

This package resolves its public names from its submodules, so they are documented on the
pages listed below rather than here.

- `LazyThing`

## Submodules

- [`samplepkg.lazy.impl`](ref:samplepkg.lazy.impl)
