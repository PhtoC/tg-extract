"""体检脚本：只发一次验证码，把 Telegram 的真实反馈打印出来。"""
from __future__ import annotations

import asyncio

from telethon import TelegramClient
from telethon.errors import ApiIdInvalidError, FloodWaitError, PhoneNumberInvalidError

from . import config
from .login import ask, describe_sent_type, normalize_phone


async def main() -> None:
    config.ensure_dirs()
    api_id = config.get_int("API_ID")
    api_hash = config.get("API_HASH")
    if not api_id or not api_hash:
        raise SystemExit("还没有 .env，先跑 ./start.sh")

    print(f"api_id={api_id}  api_hash={api_hash[:4]}...{api_hash[-4:]}")
    print()

    client = TelegramClient(str(config.DATA_DIR / "user"), api_id, api_hash)
    await client.connect()
    print("网络连接：正常")
    print(f"是否已登录：{'是' if await client.is_user_authorized() else '否'}")
    print()

    while True:
        phone = normalize_phone(ask("手机号（国内直接输 13800138000）"))
        if phone:
            break
        print("  号码认不出来。")
    print(f"规范化后：{phone}")

    try:
        sent = await client.send_code_request(phone)
    except PhoneNumberInvalidError:
        print("❌ Telegram 说这个号码格式不合法。")
        await client.disconnect()
        return
    except ApiIdInvalidError:
        print("❌ api_id / api_hash 不对。")
        await client.disconnect()
        return
    except FloodWaitError as exc:
        print(f"⏳ 请求太频繁，需要等 {exc.seconds} 秒（约 {exc.seconds // 60} 分钟）。")
        await client.disconnect()
        return

    print()
    print(f"✅ 验证码请求已被接受：{describe_sent_type(sent)}")
    print(f"   超时时间：{sent.timeout} 秒")
    nxt = getattr(sent, "next_type", None)
    if nxt is not None:
        print(f"   再次请求会改用：{type(nxt).__name__}")
    print()
    print("如果上面写的是「发到 Telegram App 内部」，就去手机 Telegram 里")
    print("找名字叫 Telegram 的官方对话；找不到就说明那个号码上没登录过任何设备。")
    await client.disconnect()


if __name__ == "__main__":
    asyncio.run(main())
