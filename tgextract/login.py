"""一次性登录向导：写 .env、登录你的账号、记录允许使用的人。"""
from __future__ import annotations

import asyncio
import getpass
import os
import re
import sys

from telethon import TelegramClient
from telethon.errors import (
    ApiIdInvalidError,
    FloodWaitError,
    PhoneCodeEmptyError,
    PhoneCodeExpiredError,
    PhoneCodeInvalidError,
    SessionPasswordNeededError,
)

from . import config

HEX32 = re.compile(r"^[0-9a-f]{32}$")


def ask(prompt: str, default: str = "") -> str:
    suffix = f" [{default}]" if default else ""
    while True:
        value = input(f"{prompt}{suffix}: ").strip()
        if value:
            return value
        if default:
            return default
        print("  这一项不能空。")


def ask_api_id(default: str = "") -> str:
    while True:
        value = ask("API_ID（纯数字）", default).replace(" ", "")
        if value.isdigit() and 4 <= len(value) <= 12:
            return value
        print("  API_ID 只能是一串数字，重新填。")


def ask_api_hash(default: str = "") -> str:
    default = re.sub(r"\s+", "", default).lower()
    if not HEX32.match(default):
        default = ""
    while True:
        value = ask("API_HASH（32 位字母数字）", default)
        value = re.sub(r"\s+", "", value).lower()
        if HEX32.match(value):
            return value
        print(f"  格式不对：应该是 32 位，你现在填了 {len(value)} 位。重新粘贴。")


def normalize_phone(raw: str) -> str | None:
    """把各种写法统一成 +8613800138000。认不出来返回 None。"""
    s = re.sub(r"[\s\-()]", "", raw or "")
    if not s:
        return None
    if s.startswith("+"):
        digits = re.sub(r"\D", "", s)
        return "+" + digits if 8 <= len(digits) <= 15 else None

    digits = re.sub(r"\D", "", s)
    if not digits:
        return None
    # 中国大陆手机号：1 开头的 11 位
    if len(digits) == 11 and digits.startswith("1"):
        return "+86" + digits
    # 86 开头的 13 位
    if len(digits) == 13 and digits.startswith("86"):
        return "+" + digits
    # 日本：090/080/070 开头的 11 位，去掉开头的 0
    if len(digits) in (10, 11) and digits.startswith("0"):
        return "+81" + digits.lstrip("0")
    # 81 开头的 12~13 位
    if len(digits) in (12, 13) and digits.startswith("81"):
        return "+" + digits
    # 其它：默认已经带了国家码
    if 10 <= len(digits) <= 15:
        return "+" + digits
    return None


def print_qr(url: str) -> None:
    import qrcode

    qr = qrcode.QRCode(border=2)
    qr.add_data(url)
    qr.make(fit=True)
    qr.print_ascii(invert=True)


async def qr_login(client: TelegramClient) -> None:
    """扫码登录，不收短信，适合 +86。"""
    await client.connect()
    if await client.is_user_authorized():
        print("这个会话已经登录过了。")
        return

    print()
    print("=" * 52)
    print("在手机上用**要登录的那个账号**这样操作：")
    print("  1. Telegram → 设置")
    print("  2. 点「设备」（Devices）")
    print("  3. 点「关联桌面设备 / Link Desktop Device」")
    print("  4. 对着下面的二维码扫")
    print("=" * 52)
    print()

    for _ in range(10):
        qr = await client.qr_login()
        print_qr(qr.url)
        print("（十几秒后自动换一张，正常现象；期间扫任意一张都行。）")
        print()
        try:
            await qr.wait()
            print("✅ 扫码成功")
            return
        except asyncio.TimeoutError:
            continue
        except SessionPasswordNeededError:
            password = getpass.getpass("两步验证密码（输入时不显示）: ")
            await client.sign_in(password=password)
            print("✅ 登录成功")
            return
    raise SystemExit("扫了好几次都没成功，重跑一次试试。")


async def interactive_login(client: TelegramClient) -> None:
    """自己控制发码流程：可以重发、可以改走短信。"""
    await client.connect()
    if await client.is_user_authorized():
        return

    print("你的手机号。国内号码直接输 13800138000 就行，会自动补 +86。")
    while True:
        phone = normalize_phone(ask("手机号"))
        if phone:
            break
        print("  号码认不出来，重新输。")
    print(f"  → 将发送到 {phone}")

    try:
        sent = await client.send_code_request(phone)
    except FloodWaitError as exc:
        raise SystemExit(
            f"请求太频繁了，Telegram 要求等 {exc.seconds} 秒。等完重新跑 ./start.sh。"
        )
    print()
    print(f"  Telegram 说：{describe_sent_type(sent)}")
    print()
    print("=" * 52)
    print("验证码已经发出，但注意：")
    print("  它默认发到 Telegram App 里，不是短信！")
    print("  打开手机 Telegram，找那个叫「Telegram」的官方对话，")
    print("  里面会有一条「Login code: 12345」。")
    print("=" * 52)
    print()

    for _ in range(8):
        raw = input("验证码（r=重发  s=改用短信  q=退出）: ").strip()
        low = raw.lower()
        if low == "q":
            raise SystemExit("已退出。")
        if low in ("r", "s"):
            try:
                sent = await client.send_code_request(phone, force_sms=(low == "s"))
            except FloodWaitError as exc:
                print(f"  发太频繁了，等 {exc.seconds} 秒再试。")
                continue
            print(f"  已重发。{describe_sent_type(sent)}")
            continue

        code = re.sub(r"\D", "", raw)
        if not code:
            continue
        try:
            await client.sign_in(phone=phone, code=code, phone_code_hash=sent.phone_code_hash)
            break
        except SessionPasswordNeededError:
            password = getpass.getpass("两步验证密码（输入时不显示）: ")
            await client.sign_in(password=password)
            break
        except PhoneCodeExpiredError:
            print("  这个码过期了，重发一个。")
            sent = await client.send_code_request(phone)
        except (PhoneCodeInvalidError, PhoneCodeEmptyError):
            print("  验证码不对，再试一次。")
        except FloodWaitError as exc:
            print(f"  试太多次了，等 {exc.seconds} 秒。")
    else:
        raise SystemExit("验证码试了太多次，重新跑一次 ./start.sh。")


def describe_sent_type(sent) -> str:
    """用类名判断，避开 Telethon 各版本路径不一致的坑。"""
    name = type(getattr(sent, "type", None)).__name__
    table = {
        "SentCodeTypeApp": "发到 Telegram App 内部了（不是短信）",
        "SentCodeTypeSms": "发短信了",
        "SentCodeTypeCall": "会给你打电话报验证码",
        "SentCodeTypeFlashCall": "会闪断一下电话，号码就是验证码",
        "SentCodeTypeMissedCall": "会给你一个未接来电，号码里带验证码",
        "SentCodeTypeFragmentSms": "通过 Fragment 短信发送",
        "SentCodeTypeFirebaseSms": "走 Firebase 短信通道",
        "SentCodeTypeSmsWord": "短信里只发一个单词，需要再确认",
        "SentCodeTypeSmsPhrase": "短信里发一句话",
        "SentCodeTypeSetUpEmailRequired": "要求先绑定邮箱",
        "SentCodeTypeEmailCode": "发到邮箱了",
    }
    return table.get(name, f"未知方式 {name}")


def mask(value: str) -> str:
    if len(value) <= 8:
        return value[:2] + "***"
    return f"{value[:4]}...{value[-4:]}"


def write_env(values: dict[str, str]) -> None:
    lines = [
        "# 自动生成，改完重启即可",
        f"API_ID={values.get('API_ID', '')}",
        f"API_HASH={values.get('API_HASH', '')}",
        f"BOT_TOKEN={values.get('BOT_TOKEN', '')}",
        f"ALLOWED_USER_IDS={values.get('ALLOWED_USER_IDS', '')}",
        f"BOT_MAX_MB={values.get('BOT_MAX_MB', '50')}",
        "KEEP_FILES=0",
        "",
    ]
    config.ENV_FILE.write_text("\n".join(lines), encoding="utf-8")
    os.chmod(config.ENV_FILE, 0o600)


def collect(defaults: dict[str, str] | None = None) -> dict[str, str]:
    defaults = defaults or {}
    print("下面三项在 my.telegram.org 和 @BotFather 拿，README 里有说明。")
    if defaults:
        print("方括号里是上次填的值，直接回车就沿用。")
    print()
    values = {
        "API_ID": ask_api_id(defaults.get("API_ID", "")),
        "API_HASH": ask_api_hash(defaults.get("API_HASH", "")),
        "BOT_TOKEN": ask("BOT_TOKEN", defaults.get("BOT_TOKEN", "")),
        "BOT_MAX_MB": defaults.get("BOT_MAX_MB", "50"),
        "ALLOWED_USER_IDS": defaults.get("ALLOWED_USER_IDS", ""),
    }
    print()
    print(f"  收到：api_id={values['API_ID']}  api_hash={mask(values['API_HASH'])}")
    print(f"        bot_token={mask(values['BOT_TOKEN'])}")
    return values


async def login_loop(defaults: dict[str, str] | None = None) -> None:
    for attempt in range(1, 4):
        values = collect(defaults)
        write_env(values)
        config.load_env()

        client = TelegramClient(str(config.DATA_DIR / "user"), int(values["API_ID"]), values["API_HASH"])
        print()
        print("接下来登录你的 Telegram 账号（验证码会发到 Telegram 里）。")
        print()
        try:
            await interactive_login(client)
        except ApiIdInvalidError:
            await client.disconnect()
            session_file = config.DATA_DIR / "user.session"
            if session_file.exists():
                session_file.unlink()
            print()
            print("=" * 52)
            print("❌ api_id / api_hash 对不上（Telegram 拒绝了）。")
            print("   常见原因：少复制了几位、多了空格、两个填反了、")
            print("   或者填的是另一个 App 的值。")
            print("   回到 my.telegram.org → API development tools 重新复制一遍。")
            print("=" * 52)
            print()
            if attempt == 3:
                raise SystemExit("连续 3 次失败，先把这两个值核对好再跑一次。")
            defaults = values
            print()
            continue

        me = await client.get_me()
        allowed = {a.strip() for a in values.get("ALLOWED_USER_IDS", "").split(",") if a.strip()}
        allowed.add(str(me.id))
        values["ALLOWED_USER_IDS"] = ",".join(sorted(allowed))
        write_env(values)
        await client.disconnect()

        print()
        print("=" * 52)
        print(f"登录成功：{me.first_name or ''} (@{getattr(me, 'username', '无用户名')})")
        print(f"你的 user id：{me.id}（只有这个 id 能用 bot）")
        print("=" * 52)
        print()
        print("现在运行 ./start.sh 启动 bot。")
        return


async def main() -> None:
    config.ensure_dirs()
    print("=" * 52)
    print(" Telegram 媒体提取 bot — 首次设置")
    print("=" * 52)
    print()

    if config.ENV_FILE.exists():
        print(f"发现已有配置：{config.ENV_FILE}")
        again = input("要重新填写 api_id / api_hash / token 吗？(Y/n): ").strip().lower()
        print()
        if again in ("n", "no"):
            values = {
                "API_ID": config.get("API_ID"),
                "API_HASH": config.get("API_HASH"),
                "BOT_TOKEN": config.get("BOT_TOKEN"),
                "ALLOWED_USER_IDS": config.get("ALLOWED_USER_IDS"),
                "BOT_MAX_MB": config.get("BOT_MAX_MB", "50"),
            }
            client = TelegramClient(
                str(config.DATA_DIR / "user"), int(values["API_ID"]), values["API_HASH"]
            )
            await interactive_login(client)
            me = await client.get_me()
            allowed = {a.strip() for a in values["ALLOWED_USER_IDS"].split(",") if a.strip()}
            allowed.add(str(me.id))
            values["ALLOWED_USER_IDS"] = ",".join(sorted(allowed))
            write_env(values)
            await client.disconnect()
            print(f"登录成功：{me.first_name or ''}，id={me.id}")
            return

    existing = {k: config.get(k) for k in ("API_ID", "API_HASH", "BOT_TOKEN", "ALLOWED_USER_IDS")}
    await login_loop(existing)


async def add_account(use_qr: bool) -> None:
    """追加一个账号会话，供 bot 在对应群组里使用。"""
    config.ensure_dirs()
    api_id = config.get_int("API_ID")
    api_hash = config.get("API_HASH")
    if not api_id or not api_hash:
        raise SystemExit("还没有 .env，先跑一次 ./start.sh")

    path = config.next_session_path()
    label = path.stem
    print("=" * 52)
    print(f" 添加账号（会话名：{label}）")
    print("=" * 52)
    print()

    client = TelegramClient(str(path.with_suffix("")), api_id, api_hash)
    if use_qr:
        await qr_login(client)
    else:
        await interactive_login(client)

    me = await client.get_me()
    values = {
        "API_ID": str(api_id),
        "API_HASH": api_hash,
        "BOT_TOKEN": config.get("BOT_TOKEN"),
        "ALLOWED_USER_IDS": config.get("ALLOWED_USER_IDS"),
        "BOT_MAX_MB": config.get("BOT_MAX_MB", "50"),
    }
    allowed = {a.strip() for a in (values["ALLOWED_USER_IDS"] or "").split(",") if a.strip()}
    allowed.add(str(me.id))
    values["ALLOWED_USER_IDS"] = ",".join(sorted(allowed))
    write_env(values)
    await client.disconnect()

    print()
    print("=" * 52)
    print(f"✅ 已添加账号：{me.first_name or ''} (@{getattr(me, 'username', '无用户名')}) id={me.id}")
    print("   已同时加入白名单。重启 bot 生效。")
    print("=" * 52)


def run_add() -> None:
    use_qr = "--phone" not in sys.argv
    asyncio.run(add_account(use_qr))


if __name__ == "__main__":
    try:
        if "add" in sys.argv[1:]:
            run_add()
        else:
            asyncio.run(main())
    except KeyboardInterrupt:
        print("\n已取消。")
        sys.exit(1)
