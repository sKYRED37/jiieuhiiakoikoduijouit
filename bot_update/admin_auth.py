"""Shared admin authorization for Football Manager bot.

Set ADMIN_IDS as comma-separated Telegram numeric user IDs, e.g. 123456789,987654321.
Group administrators are also allowed.
"""
import os


def configured_admin_ids() -> set[int]:
    raw = os.getenv("ADMIN_IDS", "")
    ids: set[int] = set()
    for part in raw.split(","):
        part = part.strip()
        if part.isdigit():
            ids.add(int(part))
    return ids


async def is_admin_user(message) -> bool:
    user = getattr(message, "from_user", None)
    if user and user.id in configured_admin_ids():
        return True
    chat = getattr(message, "chat", None)
    if not user or not chat or chat.type not in ("group", "supergroup"):
        return False
    try:
        member = await message.bot.get_chat_member(chat.id, user.id)
        return member.status in ("creator", "administrator")
    except Exception:
        return False
