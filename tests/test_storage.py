from __future__ import annotations

import sqlite3
from datetime import UTC, datetime, timedelta
from pathlib import Path

from assistant.storage import Storage


def make_storage(tmp_path: Path, *, retention_hours: int = 48, max_seen_post_ids: int = 5000) -> Storage:
    storage = Storage(
        tmp_path / "state.sqlite3",
        retention_hours=retention_hours,
        max_seen_post_ids=max_seen_post_ids,
    )
    storage.connect()
    return storage


def test_duplicate_notification_prevention_state(tmp_path: Path) -> None:
    storage = make_storage(tmp_path)

    storage.mark_seen("post1")

    assert storage.has_seen("post1")


def test_seen_posts_expire_after_retention_period(tmp_path: Path) -> None:
    storage = make_storage(tmp_path, retention_hours=48)
    now = datetime(2026, 7, 19, tzinfo=UTC)
    storage.mark_seen("old", when=now - timedelta(hours=49))
    storage.mark_seen("new", when=now - timedelta(hours=1))

    removed = storage.cleanup_seen(now=now)

    assert removed == 1
    assert not storage.has_seen("old")
    assert storage.has_seen("new")


def test_maximum_seen_post_limit_keeps_newest_records(tmp_path: Path) -> None:
    storage = make_storage(tmp_path, max_seen_post_ids=3)
    now = datetime(2026, 7, 19, tzinfo=UTC)
    for index in range(5):
        storage.mark_seen(
            f"post-{index}",
            when=now + timedelta(minutes=index),
        )

    storage.cleanup_seen(now=now + timedelta(hours=1))

    assert storage.count_seen() == 3
    assert not storage.has_seen("post-0")
    assert not storage.has_seen("post-1")
    assert storage.has_seen("post-2")
    assert storage.has_seen("post-3")
    assert storage.has_seen("post-4")


def test_sqlite_schema_contains_only_seen_posts_table(tmp_path: Path) -> None:
    storage = make_storage(tmp_path)

    with sqlite3.connect(storage.path) as conn:
        tables = {
            row[0]
            for row in conn.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table' ORDER BY name"
            )
        }
        columns = [
            (row[1], row[2], row[3], row[5])
            for row in conn.execute("PRAGMA table_info(seen_posts)")
        ]

    assert tables == {"seen_posts"}
    assert columns == [
        ("post_id", "TEXT", 0, 1),
        ("seen_at_utc", "TEXT", 1, 0),
    ]


def test_obsolete_storage_tables_and_notification_status_are_removed(tmp_path: Path) -> None:
    database_path = tmp_path / "state.sqlite3"
    with sqlite3.connect(database_path) as conn:
        conn.execute(
            """
            CREATE TABLE processed_posts (
                post_id TEXT PRIMARY KEY,
                processed_at_utc TEXT NOT NULL,
                notification_status TEXT NOT NULL
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE callback_state (
                callback_id TEXT PRIMARY KEY,
                payload TEXT NOT NULL,
                created_at_utc TEXT NOT NULL
            )
            """
        )
        conn.execute("CREATE TABLE metadata (key TEXT PRIMARY KEY, value TEXT NOT NULL)")
        conn.commit()

    storage = Storage(database_path)
    storage.connect()
    storage.close()

    with sqlite3.connect(database_path) as conn:
        tables = {
            row[0]
            for row in conn.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table' ORDER BY name"
            )
        }
        seen_columns = [row[1] for row in conn.execute("PRAGMA table_info(seen_posts)")]

    assert tables == {"seen_posts"}
    assert "notification_status" not in seen_columns
