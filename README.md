# reddit_telegram_assistant

A private Reddit-to-Telegram assistant for one authorized Telegram user.

The application runs continuously with Telegram long polling. A scheduled monitor checks configured public subreddits for new posts, matches configured keywords against post titles and self-text in memory, and sends permalink-only Telegram alerts.

## Features

- Monitor new public posts in configured subreddits.
- Match single keywords and multi-word phrases from `config/keywords.txt`.
- Send private Telegram alerts containing only a generic message and the Reddit permalink.
- Save matched posts from an inline Telegram button.
- Optionally auto-save matched posts with `AUTO_SAVE_MATCHES=true`.
- Save a Reddit post or comment manually with `/save <reddit_url>`.
- List saved Reddit posts and comments with pagination.
- List recent comments from the authenticated Reddit account, with optional search over the fetched comments.
- Verify the authenticated Reddit username before starting monitoring or Telegram commands.
- Store only duplicate-prevention state in SQLite.

## Project Structure

```text
reddit_telegram_assistant/
├── assistant/
│   ├── __init__.py
│   ├── __main__.py
│   ├── main.py
│   ├── auth.py
│   ├── config.py
│   ├── models.py
│   ├── reddit_client.py
│   ├── telegram_bot.py
│   ├── monitor.py
│   ├── matcher.py
│   ├── scheduler.py
│   ├── storage.py
│   ├── logging_config.py
│   └── commands/
├── config/
│   └── keywords.txt
├── tests/
├── .env.example
├── .gitignore
├── pyproject.toml
├── README.md
└── LICENSE
```

There is no `src` folder and no nested `assistant` package.

## Installation

Requires Python 3.12 or newer.

```bash
cd reddit_telegram_assistant
python -m venv .venv
source .venv/bin/activate
python -m pip install -e ".[test]"
cp .env.example .env
```

## Reddit Application Configuration

Create a Reddit application at https://www.reddit.com/prefs/apps.

Use an installed app or script-style app that supports OAuth redirect flow. Set the redirect URI to match:

```text
http://localhost:8080
```

Set a descriptive user agent, for example:

```text
private:reddit-telegram-assistant:v0.1.0 (by u/your_username)
```

## OAuth Authorization

Fill these values in `.env` first:

```text
REDDIT_CLIENT_ID=
REDDIT_CLIENT_SECRET=
REDDIT_REDIRECT_URI=http://localhost:8080
REDDIT_USER_AGENT=
```

Then run:

```bash
python -m assistant.auth
```

The command requests exactly these Reddit OAuth scopes:

- `identity`
- `read`
- `save`
- `history`

It uses permanent authorization, generates a secure state value, verifies the returned state, exchanges the authorization code for a refresh token, and prints the `REDDIT_REFRESH_TOKEN=` line for `.env`.

The application uses the refresh token during normal operation. It does not use Reddit username/password authentication.

## Telegram Bot Configuration

Create a Telegram bot with BotFather and place the bot token in `.env`.

Set both:

```text
TELEGRAM_ALLOWED_USER_ID=
TELEGRAM_ALLOWED_CHAT_ID=
```

Every command and callback checks both the Telegram user ID and chat ID before doing anything. Unauthorized users receive only a generic unauthorized response. They cannot trigger Reddit API calls, see configured subreddits or keywords, or access Reddit account data.

## Environment Variables

```text
REDDIT_CLIENT_ID=
REDDIT_CLIENT_SECRET=
REDDIT_REDIRECT_URI=http://localhost:8080
REDDIT_REFRESH_TOKEN=
EXPECTED_REDDIT_USERNAME=
REDDIT_USER_AGENT=
TELEGRAM_BOT_TOKEN=
TELEGRAM_ALLOWED_USER_ID=
TELEGRAM_ALLOWED_CHAT_ID=
SUBREDDITS=islam
CHECK_INTERVAL_MINUTES=15
REDDIT_NEW_POST_LIMIT=25
AUTO_SAVE_MATCHES=false
DATABASE_PATH=reddit_telegram_assistant.sqlite3
SEEN_POST_RETENTION_HOURS=48
MAX_SEEN_POST_IDS=5000
LOG_LEVEL=INFO
```

`EXPECTED_REDDIT_USERNAME` accepts both `username` and `u/username` formats. Startup stops if the authenticated Reddit account does not match.

`SUBREDDITS` supports comma-separated subreddit names:

```text
SUBREDDITS=islam,another_subreddit
```

## Keyword Configuration

Edit `config/keywords.txt`.

- One keyword or phrase per line.
- Blank lines are ignored.
- Lines beginning with `#` are ignored.
- Matching is case-insensitive.
- Whitespace is normalized.
- Single words and multi-word phrases are supported.
- Partial-word matches are prevented.

Keywords are matched only against each post title and self-text in memory.

## Running

Start the long-running bot:

```bash
python -m assistant
```

Run one check and exit without Telegram long polling:

```bash
python -m assistant --check-once
```

## Telegram Commands

- `/start` - display supported commands.
- `/help` - display concise command instructions.
- `/account` - display authenticated Reddit username, expected username match status, and configured OAuth scopes.
- `/status` - display authentication, monitoring, counts, last check, and next scheduled check.
- `/checknow` - run an immediate Reddit check if one is not already running.
- `/save <reddit_url>` - save a Reddit post or comment URL.
- `/saved` - list saved Reddit posts and comments, five per page.
- `/comments` - list recent comments from the authenticated Reddit account.
- `/comments search phrase` - search within the limited fetched recent comments.

## OAuth Scopes

- `identity`: verify the authenticated Reddit account.
- `read`: read public posts, comments, and Reddit URLs provided by the authorized user.
- `save`: save posts and comments to the authenticated account.
- `history`: retrieve saved items and the authenticated account's own recent comments.

No other Reddit OAuth scopes are requested.

## Data Stored Locally

SQLite is used only for duplicate prevention. It stores:

- Reddit post ID.
- UTC time when processing was successfully completed.

The application does not store:

- Reddit usernames from posts.
- Post titles.
- Post bodies.
- Comment bodies.
- Telegram message text.
- Matched keywords.
- Saved-item content.
- Reddit tokens.
- Telegram tokens.
- User profiles.

## Retention Policy

Seen-post records expire after 48 hours by default. Cleanup runs automatically during monitor checks. The maximum number of seen post IDs is also capped by `MAX_SEEN_POST_IDS`.

The legacy names `PROCESSED_ID_RETENTION_HOURS` and `MAX_PROCESSED_IDS` are still accepted for existing local `.env` files.

## Privacy Protections

- The application is for one authorized Telegram user.
- Post alerts contain only a generic message and the Reddit permalink.
- Alerts do not include author usernames, post titles, post bodies, excerpts, matched keywords, or profile data.
- The monitor evaluates each post independently.
- It does not inspect or analyze Reddit author histories.
- It does not profile Reddit users.
- It does not access Reddit Chat or private messages.
- It does not automatically comment, post, vote, edit, delete, moderate, or contact users.
- It does not use Reddit data for AI training.

## Rate Limits and Failures

The monitor retrieves only a small number of newest posts per subreddit. It prevents overlapping checks, continues with other subreddits when one fails, and uses bounded exponential backoff for temporary Reddit failures such as rate limits and network errors.

If a matching post cannot be delivered to Telegram, it is not marked seen. A later monitoring check can retry the same notification. If optional auto-save fails after a Telegram notification succeeds, the post is still marked seen and the save failure is logged safely.

Authentication and configuration failures are not retried endlessly.

## Security Protections

- OAuth state is generated securely and verified.
- Refresh tokens are used for normal operation.
- Reddit username/password authentication is not used.
- Secrets and tokens are not logged.
- Reddit post content, comment content, and Telegram message contents are not logged.
- Telegram user ID and chat ID are checked before every command and callback.

## Testing

Tests use mocked Reddit and Telegram clients and do not require real credentials.

```bash
python -m compileall .
pytest
```

## Known Limitations

- `/comments` searches only within a limited number of recently fetched authenticated-user comments. It is not a complete Reddit-history search.
- Saved-item and comment titles or bodies are fetched live only for authorized display and are not stored locally.
- Telegram pagination state is short-lived process memory.
- The bot is designed for one private Telegram user, not groups or multiple users.
