# IBN 部署与使用手册

---

## 1. 环境要求

**Windows 主机：**
- Python 3.10+
- Node.js 18+
- Git

**Ubuntu VM：**
- Python 3.10+
- Ryu SDN 控制器
- Mininet
- Open vSwitch

---

## 2. 安装

### 2.1 后端

在项目根目录执行：

```powershell
python -m venv .venv
.\.venv\Scripts\pip install -r backend\requirements.txt
```

### 2.2 前端

```powershell
cd frontend
npm install
cd ..
```

### 2.3 配置环境变量

```powershell
Copy-Item backend\.env.example backend\.env
```

编辑 `backend\.env`：

```env
RYU_REST_URL=http://<VM_IP_ADDRESS>:8080
LLM_BASE_URL=https://api.siliconflow.cn/v1
LLM_API_KEY=sk-your-api-key-here
LLM_MODEL=Qwen/Qwen2.5-72B-Instruct
```

- `RYU_REST_URL`：替换 `<VM_IP_ADDRESS>` 为 Ubuntu VM 的实际 IP
- `LLM_*`：填入你的大模型 API 地址、Key 和模型名，兼容 OpenAI 接口格式（SiliconFlow、DeepSeek、Ollama、vLLM 等均可）

### 2.4 Ubuntu VM

将 `vm-agent/` 目录下所有文件传到 VM：

```powershell
scp -r .\vm-agent\* sdn@<VM_IP_ADDRESS>:~/Desktop/vm-agent/
```

VM 上无需额外安装依赖，`startup.sh` 会自动查找系统中的 Ryu 和 Mininet。

---

## 3. 启动

### 3.1 Windows 端

终端 1 — 后端：

```powershell
.\.venv\Scripts\uvicorn backend.main:app --host 0.0.0.0 --port 8000 --reload
```

终端 2 — 前端：

```powershell
cd frontend
npm run dev
```

浏览器访问 `http://localhost:5173`。

### 3.2 Ubuntu VM 端

```bash
cd ~/Desktop/vm-agent
sudo bash startup.sh
```

启动后 Mininet 进入交互式 CLI（`mininet>` 提示符）。按 `exit` 退出 CLI 时 Mininet 拓扑会停止，Ryu 控制器仍在后台运行。

指定拓扑：

```bash
sudo bash startup.sh --config topology_ring.json
```

可选拓扑文件：`topology.json`（默认线型）、`topology_ring.json`、`topology_multipath.json`、`topology_fat_tree.json`。

---

## 4. VM 服务管理

### 查看日志

```bash
cd ~/Desktop/vm-agent

bash logs.sh          # 同时查看 Ryu + Mininet 日志
bash logs.sh ryu      # 仅 Ryu
bash logs.sh mininet  # 仅 Mininet
```

日志文件位置：`logs/ryu.log`、`logs/mininet.log`

### 停止服务

```bash
sudo bash ~/Desktop/vm-agent/stop.sh
```

---

## 5. 自然语言指令

| 示例输入 | 动作 |
|----------|------|
| `隔离 h1 和 h3，让它们不能互相通信` | block_traffic |
| `恢复 h1 和 h3 之间的正常通信` | allow_traffic |
| `把 h2 到 h4 的流量限制在 5Mbps` | rate_limit |
| `给 h1 到 h2 的流量设置高优先级 300` | set_priority |
| `清除 s1 上的所有自定义规则` | clear_flows |
| `限制 h1 到 h3 的 SSH 流量` | acl |
| `给 h1 到 h2 的流量打上 DSCP 46 标记` | qos_mark |
| `把 h1 和 h2 划分到 VLAN 10` | vlan |
| `在 h1 和 h2 之间启用多路径负载均衡` | multipath |

---

## 6. API 文档

启动后端后访问 `http://localhost:8000/docs` 查看 Swagger 交互式文档。

主要接口：

| 方法 | 端点 | 说明 |
|------|------|------|
| `POST` | `/api/intent/process` | 提交自然语言意图 |
| `GET` | `/api/intent/records` | 历史对话记录 |
| `GET` | `/api/topology` | 当前拓扑 |
| `GET` | `/api/flows` | 所有交换机流表 |
| `GET` | `/api/port-stats` | 端口流量统计 |
| `GET` | `/api/policies` | 当前自定义策略 |
| `GET` | `/api/health` | 健康检查 |
| `WS` | `/ws` | WebSocket 实时推送 |

---