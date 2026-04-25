# Finance Tools - 自动化浏览器数据采集工具

基于 **Electron + Python + Playwright** 的桌面应用，用于多商家端自动登录、验证码处理、凭证管理及数据采集。

## 技术架构

```
┌─────────────────────────────────────────────┐
│              Electron 桌面应用                 │
│  ┌──────────────────┐  ┌────────────────┐   │
│  │ Vue 3 渲染进程    │  │ Electron 主进程 │   │
│  │ (Element Plus)   │◄─►│ IPC 通信      │   │
│  ├──────────────────┤  ├──┬─────────────┤   │
│  │ 商家配置/任务调度  │  │ Python 子进程  │   │
│  │ 数据查看/验证码    │  │  ┌───────────┐│   │
│  └──────────────────┘  │  │Playwright   ││   │
│                        │  │(登录+验证码) ││   │
│                        │  ├───────────┤│   │
│                        │  │HTTP 采集    ││   │
│                        │  │(httpx+Cookie)│   │
│                        │  ├───────────┤│   │
│                        │  │SQLite 存储  ││   │
│                        │  └───────────┘│   │
│                        └────────────────┘   │
└─────────────────────────────────────────────┘
```

## 核心功能

| 功能 | 描述 |
|------|------|
| 商家配置管理 | GUI 界面配置多个商家端 URL、账号密码、选择器规则 |
| Playwright 自动化 | 浏览器自动化登录，支持表单填写、页面导航 |
| 验证码处理 | 滑块验证码（OpenCV 自动识别 + 轨迹模拟）、短信验证码（UI 弹窗） |
| 凭证加密存储 | AES-256-GCM 加密 Cookie，机器指纹派生密钥 |
| HTTP 数据采集 | httpx 携带 Cookie 调用 API，支持分页、重试、限流 |
| 本地 SQLite | 存储商家配置、凭证、采集数据，支持 Excel 导出 |

## 项目结构

```
finance_tools/
├── electron/                  # Electron 主进程（窗口、IPC、Python 管理）
│   ├── main.ts                # 入口 & IPC 注册
│   ├── preload.ts             # 安全桥接脚本
│   └── python-manager.ts      # Python 子进程管理器
├── src/                       # Vue 3 前端渲染进程
│   ├── views/                 # 页面组件
│   │   ├── Dashboard.vue      # 仪表盘总览
│   │   ├── MerchantConfig.vue # 商家配置管理
│   │   ├── TaskCenter.vue     # 任务调度中心
│   │   ├── DataView.vue       # 数据查看与导出
│   │   └── CaptchaDialog.vue  # 验证码输入弹窗
│   ├── components/            # 公共组件
│   ├── stores/                # Pinia 状态管理
│   ├── api/                   # API 封装层
│   └── styles/                # 全局样式 (Tailwind)
├── python/                    # Python 后端引擎
│   ├── main.py                # JSON-RPC 消息循环入口
│   ├── engine/                # 核心引擎模块
│   │   ├── login_engine.py    # Playwright 登录状态机
│   │   ├── captcha_handler.py # 验证码处理器
│   │   ├── credential_manager.py # 凭证加密管理
│   │   ├── data_collector.py  # HTTP 数据采集器
│   │   └── config_parser.py   # 配置解析校验
│   ├── db/                    # 数据库层 (SQLite)
│   │   ├── database.py        # 初始化 & 连接管理
│   │   ├── migrations.py      # Schema 建表 SQL
│   │   └── repositories.py    # CRUD 操作封装
│   └── utils/                 # 工具函数
│       ├── crypto.py          # AES-256-GCM 加解密
│       ├── logger.py          # 日志配置
│       └── helpers.py         # 辅助函数
├── shared/
│   ├── db/finance_tools.db    # 运行时生成的数据库文件
│   └── schemas/init.sql       # 初始化建表脚本
├── package.json               # 根项目配置
└── README.md                  # 项目文档
```

## 快速开始

### 前提条件

- Node.js >= 18.0
- Python >= 3.10
- npm / pnpm / yarn

### 安装步骤

```bash
# 1. 克隆或进入项目目录
cd finance_tools

# 2. 安装前端依赖
cd src && npm install && cd ..

# 3. 安装 Electron 依赖
npm install

# 4. 创建 Python 虚拟环境并安装依赖
python3 -m venv python/.venv
source python/.venv/bin/activate  # Linux/Mac
# python\.venv\Scripts\activate  # Windows

pip install -r python/requirements.txt

# 5. 安装 Playwright 浏览器
playwright install chromium

# 6. 启动开发模式
npm run dev
```

### 开发模式运行

```bash
# 终端1: 启动 Vite 开发服务器
cd src && npm run dev

# 终端2: 启动 Electron
npm run dev:electron
```

或使用 concurrently 一键启动：
```bash
npm run dev
```

### 桌面端打包

```bash
# Windows x64
npm run build

# macOS: 同时生成 Intel(x64) 和 Apple Silicon(arm64) DMG
npm run build:mac

# macOS: 只生成 Intel 包
npm run build:mac:x64

# macOS: 只生成 Apple Silicon 包
npm run build:mac:arm64

# macOS: 生成 universal 包
npm run build:mac:universal
```

> 注意：如果后续将 `resources/python-runtime` 打入安装包，macOS 也需要准备对应架构的 Python runtime；Intel 包使用 x64 runtime，Apple Silicon 包使用 arm64 runtime，universal 包需要确认所有原生依赖都支持 universal 或在运行时正确选择架构。

## 使用说明

### 业务采集配置文档

浏览器自动化、抓包 CURL、动态参数、Storage / Session / Cookie 取值规则见：

- [自动化业务采集配置说明](docs/automation-capture.md)

### 1. 配置商家

进入「商家配置」页面 → 点击「添加商家」→ 填写：
- **基本信息**：名称、访问地址、登录页地址
- **登录凭证**：账号和密码
- **高级设置**：验证码类型（无/滑块/短信）、CSS 选择器

### 2. 执行采集任务

进入「任务调度」页面 → 点击「开始采集」或「全部开始采集」

系统将自动执行：
1. 打开浏览器访问商家登录页
2. 填写账号密码
3. 如遇滑块验证码 → OpenCV 自动识别缺口并模拟拖拽
4. 如遇短信验证码 → 弹出 UI 让用户手动输入
5. 登录成功后提取 Cookie 并加密保存
6. 使用 Cookie 调用目标 API 获取业务数据
7. 解析数据并存入本地 SQLite 数据库

### 3. 查看数据

进入「数据查看」页面 → 筛选查看已采集数据 → 支持导出 Excel

## 验证码处理机制

### 滑块验证码
1. 截取验证码图片
2. 使用 OpenCV Canny 边缘检测识别缺口位置
3. 生成拟人化拖拽轨迹（加速→匀速→减速→微调回弹）
4. Playwright 模拟鼠标拖拽操作
5. 失败时自动重试，超过阈值则请求手动协助

### 短信验证码
1. Python 检测到短信验证需求
2. 通过 JSON-RPC 发送 `captcha:required` 事件给 Electron
3. Electron 弹出 CaptchaDialog 输入框
4. 用户输入后通过 `captcha:resolve` 回传结果
5. Python 将验证码填入提交

## 安全设计

- **Cookie 加密**：AES-256-GCM 对称加密，密钥由机器指纹 PBKDF2 派生
- **密码存储**：商家密码同样加密存储在本地数据库
- **IPC 安全**：使用 preload 脚本白名单限制可调用的 IPC 通道
- **沙箱隔离**：渲染进程启用 contextIsolation 和 sandbox
- **文件权限**：密钥文件设置为仅当前用户可读写 (chmod 600)

## 通用适配

每个商家的配置完全独立，支持：

- 自定义登录页 CSS 选择器
- 多个 API 数据接口配置
- 字段映射转换
- 分页参数自定义
- 请求头自定义
- Cookie 域名白名单

无需修改代码即可适配不同商家系统。

## License

MIT
