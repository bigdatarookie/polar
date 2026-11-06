-- Apply only through `polar migrate` under an advisory transaction lock.
CREATE TABLE IF NOT EXISTS schema_version (version integer PRIMARY KEY CHECK (version = 1), checksum text NOT NULL);
CREATE TABLE IF NOT EXISTS datasets (
    id text PRIMARY KEY, content_hash text UNIQUE NOT NULL, body jsonb NOT NULL,
    source_hash text NOT NULL, source_bytes bytea NOT NULL,
    registered_at timestamptz NOT NULL DEFAULT now()
);
CREATE TABLE IF NOT EXISTS runs (
    id uuid PRIMARY KEY, idempotency_key text UNIQUE NOT NULL, payload_hash text NOT NULL,
    config jsonb NOT NULL, dataset_id text NOT NULL REFERENCES datasets(id),
    state text NOT NULL CHECK (state IN ('queued','running','completed','failed','canceled')),
    created_at timestamptz NOT NULL DEFAULT now(), updated_at timestamptz NOT NULL DEFAULT now(),
    attempt integer NOT NULL DEFAULT 0 CHECK (attempt BETWEEN 0 AND 2),
    attempt_id uuid, lease_until timestamptz, cancel_requested boolean NOT NULL DEFAULT false,
    artifact_ref text, artifact_hash text, error_code text,
    CHECK (state <> 'completed' OR (artifact_ref IS NOT NULL AND artifact_hash IS NOT NULL))
);
CREATE TABLE IF NOT EXISTS attempts (
    id uuid PRIMARY KEY, run_id uuid NOT NULL REFERENCES runs(id), number integer NOT NULL,
    state text NOT NULL, started_at timestamptz NOT NULL DEFAULT now(), finished_at timestamptz,
    cpu_seconds double precision NOT NULL DEFAULT 0, error_code text,
    UNIQUE(run_id, number)
);
CREATE INDEX IF NOT EXISTS runs_state_created ON runs(state, created_at);
CREATE OR REPLACE FUNCTION protect_dataset() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN RAISE EXCEPTION 'IMMUTABLE_DATASET'; END;
$$;
DROP TRIGGER IF EXISTS immutable_dataset ON datasets;
CREATE TRIGGER immutable_dataset BEFORE UPDATE OR DELETE ON datasets FOR EACH ROW EXECUTE FUNCTION protect_dataset();
CREATE OR REPLACE FUNCTION protect_run() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
  IF TG_OP = 'DELETE' THEN RAISE EXCEPTION 'IMMUTABLE_RUN'; END IF;
  IF OLD.state IN ('completed','failed','canceled') OR
     NEW.config IS DISTINCT FROM OLD.config OR NEW.dataset_id <> OLD.dataset_id OR
     NEW.payload_hash <> OLD.payload_hash OR NEW.idempotency_key <> OLD.idempotency_key THEN
    RAISE EXCEPTION 'IMMUTABLE_RUN';
  END IF;
  RETURN NEW;
END;
$$;
DROP TRIGGER IF EXISTS immutable_run ON runs;
CREATE TRIGGER immutable_run BEFORE UPDATE OR DELETE ON runs FOR EACH ROW EXECUTE FUNCTION protect_run();
