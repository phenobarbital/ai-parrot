-- FEAT-884 postcondition: no old tool keys remain in arrays; unrelated and non-array values remain untouched.
SELECT NOT EXISTS (
    SELECT 1
    FROM {schema}.{bots_table}
    WHERE jsonb_typeof(tools) = 'array'
      AND tools ?| ARRAY['WebScraperTool', 'Ibis', 'Tickertool']
);
