#!/bin/bash
# ============================================================
#  IBN 系统一键启动脚本
#  在 Ubuntu VM 上运行: sudo bash startup.sh
# ============================================================

set -e
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
LOG_DIR="$SCRIPT_DIR/logs"
mkdir -p "$LOG_DIR"

GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
NC='\033[0m'

log()  { echo -e "${GREEN}[IBN]${NC} $1"; }
warn() { echo -e "${YELLOW}[IBN]${NC} $1"; }
err()  { echo -e "${RED}[IBN]${NC} $1"; }

# ── 清理旧进程 ────────────────────────────────────────
log "清理旧进程..."
pkill -f ryu-manager       2>/dev/null || true
pkill -f "python3 agent"   2>/dev/null || true
pkill -f "mininet_topology"    2>/dev/null || true
mn -c 2>/dev/null || true
sleep 2

# ── 找到 ryu-manager 的路径 ───────────────────────────
RYU_BIN=$(which ryu-manager 2>/dev/null || find /home -name "ryu-manager" 2>/dev/null | head -1)
if [ -z "$RYU_BIN" ]; then
    err "找不到 ryu-manager，请检查 Ryu 是否安装"
    exit 1
fi
log "找到 Ryu: $RYU_BIN"

# ── 从 ryu_venv 推导 Python 路径（flask/requests 均在此 venv）──
VENV_DIR="$(dirname "$(dirname "$RYU_BIN")")"
AGENT_PYTHON="$VENV_DIR/bin/python3"
if [ ! -x "$AGENT_PYTHON" ]; then
    AGENT_PYTHON=$(which python3)
fi
log "Agent Python: $AGENT_PYTHON"

# ── 找到有 mininet 模块的 Python ─────────────────────
MININET_PYTHON=""
for py in /usr/bin/python3 /usr/local/bin/python3 "$AGENT_PYTHON"; do
    if [ -x "$py" ] && "$py" -c "import mininet" 2>/dev/null; then
        MININET_PYTHON="$py"
        break
    fi
done
if [ -z "$MININET_PYTHON" ]; then
    err "找不到安装了 mininet 的 Python，请执行: sudo apt install mininet"
    exit 1
fi
log "Mininet Python: $MININET_PYTHON"

# ── 步骤 1: 启动 Ryu ──────────────────────────────────
log "启动 Ryu 控制器..."
nohup "$RYU_BIN" \
    "$SCRIPT_DIR/ryu_controller.py" \
    ryu.app.ofctl_rest \
    ryu.app.rest_topology \
    --observe-links \
    --ofp-tcp-listen-port 6633 \
    > "$LOG_DIR/ryu.log" 2>&1 &
RYU_PID=$!
echo $RYU_PID > "$LOG_DIR/ryu.pid"
log "Ryu 已启动 (PID: $RYU_PID)，等待就绪..."

# 等待 Ryu REST API 可用
for i in $(seq 1 15); do
    if curl -s http://127.0.0.1:8080/stats/switches > /dev/null 2>&1; then
        log "Ryu REST API 就绪 ✓"
        break
    fi
    if [ $i -eq 15 ]; then
        err "Ryu 启动超时，查看日志: $LOG_DIR/ryu.log"
        exit 1
    fi
    echo -n "."
    sleep 1
done

# ── 步骤 2: 启动 VM Agent ─────────────────────────────
log "启动 VM Agent..."
nohup "$AGENT_PYTHON" "$SCRIPT_DIR/agent.py" \
    > "$LOG_DIR/agent.log" 2>&1 &
AGENT_PID=$!
echo $AGENT_PID > "$LOG_DIR/agent.pid"
sleep 2

# 验证 Agent 是否启动
if curl -s http://127.0.0.1:5000/ping > /dev/null 2>&1; then
    log "VM Agent 已就绪 ✓"
else
    err "VM Agent 启动失败，查看日志: $LOG_DIR/agent.log"
fi

echo ""
echo "════════════════════════════════════"
log "IBN 系统服务已就绪！"
echo "  Ryu    PID: $RYU_PID  日志: $LOG_DIR/ryu.log"
echo "  Agent  PID: $AGENT_PID 日志: $LOG_DIR/agent.log"
echo ""
echo "  即将进入 Mininet 交互式 CLI (mininet>)"
echo "  按 exit 退出 CLI 时将停止 Mininet 拓扑"
echo "  停止后台服务请执行: bash $SCRIPT_DIR/stop.sh"
echo "════════════════════════════════════"
echo ""

# ── 步骤 3: 启动 Mininet (前台 CLI 模式) ───────────────
log "启动 Mininet 拓扑 (前台 CLI 模式)..."
sudo "$MININET_PYTHON" "$SCRIPT_DIR/mininet_topology.py" --cli

