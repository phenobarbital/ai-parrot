-- Security events tracking table
CREATE TABLE IF NOT EXISTS security_events (
    event_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    event_type VARCHAR(50) NOT NULL,
    user_id VARCHAR(255) NOT NULL,
    session_id VARCHAR(255) NOT NULL,
    chatbot_id VARCHAR(255),
    severity VARCHAR(20) NOT NULL,
    threat_details JSONB NOT NULL,
    original_input TEXT,
    sanitized_input TEXT,
    metadata JSONB DEFAULT '{}',
    created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW()
);

-- Indexes for security monitoring
CREATE INDEX idx_security_events_user_id ON security_events(user_id);
CREATE INDEX idx_security_events_session_id ON security_events(session_id);
CREATE INDEX idx_security_events_severity ON security_events(severity);
CREATE INDEX idx_security_events_created_at ON security_events(created_at DESC);
CREATE INDEX idx_security_events_chatbot ON security_events(chatbot_id);

-- Index for monitoring critical/high severity events
CREATE INDEX idx_security_events_high_severity ON security_events(severity, created_at DESC)
WHERE severity IN ('critical', 'high');
