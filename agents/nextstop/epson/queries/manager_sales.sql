WITH stores AS (
    SELECT
    st.store_id, d.market_trainer_name as visitor_name,
    d.market_trainer_unq_id as visitor_email,
    COUNT(DISTINCT st.store_id) AS assigned_stores,
    (DATE_TRUNC('week', CURRENT_DATE)::date - 2) - INTERVAL '1 week' AS current_week,
    (DATE_TRUNC('week', CURRENT_DATE)::date - 2) - INTERVAL '2 week' AS previous_week,
    (DATE_TRUNC('week', (CURRENT_DATE - INTERVAL '1 month'))::date - 2)::date AS week_previous_month
    FROM epson.vw_stores st
    JOIN epson.stores_details d USING (store_id)
    WHERE regional_manager_email = '{manager_id}'
    GROUP BY st.store_id, d.market_trainer_name, d.market_trainer_unq_id
), sales AS (
  SELECT
  e.visitor_name,
  e.visitor_email,
  sum(coalesce(revenue, 0)) as total_sales,
  sum(sell_thru_qty) FILTER(WHERE i.order_date::date = e.current_week::date) AS sales_current_week,
  sum(sell_thru_qty) FILTER(where i.order_date::date = e.previous_week::date) AS sales_previous_week,
  sum(sell_thru_qty) FILTER(where i.order_date::date = e.week_previous_month::date) AS sales_previous_month
  FROM epson.summarize_sales_by_day i
  JOIN stores e USING(store_id)
  WHERE order_date::date between e.week_previous_month and current_date - 1
  GROUP BY e.visitor_name, e.visitor_email
)
SELECT *,
 rank() over (order by sales_current_week DESC) as current_ranking,
 rank() over (order by sales_previous_week DESC) as previous_week_ranking,
 rank() over (order by sales_previous_month DESC) as previous_month_ranking
FROM sales;
