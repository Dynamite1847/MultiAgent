#!/usr/bin/env bash
# ─── Multi-Agent Workbench 一键启动脚本 ──────────────────────────────
# 用法: ./start.sh [start|stop|restart|status]
# ─────────────────────────────────────────────────────────────────────
# set -euo pipefail  # 不使用 -e，因为启动检测过程中的临时失败不应中断脚本

ACTION=${1:-start}
ROOT="$(cd "$(dirname "$0")" && pwd)"
BACKEND_PID="$ROOT/.backend.pid"
FRONTEND_PID="$ROOT/.frontend.pid"
CONDA_ENV="multiagent"
BACKEND_PORT=9000
FRONTEND_PORT=3000

# ── 工具函数 ──────────────────────────────────

# 通过端口查找 PID（比 PID 文件更可靠）
find_pid_by_port() {
  lsof -ti :"$1" 2>/dev/null | head -1
}

is_running() {
  local pidfile=$1 port=$2
  # 优先查端口
  if [ -n "$port" ]; then
    [ -n "$(find_pid_by_port $port)" ] && return 0
  fi
  # 回退到 PID 文件
  [ -f "$pidfile" ] && kill -0 "$(cat $pidfile)" 2>/dev/null
}

stop_by_port() {
  local port=$1
  local pid
  pid=$(find_pid_by_port "$port")
  if [ -n "$pid" ]; then
    kill "$pid" 2>/dev/null || true
    return 0
  fi
  return 1
}

start_backend() {
  if is_running "$BACKEND_PID" "$BACKEND_PORT"; then
    local pid=$(find_pid_by_port $BACKEND_PORT)
    echo "  ⚠️  后端已在运行 (PID ${pid:-$(cat $BACKEND_PID 2>/dev/null)})"
    return
  fi
  echo "  🚀 启动后端 (FastAPI :$BACKEND_PORT)…"
  cd "$ROOT"
  # 使用 conda run 确保在正确的环境中运行
  nohup conda run -n "$CONDA_ENV" python server.py \
    > "$ROOT/logs/backend.log" 2>&1 &
  local bg_pid=$!
  echo $bg_pid > "$BACKEND_PID"
  # 等待服务实际启动
  echo -n "     等待启动"
  for i in $(seq 1 15); do
    sleep 1
    echo -n "."
    if [ -n "$(find_pid_by_port $BACKEND_PORT)" ]; then
      echo ""
      echo "     ✅ PID: $(find_pid_by_port $BACKEND_PORT) | 日志: logs/backend.log"
      return
    fi
  done
  echo ""
  echo "     ⚠️  启动可能较慢，请检查 logs/backend.log"
}

start_frontend() {
  if is_running "$FRONTEND_PID" "$FRONTEND_PORT"; then
    local pid=$(find_pid_by_port $FRONTEND_PORT)
    echo "  ⚠️  前端已在运行 (PID ${pid:-$(cat $FRONTEND_PID 2>/dev/null)})"
    return
  fi
  echo "  🎨 启动前端 (Vite :$FRONTEND_PORT)…"
  cd "$ROOT/frontend"
  [ ! -d "node_modules" ] && npm install --silent
  nohup npm run dev > "$ROOT/logs/frontend.log" 2>&1 &
  echo $! > "$FRONTEND_PID"
  sleep 2
  local pid=$(find_pid_by_port $FRONTEND_PORT)
  if [ -z "$pid" ]; then
    # Vite 可能用了 3001
    pid=$(find_pid_by_port 3001)
  fi
  echo "     PID: ${pid:-$(cat $FRONTEND_PID)} | 日志: logs/frontend.log"
}

stop_service() {
  local pidfile=$1 name=$2 port=$3
  local stopped=false

  # 优先通过端口停止
  if [ -n "$port" ] && stop_by_port "$port"; then
    echo "  🛑 已停止 $name (端口 $port)"
    stopped=true
  fi

  # 再通过 PID 文件停止
  if [ -f "$pidfile" ]; then
    local pid=$(cat "$pidfile")
    if kill -0 "$pid" 2>/dev/null; then
      kill "$pid" 2>/dev/null || true
      if ! $stopped; then
        echo "  🛑 已停止 $name (PID $pid)"
        stopped=true
      fi
    fi
    rm -f "$pidfile"
  fi

  if ! $stopped; then
    echo "  ℹ️  $name 未运行"
  fi
}

status_service() {
  local pidfile=$1 name=$2 port=$3
  local pid=$(find_pid_by_port "$port")
  if [ -n "$pid" ]; then
    echo "  ✅ $name 运行中 (PID $pid, 端口 $port)"
  elif is_running "$pidfile"; then
    echo "  ⚠️  $name 进程在但端口 $port 未监听 (PID $(cat $pidfile))"
  else
    echo "  ❌ $name 未运行"
  fi
}

mkdir -p "$ROOT/logs"

case "$ACTION" in
  start)
    echo "── Multi-Agent Workbench ────────────────────"
    start_backend
    start_frontend
    echo ""
    echo "✅ 启动完成！"
    echo "   🌐 前端:  http://localhost:$FRONTEND_PORT"
    echo "   📡 后端:  http://localhost:$BACKEND_PORT/docs"
    ;;
  stop)
    echo "── 停止服务 ───────────────────────────────"
    stop_service "$BACKEND_PID" "后端" "$BACKEND_PORT"
    stop_service "$FRONTEND_PID" "前端" "$FRONTEND_PORT"
    # 也检查 3001 端口（Vite 备用端口）
    stop_by_port 3001 2>/dev/null && echo "  🛑 已停止前端备用端口 3001"
    ;;
  restart)
    bash "$ROOT/start.sh" stop
    sleep 2
    bash "$ROOT/start.sh" start
    ;;
  status)
    echo "── 服务状态 ───────────────────────────────"
    status_service "$BACKEND_PID" "后端 (FastAPI)" "$BACKEND_PORT"
    status_service "$FRONTEND_PID" "前端 (Vite)" "$FRONTEND_PORT"
    # 检查 3001
    if [ -n "$(find_pid_by_port 3001)" ]; then
      echo "  ℹ️  前端备用端口 3001 也在运行 (PID $(find_pid_by_port 3001))"
    fi
    ;;
  *)
    echo "用法: $0 [start|stop|restart|status]"
    exit 1
    ;;
esac
