-- FEAT-704 §8 Q3 — semantic-layer audit events (one row per SemanticAuditEntry)
CREATE TABLE IF NOT EXISTS semantic_audit_events (
    entry_id UUID PRIMARY KEY,
    created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW(),
    user_id VARCHAR(255) NOT NULL,
    tenant_id VARCHAR(255) NOT NULL,
    model VARCHAR(255) NOT NULL,
    outcome VARCHAR(32) NOT NULL,
    payload JSONB NOT NULL,
    signature TEXT NOT NULL DEFAULT ''
);
CREATE INDEX IF NOT EXISTS idx_semantic_audit_user_id ON semantic_audit_events(user_id);
CREATE INDEX IF NOT EXISTS idx_semantic_audit_tenant_id ON semantic_audit_events(tenant_id);
CREATE INDEX IF NOT EXISTS idx_semantic_audit_model ON semantic_audit_events(model);
CREATE INDEX IF NOT EXISTS idx_semantic_audit_outcome ON semantic_audit_events(outcome);
CREATE INDEX IF NOT EXISTS idx_semantic_audit_created_at ON semantic_audit_events(created_at DESC);
