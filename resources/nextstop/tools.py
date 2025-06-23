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
from .models import StoreInfoInput, ManagerInput


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
            self._get_employee_visits_tool()
        ]


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
                "Returns detailed information including visit timestamps, duration, "
                "customer types, and visit purposes. Useful for understanding recent "
                "customer activity patterns and store performance."
            ),
            args_schema=StoreInfoInput,
            handle_tool_error=True
        )

    async def get_visit_info(self, store_id: str) -> pd.DataFrame:
        """Get visit information for a specific store.

        This coroutine retrieves the most recent visits for the specified store,
        including detailed visit metrics and questions answered during those visits.

        Args:
            store_id (str): The unique identifier of the store.

        Returns:
            str: Pandas dataframe containing the last visits with detailed information.
        """
        sql = f"""
WITH visit_data AS (
    SELECT
        form_id,
        formid,
        visit_date::date AS visit_date,
        visitor_name,
        visitor_username,
        visitor_role,
        visit_timestamp,
        visit_length,
        time_in,
        time_out,
        d.store_id,
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
                'data', data
            ) ORDER BY column_name
        ) AS visit_data,

        -- Aggregate visitor data
        jsonb_agg(
            DISTINCT jsonb_build_object(
                'visitor_name', visitor_name,
                'username', visitor_username,
                'role', visitor_role
            )
        ) AS visitor,
        -- Period calculations
        CASE WHEN visit_date::date >= CURRENT_DATE - INTERVAL '7 days' THEN 1 ELSE 0 END AS in_7_days,
        CASE WHEN visit_date::date >= CURRENT_DATE - INTERVAL '14 days' THEN 1 ELSE 0 END AS in_14_days,
        CASE WHEN visit_date::date >= CURRENT_DATE - INTERVAL '21 days' THEN 1 ELSE 0 END AS in_21_days,

        -- Week-specific calculations for variance analysis
        CASE WHEN visit_date::date >= CURRENT_DATE - INTERVAL '7 days' THEN 1 ELSE 0 END AS in_week_1,
        CASE WHEN visit_date::date >= CURRENT_DATE - INTERVAL '14 days'
             AND visit_date::date < CURRENT_DATE - INTERVAL '7 days' THEN 1 ELSE 0 END AS in_week_2,
        CASE WHEN visit_date::date >= CURRENT_DATE - INTERVAL '21 days'
             AND visit_date::date < CURRENT_DATE - INTERVAL '14 days' THEN 1 ELSE 0 END AS in_week_3

    FROM hisense.form_data d
    INNER JOIN troc.stores st ON st.store_id = d.store_id AND st.program_slug = 'hisense'
    WHERE visit_date::date >= CURRENT_DATE - INTERVAL '21 days'
    AND column_name IN ('9733','9731','9732','9730')
    AND d.store_id = '{store_id}'
    GROUP BY
        form_id, formid, visit_date, visit_timestamp, visit_length,
        time_in, time_out, d.store_id, st.alt_name, visitor_name, visitor_username, visitor_role
),
-- Weekly statistics for variance calculations
weekly_stats AS (
    SELECT
        -- Week 1 (most recent 7 days)
        SUM(in_week_1) AS week_1_total_visits,
        COUNT(DISTINCT CASE WHEN in_week_1 = 1 THEN store_id END) AS week_1_unique_stores,
        ROUND(SUM(in_week_1)::numeric / 7, 2) AS week_1_avg_daily_visits,

        -- Week 2 (days 8-14)
        SUM(in_week_2) AS week_2_total_visits,
        COUNT(DISTINCT CASE WHEN in_week_2 = 1 THEN store_id END) AS week_2_unique_stores,
        ROUND(SUM(in_week_2)::numeric / 7, 2) AS week_2_avg_daily_visits,

        -- Week 3 (days 15-21)
        SUM(in_week_3) AS week_3_total_visits,
        COUNT(DISTINCT CASE WHEN in_week_3 = 1 THEN store_id END) AS week_3_unique_stores,
        ROUND(SUM(in_week_3)::numeric / 7, 2) AS week_3_avg_daily_visits

    FROM visit_data
),
-- Store visit counts by week for median calculations
store_visit_counts_by_week AS (
    SELECT
        store_id,
        SUM(in_week_1) AS week_1_visits,
        SUM(in_week_2) AS week_2_visits,
        SUM(in_week_3) AS week_3_visits
    FROM visit_data
    GROUP BY store_id
),
-- Median calculations by week
weekly_medians AS (
    SELECT
        PERCENTILE_CONT(0.5) WITHIN GROUP (ORDER BY week_1_visits) AS week_1_median_visits_per_store,
        PERCENTILE_CONT(0.5) WITHIN GROUP (ORDER BY week_2_visits) AS week_2_median_visits_per_store,
        PERCENTILE_CONT(0.5) WITHIN GROUP (ORDER BY week_3_visits) AS week_3_median_visits_per_store
    FROM store_visit_counts_by_week
    WHERE week_1_visits > 0 OR week_2_visits > 0 OR week_3_visits > 0
),
-- Calculate summary statistics
summary_stats AS (
    SELECT
        -- Total visits by period
        SUM(in_7_days) AS total_visits_7_days,
        SUM(in_14_days) AS total_visits_14_days,
        SUM(in_21_days) AS total_visits_21_days,

        -- Unique stores by period
        COUNT(DISTINCT CASE WHEN in_7_days = 1 THEN vd.store_id END) AS stores_visited_7_days,
        COUNT(DISTINCT CASE WHEN in_14_days = 1 THEN vd.store_id END) AS stores_visited_14_days,
        COUNT(DISTINCT CASE WHEN in_21_days = 1 THEN vd.store_id END) AS stores_visited_21_days,

        -- Visit averages per day
        ROUND(SUM(in_7_days)::numeric / 7, 2) AS avg_daily_visits_7_days,
        ROUND(SUM(in_14_days)::numeric / 14, 2) AS avg_daily_visits_14_days,
        ROUND(SUM(in_21_days)::numeric / 21, 2) AS avg_daily_visits_21_days,

        -- Visit medians (visits per store)
        PERCENTILE_CONT(0.5) WITHIN GROUP (
            ORDER BY store_visit_counts_7.visit_count
        ) AS median_visits_per_store_7_days,
        PERCENTILE_CONT(0.5) WITHIN GROUP (
            ORDER BY store_visit_counts_14.visit_count
        ) AS median_visits_per_store_14_days,
        PERCENTILE_CONT(0.5) WITHIN GROUP (
            ORDER BY store_visit_counts_21.visit_count
        ) AS median_visits_per_store_21_days

    FROM visit_data vd
    LEFT JOIN (
        SELECT store_id, COUNT(*) as visit_count
        FROM visit_data WHERE in_7_days = 1 GROUP BY store_id
    ) store_visit_counts_7 ON vd.store_id = store_visit_counts_7.store_id
    LEFT JOIN (
        SELECT store_id, COUNT(*) as visit_count
        FROM visit_data WHERE in_14_days = 1 GROUP BY store_id
    ) store_visit_counts_14 ON vd.store_id = store_visit_counts_14.store_id
    LEFT JOIN (
        SELECT store_id, COUNT(*) as visit_count
        FROM visit_data WHERE in_21_days = 1 GROUP BY store_id
    ) store_visit_counts_21 ON vd.store_id = store_visit_counts_21.store_id
),
-- Week-over-week variance calculations
variance_stats AS (
    SELECT
        ws.*,
        wm.*,

        -- Week-over-week variance for total visits
        CASE
            WHEN ws.week_2_total_visits > 0 THEN
                ROUND(((ws.week_1_total_visits - ws.week_2_total_visits)::numeric / ws.week_2_total_visits::numeric * 100), 2)
            ELSE NULL
        END AS week_1_vs_week_2_total_visits_variance_pct,

        CASE
            WHEN ws.week_3_total_visits > 0 THEN
                ROUND(((ws.week_2_total_visits - ws.week_3_total_visits)::numeric / ws.week_3_total_visits::numeric * 100), 2)
            ELSE NULL
        END AS week_2_vs_week_3_total_visits_variance_pct,

        -- Week-over-week variance for average daily visits
        CASE
            WHEN ws.week_2_avg_daily_visits > 0 THEN
                ROUND(((ws.week_1_avg_daily_visits - ws.week_2_avg_daily_visits) / ws.week_2_avg_daily_visits * 100)::numeric, 2)
            ELSE NULL
        END AS week_1_vs_week_2_avg_daily_variance_pct,

        CASE
            WHEN ws.week_3_avg_daily_visits > 0 THEN
                ROUND(((ws.week_2_avg_daily_visits - ws.week_3_avg_daily_visits) / ws.week_3_avg_daily_visits * 100)::numeric, 2)
            ELSE NULL
        END AS week_2_vs_week_3_avg_daily_variance_pct,

        -- Week-over-week variance for median visits per store
        CASE
            WHEN wm.week_2_median_visits_per_store > 0 THEN
                ROUND(((wm.week_1_median_visits_per_store - wm.week_2_median_visits_per_store) / wm.week_2_median_visits_per_store * 100)::numeric, 2)
            ELSE NULL
        END AS week_1_vs_week_2_median_variance_pct,

        CASE
            WHEN wm.week_3_median_visits_per_store > 0 THEN
                ROUND(((wm.week_2_median_visits_per_store - wm.week_3_median_visits_per_store) / wm.week_3_median_visits_per_store * 100)::numeric, 2)
            ELSE NULL
        END AS week_2_vs_week_3_median_variance_pct,

        -- Week-over-week variance for unique stores
        CASE
            WHEN ws.week_2_unique_stores > 0 THEN
                ROUND(((ws.week_1_unique_stores - ws.week_2_unique_stores)::numeric / ws.week_2_unique_stores::numeric * 100), 2)
            ELSE NULL
        END AS week_1_vs_week_2_unique_stores_variance_pct,

        CASE
            WHEN ws.week_3_unique_stores > 0 THEN
                ROUND(((ws.week_2_unique_stores - ws.week_3_unique_stores)::numeric / ws.week_3_unique_stores::numeric * 100), 2)
            ELSE NULL
        END AS week_2_vs_week_3_unique_stores_variance_pct

    FROM weekly_stats ws
    CROSS JOIN weekly_medians wm
)
-- Final result set
SELECT
    vd.*,
    ss.total_visits_7_days,
    ss.total_visits_14_days,
    ss.total_visits_21_days,
    ss.stores_visited_7_days,
    ss.stores_visited_14_days,
    ss.stores_visited_21_days,
    ss.avg_daily_visits_7_days,
    ss.avg_daily_visits_14_days,
    ss.avg_daily_visits_21_days,
    ss.median_visits_per_store_7_days,
    ss.median_visits_per_store_14_days,
    ss.median_visits_per_store_21_days,
    -- Weekly breakdown
    vs.week_1_total_visits,
    vs.week_2_total_visits,
    vs.week_3_total_visits,
    vs.week_1_unique_stores,
    vs.week_2_unique_stores,
    vs.week_3_unique_stores,
    vs.week_1_avg_daily_visits,
    vs.week_2_avg_daily_visits,
    vs.week_3_avg_daily_visits,
    vs.week_1_median_visits_per_store,
    vs.week_2_median_visits_per_store,
    vs.week_3_median_visits_per_store,
    -- Week-over-week variance percentages
    vs.week_1_vs_week_2_total_visits_variance_pct,
    vs.week_2_vs_week_3_total_visits_variance_pct,
    vs.week_1_vs_week_2_avg_daily_variance_pct,
    vs.week_2_vs_week_3_avg_daily_variance_pct,
    vs.week_1_vs_week_2_median_variance_pct,
    vs.week_2_vs_week_3_median_variance_pct,
    vs.week_1_vs_week_2_unique_stores_variance_pct,
    vs.week_2_vs_week_3_unique_stores_variance_pct
FROM visit_data vd
CROSS JOIN summary_stats ss
CROSS JOIN variance_stats vs
ORDER BY vd.visit_timestamp ASC;
        """
        visit_data = await self.get_dataset(sql, output='pandas')
        if visit_data.empty:
            raise ToolException(
                f"No visit data found for store with ID {store_id}."
            )
        return visit_data


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

    async def get_employee_sales(self, manager_id: str) -> pd.DataFrame:
        """Get foot traffic data for a specific store.
        This coroutine retrieves the foot traffic data for the specified store,
        including the number of visitors and average visits per day.

        Args:
            manager (str): The unique identifier of the Manager (Associate OID).
        Returns:
            pd.DataFrame: DataFrame containing employee sales data and rankings.
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
        return visit_data

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

    async def get_employee_visits(self, manager_id: str) -> pd.DataFrame:
        """Get Employee Visits data for a specific Manager.
        This coroutine retrieves the visit data for employees under a specific manager,
        including the number of visits, average visit duration, and most frequent visit hours.
        Args:
            manager (str): The unique identifier of the Manager (Associate OID).
        Returns:
            pd.DataFrame: DataFrame containing employee sales data and rankings.
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
        return visit_data
