-- Per ADR 0007 (leads data model) and ADR 0008 (idempotency strategy).
-- Applied to the project's Supabase database via the Supabase migration tool;
-- this file is the checked-in record of that schema, kept in sync by hand for now
-- (no migration runner yet — a single-table schema doesn't justify one; revisit if
-- the schema starts changing often).

CREATE TYPE step_status AS ENUM ('pending', 'success', 'failed');

CREATE TABLE leads (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),

    -- Idempotency (ADR 0008): enforced at the DB layer via UNIQUE, not app-level check-then-insert
    idempotency_key TEXT NOT NULL UNIQUE,
    idempotency_source TEXT NOT NULL CHECK (idempotency_source IN ('client', 'derived')),

    -- Lead content (PII — see ADR 0007, ADR 0002 secrets/PII policy)
    name TEXT NOT NULL,
    email TEXT NOT NULL,
    phone TEXT,
    message TEXT NOT NULL,
    source TEXT,

    received_at TIMESTAMPTZ NOT NULL DEFAULT now(),

    -- Per-step reliability status (ADR 0007): visible, recoverable partial failure without a queue
    crm_status step_status NOT NULL DEFAULT 'pending',
    crm_external_id TEXT,
    crm_error TEXT,

    notify_status step_status NOT NULL DEFAULT 'pending',
    notify_error TEXT,

    ack_status step_status NOT NULL DEFAULT 'pending',
    ack_error TEXT,

    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX idx_leads_email ON leads (email);

CREATE OR REPLACE FUNCTION set_updated_at()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = now();
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER leads_set_updated_at
    BEFORE UPDATE ON leads
    FOR EACH ROW
    EXECUTE FUNCTION set_updated_at();

-- Only ever accessed via a direct DB connection from the FastAPI app (never through
-- Supabase's PostgREST/anon key), so RLS is enabled with no policies: deny-by-default
-- for any anon/authenticated-role access, while the app's direct Postgres role is
-- unaffected.
ALTER TABLE leads ENABLE ROW LEVEL SECURITY;
