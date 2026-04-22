"""S3 Overflow Manager — backward-compatible subclass of OverflowStore.

This module preserves the original ``S3OverflowManager`` public name for
callers that imported it directly in FEAT-103. New code should use
``OverflowStore`` from ``parrot.storage.overflow`` and pass any
``FileManagerInterface`` implementation.

FEAT-116: dynamodb-fallback-redis — Module 2 (OverflowStore generalization).
"""

from navconfig.logging import logging

from parrot.interfaces.file.s3 import S3FileManager
from parrot.storage.overflow import OverflowStore


class S3OverflowManager(OverflowStore):
    """Back-compat subclass: OverflowStore bound to S3FileManager.

    Preserves the original constructor signature so existing callers do not
    need to change. The class now delegates all behaviour to ``OverflowStore``
    which accepts any ``FileManagerInterface``.

    Args:
        s3_file_manager: Pre-configured ``S3FileManager`` pointing at
            the artifact bucket.
    """

    def __init__(self, s3_file_manager: S3FileManager) -> None:
        super().__init__(file_manager=s3_file_manager)
        # Override logger name to maintain log-line continuity with FEAT-103.
        self.logger = logging.getLogger("parrot.storage.S3OverflowManager")
