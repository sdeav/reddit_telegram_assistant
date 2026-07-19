from __future__ import annotations

import logging
import sqlite3
from datetime import UTC, datetime, timedelta
from pathlib import Path

logger = logging.getLogger(__name__)

LAST_SUCCESSFUL_CHECK_KEY = "last_successful_check_utc"


class Storage:
    def __init__(
        self,
        path: Path | str,
        *,
        retention_hours: int = 48,
        max_processed_ids: int = 5000,
    ) -> None:
        self.path = Path(path)
        self.retention_hours = retention_hours
        self.max_processed_ids = max_processed_ids
        self._conn: sqlite3.Connection | None = None

    def connect(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(self.path)
        self._conn.row_factory = sqlite3.Row
        self.initialize()

    def close(self) -> None:
        if self._conn is not None:
            self._conn.close()
            self._conn = None

    def initialize(self) -> None:
        conn = self._require_conn()
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS processed_posts (
                post_id TEXT PRIMARY KEY,
                processed_at_utc TEXT NOT NULL,
                notification_status TEXT NOT NULL
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS metadata (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS callback_state (
                callback_id TEXT PRIMARY KEY,
                payload TEXT NOT NULL,
                created_at_utc TEXT NOT NULL
            )
            """
        )
        conn.commit()

    def has_processed(self, post_id: str) -> bool:
        row = self._require_conn().execute(
            "SELECT 1 FROM processed_posts WHERE post_id = ?",
            (post_id,),
        ).fetchone()
        return row is not None

    def mark_processed(
        self,
        post_id: str,
        notification_status: str,
        *,
        when: datetime | None = None,
    ) -> None:
        processed_at = (when or utc_now()).isoformat()
        self._require_conn().execute(
            """
            INSERT INTO processed_posts(post_id, processed_at_utc, notification_status)
            VALUES (?, ?, ?)
            ON CONFLICT(post_id) DO UPDATE SET
                processed_at_utc = excluded.processed_at_utc,
                notification_status = excluded.notification_status
            """,
            (post_id, processed_at, notification_status),
        )
        self._require_conn().commit()

    def cleanup_processed(self, *, now: datetime | None = None) -> int:
        conn = self._require_conn()
        reference = now or utc_now()
        cutoff = (reference - timedelta(hours=self.retention_hours)).isoformat()
        before = self.count_processed()
        conn.execute("DELETE FROM processed_posts WHERE processed_at_utc < ?", (cutoff,))
        overflow = self.count_processed() - self.max_processed_ids
        if overflow > 0:
            conn.execute(
                """
                DELETE FROM processed_posts
                WHERE post_id IN (
                    SELECT post_id
                    FROM processed_posts
                    ORDER BY processed_at_utc ASC
                    LIMIT ?
                )
                """,
                (overflow,),
            )
        conn.commit()
        removed = before - self.count_processed()
        if removed:
            logger.info("Cleaned processed-post state count=%s", removed)
        return removed

    def count_processed(self) -> int:
        row = self._require_conn().execute("SELECT COUNT(*) AS count FROM processed_posts").fetchone()
        return int(row["count"])

    def set_last_successful_check(self, when: datetime | None = None) -> None:
        self.set_metadata(LAST_SUCCESSFUL_CHECK_KEY, (when or utc_now()).isoformat())

    def get_last_successful_check(self) -> datetime | None:
        value = self.get_metadata(LAST_SUCCESSFUL_CHECK_KEY)
        if not value:
            return None
        return datetime.fromisoformat(value)

    def set_metadata(self, key: str, value: str) -> None:
        self._require_conn().execute(
            """
            INSERT INTO metadata(key, value)
            VALUES (?, ?)
            ON CONFLICT(key) DO UPDATE SET value = excluded.value
            """,
            (key, value),
        )
        self._require_conn().commit()

    def get_metadata(self, key: str) -> str | None:
        row = self._require_conn().execute(
            "SELECT value FROM metadata WHERE key = ?",
            (key,),
        ).fetchone()
        return None if row is None else str(row["value"])

    def _require_conn(self) -> sqlite3.Connection:
        if self._conn is None:
            raise RuntimeError("Storage is not connected")
        return self._conn

    def __enter__(self) -> "Storage":
        self.connect()
        return self

    def __exit__(self, exc_type: object, exc: object, traceback: object) -> None:
        self.close()


def utc_now() -> datetime:
    return datetime.now(UTC)
