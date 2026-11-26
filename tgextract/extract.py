"""用你的账号解析链接、取消息、下载原始媒体。"""
from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Optional

from telethon import TelegramClient, types
from telethon.errors import RPCError

from . import links
from .config import TMP_DIR


class ExtractError(Exception):
    """可以直接展示给用户看的错误。"""


@dataclass
class Item:
    path: Path
    name: str
    size: int
    is_preview: bool = False
    kind: str = "file"          # photo | video | file


@dataclass
class Result:
    items: list[Item] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    source: str = ""
    caption: str = ""
    client: Optional[TelegramClient] = None
    comment_id: Optional[int] = None   # 实际取到媒体的楼层


async def resolve_entity(user: TelegramClient, link: links.MsgLink):
    if link.kind == "channel_id":
        try:
            return await user.get_entity(types.PeerChannel(link.channel_id))
        except Exception:
            pass
        # 直接在频道列表里查，比遍历全部对话快得多
        try:
            from telethon.tl.functions.channels import GetChannelsRequest

            res = await user(
                GetChannelsRequest([types.InputChannel(link.channel_id, 0)])
            )
            if res.chats:
                return res.chats[0]
        except Exception:
            pass
        try:
            dialogs = await asyncio.wait_for(_scan_dialogs(user, link.channel_id), 25)
            if dialogs is not None:
                return dialogs
        except asyncio.TimeoutError:
            pass
        raise ExtractError(
            "找不到这个群/频道。链接是 t.me/c/… 形式，说明是私密群，"
            "而你的账号似乎不在里面（或者已被踢出）。"
        )

    if link.kind == "username":
        try:
            return await user.get_entity(link.username)
        except Exception:
            raise ExtractError(f"找不到 @{link.username}，检查一下链接，或确认你已加入。")

    if link.kind == "invite":
        try:
            return await user.get_entity(link.invite)
        except Exception:
            try:
                from telethon.tl.functions.messages import CheckChatInviteRequest

                res = await user(CheckChatInviteRequest(link.invite))
                return getattr(res, "chat", None)
            except Exception:
                raise ExtractError("这个邀请链接解析失败（可能已过期，或需要先加入）。")

    if link.kind == "user":
        try:
            return await user.get_entity(link.channel_id)
        except Exception:
            raise ExtractError("找不到这个对话。")

    raise ExtractError("这不是一个能识别的 Telegram 消息链接。")


async def _scan_dialogs(user, channel_id: int):
    async for dialog in user.iter_dialogs():
        if getattr(dialog.entity, "id", None) == channel_id:
            return dialog.entity
    return None


def pick_media(msg) -> Optional[tuple[object, bool]]:
    """返回 (可下载对象, 是否只是模糊预览)。"""
    media = getattr(msg, "media", None)
    if media is None:
        return None

    if isinstance(media, types.MessageMediaPaidMedia):
        for em in media.extended_media:
            if isinstance(em, types.MessageExtendedMedia) and getattr(em, "media", None):
                return em.media, False
        for em in media.extended_media:
            if isinstance(em, types.MessageExtendedMediaPreview):
                return em, True
        return None

    if isinstance(media, types.MessageMediaWebPage):
        if getattr(media, "photo", None):
            return media.photo, False
        if getattr(media, "document", None):
            return media.document, False
        return None

    return media, False


def _guess_kind(media) -> str:
    if isinstance(media, types.MessageMediaPhoto):
        return "photo"
    if isinstance(media, types.MessageMediaDocument):
        doc = getattr(media, "document", None)
        for attr in getattr(doc, "attributes", []) or []:
            if isinstance(attr, types.DocumentAttributeVideo):
                return "video"
            if isinstance(attr, types.DocumentAttributeAudio):
                return "file"
        return "file"
    return "file"


def _file_name(msg, media, fallback: str) -> str:
    doc = getattr(media, "document", None)
    if doc is not None:
        for attr in getattr(doc, "attributes", []) or []:
            name = getattr(attr, "file_name", None)
            if name:
                return name
    name = getattr(getattr(msg, "file", None), "name", None)
    if name:
        return name
    return fallback


async def collect_messages(user: TelegramClient, entity, msg_id: int, with_album: bool = True) -> list:
    try:
        msg = await user.get_messages(entity, ids=msg_id)
    except RPCError as exc:
        raise ExtractError(f"读取消息失败：{exc.__class__.__name__}")
    if not msg:
        raise ExtractError("这条消息不存在，或者你的账号看不到它。")

    msgs = [msg]
    grouped = getattr(msg, "grouped_id", None)
    if with_album and grouped:
        try:
            ids = [i for i in range(max(1, msg_id - 9), msg_id + 10) if i != msg_id]
            around = await user.get_messages(entity, ids=ids)
            for other in around or []:
                if other and getattr(other, "grouped_id", None) == grouped:
                    msgs.append(other)
            msgs.sort(key=lambda m: m.id)
        except Exception:
            pass
    return msgs


async def download_all(
    user: TelegramClient,
    entity,
    msg_id: int,
    progress: Optional[Callable[[int, int], None]] = None,
    with_album: bool = True,
) -> Result:
    msgs = await collect_messages(user, entity, msg_id, with_album)
    result = Result(source=str(msg_id), client=user)
    first = msgs[0]
    result.caption = (getattr(first, "message", None) or "").strip()

    for msg in msgs:
        picked = pick_media(msg)
        if not picked:
            if msg is first:
                raise ExtractError("这条消息里没有图片/视频/文件。")
            continue

        media, is_preview = picked
        kind = _guess_kind(media) if not is_preview else "photo"
        default_ext = {"photo": ".jpg", "video": ".mp4"}.get(kind, ".bin")
        name = _file_name(msg, media, f"{msg.id}{default_ext}")
        target = TMP_DIR / f"{msg.id}_{int(time.time() * 1000)}_{name}"
        target.parent.mkdir(parents=True, exist_ok=True)

        try:
            if is_preview:
                thumb = getattr(media, "thumb", None)
                got = await user.download_media(thumb, file=str(target)) if thumb else None
            else:
                got = await user.download_media(
                    media, file=str(target), progress_callback=progress
                )
        except Exception:
            got = None

        if not got:
            if msg is first:
                raise ExtractError("下载失败：可能文件已被删除，或超出你账号的下载权限。")
            continue

        path = Path(got)
        if not path.exists():
            continue

        result.items.append(
            Item(
                path=path,
                name=name,
                size=path.stat().st_size,
                is_preview=is_preview,
                kind=kind,
            )
        )
        if is_preview:
            result.warnings.append(
                "这条是付费/受限媒体，你的账号还没解锁，只能拿到模糊预览版。"
            )

    if not result.items:
        raise ExtractError("没取到任何媒体。")
    return result


async def _comment_target(user: TelegramClient, entity):
    """讨论组里的评论要跑到关联群去找。"""
    try:
        from telethon.tl.functions.channels import GetFullChannelRequest

        full = await user(GetFullChannelRequest(entity))
        linked = getattr(full.full_chat, "linked_chat_id", None)
        if linked:
            return await user.get_entity(types.PeerChannel(linked))
    except Exception:
        pass
    return None


async def fetch(accounts: list[TelegramClient], link: links.MsgLink, **kwargs) -> Result:
    """按顺序尝试每个账号，用第一个能看到这个对话的。"""
    if not link.msg_id:
        raise ExtractError("链接里没有消息编号（…/123 结尾的那部分）。")

    resolve_errors: list[str] = []
    content_errors: list[str] = []

    for user in accounts:
        try:
            entity = await resolve_entity(user, link)
        except ExtractError as exc:
            resolve_errors.append(str(exc))
            continue
        if entity is None:
            continue

        # 先走关联的讨论组（评论区链接的楼层在那里），再回到原对话
        targets: list[tuple[object, list[int]]] = []
        if link.comment_id:
            discussion = await _comment_target(user, entity)
            if discussion is not None:
                targets.append((discussion, [link.comment_id]))
        own_ids = [link.msg_id]
        if link.comment_id and link.comment_id != link.msg_id:
            own_ids.append(link.comment_id)
        targets.append((entity, own_ids))

        for target, ids in targets:
            for mid in ids:
                try:
                    result = await download_all(user, target, mid, **kwargs)
                    result.comment_id = mid
                    return result
                except ExtractError as exc:
                    content_errors.append(str(exc))
                    continue

    # 有过"能看到群但取不到内容"的记录，优先报它，比"找不到群"准确
    if content_errors:
        raise ExtractError(content_errors[0])
    if resolve_errors:
        raise ExtractError(resolve_errors[0])
    raise ExtractError("解析不到这个对话。")
