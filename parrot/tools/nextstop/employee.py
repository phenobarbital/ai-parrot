from typing import List, Dict, Any, Union, Optional
from decimal import Decimal
from datetime import datetime, date, time
import json
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator
from ...exceptions import ToolError  # pylint: disable=E0611
from ..toolkit import tool_schema
from .base import BaseNextStop

def today_date() -> date:
    """Returns today's date."""
    return datetime.now().date()


class EmployeeInput(BaseModel):
    """Input for the employee-related operations in the NextStop tool."""
    employee_id: Optional[str] = Field(default=None, description="Unique identifier for the employee")
    display_name: Optional[str] = Field(default=None, description="Name of the employee")
    email: Optional[str] = Field(default=None, description="Email address of the employee")

    # Add a model_config to prevent additional properties
    model_config = ConfigDict(
        arbitrary_types_allowed=False,
        extra="forbid",
    )

class ManagerInput(BaseModel):
    """Input for the manager-related operations in the NextStop tool."""
    manager_id: str = Field(description="Unique identifier for the manager")

    # Add a model_config to prevent additional properties
    model_config = ConfigDict(
        arbitrary_types_allowed=False,
        extra="forbid",
    )

## Outputs:
class VisitDetail(BaseModel):
    """Individual visit detail from the visit_data JSONB array."""
    visit_date: date = Field(..., description="Date of the visit")
    column_name: str = Field(..., description="Column identifier for the data point")
    question: str = Field(..., description="Question asked during the visit")
    answer: Optional[str] = Field(None, description="Answer provided for the question")
    account_name: str = Field(..., description="Name of the retail account/store")

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
    assigned_stores: int = Field(..., description="Number of stores assigned to the manager")
    total_visits: int = Field(..., description="Total number of visits made")
    visited_stores: int = Field(..., description="Number of stores actually visited")
    visit_duration: float = Field(..., description="Total visit duration in minutes")
    average_visit_duration: Optional[float] = Field(..., description="Average visit duration in minutes")
    hour_of_visit: float = Field(..., description="Average hour of visit (24-hour format)")
    current_visits: int = Field(..., description="Number of visits in current month")
    previous_week_visits: int = Field(..., description="Number of visits in previous week")
    previous_month_visits: int = Field(..., description="Number of visits in previous month's week")
    most_frequent_day_of_week: int = Field(..., description="Most frequent day of week (0=Monday, 6=Sunday)")
    most_frequent_store: str = Field(..., description="Most frequently visited store")
    most_frequent_store_visits: int = Field(..., description="Number of visits to the most frequent store")
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


class EmployeeSales(BaseModel):
    """Individual record for employee sales data"""
    visitor_name: str = Field(..., description="Name of the employee/visitor")
    visitor_email: str = Field(..., description="Email address of the employee")
    total_sales: Optional[int] = Field(description="Total sales amount across all periods")
    sales_current_week: Optional[int] = Field(description="Sales in current week")
    sales_previous_week: Optional[int] = Field(description="Sales in previous week")
    sales_previous_month: Optional[int] = Field(description="Sales from week of previous month")
    current_ranking: Optional[int] = Field(description="Current ranking by sales performance")
    previous_week_ranking: Optional[int] = Field(description="Previous month ranking by sales")
    previous_month_ranking: Optional[int] = Field(description="Two months ago ranking by sales")


class EmployeeSalesOutput(BaseModel):
    """Structured output for get_employee_sales tool"""
    records: List[EmployeeSales] = Field(..., description="List of employee sales")
    total_records: int = Field(..., description="Total number of records returned")
    generated_at: datetime = Field(default_factory=datetime.now, description="Timestamp when data was generated")

    class Config:
        json_encoders = {
            datetime: lambda dt: dt.isoformat()
        }


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
    - get_employee_sales: Fetch sales data for a specific employee and ranked performance.
    """

    @tool_schema(ManagerInput)
    async def get_visits_by_manager(self, manager_id: str, **kwargs) -> List[VisitsByManager]:
        """Get Employee Visits data for a specific Manager, requires the associated_oid of the manager.
        including total visits, average visit duration, and most frequent visit hours.
        Useful for analyzing employee performance and visit patterns.
        """
        sql = f"""
WITH employee_data AS (
WITH employee_info AS (
    SELECT
        d.rep_name as visitor_name,
        d.rep_email as visitor_email,
        COUNT(DISTINCT st.store_id) AS assigned_stores,
      -- 1) Current week Sunday → Saturday
      (CURRENT_DATE
        - EXTRACT(dow FROM CURRENT_DATE) * INTERVAL '1 day'
      )::date                               AS current_week_start,
      (CURRENT_DATE
        - EXTRACT(dow FROM CURRENT_DATE) * INTERVAL '1 day'
        + INTERVAL '6 days'
      )::date                               AS current_week_end,

      -- 2) Previous week (the Sunday–Saturday immediately before)
      (
        CURRENT_DATE
        - EXTRACT(dow FROM CURRENT_DATE) * INTERVAL '1 day'
        - INTERVAL '1 week'
      )::date                               AS previous_week_start,
      (
        CURRENT_DATE
        - EXTRACT(dow FROM CURRENT_DATE) * INTERVAL '1 day'
        - INTERVAL '1 week'
        + INTERVAL '6 days'
      )::date                               AS previous_week_end,

      -- 3) “Same week” one month ago (Sunday–Saturday)
      (
        (CURRENT_DATE - INTERVAL '1 month')::date
        - EXTRACT(dow FROM (CURRENT_DATE - INTERVAL '1 month')) * INTERVAL '1 day'
      )::date                               AS week_prev_month_start,
      (
        (CURRENT_DATE - INTERVAL '1 month')::date
        - EXTRACT(dow FROM (CURRENT_DATE - INTERVAL '1 month')) * INTERVAL '1 day'
        + INTERVAL '6 days'
      )::date                               AS week_prev_month_end
    FROM hisense.vw_stores st
    LEFT JOIN hisense.stores_details d USING (store_id)
    WHERE d.manager_name = '{manager_id}'
        AND d.rep_email <> '' and d.rep_name <> '0'
    GROUP BY d.rep_name, d.rep_email
)
    SELECT
        e.visitor_name,
        e.visitor_email,
        e.assigned_stores,
        -- visit stats:
        count(distinct f.form_id) as total_visits,
        count(distinct f.store_id) as visited_stores,
        SUM(f.visit_length) AS visit_duration,
        AVG(f.visit_length) AS average_visit_duration,
        AVG(f.visit_hour) AS hour_of_visit,
        count(DISTINCT f.form_id) FILTER(WHERE f.visit_date between current_week_start and current_week_end) AS current_visits,
        count(DISTINCT f.form_id) FILTER(WHERE f.visit_date between previous_week_start and previous_week_end) AS previous_week_visits,
        count(DISTINCT f.form_id) FILTER(WHERE f.visit_date between week_prev_month_start and week_prev_month_end) AS previous_month_visits,
        AVG(f.visit_dow)::integer AS most_frequent_day_of_week,
        ts.store_id   AS most_frequent_store,
        ts.visits_cnt AS most_frequent_store_visits
    FROM hisense.form_information f
    JOIN employee_info e USING(visitor_email)
    LEFT JOIN hisense.stores_details d USING (store_id)
    LEFT JOIN LATERAL (
      SELECT
      f2.store_id,
      COUNT(*) AS visits_cnt
      FROM hisense.form_information f2
      WHERE f2.visitor_email = e.visitor_email
      AND f2.visit_date >= e.week_prev_month_start
      GROUP BY f2.store_id
      ORDER BY visits_cnt DESC
      LIMIT 1
    ) as ts ON TRUE
    WHERE f.visit_date >= week_prev_month_start
    AND d.manager_name = 'mcarter@trocglobal.com'
    GROUP BY e.visitor_name, e.visitor_email, e.assigned_stores, ts.store_id, ts.visits_cnt
)
SELECT
    ed.*,
    round(coalesce(troc_percent(visited_stores, assigned_stores), 0) * 100, 1)::text   || '%' AS visit_ratio,
    CASE most_frequent_day_of_week
        WHEN 0 THEN 'Monday'
        WHEN 1 THEN 'Tuesday'
        WHEN 2 THEN 'Wednesday'
        WHEN 3 THEN 'Thursday'
        WHEN 4 THEN 'Friday'
        WHEN 5 THEN 'Saturday'
        WHEN 6 THEN 'Sunday'
        ELSE 'Unknown' -- Handle any unexpected values
    END AS day_of_week,
    RANK() OVER (ORDER BY current_visits DESC) AS ranking_visits,
    RANK() OVER (ORDER BY previous_week_visits DESC) AS previous_week_ranking,
    RANK() OVER (ORDER BY previous_month_visits DESC) AS previous_month_ranking,
    RANK() OVER (ORDER BY visit_duration DESC) AS ranking_duration
FROM employee_data ed
ORDER BY visitor_email DESC;
        """
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
    async def get_employee_sales(
        self,
        manager_id: str,
        **kwargs
    ) -> List[EmployeeSales]:
        """Get Sales and goals for all employees related to a Manager.
        Returns a ranked list of employees based on their sales performance.
        Useful for understanding employee performance and sales distribution.
        """
        sql = f"""
WITH stores AS (
    SELECT
    st.store_id, d.rep_name as visitor_name, market_name, region_name, d.rep_email as visitor_email,
    count(store_id) filter(where focus = true) as focus_400,
    count(store_id) filter(where wall_display = true) as wall_display,
    count(store_id) filter(where triple_stack = true) as triple_stack,
    count(store_id) filter(where covered = true) as covered,
    count(store_id) filter(where end_cap = true) as endcap,
    DATE_TRUNC('week', CURRENT_DATE)::date - 1 AS current_week,
    (DATE_TRUNC('week', CURRENT_DATE)::date - 1) - INTERVAL '1 week' AS previous_week,
    (DATE_TRUNC('week', (CURRENT_DATE - INTERVAL '1 month'))::date - 1)::date AS week_previous_month
    FROM hisense.vw_stores st
    left join hisense.stores_details d using(store_id)
    WHERE manager_name = '{manager_id}'
    and rep_name <> '0' and rep_email <> ''
    GROUP BY st.store_id, d.rep_name, d.rep_email, market_name, region_name
), sales AS (
  SELECT
  st.visitor_name,
  st.visitor_email,
  sum(coalesce(net_sales, 0)) as total_sales,
  sum(net_sales) FILTER(WHERE i.order_date_week::date = st.current_week::date) AS sales_current_week,
  sum(net_sales) FILTER(where i.order_date_week::date = st.previous_week::date) AS sales_previous_week,
  sum(net_sales) FILTER(where i.order_date_week::date = st.week_previous_month::date) AS sales_previous_month
  FROM hisense.summarized_inventory i
  JOIN stores st USING(store_id)
  INNER JOIN hisense.all_products p using(model)
  WHERE order_date_week::date between st.week_previous_month and current_date - 1
  AND new_model = True
  and i.store_id is not null
  GROUP BY st.visitor_name, st.visitor_email
)
SELECT *,
 rank() over (order by sales_current_week DESC) as current_ranking,
 rank() over (order by sales_previous_week DESC) as previous_week_ranking,
 rank() over (order by sales_previous_month DESC) as previous_month_ranking
FROM sales;
        """
        try:
            return await self._get_dataset(
                sql,
                output_format='structured',
                structured_obj=EmployeeSales
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
        **kwargs
    ) -> EmployeeVisit:
        """Get statistics about visits made by an Employee during the current week.
        Returns detailed visit information for the specified employee.
        Data is returned as a Structured JSON object.
        Useful for analyzing employee visit patterns and performance.
        """
        sql = f"""
WITH visit_data AS (
    SELECT
        form_id,
        formid,
        visit_date::date AS visit_date,
        visitor_name,
        visitor_email,
        visit_timestamp,
        visit_length,
        visit_hour,
        time_in,
        time_out,
        d.store_id,
        d.visit_dow,
        d.account_name,
        -- Calculate time spent in decimal minutes
        CASE
            WHEN time_in IS NOT NULL AND time_out IS NOT NULL THEN
                EXTRACT(EPOCH FROM (time_out::time - time_in::time)) / 60.0
            ELSE NULL END AS time_spent_minutes,
        -- Aggregate visit data
        jsonb_agg(
            jsonb_build_object(
                'visit_date', visit_date,
                'column_name', column_name,
                'question', question,
                'answer', data,
                'account_name', d.account_name
            ) ORDER BY column_name
        ) AS visit_info
    FROM hisense.form_data d
    ---cross join dates da
    INNER JOIN troc.stores st ON st.store_id = d.store_id AND st.program_slug = 'hisense'
    WHERE visit_date::date between (
    SELECT firstdate  FROM public.week_range((current_date::date - interval '1 week')::date, (current_date::date - interval '1 week')::date))
    and (SELECT lastdate  FROM public.week_range((current_date::date - interval '1 week')::date, (current_date::date - interval '1 week')::date))
    AND column_name IN ('9733','9731','9732','9730')
    AND d.visitor_email = '{employee_id}'
    GROUP BY
        form_id, formid, visit_date, visit_timestamp, visit_length, d.visit_hour, d.account_name,
        time_in, time_out, d.store_id, st.alt_name, visitor_name, visitor_email, visitor_role, d.visit_dow
),
retailer_summary AS (
  -- compute per-visitor, per-account counts, then turn into a single JSONB
  SELECT
    visitor_email,
    jsonb_object_agg(account_name, cnt) AS visited_retailers
  FROM (
    SELECT
      visitor_email,
      account_name,
      COUNT(*) AS cnt
    FROM visit_data
    GROUP BY visitor_email, account_name
  ) t
  GROUP BY visitor_email
)
SELECT
visitor_name,
vd.visitor_email,
max(visit_date) as latest_visit_date,
COUNT(DISTINCT form_id) AS number_of_visits,
count(distinct store_id) as visited_stores,
avg(visit_length) as visit_duration,
AVG(visit_hour) AS average_hour_visit,
min(time_in) as min_time_in,
max(time_out) as max_time_out,
mode() WITHIN GROUP (ORDER BY visit_hour) as most_frequent_hour_of_day,
mode() WITHIN GROUP (ORDER BY visit_dow) AS most_frequent_day_of_week,
percentile_disc(0.5) WITHIN GROUP (ORDER BY visit_length) AS median_visit_duration,
jsonb_agg(elem) AS visit_data,
rs.visited_retailers
FROM visit_data vd
CROSS JOIN LATERAL jsonb_array_elements(visit_info) AS elem
LEFT JOIN retailer_summary rs
    ON rs.visitor_email = vd.visitor_email
group by visitor_name, vd.visitor_email, rs.visited_retailers
        """
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
