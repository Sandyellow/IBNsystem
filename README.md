# IBN — Intent-Based Networking 使用手册

> 基于自然语言的 SDN 网络管理系统。  
> Windows 主机运行前端 + 后端，Ubuntu VM 运行 Ryu + Mininet + Agent。

---

## 一、系统架构

```
Windows 主机
├── frontend/   React + Vite       → http://localhost:5173
└── backend/    FastAPI + uvicorn  → http://localhost:8000

Ubuntu VM (192.168.114.130)
└── vm-agent/
    ├── ryu_controller.py   Ryu SDN 控制器
    ├── mininet_topo.py     Mininet 网络拓扑
    └── agent.py            Flask 中间层 Agent  → :5000
```

---

## 二、首次配置

### 1. 配置后端 API Key（必填）

```powershell
# Windows PowerShell
Copy-Item backend\.env.example backend\.env
notepad backend\.env
```

在 `.env` 中填入你的大模型服务配置：

```env
VM_AGENT_URL=http://192.168.114.130:5000
RYU_REST_URL=http://192.168.114.130:8080

# 大模型配置 (OpenAI 兼容格式)
LLM_BASE_URL=https://api.siliconflow.cn/v1
LLM_API_KEY=sk-xxxxxxxxxxxxxxxx        ← 填入你的 API Key
LLM_MODEL=Qwen/Qwen2.5-72B-Instruct    ← 指定模型名称
```

---

## 三、启动步骤

### Windows 端

**终端 1 — 启动后端：**
```powershell
cd f:\DevelopmentProjects\AskAnything\backend
..\.venv\Scripts\uvicorn main:app --host 0.0.0.0 --port 8000 --reload
```

**终端 2 — 启动前端：**
```powershell
cd f:\DevelopmentProjects\AskAnything\frontend
npm run dev
```

访问 → http://localhost:5173

---

### Ubuntu VM 端

**将脚本文件传到 VM（首次）：**
```powershell
scp -r f:\DevelopmentProjects\AskAnything\vm-agent\* sdn@192.168.114.130:~/Desktop/vm-agent/
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

在前端右侧「意图交互」框中输入以下指令：

### 📊 查询类（立即返回数据）

| 输入 | 说明 |
|------|------|
| `查看 s1 的流量统计` | 返回 s1 的 RX/TX 字节数 |
| `查看所有交换机流量` | 返回全部交换机统计 |
| `查看当前网络拓扑` | 返回节点数、链路数 |

### ⚙️ 控制类（下发到 Ryu 执行）

| 输入 | 说明 |
|------|------|
| `限制 h1 到 h3 带宽为 2Mbps` | 在 s1 上下发 Meter 限速规则 |
| `限制 h2 到 h4 带宽为 5Mbps` | 同上，不同节点 |
| `阻断 h1 和 h2 之间的通信` | 下发 DROP 流表（⚠️ 高危，需二次确认）|
| `允许 h1 和 h3 互相通信` | 下发 ALLOW 流表 |
| `删除 h1 到 h3 的流表规则` | 删除已有规则（⚠️ 高危，需二次确认）|
| `将 h2 的流量重定向经由 s2` | 添加重定向路由规则 |
| `设置 h1 到 h2 流量优先级为 500` | 调整流表 priority |

> ⚠️ **高危操作**会在验证后暂停，要求你点击「确认执行」才会下发。
> 💡 **架构边界说明**：系统遵循严格的 SDN 控制平面边界。物理链路断开/恢复（如 `link s1 s2 down`）属于底层硬件模拟操作，请在 Mininet CLI 终端中直接运行以测试系统告警；系统意图引擎专注处理 Ryu 控制平面能够覆盖的流量调度规则。

---

## 六、系统流程说明

```
用户输入自然语言
      ↓
  LLM 解析（最多重试 3 次）
      ↓
  6层验证：
    Schema → 白名单 → 节点存在 → 参数范围 → 安全红线 → 置信度
      ↓ 全部通过
  高危操作？→ 等待用户二次确认
      ↓
  策略生成（FlowRule / Meter / Routing）
      ↓
  下发到 VM Agent（:5000）
      ↓
  Agent 调用 Ryu REST API（:8080）
      ↓
  OVS 交换机执行 OpenFlow 规则
      ↓
  结果通过 WebSocket 推送前端（支持页面刷新对话历史恢复）
```

---

## 七、故障排查

| 症状 | 可能原因 | 解决方法 |
|------|---------|---------|
| 前端显示「VM 未连接」 | VM Agent 未启动 | `sudo bash startup.sh` |
| 拓扑无节点 | Mininet 未运行或 LLDP 未就绪 | 确认 Ryu 启动带有 `--observe-links` 参数 |
| 意图解析失败（LLM 错误）| API Key 未配置 | 检查 `backend/.env` |
| 意图置信度低（< 0.6）| 描述不清晰 | 参考上面的示例格式 |
| 限速/封锁无效 | 流表未匹配 | 主机需要有 IP（在 Mininet 中执行 `pingall`）|
| Ryu 拓扑报错 | ryu.topology 模块未加载 | 系统采用纯 LLDP 发现，需确保 Ryu 启动参数正确 |

---

## 八、API 文档

后端 Swagger 文档：http://localhost:8000/docs

主要接口：
- `POST /api/intent/process` — 提交意图
- `GET  /api/intent/records` — 获取历史意图对话记录（用于页面刷新恢复）
- `GET  /api/topology` — 获取当前拓扑（基于 Ryu LLDP 实时发现）
- `GET  /api/network/status` — 获取网络状态
- `WS   /ws` — WebSocket 实时推送

