from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

from assistant.storage import Storage


def make_storage(tmp_path: Path, *, retention_hours: int = 48, max_processed_ids: int = 5000) -> Storage:
    storage = Storage(
        tmp_path / "state.sqlite3",
        retention_hours=retention_hours,
        max_processed_ids=max_processed_ids,
    )
    storage.connect()
    return storage


def test_duplicate_notification_prevention_state(tmp_path: Path) -> None:
    storage = make_storage(tmp_path)

    storage.mark_processed("post1", "notified")

    assert storage.has_processed("post1")


def test_processed_ids_expire_after_48_hours(tmp_path: Path) -> None:
    storage = make_storage(tmp_path, retention_hours=48)
    now = datetime(2026, 7, 19, tzinfo=UTC)
    storage.mark_processed("old", "notified", when=now - timedelta(hours=49))
    storage.mark_processed("new", "notified", when=now - timedelta(hours=1))

    removed = storage.cleanup_processed(now=now)

    assert removed == 1
    assert not storage.has_processed("old")
    assert storage.has_processed("new")


def test_maximum_processed_id_limit_is_enforced(tmp_path: Path) -> None:
    storage = make_storage(tmp_path, max_processed_ids=3)
    now = datetime(2026, 7, 19, tzinfo=UTC)
    for index in range(5):
        storage.mark_processed(
            f"post-{index}",
            "no_match",
            when=now + timedelta(minutes=index),
        )

    storage.cleanup_processed(now=now + timedelta(hours=1))

    assert storage.count_processed() == 3
    assert not storage.has_processed("post-0")
    assert not storage.has_processed("post-1")
    assert storage.has_processed("post-4")
