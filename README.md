<div align="center">

# IBN — Intent-Based Networking System

**基于大语言模型的自然语言 SDN 网络管理系统**

*Tell the network what you want, not how to do it.*

[![Python](https://img.shields.io/badge/Python-3.10+-3776AB?style=flat-square&logo=python&logoColor=white)](https://www.python.org/)
[![FastAPI](https://img.shields.io/badge/FastAPI-0.110+-009688?style=flat-square&logo=fastapi&logoColor=white)](https://fastapi.tiangolo.com)
[![React](https://img.shields.io/badge/React-19-61DAFB?style=flat-square&logo=react&logoColor=black)](https://react.dev)
[![Vite](https://img.shields.io/badge/Vite-8-646CFF?style=flat-square&logo=vite&logoColor=white)](https://vitejs.dev)
[![Ryu](https://img.shields.io/badge/SDN-Ryu-ff69b4?style=flat-square)](https://ryu-sdn.org/)
[![OpenFlow](https://img.shields.io/badge/OpenFlow-1.3-00a393?style=flat-square)](https://opennetworking.org/)
[![License](https://img.shields.io/badge/License-MIT-yellow?style=flat-square)](./LICENSE)

[使用手册](./USAGE.md) &nbsp;&middot;&nbsp; [API 文档](http://localhost:8000/docs)

</div>

---

## 简介

**IBN System** 是一个基于自然语言的网络管理系统，结合大语言模型（LLM）与软件定义网络（SDN）技术，支持网络管理员使用自然语言对网络状态进行查询与流量控制。

系统通过 LLM 解析用户运维意图，将其规范化后直接映射为 Ryu 控制器的 REST API 调用，并通过 OpenFlow 协议下发流表规则，实现交互式、直观的网络管理方案。

---

## 核心特性

| 特性 | 说明 |
|------|------|
| **自然语言控制** | 对话式网络管理接口，支持流量管控、状态查询等多类意图的解析与参数自动提取 |
| **三步流水线架构** | 意图解析 -> 策略执行 -> 状态推送，LLM 直接生成可执行指令，零中间转译层 |
| **实时拓扑发现** | 基于 LLDP 协议自动感知物理拓扑变化，Web 前端力导向图实时渲染 |
| **安全拦截** | 节点隔离、流表清空等高危操作强制二次确认，执行前自动检测策略冲突 |
| **WebSocket 实时同步** | 拓扑变更、端口流量统计、意图执行进度通过 WebSocket 双向通道毫秒级推送 |

---

## 技术栈

| 层级 | 技术 | 说明 |
|------|------|------|
| **前端** | React 19 &middot; Vite 8 &middot; Zustand &middot; Recharts &middot; @xyflow/react | Glassmorphism UI &middot; 力导向拓扑图 &middot; 实时统计图表 |
| **后端** | FastAPI &middot; Pydantic v2 &middot; WebSocket | 异步流水线 &middot; 自动生成 OpenAPI 文档 |
| **AI** | OpenAI 兼容接口 | 支持 SiliconFlow / DeepSeek / Ollama / vLLM 等任意兼容服务 |
| **SDN** | Ryu Controller &middot; OpenFlow 1.3 | LLDP 拓扑发现 &middot; Meter 表限速 &middot; 流表管理 |
| **仿真** | Mininet &middot; Open vSwitch | 多拓扑模板 &middot; 可编程网络仿真 |

---

## 快速开始

详细步骤请参阅 [使用手册 (USAGE.md)](./USAGE.md)。

```powershell
# 1. 安装后端依赖
python -m venv .venv
.\.venv\Scripts\pip install -r backend\requirements.txt

# 2. 安装前端依赖
cd frontend; npm install; cd ..

# 3. 配置环境变量
Copy-Item backend\.env.example backend\.env
# 编辑 backend\.env 填入 LLM API Key 和 VM IP 地址

# 4. 启动后端
.\.venv\Scripts\uvicorn backend.main:app --host 0.0.0.0 --port 8000 --reload

# 5. 启动前端
cd frontend; npm run dev
```
---

## 项目结构

```
AskAnything/
├── backend/                 # FastAPI 后端
│   ├── api/                 #   REST + WebSocket 路由
│   ├── core/                #   意图解析、策略执行、拓扑管理
│   ├── models/              #   Pydantic 数据模型
│   ├── main.py              #   应用入口
│   ├── config.py            #   环境配置
│   └── requirements.txt
├── frontend/                # React 前端
│   ├── src/
│   │   ├── components/      #   UI 组件
│   │   ├── stores/          #   Zustand 状态管理
│   │   └── api/             #   HTTP + WebSocket 客户端
│   └── package.json
├── vm-agent/                # Ubuntu VM 端脚本
│   ├── ryu_controller.py    #   Ryu 控制器应用
│   ├── mininet_topology.py  #   Mininet 拓扑定义
│   ├── startup.sh           #   一键启动
│   ├── stop.sh              #   停止服务
│   └── logs.sh              #   日志查看
├── README.md
└── USAGE.md
```

---

## 开源协议

本项目基于 [MIT License](./LICENSE) 开源。
