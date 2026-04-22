---
name: finance-tools-auto-browser
overview: 基于 Python + Playwright + Electron 的桌面应用，实现多商家端自动登录（支持滑块/短信验证码）、Cookie 凭证管理、以及通过 HTTP 请求获取商家数据并存入 SQLite 数据库的通用型自动化浏览器工具。
design:
  architecture:
    framework: vue
  styleKeywords:
    - 深色主题 Dark Theme
    - 桌面应用风格 Desktop Application
    - 青蓝色强调色 Cyan Accent
    - 卡片式布局 Card Layout
    - 微交互动效 Micro-interactions
    - 玻璃态效果 Glassmorphism
    - 专业运维工具感 DevOps Tool Aesthetic
  fontSystem:
    fontFamily: PingFang SC
    heading:
      size: 20px
      weight: 600
    subheading:
      size: 16px
      weight: 500
    body:
      size: 14px
      weight: 400
todos:
  - id: init-project
    content: 初始化项目脚手架：创建根目录结构、Electron配置、Vite+Vue3前端配置、Python虚拟环境及依赖
    status: completed
  - id: setup-database
    content: 设计和实现SQLite数据库Schema：商家配置表、凭证表、采集数据表、任务日志表及初始化脚本
    status: completed
    dependencies:
      - init-project
  - id: build-electron-main
    content: 实现Electron主进程：窗口创建与管理、IPC通道注册、Python子进程管理器（启动/监控/重启/消息收发）
    status: completed
    dependencies:
      - init-project
      - setup-database
  - id: build-vue-frontend
    content: 实现Vue3渲染进程：Pinia状态管理、Vue Router路由、5个核心页面组件（Dashboard/MerchantConfig/TaskCenter/DataView/CaptchaDialog）、Element Plus集成
    status: completed
    dependencies:
      - init-project
      - setup-database
  - id: build-python-core
    content: 实现Python核心引擎：JSON-RPC消息循环、Playwright登录引擎（状态机流程）、配置解析器、凭证加密管理器
    status: completed
    dependencies:
      - init-project
      - setup-database
  - id: build-captcha-handler
    content: 实现验证码处理系统：OpenCV滑块缺口识别与轨迹模拟、短信验证码回调机制、与Electron的验证码交互协议
    status: completed
    dependencies:
      - build-python-core
  - id: build-data-collector
    content: 实现数据采集模块：HTTP客户端（httpx携带Cookie）、请求重试与限流、数据解析与字段映射、SQLite数据写入
    status: completed
    dependencies:
      - build-python-core
  - id: integration-test
    content: 全链路联调测试：端到端流程验证（配置商家->自动登录->验证码->凭证保存->数据采集->数据展示）
    status: completed
    dependencies:
      - build-electron-main
      - build-vue-frontend
      - build-python-core
      - build-captcha-handler
      - build-data-collector
---

## Product Overview

一个基于 Electron + Python + Playwright 的桌面自动化浏览器工具，用于批量配置商家端系统、自动登录获取凭证、执行数据采集并存储到本地数据库。

## Core Features

- **商家配置管理**：通过 GUI 界面配置多个商家端的访问地址（URL）、登录账户密码、登录页面选择器等参数
- **自动登录引擎**：使用 Playwright 自动化浏览器访问各商家端登录页面，填写账号密码并提交
- **验证码处理**：支持图片滑块验证码（图像识别 + 模拟拖拽）和短信验证码（Electron UI 弹窗手动输入）
- **凭证持久化**：登录成功后保存 Cookie/Session/Token 到本地加密存储，支持凭证有效期管理与自动刷新
- **数据采集执行**：利用保存的凭证，通过 HTTP 请求（模拟 curl）调用商家端 API 接口获取业务数据
- **本地数据存储**：采集的数据统一保存到 SQLite 数据库，支持通过 GUI 界面查看和管理
- **通用型架构**：可适配任意商家系统，通过配置化的方式定义不同商家的登录流程和 API 接口
- **任务调度**：支持手动触发和定时任务两种模式执行数据采集

## Tech Stack

- **桌面应用框架**: Electron 28+ (主进程管理)
- **前端界面**: Vue 3 + TypeScript + Vite + Element Plus (渲染进程)
- **浏览器自动化**: Python 3.10+ + Playwright (子进程)
- **进程通信**: Electron IPC (主进程) ↔ stdio/Socket (Python 子进程)
- **本地数据库**: SQLite (商家配置 + 凭证存储 + 采集数据)
- **HTTP 客户端**: httpx (Python 端携带 Cookie 发起请求)
- **验证码处理**: OpenCV (滑块缺口识别) + 手动输入弹窗

## Tech Architecture

### 整体架构设计

采用 Electron 主进程 + Vue 渲染进程 + Python 子进程的三层架构：

```
┌──────────────────────────────────────────────────┐
│                  Electron 应用                     │
│                                                    │
│  ┌──────────────────────┐  ┌───────────────────┐  │
│  │   渲染进程 (Vue 3)    │  │   主进程 (Node.js) │  │
│  │                      │  │                   │  │
│  │  ┌────────────────┐  │  │  ┌─────────────┐  │  │
│  │  │ 商家配置面板   │  │  │  │ IPC 通信层   │  │  │
│  │  ├────────────────┤  │  │  ├─────────────┤  │  │
│  │  │ 任务调度中心   │◄─┼─►│  │ Python 进程  │  │  │
│  │  ├────────────────┤  │  │  │ 管理器       │  │  │
│  │  │ 数据查看表格   │  │  │  └──────┬──────┘  │  │
│  │  ├────────────────┤  │  │         │         │  │
│  │  │ 验证码输入弹窗 │  │  │         ▼         │  │
│  │  └────────────────┘  │  │  ┌─────────────┐  │  │
│  └──────────────────────┘  │  │ Python 子进程 │  │  │
│                             │  │              │  │  │
│                             │  │ ┌───────────┐│  │  │
│                             │  │ │Playwright  ││  │  │
│                             │  │ │登录引擎    ││  │  │
│                             │  │ ├───────────┤│  │  │
│                             │  │ │验证码处理  ││  │  │
│                             │  │ ├───────────┤│  │  │
│                             │  │ │Cookie 管理 ││  │  │
│                             │  │ ├───────────┤│  │  │
│                             │  │ │HTTP 采集   ││  │  │
│                             │  │ └───────────┘│  │  │
│                             │  └─────────────┘  │  │
│                             └───────────────────┘  │
└──────────────────────────────────────────────────┘
          │                              │
          ▼                              ▼
    ┌─────────────┐               ┌─────────────┐
    │ SQLite DB   │◄──────────────│ SQLite DB   │
    │(Electron侧) │   共享数据库    │(Python侧)   │
    └─────────────┘               └─────────────┘
```

### 模块划分

- **Electron 主进程模块**：
- IPC 通信服务：接收渲染进程指令，转发给 Python 子进程
- Python 进程管理器：启动/监控/重启 Python 子进程
- 窗口管理：主窗口 + 验证码弹窗

- **Vue 渲染进程模块**：
- 商家 CRUD 配置界面
- 采集任务控制面板（启动/停止/查看日志）
- 数据浏览与导出界面
- 验证码手动输入弹窗组件

- **Python 子进程模块**：
- Playwright 登录引擎（通用登录流程编排）
- 验证码处理器（滑块识别 + 短信回调）
- Cookie/Token 凭证管理（加密存储 + 有效期检测）
- HTTP 数据采集器（携带凭证发起请求）
- 数据解析与入库（通用 JSON 解析 + 字段映射）

### 数据流

1. 用户在 Electron GUI 中添加商家配置（URL、账号、密码、选择器规则）
2. 用户点击"测试登录"或"开始采集"
3. 主进程通过 IPC 接收指令 → 启动/通知 Python 子进程
4. Python 使用 Playwright 打开浏览器 → 导航到登录页 → 填写表单
5. 如遇验证码 → 通过 stdio 回调到 Electron → 弹出验证码输入UI → 返回结果
6. 登录成功 → 提取 Cookie/Token → 加密存储到 SQLite
7. 使用凭证构造 HTTP 请求 → 调用目标 API → 解析响应 → 存入 SQLite
8. 进度/结果通过 IPC 实时回传到 Vue 前端展示

### 关键技术决策与理由

1. **Python 作为子进程而非 Node.js 直接调 Playwright**：用户明确要求 Python + Playwright 技术栈，且 Python 在自动化脚本生态（OpenCV验证码识别、requests/httpx、数据处理库）方面更成熟
2. **stdio 方式通信**：相比 Socket/HTTP，stdio 更简单可靠，适合父子进程场景；使用 JSON-RPC 协议格式化消息
3. **SQLite 作为共享数据库**：轻量无需安装、支持并发读写（WAL 模式）、Electron 和 Python 都有成熟的驱动
4. **凭证加密存储**：使用 AES-256-GCM 加密 Cookie/密码，密钥由机器指纹派生
5. **通用型适配策略**：每个商家的登录流程和数据接口通过 JSON 配置文件定义，包括 CSS 选择器、API 路径、字段映射等，无需为每个商家硬编码逻辑

## Implementation Details

### 核心目录结构

```
finance_tools/
├── electron/                          # Electron 主应用
│   ├── main.ts                        # [NEW] 主进程入口，窗口创建、IPC注册、Python进程管理
│   ├── preload.ts                     # [NEW] Preload脚本，暴露安全的IPC通信API给渲染进程
│   ├── ipc/                           # [NEW] IPC 处理器目录
│   │   ├── handlers.ts                # [NEW] 所有IPC消息处理函数（商家CRUD、任务控制、事件推送）
│   │   └── channels.ts                # [NEW] IPC通道常量定义
│   ├── python-manager.ts             # [NEW] Python子进程管理（启动、监控、消息收发、异常重启）
│   └── package.json                   # [NEW] Electron依赖配置
│
├── src/                               # Vue 渲染进程前端
│   ├── App.vue                        # [NEW] 根组件
│   ├── main.ts                        # [NEW] Vue入口
│   ├── views/                         # [NEW] 页面视图
│   │   ├── Dashboard.vue              # [NEW] 仪表盘总览（任务状态、最近采集记录）
│   │   ├── MerchantConfig.vue         # [NEW] 商家配置管理页（列表、添加、编辑、删除）
│   │   ├── TaskCenter.vue             # [NEW] 任务调度中心（启动/停止采集、实时日志）
│   │   ├── DataView.vue               # [NEW] 数据查看页（表格展示、筛选、导出）
│   │   └── CaptchaDialog.vue          # [NEW] 验证码输入弹窗（滑块手动操作/短信输入）
│   ├── components/                    # [NEW] 公共组件
│   │   ├── MerchantForm.vue           # [NEW] 商家配置表单（URL、账号密码、选择器规则）
│   │   ├── TaskCard.vue               # [NEW] 任务卡片组件
│   │   ├── LogViewer.vue              # [NEW] 实时日志查看器
│   │   └── StatusBadge.vue            # [NEW] 状态标识组件
│   ├── stores/                        # [NEW] Pinia 状态管理
│   │   ├── merchant.ts                # [NEW] 商家配置状态
│   │   ├── task.ts                    # [NEW] 任务运行状态
│   │   └── app.ts                     # [NEW] 全局应用状态
│   ├── api/                           # [NEW] API 调用封装（IPC调用）
│   │   ├── merchant.ts                # [NEW] 商家相关API
│   │   ├── task.ts                    # [NEW] 任务相关API
│   │   └── data.ts                    # [NEW] 数据查询API
│   ├── router/                        # [NEW] Vue Router 配置
│   ├── styles/                        # [NEW] 全局样式
│   ├── vite.config.ts                 # [NEW] Vite配置（Electron插件）
│   ├── tsconfig.json                  # [NEW] TypeScript配置
│   └── package.json                   # [NEW] 前端依赖配置
│
├── python/                            # Python 后端引擎
│   ├── main.py                        # [NEW] Python入口，JSON-RPC stdin/stdout消息循环
│   ├── engine/                        # [NEW] 引擎核心模块
│   │   ├── __init__.py
│   │   ├── login_engine.py            # [NEW] Playwright登录引擎（流程编排、状态机）
│   │   ├── captcha_handler.py         # [NEW] 验证码处理器（滑块识别+短信回调）
│   │   ├── credential_manager.py      # [NEW] 凭证管理（Cookie加密存储、有效期、刷新）
│   │   ├── data_collector.py          # [NEW] 数据采集器（HTTP请求、重试、限流）
│   │   └── config_parser.py           # [NEW] 配置解析器（商家配置JSON解析与校验）
│   ├── captcha/                       # [NEW] 验证码识别模块
│   │   ├── __init__.py
│   │   ├── slider_solver.py           # [NEW] 滑块验证码求解器（OpenCV缺口检测+轨迹模拟）
│   │   └── slider_tracker.py          # [NEW] 人类行为轨迹模拟（加速/减速/抖动）
│   ├── models/                        # [NEW] 数据模型
│   │   ├── __init__.py
│   │   ├── merchant.py                # [NEW] 商家配置模型
│   │   ├── credential.py              # [NEW] 凭证模型
│   │   └── collected_data.py          # [NEW] 采集数据模型
│   ├── db/                            # [NEW] 数据库层
│   │   ├── __init__.py
│   │   ├── database.py                # [NEW] SQLite数据库初始化与连接管理
│   │   ├── migrations.py              # [NEW] 建表SQL迁移脚本
│   │   └── repositories.py            # [NEW] 数据访问对象（CRUD操作）
│   ├── utils/                         # [NEW] 工具函数
│   │   ├── crypto.py                  # [NEW] 加解密工具（AES-256-GCM）
│   │   ├── logger.py                  # [NEW] 日志工具
│   │   └── helpers.py                 # [NEW] 通用辅助函数
│   ├── protocols/                     # [NEW] 通信协议
│   │   ├── __init__.py
│   │   ├── messages.py                # [NEW] JSON-RPC 消息类型定义
│   │   └── codec.py                   # [NEW] 消息编解码
│   └── requirements.txt               # [NEW] Python依赖清单
│
├── shared/                            # 共享资源
│   ├── db/                            # [NEW] SQLite数据库文件目录
│   │   └── finance_tools.db           # [GEN] 运行时生成的SQLite数据库文件
│   └── schemas/                       # [NEW] 数据库Schema定义
│       └── init.sql                   # [NEW] 初始化SQL脚本（建表语句）
│
├── resources/                         # [NEW] 应用资源（图标等）
├── package.json                       # [NEW] 根package.json（workspace管理）
├── tsconfig.base.json                 # [NEW] 基础TS配置
└── README.md                          # [NEW] 项目说明文档
```

### 关键实现要点

- **Playwright 登录流程状态机**：`INIT -> NAVIGATE -> FILL_FORM -> HANDLE_CAPTCHA(可选) -> SUBMIT -> VERIFY_SUCCESS -> EXTRACT_COOKIE -> DONE`
- **滑块验证码处理**：OpenCV 边缘检测找缺口位置 → 生成拟人拖拽轨迹 → Playwright 模拟鼠标拖拽 → 支持失败重试
- **短信验证码处理**：Python 检测到短信验证需求 → 通过 stdio 发送 `captcha:sms_required` 消息 → Electron 收到后弹出输入框 → 用户输入后回传 → Python 填入提交
- **Cookie 持久化**：登录成功后从 browser_context.cookies() 提取 → AES 加密 → 存储 SQLite（含过期时间）→ 下次采集时先检查有效性 → 即将过期则重新走登录流程
- **并发控制**：每个商家独立 browser context，支持多商家并行采集；限制并发数避免资源耗尽

## 设计概述

采用现代深色主题的桌面应用设计风格，参考专业运维/DevOps工具的视觉语言。整体界面以深灰色为底，搭配青蓝色作为主强调色，营造专业、高效的工具感。布局上采用左侧固定导航栏 + 右侧内容区的经典桌面应用布局。

## 页面规划

共设计5个核心页面，形成完整的操作闭环。

### Page 1: Dashboard 仪表盘

顶部统计卡片区显示：已配置商家数、今日采集次数、凭证有效/失效数、数据总量。下方为最近采集活动时间线和快捷操作按钮区。

### Page 2: MerchantConfig 商家配置管理

左侧商家列表（卡片形式，显示名称、URL、状态徽标），右侧为配置编辑表单。表单包含基本信息（名称、URL、图标）、登录配置（登录页URL、账号输入框选择器、密码输入框选择器、提交按钮选择器）、高级设置（验证码类型、自定义Headers、Cookie域名白名单）。

### Page 3: TaskCenter 任务调度中心

上方为全局控制条（一键全部采集/停止），下方为各商家任务卡片网格。每张卡片显示商家名称、当前状态（空闲/登录中/采集中/异常）、进度条、上次采集时间、操作按钮。点击卡片展开实时日志面板。

### Page 4: DataView 数据查看

顶部工具栏包含商家筛选、日期范围选择、搜索框、导出按钮。主体为 Element Plus Table 展示采集的原始数据，支持列配置、排序、分页。

### Page 5: CaptchaDialog 验证码处理弹窗（模态对话框）

滑块验证码模式：展示截图预览区域 + 可交互滑块控件（允许用户手动辅助）。短信验证码模式：大号输入框 + 倒计时提示 + 发送状态显示。

## 单页面Block设计（以TaskCenter为例）

### Block 1: 顶部导航与全局控制栏

固定在页面顶部的水平工具栏，左侧显示页面标题"任务调度中心"，右侧放置"全部开始"和"全部停止"两个主操作按钮，以及刷新按钮。使用深色次级背景与内容区区分。

### Block 2: 任务状态概览条

紧贴控制栏下方的横向信息条，用4个带图标的统计数字分别展示：运行中任务数、排队中任务数、成功数、失败数。数字使用主色调高亮。

### Block 3: 任务卡片网格区

主体内容区，采用响应式网格布局（自适应列数）。每个任务卡片包含：商家头像/图标、商家名称、当前状态（彩色脉冲指示灯）、进度环或进度条、操作按钮组（开始/停止/查看日志）。卡片悬停时有微妙上浮阴影效果。

### Block 4: 日志详情抽屉

从右侧滑出的 Drawer 面板，展示选中任务的详细执行日志。日志支持自动滚动到底部、关键字高亮、复制功能。底部有清空日志按钮。

## Agent Extensions

- **Browser Automation**
- Purpose: 为 Playwright 浏览器自动化提供最佳实践指导，包括页面交互、元素定位、表单填充等技术细节
- Expected outcome: 确保登录引擎的 Playwright 实现遵循行业标准，元素选择器策略合理，反检测措施到位
- **playwright-cli**
- Purpose: 提供 Playwright CLI 工具的使用指导，帮助调试和验证浏览器自动化流程
- Expected outcome: 在开发过程中能够快速测试和调试登录流程、验证码处理等关键环节