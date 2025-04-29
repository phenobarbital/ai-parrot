"""DB (asyncdb) Extension.
DB connection for any Application.
"""
from asyncdb import AsyncDB


class DBInterface:
    """
    Interface for using database connections in an Application using AsyncDB.
    """

    def get_database(
        self,
        driver: str,
        dsn: str = None,
        params: dict = None,
        timeout: int = 60,
        **kwargs
    ) -> AsyncDB:
        """Get the driver."""
        return AsyncDB(
            driver,
            dsn=dsn,
            params=params,
            timeout=timeout,
            **kwargs
        )
