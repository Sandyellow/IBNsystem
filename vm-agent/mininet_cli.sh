#!/bin/bash
# ============================================================
#  启动 Mininet 交互式 CLI（保持 Ryu 和 Agent 运行）
#  在 VM 上执行: sudo bash mininet_cli.sh
# ============================================================

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
LOG_DIR="$SCRIPT_DIR/logs"

GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

log()  { echo -e "${GREEN}[IBN-CLI]${NC} $1"; }
warn() { echo -e "${YELLOW}[IBN-CLI]${NC} $1"; }

# 找到有 mininet 的 python
MININET_PYTHON=""
for py in /usr/bin/python3 /usr/local/bin/python3; do
    if [ -x "$py" ] && "$py" -c "import mininet" 2>/dev/null; then
        MININET_PYTHON="$py"
        break
    fi
done

# ── 停止后台 Mininet（避免端口冲突）────────────────────
log "停止后台 Mininet..."
pkill -f "mininet_topo.py" 2>/dev/null || true
sudo mn -c 2>/dev/null || true
sleep 2

# ── 确认 Ryu 在运行 ────────────────────────────────────
if ! curl -s http://127.0.0.1:8080/stats/switches > /dev/null 2>&1; then
    warn "Ryu 未运行，正在启动..."
    RYU_BIN=$(which ryu-manager 2>/dev/null || find /home -name "ryu-manager" 2>/dev/null | head -1)
    VENV_DIR="$(dirname "$(dirname "$RYU_BIN")")"
    nohup "$RYU_BIN" \
        "$SCRIPT_DIR/ryu_controller.py" \
        ryu.app.ofctl_rest ryu.topology.switches \
        --observe-links --ofp-tcp-listen-port 6633 \
        > "$LOG_DIR/ryu.log" 2>&1 &
    sleep 5
fi

echo ""
echo -e "${GREEN}══════════════════════════════════════════════${NC}"
echo -e "${GREEN}  Mininet 交互式 CLI 启动中...${NC}"
echo -e "${GREEN}══════════════════════════════════════════════${NC}"
echo ""
echo "  主机 IP:"
echo "    h1 = 10.0.0.1    h2 = 10.0.0.2"
echo "    h3 = 10.0.0.3    h4 = 10.0.0.4"
echo ""
echo "  常用命令:"
echo "    pingall          → 所有主机互相 ping"
echo "    h1 ping h2       → h1 ping h2"
echo "    h1 ping h2 -c 3  → h1 ping h2 三次"
echo "    iperf h1 h2      → h1 和 h2 之间带宽测试"
echo "    h1 iperf -s &    → 在 h1 上启动 iperf 服务端"
echo "    h2 iperf -c h1   → h2 连接 h1 测速"
echo "    net              → 显示网络拓扑连接"
echo "    nodes            → 显示所有节点"
echo "    links            → 显示所有链路"
echo "    dump             → 显示节点详细信息"
echo "    h1 ifconfig      → 查看 h1 网络配置"
echo "    h1 route         → 查看 h1 路由表"
echo "    s1 ovs-ofctl dump-flows s1  → 查看 s1 流表"
echo "    exit             → 退出 CLI（返回后台模式）"
echo ""
echo -e "${GREEN}══════════════════════════════════════════════${NC}"

# ── 启动带 CLI 的 Mininet ──────────────────────────────
sudo "$MININET_PYTHON" "$SCRIPT_DIR/mininet_topo.py" --cli

# ── CLI 退出后，重启后台 Mininet ────────────────────────
log "CLI 已退出，重启后台 Mininet..."
nohup sudo "$MININET_PYTHON" "$SCRIPT_DIR/mininet_topo.py" \
    > "$LOG_DIR/mininet.log" 2>&1 &
log "后台 Mininet 已重启 (PID: $!)"
