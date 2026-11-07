-- Separate additive extension. Never modify legacy schema_version or schema.sql.
CREATE TABLE IF NOT EXISTS history_schema_version (
    version integer PRIMARY KEY CHECK (version = 1), checksum text NOT NULL
);
CREATE TABLE IF NOT EXISTS history_revisions (
    dataset_id text NOT NULL, revision text PRIMARY KEY,
    catalog_sequence bigint GENERATED ALWAYS AS IDENTITY UNIQUE,
    primary_import_receipt_id text NOT NULL, manifest_hash text NOT NULL,
    publication_hash text NOT NULL, summary jsonb NOT NULL,
    registered_at timestamptz NOT NULL DEFAULT now()
);
CREATE TABLE IF NOT EXISTS history_receipts (
    revision text NOT NULL REFERENCES history_revisions(revision),
    receipt_id text NOT NULL, manifest_hash text NOT NULL,
    publication_hash text NOT NULL, registered_at timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (revision, receipt_id)
);
CREATE OR REPLACE FUNCTION history_protect_immutable() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN RAISE EXCEPTION 'IMMUTABLE_HISTORY'; END;
$$;
CREATE TRIGGER history_revision_immutable BEFORE UPDATE OR DELETE ON history_revisions
    FOR EACH ROW EXECUTE FUNCTION history_protect_immutable();
CREATE TRIGGER history_receipt_immutable BEFORE UPDATE OR DELETE ON history_receipts
    FOR EACH ROW EXECUTE FUNCTION history_protect_immutable();
