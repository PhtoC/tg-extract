"""导出/导入会话，方便把一台机器的登录态搬到服务器上。"""
from __future__ import annotations

import base64
import json
import sys

from telethon.sessions import SQLiteSession, StringSession

from . import config


def _session_string(path) -> str:
    sqlite = SQLiteSession(str(path.with_suffix("")))
    temp = StringSession()
    temp.set_dc(sqlite.dc_id, sqlite.server_address, sqlite.port)
    temp.auth_key = sqlite.auth_key
    sqlite.close()
    return temp.save()


def export() -> None:
    users = [_session_string(p) for p in config.session_paths()]
    blob = {"users": users}
    bot_path = config.DATA_DIR / "bot.session"
    if bot_path.exists():
        blob["bot"] = _session_string(bot_path)
    raw = json.dumps(blob, separators=(",", ":")).encode()
    print(base64.b64encode(raw).decode())


def import_blob(blob: str) -> None:
    config.ensure_dirs()
    data = json.loads(base64.b64decode(blob))
    for i, s in enumerate(data.get("users", []), start=1):
        name = "user" if i == 1 else f"user{i}"
        (config.DATA_DIR / f"{name}.session").write_text(s, encoding="utf-8")
    if data.get("bot"):
        (config.DATA_DIR / "bot.session").write_text(data["bot"], encoding="utf-8")
    print(f"已导入 {len(data.get('users', []))} 个账号会话")


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "import":
        import_blob(sys.stdin.read().strip())
    else:
        export()
