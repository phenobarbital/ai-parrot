"""Parent document searcher package for FEAT-128 — Parent-Child Retrieval.

This package provides the composable :class:`AbstractParentSearcher` interface
and the default :class:`InTableParentSearcher` implementation that fetches
parent documents from the same vector table as child chunks.

Usage::

    from parrot.stores.parents import AbstractParentSearcher, InTableParentSearcher

    # Default in-table searcher (postgres / pgvector)
    searcher = InTableParentSearcher(store=pg_store)
    parents = await searcher.fetch(['parent-id-1', 'parent-id-2'])
"""
from parrot.stores.parents.abstract import AbstractParentSearcher
from parrot.stores.parents.in_table import InTableParentSearcher

__all__ = [
    'AbstractParentSearcher',
    'InTableParentSearcher',
]
