-- Schema
CREATE SCHEMA IF NOT EXISTS epson;

-- Table
CREATE TABLE IF NOT EXISTS sassie.products_informations (
  id              BIGSERIAL PRIMARY KEY,
  model VARCHAR,
  agent_id        TEXT,
  agent_name      TEXT        NOT NULL DEFAULT 'Agentic',
  status          TEXT        NOT NULL DEFAULT 'success',
  data            TEXT,                     -- free-form text/JSON-as-string
  output          JSONB,                    -- structured output
  attributes      JSONB       NOT NULL DEFAULT '{}'::jsonb,
  created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  transcript      TEXT,
  script_path     TEXT,
  podcast_path    TEXT,
  pdf_path        TEXT,
  document_path   TEXT,
  files           JSONB       NOT NULL DEFAULT '[]'::jsonb,  -- list of generated files
  CONSTRAINT unq_sassie_products_model UNIQUE (model, agent_id)
);

-- Optional: helpful indexes (drop if you don't need them)
CREATE INDEX IF NOT EXISTS sassie_products_informations_created_at_idx
  ON sassie.products_informations (created_at);

-- GIN indexes for JSONB lookups
CREATE INDEX IF NOT EXISTS sassie_products_informations_attributes_gin
  ON sassie.products_informations USING GIN (attributes);

CREATE INDEX IF NOT EXISTS sassie_products_informations_output_gin
  ON sassie.products_informations USING GIN (output);

CREATE INDEX IF NOT EXISTS sassie_products_informations_files_gin
  ON sassie.products_informations USING GIN (files);

-- Optional: documentation
COMMENT ON TABLE  sassie.products_informations IS
  'Responses produced by Epson agents (free-form data + structured output).';
COMMENT ON COLUMN sassie.products_informations.agent_id      IS 'Unique identifier for the agent that processed the request';
COMMENT ON COLUMN sassie.products_informations.agent_name    IS 'Name of the agent that processed the request';
COMMENT ON COLUMN sassie.products_informations.status        IS 'Status of the response';
COMMENT ON COLUMN sassie.products_informations.data          IS 'Data returned by the agent (text/JSON as string)';
COMMENT ON COLUMN sassie.products_informations.output        IS 'Structured output of the agent (JSONB)';
COMMENT ON COLUMN sassie.products_informations.attributes    IS 'Attributes associated with the response (JSONB)';
COMMENT ON COLUMN sassie.products_informations.created_at    IS 'Timestamp when response was created';
COMMENT ON COLUMN sassie.products_informations.transcript    IS 'Transcript of the conversation';
COMMENT ON COLUMN sassie.products_informations.script_path   IS 'Path to conversational script';
COMMENT ON COLUMN sassie.products_informations.podcast_path  IS 'Path to generated podcast';
COMMENT ON COLUMN sassie.products_informations.pdf_path      IS 'Path to generated PDF';
COMMENT ON COLUMN sassie.products_informations.document_path IS 'Path to any other generated document';
COMMENT ON COLUMN sassie.products_informations.files         IS 'Complete list of generated files (JSON array)';
