"""FEAT-878 user stores: backend selection and Redis primitives."""

from .collections import COLLECTION_SWITCH, USER_STORE_COLLECTIONS, CollectionSpec
from .redis_documents import RedisDocumentStore
from .settings import (
    DEFAULT_BACKEND,
    GLOBAL_SWITCH,
    SWITCHES,
    StoreBackend,
    StoreSwitch,
    UserStoreMisconfigured,
    close_user_store_redis,
    default_result_storage,
    documentdb_configured,
    get_user_store_redis,
    implicit_redis_stores,
    key_prefix,
    redis_url,
    resolve_store_backend,
    store_backend_source,
    validate_user_store_settings,
)

__all__ = [
    "COLLECTION_SWITCH",
    "DEFAULT_BACKEND",
    "GLOBAL_SWITCH",
    "SWITCHES",
    "USER_STORE_COLLECTIONS",
    "CollectionSpec",
    "RedisDocumentStore",
    "StoreBackend",
    "StoreSwitch",
    "UserStoreMisconfigured",
    "close_user_store_redis",
    "default_result_storage",
    "documentdb_configured",
    "get_user_store_redis",
    "implicit_redis_stores",
    "key_prefix",
    "redis_url",
    "resolve_store_backend",
    "store_backend_source",
    "validate_user_store_settings",
]
