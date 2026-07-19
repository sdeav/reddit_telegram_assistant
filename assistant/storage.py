from __future__ import annotations

import logging
import sqlite3
from datetime import UTC, datetime, timedelta
from pathlib import Path

logger = logging.getLogger(__name__)


class Storage:
    def __init__(
        self,
        path: Path | str,
        *,
        retention_hours: int = 48,
        max_seen_post_ids: int | None = None,
        max_processed_ids: int | None = None,
    ) -> None:
        self.path = Path(path)
        self.retention_hours = retention_hours
        self.max_seen_post_ids = max_seen_post_ids or max_processed_ids or 5000
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
        conn.execute("DROP TABLE IF EXISTS processed_posts")
        conn.execute("DROP TABLE IF EXISTS metadata")
        conn.execute("DROP TABLE IF EXISTS callback_state")
        if not self._seen_posts_schema_is_minimal():
            conn.execute("DROP TABLE IF EXISTS seen_posts")
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS seen_posts (
                post_id TEXT PRIMARY KEY,
                seen_at_utc TEXT NOT NULL
            )
            """
        )
        conn.commit()

    def has_seen(self, post_id: str) -> bool:
        row = self._require_conn().execute(
            "SELECT 1 FROM seen_posts WHERE post_id = ?",
            (post_id,),
        ).fetchone()
        return row is not None

    def mark_seen(
        self,
        post_id: str,
        *,
        when: datetime | None = None,
    ) -> None:
        seen_at = _to_utc_iso(when or utc_now())
        self._require_conn().execute(
            """
            INSERT INTO seen_posts(post_id, seen_at_utc)
            VALUES (?, ?)
            ON CONFLICT(post_id) DO UPDATE SET
                seen_at_utc = excluded.seen_at_utc
            """,
            (post_id, seen_at),
        )
        self._require_conn().commit()

    def cleanup_seen(self, *, now: datetime | None = None) -> int:
        conn = self._require_conn()
        reference = now or utc_now()
        cutoff = _to_utc_iso(reference - timedelta(hours=self.retention_hours))
        before = self.count_seen()
        conn.execute("DELETE FROM seen_posts WHERE seen_at_utc < ?", (cutoff,))
        overflow = self.count_seen() - self.max_seen_post_ids
        if overflow > 0:
            conn.execute(
                """
                DELETE FROM seen_posts
                WHERE post_id IN (
                    SELECT post_id
                    FROM seen_posts
                    ORDER BY seen_at_utc ASC, post_id ASC
                    LIMIT ?
                )
                """,
                (overflow,),
            )
        conn.commit()
        removed = before - self.count_seen()
        if removed:
            logger.info("Cleaned seen-post state count=%s", removed)
        return removed

    def count_seen(self) -> int:
        row = self._require_conn().execute("SELECT COUNT(*) AS count FROM seen_posts").fetchone()
        return int(row["count"])

    def _require_conn(self) -> sqlite3.Connection:
        if self._conn is None:
            raise RuntimeError("Storage is not connected")
        return self._conn

    def _seen_posts_schema_is_minimal(self) -> bool:
        rows = self._require_conn().execute("PRAGMA table_info(seen_posts)").fetchall()
        if not rows:
            return True
        columns = tuple((str(row["name"]), str(row["type"]).upper()) for row in rows)
        return columns == (("post_id", "TEXT"), ("seen_at_utc", "TEXT"))

    def __enter__(self) -> "Storage":
        self.connect()
        return self

    def __exit__(self, exc_type: object, exc: object, traceback: object) -> None:
        self.close()


def utc_now() -> datetime:
    return datetime.now(UTC)


def _to_utc_iso(value: datetime) -> str:
    if value.tzinfo is None:
        value = value.replace(tzinfo=UTC)
    return value.astimezone(UTC).isoformat()
