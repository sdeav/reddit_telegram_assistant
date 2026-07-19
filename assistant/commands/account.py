from __future__ import annotations

from assistant.models import RedditAccountVerification


def format_account_response(verification: RedditAccountVerification) -> str:
    match_text = "yes" if verification.matches_expected else "no"
    scopes = ", ".join(verification.configured_scopes)
    granted = ", ".join(verification.granted_scopes) if verification.granted_scopes else "unknown"
    return (
        "Reddit account\n"
        f"Authenticated username: u/{verification.authenticated_username}\n"
        f"Matches expected username: {match_text}\n"
        f"Configured OAuth scopes: {scopes}\n"
        f"Granted OAuth scopes: {granted}"
    )
