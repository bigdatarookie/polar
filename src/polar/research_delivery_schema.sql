-- Additive delivery metadata in the existing PostgreSQL database. Scientific
-- runs, attempts, reservations, and schema_version/1 are deliberately untouched.
CREATE TABLE research_delivery_schema_version (
    version integer PRIMARY KEY CHECK (version = 1), checksum text NOT NULL
);
CREATE TABLE research_deliveries (
    id text PRIMARY KEY CHECK (id ~ '^delivery-[0-9a-f]{64}$'),
    kind text NOT NULL CHECK (kind IN ('RESULT','ASSESSMENT')),
    result_id text NOT NULL CHECK (result_id ~ '^research-[0-9a-f]{64}$'),
    payload_hash text NOT NULL CHECK (payload_hash ~ '^[0-9a-f]{64}$'),
    body jsonb NOT NULL CHECK (jsonb_typeof(body) = 'object'),
    body_bytes bigint NOT NULL CHECK (body_bytes > 0),
    state text NOT NULL DEFAULT 'QUEUED'
        CHECK (state IN ('QUEUED','DELIVERING','WAITING_FOR_RESULT','DELIVERED','REJECTED')),
    delivery_attempt_count bigint NOT NULL DEFAULT 0 CHECK (delivery_attempt_count >= 0),
    lease_token uuid, lease_until timestamptz,
    queued_at timestamptz NOT NULL DEFAULT now(),
    started_at timestamptz, last_started_at timestamptz,
    delivered_at timestamptz, finished_at timestamptz,
    updated_at timestamptz NOT NULL DEFAULT now(),
    not_before timestamptz NOT NULL DEFAULT now(),
    receipt jsonb CHECK (receipt IS NULL OR jsonb_typeof(receipt) = 'object'),
    error_code text CHECK (error_code IS NULL OR error_code ~ '^[A-Z][A-Z0-9_]{0,127}$'),
    CHECK (id = 'delivery-' || payload_hash),
    CHECK ((state = 'DELIVERING' AND lease_token IS NOT NULL AND lease_until IS NOT NULL)
        OR (state <> 'DELIVERING' AND lease_token IS NULL AND lease_until IS NULL)),
    CHECK (state <> 'DELIVERED' OR delivered_at IS NOT NULL),
    CHECK (state NOT IN ('DELIVERED','REJECTED') OR finished_at IS NOT NULL)
);
CREATE INDEX research_deliveries_claim ON research_deliveries(state,not_before,queued_at,id);
CREATE OR REPLACE FUNCTION protect_research_delivery() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
  IF TG_OP = 'DELETE' THEN RAISE EXCEPTION 'IMMUTABLE_RESEARCH_DELIVERY'; END IF;
  IF OLD.state IN ('DELIVERED','REJECTED') OR
     NEW.id IS DISTINCT FROM OLD.id OR NEW.kind IS DISTINCT FROM OLD.kind OR
     NEW.result_id IS DISTINCT FROM OLD.result_id OR
     NEW.payload_hash IS DISTINCT FROM OLD.payload_hash OR NEW.body IS DISTINCT FROM OLD.body OR
     NEW.body_bytes IS DISTINCT FROM OLD.body_bytes OR NEW.queued_at IS DISTINCT FROM OLD.queued_at THEN
    RAISE EXCEPTION 'IMMUTABLE_RESEARCH_DELIVERY';
  END IF;
  RETURN NEW;
END;
$$;
CREATE TRIGGER immutable_research_delivery BEFORE UPDATE OR DELETE ON research_deliveries
    FOR EACH ROW EXECUTE FUNCTION protect_research_delivery();
