DROP TABLE IF EXISTS troc.nextstop_responses;
CREATE TABLE IF NOT EXISTS troc.nextstop_responses (
  user_id        varchar         NOT NULL,
  agent_name     varchar         NOT NULL,
  kind varchar NOT NULL,
  content        varchar NOT NULL,
  program_slug   varchar         NOT NULL,
  data           TEXT         NOT NULL DEFAULT '',
  request_date   DATE         NOT NULL DEFAULT CURRENT_DATE,
  output         TEXT         NOT NULL DEFAULT '',
  podcast_path   TEXT,
  pdf_path       TEXT,
  image_path     TEXT,
  documents      jsonb,
  attributes     jsonb,
  created_at     TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW(),
  PRIMARY KEY (user_id, agent_name, program_slug, kind, request_date)
);


select * from troc.nextstop_responses;
