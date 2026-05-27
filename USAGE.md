# IBN — Intent-Based Networking 使用手册

> 基于自然语言的 SDN 网络管理系统。  
> Windows 主机运行前端 + 后端，Ubuntu VM 运行 Ryu + Mininet + Agent。

---

## 一、系统架构

```
Windows 主机
├── frontend/   React + Vite       → http://localhost:5173
└── backend/    FastAPI + uvicorn  → http://localhost:8000

Ubuntu VM
└── vm-agent/
    ├── ryu_controller.py   Ryu SDN 控制器
    ├── mininet_topology.py     Mininet 网络拓扑
    └── agent.py            Flask 中间层 Agent  → :5000
```

---

## 二、首次配置

### 1. 搭建后端 Python 虚拟环境

在项目根目录下打开 Windows PowerShell，创建虚拟环境并安装依赖：

```powershell
# 1. 创建虚拟环境 (在根目录下)
python -m venv .venv

# 2. 激活虚拟环境并安装后端依赖
.\.venv\Scripts\pip install -r backend\requirements.txt
```

### 2. 安装前端依赖

```powershell
cd frontend
npm install
cd ..
```

### 3. 配置后端环境变量（必填）

```powershell
Copy-Item backend\.env.example backend\.env
notepad backend\.env
```

在 `.env` 中填入你的大模型服务配置以及实际的 VM IP 地址（系统采用标准 **OpenAI 兼容接口**，支持硅基流动 SiliconFlow、DeepSeek、本地 Ollama、vLLM 等任意兼容服务）：

```env
# 请将 <VM_IP_ADDRESS> 替换为你实际运行 Mininet VM 的 IP 地址
VM_AGENT_URL=http://<VM_IP_ADDRESS>:5000
RYU_REST_URL=http://<VM_IP_ADDRESS>:8080

# 大模型配置 (OpenAI 兼容格式)
LLM_BASE_URL=https://api.siliconflow.cn/v1
LLM_API_KEY=sk-xxxxxxxxxxxxxxxx        ← 填入你的 API Key
LLM_MODEL=Qwen/Qwen2.5-72B-Instruct    ← 指定模型名称
```

### 4. 配置前端环境变量（可选）

默认情况下，前端会自动连接到同一台机器上的 `8000` 端口。如果你的后端服务运行在其他机器上，你可以复制前端的环境变量模板并进行修改：

```powershell
Copy-Item frontend\.env.example frontend\.env
notepad frontend\.env
```


---

## 三、启动步骤

### Windows 端

**终端 1 — 启动后端：**
```powershell
cd .\backend
..\.venv\Scripts\uvicorn main:app --host 0.0.0.0 --port 8000 --reload
```

**终端 2 — 启动前端：**
```powershell
cd .\DevelopmentProjects\AskAnything\frontend
npm run dev
```

访问 → http://localhost:5173

---

### Ubuntu VM 端

**将脚本文件传到 VM（首次，注意替换 IP）：**
```powershell
scp -r .\vm-agent\* sdn@<VM_IP_ADDRESS>:~/Desktop/vm-agent/
```

**一键启动（在 VM 终端执行）：**
```bash
cd ~/Desktop/vm-agent
sudo bash startup.sh
```

> 💡 **提示**：为方便开发调试，`startup.sh` 执行后会将 Mininet 作为前台进程挂起，并保持在 `mininet>` 交互提示符下。Ryu 控制器和 VM Agent 会在后台守护运行。

---

## 四、查看 VM 服务日志

后台启动后，在 **VM 新终端** 中查看实时日志：

```bash
cd ~/Desktop/vm-agent

# 同时查看所有服务日志（推荐）
bash logs.sh

# 只看 Ryu 控制器
bash logs.sh ryu

# 只看 Agent
bash logs.sh agent
```

日志文件位置：`~/Desktop/vm-agent/logs/`
- `ryu.log`     — Ryu 控制器输出（交换机连接、流表下发记录、LLDP 拓扑发现）
- `agent.log`   — Flask Agent 的 HTTP 请求记录

**停止所有服务：**
```bash
sudo bash ~/Desktop/vm-agent/stop.sh
```

---

## 五、自然语言意图示例

系统支持多种基于自然语言的网络运维指令。在前端右侧的对话框中，你可以尝试输入以下意图：

### 📊 查询与测试类（立即返回数据）

| 意图说明 | 示例输入 | 对应的系统动作 (Action) |
|----------|----------|-------------------------|
| **查询网络拓扑** | `显示当前网络拓扑结构` | `query_topology` |
| **查询端口统计** | `查看所有交换机的端口流量统计` | `query_port_stats` |
| **查询交换机流表** | `查看 s2 交换机的流表` | `query_flows` |
| **连通性测试** | `测试 h1 和 h2 之间的连通性` | `ping_test` |

### ⚙️ 控制类（通过 Ryu 下发 OpenFlow 规则）

| 意图说明 | 示例输入 | 对应的系统动作 (Action) |
|----------|----------|-------------------------|
| **阻断通信** | `隔离 h1 和 h3，让它们不能互相通信` | `block_traffic` |
| **恢复通信** | `恢复 h1 和 h3 之间的正常通信` | `allow_traffic` |
| **带宽限速** | `把 h2 到 h4 的流量限制在 5Mbps` | `rate_limit` (下发 Meter 表) |
| **流量重定向** | `将 h1 到 h2 的流量重定向经过 s3` | `redirect_traffic` |
| **设置优先级** | `给 h1 到 h2 的流量设置高优先级 300` | `set_priority` |
| **清除自定义流表** | `清除 s1 上的所有自定义规则` | `clear_flows` |

> 💡 **提示**：系统会自动提取意图中的参数（如源主机 `h1`，目标交换机 `s2`，限速带宽 `5Mbps`）并将其映射为针对 Ryu REST API 的参数调用。系统目前没有物理链路断开控制，若要模拟物理链路中断断请直接在 VM 的 Mininet CLI 执行 `link s1 s2 down`。

---

## 六、系统流程说明（IBN v2 架构）

本系统采用了极其简练且高效的 **三步流水线架构**，去除了繁琐的中间转译层，直接由大模型生成可执行指令：

```
用户输入自然语言意图
      ↓
【Step 1】意图解析 (LLM Parsing)
  - 注入系统当前的真实拓扑上下文
  - 采用 Few-shot 方式约束输出 JSON Schema
  - 如果解析失败会自动基于错误原因重试（最大重试 3 次）
      ↓
【Step 2】策略执行 (Policy Execution)
  - 解析成功的意图对象（包含具体的 action 和提取参数）直接下发到执行器
  - 绕过复杂的逻辑树，映射并调用底层的 Ryu REST API 或 VM Agent 代理接口
  - 收集并等待交换机真实的下发和返回结果（如流表安装、Meter 创建成功）
      ↓
【Step 3】状态推送 (WebSocket Broadcast)
  - 执行结束后，如果有拓扑或策略的改变，后端主动刷新数据
  - 通过 WebSocket 将变更增量及意图执行进度实时推送到前端页面
```

---

## 七、API 文档

后端 FastAPI 自动生成了基于 OpenAPI 的交互式文档，在启动项目后，可直接访问：  
🔗 **Swagger UI**: http://localhost:8000/docs

系统主要暴露的 RESTful API 包括：

- `POST /api/intent/process` — 提交自然语言意图，启动异步处理流水线
- `GET  /api/intent/records` — 获取历史意图对话记录（用于页面刷新恢复）
- `GET  /api/topology` — 获取当前拓扑（基于 Ryu LLDP 实时发现，无硬编码）
- `GET  /api/flows` — 获取网络中所有交换机的流表详情
- `GET  /api/port-stats` — 获取所有端口的流量收发统计及错误包监控
- `GET  /api/policies` — 获取 IBN 系统当前下发的自定义策略记录（限速、隔离等）
- `WS   /ws` — WebSocket 端点，用于实时订阅意图处理进度及拓扑/策略变化
