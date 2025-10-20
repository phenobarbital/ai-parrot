-- Example schedule entry for the market_analysis crew.
-- Triggers the crew every Monday at 9:00 UTC and emails the results.
INSERT INTO navigator.agents_scheduler (
    schedule_id,
    agent_id,
    agent_name,
    prompt,
    method_name,
    schedule_type,
    schedule_config,
    enabled,
    created_by,
    created_email,
    metadata,
    is_crew,
    send_result
) VALUES (
    uuid_generate_v4(),
    'crew.market_analysis',
    'market_analysis',
    'Provide the weekly global market analysis briefing.',
    'run_sequential',
    'weekly',
    '{"day_of_week": "mon", "hour": 9, "minute": 0}'::jsonb,
    TRUE,
    101,
    'jlara@trocglobal.com',
    '{}'::jsonb,
    TRUE,
    '{"emails": ["jlara@trocglobal.com"], "subject": "Market analysis weekly report", "include_result": true}'::jsonb
);
