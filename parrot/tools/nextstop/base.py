from typing import Optional, Callable, Dict, Any, Union
import pandas as pd
from asyncdb import AsyncDB
from datamodel.parsers.json import json_encoder, json_decoder  # pylint: disable=E0611
from querysource.conf import default_dsn
from ..toolkit import AbstractToolkit, tool_schema


class BaseNextStop(AbstractToolkit):
    """Abstract base class for NextStop toolkits.

    This class provides a foundation for NextStop toolkits, including
    common configurations and methods for interacting with the database.
    It is designed to be extended by specific toolkits that implement
    functionality related to NextStop operations.
    """

    def __init__(self, dsn: str = None, program: str = None, **kwargs):
        """Initialize the StoreInfo toolkit.

        Args:
            dsn: Default database connection string
            **kwargs: Additional configuration options
        """
        super().__init__(**kwargs)
        self.default_dsn = dsn or default_dsn
        self.program = program or 'hisense'
        self._json_encoder = json_encoder
        self._json_decoder = json_decoder

    async def _fetch_one(
        self,
        query: str,
        output_format: str = 'pandas',
        structured_obj: Optional[Callable[[Dict[str, Any]], Any]] = None
    ) -> Union[pd.DataFrame, Dict[str, Any]]:
        """Fetch a single record based on the provided query.

        Args:
            query: The SQL query string to fetch the record
            output_format: Output format ('pandas' or 'dict')

        Returns:
            Union[pd.DataFrame, Dict]: Record in the requested format

        Raises:
            Exception: If there's an error executing the query
        """
        frmt = output_format.lower()
        if frmt == 'structured':
            frmt = 'native'  # Default to json for structured output
        db = AsyncDB('pg', dsn=self.default_dsn)
        async with await db.connection() as conn:  # pylint: disable=E1101  # noqa
            conn.output_format(frmt)
            result, error = await conn.query(query)
            if error:
                raise Exception(
                    f"Error fetching record: {error}"
                )
            if isinstance(result, pd.DataFrame) and result.empty:
                raise ValueError(
                    "No data found for the provided query."
                )
            elif not result:
                raise ValueError(
                    "No data found for the provided query."
                )
            if output_format == "pandas":
                # return the first row as a DataFrame
                return result.iloc[0:1]
            elif output_format == "json":
                return json_encoder(
                    result.to_dict(orient='records')
                )
            elif output_format == "structured":
                # Convert to Pydantic model
                return structured_obj(**result[0])
            else:
                raise TypeError(
                    f"Unsupported output format: {output_format}"
    )

    async def _get_dataset(
        self,
        query: str,
        output_format: str = 'pandas',
        structured_obj: Optional[Callable[[Dict[str, Any]], Any]] = None
    ) -> Union[pd.DataFrame, Dict[str, Any]]:
        """Fetch a dataset based on the provided query.

        Args:
            query: The SQL query string to fetch the dataset
            output_format: Output format ('pandas' or 'dict')

        Returns:
            Union[pd.DataFrame, Dict]: Dataset in the requested format

        Raises:
            Exception: If there's an error executing the query
        """
        frmt = output_format.lower()
        if frmt == 'structured':
            frmt = 'pandas'  # Default to pandas for structured output
        db = AsyncDB('pg', dsn=self.default_dsn)
        async with await db.connection() as conn:  # pylint: disable=E1101  # noqa
            conn.output_format(frmt)
            result, error = await conn.query(query)
            if error:
                raise Exception(
                    f"Error fetching dataset: {error}"
                )
            if result.empty:
                raise ValueError(
                    "No data found for the provided query."
                )
            if output_format == "pandas":
                return result
            elif output_format == "json":
                return json_encoder(
                    result.to_dict(orient='records')
                )
            elif output_format == "structured":
                # Convert DataFrame to Pydantic models
                data = []
                for _, row in result.iterrows():
                    data.append(structured_obj(**row.to_dict()))
                return data
            else:
                raise TypeError(
                    f"Unsupported output format: {output_format}"
                )
