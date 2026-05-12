CREATE EXTENSION IF NOT EXISTS timescaledb CASCADE;
CREATE EXTENSION IF NOT EXISTS pgcrypto;

CREATE TABLE IF NOT EXISTS watched_aids (
    aid                 TEXT            NOT NULL,
    registered_at       TIMESTAMPTZ     NOT NULL DEFAULT NOW(),
    witnesses           TEXT[]          NOT NULL DEFAULT '{}',
    witness_oobis       JSONB           NOT NULL DEFAULT '{}',
    last_polled_at      TIMESTAMPTZ,
    last_sn             BIGINT          NOT NULL DEFAULT -1,
    enabled             BOOLEAN         NOT NULL DEFAULT TRUE,
    metadata            JSONB           NOT NULL DEFAULT '{}',
    updated_at          TIMESTAMPTZ     NOT NULL DEFAULT NOW(),
    PRIMARY KEY (aid)
);

CREATE INDEX IF NOT EXISTS idx_watched_aids_enabled
    ON watched_aids (enabled)
    WHERE enabled = TRUE;

CREATE INDEX IF NOT EXISTS idx_watched_aids_last_polled
    ON watched_aids (last_polled_at ASC NULLS FIRST)
    WHERE enabled = TRUE;


CREATE TABLE IF NOT EXISTS first_seen_events (
    first_seen_at       TIMESTAMPTZ     NOT NULL,
    aid                 TEXT            NOT NULL,
    sn                  BIGINT          NOT NULL,
    said                TEXT            NOT NULL,
    ilk                 TEXT            NOT NULL,
    raw_event           BYTEA,
    source_witness      TEXT,
    prior_said          TEXT,
    digest_algo         TEXT            NOT NULL DEFAULT 'blake3-256',
    PRIMARY KEY (aid, sn, said)
);

SELECT create_hypertable(
    'first_seen_events',
    'first_seen_at',
    chunk_time_interval => INTERVAL '7 days',
    if_not_exists => TRUE
);

CREATE INDEX IF NOT EXISTS idx_fse_aid_sn
    ON first_seen_events (aid, sn, first_seen_at DESC);

CREATE INDEX IF NOT EXISTS idx_fse_said
    ON first_seen_events (said);

CREATE INDEX IF NOT EXISTS idx_fse_ilk
    ON first_seen_events (ilk, first_seen_at DESC);


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
    ON escrow_events (aid, received_at DESC);

CREATE INDEX IF NOT EXISTS idx_escrow_pending
    ON escrow_events (resolved, expires_at)
    WHERE resolved = FALSE;

CREATE INDEX IF NOT EXISTS idx_escrow_said
    ON escrow_events (said)
    WHERE said IS NOT NULL;


CREATE TABLE IF NOT EXISTS watcher_metrics (
    recorded_at             TIMESTAMPTZ     NOT NULL DEFAULT NOW(),
    events_received         BIGINT          NOT NULL DEFAULT 0,
    events_processed        BIGINT          NOT NULL DEFAULT 0,
    events_rejected         BIGINT          NOT NULL DEFAULT 0,
    duplicity_count         BIGINT          NOT NULL DEFAULT 0,
    escrow_count            BIGINT          NOT NULL DEFAULT 0,
    watched_aid_count       BIGINT          NOT NULL DEFAULT 0,
    poll_success_count      BIGINT          NOT NULL DEFAULT 0,
    poll_error_count        BIGINT          NOT NULL DEFAULT 0
);

SELECT create_hypertable(
    'watcher_metrics',
    'recorded_at',
    chunk_time_interval => INTERVAL '1 day',
    if_not_exists => TRUE
);


CREATE TABLE IF NOT EXISTS witness_registry (
    witness_aid         TEXT            NOT NULL,
    oobi                TEXT            NOT NULL,
    first_seen_at       TIMESTAMPTZ     NOT NULL DEFAULT NOW(),
    last_successful_at  TIMESTAMPTZ,
    last_error_at       TIMESTAMPTZ,
    consecutive_errors  INTEGER         NOT NULL DEFAULT 0,
    enabled             BOOLEAN         NOT NULL DEFAULT TRUE,
    PRIMARY KEY (witness_aid)
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
    COUNT(*) AS event_count
FROM first_seen_events
GROUP BY bucket, ilk
WITH NO DATA;

SELECT add_continuous_aggregate_policy(
    'event_throughput',
    start_offset => INTERVAL '1 day',
    end_offset   => INTERVAL '5 minutes',
    schedule_interval => INTERVAL '5 minutes',
    if_not_exists => TRUE
);


SELECT add_retention_policy(
    'watcher_metrics',
    INTERVAL '90 days',
    if_not_exists => TRUE
);

SELECT add_retention_policy(
    'escrow_events',
    INTERVAL '30 days',
    if_not_exists => TRUE
);

SELECT add_compression_policy(
    'first_seen_events',
    INTERVAL '30 days',
    if_not_exists => TRUE
);

ALTER TABLE first_seen_events SET (
    timescaledb.compress,
    timescaledb.compress_orderby = 'first_seen_at DESC',
    timescaledb.compress_segmentby = 'aid'
);