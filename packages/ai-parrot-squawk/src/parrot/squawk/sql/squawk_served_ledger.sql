-- FEAT-746 M9a — served ledger durable sink (one row per signed ServedLedgerEntry)
CREATE TABLE IF NOT EXISTS squawk_served_ledger (
    entry_id        TEXT PRIMARY KEY,
    created_at      TIMESTAMPTZ NOT NULL,
    caller          JSONB NOT NULL,
    cap_id          TEXT NOT NULL,
    category        TEXT NOT NULL,
    contract_hash   TEXT NOT NULL,
    args_digest     TEXT NOT NULL,
    status          TEXT NOT NULL,
    result_kind     TEXT NOT NULL,
    result_digest   TEXT,
    cost            JSONB NOT NULL,
    backing         TEXT NOT NULL,
    trace_id        TEXT NOT NULL,
    correlation_id  TEXT,
    signature       TEXT NOT NULL,
    raw             JSONB NOT NULL
);
CREATE INDEX IF NOT EXISTS squawk_served_ledger_cap_idx ON squawk_served_ledger (cap_id, created_at DESC);
CREATE INDEX IF NOT EXISTS squawk_served_ledger_trace_idx ON squawk_served_ledger (trace_id);
