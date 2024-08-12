"""DB (asyncdb) Extension.
DB connection for any Application.
"""
from abc import ABCMeta
from asyncdb import AsyncDB



class DBInterface(metaclass=ABCMeta):
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
