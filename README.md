<div align="center">

# IBN System (Intent-Based Networking)

**基于大语言模型驱动的自然语言网络管理系统**

[![Python 3.10+](https://img.shields.io/badge/python-3.10+-blue.svg)](https://www.python.org/downloads/)
[![FastAPI](https://img.shields.io/badge/FastAPI-0.100+-00a393.svg)](https://fastapi.tiangolo.com)
[![React Vite](https://img.shields.io/badge/React-Vite-61DAFB.svg)](https://vitejs.dev/)
[![Ryu Controller](https://img.shields.io/badge/SDN-Ryu-ff69b4.svg)](https://ryu-sdn.org/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)

[**使用手册**](./USAGE.md) · [API 文档](http://localhost:8000/docs)

</div>

---

## 简介

**IBN System** 是一个基于自然语言的网络管理系统。本系统结合了大语言模型（LLM）与软件定义网络（SDN）技术，支持网络管理员使用自然语言对网络状态进行查询与流量控制。

系统通过 LLM 解析用户运维意图，将其规范化后直接映射为 Ryu 控制器的 API 调用，并通过 OpenFlow 协议下发流表规则，实现一种交互式、直观的网络管理方案。

## 核心特性

- **自然语言控制**：提供对话式的网络管理接口，支持流量管控、状态查询等多类意图的解析与参数提取。
- **流水线架构**：采用“意图解析 → 策略执行 → 状态推送”的三步流水线机制，简化了中间转译层，直接对接近底层控制 API。
- **动态拓扑发现**：基于 LLDP 协议自动获取底层网络的物理拓扑，并通过 Web 前端进行可视化拓扑渲染。
- **安全拦截机制**：针对节点隔离、流表清空等高危控制操作引入二次确认机制，并在执行前进行基础策略冲突检测。
- **实时状态同步**：利用 WebSocket 维持前后端双向通信，实时下发拓扑变更、端口流量统计数据及意图执行进度。

## 技术栈

<details>
<summary>展开查看详细技术栈</summary>

- **前端 (Frontend)**
  - React 18 / Vite
  - Zustand
  - Vanilla CSS / Glassmorphism UI 设计规范
- **后端 (Backend)**
  - FastAPI
  - Pydantic v2
  - 兼容 OpenAI 格式的大模型接口 (支持本地及云端模型部署)
- **底层网络 (SDN Infrastructure)**
  - Ryu Controller (遵循 OpenFlow 1.3 规范)
  - Mininet (网络拓扑仿真)
  - Open vSwitch (OVS 虚拟交换机)

</details>

## 快速开始

本项目采用前后端分离架构，前端作为交互入口，后端核心引擎通过 HTTP 与部署在 Ubuntu 上的网络节点代理（VM Agent）进行通信。

关于详细的环境依赖安装、变量配置步骤，以及系统目前支持的自然语言指令列表，请参阅独立的文档：

**[《IBN System 部署与使用手册》(USAGE.md)](./USAGE.md)**

## 开源协议

本项目采用 [MIT 协议](LICENSE) 开源。
