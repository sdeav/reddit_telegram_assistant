from __future__ import annotations

import secrets
from dataclasses import dataclass
from http.server import BaseHTTPRequestHandler, HTTPServer
from typing import Any
from urllib.parse import parse_qs, urlparse

from .config import OAuthConfig, REQUIRED_REDDIT_SCOPES


class OAuthError(RuntimeError):
    """Raised for OAuth setup failures."""


@dataclass
class CallbackResult:
    code: str | None = None
    error: str | None = None


def generate_state() -> str:
    return secrets.token_urlsafe(32)


def build_authorization_url(reddit: Any, state: str) -> str:
    return reddit.auth.url(
        scopes=list(REQUIRED_REDDIT_SCOPES),
        state=state,
        duration="permanent",
    )


def parse_callback_url(callback_url: str, expected_state: str) -> str:
    parsed = urlparse(callback_url)
    query = parse_qs(parsed.query)
    returned_state = query.get("state", [""])[0]
    if not secrets.compare_digest(returned_state, expected_state):
        raise OAuthError("OAuth state mismatch")
    error = query.get("error", [""])[0]
    if error:
        raise OAuthError(f"Reddit returned OAuth error: {error}")
    code = query.get("code", [""])[0]
    if not code:
        raise OAuthError("OAuth callback did not include an authorization code")
    return code


def wait_for_authorization_code(redirect_uri: str, expected_state: str) -> str:
    parsed = urlparse(redirect_uri)
    if parsed.scheme != "http" or parsed.hostname not in {"localhost", "127.0.0.1"}:
        redirected = input("Paste the full redirected URL here: ").strip()
        return parse_callback_url(redirected, expected_state)

    port = parsed.port or 80
    path = parsed.path or "/"
    result = CallbackResult()

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:  # noqa: N802 - required by BaseHTTPRequestHandler
            if urlparse(self.path).path != path:
                self.send_response(404)
                self.end_headers()
                return
            try:
                result.code = parse_callback_url(f"http://localhost:{port}{self.path}", expected_state)
                body = b"Authorization received. You can close this browser window."
                self.send_response(200)
                self.send_header("Content-Type", "text/plain; charset=utf-8")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)
            except OAuthError as exc:
                result.error = str(exc)
                body = b"Authorization failed. Return to the terminal for details."
                self.send_response(400)
                self.send_header("Content-Type", "text/plain; charset=utf-8")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

        def log_message(self, format: str, *args: object) -> None:
            return

    with HTTPServer((parsed.hostname, port), Handler) as server:
        server.handle_request()

    if result.error:
        raise OAuthError(result.error)
    if not result.code:
        raise OAuthError("OAuth callback was not received")
    return result.code


def build_praw_reddit(config: OAuthConfig) -> Any:
    try:
        import praw
    except ModuleNotFoundError as exc:
        raise OAuthError("PRAW is not installed. Install project dependencies first.") from exc

    return praw.Reddit(
        client_id=config.reddit_client_id,
        client_secret=config.reddit_client_secret,
        redirect_uri=config.reddit_redirect_uri,
        user_agent=config.reddit_user_agent,
    )


def run_authorization() -> None:
    config = OAuthConfig.from_env()
    state = generate_state()
    reddit = build_praw_reddit(config)
    authorization_url = build_authorization_url(reddit, state)

    print("Open this Reddit authorization URL in your browser:")
    print(authorization_url)
    print()
    print(
        "The command is requesting exactly these scopes: "
        + ", ".join(REQUIRED_REDDIT_SCOPES)
    )
    print("Waiting for the OAuth redirect...")

    code = wait_for_authorization_code(config.reddit_redirect_uri, state)
    refresh_token = reddit.auth.authorize(code)

    print()
    print("Place this line in your .env file:")
    print(f"REDDIT_REFRESH_TOKEN={refresh_token}")


def main() -> None:
    run_authorization()


if __name__ == "__main__":
    main()
