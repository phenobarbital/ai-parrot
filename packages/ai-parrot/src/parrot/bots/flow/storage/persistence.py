"""PersistenceMixin — DocumentDB persistence for crew/flow results."""

import time
import logging
from typing import Any


class PersistenceMixin:
    """Mixin that adds DocumentDB persistence to crew/flow orchestrators.

    Requires the host class to have a `name` attribute and a `logger`.
    """

    async def _save_result(
        self,
        result: Any,
        method: str,
        *,
        collection: str = "crew_executions",
        **kwargs,
    ) -> None:
        """Save execution result to DocumentDB in background.

        Args:
            result: The execution result (must support `.to_dict()` or `str()`).
            method: Execution method name (e.g. ``"run_flow"``).
            collection: Target DocumentDB collection name.
            **kwargs: Extra fields merged into the saved document.
        """
        logger = getattr(self, "logger", logging.getLogger(__name__))
        try:
            from ....interfaces.documentdb import DocumentDb

            data = {
                "crew_name": getattr(self, "name", "unknown"),
                "method": method,
                "timestamp": time.time(),
                "result": result.to_dict() if hasattr(result, "to_dict") else str(result),
                **kwargs,
            }
            if "user_id" not in data:
                data["user_id"] = "unknown"

            async with DocumentDb() as db:
                await db.write(collection, data)
        except Exception as e:
            logger.warning("Failed to save result to '%s': %s", collection, e)
