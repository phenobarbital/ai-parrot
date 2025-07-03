from typing import List
import json
import pandas as pd
from pydantic import BaseModel, Field
from datamodel.parsers.json import json_encoder, json_decoder  # pylint: disable=E0611
from langchain_core.tools import (
    BaseTool,
    BaseToolkit,
    StructuredTool,
    ToolException,
    Tool
)
# AsyncDB database connections
from asyncdb import AsyncDB
from querysource.conf import default_dsn
from .models import (
    StoreInfoInput,
    ManagerInput,
    EmployeeInput
)

class StoreInfo(BaseToolkit):
    """Comprehensive toolkit for store information and demographic analysis.

    This toolkit provides tools to:
    1. Get detailed visit information for specific stores including recent visit history
    2. Retrieve comprehensive store information including location and visit statistics
    3. Foot traffic analysis for stores, providing insights into customer behavior

    All tools are designed to work asynchronously with database connections and external APIs.

    Tools included:
    - get_visit_info: Retrieves the last visits for a specific store
    - get_foot_traffic: Fetches foot traffic data for a store
    - get_store_information: Gets complete store details and aggregate visit metrics
    - get_employee_sales: Fetches Employee Sales data and ranked performance.
    """
    name: str = "StoreInfo"
    description: str = (
        "Toolkit for retrieving store information, visit history, "
        "foot traffic data, and demographic analysis. "
        "Includes tools for fetching detailed visit records, "
        "store details, and foot traffic statistics."
    )
    # Allow arbitrary types and forbid extra fields in the model
    model_config = {
        "arbitrary_types_allowed": False,
        "extra": "forbid",
    }

    async def get_dataset(self, query: str, output: str = 'pandas') -> pd.DataFrame:
        """Fetch a dataset based on the provided query.

        Args:
            query (str): The query string to fetch the dataset.

        Returns:
            pd.DataFrame: A pandas DataFrame containing the dataset.
        """
        db = AsyncDB('pg', dsn=default_dsn)
        async with await db.connection() as conn:  # pylint: disable=E1101  # noqa
            conn.output_format(output)
            result, error = await conn.query(
                query
            )
            if error:
                raise ToolException(
                    f"Error fetching dataset: {error}"
                )
            return result

    def get_tools(self) -> List[BaseTool]:
        """Get all available tools in the toolkit.

        Returns:
            List[BaseTool]: A list of configured Langchain tools ready for agent use.
        """
        return [
            self._get_visit_info_tool(),
            self._get_store_info_tool(),
            self._get_foot_traffic_tool(),
            self._get_employee_sales_tool(),
            self._get_by_employee_visits_tool(),
            self._get_employee_visits_tool()
        ]

    def _get_by_employee_visits_tool(self) -> StructuredTool:
        """Visits information retrieval tool.

        Returns:
            StructuredTool: Configured tool for getting recent weekly visits made by an employee.
        """
        return StructuredTool.from_function(
            name="get_by_employee_visits",
            func=self.get_by_employee_visits,
            coroutine=self.get_by_employee_visits,
            description=(
                "Get statistics about visits made by an Employee during the current week. "
                "Returns detailed visit information for the specified employee. "
                "Data is returned as a pandas dataframe with visit metrics."
            ),
            args_schema=EmployeeInput,
            # return_direct=True,
            handle_tool_error=True
        )

    async def get_by_employee_visits(self, employee_id: str) -> dict:
        """Get visits information for a specific employee.

        This coroutine retrieves the most recent visits made by the specified employee,
        including detailed visit metrics and questions answered during those visits.

        Args:
            employee_id (str): The unique identifier of the employee.

        Returns:
            dict: Data containing the last visits with detailed information.
        """
        sql = f"""
WITH visit_data AS (
    SELECT
        form_id,
        formid,
        visit_date::date AS visit_date,
        visitor_name,
        visitor_email,
        visitor_role,
        visit_timestamp,
        visit_length,
        visit_hour,
        time_in,
        time_out,
        d.store_id,
        d.visit_dow,
        d.account_name,
        st.alt_name as alt_store,
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
        visit_data = await self.get_dataset(sql, output='pandas')
        if visit_data.empty:
            raise ToolException(
                f"No Visit data found for Employee {employee_id}."
            )
        result = visit_data.to_dict(orient='records')
        if isinstance(result, list) and len(result) == 1:
            # If only one record, return it directly
            return result[0]
        return result

    def _get_foot_traffic_tool(self) -> StructuredTool:
        """Create the traffic information retrieval tool.

        Returns:
            StructuredTool: Configured tool for getting recent foot traffic data for a store.
        """
        return StructuredTool.from_function(
            name="get_foot_traffic",
            func=self.get_foot_traffic,
            coroutine=self.get_foot_traffic,
            description=(
                "Get the Foot Traffic and average visits by day from a specific store. "
            ),
            args_schema=StoreInfoInput,
            handle_tool_error=True
        )

    async def get_foot_traffic(self, store_id: str) -> str:
        """Get foot traffic data for a specific store.
        This coroutine retrieves the foot traffic data for the specified store,
        including the number of visitors and average visits per day.

        Args:
            store_id (str): The unique identifier of the store.
        Returns:
            str: JSON string containing foot traffic data for the store.
        """
        sql = f"""
SELECT store_id, start_date, avg_visits_per_day, foottraffic, visits_by_day_of_week_monday, visits_by_day_of_week_tuesday, visits_by_day_of_week_wednesday, visits_by_day_of_week_thursday, visits_by_day_of_week_friday, visits_by_day_of_week_saturday, visits_by_day_of_week_sunday
FROM placerai.weekly_traffic
WHERE store_id = '{store_id}'
ORDER BY start_date DESC
LIMIT 3;
        """
        visit_data = await self.get_dataset(sql, output='pandas')
        if visit_data.empty:
            raise ToolException(
                f"No Foot Traffic data found for store with ID {store_id}."
            )
        return visit_data

    def _get_visit_info_tool(self) -> StructuredTool:
        """Create the visit information retrieval tool.

        Returns:
            StructuredTool: Configured tool for getting recent visit data for a store.
        """
        return StructuredTool.from_function(
            name="get_visit_info",
            func=self.get_visit_info,
            coroutine=self.get_visit_info,
            description=(
                "Retrieve the last 3 visits made to a specific store. "
                "Returns detailed visit information including timestamps, "
                " duration, customer types, and visit purposes. "
                " Data is a list of dictionaries with visit details."
            ),
            args_schema=StoreInfoInput,
            handle_tool_error=True
        )

    async def get_visit_info(self, store_id: str) -> List[dict]:
        """Get visit information for a specific store.

        This coroutine retrieves the most recent visits for the specified store,
        including detailed visit metrics and questions answered during those visits.

        Args:
            store_id (str): The unique identifier of the store.

        Returns:
            List[dict]: Data containing the last visits with detailed information.
        """
        sql = f"""
WITH visits AS (
WITH last_visits AS (
    select store_id, visit_timestamp
    from hisense.form_information
    where store_id = '{store_id}'
    order by visit_timestamp desc limit 3
)
    SELECT
        form_id,
        formid,
        visit_date::date AS visit_date,
        visitor_name,
        visitor_email,
        visitor_username,
        visitor_role,
        visit_timestamp,
        visit_length,
        time_in,
        time_out,
        d.store_id,
        d.visit_dow,
        d.visit_hour,
        st.alt_name as alt_store,
        -- Calculate time spent in decimal minutes
        CASE
            WHEN time_in IS NOT NULL AND time_out IS NOT NULL THEN
                EXTRACT(EPOCH FROM (time_out::time - time_in::time)) / 60.0
            ELSE NULL
         END AS time_spent_minutes,

        -- Aggregate visit data
        jsonb_agg(
            jsonb_build_object(
                'column_name', column_name,
                'question', question,
                'answer', data
            ) ORDER BY column_name
        ) AS visit_data
    FROM last_visits lv
    JOIN hisense.form_data d using(store_id, visit_timestamp)
    JOIN troc.stores st ON st.store_id = d.store_id AND st.program_slug = 'hisense'
    WHERE column_name IN ('9733','9731','9732','9730')
    GROUP BY
        form_id, formid, visit_date, visit_timestamp, visit_length, visitor_email,
        time_in, time_out, d.store_id, st.alt_name, visitor_name, visitor_username, visitor_role, d.visit_dow, d.visit_hour
), visit_stats as (
  SELECT visitor_email,
    max(visit_date) as latest_visit_date,
    COUNT(DISTINCT v.form_id) AS number_of_visits,
    COUNT(DISTINCT v.store_id) AS visited_stores,
    AVG(v.visit_length) AS visit_duration,
    AVG(v.visit_hour) AS average_hour_visit,
    mode() WITHIN GROUP (ORDER BY v.visit_hour) as most_frequent_hour_of_day,
    mode() WITHIN GROUP (ORDER BY v.visit_dow) AS most_frequent_day_of_week,
    percentile_disc(0.5) WITHIN GROUP (ORDER BY visit_length) AS median_visit_duration
  FROM visits v
  GROUP BY visitor_email
), median_visits AS (
  SELECT
      visitor_email,
      percentile_disc(0.5) WITHIN GROUP (ORDER BY visited_stores)
          AS median_visits_per_store
  FROM visit_stats
  GROUP BY visitor_email
)
SELECT v.*, vs.number_of_visits, vs.latest_visit_date, vs.visited_stores, vs.average_hour_visit, vs.most_frequent_hour_of_day, vs.most_frequent_day_of_week,
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
mv.median_visits_per_store, vs.median_visit_duration
FROM visits v
JOIN visit_stats vs USING(visitor_email)
JOIN median_visits mv USING(visitor_email)
        """
        visit_data = await self.get_dataset(sql, output='pandas')
        if visit_data.empty:
            raise ToolException(
                f"No visit data found for store with ID {store_id}."
            )
        return visit_data.to_dict(orient='records')


    def _get_store_info_tool(self) -> StructuredTool:
        """Create the store information retrieval tool.

        Returns:
            StructuredTool: Configured tool for getting comprehensive store details.
        """
        return StructuredTool.from_function(
            name="get_store_information",
            func=self.get_store_information,
            coroutine=self.get_store_information,
            description=(
                "Get comprehensive store information including location details, "
                "contact information, operating hours, and aggregate visit statistics. "
                "Provides total visits, unique visitors, and average visit duration "
                "for the specified store. Essential for store analysis and planning."
            ),
            args_schema=StoreInfoInput,
            handle_tool_error=True
        )

    async def get_store_information(self, store_id: str) -> str:
        """Get comprehensive store information for a specific store.

        This coroutine retrieves complete store details including location,
        contact information, operating schedule, and aggregate visit metrics.

        Args:
            store_id (str): The unique identifier of the store.

        Returns:
            str: JSON string containing comprehensive store information and visit statistics.
        """

        print(f"DEBUG: Tool called with store_id: {store_id}")
        sql = f"""
        SELECT st.store_id, store_name, street_address, city, latitude, longitude, zipcode,
        state_code market_name, district_name, account_name, vs.*
        FROM hisense.stores st
        INNER JOIN (
            SELECT
                store_id,
                avg(visit_length) as avg_visit_length,
                count(*) as total_visits,
                avg(visit_hour) as avg_middle_time
                FROM hisense.form_information where store_id = '{store_id}'
                AND visit_date::date >= CURRENT_DATE - INTERVAL '21 days'
                GROUP BY store_id
        ) as vs ON vs.store_id = st.store_id
        WHERE st.store_id = '{store_id}';
        """
        store = await self.get_dataset(sql)
        if store.empty:
            raise ToolException(
                f"Store with ID {store_id} not found."
            )
        print(
            f"DEBUG: Fetched store data: {store.head(1).to_dict(orient='records')}"
        )
        # convert dataframe to dictionary:
        store_info = store.head(1).to_dict(orient='records')[0]
        return json_encoder(store_info)

    def _get_employee_sales_tool(self) -> StructuredTool:
        """Create the traffic information retrieval tool.

        Returns:
            StructuredTool: Configured tool for getting recent Sales data from all employees.
        """
        return StructuredTool.from_function(
            name="get_employee_sales",
            func=self.get_employee_sales,
            coroutine=self.get_employee_sales,
            description=(
                "Get Sales and goals for all employees related to a Manager. "
                "Returns a ranked list of employees based on their sales performance. "
                "Useful for understanding employee performance and sales distribution."
            ),
            args_schema=ManagerInput,
            handle_tool_error=True
        )

    async def get_employee_sales(self, manager_id: str) -> str:
        """Get foot traffic data for a specific store.
        This coroutine retrieves the foot traffic data for the specified store,
        including the number of visitors and average visits per day.

        Args:
            manager (str): The unique identifier of the Manager (Associate OID).
        Returns:
            str: Data containing employee sales data and rankings.
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
        visit_data = await self.get_dataset(sql, output='pandas')
        if visit_data.empty:
            raise ToolException(
                f"No Employee Sales data found for manager {manager_id}."
            )
        return json_encoder(visit_data.to_dict(orient='records'))

    def _get_employee_visits_tool(self) -> StructuredTool:
        """Create the employee visits retrieval tool.
        This tool retrieves visit data for employees under a specific manager,
        including the number of visits, average visit duration, and most frequent visit hours.

        Returns:
            StructuredTool: Configured tool for getting recent Visit data for all employees.
        """
        return StructuredTool.from_function(
            name="get_employee_visits",
            func=self.get_employee_visits,
            coroutine=self.get_employee_visits,
            description=(
                "Get Employee Visits data for a specific Manager. "
                "Returns a DataFrame containing employee visit statistics, "
                "including total visits, average visit duration, and most frequent visit hours. "
                "Useful for analyzing employee performance and visit patterns."
            ),
            args_schema=ManagerInput,
            handle_tool_error=True
        )

    async def get_employee_visits(self, manager_id: str) -> str:
        """Get Employee Visits data for a specific Manager.
        This coroutine retrieves the visit data for employees under a specific manager,
        including the number of visits, average visit duration, and most frequent visit hours.
        Args:
            manager (str): The unique identifier of the Manager (Associate OID).
        Returns:
            str: Data containing employee sales data and rankings.
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
        visit_data = await self.get_dataset(sql, output='pandas')
        if visit_data.empty:
            raise ToolException(
                f"No Employee Visit data found for manager {manager_id}."
            )
        return json_encoder(
            visit_data.to_dict(orient='records')
        )  # type: ignore[return-value]
