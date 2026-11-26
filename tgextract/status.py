"""退出码 0 = 已登录；1 = 未登录 / 没配置。给 start.sh 判断用。"""
from __future__ import annotations

import asyncio
import sys

from telethon import TelegramClient

from . import config


async def check() -> bool:
    api_id = config.get_int("API_ID")
    api_hash = config.get("API_HASH")
    if not api_id or not api_hash:
        return False
    client = TelegramClient(str(config.DATA_DIR / "user"), api_id, api_hash)
    try:
        await client.connect()
        return await client.is_user_authorized()
    except Exception:
        return False
    finally:
        try:
            await client.disconnect()
        except Exception:
            pass


if __name__ == "__main__":
    try:
        ok = asyncio.run(check())
    except Exception:
        ok = False
    sys.exit(0 if ok else 1)
