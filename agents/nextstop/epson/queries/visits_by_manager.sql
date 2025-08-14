WITH employee_data AS (
WITH employee_info AS (
    SELECT
        d.market_trainer_name as visitor_name,
        d.market_trainer_unq_id as visitor_email,
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
    FROM epson.vw_stores st
    LEFT JOIN epson.stores_details d USING (store_id)
    WHERE d.regional_manager_email = '{manager_id}' ---'cjang@trocglobal.com'
    GROUP BY d.market_trainer_name, d.market_trainer_unq_id
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
    FROM epson.form_information f
    JOIN employee_info e USING(visitor_email)
    LEFT JOIN epson.stores_details d USING (store_id)
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
    AND d.regional_manager_email = '{manager_id}' ---'cjang@trocglobal.com'
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
