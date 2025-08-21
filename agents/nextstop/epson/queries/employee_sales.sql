WITH employee as (
  SELECT store_id, display_name, corporate_email as email,
  (DATE_TRUNC('week', CURRENT_DATE)::date - 2) - INTERVAL '1 week' AS current_week,
  (DATE_TRUNC('week', CURRENT_DATE)::date - 2) - INTERVAL '2 week' AS previous_week,
  (DATE_TRUNC('week', (CURRENT_DATE - INTERVAL '1 month'))::date - 2)::date AS week_previous_month
  FROM epson.stores_details d
  JOIN troc.troc_employees e ON d.market_trainer_name = e.display_name and corporate_email = '{employee_id}'
), sales AS (
SELECT
  store_id, email,
  sum(sell_thru_qty) FILTER(WHERE i.order_date::date = e.current_week::date) AS sales_current_week,
  sum(sell_thru_qty) FILTER(where i.order_date::date = e.previous_week::date) AS sales_previous_week,
  sum(sell_thru_qty) FILTER(where i.order_date::date = e.week_previous_month::date) AS sales_previous_month
  FROM epson.summarize_sales_by_day i
  JOIN employee e USING(store_id)
  WHERE order_date::date between e.week_previous_month and current_date - 1
  GROUP BY store_id, email
), ranked AS (
  SELECT
    a.store_id, a.email, coalesce(sales_current_week, 0) as sales_current_week,
    coalesce(sales_previous_week, 0) as sales_previous_week, coalesce(sales_previous_month, 0) as sales_previous_month,
    DENSE_RANK() OVER (ORDER BY a.sales_current_week DESC NULLS LAST) AS r_desc_week,
    DENSE_RANK() OVER (ORDER BY a.sales_current_week ASC NULLS LAST)  AS r_asc_week
  FROM sales a
), filter AS (
SELECT store_id, sales_current_week, sales_previous_week,
-- absolute delta week over week
(s.sales_current_week - s.sales_previous_week) AS week_over_week_delta,
-- percentage delta week over week; NULL if previous is 0 or NULL
coalesce(CASE
      WHEN s.sales_previous_week IS NULL OR s.sales_previous_week = 0 THEN NULL
      ELSE (s.sales_current_week - s.sales_previous_week)::numeric
           / NULLIF(s.sales_previous_week, 0)::numeric
END, 0.0) AS week_over_week_variance,
    CASE
      WHEN s.r_desc_week <= 3 THEN 'top'
      WHEN s.r_asc_week  <= 3 THEN 'bottom'
      ELSE 'middle'
    END AS tier
FROM ranked s
), numbered AS (
  SELECT f.*,
  ROW_NUMBER() OVER (
      PARTITION BY f.tier
      ORDER BY
        -- For 'top' we want highest first; for 'bottom' we want lowest first.
        CASE
          WHEN f.tier = 'top'    THEN -f.sales_current_week
          WHEN f.tier = 'bottom' THEN  f.sales_current_week
          ELSE  0
        END,
        f.store_id
    ) AS rn_tier
    FROM filter f WHERE f.tier IN ('top','bottom')
)
select * from numbered;
