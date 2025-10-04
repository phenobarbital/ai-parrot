from typing import List, Dict, Any, Union, Optional
from decimal import Decimal
from datetime import datetime, date, time
import json
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator
from ...exceptions import ToolError  # pylint: disable=E0611
from ..decorators import tool_schema
from .base import BaseNextStop

def today_date() -> date:
    """Returns today's date."""
    return datetime.now().date()


class EmployeeInput(BaseModel):
    """Input for the employee-related operations in the NextStop tool."""
    employee_id: Optional[str] = Field(
        default=None,
        description="Unique identifier for the employee"
    )
    program: Optional[str] = Field(
        default=None,
        description="Program slug for the store (e.g., 'hisense', 'epson')"
    )
    output_format: Optional[str] = Field(
        default='structured',
        description="Output format for the employee data"
    )

    display_name: Optional[str] = Field(
        default=None,
        description="Name of the employee"
    )
    email: Optional[str] = Field(
        default=None,
        description="Email address of the employee"
    )

    # Add a model_config to prevent additional properties
    model_config = ConfigDict(
        arbitrary_types_allowed=False,
        extra="forbid",
    )

class ManagerInput(BaseModel):
    """Input for the manager-related operations in the NextStop tool."""
    manager_id: str = Field(description="Unique identifier for the manager")
    program: Optional[str] = Field(
        default=None,
        description="Program slug for the store (e.g., 'hisense', 'epson')"
    )
    output_format: Optional[str] = Field(
        default='structured',
        description="Output format for the employee data"
    )

    # Add a model_config to prevent additional properties
    model_config = ConfigDict(
        arbitrary_types_allowed=False,
        extra="forbid",
    )

## Outputs:
class VisitDetailed(BaseModel):
    """Detailed visit information model."""
    visit_date: date = Field(..., description="Date of the visit")
    column_name: str = Field(..., description="Column identifier for the data point")
    store_id: str = Field(description="Store identifier")
    question: str = Field(..., description="Question asked during the visit")
    answer: Optional[str] = Field(None, description="Answer provided for the question")
    account_name: str = Field(..., description="Name of the retail account/store")
    visit_timestamp: Optional[datetime] = Field(default=None, description="Visit timestamp")
    visit_length: Optional[float] = Field(default=None, description="Visit length")
    time_in: Optional[time] = Field(default=None, description="Check-in time")
    time_out: Optional[time] = Field(default=None, description="Check-out time")

    @field_validator('question', mode='before')
    @classmethod
    def truncate_question(cls, v: str) -> str:
        """Truncate question if longer than 200 characters."""
        if not isinstance(v, str):
            return v
        return v[:200] + " (...)" if len(v) > 200 else v

class VisitInformation(BaseModel):
    """Visit information model."""
    # Basic visit info
    visitor_name: str = Field(..., description="Name of the visitor/manager")
    visitor_email: str = Field(..., description="Email address of the visitor")
    visitor_name: Optional[str] = Field(default=None, description="Visitor name")
    visitor_username: Optional[str] = Field(default=None, description="Visitor username")
    # aggregated visit data
    visit_data: Optional[List[VisitDetailed]] = Field(
        default=None,
        description="Visit data aggregated"
    )
    # Aggregated questions:
    questions: Optional[Dict[str, List[Dict[str, Any]]]] = Field(
        default=None,
        description="Aggregated visit questions and answers organized by question type"
    )

class VisitDetail(BaseModel):
    """Individual visit detail from the visit_data JSONB array."""
    visit_date: date = Field(..., description="Date of the visit")
    column_name: str = Field(..., description="Column identifier for the data point")
    question: str = Field(..., description="Question asked during the visit")
    answer: Optional[str] = Field(None, description="Answer provided for the question")
    account_name: str = Field(..., description="Name of the retail account/store")
    visit_length: Optional[float] = Field(default=None, description="Visit length in minutes")
    store_id: str = Field(..., description="Store identifier")

    @field_validator('question', mode='before')
    @classmethod
    def truncate_question(cls, v: str) -> str:
        """Truncate question if longer than 200 characters."""
        if not isinstance(v, str):
            return v

        max_length = 200
        if len(v) > max_length:
            # Truncate and add ellipsis
            return v[:max_length-6] + " (...)"

        return v

class VisitsByManager(BaseModel):
    """Individual record for visits by manager data"""
    visitor_name: str = Field(..., description="Name of the visitor/manager")
    visitor_email: str = Field(..., description="Email address of the visitor")
    assigned_stores: Optional[int] = Field(default=0, description="Number of stores assigned to the manager")
    total_visits: Optional[int] = Field(default=0, description="Total number of visits made")
    visited_stores: int = Field(..., description="Number of stores actually visited")
    visit_duration: float = Field(..., description="Total visit duration in minutes")
    average_visit_duration: Optional[float] = Field(..., description="Average visit duration in minutes")
    hour_of_visit: float = Field(..., description="Average hour of visit (24-hour format)")
    current_visits: int = Field(..., description="Number of visits in current month")
    previous_week_visits: Optional[int] = Field(default=0, description="Number of visits in previous week")
    previous_month_visits: Optional[int] = Field(default=0, description="Number of visits in previous month's week")
    most_frequent_day_of_week: int = Field(default=None, description="Most frequent day of week (0=Monday, 6=Sunday)")
    most_frequent_store: str = Field(default=None, description="Most frequently visited store")
    most_frequent_store_visits: Optional[float] = Field(default=None, description="Number of visits to the most frequent store")
    visit_ratio: str = Field(..., description="Ratio of visited stores to assigned stores")
    day_of_week: str = Field(..., description="Most frequent day name")
    ranking_visits: int = Field(..., description="Current ranking by visits")
    previous_week_ranking: int = Field(..., description="Previous week ranking by visits")
    previous_month_ranking: int = Field(..., description="Previous month ranking by visits")
    ranking_duration: int = Field(..., description="Ranking by visit duration")

class VisitsByManagerOutput(BaseModel):
    """Structured output for get_visits_by_manager tool"""
    records: List[VisitsByManager] = Field(..., description="List of visitor stats")
    total_records: int = Field(..., description="Total number of records returned")
    generated_at: datetime = Field(default_factory=datetime.now, description="Timestamp when data was generated")

    class Config:
        json_encoders = {
            datetime: lambda dt: dt.isoformat()
        }


class ManagerSales(BaseModel):
    """Individual record for Manager sales data"""
    visitor_name: str = Field(..., description="Name of the employee/visitor")
    visitor_email: str = Field(..., description="Email address of the employee")
    total_sales: Optional[float] = Field(description="Total sales amount across all periods")
    sales_current_week: Optional[float] = Field(description="Sales in current week")
    sales_previous_week: Optional[float] = Field(description="Sales in previous week")
    sales_previous_month: Optional[float] = Field(description="Sales from week of previous month")
    current_ranking: Optional[int] = Field(description="Current ranking by sales performance")
    previous_week_ranking: Optional[int] = Field(description="Previous month ranking by sales")
    previous_month_ranking: Optional[int] = Field(description="Two months ago ranking by sales")


class ManagerSalesOutput(BaseModel):
    """Structured output for get_manager_sales tool"""
    records: List[ManagerSales] = Field(..., description="List of manager sales")
    total_records: int = Field(..., description="Total number of records returned")
    generated_at: datetime = Field(default_factory=datetime.now, description="Timestamp when data was generated")

    class Config:
        json_encoders = {
            datetime: lambda dt: dt.isoformat()
        }

class EmployeeSales(BaseModel):
    """Individual record for Employee sales data"""
    store_id: str = Field(..., description="Store identifier")
    tier: str = Field(..., description="Sales ranking")
    sales_current_week: Optional[float] = Field(
        ...,
        description="Sales in current week"
    )
    sales_previous_week: Optional[float] = Field(
        ...,
        description="Sales in previous week"
    )
    week_over_week_delta: Optional[float] = Field(
        ..., description="Week over week sales delta"
    )
    week_over_week_variance: Optional[float] = Field(
        ..., description="Week over week sales variance"
    )


class EmployeeVisit(BaseModel):
    """
    Employee visit summary with aggregated statistics and detailed visit data.

    This model represents the result of a complex SQL query that aggregates
    employee visit data including timing patterns, visit counts, and detailed
    visit information.
    """

    # Employee Information
    visitor_name: str = Field(..., description="Name of the visiting employee")
    visitor_email: str = Field(..., description="Email address of the visiting employee")

    # Visit Statistics
    latest_visit_date: date = Field(..., description="Date of the most recent visit")
    number_of_visits: int = Field(..., ge=0, description="Total number of visits made")
    latest_store_visited: Optional[str] = Field(
        None,
        description="Name of the most recently visited store"
    )
    # Unique stores visited
    visited_stores: int = Field(..., ge=0, description="Number of unique stores visited")

    # Time-based Metrics
    visit_duration: Optional[float] = Field(
        None,
        ge=0,
        description="Average visit duration in minutes"
    )
    average_hour_visit: Optional[float] = Field(
        None,
        ge=0,
        le=23.99,
        description="Average hour of day when visits occur (0-23.99)"
    )
    min_time_in: Optional[time] = Field(
        None, description="Earliest check-in time across all visits"
    )
    max_time_out: Optional[time] = Field(
        None, description="Latest check-out time across all visits"
    )

    # Pattern Analysis
    most_frequent_hour_of_day: Optional[int] = Field(
        None,
        ge=0,
        le=23,
        description="Most common hour of day for visits (0-23)"
    )
    most_frequent_day_of_week: Optional[int] = Field(
        None,
        ge=0,
        le=6,
        description="Most common day of week for visits (0=Sunday, 6=Saturday)"
    )
    median_visit_duration: Optional[float] = Field(
        None,
        ge=0,
        description="Median visit duration in minutes"
    )

    # Detailed Visit Data
    visit_data: List[VisitDetail] = Field(
        default_factory=list,
        description="Detailed information from each visit"
    )

    # Retailer Summary
    visited_retailers: Optional[Dict[str, int]] = Field(
        None,
        description="Dictionary mapping retailer names to visit counts"
    )

    # Computed Properties
    @property
    def average_visits_per_store(self) -> Optional[float]:
        """Calculate average number of visits per store."""
        if self.visited_stores > 0:
            return round(self.number_of_visits / self.visited_stores, 2)
        return None

    @property
    def total_retailers(self) -> int:
        """Get total number of different retailers visited."""
        return len(self.visited_retailers) if self.visited_retailers else 0

    @property
    def most_visited_retailer(self) -> Optional[str]:
        """Get the name of the most visited retailer."""
        if self.visited_retailers:
            return max(self.visited_retailers.items(), key=lambda x: x[1])[0]
        return None

    @property
    def day_of_week_name(self) -> Optional[str]:
        """Convert numeric day of week to name."""
        if self.most_frequent_day_of_week is not None:
            days = ["Sunday", "Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday"]
            return days[self.most_frequent_day_of_week]
        return None

    @property
    def visit_efficiency_score(self) -> Optional[float]:
        """
        Calculate a visit efficiency score based on visit duration and store coverage.
        Higher score indicates more efficient visits (shorter duration, more stores covered).
        """
        if self.visit_duration and self.visited_stores > 0:
            # Score: stores visited per minute of average visit time
            return round(self.visited_stores / self.visit_duration, 4)
        return None

    # Validators
    @field_validator('visitor_email')
    @classmethod
    def validate_email_format(cls, v):
        """Basic email validation."""
        if '@' not in v:
            raise ValueError('Invalid email format')
        return v.lower()

    @field_validator('visit_data', mode='before')
    @classmethod
    def parse_visit_data(cls, v):
        """Parse visit data - handles lists directly from DataFrame."""
        # If it's already a list of dicts (from DataFrame), process directly
        if isinstance(v, list):
            parsed_visits = []
            for item in v:
                if isinstance(item, dict):
                    try:
                        # Convert string dates to date objects if needed
                        if 'visit_date' in item and isinstance(item['visit_date'], str):
                            item['visit_date'] = datetime.strptime(item['visit_date'], '%Y-%m-%d').date()

                        parsed_visits.append(VisitDetail(**item))
                    except Exception as e:
                        # Log the error but continue processing other items
                        print(f"Error parsing visit detail: {e}, item: {item}")
                        continue
            return parsed_visits

        # Handle string JSON (shouldn't happen with DataFrame but just in case)
        if isinstance(v, str):
            import json
            try:
                v = json.loads(v)
                # Recursive call with the parsed data
                return cls.parse_visit_data(v)
            except json.JSONDecodeError:
                return []

        # Return empty list for None or other types
        return v or []

    @field_validator('visited_retailers', mode='before')
    @classmethod
    def parse_visited_retailers(cls, v):
        """Parse visited retailers data if it comes as raw JSON."""
        if isinstance(v, str):
            import json
            try:
                v = json.loads(v)
            except json.JSONDecodeError:
                return {}
        return v or {}

    # Model validator for additional validation after all fields are processed
    @model_validator(mode='after')
    def validate_model(self):
        """Additional model-level validation."""
        # Ensure visit counts make sense
        if self.number_of_visits < 0:
            raise ValueError("Number of visits cannot be negative")

        if self.visited_stores > self.number_of_visits:
            raise ValueError("Visited stores cannot exceed number of visits")

        return self

    class Config:
        """Pydantic configuration."""
        # Allow extra fields that might come from the database
        extra = "ignore"
        # Use enum values in JSON serialization
        use_enum_values = True
        # Enable validation of assignment
        validate_assignment = True
        # Custom JSON encoders for special types
        json_encoders = {
            date: lambda v: v.isoformat(),
            time: lambda v: v.isoformat(),
            Decimal: lambda v: float(v)
        }

    def model_dump_summary(self) -> Dict[str, Any]:
        """
        Return a summary version with key metrics only.
        Useful for API responses where full detail isn't needed.
        """
        return {
            "visitor_name": self.visitor_name,
            "visitor_email": self.visitor_email,
            "latest_visit_date": self.latest_visit_date,
            "number_of_visits": self.number_of_visits,
            "visited_stores": self.visited_stores,
            "visit_duration": self.visit_duration,
            "most_visited_retailer": self.most_visited_retailer,
            "total_retailers": self.total_retailers,
            "visit_efficiency_score": self.visit_efficiency_score,
            "day_of_week_name": self.day_of_week_name
        }

    def get_retailer_breakdown(self) -> List[Dict[str, Union[str, int]]]:
        """
        Get a formatted breakdown of retailer visits.
        Returns sorted list by visit count (descending).
        """
        if not self.visited_retailers:
            return []

        return [
            {"retailer": retailer, "visits": count}
            for retailer, count in sorted(
                self.visited_retailers.items(),
                key=lambda x: x[1],
                reverse=True
            )
        ]

class EmployeeVisitCollection(BaseModel):
    """Collection of employee visits for batch operations."""
    employees: List[EmployeeVisit] = Field(default_factory=list)
    query_date_range: Optional[str] = Field(None, description="Date range of the query")
    total_employees: int = Field(default=0, description="Total number of employees in results")

    @property
    def top_performers(self, limit: int = 5) -> List[EmployeeVisit]:
        """Get top performing employees by number of visits."""
        return sorted(
            self.employees,
            key=lambda x: x.number_of_visits,
            reverse=True
        )[:limit]

    @property
    def most_efficient(self, limit: int = 5) -> List[EmployeeVisit]:
        """Get most efficient employees by visit efficiency score."""
        efficient = [e for e in self.employees if e.visit_efficiency_score is not None]
        return sorted(
            efficient,
            key=lambda x: x.visit_efficiency_score,
            reverse=True
        )[:limit]


# Example usage in your tool:
"""
async def get_employee_visits(employee_id: str) -> EmployeeVisit:
    # Execute your SQL query
    result = await db.fetch_one(sql)

    # Create the EmployeeVisit instance
    if result:
        return EmployeeVisit(**dict(result))
    else:
        # Return empty result
        return EmployeeVisit(
            visitor_name="Unknown",
            visitor_email=employee_id,
            latest_visit_date=date.today(),
            number_of_visits=0,
            visited_stores=0
        )
"""

class EmployeeToolkit(BaseNextStop):
    """Toolkit for managing employee-related operations in NextStop.

    This toolkit provides tools to:
    - employee_information: Get basic employee information.
    - search_employee: Search for employees based on display name or email.
    - get_by_employee_visits: Get visit information for a specific employee.
    - get_visits_by_manager: Get visit information for a specific manager, including their employees.
    - get_manager_sales: Fetch sales data for a specific manager and ranked performance.
    - get_employee_sales: Fetch sales data for a specific employee.
    """

    @tool_schema(ManagerInput)
    async def get_visits_by_manager(
        self,
        manager_id: str,
        program: str,
        **kwargs
    ) -> List[VisitsByManager]:
        """Get Employee Visits data for a specific Manager, requires the associated_oid of the manager.
        including total visits, average visit duration, and most frequent visit hours.
        Useful for analyzing employee performance and visit patterns.
        """
        if program:
            self.program = program
        sql = await self._get_query("visits_by_manager")
        sql = sql.format(manager_id=manager_id)
        try:
            return await self._get_dataset(
                sql,
                output_format='structured',
                structured_obj=VisitsByManager
            )
        except ToolError as te:
            raise ValueError(
                f"No Employee Visit data found for manager {manager_id}, error: {te}"
            )
        except ValueError as ve:
            raise ValueError(f"Invalid data format, error: {ve}")
        except Exception as e:
            raise ValueError(f"Error fetching employee visit data: {e}")

    @tool_schema(ManagerInput)
    async def get_manager_sales(
        self,
        manager_id: str,
        program: str,
        **kwargs
    ) -> List[ManagerSales]:
        """Get Sales and goals for all employees related to a Manager.
        Returns a ranked list of employees based on their sales performance.
        Useful for understanding employee performance and sales distribution.
        """
        if program:
            self.program = program
        sql = await self._get_query("manager_sales")
        if not manager_id:
            manager_id = kwargs.get('email')
        if not manager_id:
            raise ToolError("Manager ID is required to fetch employee sales data.")
        sql = sql.format(manager_id=manager_id)
        try:
            return await self._get_dataset(
                sql,
                output_format='structured',
                structured_obj=ManagerSales
            )
        except ToolError as te:
            raise ValueError(f"No Sales data found for manager {manager_id}, error: {te}")
        except ValueError as ve:
            raise ValueError(f"Invalid data format, error: {ve}")
        except Exception as e:
            raise ValueError(f"Error fetching employee sales data: {e}")

    @tool_schema(EmployeeInput)
    async def employee_information(
        self,
        employee_id: str = None,
        display_name: str = None,
        email: str = None
    ) -> str:
        """Get basic information about an employee by their ID, display name or email.
        Returns the employee's display name and email.
        Useful for identifying employees in the system.
        """
        conditions = []
        if employee_id:
            conditions.append(f"associate_oid = '{employee_id}'")
        if display_name:
            conditions.append(f"display_name = '{display_name}'")
        if email:
            conditions.append(f"corporate_email = '{email}'")

        if not conditions:
            raise ToolError("At least one of employee_id, display_name, or email must be provided.")

        sql = f"""
SELECT associate_oid, associate_id, first_name, last_name, display_name, corporate_email as email,
position_id, job_code, department, department_code
FROM troc.troc_employees
WHERE {' AND '.join(conditions)}
LIMIT 1;
        """
        try:
            employee_data = await self._get_dataset(
                sql,
                output_format='pandas',
                structured_obj=None
            )
            if employee_data.empty:
                raise ToolError(
                    f"No Employee data found for the provided criteria."
                )
            return self._json_encoder(
                employee_data.to_dict(orient='records')
            )  # type: ignore[return-value]
        except ToolError as te:
            return f"No Employee data found for the provided criteria, error: {te}"
        except ValueError as ve:
            return f"Invalid data format, error: {ve}"
        except Exception as e:
            return f"Error fetching employee information: {e}"

    @tool_schema(EmployeeInput)
    async def search_employee(
        self,
        display_name: str = None,
        email: str = None
    ) -> str:
        """Search for employees by their display name or email.
        Returns a list of employees matching the search criteria.
        Useful for finding employees in the system.
        """
        conditions = []
        if display_name:
            conditions.append(f"display_name ILIKE '%{display_name}%'")
        if email:
            conditions.append(f"corporate_email ILIKE '%{email}%'")

        if not conditions:
            raise ToolError("At least one of display_name or email must be provided.")

        sql = f"""
SELECT associate_oid, associate_id, first_name, last_name, display_name, corporate_email as email,
position_id, job_code, department, department_code
FROM troc.troc_employees
WHERE {' AND '.join(conditions)}
ORDER BY display_name
LIMIT 100;
        """
        try:
            employee_data = await self._get_dataset(
                sql,
                output_format='pandas',
                structured_obj=None
            )
            if employee_data.empty:
                raise ToolError(
                    f"No Employee data found for the provided search criteria."
                )
            return self._json_encoder(
                employee_data.to_dict(orient='records')
            )  # type: ignore[return-value]
        except ToolError as te:
            return f"No Employee data found for the provided search criteria, error: {te}"
        except ValueError as ve:
            return f"Invalid data format, error: {ve}"
        except Exception as e:
            return f"Error searching for employees: {e}"

    @tool_schema(EmployeeInput)
    async def get_by_employee_visits(
        self,
        employee_id: str,
        program: str,
        **kwargs
    ) -> EmployeeVisit:
        """Get statistics about visits made by an Employee during the current week.
        Returns detailed visit information for the specified employee.
        Data is returned as a Structured JSON object.
        Useful for analyzing employee visit patterns and performance.
        """
        if program:
            self.program = program
        if not employee_id:
            employee_id = kwargs.get('email', '').strip().lower()
        sql = await self._get_query("employee_visits")
        sql = sql.format(employee_id=employee_id)
        try:
            visit_data = await self._fetch_one(
                sql,
                output_format='structured',
                structured_obj=EmployeeVisit
            )
            if not visit_data:
                raise ToolError(
                    f"No Employee Visit data found for email {employee_id}."
                )
            return visit_data
        except ToolError as te:
            raise ValueError(
                f"No Employee Visit data found for email {employee_id}, error: {te}"
            )
        except ValueError as ve:
            raise ValueError(
                f"Invalid data format, error: {ve}"
            )
        except Exception as e:
            raise ValueError(
                f"Error fetching employee visit data: {e}"
            )

    @tool_schema(EmployeeInput)
    async def get_employee_sales(
        self,
        employee_id: str,
        program: str,
        **kwargs
    ) -> List[EmployeeSales]:
        """Get sales information for a specific employee.
        Returns a collection of EmployeeSales objects with detailed sales data.
        Useful for analyzing individual employee sales patterns and performance.
        """
        if program:
            self.program = program
        if not employee_id:
            employee_id = kwargs.get('email', '').strip().lower()
        sql = await self._get_query("employee_sales")
        sql = sql.format(employee_id=employee_id)
        try:
            sales_data = await self._get_dataset(
                sql,
                output_format='structured',
                structured_obj=EmployeeSales
            )
            if not sales_data:
                raise ToolError(
                    f"No Employee Sales data found for email {employee_id}."
                )
            return sales_data
        except ToolError as te:
            raise ValueError(
                f"No Employee Sales data found for email {employee_id}, error: {te}"
            )
        except ValueError as ve:
            raise ValueError(
                f"Invalid data format, error: {ve}"
            )
        except Exception as e:
            raise ValueError(
                f"Error fetching employee Sales data: {e}"
            )
