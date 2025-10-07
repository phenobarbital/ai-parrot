from typing import (
    Union,
    Optional,
    Callable,
    Dict,
    Any,
    get_origin,
    get_args
)
import inspect
from pathlib import Path
from pydantic import BaseModel
import aiofiles
import pandas as pd
from navconfig import BASE_DIR
from asyncdb import AsyncDB
from datamodel.parsers.json import json_encoder, json_decoder  # pylint: disable=E0611
from querysource.conf import default_dsn
from querysource.queries.qs import QS
from ..conf import AGENTS_DIR, AGENTS_BOTS_PROMPT_DIR
from .toolkit import AbstractToolkit
from ..exceptions import ToolError  # pylint: disable=E0611 # noqa


def is_collection_model(structured_obj: type) -> bool:
    """
    Determine if a BaseModel is a collection container (single instance with records field)
    or a direct list model (List[SomeModel]).

    Args:
        structured_obj: The class/type to inspect

    Returns:
        bool: True if it's a collection container, False if it's a direct list
    """
    # Check if it's a List type annotation like List[SomeModel]
    origin = get_origin(structured_obj)
    if origin is list or origin is Union:
        return False

    # Check if it's a BaseModel subclass with a 'records' field
    if inspect.isclass(structured_obj) and issubclass(structured_obj, BaseModel):
        # Get model fields
        if hasattr(structured_obj, 'model_fields'):
            fields = structured_obj.model_fields
        else:
            # Fallback for older Pydantic versions
            fields = getattr(structured_obj, '__fields__', {})

        # Check if it has a 'records' field that's a list
        if 'records' in fields:
            field_info = fields['records']
            field_type = field_info.annotation if hasattr(field_info, 'annotation') else field_info.type_
            return get_origin(field_type) is list

    return False

def get_model_from_collection(collection_model: type) -> type:
    """
    Extract the individual record model from a collection container model.

    Args:
        collection_model: Collection model like VisitsByManagerOutput

    Returns:
        type: Individual record model like VisitsByManagerRecord
    """
    if hasattr(collection_model, 'model_fields'):
        fields = collection_model.model_fields
    else:
        fields = getattr(collection_model, '__fields__', {})

    if 'records' in fields:
        field_info = fields['records']
        field_type = field_info.annotation if hasattr(field_info, 'annotation') else field_info.type_
        args = get_args(field_type)
        if args:
            return args[0]  # Return the type inside List[Type]

    raise ValueError(
        f"Could not extract record model from {collection_model}"
    )


class QueryToolkit(AbstractToolkit):
    """Abstract base class for DB Queries-like Toolkits.

    Use this class to define a toolkit for interacting with a database
    using a structured query approach. It provides methods for executing
    queries, handling results, and managing database connections.

    This class provides a foundation for DB Queries-like toolkits, including
    common configurations and methods for interacting with the database.
    It is designed to be extended by specific toolkits that implement
    functionality related to DB Queries-like operations.
    """

    def __init__(
        self,
        dsn: str = None,
        schema: str = None,
        credentials: Optional[Dict[str, Any]] = None,
        driver: Optional[str] = 'pg',
        program: Optional[str] = '',
        agent_id: Optional[str] = None,
        **kwargs
    ):
        """Initialize the QueryToolkit.

        Args:
            dsn: Default database connection string
            schema: Database schema to use
            **kwargs: Additional configuration options
        """
        super().__init__(**kwargs)
        self.default_dsn = dsn or default_dsn
        self.schema = schema or 'public'
        self.driver = driver
        self.credentials = credentials or {}
        self._db: Optional[AsyncDB] = None
        self._json_encoder = json_encoder
        self._json_decoder = json_decoder
        self.program = program
        self.agent_id = agent_id or 'default_agent'
        # get Database Driver:
        self._db = self._get_driver()

    def _set_program(self, program: str):
        """Set the program slug for the toolkit.

        Args:
            program: The program slug to set
        """
        self.program = program

    @property
    def program_slug(self) -> str:
        """Get the program slug."""
        return self.program

    def _get_driver(self) -> AsyncDB:
        if self._db is None:
            self._db = AsyncDB(
                self.driver,
                dsn=self.default_dsn,
                params=self.credentials
            )
        return self._db

    async def _open_file(self, file_path: Path) -> str:
        """Open a file and return its content as a string."""
        try:
            async with aiofiles.open(file_path, mode='r', encoding='utf-8') as f:
                content = await f.read()
            return content
        except FileNotFoundError:
            raise FileNotFoundError(
                f"File not found: {file_path}"
            )
        except Exception as e:
            raise Exception(
                f"Error reading file {file_path}: {e}"
            )

    async def _get_prompt(self, prompt_file: str) -> str:
        """Fetch the prompt content from the specified file."""
        prompt_path = AGENTS_BOTS_PROMPT_DIR.joinpath(
            self.agent_id,
            self.program if self.program else '',
            'prompts',
            f"{prompt_file}.txt"
        )
        return await self._open_file(prompt_path)

    async def _get_query(
        self,
        query_name: str
    ) -> str:
        """Fetch a SQL query from the toolkit's queries directory.

        Args:
            query_name: The name of the SQL query file (without extension)

        Returns:
            str: The content of the SQL query file

        Raises:
            FileNotFoundError: If the query file does not exist
        """
        query_path = AGENTS_DIR.joinpath(
            self.agent_id,
            self.program if self.program else '',
            'queries',
            f"{query_name}.sql"
        )
        if not query_path.exists():
            raise FileNotFoundError(
                f"Query file not found: {query_path}"
            )
        return await self._open_file(query_path)

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
        async with await self._db.connection() as conn:  # pylint: disable=E1101  # noqa
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
        if frmt in ('structured', 'json'):
            frmt = 'pandas'  # Default to pandas for structured output
        async with await self._db.connection() as conn:  # pylint: disable=E1101  # noqa
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
                try:
                    if structured_obj is None:
                        raise ValueError(
                            "structured_obj must be provided for structured output"
                        )
                    # Convert DataFrame rows to dictionaries
                    records_data = [row.to_dict() for _, row in result.iterrows()]
                    print(
                        f"Detected collection model: {structured_obj.__name__}"
                    )
                    if is_collection_model(structured_obj):
                        record_model = get_model_from_collection(structured_obj)
                        individual_records = [record_model(**row_dict) for row_dict in records_data]
                        # Create the container model with records
                        return structured_obj(
                            records=individual_records,
                            total_records=len(individual_records)
                        )
                    elif get_origin(structured_obj) is list:
                        # Handle direct list types like List[VisitsByManagerRecord]
                        record_model = get_args(structured_obj)[0]
                        return [record_model(**row_dict) for row_dict in records_data]
                    # Convert each row to the structured object
                    else:
                        for _, row in result.iterrows():
                            data.append(structured_obj(**row.to_dict()))
                        return data
                except Exception as e:
                    raise ValueError(
                        f"Error converting to structured output: {e}"
                    )
            else:
                raise TypeError(
                    f"Unsupported output format: {output_format}"
                )

    async def _get_queryslug(
        self,
        slug: str,
        output_format: str = 'pandas',
        conditions: Optional[Dict[str, Any]] = None,
        structured_obj: Optional[Callable[[Dict[str, Any]], Any]] = None
    ) -> Union[pd.DataFrame, Dict[str, Any]]:
        """Execute a query and return the results in the specified format.

        Args:
            slug: The Query slug for the query
            output_format: Output format ('pandas', 'json', or 'structured')

        Returns:
            Union[pd.DataFrame, Dict]: Query results in the requested format

        Raises:
            Exception: If there's an error executing the query
        """
        qs = QS(slug=slug, conditions=conditions)
        result, error = await qs.query()
        if error:
            raise ToolError(
                f"Error executing query '{slug}': {error}"
            )
        if isinstance(result, pd.DataFrame) and result.empty:
            raise ValueError(
                f"No data found for query '{slug}'."
            )
        elif not result:
            raise ValueError(
                f"No data found for query '{slug}'."
            )
        if isinstance(result, dict):
            result = [result]  # Convert single dict to list for consistency
        if output_format == 'pandas':
            return pd.DataFrame([dict(row) for row in result])
        elif output_format == 'json':
            return json_encoder([dict(row) for row in result])
        elif output_format == 'structured':
            if structured_obj is None:
                raise ValueError(
                    "structured_obj must be provided for structured output"
                )
            if is_collection_model(structured_obj):
                record_model = get_model_from_collection(structured_obj)
                individual_records = [record_model(**row_dict) for row_dict in result]
                # Create the container model with records
                return structured_obj(
                    records=individual_records,
                    total_records=len(individual_records)
                )
            elif get_origin(structured_obj) is list:
                # Handle direct list types like List[VisitsByManagerRecord]
                record_model = get_args(structured_obj)[0]
                return [record_model(**row_dict) for row_dict in result]
            else:
                # Convert each row to the structured object
                data = []
                for row in result:
                    data.append(structured_obj(**row))
                return data
        else:
            raise TypeError(
                f"Unsupported output format: {output_format}"
            )
