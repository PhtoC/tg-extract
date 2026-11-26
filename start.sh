#!/usr/bin/env bash
# 用法：
#   ./start.sh          启动 bot（没登录过会先走登录）
#   ./start.sh add      扫码添加一个账号
#   ./start.sh add-phone 用手机号添加一个账号
set -euo pipefail
cd "$(dirname "$0")"

export PATH="$HOME/.local/bin:/opt/homebrew/bin:/usr/local/bin:$PATH"

if ! command -v uv >/dev/null 2>&1; then
  echo "第一次运行，正在安装运行环境（约 1 分钟）..."
  curl -LsSf https://astral.sh/uv/install.sh | sh
  export PATH="$HOME/.local/bin:$PATH"
fi

echo "检查依赖..."
uv sync --quiet

case "${1:-}" in
  add)
    exec uv run python -m tgextract.login add
    ;;
  add-phone)
    exec uv run python -m tgextract.login add --phone
    ;;
esac

if ! uv run python -m tgextract.status >/dev/null 2>&1; then
  echo
  uv run python -m tgextract.login
fi

echo
echo "启动 bot（关掉这个窗口 bot 就停了）..."
exec uv run python -m tgextract.bot
