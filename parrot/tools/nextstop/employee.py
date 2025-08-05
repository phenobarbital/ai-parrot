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
    employee_id: str = Field(description="Unique identifier for the employee")
    display_name: str = Field(description="Name of the employee")
    email: str = Field(..., description="Email address of the employee")

    # Add a model_config to prevent additional properties
    model_config = ConfigDict(
        arbitrary_types_allowed=False,
        extra="forbid",
    )

class ManagerInput(BaseModel):
    """Input for the manager-related operations in the NextStop tool."""
    manager_id: str = Field(description="Unique identifier for the manager")
    display_name: str = Field(description="Name of the manager")
    email: str = Field(description="Email address of the manager")

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
    - get_employee_sales: Fetch sales data for a specific employee and ranked performance.
    - search_employee: Search for employees based on display name or email.
    - get_by_employee_visits: Get visit information for a specific employee.
    - get_visits_by_manager: Get visit information for a specific manager, including their employees.
    """

    @tool_schema(ManagerInput)
    async def get_visits_by_manager(self, manager_id: str, **kwargs) -> str:
        """Get Employee Visits data for a specific Manager, requires the associated_oid of the manager.
        including total visits, average visit duration, and most frequent visit hours.
        Useful for analyzing employee performance and visit patterns.
        """
        sql = f"""
WITH base_data AS (
    SELECT
        d.rep_name,
        d.rep_email AS visitor_email,
        st.store_id,
        f.form_id,
        f.visit_date,
        f.visit_timestamp,
        f.visit_length,
        f.visit_dow,
        EXTRACT(HOUR FROM f.visit_timestamp) AS visit_hour,
        DATE_TRUNC('month', f.visit_date) AS visit_month,
        DATE_TRUNC('month', CURRENT_DATE) AS current_month,
        DATE_TRUNC('month', CURRENT_DATE) - INTERVAL '1 month' AS previous_month,
        DATE_TRUNC('month', CURRENT_DATE) - INTERVAL '2 month' AS two_months_ago
    FROM hisense.vw_stores st
    LEFT JOIN hisense.stores_details d USING (store_id)
    LEFT JOIN hisense.form_information f ON d.rep_email = f.visitor_email
    WHERE
        cast_to_integer(st.customer_id) = 401865
        AND d.manager_name = '{manager_id}'
        AND d.rep_name <> '0'
        AND f.visit_date >= DATE_TRUNC('month', CURRENT_DATE) - INTERVAL '2 months'
),
employee_info AS (
    SELECT
        d.rep_name,
        d.rep_email AS visitor_email,
        COUNT(DISTINCT st.store_id) AS assigned_stores
    FROM hisense.vw_stores st
    LEFT JOIN hisense.stores_details d USING (store_id)
    WHERE
        cast_to_integer(st.customer_id) = 401865
        AND d.manager_name = 'mcarter@trocglobal.com'
        AND d.rep_name <> '0'
    GROUP BY d.rep_name, d.rep_email
),
monthly_visits AS (
    SELECT
        bd.rep_name,
        bd.visitor_email,
        COALESCE(count(DISTINCT bd.form_id) FILTER(where visit_month = bd.current_month), 0)::integer AS current_visits,
        COALESCE(count(DISTINCT bd.form_id) FILTER(where visit_month = bd.previous_month), 0)::integer AS previous_month_visits,
        COALESCE(count(DISTINCT bd.form_id) FILTER(where visit_month = bd.two_months_ago), 0)::integer AS two_month_visits,
        COUNT(DISTINCT bd.store_id) AS visited_stores,
        AVG(bd.visit_length) AS visit_duration,
        AVG(bd.visit_hour) AS hour_of_visit,
        AVG(bd.visit_dow)::integer AS most_frequent_day_of_week
    FROM base_data bd
    GROUP BY bd.rep_name, bd.visitor_email
),
final AS (
    SELECT
        ei.*,
        mv.current_visits,
        mv.previous_month_visits,
        mv.two_month_visits,
        mv.visited_stores,
        mv.visit_duration,
        mv.hour_of_visit,
        mv.most_frequent_day_of_week,
        CASE most_frequent_day_of_week
        WHEN 0 THEN 'Monday'
        WHEN 1 THEN 'Tuesday'
        WHEN 2 THEN 'Wednesday'
        WHEN 3 THEN 'Thursday'
        WHEN 4 THEN 'Friday'
        WHEN 5 THEN 'Saturday'
        WHEN 6 THEN 'Sunday'
        ELSE 'Unknown' -- Handle any unexpected values
    END AS day_of_week
    FROM employee_info ei
    LEFT JOIN monthly_visits mv
        ON ei.visitor_email = mv.visitor_email
    WHERE mv.current_visits is not null
)
SELECT
    *,
    RANK() OVER (ORDER BY current_visits DESC) AS ranking_visits,
    RANK() OVER (ORDER BY previous_month_visits DESC) AS previous_month_ranking,
    RANK() OVER (ORDER BY two_month_visits DESC) AS two_month_ranking,
    RANK() OVER (ORDER BY visit_duration DESC) AS ranking_duration
FROM final
ORDER BY visitor_email DESC;
        """
        try:
            visit_data = await self._get_dataset(
                sql,
                output_format='pandas',
                structured_obj=None
            )
            if visit_data.empty:
                raise ToolError(
                    f"No Employee Visit data found for manager {manager_id}."
                )
            return self._json_encoder(
                visit_data.to_dict(orient='records')
            )  # type: ignore[return-value]
        except ToolError as te:
            return f"No Employee Visit data found for manager {manager_id}, error: {te}"
        except ValueError as ve:
            return f"Invalid data format, error: {ve}"
        except Exception as e:
            return f"Error fetching employee visit data: {e}"

    async def get_employee_sales(
        self,
        manager_id: str,
        **kwargs
    ) -> str:
        """Get Sales and goals for all employees related to a Manager.
        Returns a ranked list of employees based on their sales performance.
        Useful for understanding employee performance and sales distribution.
        """
        sql = f"""
WITH sales AS (
WITH stores as(
    select st.store_id, d.rep_name, market_name, region_name, d.rep_email as visitor_email,
    count(store_id) filter(where focus = true) as focus_400,
    count(store_id) filter(where wall_display = true) as wall_display,
    count(store_id) filter(where triple_stack = true) as triple_stack,
    count(store_id) filter(where covered = true) as covered,
    count(store_id) filter(where end_cap = true) as endcap,
    count(store_id)  as stores
    FROM hisense.vw_stores st
    left join hisense.stores_details d using(store_id)
    where cast_to_integer(st.customer_id) = 401865
    and manager_name = '{manager_id}' and rep_name <> '0'
    group by st.store_id, d.rep_name, d.rep_email, market_name, region_name
), dates as (
    select date_trunc('month', case when firstdate < '2025-04-01' then '2025-04-01' else firstdate end)::date as month,
    case when firstdate < '2025-04-01' then '2025-04-01' else firstdate end as firstdate,
    case when lastdate > case when '2025-06-19' >= current_date then current_date - 1 else '2025-06-19' end then case when '2025-06-19' >= current_date then current_date - 1 else '2025-06-19' end else lastdate end as lastdate
    from public.week_range('2025-04-01'::date, (case when '2025-06-19' >= current_date then current_date - 1 else '2025-06-19' end)::date)
), goals as (
    select date_trunc('month',firstdate)::date as month, store_id,
    case when lower(effective_date) < firstdate and upper(effective_date)-1 = lastdate then
        troc_percent(goal_value,7) * (lastdate - firstdate + 1)::integer else
    case when lower(effective_date) = firstdate and upper(effective_date)-1 > lastdate then
        troc_percent(goal_value,7) * (lastdate - lower(effective_date) + 1)::integer else
    goal_value
    end end as goal_mes,
    lower(effective_date) as firstdate_effective, firstdate,  upper(effective_date)-1 as lastdate_effective, lastdate, goal_value, (lastdate - firstdate + 1)::integer as dias_one, (lastdate - lower(effective_date) + 1)::integer as last_one, (firstdate - lower(effective_date) + 1)::integer as dias
    from hisense.stores_goals g
    cross join dates d
    where effective_date @> firstdate::date
    and goal_name = 'Sales Weekly Premium'
), total_goals as (
    select month, store_id, sum(goal_mes) as goal_value
    from goals
    group by month, store_id
), sales as (
    select date_trunc('month',order_date_week)::date as month, store_id, coalesce(sum(net_sales),0) as sales
    from hisense.summarized_inventory i
    INNER JOIN hisense.all_products p using(model)
    where order_date_week::date between '2025-04-01'::date and (case when '2025-06-19' >= current_date then current_date - 1 else '2025-06-19' end)::date
    and cast_to_integer(i.customer_id) = 401865
    and new_model = true
    and store_id is not null
    group by date_trunc('month',order_date_week)::date, store_id
)
select rep_name, visitor_email,
coalesce(sum(st.stores),0)/3 as count_store,
coalesce(sum(sales) filter(where month = '2025-06-01'),0)::integer as sales_current,
coalesce(sum(sales) filter(where month = '2025-05-01'),0)::integer as sales_previous_month,
coalesce(sum(sales) filter(where month = '2025-04-01'),0)::integer as sales_2_month,
coalesce(sum(goal_value) filter(where month = '2025-06-01'),0) as goal_current,
coalesce(sum(goal_value) filter(where month = '2025-05-01'),0) as goal_previous_month,
coalesce(sum(goal_value) filter(where month = '2025-04-01'),0) as goal_2_month
from stores st
left join total_goals g using(store_id)
left join sales s using(month, store_id)
group by rep_name, visitor_email
)
SELECT *,
rank() over (order by sales_current DESC) as sales_ranking,
rank() over (order by goal_current DESC) as goal_ranking
FROM sales
        """
        try:
            sales_data = await self._get_dataset(
                sql,
                output_format='pandas',
                structured_obj=None
            )
            if sales_data.empty:
                raise ToolError(
                    f"No Sales data found for manager {manager_id}."
                )
            return self._json_encoder(
                sales_data.to_dict(orient='records')
            )  # type: ignore[return-value]
        except ToolError as te:
            return f"No Sales data found for manager {manager_id}, error: {te}"
        except ValueError as ve:
            return f"Invalid data format, error: {ve}"
        except Exception as e:
            return f"Error fetching employee sales data: {e}"

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
        email: str,
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
    AND d.visitor_email = '{email}'
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
                    f"No Employee Visit data found for email {email}."
                )
            return visit_data
        except ToolError as te:
            return f"No Employee Visit data found for email {email}, error: {te}"
        except ValueError as ve:
            return f"Invalid data format, error: {ve}"
        except Exception as e:
            return f"Error fetching employee visit data: {e}"
