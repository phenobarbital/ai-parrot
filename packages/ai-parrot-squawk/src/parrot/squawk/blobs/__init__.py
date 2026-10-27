"""Content-addressed blob storage for Squawk artifacts."""

from parrot.squawk.blobs.local import LocalDiskBlobStore
from parrot.squawk.blobs.store import BlobMeta, SquawkBlobStore

__all__ = ["BlobMeta", "LocalDiskBlobStore", "SquawkBlobStore"]
