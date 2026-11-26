"""读取 .env 配置。不依赖第三方库。"""
from __future__ import annotations

import os
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
ENV_FILE = ROOT / ".env"
DATA_DIR = Path(os.environ.get("TGX_DATA_DIR") or (ROOT / "data"))
TMP_DIR = DATA_DIR / "tmp"
ARCHIVE_DIR = DATA_DIR / "archive"
ARCHIVE_INDEX = DATA_DIR / "archive.json"


def load_env(path: Path = ENV_FILE) -> None:
    if not path.exists():
        return
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        os.environ.setdefault(key, value)


def get(name: str, default: str = "") -> str:
    return os.environ.get(name, default)


def get_int(name: str, default: int = 0) -> int:
    try:
        return int(str(os.environ.get(name, "")).strip())
    except (TypeError, ValueError):
        return default


def allowed_user_ids() -> set[int]:
    raw = os.environ.get("ALLOWED_USER_IDS", "")
    out: set[int] = set()
    for part in raw.replace(";", ",").split(","):
        part = part.strip()
        if part.lstrip("-").isdigit():
            out.add(int(part))
    return out


def task_timeout() -> int:
    """单个链接的硬上限（秒），再慢也不能超过。"""
    return get_int("TASK_TIMEOUT", 1800)


def stall_timeout() -> int:
    """多久没有任何进展就算卡住（秒）。"""
    return get_int("STALL_TIMEOUT", 60)


def bot_max_bytes() -> int:
    """Bot API 直传上限，默认 50MB。"""
    return get_int("BOT_MAX_MB", 50) * 1024 * 1024


def ensure_dirs() -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    TMP_DIR.mkdir(parents=True, exist_ok=True)
    ARCHIVE_DIR.mkdir(parents=True, exist_ok=True)


def session_paths() -> list[Path]:
    """所有已存在的账号会话，主账号（user）排在最前面。"""
    found = [p for p in DATA_DIR.glob("user*.session") if p.exists()]
    found.sort(key=lambda p: (p.stem != "user", p.stem))
    return found


def next_session_path() -> Path:
    """找一个还没被占用的会话文件名。"""
    first = DATA_DIR / "user.session"
    if not first.exists():
        return first
    i = 2
    while (DATA_DIR / f"user{i}.session").exists():
        i += 1
    return DATA_DIR / f"user{i}.session"


load_env()


def set_env(key: str, value: str) -> None:
    """改写 .env 里的某一项（保留其它内容）。"""
    lines = []
    if ENV_FILE.exists():
        lines = ENV_FILE.read_text(encoding="utf-8").splitlines()
    out, done = [], False
    for line in lines:
        if line.startswith(f"{key}="):
            out.append(f"{key}={value}")
            done = True
        else:
            out.append(line)
    if not done:
        out.append(f"{key}={value}")
    ENV_FILE.write_text("\n".join(out) + "\n", encoding="utf-8")
    os.environ[key] = value
