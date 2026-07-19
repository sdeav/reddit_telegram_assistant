from __future__ import annotations

from collections.abc import Sequence

from assistant.models import SavedItem

PAGE_SIZE = 5


def page_items(items: Sequence[SavedItem], page: int, *, page_size: int = PAGE_SIZE) -> list[SavedItem]:
    start = max(page, 0) * page_size
    return list(items[start : start + page_size])


def format_saved_page(items: Sequence[SavedItem], page: int, *, page_size: int = PAGE_SIZE) -> str:
    visible = page_items(items, page, page_size=page_size)
    lines = [f"Your saved Reddit items - page {page + 1}"]
    if not visible:
        lines.append("No saved Reddit items found.")
        return "\n".join(lines)
    offset = page * page_size
    for index, item in enumerate(visible, start=1):
        lines.append(f"{offset + index}. {item.label}")
        lines.append(item.permalink)
    return "\n".join(lines)


def has_previous(page: int) -> bool:
    return page > 0


def has_next(items: Sequence[SavedItem], page: int, *, page_size: int = PAGE_SIZE) -> bool:
    return (page + 1) * page_size < len(items)
