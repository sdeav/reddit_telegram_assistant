from __future__ import annotations

import argparse
import asyncio
import logging
from pathlib import Path

from .config import AppConfig, ConfigError, load_keywords
from .logging_config import configure_logging
from .matcher import KeywordMatcher
from .monitor import RedditMonitor
from .reddit_client import RedditAuthenticationError, RedditClient
from .scheduler import TelegramJobScheduler
from .storage import Storage
from .telegram_bot import TelegramBot, TelegramNotifier

logger = logging.getLogger(__name__)


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(prog="python -m assistant")
    parser.add_argument(
        "--check-once",
        action="store_true",
        help="Run one Reddit check and exit without Telegram long polling.",
    )
    return parser.parse_args(argv)


async def run(*, check_once: bool = False, base_dir: Path | None = None) -> int:
    config = AppConfig.from_env(base_dir=base_dir)
    configure_logging(
        config.log_level,
        secrets=(
            config.reddit_client_secret,
            config.reddit_refresh_token,
            config.telegram_bot_token,
        ),
    )
    logger.info("Application startup")

    keywords = load_keywords(config.keywords_path)
    matcher = KeywordMatcher.from_keywords(keywords)

    storage = Storage(
        config.database_path,
        retention_hours=config.processed_id_retention_hours,
        max_processed_ids=config.max_processed_ids,
    )
    storage.connect()
    try:
        reddit_client = RedditClient.from_config(config)
        verification = reddit_client.verify_expected_username(config.expected_reddit_username)
        logger.info("Reddit authentication completed")
        logger.info(
            "Expected Reddit username verification matches=%s",
            verification.matches_expected,
        )
        if not verification.matches_expected:
            raise RedditAuthenticationError("Authenticated Reddit account does not match expected username")

        notifier = TelegramNotifier.from_config(config)
        monitor = RedditMonitor(
            config=config,
            reddit_client=reddit_client,
            matcher=matcher,
            storage=storage,
            notifier=notifier,
        )
        scheduler = TelegramJobScheduler(
            monitor,
            interval_minutes=config.check_interval_minutes,
        )

        if check_once:
            result = await monitor.run_check()
            logger.info("One-time check finished errors=%s", len(result.errors))
            return 1 if result.errors else 0

        bot = TelegramBot(
            config=config,
            reddit_client=reddit_client,
            monitor=monitor,
            scheduler=scheduler,
            verification=verification,
            matcher_keyword_count=len(matcher.keywords),
        )
        await bot.run_polling()
        return 0
    finally:
        logger.info("Application shutdown")
        storage.close()


def main(argv: list[str] | None = None) -> None:
    args = parse_args(argv)
    try:
        raise SystemExit(asyncio.run(run(check_once=args.check_once)))
    except ConfigError as exc:
        print(f"Configuration error: {exc}")
        raise SystemExit(2) from exc
    except RedditAuthenticationError as exc:
        print(f"Reddit authentication error: {exc}")
        raise SystemExit(3) from exc


if __name__ == "__main__":
    main()
