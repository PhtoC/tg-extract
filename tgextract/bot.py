"""主程序：一个 bot 客户端负责对话，一个 user 客户端负责取文件。"""
from __future__ import annotations

import asyncio
import json
import logging
import subprocess
import time
from pathlib import Path

from telethon import TelegramClient, events
from telethon.sessions import StringSession
from telethon.tl import types

from . import config, expand, extract, links, state

LOG_PATH = config.DATA_DIR / "bot.log"
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
    handlers=[
        logging.FileHandler(LOG_PATH, encoding="utf-8"),
        logging.StreamHandler(),
    ],
)
log = logging.getLogger("tgextract")
logging.getLogger("telethon").setLevel(logging.WARNING)

HELP = """**媒体提取 bot**

直接把这个格式的链接发给我：
`https://t.me/频道名/123`
`https://t.me/c/1234567890/123`

支持：图片、视频、文件、相册、语音、压缩包（自动解压）。
加密压缩包试不出密码时，发 `/pwd 密码` 告诉我一次。
付费/受限频道只要你的账号已解锁，拿到的就是**清晰原版**。

bot 挂着多个账号时，会自动用**在那个群里**的账号去取。

命令：
/link — 用着不顺手时看这条说明
"""

_semaphore = asyncio.Semaphore(3)


def _fmt(size: int) -> str:
    for unit in ("B", "KB", "MB", "GB"):
        if size < 1024 or unit == "GB":
            return f"{size:.1f}{unit}" if unit != "B" else f"{size}B"
        size /= 1024
    return f"{size:.1f}GB"


async def _edit(client, chat_id, msg_id, text):
    try:
        await client.edit_message(chat_id, msg_id, text, parse_mode="md")
    except Exception:
        pass


VIDEO_EXT = {".mp4", ".m4v", ".mkv", ".avi", ".mov", ".webm", ".ts", ".flv", ".wmv"}


def _is_video_file(path) -> bool:
    return path.suffix.lower() in VIDEO_EXT


def _probe(path):
    """拿时长/宽高，失败返回 None。"""
    try:
        out = subprocess.run(
            ["ffprobe", "-v", "quiet", "-print_format", "json",
             "-show_format", "-show_streams", str(path)],
            capture_output=True, timeout=60,
        ).stdout
        data = json.loads(out or b"{}")
        stream = next((s for s in data.get("streams", []) if s.get("codec_type") == "video"), None)
        if not stream:
            return None
        raw = data.get("format", {}).get("duration") or stream.get("duration") or 0
        return int(float(raw)), int(stream.get("width") or 0), int(stream.get("height") or 0)
    except Exception:
        return None


async def _as_playable(path):
    """把容器/编码不利的片子转成 mp4（无损转封装），保证手机上能直接播放。"""
    if path.suffix.lower() == ".mp4":
        return path
    dest = path.with_suffix(".mp4")
    try:
        proc = await asyncio.create_subprocess_exec(
            "ffmpeg", "-y", "-i", str(path), "-c", "copy", "-movflags", "+faststart", str(dest),
            stdout=asyncio.subprocess.DEVNULL, stderr=asyncio.subprocess.DEVNULL,
        )
        await proc.communicate()
        if dest.exists() and dest.stat().st_size > 0:
            path.unlink(missing_ok=True)
            return dest
    except Exception:
        pass
    return path


def _video_kwargs(path):
    """让 Telegram 把它当视频播放，而不是附件。"""
    info = _probe(path)
    duration, w, h = info if info else (0, 0, 0)
    return {
        "mime_type": "video/mp4",
        "supports_streaming": True,
        "attributes": [
            types.DocumentAttributeVideo(
                duration=duration, w=w, h=h, supports_streaming=True
            )
        ],
    }


def _progress_maker(bot, chat_id, msg_id):
    state = {"last": 0.0}

    def cb(received: int, total: int) -> None:
        now = time.monotonic()
        if now - state["last"] < 2.0:
            return
        state["last"] = now
        pct = f" ({received * 100 // total}%)" if total else ""
        asyncio.create_task(
            _edit(bot, chat_id, msg_id, f"⬇️ 下载中 {_fmt(received)} / {_fmt(total)}{pct}")
        )

    return cb


async def _deliver(bot, user, chat_id, result: extract.Result) -> list[str]:
    """返回给用户的提示语。"""
    notes: list[str] = []
    limit = config.bot_max_bytes()
    items = result.items

    # 视频转成可直接播放的格式；图片/文件照常
    videos, others = [], []
    for item in items:
        if _is_video_file(item.path):
            item.path = await _as_playable(item.path)
            item.size = item.path.stat().st_size
            videos.append(item)
        else:
            others.append(item)

    # 图片等按相册发（视频混在相册里会丢失播放属性，所以单独发）
    small_others = [i for i in others if i.size <= limit]
    if small_others:
        if len(small_others) == 1:
            await bot.send_file(chat_id, str(small_others[0].path))
        else:
            await bot.send_file(chat_id, [str(i.path) for i in small_others])

    for item in videos + [i for i in others if i.size > limit]:
        kwargs = _video_kwargs(item.path) if _is_video_file(item.path) else {}
        if item.size <= limit:
            await bot.send_file(chat_id, str(item.path), **kwargs)
            continue
        # 超过 bot 上限的，用取文件的账号存进它自己的收藏夹
        await user.send_file("me", str(item.path), **kwargs)
        notes.append("📥 超过上限，已存收藏夹")

    for warning in result.warnings:
        notes.append(f"⚠️ {warning}")
    return notes


async def _send_result(bot, accounts, chat_id, result) -> None:
    """先报总数，解压出一个就发一个，中间报进度。"""
    # 先把得到的东西直接发掉（非压缩包）
    plain = [i for i in result.items if not expand.is_archive(i.path)]
    archives = [i for i in result.items if expand.is_archive(i.path)]

    remaining_plan = 0
    listing = {}
    for item in archives:
        entries = await expand.list_entries(item.path)
        listing[item.path] = entries
        remaining_plan += len(entries)

    total = len(plain) + remaining_plan
    has_video = any(expand.is_video(i.path) for i in plain)

    progress = None
    done = 0
    if archives or has_video:
        progress = await bot.send_message(chat_id, f"共 {max(total, 1)} 个")

    async def send_one(item) -> bool:
        nonlocal done
        try:
            if expand.is_video(item.path):
                item.path = await _as_playable(item.path)
                item.size = item.path.stat().st_size
                await bot.send_file(chat_id, str(item.path), **_video_kwargs(item.path))
            else:
                await bot.send_file(chat_id, str(item.path))
        except Exception:
            log.exception("发送失败 %s", item.name)
            return False
        done += 1
        if progress and total:
            left = max(total - done, 0)
            try:
                await bot.edit_message(chat_id, progress.id, f"已完成 {done}，还剩 {left}")
            except Exception:
                pass
        return True

    for item in plain:
        await send_one(item)

    for archive in archives:
        entries = listing.get(archive.path, [])
        if not entries:
            continue
        dest = archive.path.parent / f"{archive.path.stem}_unzip"
        dest.mkdir(parents=True, exist_ok=True)
        for info in entries:
            try:
                got = await expand.extract_one(archive.path, info, dest)
            except expand.NeedPassword:
                await bot.send_message(chat_id, "🔒 压缩包有密码，发 /pwd 密码 告诉我一次")
                await bot.send_file(chat_id, str(archive.path))
                break
            if not got:
                continue
            item = extract.Item(
                path=got, name=got.name, size=got.stat().st_size, kind=expand.kind_of(got)
            )
            await send_one(item)
        archive.path.unlink(missing_ok=True)

    if progress:
        try:
            await bot.edit_message(chat_id, progress.id, f"✅ 完成 {done} 个")
        except Exception:
            pass

    for warning in result.warnings:
        await bot.send_message(chat_id, warning)


async def handle(bot, accounts, event, chat_id: int | None = None) -> None:
    """chat_id 缺省用事件自己的；补漏时历史消息的 chat_id 是 bot 自己，要传用户的 id。"""
    if chat_id is None:
        chat_id = event.chat_id
    text = (event.raw_text or "").strip()

    if text.startswith("/start") or text.startswith("/link"):
        await bot.send_message(chat_id, HELP, parse_mode="md")
        return

    if text.startswith("/pwd"):
        password = text[4:].strip()
        if not password:
            current = config.get("ZIP_PASSWORDS") or "（空）"
            await bot.send_message(chat_id, f"当前密码：{current}\n用法：/pwd 666666")
            return
        existing = [p.strip() for p in config.get("ZIP_PASSWORDS", "").split(",") if p.strip()]
        if password in existing:
            existing.remove(password)
        existing.insert(0, password)
        config.set_env("ZIP_PASSWORDS", ",".join(existing))
        await bot.send_message(chat_id, f"✅ 已记住密码 {password}，重发链接即可")
        return

    found = []
    for token in text.split():
        link = links.parse(token)
        if link:
            found.append(link)
    if not found:
        if text:
            await bot.send_message(
                chat_id, "没识别到链接。发个 `https://t.me/…/123` 这种给我。", parse_mode="md"
            )
        return

    status = await bot.send_message(chat_id, "🔎 处理中…")
    failed = False
    try:
        async with _semaphore:
            for link in found[:10]:
                log.info("开始处理 %s", link.describe())
                stall = {"last": time.monotonic()}
                inner = _progress_maker(bot, chat_id, status.id)

                def on_progress(received: int, total: int) -> None:
                    stall["last"] = time.monotonic()
                    inner(received, total)

                task = asyncio.create_task(
                    extract.fetch(accounts, link, progress=on_progress)
                )
                deadline = time.monotonic() + config.task_timeout()
                stuck = False
                while task and not task.done():
                    await asyncio.sleep(3)
                    now = time.monotonic()
                    if now - stall["last"] > config.stall_timeout():
                        stuck = True
                        task.cancel()
                        break
                    if now > deadline:
                        stuck = True
                        task.cancel()
                        break
                result = None
                error = None
                try:
                    result = await task
                except asyncio.CancelledError:
                    pass
                except extract.ExtractError as exc:
                    error = exc
                except Exception as exc:
                    error = exc
                if error is not None:
                    log.warning("取失败 %s: %s", link.describe(), error)
                    await bot.send_message(chat_id, f"❌ {error}")
                    failed = True
                    continue
                if stuck or result is None:
                    log.warning("卡住取消 %s", link.describe())
                    await bot.send_message(chat_id, "⏱ 卡住了，已自动取消，稍后重发链接再试")
                    failed = True
                    continue
                log.info("取到 %d 个文件 %s", len(result.items), [i.name for i in result.items])
                await _send_result(bot, accounts, chat_id, result)
    except Exception as exc:
        log.exception("处理链路异常")
        failed = True
        await bot.send_message(chat_id, f"❌ 出错了：{exc.__class__.__name__}: {exc}")
    finally:
        if failed:
            await _edit(bot, chat_id, status.id, "❌")
        else:
            try:
                await bot.delete_messages(chat_id, status.id)
            except Exception:
                pass
        if not config.get_int("KEEP_FILES", 0):
            for f in config.TMP_DIR.glob("*"):
                if f.is_file() and time.time() - f.stat().st_mtime > 300:
                    try:
                        f.unlink()
                    except OSError:
                        pass


def load_session(path):
    """会话文件可能是 SQLite，也可能是纯字符串（服务器部署用），两种都支持。"""
    from telethon.sessions import SQLiteSession

    base = path.with_suffix("")
    try:
        raw = path.read_text(encoding="utf-8")
        if raw.startswith("1") and "\n" not in raw.strip():
            return StringSession(raw.strip())
    except (UnicodeDecodeError, OSError):
        pass

    sqlite = SQLiteSession(str(base))
    temp = StringSession()
    temp.set_dc(sqlite.dc_id, sqlite.server_address, sqlite.port)
    temp.auth_key = sqlite.auth_key
    sqlite.close()
    return temp


async def main() -> None:
    config.ensure_dirs()

    api_id = config.get_int("API_ID")
    api_hash = config.get("API_HASH")
    token = config.get("BOT_TOKEN")
    missing = [n for n, v in (("API_ID", api_id), ("API_HASH", api_hash), ("BOT_TOKEN", token)) if not v]
    if missing:
        raise SystemExit(f"缺少配置：{', '.join(missing)}。先运行 ./start.sh")

    blob = config.get("TGX_SESSIONS").strip()
    accounts: list[TelegramClient] = []

    if blob:
        # 云端部署：会话放在环境变量里，不落盘
        import base64
        import json

        data = json.loads(base64.b64decode(blob))
        for raw in data.get("users", []):
            client = TelegramClient(StringSession(raw), api_id, api_hash)
            await client.connect()
            if await client.is_user_authorized():
                accounts.append(client)
            else:
                await client.disconnect()
        if not accounts:
            raise SystemExit("环境变量里的会话都失效了，重新导出。")
        bot = TelegramClient(StringSession(data.get("bot", "")), api_id, api_hash)
        await bot.start(bot_token=token)
    else:
        sessions = config.session_paths()
        if not sessions:
            raise SystemExit("还没有登录任何账号。先运行 ./start.sh")
        for path in sessions:
            client = TelegramClient(load_session(path), api_id, api_hash)
            await client.connect()
            if await client.is_user_authorized():
                accounts.append(client)
            else:
                await client.disconnect()
        if not accounts:
            raise SystemExit("会话都失效了。先运行 ./start.sh 重新登录。")
        bot = TelegramClient(load_session(config.DATA_DIR / "bot"), api_id, api_hash)
        await bot.start(bot_token=token)

    allowed = config.allowed_user_ids()
    if not allowed:
        me = await accounts[0].get_me()
        allowed = {me.id}

    bot_me = await bot.get_me()
    bot_username = bot_me.username

    async def on_message(event):
        sender = getattr(event.message, "sender_id", None) or event.chat_id
        log.info("收到消息 from=%s chat=%s text=%r", sender, event.chat_id, event.raw_text)
        state.mark(event.chat_id, event.message.id)
        if sender not in allowed:
            log.warning("sender=%s 不在白名单 %s", sender, allowed)
            await event.reply(
                f"你不在白名单。你的 Telegram id 是 `{sender}`，\n"
                f"把这一行加到 .env 的 ALLOWED_USER_IDS 里，然后重启 bot。",
                parse_mode="md",
            )
            return
        try:
            await handle(bot, accounts, event)
        except Exception:
            log.exception("处理消息失败")
            raise

    bot.add_event_handler(on_message, events.NewMessage(incoming=True))

    async def catch_up():
        """补处理关机/断网期间漏掉的链接（用账号读 bot 对话历史，bot 自己读不了）。"""
        await asyncio.sleep(5)
        try:
            bot_entity = await accounts[0].get_entity(bot_username)
        except Exception as exc:
            log.warning("补漏拿不到 bot 实体：%s", exc)
            return
        for uid in sorted(allowed):
            since = state.last_id(uid)
            if not since:
                continue
            try:
                history = await accounts[0].get_messages(bot_entity, min_id=since, limit=50)
            except Exception as exc:
                log.warning("补漏读取 %s 失败：%s", uid, exc)
                continue
            pending = [
                m for m in reversed(history)
                if m.raw_text and links.parse(m.raw_text) and m.sender_id == uid
            ]
            if pending:
                log.info("补处理 %s 的 %d 条漏掉消息", uid, len(pending))
            for msg in pending:
                try:
                    await handle(bot, accounts, msg, chat_id=uid)
                except Exception:
                    log.exception("补漏处理失败 msg=%s", msg.id)
                state.mark(uid, msg.id)

    names = []
    for client in accounts:
        me = await client.get_me()
        names.append(f"@{me.username}" if me.username else str(me.id))
    print(f"✅ 已启动，可用账号：{', '.join(names)}；服务 {len(allowed)} 个用户", flush=True)

    async def watchdog():
        """每 60 秒自检，连接假死就重连。"""
        stall = 0
        while True:
            await asyncio.sleep(60)
            try:
                for client in [bot, *accounts]:
                    await asyncio.wait_for(client.get_me(), 20)
                stall = 0
            except Exception as exc:
                stall += 1
                reason = str(exc) or type(exc).__name__
                log.warning("自检失败(%d)：%s", stall, reason)
                try:
                    for client in [bot, *accounts]:
                        if client.is_connected():
                            await client.disconnect()
                        await client.connect()
                    log.info("重连完成")
                except Exception:
                    log.exception("重连失败")
                if stall >= 5:
                    log.error("连续 5 次自检失败，退出让服务重启")
                    raise SystemExit(1)

    try:
        await asyncio.gather(
            bot.run_until_disconnected(),
            *[c.run_until_disconnected() for c in accounts],
            watchdog(),
            catch_up(),
        )
    finally:
        await bot.disconnect()
        for client in accounts:
            await client.disconnect()


if __name__ == "__main__":
    asyncio.run(main())
