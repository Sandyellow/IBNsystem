#!/bin/bash
# IBN 系统停止脚本
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
LOG_DIR="$SCRIPT_DIR/logs"

echo "[IBN] 停止所有服务..."
pkill -f ryu-manager     2>/dev/null && echo "  Ryu 已停止" || true
pkill -f "python3 agent" 2>/dev/null && echo "  Agent 已停止" || true
pkill -f "mininet_topology"  2>/dev/null && echo "  Mininet 已停止" || true
sudo mn -c 2>/dev/null && echo "  Mininet 环境已清理" || true
rm -f "$LOG_DIR"/*.pid
echo "[IBN] 全部停止完成"
