SELECT store_id, start_date, avg_visits_per_day, foottraffic,
visits_by_day_of_week_monday, visits_by_day_of_week_tuesday,
visits_by_day_of_week_wednesday, visits_by_day_of_week_thursday,
visits_by_day_of_week_friday, visits_by_day_of_week_saturday,
visits_by_day_of_week_sunday
FROM placerai.weekly_traffic
WHERE store_id = '{store_id}'
ORDER BY start_date DESC
LIMIT 3;
