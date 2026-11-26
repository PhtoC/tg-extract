"""记录每个对话处理到哪条消息，关机/断网后能补上漏掉的链接。"""
from __future__ import annotations

import json
import os

from . import config

STATE_FILE = config.DATA_DIR / "state.json"


def _load() -> dict:
    try:
        if STATE_FILE.exists():
            return json.loads(STATE_FILE.read_text(encoding="utf-8"))
    except Exception:
        pass
    return {}


def last_id(chat_id: int) -> int:
    return int(_load().get(str(chat_id), 0))


def mark(chat_id: int, message_id: int) -> None:
    data = _load()
    if int(data.get(str(chat_id), 0)) >= message_id:
        return
    data[str(chat_id)] = message_id
    tmp = STATE_FILE.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(data), encoding="utf-8")
    os.replace(tmp, STATE_FILE)
