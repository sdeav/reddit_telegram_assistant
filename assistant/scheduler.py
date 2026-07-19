from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any

from .monitor import RedditMonitor

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class SchedulerStatus:
    running: bool
    next_scheduled_check: datetime | None


class TelegramJobScheduler:
    def __init__(self, monitor: RedditMonitor, *, interval_minutes: int) -> None:
        self.monitor = monitor
        self.interval_minutes = interval_minutes
        self._job: Any | None = None

    def start(self, application: Any) -> None:
        if application.job_queue is None:
            raise RuntimeError("python-telegram-bot JobQueue is unavailable")
        self._job = application.job_queue.run_repeating(
            self._run,
            interval=timedelta(minutes=self.interval_minutes),
            first=10,
            name="reddit-monitor",
        )
        logger.info("Monitoring scheduler started interval_minutes=%s", self.interval_minutes)

    async def _run(self, context: Any) -> None:
        await self.monitor.run_check()

    def status(self) -> SchedulerStatus:
        next_run = getattr(self._job, "next_t", None) if self._job is not None else None
        return SchedulerStatus(running=self._job is not None, next_scheduled_check=next_run)
