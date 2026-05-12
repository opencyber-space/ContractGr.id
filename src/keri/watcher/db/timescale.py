from __future__ import annotations

import asyncio
import time
from contextlib import asynccontextmanager
from typing import Any, AsyncIterator, Dict, List, Optional, Sequence

import asyncpg

from keri_watcher.config import TimescaleConfig
from keri_watcher.utils.errors import DBError
from keri_watcher.utils.logging import get_logger
from keri_watcher.utils import metrics as m

log = get_logger(__name__)


class TimescaleRepository:
    def __init__(self, config: TimescaleConfig) -> None:
        self._config = config
        self._pool: Optional[asyncpg.Pool] = None

    async def connect(self) -> None:
        for attempt in range(1, 6):
            try:
                self._pool = await asyncpg.create_pool(
                    dsn=self._config.dsn,
                    min_size=self._config.min_pool,
                    max_size=self._config.max_pool,
                    command_timeout=self._config.command_timeout,
                    server_settings={
                        "application_name": "keri-watcher",
                        "jit": "off",
                    },
                )
                log.info_kw("TimescaleDB pool established", min=self._config.min_pool, max=self._config.max_pool)
                return
            except Exception as exc:
                delay = 2 ** (attempt - 1)
                log.warning_kw("DB connect failed, retrying", attempt=attempt, delay=delay, error=str(exc))
                await asyncio.sleep(delay)
        raise DBError("Failed to connect to TimescaleDB after 5 attempts")

    async def close(self) -> None:
        if self._pool:
            await self._pool.close()
            self._pool = None

    @asynccontextmanager
    async def _conn(self) -> AsyncIterator[asyncpg.Connection]:
        if not self._pool:
            raise DBError("Database pool is not initialized")
        async with self._pool.acquire() as conn:
            yield conn

    @asynccontextmanager
    async def _tx(self) -> AsyncIterator[asyncpg.Connection]:
        async with self._conn() as conn:
            async with conn.transaction():
                yield conn

    async def _timed_execute(self, op: str, conn: asyncpg.Connection, query: str, *args: Any) -> str:
        start = time.monotonic()
        try:
            result = await conn.execute(query, *args)
            m.DB_WRITE_DURATION.labels(operation=op).observe(time.monotonic() - start)
            return result
        except Exception as exc:
            m.DB_ERRORS.labels(operation=op).inc()
            raise DBError(f"DB {op} failed: {exc}") from exc

    async def _timed_fetch(self, op: str, conn: asyncpg.Connection, query: str, *args: Any) -> List[asyncpg.Record]:
        start = time.monotonic()
        try:
            result = await conn.fetch(query, *args)
            m.DB_WRITE_DURATION.labels(operation=op).observe(time.monotonic() - start)
            return result
        except Exception as exc:
            m.DB_ERRORS.labels(operation=op).inc()
            raise DBError(f"DB {op} failed: {exc}") from exc

    async def _timed_fetchrow(self, op: str, conn: asyncpg.Connection, query: str, *args: Any) -> Optional[asyncpg.Record]:
        start = time.monotonic()
        try:
            result = await conn.fetchrow(query, *args)
            m.DB_WRITE_DURATION.labels(operation=op).observe(time.monotonic() - start)
            return result
        except Exception as exc:
            m.DB_ERRORS.labels(operation=op).inc()
            raise DBError(f"DB {op} failed: {exc}") from exc

    async def add_watched_aid(
        self,
        aid: str,
        witnesses: List[str],
        witness_oobis: Dict[str, str],
        metadata: Optional[Dict[str, Any]] = None,
    ) -> None:
        import json
        async with self._tx() as conn:
            await self._timed_execute(
                "add_watched_aid", conn,
                """
                INSERT INTO watched_aids (aid, witnesses, witness_oobis, metadata)
                VALUES ($1, $2, $3, $4)
                ON CONFLICT (aid) DO UPDATE
                    SET witnesses = EXCLUDED.witnesses,
                        witness_oobis = EXCLUDED.witness_oobis,
                        metadata = EXCLUDED.metadata,
                        enabled = TRUE,
                        updated_at = NOW()
                """,
                aid,
                witnesses,
                json.dumps(witness_oobis),
                json.dumps(metadata or {}),
            )

    async def remove_watched_aid(self, aid: str) -> None:
        async with self._conn() as conn:
            await self._timed_execute(
                "remove_watched_aid", conn,
                "UPDATE watched_aids SET enabled = FALSE, updated_at = NOW() WHERE aid = $1",
                aid,
            )

    async def get_watched_aid(self, aid: str) -> Optional[asyncpg.Record]:
        async with self._conn() as conn:
            return await self._timed_fetchrow(
                "get_watched_aid", conn,
                "SELECT * FROM watched_aids WHERE aid = $1 AND enabled = TRUE",
                aid,
            )

    async def list_watched_aids(self, limit: int = 1000, offset: int = 0) -> List[asyncpg.Record]:
        async with self._conn() as conn:
            return await self._timed_fetch(
                "list_watched_aids", conn,
                "SELECT * FROM watched_aids WHERE enabled = TRUE ORDER BY registered_at DESC LIMIT $1 OFFSET $2",
                limit, offset,
            )

    async def get_aids_due_for_polling(self, poll_interval_seconds: int, limit: int = 100) -> List[asyncpg.Record]:
        async with self._conn() as conn:
            return await self._timed_fetch(
                "get_aids_due_for_polling", conn,
                """
                SELECT * FROM watched_aids
                WHERE enabled = TRUE
                  AND (
                    last_polled_at IS NULL
                    OR last_polled_at < NOW() - ($1 || ' seconds')::INTERVAL
                  )
                ORDER BY last_polled_at ASC NULLS FIRST
                LIMIT $2
                FOR UPDATE SKIP LOCKED
                """,
                str(poll_interval_seconds), limit,
            )

    async def update_poll_timestamp(self, aid: str, last_sn: int) -> None:
        async with self._conn() as conn:
            await self._timed_execute(
                "update_poll_timestamp", conn,
                """
                UPDATE watched_aids
                SET last_polled_at = NOW(),
                    last_sn = GREATEST(last_sn, $2),
                    updated_at = NOW()
                WHERE aid = $1
                """,
                aid, last_sn,
            )

    async def update_witnesses(
        self,
        aid: str,
        witnesses: List[str],
        witness_oobis: Dict[str, str],
    ) -> None:
        import json
        async with self._conn() as conn:
            await self._timed_execute(
                "update_witnesses", conn,
                """
                UPDATE watched_aids
                SET witnesses = $2, witness_oobis = $3, updated_at = NOW()
                WHERE aid = $1
                """,
                aid, witnesses, json.dumps(witness_oobis),
            )

    async def record_first_seen(
        self,
        aid: str,
        sn: int,
        said: str,
        ilk: str,
        raw_event: Optional[bytes],
        source_witness: Optional[str] = None,
        prior_said: Optional[str] = None,
        digest_algo: str = "blake3-256",
    ) -> bool:
        async with self._conn() as conn:
            result = await self._timed_execute(
                "record_first_seen", conn,
                """
                INSERT INTO first_seen_events
                    (first_seen_at, aid, sn, said, ilk, raw_event, source_witness, prior_said, digest_algo)
                VALUES (NOW(), $1, $2, $3, $4, $5, $6, $7, $8)
                ON CONFLICT (aid, sn, said) DO NOTHING
                """,
                aid, sn, said, ilk, raw_event, source_witness, prior_said, digest_algo,
            )
            return result.endswith("1")

    async def get_first_seen_said(self, aid: str, sn: int) -> Optional[str]:
        async with self._conn() as conn:
            row = await self._timed_fetchrow(
                "get_first_seen_said", conn,
                """
                SELECT said FROM first_seen_events
                WHERE aid = $1 AND sn = $2
                ORDER BY first_seen_at ASC
                LIMIT 1
                """,
                aid, sn,
            )
            return row["said"] if row else None

    async def get_kel(self, aid: str, from_sn: int = 0, limit: int = 1000) -> List[asyncpg.Record]:
        async with self._conn() as conn:
            return await self._timed_fetch(
                "get_kel", conn,
                """
                SELECT sn, said, ilk, raw_event, first_seen_at, source_witness, prior_said
                FROM first_seen_events
                WHERE aid = $1 AND sn >= $2
                ORDER BY sn ASC
                LIMIT $3
                """,
                aid, from_sn, limit,
            )

    async def get_latest_event(self, aid: str) -> Optional[asyncpg.Record]:
        async with self._conn() as conn:
            return await self._timed_fetchrow(
                "get_latest_event", conn,
                """
                SELECT sn, said, ilk, first_seen_at
                FROM first_seen_events
                WHERE aid = $1
                ORDER BY sn DESC
                LIMIT 1
                """,
                aid,
            )

    async def record_duplicity(
        self,
        aid: str,
        sn: int,
        first_said: str,
        conflict_said: str,
        first_raw: Optional[bytes] = None,
        conflict_raw: Optional[bytes] = None,
        source_witness: Optional[str] = None,
    ) -> str:
        async with self._conn() as conn:
            row = await self._timed_fetchrow(
                "record_duplicity", conn,
                """
                INSERT INTO duplicity_log
                    (aid, sn, first_said, conflict_said, first_raw, conflict_raw, source_witness)
                VALUES ($1, $2, $3, $4, $5, $6, $7)
                RETURNING id::text
                """,
                aid, sn, first_said, conflict_said, first_raw, conflict_raw, source_witness,
            )
            return row["id"]

    async def list_duplicity(
        self,
        aid: Optional[str] = None,
        resolved: Optional[bool] = None,
        limit: int = 100,
        offset: int = 0,
    ) -> List[asyncpg.Record]:
        conditions = ["1=1"]
        params: list = []
        i = 1
        if aid is not None:
            conditions.append(f"aid = ${i}")
            params.append(aid)
            i += 1
        if resolved is not None:
            conditions.append(f"resolved = ${i}")
            params.append(resolved)
            i += 1
        params.extend([limit, offset])
        query = f"""
            SELECT id::text, detected_at, aid, sn, first_said, conflict_said, source_witness, resolved, resolved_at
            FROM duplicity_log
            WHERE {" AND ".join(conditions)}
            ORDER BY detected_at DESC
            LIMIT ${i} OFFSET ${i+1}
        """
        async with self._conn() as conn:
            return await self._timed_fetch("list_duplicity", conn, query, *params)

    async def resolve_duplicity(self, duplicity_id: str, notes: Optional[str] = None) -> bool:
        async with self._conn() as conn:
            result = await self._timed_execute(
                "resolve_duplicity", conn,
                """
                UPDATE duplicity_log
                SET resolved = TRUE, resolved_at = NOW(), notes = $2
                WHERE id = $1::uuid AND resolved = FALSE
                """,
                duplicity_id, notes,
            )
            return result.endswith("1")

    async def escrow_event(
        self,
        aid: str,
        raw_event: bytes,
        reason: str,
        sn: Optional[int] = None,
        said: Optional[str] = None,
    ) -> None:
        async with self._conn() as conn:
            await self._timed_execute(
                "escrow_event", conn,
                """
                INSERT INTO escrow_events (aid, sn, said, raw_event, reason)
                VALUES ($1, $2, $3, $4, $5)
                ON CONFLICT DO NOTHING
                """,
                aid, sn, said, raw_event, reason,
            )

    async def get_pending_escrow(self, aid: Optional[str] = None, limit: int = 50) -> List[asyncpg.Record]:
        if aid:
            query = """
                SELECT id::text, received_at, aid, sn, said, raw_event, reason, retry_count
                FROM escrow_events
                WHERE resolved = FALSE AND expires_at > NOW() AND aid = $1
                ORDER BY received_at ASC LIMIT $2
            """
            params = [aid, limit]
        else:
            query = """
                SELECT id::text, received_at, aid, sn, said, raw_event, reason, retry_count
                FROM escrow_events
                WHERE resolved = FALSE AND expires_at > NOW()
                ORDER BY received_at ASC LIMIT $1
            """
            params = [limit]
        async with self._conn() as conn:
            return await self._timed_fetch("get_pending_escrow", conn, query, *params)

    async def resolve_escrow(self, escrow_id: str) -> None:
        async with self._conn() as conn:
            await self._timed_execute(
                "resolve_escrow", conn,
                "UPDATE escrow_events SET resolved = TRUE, resolved_at = NOW() WHERE id = $1::uuid",
                escrow_id,
            )

    async def increment_escrow_retry(self, escrow_id: str) -> None:
        async with self._conn() as conn:
            await self._timed_execute(
                "increment_escrow_retry", conn,
                """
                UPDATE escrow_events
                SET retry_count = retry_count + 1, last_retry_at = NOW()
                WHERE id = $1::uuid
                """,
                escrow_id,
            )

    async def upsert_witness(self, witness_aid: str, oobi: str) -> None:
        async with self._conn() as conn:
            await self._timed_execute(
                "upsert_witness", conn,
                """
                INSERT INTO witness_registry (witness_aid, oobi)
                VALUES ($1, $2)
                ON CONFLICT (witness_aid) DO UPDATE
                    SET oobi = EXCLUDED.oobi, enabled = TRUE
                """,
                witness_aid, oobi,
            )

    async def record_witness_success(self, witness_aid: str) -> None:
        async with self._conn() as conn:
            await self._timed_execute(
                "record_witness_success", conn,
                """
                UPDATE witness_registry
                SET last_successful_at = NOW(), consecutive_errors = 0
                WHERE witness_aid = $1
                """,
                witness_aid,
            )

    async def record_witness_error(self, witness_aid: str) -> int:
        async with self._conn() as conn:
            row = await self._timed_fetchrow(
                "record_witness_error", conn,
                """
                UPDATE witness_registry
                SET last_error_at = NOW(), consecutive_errors = consecutive_errors + 1
                WHERE witness_aid = $1
                RETURNING consecutive_errors
                """,
                witness_aid,
            )
            return row["consecutive_errors"] if row else 0

    async def write_metrics_snapshot(
        self,
        events_received: int,
        events_processed: int,
        events_rejected: int,
        duplicity_count: int,
        escrow_count: int,
        watched_aid_count: int,
        poll_success_count: int,
        poll_error_count: int,
    ) -> None:
        async with self._conn() as conn:
            await self._timed_execute(
                "write_metrics_snapshot", conn,
                """
                INSERT INTO watcher_metrics
                    (events_received, events_processed, events_rejected,
                     duplicity_count, escrow_count, watched_aid_count,
                     poll_success_count, poll_error_count)
                VALUES ($1, $2, $3, $4, $5, $6, $7, $8)
                """,
                events_received, events_processed, events_rejected,
                duplicity_count, escrow_count, watched_aid_count,
                poll_success_count, poll_error_count,
            )

    async def get_throughput_stats(self, hours: int = 24) -> List[asyncpg.Record]:
        async with self._conn() as conn:
            return await self._timed_fetch(
                "get_throughput_stats", conn,
                """
                SELECT bucket, ilk, event_count
                FROM event_throughput
                WHERE bucket > NOW() - ($1 || ' hours')::INTERVAL
                ORDER BY bucket DESC
                """,
                str(hours),
            )

    async def get_duplicity_stats(self, hours: int = 24) -> List[asyncpg.Record]:
        async with self._conn() as conn:
            return await self._timed_fetch(
                "get_duplicity_stats", conn,
                """
                SELECT bucket, total_duplicity, affected_aids
                FROM duplicity_summary
                WHERE bucket > NOW() - ($1 || ' hours')::INTERVAL
                ORDER BY bucket DESC
                """,
                str(hours),
            )

    async def run_migration(self, migration_sql: str) -> None:
        async with self._tx() as conn:
            await conn.execute(migration_sql)

    async def health_check(self) -> Dict[str, Any]:
        try:
            async with self._conn() as conn:
                row = await conn.fetchrow("SELECT NOW() as ts, version() as ver")
                return {"status": "ok", "ts": str(row["ts"]), "version": row["ver"]}
        except Exception as exc:
            return {"status": "error", "error": str(exc)}