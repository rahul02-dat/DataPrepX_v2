-- Phase 1: full data/job model per CLAUDE.md §6.
-- Extends 0001_init (datasets, runs) rather than replacing it.

-- datasets: extend 0001_init if columns are missing (idempotent-ish via IF NOT EXISTS)
ALTER TABLE datasets ADD COLUMN IF NOT EXISTS storage_uri TEXT;
ALTER TABLE datasets ADD COLUMN IF NOT EXISTS size_bytes BIGINT;
ALTER TABLE datasets ADD COLUMN IF NOT EXISTS original_filename TEXT;

-- content_hash must be unique so re-uploading an identical file resolves to
-- the same dataset row rather than duplicating it (content-addressed, per
-- the lineage philosophy in CLAUDE.md §5.3).
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint WHERE conname = 'datasets_content_hash_key'
    ) THEN
        ALTER TABLE datasets ADD CONSTRAINT datasets_content_hash_key UNIQUE (content_hash);
    END IF;
END $$;

-- runs: extend 0001_init with the fields CLAUDE.md §6 requires
ALTER TABLE runs ADD COLUMN IF NOT EXISTS config_hash TEXT;
ALTER TABLE runs ADD COLUMN IF NOT EXISTS git_sha TEXT;
ALTER TABLE runs ADD COLUMN IF NOT EXISTS status TEXT NOT NULL DEFAULT 'queued';
ALTER TABLE runs ADD COLUMN IF NOT EXISTS created_at TIMESTAMPTZ NOT NULL DEFAULT now();
ALTER TABLE runs ADD COLUMN IF NOT EXISTS started_at TIMESTAMPTZ;
ALTER TABLE runs ADD COLUMN IF NOT EXISTS finished_at TIMESTAMPTZ;

CREATE TABLE IF NOT EXISTS pipeline_steps (
    id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    run_id      UUID NOT NULL REFERENCES runs(id) ON DELETE CASCADE,
    step_type   TEXT NOT NULL,
    input_hash  TEXT NOT NULL,
    output_hash TEXT,
    params_json JSONB NOT NULL DEFAULT '{}'::jsonb,
    seed        BIGINT,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS transformations (
    id                  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    step_id             UUID NOT NULL REFERENCES pipeline_steps(id) ON DELETE CASCADE,
    transform_code_hash TEXT NOT NULL,
    description         TEXT,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS hyperparameters (
    id            UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    run_id        UUID NOT NULL REFERENCES runs(id) ON DELETE CASCADE,
    model_family  TEXT NOT NULL,
    trial_number  INT NOT NULL,
    params_json   JSONB NOT NULL DEFAULT '{}'::jsonb,
    score         DOUBLE PRECISION,
    created_at    TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS metrics (
    id         UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    run_id     UUID NOT NULL REFERENCES runs(id) ON DELETE CASCADE,
    name       TEXT NOT NULL,
    value      DOUBLE PRECISION NOT NULL,
    ci_low     DOUBLE PRECISION,
    ci_high    DOUBLE PRECISION,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS artifacts (
    id           UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    run_id       UUID NOT NULL REFERENCES runs(id) ON DELETE CASCADE,
    kind         TEXT NOT NULL,
    storage_uri  TEXT NOT NULL,
    content_hash TEXT NOT NULL,
    created_at   TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS audit_log (
    id         UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    run_id     UUID REFERENCES runs(id) ON DELETE SET NULL,
    actor      TEXT NOT NULL,
    action     TEXT NOT NULL,
    timestamp  TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_pipeline_steps_run_id ON pipeline_steps(run_id);
CREATE INDEX IF NOT EXISTS idx_hyperparameters_run_id ON hyperparameters(run_id);
CREATE INDEX IF NOT EXISTS idx_metrics_run_id ON metrics(run_id);
CREATE INDEX IF NOT EXISTS idx_artifacts_run_id ON artifacts(run_id);
CREATE INDEX IF NOT EXISTS idx_audit_log_run_id ON audit_log(run_id);