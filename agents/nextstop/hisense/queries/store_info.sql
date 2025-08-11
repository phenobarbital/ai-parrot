SELECT st.store_id, store_name, street_address, city, latitude, longitude, zipcode,
state_code, market_name, district_name, account_name, vs.*
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
