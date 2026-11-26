#!/usr/bin/env bash
# 在服务器上一次性装好 bot（systemd 常驻 + 开机自启）
set -euo pipefail
cd "$(dirname "$0")"

echo "== 安装系统依赖 =="
sudo apt-get update -qq
sudo apt-get install -y -qq python3-venv python3-pip ffmpeg unzip curl >/dev/null

echo "== 创建虚拟环境 =="
python3 -m venv .venv
./.venv/bin/pip install -q --upgrade pip
./.venv/bin/pip install -q telethon qrcode

echo "== 写入配置 =="
cp deploy/env.server .env
chmod 600 .env

echo "== 导入会话 =="
if [ -f deploy/sessions.txt ]; then
  ./.venv/bin/python -m tgextract.sessions import < deploy/sessions.txt
fi

echo "== 注册 systemd 服务 =="
sudo cp deploy/tg-extract.service /etc/systemd/system/tg-extract.service
sudo systemctl daemon-reload
sudo systemctl enable --now tg-extract

sleep 5
sudo systemctl --no-pager status tg-extract | head -20 || true
echo
echo "== 完成，日志： sudo journalctl -u tg-extract -f =="
