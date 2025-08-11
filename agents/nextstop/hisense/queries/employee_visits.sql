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
    INNER JOIN troc.stores st ON st.store_id = d.store_id AND st.program_slug = 'hisense'
    WHERE visit_date::date between (current_date::date - interval '1 week')::date and current_date::date
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
