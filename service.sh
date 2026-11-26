#!/usr/bin/env bash
# 后台服务管理（macOS launchd）
#   ./service.sh install   安装并启动（开机自启，崩溃自动拉起）
#   ./service.sh stop      停止
#   ./service.sh start     启动
#   ./service.sh status    看状态
#   ./service.sh logs      看最近日志
#   ./service.sh uninstall 卸载
set -euo pipefail
cd "$(dirname "$0")"

PLIST_NAME="local.telegram-extract"
PLIST_SRC="$PWD/$PLIST_NAME.plist"
PLIST_DST="$HOME/Library/LaunchAgents/$PLIST_NAME.plist"
SERVICE_LOG="data/service.log"

install() {
  mkdir -p "$HOME/Library/LaunchAgents"
  cp "$PLIST_SRC" "$PLIST_DST"
  # 先停掉手动跑的实例，避免两个 bot 抢消息
  pkill -f "tgextract.bot" 2>/dev/null || true
  sleep 1
  launchctl unload "$PLIST_DST" 2>/dev/null || true
  launchctl load "$PLIST_DST"
  echo "✅ 已安装并启动。以后开机自动运行，终端可以关了。"
  echo "   看日志：./service.sh logs"
  sleep 2
  status
}

stop() {
  launchctl unload "$PLIST_DST" 2>/dev/null || true
  pkill -f "tgextract.bot" 2>/dev/null || true
  echo "⏹ 已停止"
}

start() {
  [ -f "$PLIST_DST" ] || { echo "还没安装，先 ./service.sh install"; exit 1; }
  launchctl load "$PLIST_DST"
  echo "▶️ 已启动"
}

status() {
  if pgrep -f "tgextract.bot" >/dev/null; then
    echo "✅ bot 正在后台运行（pid: $(pgrep -f 'tgextract.bot' | tr '\n' ' ')）"
    tail -3 "$SERVICE_LOG" 2>/dev/null || true
  else
    echo "❌ 没在运行。./service.sh start"
  fi
}

logs() {
  echo "—— 服务日志（最近 40 行）——"
  tail -40 "$SERVICE_LOG" 2>/dev/null || echo "（还没有日志）"
  echo
  echo "—— bot 日志（最近 40 行）——"
  tail -40 data/bot.log 2>/dev/null || true
}

uninstall() {
  launchctl unload "$PLIST_DST" 2>/dev/null || true
  rm -f "$PLIST_DST"
  pkill -f "tgextract.bot" 2>/dev/null || true
  echo "已卸载"
}

case "${1:-}" in
  install) install ;;
  stop) stop ;;
  start) start ;;
  status) status ;;
  logs) logs ;;
  uninstall) uninstall ;;
  *) echo "用法: ./service.sh install|stop|start|status|logs|uninstall" ;;
esac
