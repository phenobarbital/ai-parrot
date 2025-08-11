WITH last_visits AS (
    select store_id, visit_timestamp
    from hisense.form_information d
    where store_id = '{store_id}'
    order by visit_timestamp DESC NULLS LAST limit {limit}
)
SELECT st.store_id, store_name, street_address, city, latitude, longitude, zipcode,
state_code, market_name, district_name, account_name, vs.*
FROM hisense.stores st
INNER JOIN (
    SELECT
        store_id,
        avg(visit_length) as avg_visit_length,
        count(*) as total_visits,
        avg(visit_hour) as avg_middle_time
        FROM last_visits v
        JOIN hisense.form_information d USING(store_id, visit_timestamp)
        GROUP BY store_id
) as vs ON vs.store_id = st.store_id
WHERE st.store_id = '{store_id}';
