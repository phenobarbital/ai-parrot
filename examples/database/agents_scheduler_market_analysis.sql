-- Example database-backed schedule for the market_analysis crew.
-- Triggers the crew every Monday at 9:00 UTC and emails the results.
INSERT INTO navigator.service_scheduler (
    schedule_id,
    target_kind,
    target_name,
    target_id,
    prompt,
    method_name,
    schedule_type,
    schedule_config,
    enabled,
    created_by,
    created_email,
    metadata,
    send_result,
    callbacks
) VALUES (
    uuid_generate_v4(),
    'crew',
    'market_analysis',
    'crew.market_analysis',
    'Provide the weekly global market analysis briefing.',
    'run_sequential',
    'weekly',
    '{"day_of_week": "mon", "hour": 9, "minute": 0}'::jsonb,
    TRUE,
    101,
    'jlara@trocglobal.com',
    '{}'::jsonb,
    '{"emails": ["jlara@trocglobal.com"], "subject": "Market analysis weekly report", "include_result": true}'::jsonb,
    '[]'::jsonb
);
