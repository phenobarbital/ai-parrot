"""BOE (Boletin Oficial del Estado) integration for the Legal Norms Graph.

Houses the consolidated-legislation XML parser (``parser.py``) and its
Pydantic record models (``models.py``), the ``BOEDataSource``
``ExtractDataSource`` implementation (``datasource.py``), and the
``sync_boe`` entrypoint (``sync.py``) for FEAT-449 Sprint 1.

Importing this package registers ``"boe"`` with ``DataSourceFactory`` at
import time, so ``OntologyRefreshPipeline`` can resolve it without any
factory modification.
"""

from parrot_loaders.extractors.factory import DataSourceFactory

from .datasource import BOEDataSource
from .hashing import HASH_NORM_VERSION, normalize_for_hash, seal_hash
from .sync import sync_boe

DataSourceFactory.register_api_source("boe", BOEDataSource)

__all__ = [
    "HASH_NORM_VERSION",
    "BOEDataSource",
    "normalize_for_hash",
    "seal_hash",
    "sync_boe",
]
