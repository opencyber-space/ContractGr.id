CREATE EXTENSION IF NOT EXISTS timescaledb CASCADE;
CREATE EXTENSION IF NOT EXISTS pgcrypto;

CREATE TABLE IF NOT EXISTS key_events (
    first_seen_at       TIMESTAMPTZ     NOT NULL DEFAULT NOW(),
    aid                 TEXT            NOT NULL,
    sn                  BIGINT          NOT NULL,
    said                TEXT            NOT NULL,
    ilk                 TEXT            NOT NULL,
    raw_event           BYTEA           NOT NULL,
    prior_said          TEXT,
    receipted           BOOLEAN         NOT NULL DEFAULT FALSE,
    receipt_sig         TEXT,
    PRIMARY KEY (aid, sn, said)
);

SELECT create_hypertable(
    'key_events',
    'first_seen_at',
    chunk_time_interval => INTERVAL '7 days',
    if_not_exists => TRUE
);

CREATE INDEX IF NOT EXISTS idx_ke_aid_sn
    ON key_events (aid, sn, first_seen_at ASC);

CREATE INDEX IF NOT EXISTS idx_ke_said
    ON key_events (said);

CREATE INDEX IF NOT EXISTS idx_ke_ilk_time
    ON key_events (ilk, first_seen_at DESC);

CREATE INDEX IF NOT EXISTS idx_ke_unreceipted
    ON key_events (receipted, first_seen_at DESC)
    WHERE receipted = FALSE;

ALTER TABLE key_events SET (
    timescaledb.compress,
    timescaledb.compress_orderby = 'first_seen_at DESC',
    timescaledb.compress_segmentby = 'aid'
);

SELECT add_compression_policy('key_events', INTERVAL '30 days', if_not_exists => TRUE);


CREATE TABLE IF NOT EXISTS receipts (
    issued_at           TIMESTAMPTZ     NOT NULL DEFAULT NOW(),
    id                  UUID            NOT NULL DEFAULT gen_random_uuid(),
    aid                 TEXT            NOT NULL,
    sn                  BIGINT          NOT NULL,
    said                TEXT            NOT NULL,
    witness_aid         TEXT            NOT NULL,
    signature_b64       TEXT            NOT NULL,
    ilk                 TEXT            NOT NULL DEFAULT 'rct',
    PRIMARY KEY (aid, sn)
);

SELECT create_hypertable(
    'receipts',
    'issued_at',
    chunk_time_interval => INTERVAL '7 days',
    if_not_exists => TRUE
);

CREATE INDEX IF NOT EXISTS idx_receipts_aid_sn
    ON receipts (aid, sn);

CREATE INDEX IF NOT EXISTS idx_receipts_said
    ON receipts (said);

CREATE INDEX IF NOT EXISTS idx_receipts_witness
    ON receipts (witness_aid, issued_at DESC);


CREATE TABLE IF NOT EXISTS duplicity_log (
    detected_at         TIMESTAMPTZ     NOT NULL DEFAULT NOW(),
    id                  UUID            NOT NULL DEFAULT gen_random_uuid(),
    aid                 TEXT            NOT NULL,
    sn                  BIGINT          NOT NULL,
    first_said          TEXT            NOT NULL,
    conflict_said       TEXT            NOT NULL,
    first_raw           BYTEA,
    conflict_raw        BYTEA,
    source_witness      TEXT,
    resolved            BOOLEAN         NOT NULL DEFAULT FALSE,
    resolved_at         TIMESTAMPTZ,
    notes               TEXT,
    PRIMARY KEY (detected_at, id)
);

SELECT create_hypertable(
    'duplicity_log',
    'detected_at',
    chunk_time_interval => INTERVAL '30 days',
    if_not_exists => TRUE
);

CREATE INDEX IF NOT EXISTS idx_dup_aid
    ON duplicity_log (aid, detected_at DESC);

CREATE INDEX IF NOT EXISTS idx_dup_unresolved
    ON duplicity_log (resolved, detected_at DESC)
    WHERE resolved = FALSE;


CREATE TABLE IF NOT EXISTS escrow_events (
    received_at         TIMESTAMPTZ     NOT NULL DEFAULT NOW(),
    id                  UUID            NOT NULL DEFAULT gen_random_uuid(),
    aid                 TEXT            NOT NULL,
    sn                  BIGINT,
    said                TEXT,
    raw_event           BYTEA           NOT NULL,
    reason              TEXT            NOT NULL,
    retry_count         INTEGER         NOT NULL DEFAULT 0,
    last_retry_at       TIMESTAMPTZ,
    resolved            BOOLEAN         NOT NULL DEFAULT FALSE,
    resolved_at         TIMESTAMPTZ,
    expires_at          TIMESTAMPTZ     NOT NULL DEFAULT NOW() + INTERVAL '7 days',
    PRIMARY KEY (received_at, id)
);

SELECT create_hypertable(
    'escrow_events',
    'received_at',
    chunk_time_interval => INTERVAL '1 day',
    if_not_exists => TRUE
);

CREATE INDEX IF NOT EXISTS idx_escrow_aid
    ON escrow_events (aid, received_at ASC);

CREATE INDEX IF NOT EXISTS idx_escrow_pending
    ON escrow_events (resolved, expires_at)
    WHERE resolved = FALSE;

CREATE INDEX IF NOT EXISTS idx_escrow_said
    ON escrow_events (said)
    WHERE said IS NOT NULL;

SELECT add_retention_policy('escrow_events', INTERVAL '30 days', if_not_exists => TRUE);


CREATE TABLE IF NOT EXISTS witness_metrics (
    recorded_at             TIMESTAMPTZ     NOT NULL DEFAULT NOW(),
    events_received         BIGINT          NOT NULL DEFAULT 0,
    events_processed        BIGINT          NOT NULL DEFAULT 0,
    events_rejected         BIGINT          NOT NULL DEFAULT 0,
    receipts_issued         BIGINT          NOT NULL DEFAULT 0,
    duplicity_count         BIGINT          NOT NULL DEFAULT 0,
    escrow_count            BIGINT          NOT NULL DEFAULT 0,
    watcher_push_success    BIGINT          NOT NULL DEFAULT 0,
    watcher_push_errors     BIGINT          NOT NULL DEFAULT 0
);

SELECT create_hypertable(
    'witness_metrics',
    'recorded_at',
    chunk_time_interval => INTERVAL '1 day',
    if_not_exists => TRUE
);

SELECT add_retention_policy('witness_metrics', INTERVAL '90 days', if_not_exists => TRUE);


CREATE TABLE IF NOT EXISTS watcher_registry (
    url                 TEXT            NOT NULL,
    registered_at       TIMESTAMPTZ     NOT NULL DEFAULT NOW(),
    last_push_at        TIMESTAMPTZ,
    last_error_at       TIMESTAMPTZ,
    consecutive_errors  INTEGER         NOT NULL DEFAULT 0,
    enabled             BOOLEAN         NOT NULL DEFAULT TRUE,
    PRIMARY KEY (url)
);


CREATE MATERIALIZED VIEW IF NOT EXISTS receipt_throughput
WITH (timescaledb.continuous) AS
SELECT
    time_bucket('5 minutes', issued_at) AS bucket,
    ilk,
    COUNT(*) AS receipt_count
FROM receipts
GROUP BY bucket, ilk
WITH NO DATA;

SELECT add_continuous_aggregate_policy(
    'receipt_throughput',
    start_offset => INTERVAL '1 day',
    end_offset   => INTERVAL '5 minutes',
    schedule_interval => INTERVAL '5 minutes',
    if_not_exists => TRUE
);


CREATE MATERIALIZED VIEW IF NOT EXISTS duplicity_summary
WITH (timescaledb.continuous) AS
SELECT
    time_bucket('1 hour', detected_at) AS bucket,
    COUNT(*) AS total_duplicity,
    COUNT(DISTINCT aid) AS affected_aids
FROM duplicity_log
GROUP BY bucket
WITH NO DATA;

SELECT add_continuous_aggregate_policy(
    'duplicity_summary',
    start_offset => INTERVAL '7 days',
    end_offset   => INTERVAL '1 hour',
    schedule_interval => INTERVAL '1 hour',
    if_not_exists => TRUE
);


CREATE MATERIALIZED VIEW IF NOT EXISTS event_throughput
WITH (timescaledb.continuous) AS
SELECT
    time_bucket('5 minutes', first_seen_at) AS bucket,
    ilk,
    COUNT(*) AS event_count,
    COUNT(*) FILTER (WHERE receipted = TRUE) AS receipted_count
FROM key_events
GROUP BY bucket, ilk
WITH NO DATA;

SELECT add_continuous_aggregate_policy(
    'event_throughput',
    start_offset => INTERVAL '1 day',
    end_offset   => INTERVAL '5 minutes',
    schedule_interval => INTERVAL '5 minutes',
    if_not_exists => TRUE
);