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
