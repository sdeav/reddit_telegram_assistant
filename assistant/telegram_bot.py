from __future__ import annotations

import logging
import secrets
from dataclasses import dataclass, field
from typing import Any

from .commands.account import format_account_response
from .commands.check_now import format_check_result
from .commands.comments import format_comments_page, has_next as comments_has_next, has_previous as comments_has_previous
from .commands.save import format_save_error, format_save_success
from .commands.saved import format_saved_page, has_next as saved_has_next, has_previous as saved_has_previous
from .commands.status import StatusView, format_status_response
from .config import AppConfig
from .logging_config import safe_error_detail
from .models import RecentComment, RedditAccountVerification, RedditPost, SavedItem
from .reddit_client import RedditClient, RedditClientError, RedditConfigurationError
from .scheduler import TelegramJobScheduler

logger = logging.getLogger(__name__)

START_TEXT = (
    "Commands\n"
    "/account - show Reddit account verification\n"
    "/status - show monitoring status\n"
    "/checknow - run a Reddit check now\n"
    "/save <reddit_url> - save a Reddit post or comment\n"
    "/saved - list saved Reddit items\n"
    "/comments [search phrase] - list recent Reddit comments"
)

HELP_TEXT = (
    "/start - show commands\n"
    "/help - show command help\n"
    "/account - Reddit username and OAuth scope status\n"
    "/status - current monitor state\n"
    "/checknow - run an immediate check when idle\n"
    "/save <reddit_url> - save a Reddit post or comment\n"
    "/saved - browse saved Reddit posts and comments\n"
    "/comments [search phrase] - browse recent own comments"
)

MAX_SAVED_ITEMS = 50
MAX_RECENT_COMMENTS = 50


@dataclass(frozen=True)
class TelegramAccessGuard:
    allowed_user_id: int
    allowed_chat_id: int

    def is_authorized_ids(self, user_id: int | None, chat_id: int | None) -> bool:
        return user_id == self.allowed_user_id and chat_id == self.allowed_chat_id

    def is_authorized_update(self, update: Any) -> bool:
        user = getattr(update, "effective_user", None)
        chat = getattr(update, "effective_chat", None)
        user_id = getattr(user, "id", None)
        chat_id = getattr(chat, "id", None)
        return self.is_authorized_ids(user_id, chat_id)


class TelegramDeliveryError(RuntimeError):
    """Raised when a Telegram notification cannot be delivered."""


@dataclass
class PaginationCache:
    saved_items: list[SavedItem] = field(default_factory=list)
    comment_queries_by_token: dict[str, str | None] = field(default_factory=dict)


class TelegramNotifier:
    def __init__(self, bot: Any, *, allowed_chat_id: int) -> None:
        self.bot = bot
        self.allowed_chat_id = allowed_chat_id

    @classmethod
    def from_config(cls, config: AppConfig) -> "TelegramNotifier":
        try:
            from telegram import Bot
        except ModuleNotFoundError as exc:
            raise TelegramDeliveryError(
                "python-telegram-bot is not installed. Install project dependencies first."
            ) from exc
        return cls(Bot(config.telegram_bot_token), allowed_chat_id=config.telegram_allowed_chat_id)

    async def send_match_alert(self, post: RedditPost) -> None:
        try:
            from telegram import InlineKeyboardButton, InlineKeyboardMarkup
        except ModuleNotFoundError as exc:
            raise TelegramDeliveryError("python-telegram-bot is not installed") from exc

        keyboard = InlineKeyboardMarkup(
            [[InlineKeyboardButton("Save on Reddit", callback_data=f"save:{post.id}")]]
        )
        await self.bot.send_message(
            chat_id=self.allowed_chat_id,
            text=format_match_alert(post),
            reply_markup=keyboard,
            disable_web_page_preview=True,
        )


class TelegramBot:
    def __init__(
        self,
        *,
        config: AppConfig,
        reddit_client: RedditClient,
        monitor: Any,
        scheduler: TelegramJobScheduler,
        verification: RedditAccountVerification,
        matcher_keyword_count: int,
    ) -> None:
        self.config = config
        self.reddit_client = reddit_client
        self.monitor = monitor
        self.scheduler = scheduler
        self.verification = verification
        self.matcher_keyword_count = matcher_keyword_count
        self.guard = TelegramAccessGuard(
            config.telegram_allowed_user_id,
            config.telegram_allowed_chat_id,
        )
        self.cache = PaginationCache()

    def build_application(self) -> Any:
        try:
            from telegram.ext import ApplicationBuilder, CallbackQueryHandler, CommandHandler
        except ModuleNotFoundError as exc:
            raise RuntimeError(
                "python-telegram-bot is not installed. Install project dependencies first."
            ) from exc

        application = ApplicationBuilder().token(self.config.telegram_bot_token).build()
        application.add_handler(CommandHandler("start", self.start))
        application.add_handler(CommandHandler("help", self.help))
        application.add_handler(CommandHandler("account", self.account))
        application.add_handler(CommandHandler("status", self.status))
        application.add_handler(CommandHandler("checknow", self.checknow))
        application.add_handler(CommandHandler("save", self.save))
        application.add_handler(CommandHandler("saved", self.saved))
        application.add_handler(CommandHandler("comments", self.comments))
        application.add_handler(CallbackQueryHandler(self.callback))
        self.scheduler.start(application)
        return application

    async def run_polling(self) -> None:
        application = self.build_application()
        logger.info("Telegram long polling starting")
        await application.initialize()
        await application.start()
        await application.updater.start_polling()
        try:
            await _idle_forever()
        finally:
            logger.info("Telegram long polling stopping")
            await application.updater.stop()
            await application.stop()
            await application.shutdown()

    async def start(self, update: Any, context: Any) -> None:
        if not await self._ensure_authorized(update):
            return
        await update.effective_message.reply_text(START_TEXT)

    async def help(self, update: Any, context: Any) -> None:
        if not await self._ensure_authorized(update):
            return
        await update.effective_message.reply_text(HELP_TEXT)

    async def account(self, update: Any, context: Any) -> None:
        if not await self._ensure_authorized(update):
            return
        try:
            verification = self.reddit_client.verify_expected_username(
                self.config.expected_reddit_username
            )
        except RedditClientError:
            verification = self.verification
        await update.effective_message.reply_text(format_account_response(verification))

    async def status(self, update: Any, context: Any) -> None:
        if not await self._ensure_authorized(update):
            return
        monitor_status = self.monitor.status()
        scheduler_status = self.scheduler.status()
        view = StatusView(
            reddit_authentication_ok=True,
            reddit_username_verified=self.verification.matches_expected,
            monitoring_running=monitor_status.is_running,
            subreddit_count=len(self.config.subreddits),
            keyword_count=self.matcher_keyword_count,
            last_successful_check=monitor_status.last_successful_check_utc,
            last_check_result=monitor_status.last_result,
            next_scheduled_check=scheduler_status.next_scheduled_check,
        )
        await update.effective_message.reply_text(format_status_response(view))

    async def checknow(self, update: Any, context: Any) -> None:
        if not await self._ensure_authorized(update):
            return
        result = await self.monitor.run_check()
        await update.effective_message.reply_text(format_check_result(result))

    async def save(self, update: Any, context: Any) -> None:
        if not await self._ensure_authorized(update):
            return
        args = getattr(context, "args", []) or []
        if len(args) != 1:
            await update.effective_message.reply_text("Usage: /save <reddit_url>")
            return
        try:
            result = self.reddit_client.save_url(args[0])
            logger.info("Manual Reddit save completed item_kind=%s item_id=%s", result.item_kind, result.item_id)
            await update.effective_message.reply_text(format_save_success(result))
        except (RedditClientError, RedditConfigurationError):
            await update.effective_message.reply_text(format_save_error())

    async def saved(self, update: Any, context: Any) -> None:
        if not await self._ensure_authorized(update):
            return
        try:
            self.cache.saved_items = self.reddit_client.list_saved(limit=MAX_SAVED_ITEMS)
            await self._reply_saved_page(update.effective_message, page=0)
        except RedditClientError:
            await update.effective_message.reply_text("Could not retrieve saved Reddit items.")

    async def comments(self, update: Any, context: Any) -> None:
        if not await self._ensure_authorized(update):
            return
        args = getattr(context, "args", []) or []
        query = " ".join(args).strip() or None
        try:
            comments = self.reddit_client.list_my_recent_comments(limit=MAX_RECENT_COMMENTS)
            token = "all" if query is None else secrets.token_urlsafe(8)
            self.cache.comment_queries_by_token[token] = query
            await self._reply_comments_page(update.effective_message, token=token, page=0, comments=comments)
        except RedditClientError:
            await update.effective_message.reply_text("Could not retrieve recent Reddit comments.")

    async def callback(self, update: Any, context: Any) -> None:
        if not await self._ensure_authorized(update):
            return
        query = update.callback_query
        data = query.data or ""
        if data.startswith("save:"):
            await self._handle_save_callback(query, data.removeprefix("save:"))
            return
        if data.startswith("saved:"):
            await self._handle_saved_callback(query, data)
            return
        if data.startswith("comments:"):
            await self._handle_comments_callback(query, data)
            return
        await query.answer("Unsupported action.")

    async def _handle_save_callback(self, query: Any, post_id: str) -> None:
        try:
            self.reddit_client.save_submission_by_id(post_id)
            logger.info("Callback Reddit save completed post_id=%s", post_id)
            await query.answer("Saved on Reddit.")
        except RedditClientError:
            await query.answer("Could not save that Reddit post.")

    async def _handle_saved_callback(self, query: Any, data: str) -> None:
        try:
            page = max(int(data.split(":", 1)[1]), 0)
        except ValueError:
            await query.answer("Invalid page.")
            return
        await self._edit_saved_page(query, page=page)

    async def _handle_comments_callback(self, query: Any, data: str) -> None:
        parts = data.split(":")
        if len(parts) != 3 or parts[1] not in self.cache.comment_queries_by_token:
            await query.answer("Page expired.")
            return
        try:
            page = max(int(parts[2]), 0)
        except ValueError:
            await query.answer("Invalid page.")
            return
        await self._edit_comments_page(query, token=parts[1], page=page)

    async def _reply_saved_page(self, message: Any, *, page: int) -> None:
        await message.reply_text(
            format_saved_page(self.cache.saved_items, page),
            reply_markup=self._saved_markup(page),
            disable_web_page_preview=True,
        )

    async def _edit_saved_page(self, query: Any, *, page: int) -> None:
        await query.edit_message_text(
            format_saved_page(self.cache.saved_items, page),
            reply_markup=self._saved_markup(page),
            disable_web_page_preview=True,
        )
        await query.answer()

    async def _reply_comments_page(
        self,
        message: Any,
        *,
        token: str,
        page: int,
        comments: list[RecentComment] | None = None,
    ) -> None:
        comments = comments or self.reddit_client.list_my_recent_comments(limit=MAX_RECENT_COMMENTS)
        query = self.cache.comment_queries_by_token[token]
        await message.reply_text(
            format_comments_page(comments, page, query=query),
            reply_markup=self._comments_markup(token, page, comments=comments, query=query),
            disable_web_page_preview=True,
        )

    async def _edit_comments_page(self, query_obj: Any, *, token: str, page: int) -> None:
        search_query = self.cache.comment_queries_by_token[token]
        comments = self.reddit_client.list_my_recent_comments(limit=MAX_RECENT_COMMENTS)
        await query_obj.edit_message_text(
            format_comments_page(comments, page, query=search_query),
            reply_markup=self._comments_markup(token, page, comments=comments, query=search_query),
            disable_web_page_preview=True,
        )
        await query_obj.answer()

    def _saved_markup(self, page: int) -> Any:
        return build_pagination_markup(
            previous_data=f"saved:{page - 1}" if saved_has_previous(page) else None,
            next_data=f"saved:{page + 1}" if saved_has_next(self.cache.saved_items, page) else None,
        )

    def _comments_markup(
        self,
        token: str,
        page: int,
        *,
        comments: list[RecentComment],
        query: str | None,
    ) -> Any:
        return build_pagination_markup(
            previous_data=f"comments:{token}:{page - 1}" if comments_has_previous(page) else None,
            next_data=(
                f"comments:{token}:{page + 1}"
                if comments_has_next(comments, page, query=query)
                else None
            ),
        )

    async def _ensure_authorized(self, update: Any) -> bool:
        if self.guard.is_authorized_update(update):
            return True
        callback_query = getattr(update, "callback_query", None)
        if callback_query is not None:
            await callback_query.answer("Unauthorized.")
            return False
        message = getattr(update, "effective_message", None)
        if message is not None:
            await message.reply_text("Unauthorized.")
        return False


def format_match_alert(post: RedditPost) -> str:
    return f"New matching post found in r/{post.subreddit}:\n{post.permalink}"


def build_pagination_markup(*, previous_data: str | None, next_data: str | None) -> Any:
    buttons = []
    try:
        from telegram import InlineKeyboardButton, InlineKeyboardMarkup
    except ModuleNotFoundError:
        return None
    row = []
    if previous_data:
        row.append(InlineKeyboardButton("Previous", callback_data=previous_data))
    if next_data:
        row.append(InlineKeyboardButton("Next", callback_data=next_data))
    if row:
        buttons.append(row)
    return InlineKeyboardMarkup(buttons) if buttons else None


async def _idle_forever() -> None:
    import asyncio

    stop = asyncio.Event()
    await stop.wait()
