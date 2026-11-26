#!/usr/bin/env bash
# 在 Mac 上执行：把项目打包并传到服务器
# 用法：./deploy/push.sh <服务器IP>
set -euo pipefail
cd "$(dirname "$0")/.."

IP="${1:?用法: ./deploy/push.sh <服务器IP>}"

echo "== 刷新会话串 =="
./.venv/bin/python -m tgextract.sessions > deploy/sessions.txt

echo "== 打包 =="
tar czf /tmp/tgx.tgz \
  --exclude='.venv' --exclude='data' --exclude='__pycache__' \
  --exclude='*.session' --exclude='.git' \
  tgextract deploy pyproject.toml

echo "== 上传到 $IP =="
scp -i deploy/oracle_key -o StrictHostKeyChecking=no -o ConnectTimeout=20 \
  /tmp/tgx.tgz "ubuntu@$IP:/tmp/tgx.tgz"

echo "== 远端解包并安装 =="
ssh -i deploy/oracle_key -o StrictHostKeyChecking=no -o ConnectTimeout=20 "ubuntu@$IP" \
  "sudo mkdir -p /opt/tg-extract && sudo chown ubuntu:ubuntu /opt/tg-extract && \
   tar xzf /tmp/tgx.tgz -C /opt/tg-extract && cd /opt/tg-extract && chmod +x deploy/install.sh && ./deploy/install.sh"

echo "== 部署结束 =="
