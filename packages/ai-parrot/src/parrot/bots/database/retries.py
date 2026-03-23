from typing import Optional, List, Tuple
import re
from sqlalchemy import text


class QueryRetryConfig:
    """Configuration for SQL query retry mechanism."""

    def __init__(
        self,
        max_retries: int = 3,
        retry_on_errors: List[str] = None,
        sample_data_on_error: bool = True,
        max_sample_rows: int = 3
    ):
        self.max_retries = max_retries
        self.retry_on_errors = retry_on_errors or [
            'InvalidTextRepresentationError',
            'DataError',
            'ProgrammingError',
            'invalid input syntax',
            'column does not exist',
            'relation does not exist',
            'type',
            'cast',
            'convert'
        ]
        self.sample_data_on_error = sample_data_on_error
        self.max_sample_rows = max_sample_rows

class SQLRetryHandler:
    """Handles SQL query retries with error learning."""

    def __init__(self, agent, config: Optional[QueryRetryConfig] = None):
        self.agent = agent
        self.config = config or QueryRetryConfig()
        self.logger = agent.logger

    def _is_retryable_error(self, error: Exception) -> bool:
        """Determine if an error is worth retrying."""
        error_str = str(error).lower()
        error_type = type(error).__name__

        # Check if error type or message contains retryable patterns
        for pattern in self.config.retry_on_errors:
            if pattern.lower() in error_str or pattern.lower() in error_type.lower():
                return True
        return False

    async def _get_sample_data_for_error(self, schema_name: str, table_name: str, column_name: str) -> str:
        """Get sample data from the problematic column."""
        if not self.config.sample_data_on_error:
            return ""

        try:
            sample_query = f'''
            SELECT "{column_name}"
            FROM "{schema_name}"."{table_name}"
            WHERE "{column_name}" IS NOT NULL
            LIMIT {self.config.max_sample_rows};
            '''

            async with self.agent.engine.begin() as conn:
                result = await conn.execute(text(sample_query))
                samples = [row[0] for row in result]

                if samples:
                    return f"Sample values from {column_name}: {samples}"
        except Exception as e:
            self.logger.debug(f"Could not fetch sample data: {e}")

        return ""

    def _extract_table_column_from_error(self, sql_query: str, error: Exception) -> Tuple[Optional[str], Optional[str]]:
        """Extract problematic table and column from SQL and error."""
        try:
            # Try to find table name in FROM clause
            from_match = re.search(r'FROM\s+(?:"?(\w+)"?\.)?"?(\w+)"?', sql_query, re.IGNORECASE)
            table_name = from_match.group(2) if from_match else None

            # Try to find problematic column from error or ORDER BY clause
            error_str = str(error).lower()

            # Look for column in ORDER BY clause (common for type conversion errors)
            order_match = re.search(r'ORDER BY\s+.*?(\w+)', sql_query, re.IGNORECASE)
            column_name = order_match.group(1) if order_match else None

            # Or look for CAST function usage
            cast_match = re.search(r'CAST\([^,]+,\s*[\'"]([^\'"]+)[\'"]', sql_query, re.IGNORECASE)
            if cast_match:
                # Find the column being cast
                cast_col_match = re.search(r'CAST\(\s*(?:REPLACE\([^,]+,\s*)?[\'"]?(\w+)[\'"]?', sql_query, re.IGNORECASE)
                if cast_col_match:
                    column_name = cast_col_match.group(1)

            return table_name, column_name
        except Exception:
            return None, None
