"""把各种 Telegram 链接解析成 (对话, 消息ID)。"""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Optional
from urllib.parse import parse_qs, unquote, urlparse


@dataclass
class MsgLink:
    kind: str                      # username | channel_id | invite | unknown
    msg_id: Optional[int] = None
    username: Optional[str] = None
    channel_id: Optional[int] = None
    invite: Optional[str] = None
    thread_id: Optional[int] = None
    comment_id: Optional[int] = None   # 链接里第二段数字（评论楼层）
    raw: str = ""

    def describe(self) -> str:
        if self.kind == "username":
            return f"@{self.username}/{self.msg_id}"
        if self.kind == "channel_id":
            return f"c/{self.channel_id}/{self.msg_id}"
        if self.kind == "invite":
            return f"+{self.invite}/{self.msg_id}"
        return self.raw


_TME = re.compile(r"(?:https?://)?(?:www\.)?(?:t|telegram)\.me/([^\s]+)", re.I)
_TG = re.compile(r"tg://([^\s]+)", re.I)
_BARE = re.compile(r"^(?:@?[A-Za-z][A-Za-z0-9_]{3,31}/\d+|\d{5,}/\d+)$")


def parse(text: str) -> Optional[MsgLink]:
    """从任意文本里抽出第一个 Telegram 消息链接。"""
    if not text:
        return None
    text = text.strip()

    m = _TG.search(text)
    if m:
        parsed = _parse_tg(m.group(1))
        if parsed:
            return parsed

    m = _TME.search(text)
    if m:
        parsed = _parse_tme(m.group(1))
        if parsed:
            return parsed

    if _BARE.match(text):
        parsed = _parse_tme(text.lstrip("@"))
        if parsed:
            return parsed
    return None


def _parse_tg(payload: str) -> Optional[MsgLink]:
    # tg://openmessage?chat_id=-1001234&message_id=5
    # tg://privatepost?channel=1234&post=5
    # tg://resolve?domain=name&post=5
    if "?" not in payload:
        return None
    action, _, query = payload.partition("?")
    q = parse_qs(query)
    action = action.lower()

    def one(key: str) -> Optional[str]:
        vals = q.get(key)
        return vals[0] if vals else None

    if action == "openmessage":
        chat_id = one("chat_id")
        msg_id = one("message_id")
        if not chat_id or not msg_id:
            return None
        cid = int(chat_id)
        if cid < 0 and str(cid).startswith("-100"):
            return MsgLink(
                kind="channel_id",
                channel_id=int(str(cid)[4:]),
                msg_id=int(msg_id),
                thread_id=_int(one("thread")),
                raw=payload,
            )
        return MsgLink(kind="user", channel_id=cid, msg_id=int(msg_id), raw=payload)

    if action == "privatepost":
        chan = one("channel")
        post = one("post")
        if not chan or not post:
            return None
        return MsgLink(kind="channel_id", channel_id=int(chan), msg_id=int(post), raw=payload)

    if action == "resolve":
        domain = one("domain")
        post = one("post")
        if domain and post:
            return MsgLink(kind="username", username=domain, msg_id=int(post), raw=payload)
    return None


def _parse_tme(path: str) -> Optional[MsgLink]:
    path = unquote(path)
    query = ""
    if "?" in path:
        path, _, query = path.partition("?")
    path = path.strip("/")
    params = parse_qs(query) if query else {}
    thread_id = _int(params.get("thread", [None])[0])
    comment_id = _int(params.get("comment", [None])[0])

    parts = [p for p in path.split("/") if p]
    if not parts:
        return None

    # t.me/s/channel/123  (网页预览版)
    if parts[0] == "s" and len(parts) >= 3:
        parts = parts[1:]

    # t.me/c/1234567/89
    if parts[0] == "c" and len(parts) >= 3 and parts[1].isdigit() and parts[2].isdigit():
        comment = None
        if len(parts) >= 4 and parts[3].isdigit():
            comment = int(parts[3])
        return MsgLink(
            kind="channel_id",
            channel_id=int(parts[1]),
            msg_id=int(parts[2]),
            comment_id=comment,
            thread_id=thread_id,
            raw=path,
        )

    # t.me/+hash/12  或  t.me/joinchat/hash
    if parts[0].startswith("+"):
        return MsgLink(
            kind="invite",
            invite=parts[0][1:],
            msg_id=int(parts[1]) if len(parts) > 1 and parts[1].isdigit() else None,
            thread_id=thread_id,
            raw=path,
        )
    if parts[0] == "joinchat" and len(parts) >= 2:
        return MsgLink(
            kind="invite",
            invite=parts[1],
            msg_id=int(parts[2]) if len(parts) > 2 and parts[2].isdigit() else None,
            raw=path,
        )

    # t.me/username/123
    if len(parts) >= 2 and parts[1].isdigit():
        # t.me/频道/帖子/评论楼层 —— iOS 复制评论区消息会带两段数字
        comment = comment_id
        if len(parts) >= 3 and parts[2].isdigit():
            comment = int(parts[2])
        return MsgLink(
            kind="username",
            username=parts[0],
            msg_id=int(parts[1]),
            comment_id=comment,
            thread_id=thread_id,
            raw=path,
        )
    return None


def _int(value) -> Optional[int]:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None
