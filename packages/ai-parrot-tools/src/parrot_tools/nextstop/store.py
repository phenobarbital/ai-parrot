"""
StoreInfo toolkit for store information and demographic analysis.
"""
from typing import Dict, Any, List, Optional, Union, Literal, Callable
from datetime import datetime, time
from pydantic import BaseModel, Field
import pandas as pd
from ..decorators import tool_schema
from .base import BaseNextStop


# Pydantic models for structured outputs
class StoreBasicInfo(BaseModel):
    """Basic store information model."""
    store_id: str = Field(description="Unique store identifier")
    store_name: Optional[str] = Field(default=None, description="Store name")
    street_address: Optional[str] = Field(default=None, description="Store address")
    city: Optional[str] = Field(default=None, description="City")
    state_name: Optional[str] = Field(default=None, description="State")
    state_code: Optional[str] = Field(default=None, description="State code")
    zipcode: Optional[str] = Field(default=None, description="ZIP code")
    latitude: Optional[float] = Field(default=None, description="Latitude coordinate")
    longitude: Optional[float] = Field(default=None, description="Longitude coordinate")
    account_name: Optional[str] = Field(default=None, description="Account name")


class FootTrafficData(BaseModel):
    """Foot traffic data model."""
    store_id: str = Field(description="Store identifier")
    start_date: datetime = Field(description="Start date of the traffic period")
    avg_visits_per_day: Optional[float] = Field(default=None, description="Average visits per day")
    foottraffic: Optional[int] = Field(default=None, description="Total foot traffic")
    visits_by_day_of_week_monday: Optional[int] = Field(default=None, description="Monday visits")
    visits_by_day_of_week_tuesday: Optional[int] = Field(default=None, description="Tuesday visits")
    visits_by_day_of_week_wednesday: Optional[int] = Field(default=None, description="Wednesday visits")
    visits_by_day_of_week_thursday: Optional[int] = Field(default=None, description="Thursday visits")
    visits_by_day_of_week_friday: Optional[int] = Field(default=None, description="Friday visits")
    visits_by_day_of_week_saturday: Optional[int] = Field(default=None, description="Saturday visits")
    visits_by_day_of_week_sunday: Optional[int] = Field(default=None, description="Sunday visits")


class FootTrafficSearch(BaseModel):
    """Foot traffic search model."""
    state_code: str = Field(description="State code")
    retailer_name: str = Field(description="Retailer name")
    limit: int = Field(default=10, description="Number of results to return")


class FootTrafficInfo(BaseModel):
    """Foot traffic information model."""
    store_id: str = Field(description="Store identifier")
    store_number: Optional[str] = Field(default=None, description="Store number")
    store_name: Optional[str] = Field(default=None, description="Store name")
    state_name: Optional[str] = Field(default=None, description="State name")
    city: Optional[str] = Field(default=None, description="City name")
    state_code: Optional[str] = Field(default=None, description="State code")
    zipcode: Optional[str] = Field(default=None, description="ZIP code")
    street_address: Optional[str] = Field(default=None, description="Street address")
    foottraffic: Optional[int] = Field(default=None, description="Average of foot traffic")

class VisitInfo(BaseModel):
    """Visit information model."""
    # Basic visit info
    form_id: int = Field(default=None, description="Form identifier")
    formid: int = Field(default=None, description="Form ID")
    visit_date: Optional[datetime] = Field(default=None, description="Date of visit")
    visitor_name: Optional[str] = Field(default=None, description="Visitor name")
    visitor_username: Optional[str] = Field(default=None, description="Visitor username")
    visit_timestamp: Optional[datetime] = Field(default=None, description="Visit timestamp")
    visit_length: Optional[float] = Field(default=None, description="Visit length")
    time_in: Optional[time] = Field(default=None, description="Check-in time")
    time_out: Optional[time] = Field(default=None, description="Check-out time")
    store_id: str = Field(description="Store identifier")
    visit_dow: Optional[int] = Field(default=None, description="Day of week (0=Monday)")
    visit_hour: Optional[int] = Field(default=None, description="Hour of visit")
    alt_store: Optional[str] = Field(default=None, description="Alternative store name")
    time_spent_minutes: Optional[float] = Field(default=None, description="Time spent in minutes")
    visit_data: Optional[List[Dict[str, Any]]] = Field(default=None, description="Visit data aggregated")
    # Aggreated questions:
    questions: Optional[Dict[str, List[Dict[str, Any]]]] = Field(
        default=None,
        description="Aggregated visit questions and answers organized by question type"
    )
    # Visitor statistics
    number_of_visits: Optional[int] = Field(default=None, description="Total number of visits by this visitor")
    latest_visit_date: Optional[datetime] = Field(default=None, description="Latest visit date for this visitor")
    visited_stores: Optional[int] = Field(default=None, description="Number of stores visited by this visitor")
    average_hour_visit: Optional[float] = Field(default=None, description="Average hour of visits")
    most_frequent_hour_of_day: Optional[int] = Field(default=None, description="Most frequent hour of day")
    most_frequent_day_of_week: Optional[int] = Field(default=None, description="Most frequent day of week")
    day_of_week: Optional[str] = Field(default=None, description="Day of week name")
    median_visits_per_store: Optional[float] = Field(default=None, description="Median visits per store")
    median_visit_duration: Optional[float] = Field(default=None, description="Median visit duration")

# Input schemas for tools
class StoreInfoInput(BaseModel):
    """Input schema for store information queries."""
    store_id: str = Field(description="The unique identifier of the store")
    program: Optional[str] = Field(
        default=None,
        description="Program slug for the store (e.g., 'hisense', 'epson')"
    )


class FootTrafficInput(BaseModel):
    """Input schema for foot traffic queries."""
    store_id: str = Field(description="The unique identifier of the store")
    output_format: Literal["pandas", "structured"] = Field(
        default="structured",
        description="Output format: 'pandas' for DataFrame, 'structured' for Pydantic models"
    )


class VisitInfoInput(BaseModel):
    """Input schema for visit information queries."""
    store_id: str = Field(description="The unique identifier of the store")
    program_slug: Optional[str] = Field(
        default=None,
        description="Program slug for the store (e.g., 'hisense', 'epson')"
    )
    limit: int = Field(default=10, description="Maximum number of visits to retrieve")
    output_format: Literal["pandas", "structured"] = Field(
        default="structured",
        description="Output format: 'pandas' for DataFrame, 'structured' for Pydantic models"
    )

class VisitQuestionInput(BaseModel):
    """Input schema for visit question queries."""
    store_id: str = Field(description="The unique identifier of the store")
    program_slug: Optional[str] = Field(
        default=None,
        description="Program slug for the store (e.g., 'hisense', 'epson')"
    )
    limit: int = Field(default=5, description="Maximum number of visits to retrieve")

class StoreSearchInput(BaseModel):
    """Input schema for store search queries."""
    city: Optional[str] = Field(default=None, description="City name to search for stores")
    state_name: Optional[str] = Field(default=None, description="US State Name")
    zipcode: Optional[str] = Field(default=None, description="ZIP code")
    limit: int = Field(default=50, description="Maximum number of stores to return")


class DatasetQueryInput(BaseModel):
    """Input schema for custom dataset queries."""
    query: str = Field(description="SQL query to execute")
    output_format: Literal["pandas", "dict"] = Field(
        default="pandas",
        description="Output format: 'pandas' for DataFrame, 'dict' for dictionary"
    )


class StoreInfo(BaseNextStop):
    """Comprehensive toolkit for store information and demographic analysis.

    This toolkit provides tools to:
    1. get_visit_information: Get visit information for an store including recent visit history.
    2. get_store_information: Retrieve comprehensive store information including location and visit statistics
    3. get_foot_traffic: Foot traffic analysis for stores, providing insights into customer behavior
    4. search_stores: Search for stores by location (city, state, zipcode)

    All tools are designed to work asynchronously with database connections and external APIs.
    """
    def _pad_storeid(self, store_id: str , width: int = 4) -> str:
        """Pad the store ID with leading zeros to ensure it has a fixed width.

        Split a store id into prefix + numeric suffix and zero-fill the number.

        Examples:
            pad_store_id("BBY599") -> "BBY0599"
            pad_store_id("BBY4")   -> "BBY0004"
        """
        if self.program != "hisense":
            return store_id.strip()  # No padding needed for other programs

        # Ensure the store_id is a string and strip whitespace
        store_id = str(store_id)
        if not store_id:
            raise ValueError("Store ID cannot be empty")
        s = store_id.strip()
        # extract non-numeric characters as prefix
        prefix = ''.join(filter(str.isalpha, s))
        # extract the suffix from store_id, to get the numeric part:
        s = s.replace(prefix, '', 1)
        if len(s) < width:
            # zero-fill the numeric part to the specified width
            s = s.lstrip('0')  # remove leading zeros first
            numeric_suffix = s.zfill(width)
        else:
            numeric_suffix = s
        return f"{prefix}{numeric_suffix}"

    @tool_schema(FootTrafficInput)
    async def get_foot_traffic(
        self,
        store_id: str,
        output_format: str = "structured"
    ) -> Union[pd.DataFrame, List[FootTrafficData]]:
        """Get foot traffic data for a specific store.
        This method retrieves the foot traffic data for the specified store,
        including the number of visitors and average visits per day.
        """
        sql = await self._get_query("foot_traffic")
        sql = sql.format(store_id=store_id)

        # Fetch the foot traffic data
        try:
            return await self._get_dataset(
                sql,
                output_format=output_format,
                structured_obj=FootTrafficData if output_format == "structured" else None
            )
        except ValueError as ve:
            return f"No Traffic data found for the specified store, error: {ve}"
        except Exception as e:
            return f"Error fetching foot traffic data: {e}"

    @tool_schema(FootTrafficSearch)
    async def get_foot_traffic_average(
        self,
        state_code: str,
        retailer_name: str,
        limit: int = 10,
        output_format: str = "structured"
    ) -> Union[pd.DataFrame, List[FootTrafficInfo]]:
        """Get foot traffic data for a specific store.
        This method retrieves the foot traffic data for the specified store,
        including the number of visitors and average visits per day.
        """
        sql = await self._get_query("foot_traffic_avg")
        sql = sql.format(state_code=state_code, retailer_name=retailer_name, limit=limit)

        # Fetch the foot traffic data
        try:
            return await self._get_dataset(
                sql,
                output_format=output_format,
                structured_obj=FootTrafficInfo if output_format == "structured" else None
            )
        except ValueError as ve:
            return f"No Traffic data found for the specified store, error: {ve}"
        except Exception as e:
            return f"Error fetching foot traffic data: {e}"

    async def _get_visits(
        self,
        store_id: str,
        limit: int = 5,
        output_format: str = "structured"
    ) -> List[VisitInfo]:
        """Internal method to fetch visit information for a store.

        Args:
            store_id: The unique identifier of the store
            limit: Maximum number of visits to retrieve
            output_format: Output format - 'pandas' for DataFrame, 'structured' for Pydantic models

        Returns:
            List[VisitInfo]: List of visit information objects
        """

        sql = await self._get_query("store_visits")
        store_id = self._pad_storeid(store_id)
        sql = sql.format(store_id=store_id, program_slug=self.program, limit=limit)
        print('STORE QUERY > ', sql)
        try:
            return await self._get_dataset(
                sql,
                output_format=output_format,
                structured_obj=VisitInfo if output_format == "structured" else None
            )
        except ValueError as ve:
            return f"No visit information found for the specified store, error: {ve}"
        except Exception as e:
            return f"Error fetching visit information: {e}"

    @tool_schema(VisitInfoInput)
    async def get_visit_information(
        self,
        store_id: str,
        limit: int = 3,
        output_format: str = "structured",
        program_slug: Optional[str] = None
    ) -> Union[pd.DataFrame, List[VisitInfo]]:
        """Get visit information for a specific store.

        This method retrieves visit information for the specified store,
        including visitor statistics and aggregated visit data.
        """
        try:
            # Ensure the program is set correctly
            if program_slug:
                self.program = program_slug
            visits = await self._get_visits(store_id, limit, output_format)
            if isinstance(visits, str):  # If an error message was returned
                return visits

            return visits
        except ValueError as ve:
            return f"No visit information found for the specified store, error: {ve}"
        except Exception as e:
            return f"Error fetching visit information: {e}"

    @tool_schema(VisitQuestionInput)
    async def get_visit_questions(
        self,
        store_id: str,
        program_slug: Optional[str] = None,
        limit: int = 3
    ) -> Dict[str, List[Dict[str, Any]]]:
        """
        Get visit information for a specific store, focusing on questions and answers.
        """
        if program_slug:
            self.program = program_slug
        visits = await self._get_visits(
            store_id,
            limit,
            "structured"
        )
        if isinstance(visits, str):  # If an error message was returned
            return visits

        question_data = {
            '9730': [],  # Key Wins
            '9731': [],  # Challenges
            '9732': [],  # Next Focus
            '9733': []   # Competitive
        }
        for row_index, visit in enumerate(visits):
            if not visit.visit_data:
                continue

            for qa_item in visit.visit_data:
                column_name = qa_item.get('column_name')
                if column_name in question_data:
                    # first: truncate answer if is too long
                    answer = qa_item.get('answer', '')
                    if answer is None:
                        answer = "No answer provided"
                    if len(answer) > 100:
                        answer = answer[:100] + '...'
                    question_data[column_name].append({
                        'answer': answer,
                        'row_index': row_index,
                        'visitor': visit.visitor_username,
                        'visit_date': visit.visit_date.isoformat() if visit.visit_date else None,
                        'store_id': visit.store_id,
                        'visit_length': visit.visit_length,
                        'question_text': qa_item.get('question', ''),
                        'time_in': visit.time_in.isoformat() if visit.time_in else None,
                        'time_out': visit.time_out.isoformat() if visit.time_out else None,
                        'visit_dow': visit.visit_dow,
                        'visit_hour': visit.visit_hour,
                        'day_of_week': visit.day_of_week,
                        'time_spent_minutes': visit.time_spent_minutes
                    })
        return question_data

    @tool_schema(StoreInfoInput)
    async def get_store_information(self, store_id: str, program: str) -> StoreBasicInfo:
        """Get comprehensive store information including location and basic details,
        contact information, operating hours, and aggregate visit statistics.
        Provides total visits, unique visitors, and average visit duration
        for the specified store. Essential for store analysis and planning.
        """
        # Ensure the program is set correctly
        if program:
            self.program = program
        sql = await self._get_query("store_info")
        store_id = self._pad_storeid(store_id)
        sql = sql.format(store_id=store_id, limit=3)

        # Fetch the store data
        try:
            store_data = await self._get_dataset(sql, output_format='pandas')
        except Exception as e:
            return f"Error fetching store information: {e}"

        if store_data.empty:
            return f"No store found with ID {store_id}"


        # Convert first row to Pydantic model
        store_info = store_data.iloc[0].to_dict()
        return StoreBasicInfo(**store_info)

    @tool_schema(StoreSearchInput)
    async def search_stores(
        self,
        city: Optional[str] = None,
        state_name: Optional[str] = None,
        zipcode: Optional[str] = None,
        limit: int = 50
    ) -> List[StoreBasicInfo]:
        """
        Search for stores based on city, state, or zipcode.
        """
        # Build WHERE clause based on provided criteria
        conditions = []
        if city:
            conditions.append(f"LOWER(s.city) LIKE LOWER('%{city}%')")
        if state_name:
            conditions.append(f"LOWER(c.state_name) LIKE LOWER('%{state_name}%')")
        if zipcode:
            conditions.append(f"s.zipcode = '{zipcode}'")

        if not conditions:
            raise ValueError("At least one search criterion (city, state, or zipcode) must be provided")

        where_clause = " AND ".join(conditions)

        sql = f"""
SELECT DISTINCT ON (s.city, s.zipcode) store_id, store_name, street_address, c.city,
s.latitude, s.longitude, account_name, c.state_code, c.state_name
FROM troc.stores s
JOIN datasets.usa_cities c on s.zipcode = c.zipcode and s.city = c.city
WHERE program_slug = '{self.program}'
AND {where_clause}
        """
        try:
            stores_data = await self._get_dataset(sql, output_format='pandas')
        except Exception as e:
            return f"Error searching for stores: {e}"

        if stores_data.empty:
            search_terms = []
            if city:
                search_terms.append(f"city: {city}")
            if state_name:
                search_terms.append(f"state: {state_name}")
            if zipcode:
                search_terms.append(f"zipcode: {zipcode}")

            return f"No stores found matching the criteria: {', '.join(search_terms)}."

        # Convert DataFrame to list of Pydantic models
        stores = []
        for _, row in stores_data.iterrows():
            stores.append(StoreBasicInfo(**row.to_dict()))

        return stores

    # @tool_schema(DatasetQueryInput)
    # async def get_custom_dataset(
    #     self,
    #     query: str,
    #     output_format: str = "pandas"
    # ) -> Union[pd.DataFrame, Dict[str, Any]]:
    #     """Execute a custom SQL query and return the dataset.

    #     Args:
    #         query: SQL query to execute
    #         output_format: Output format - 'pandas' for DataFrame, 'dict' for dictionary

    #     Returns:
    #         Union[pd.DataFrame, Dict]: Query results in requested format
    #     """
    #     try:
    #         return await self._get_dataset(query, output_format=output_format)
    #     except Exception as e:
    #         return f"Error executing custom query: {str(e)}. Please check your SQL syntax and table names."
