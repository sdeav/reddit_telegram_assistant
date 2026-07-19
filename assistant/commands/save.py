from __future__ import annotations

from assistant.models import SaveResult


def format_save_success(result: SaveResult) -> str:
    label = "comment" if result.item_kind == "comment" else "post"
    return f"Saved Reddit {label}."


def format_save_error() -> str:
    return "Could not save that Reddit item. Check the URL or try again later."
