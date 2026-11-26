"""本地存档：取过的文件按链接指纹归档，群没了也能重新发。"""
from __future__ import annotations

import hashlib
import json
import os
import time
from pathlib import Path
from typing import Optional

from . import config
from .links import MsgLink


def link_key(link: MsgLink) -> str:
    """同一条消息永远得到同一个 key，无论哪个号、哪个楼层取的。"""
    if link.kind == "username":
        base = f"u:{(link.username or '').lower()}:{link.msg_id}"
    elif link.kind == "channel_id":
        base = f"c:{link.channel_id}:{link.msg_id}"
    elif link.kind == "invite":
        base = f"i:{link.invite}:{link.msg_id}"
    else:
        base = f"?:{link.raw}"
    return hashlib.sha1(base.encode()).hexdigest()[:16]


class Archive:
    def __init__(self) -> None:
        self._data: dict[str, dict] = {}
        self._load()

    def _load(self) -> None:
        try:
            if config.ARCHIVE_INDEX.exists():
                self._data = json.loads(config.ARCHIVE_INDEX.read_text(encoding="utf-8"))
        except Exception:
            self._data = {}

    def _save(self) -> None:
        tmp = config.ARCHIVE_INDEX.with_suffix(".json.tmp")
        tmp.write_text(
            json.dumps(self._data, ensure_ascii=False, indent=1), encoding="utf-8"
        )
        os.replace(tmp, config.ARCHIVE_INDEX)

    def get(self, link: MsgLink) -> Optional[list[Path]]:
        entry = self._data.get(link_key(link))
        if not entry:
            return None
        paths = []
        for item in entry.get("items", []):
            p = Path(item["path"])
            if p.exists():
                paths.append(p)
        entry["items"] = [
            i for i in entry.get("items", []) if Path(i["path"]).exists()
        ]
        return paths or None

    def describe(self, link: MsgLink) -> Optional[str]:
        entry = self._data.get(link_key(link))
        if not entry:
            return None
        when = time.strftime("%Y-%m-%d %H:%M", time.localtime(entry.get("ts", 0)))
        names = [Path(i["path"]).name for i in entry.get("items", [])]
        return f"{when} 存档，{len(names)} 个文件：{', '.join(names[:3])}{'…' if len(names) > 3 else ''}"

    def put(self, link: MsgLink, items: list) -> None:
        entry = {
            "ts": int(time.time()),
            "describe": link.describe(),
            "items": [
                {"path": str(i.path), "name": i.name, "size": i.size}
                for i in items
            ],
        }
        # 把文件从 tmp 挪进 archive
        dest_dir = config.ARCHIVE_DIR / link_key(link)
        dest_dir.mkdir(parents=True, exist_ok=True)
        saved = []
        for i in items:
            dest = dest_dir / i.path.name
            try:
                os.replace(i.path, dest)
            except OSError:
                import shutil

                shutil.copy2(i.path, dest)
            saved.append({"path": str(dest), "name": i.name, "size": i.size})
        entry["items"] = saved
        self._data[link_key(link)] = entry
        self._save()


archive = Archive()
