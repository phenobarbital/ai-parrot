WITH visits AS (
WITH last_visits AS (
    select store_id, visit_timestamp
    from hisense.form_information d
    where store_id = '{store_id}'
    order by visit_timestamp DESC NULLS LAST limit {limit}
)
    SELECT
        form_id,
        formid,
        visit_date::date AS visit_date,
        visitor_name,
        visitor_username,
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
        form_id, formid, visit_date, visit_timestamp, visit_length, visitor_name,
        time_in, time_out, d.store_id, st.alt_name, visitor_name, visitor_username, d.visit_dow, d.visit_hour
), visit_stats as (
  SELECT visitor_username,
    max(visit_date) as latest_visit_date,
    COUNT(DISTINCT v.form_id) AS number_of_visits,
    COUNT(DISTINCT v.store_id) AS visited_stores,
    AVG(v.visit_length) AS visit_duration,
    AVG(v.visit_hour) AS average_hour_visit,
    mode() WITHIN GROUP (ORDER BY v.visit_hour) as most_frequent_hour_of_day,
    mode() WITHIN GROUP (ORDER BY v.visit_dow) AS most_frequent_day_of_week,
    percentile_disc(0.5) WITHIN GROUP (ORDER BY visit_length) AS median_visit_duration
  FROM visits v
  GROUP BY visitor_username
), median_visits AS (
  SELECT
      visitor_username,
      percentile_disc(0.5) WITHIN GROUP (ORDER BY visited_stores)
          AS median_visits_per_store
  FROM visit_stats
  GROUP BY visitor_username
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
JOIN visit_stats vs USING(visitor_username)
JOIN median_visits mv USING(visitor_username)
