# Operator runbook

Answers to "how's the pipeline doing" via direct SQL against the Supabase project — no
dashboard tool, because the database already holds everything needed (ADR 0011). Run
these via the Supabase SQL editor or any Postgres client connected to `DATABASE_URL`.

These queries return lead names/emails/messages where noted — that's expected for an
operator with direct database access (the same trust boundary the rest of this project's
PII policy is built around: PII stays out of logs and third-party tools, not out of the
database itself).

## How many leads came in today?

```sql
SELECT count(*) FROM leads WHERE received_at >= date_trunc('day', now());
```

## Leads per day, last 7 days

```sql
SELECT date_trunc('day', received_at) AS day, count(*)
FROM leads
WHERE received_at >= now() - interval '7 days'
GROUP BY 1
ORDER BY 1 DESC;
```

## Failure rate per step, last 24 hours

```sql
SELECT
    count(*) FILTER (WHERE crm_status = 'success') AS crm_success,
    count(*) FILTER (WHERE crm_status = 'failed') AS crm_failed,
    count(*) FILTER (WHERE notify_status = 'success') AS notify_success,
    count(*) FILTER (WHERE notify_status = 'failed') AS notify_failed,
    count(*) FILTER (WHERE ack_status = 'success') AS ack_success,
    count(*) FILTER (WHERE ack_status = 'failed') AS ack_failed
FROM leads
WHERE received_at >= now() - interval '24 hours';
```

## Leads that need a human to look at them (any step permanently failed)

Each permanent failure already triggers a Sentry event (ADR 0011) at the moment it
happens; this query is for catching up after the fact, or auditing all currently-failed
leads at once.

```sql
SELECT id, name, email, received_at,
       crm_status, crm_error,
       notify_status, notify_error,
       ack_status, ack_error
FROM leads
WHERE crm_status = 'failed' OR notify_status = 'failed' OR ack_status = 'failed'
ORDER BY received_at DESC;
```

## Leads still in flight (retrying, not yet given up)

```sql
SELECT id, received_at, crm_status, crm_attempts, notify_status, notify_attempts,
       ack_status, ack_attempts
FROM leads
WHERE crm_status = 'pending' OR notify_status = 'pending' OR ack_status = 'pending'
ORDER BY received_at DESC;
```

## A specific lead's full history, given a correlation ID

Every request now carries a correlation ID (`X-Request-ID` response header, and in every
structured log line for that request — ADR 0011). To find the lead a specific request
created, search the app's logs (wherever they're shipped once deployed) for that
correlation ID to find the `lead_intake` line, which includes the `lead_id`, then:

```sql
SELECT * FROM leads WHERE id = '<lead_id>';
```
