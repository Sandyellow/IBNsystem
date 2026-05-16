#!/bin/bash
# ============================================================
#  IBN 系统日志实时查看
#  用法:
#    bash logs.sh         # 同时查看所有服务日志
#    bash logs.sh ryu     # 只看 Ryu 日志
#    bash logs.sh mininet # 只看 Mininet 日志
#    bash logs.sh agent   # 只看 Agent 日志
# ============================================================

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
LOG_DIR="$SCRIPT_DIR/logs"

GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
CYAN='\033[0;36m'
NC='\033[0m'

SERVICE="${1:-all}"

case "$SERVICE" in
    ryu)
        echo -e "${GREEN}══ Ryu 控制器日志 (Ctrl+C 退出) ══${NC}"
        tail -f "$LOG_DIR/ryu.log"
        ;;
    mininet)
        echo -e "${YELLOW}══ Mininet 拓扑日志 (Ctrl+C 退出) ══${NC}"
        tail -f "$LOG_DIR/mininet.log"
        ;;
    agent)
        echo -e "${BLUE}══ VM Agent 日志 (Ctrl+C 退出) ══${NC}"
        tail -f "$LOG_DIR/agent.log"
        ;;
    all|*)
        # 同时查看所有日志（需要 multitail，若无则用 tail）
        if command -v multitail &>/dev/null; then
            multitail \
                -cS ryu     "$LOG_DIR/ryu.log" \
                -cS mininet "$LOG_DIR/mininet.log" \
                -cS flask   "$LOG_DIR/agent.log"
        else
            # 用 tail -f 合并输出，用颜色区分来源
            echo -e "${CYAN}══ IBN 系统实时日志（所有服务）按 Ctrl+C 退出 ══${NC}"
            echo -e "  ${GREEN}[ryu]${NC} Ryu 控制器  ${YELLOW}[mininet]${NC} Mininet  ${BLUE}[agent]${NC} VM Agent"
            echo "────────────────────────────────────────────"
            # 用管道加前缀颜色区分
            (
                tail -f "$LOG_DIR/ryu.log"     | sed "s/^/${GREEN}[ryu    ]${NC} /" &
                tail -f "$LOG_DIR/mininet.log" | sed "s/^/${YELLOW}[mininet]${NC} /" &
                tail -f "$LOG_DIR/agent.log"   | sed "s/^/${BLUE}[agent  ]${NC} /" &
                wait
            )
        fi
        ;;
esac
