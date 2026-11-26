"""压缩包自动解压：把 zip 里的媒体展开成可发送的条目。支持加密 zip。"""
from __future__ import annotations

import asyncio
from pathlib import Path

import pyzipper

from . import config
from .extract import Item

PHOTO_EXT = {".jpg", ".jpeg", ".png", ".webp", ".gif", ".bmp", ".heic"}
VIDEO_EXT = {".mp4", ".m4v", ".mkv", ".avi", ".mov", ".webm", ".ts", ".flv", ".wmv"}
ARCHIVE_EXT = {".zip"}

MAX_FILES = 300
MAX_TOTAL = 4 * 1024 * 1024 * 1024
MAX_DEPTH = 2

# 常见密码，先自动试
BUILTIN_PASSWORDS = [
    "",
    "666666",
    "888888",
    "6666",
    "8888",
    "1234",
    "123456",
    "12345678",
    "0000",
    "1111",
    "9999",
    "123",
    "520",
    "1314",
    "tg",
    "t.me",
    "telegram",
]


class NeedPassword(Exception):
    """压缩包加密且已知密码都不对。"""


def is_archive(path: Path) -> bool:
    return path.suffix.lower() in ARCHIVE_EXT


def is_video(path: Path) -> bool:
    return path.suffix.lower() in VIDEO_EXT


def kind_of(path: Path) -> str:
    ext = path.suffix.lower()
    if ext in PHOTO_EXT:
        return "photo"
    if ext in VIDEO_EXT:
        return "video"
    return "file"


def _candidates() -> list[str]:
    extra = [p.strip() for p in config.get("ZIP_PASSWORDS", "").split(",") if p.strip()]
    out = []
    for pw in extra + BUILTIN_PASSWORDS:
        if pw not in out:
            out.append(pw)
    return out


def _extract(zip_path: Path, dest: Path) -> list[Path]:
    out: list[Path] = []
    total = 0
    passwords = _candidates()

    with pyzipper.AESZipFile(zip_path) as zf:
        infos = [i for i in zf.infolist() if not i.is_dir() and not i.filename.startswith("__MACOSX/")]
        if not infos:
            return []

        encrypted = bool(infos[0].flag_bits & 0x1)
        password = ""
        if encrypted:
            password = ""
            for candidate in passwords:
                try:
                    with zf.open(infos[0], pwd=candidate.encode()) as f:
                        f.read(16)
                    password = candidate
                    break
                except Exception:
                    continue
            else:
                raise NeedPassword()

        for info in infos:
            if len(out) >= MAX_FILES or total > MAX_TOTAL:
                break
            name = info.filename
            target = (dest / name).resolve()
            if not str(target).startswith(str(dest.resolve())):
                continue  # zip slip 防护
            target.parent.mkdir(parents=True, exist_ok=True)
            try:
                with zf.open(info, pwd=password.encode()) as src, open(target, "wb") as dst:
                    while True:
                        chunk = src.read(1 << 20)
                        if not chunk:
                            break
                        dst.write(chunk)
            except Exception:
                target.unlink(missing_ok=True)
                continue
            total += target.stat().st_size
            out.append(target)
    return out


async def expand(items: list[Item], depth: int = 0) -> tuple[list[Item], list[str]]:
    """解压 items 里的压缩包；返回 (展开后的条目, 提示语)。"""
    notes: list[str] = []
    result: list[Item] = []
    for item in items:
        if not is_archive(item.path):
            result.append(item)
            continue

        dest = item.path.parent / f"{item.path.stem}_unzip"
        dest.mkdir(parents=True, exist_ok=True)
        try:
            files = await asyncio.to_thread(_extract, item.path, dest)
        except NeedPassword:
            notes.append(f"🔒 {item.name} 有密码，发 /pwd 密码 告诉我一次")
            result.append(item)
            continue
        except Exception:
            notes.append(f"⚠️ {item.name} 解压失败")
            result.append(item)
            continue

        if not files:
            notes.append(f"⚠️ {item.name} 里没有能提取的文件")
            result.append(item)
            continue

        nested = [
            Item(path=f, name=f.name, size=f.stat().st_size, kind=kind_of(f))
            for f in files
        ]
        if depth < MAX_DEPTH and any(is_archive(i.path) for i in nested):
            nested, more = await expand(nested, depth + 1)
            notes.extend(more)
        result.extend(nested)
        item.path.unlink(missing_ok=True)

    result.sort(key=lambda i: (i.kind == "file", i.name.lower()))
    return result, notes


async def list_entries(zip_path: Path) -> list:
    """只读目录，不解压。用来先算出总数。"""

    def _list():
        try:
            with pyzipper.AESZipFile(zip_path) as zf:
                return [
                    i for i in zf.infolist()
                    if not i.is_dir()
                    and not i.filename.startswith("__MACOSX/")
                    and "/." not in i.filename
                ]
        except Exception:
            return []

    return await asyncio.to_thread(_list)


async def extract_one(zip_path: Path, info, dest: Path) -> Path | None:
    """解压单个条目，成功返回路径。密码在内部自动尝试。"""

    def _one():
        try:
            with pyzipper.AESZipFile(zip_path) as zf:
                password = b""
                if info.flag_bits & 0x1:
                    for candidate in _candidates():
                        try:
                            with zf.open(info, pwd=candidate.encode()) as f:
                                f.read(16)
                            password = candidate.encode()
                            break
                        except Exception:
                            continue
                    else:
                        raise NeedPassword()
                target = (dest / info.filename).resolve()
                if not str(target).startswith(str(dest.resolve())):
                    return None
                target.parent.mkdir(parents=True, exist_ok=True)
                with zf.open(info, pwd=password) as src, open(target, "wb") as dst:
                    while True:
                        chunk = src.read(1 << 20)
                        if not chunk:
                            break
                        dst.write(chunk)
                return target
        except NeedPassword:
            raise
        except Exception:
            return None

    return await asyncio.to_thread(_one)
