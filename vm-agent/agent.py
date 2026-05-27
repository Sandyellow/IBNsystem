"""
VM Agent — 仅作为开发调试辅助服务
(注：IBN 系统的网络拓扑感知、自发现与意图策略下发已 100% 迁移至后端直连 Ryu API，本服务不参与生成任何系统业务逻辑)
"""
from flask import Flask, jsonify, request
import subprocess
import time
import os
import re
import logging
from logging.handlers import RotatingFileHandler

app = Flask(__name__)

# 配置 API Key
API_KEY = os.getenv("VM_AGENT_API_KEY", "IBN-Debug-Secret-Key")

# 配置日志审计组件
LOG_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "logs")
os.makedirs(LOG_DIR, exist_ok=True)
log_file = os.path.join(LOG_DIR, "agent.log")

handler = RotatingFileHandler(log_file, maxBytes=10*1024*1024, backupCount=5)
handler.setFormatter(logging.Formatter(
    '%(asctime)s [%(levelname)s] (Client: %(client_ip)s) %(message)s'
))
logger = logging.getLogger("VM-Agent")
logger.addHandler(handler)
logger.setLevel(logging.INFO)

# 安全正则限制：仅允许字母、数字、空格、点号、短横线、斜杠
SAFE_CMD_PATTERN = re.compile(r"^[a-zA-Z0-9\s.\-/]+$")

def get_client_ip():
    return request.remote_addr or "unknown"

@app.route("/ping")
def ping():
    """健康检查端点"""
    return jsonify({"status": "ok", "timestamp": time.time()})

@app.route("/mininet/exec", methods=["POST"])
def exec_mininet_cmd():
    """
    在 Mininet 中执行仿真命令（如 ping、iperf、link up/down），仅作为开发调试辅助
    """
    client_ip = get_client_ip()
    
    # 1. API Key 认证
    auth_key = request.headers.get("X-API-Key")
    if auth_key != API_KEY:
        logger.warning("Unauthorized access attempt", extra={"client_ip": client_ip})
        return jsonify({"success": False, "error": "Unauthorized"}), 401

    req_data = request.json or {}
    command = req_data.get("command", "").strip()
    if not command:
        return jsonify({"success": False, "error": "Missing command argument"}), 400

    # 2. 安全性校验：防命令注入
    if not SAFE_CMD_PATTERN.match(command):
        logger.warning(
            f"Blocked command with disallowed characters: {command}", 
            extra={"client_ip": client_ip}
        )
        return jsonify({"success": False, "error": "Command contains disallowed characters (only a-z, A-Z, 0-9, space, '.', '-', '/' are allowed)"}), 403

    logger.info(f"Executing command: {command}", extra={"client_ip": client_ip})

    try:
        # 执行底层仿真命令。出于安全考虑，必须通过正则防注入校验，并且 timeout 设为 15.0 秒
        res = subprocess.run(
            command,
            shell=True,
            capture_output=True,
            text=True,
            timeout=15.0
        )
        logger.info(f"Command execution completed with code: {res.returncode}", extra={"client_ip": client_ip})
        return jsonify({
            "success": res.returncode == 0,
            "stdout": res.stdout,
            "stderr": res.stderr,
            "returncode": res.returncode
        })
    except subprocess.TimeoutExpired:
        logger.error(f"Command timed out: {command}", extra={"client_ip": client_ip})
        return jsonify({"success": False, "error": "Command execution timeout"}), 504
    except Exception as e:
        logger.error(f"Command failed with error: {e}", extra={"client_ip": client_ip}, exc_info=True)
        return jsonify({"success": False, "error": str(e)}), 500

if __name__ == "__main__":
    # 限制只能从宿主机或本地通信（生产可配置 127.0.0.1 或是特定内网网卡 IP，此处开启 0.0.0.0 配合 IP 白名单/API Key 最佳）
    app.run(host="0.0.0.0", port=5000, threaded=True, debug=False)
