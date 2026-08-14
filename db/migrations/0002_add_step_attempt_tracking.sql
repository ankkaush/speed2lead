-- Per ADR 0009 (Phase 4 reliability design).
-- The status columns alone (from migration 0001) can't drive a retry schedule: they say
-- *what* state a step is in, not *when it was last tried* or *how many times*, which a
-- reconciliation sweep needs to implement backoff and an eventual give-up point.

ALTER TABLE leads
    ADD COLUMN crm_attempts INT NOT NULL DEFAULT 0,
    ADD COLUMN crm_last_attempted_at TIMESTAMPTZ,
    ADD COLUMN notify_attempts INT NOT NULL DEFAULT 0,
    ADD COLUMN notify_last_attempted_at TIMESTAMPTZ,
    ADD COLUMN ack_attempts INT NOT NULL DEFAULT 0,
    ADD COLUMN ack_last_attempted_at TIMESTAMPTZ;
