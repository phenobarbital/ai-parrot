from typing import Union, Optional, Callable, Dict, Any, get_origin, get_args
import inspect
from pathlib import Path
from pydantic import BaseModel
import aiofiles
import pandas as pd
from asyncdb import AsyncDB
from datamodel.parsers.json import json_encoder, json_decoder  # pylint: disable=E0611
from querysource.conf import default_dsn
from ..toolkit import AbstractToolkit
from ...conf import AGENTS_DIR


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
        if (args := get_args(field_type)):
            return args[0]  # Return the type inside List[Type]

    raise ValueError(f"Could not extract record model from {collection_model}")


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
        self.program = program or ''
        self.agent_name: str = kwargs.get('agent_name', 'nextstop')
        self._json_encoder = json_encoder
        self._json_decoder = json_decoder

    def set_program(self, program: str):
        """Set the program slug for the toolkit.

        Args:
            program: The program slug to set
        """
        self.program = program

    @property
    def program_slug(self) -> str:
        """Get the program slug."""
        return self.program

    async def _open_file(self, file_path: Path) -> str:
        """Open a file and return its content as a string."""
        try:
            async with aiofiles.open(file_path, mode='r', encoding='utf-8') as f:
                content = await f.read()
            return content
        except FileNotFoundError as e:
            raise FileNotFoundError(
                f"File not found: {file_path}"
            ) from e
        except Exception as e:
            raise RuntimeError(
                f"Error reading file {file_path}: {e}"
            ) from e

    async def _get_prompt(self, prompt_file: str) -> str:
        """Fetch the prompt content from the specified file."""
        print('AQUI > ', AGENTS_DIR)
        prompt_path = AGENTS_DIR.joinpath(
            self.agent_name,
            self.program,
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
            self.agent_name,
            self.program,
            'queries',
            f"{query_name}.sql"
        )
        if not query_path.exists():
            raise FileNotFoundError(f"Query file not found: {query_path}")
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
        db = AsyncDB('pg', dsn=self.default_dsn)
        async with await db.connection() as conn:  # pylint: disable=E1101  # noqa
            conn.output_format(frmt)
            result, error = await conn.query(query)
            if error:
                raise RuntimeError(
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
        if frmt in {'structured', 'json'}:
            frmt = 'pandas'  # Default to pandas for structured output
        db = AsyncDB('pg', dsn=self.default_dsn)
        async with await db.connection() as conn:  # pylint: disable=E1101  # noqa
            conn.output_format(frmt)
            result, error = await conn.query(query)
            if error:
                raise RuntimeError(
                    f"Error fetching dataset: {error}"
                )
            if result.empty:
                raise ValueError(
                    "No data found for the provided query."
                )
            if output_format == "pandas":
                return result
            if output_format == "json":
                return json_encoder(
                    result.to_dict(orient='records')
                )
            if output_format == "structured":
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
