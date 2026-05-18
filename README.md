# Desktop Agent

Desktop Agent 是一个运行在本机的桌面级个人 Agent：Electron + React 提供图形界面，Python + FastAPI 提供 Agent 后端，二者通过 WebSocket 和 REST API 通信。

当前仓库已完成第一阶段质量清理：产品代码、测试、文档和模板保留在仓库中；会话、计划、工作流、截图、Personal Agent 记忆等运行时数据写入用户数据目录，不再污染 git worktree。

## 核心能力

| 能力 | 说明 |
| --- | --- |
| 多模型路由 | 通过 LiteLLM 接入 OpenAI、Anthropic、Kimi、Ollama 及兼容 OpenAI API 的端点 |
| ReAct Agent | 自动推理、选择工具、执行、观察并继续迭代 |
| 文件与终端 | 本地文件读写、搜索、删除，以及受保护的 shell 命令执行 |
| 浏览器自动化 | Playwright 驱动的页面导航、点击、输入、截图和脚本执行 |
| 桌面与应用控制 | PyAutoGUI、pynput、pywinauto、pywin32 支持键鼠、窗口和应用操作 |
| 本地知识库 | sentence-transformers + sqlite-vec 提供文档索引和语义搜索 |
| 工作流与计划 | 录制、回放工作流，并把结构化计划保存到运行时目录 |
| MCP 扩展 | 作为 MCP 客户端动态接入外部工具服务器 |
| Personal / Coding Agent | 通过 `AGENTS/` 种子模板初始化不同 Agent 的身份、规则和技能 |

## 仓库结构

```text
desktop-agent/
├── AGENTS/                 # Agent 种子模板；运行时会复制到用户数据目录
├── backend/                # Python FastAPI 后端
│   ├── app/
│   │   ├── main.py         # FastAPI 入口、WebSocket、REST API
│   │   ├── agent.py        # AgentSession 与 ReAct 循环
│   │   ├── runtime_paths.py # 仓库路径、用户数据目录和运行时目录解析
│   │   ├── agents/         # Personal/Coding Agent 管理
│   │   ├── routes/         # REST 路由
│   │   ├── tools/          # 文件、终端、浏览器、桌面、Git、RAG、MCP 等工具
│   │   ├── rag/            # 本地知识库引擎
│   │   └── workflow/       # 计划和工作流存储
│   ├── tests/              # pytest 测试
│   ├── requirements.txt
│   ├── pytest.ini
│   └── start.py
├── config/
│   ├── models.yaml         # 模型配置模板，使用环境变量占位
│   └── mcp.yaml            # MCP server 配置模板
├── docs/
│   └── QUALITY_REVIEW.md   # 第一阶段质量审查记录
├── frontend/               # Electron + React + Vite 前端
│   ├── src/                # React 渲染进程
│   ├── src-main/           # Electron 主进程和 preload
│   ├── e2e/                # Playwright E2E 测试
│   ├── package.json
│   └── vite.config.ts
├── install.ps1 / install.bat
├── start-all.ps1 / start-all.bat
└── README.md
```

根目录不再保留 npm 包配置；前端相关 npm 命令统一在 `frontend/` 下执行。

## 运行时目录

`backend/app/runtime_paths.py` 统一管理运行时路径。

优先级最高的是环境变量：

```powershell
$env:DESKTOP_AGENT_USER_DATA_DIR="D:\DesktopAgentData"
```

未设置时默认使用系统用户数据目录：

| 平台 | 默认目录 |
| --- | --- |
| Windows | `%APPDATA%\Desktop Agent` |
| macOS | `~/Library/Application Support/Desktop Agent` |
| Linux | `$XDG_CONFIG_HOME/Desktop Agent` 或 `~/.config/Desktop Agent` |

后端运行时根目录为：

```text
<user-data-dir>/backend/
```

主要运行时数据包括：

```text
<user-data-dir>/backend/AGENTS/      # Agent 身份、记忆、日记、技能等可变数据
<user-data-dir>/backend/config/      # 用户模型配置副本
<user-data-dir>/backend/sessions/    # 会话 JSON
<user-data-dir>/backend/plans/       # 计划 markdown
<user-data-dir>/backend/workflows/   # 工作流 JSON
<user-data-dir>/backend/preview/     # 回测报告、预览文件等
<user-data-dir>/backend/data/        # 本地知识库等数据文件
```

首次启动会从仓库中的 `AGENTS/` 和 `config/models.yaml` 复制缺失模板到运行时目录；已存在的用户文件不会被覆盖。

## 环境要求

- Windows 是主要目标平台；桌面和应用控制依赖 Windows API。
- Python 3.11+。
- Node.js 18+。
- Playwright Chromium：后端浏览器工具需要安装。

## 安装

一键安装：

```powershell
.\install.ps1
```

手动安装：

```powershell
cd backend
python -m venv venv
.\venv\Scripts\activate
pip install -r requirements.txt
playwright install chromium

cd ..\frontend
npm install
```

## 启动

一键启动：

```powershell
.\start-all.ps1
```

手动启动后端：

```powershell
cd backend
.\venv\Scripts\python.exe start.py
```

后端默认监听 `http://127.0.0.1:8765`。

手动启动前端：

```powershell
cd frontend
npm run dev
```

开发模式会启动 Vite 并打开 Electron 窗口。

## 配置 API Key

仓库内的 `config/models.yaml` 是模板，使用环境变量占位：

```yaml
providers:
  openai:
    api_key: ${OPENAI_API_KEY}
  anthropic:
    api_key: ${ANTHROPIC_API_KEY}
  kimi:
    base_url: https://api.kimi.com/coding
    api_key: ${KIMI_API_KEY}
```

推荐在 PowerShell 中设置环境变量：

```powershell
$env:OPENAI_API_KEY="<your-openai-key>"
$env:ANTHROPIC_API_KEY="<your-anthropic-key>"
$env:KIMI_API_KEY="<your-kimi-key>"
```

也可以在应用设置页编辑 Provider。保存后的用户配置写入运行时目录下的 `backend/config/models.yaml`，不会修改仓库模板。

不要把真实 API Key 提交到仓库。如果历史版本曾经包含真实密钥，请在对应平台轮换旧密钥。

## 测试与构建

后端：

```powershell
cd backend
.\venv\Scripts\python.exe -m pytest -q
```

后端测试会把 `DESKTOP_AGENT_USER_DATA_DIR` 指向系统临时目录，避免向仓库写入 plan、session、workflow 或 Personal Agent 记忆。

前端：

```powershell
cd frontend
npx vitest run
npm run build
```

收尾检查：

```powershell
git diff --check
git status --short
```

## 生产构建

```powershell
cd frontend
npm run build
npm run dist
```

`npm run build` 输出到 `frontend/dist/`，`npm run dist` 调用 electron-builder 并输出到 `frontend/release/`。当前后端仍以源码方式运行；如需完整分发安装包，需要单独补齐 Python 后端 exe 打包流程。

## WebSocket 协议概览

前端通过 `/ws/{session_id}` 与后端建立 WebSocket。

前端发送：

- `chat`: 用户消息，支持 `text`、`model_id`、`image_base64`
- `clear`: 清空会话
- `stop`: 中断当前 Agent 循环
- `retry`: 重试最后一次回复
- `tool_direct`: 调用白名单内的安全直连工具

后端发送：

- `content`: 助手文本流
- `reasoning`: 模型 reasoning/thinking 文本
- `tool_call`: 工具调用记录
- `image`: 图片数据
- `status`: `thinking`、`executing`、`completed` 等状态
- `error`: 错误信息
- `done`: 单次交互结束

## 开发提示

- 新工具放在 `backend/app/tools/`，继承 `BaseTool` 并在 `backend/app/tools/__init__.py` 注册。
- 普通文件工具的工作区根是仓库根目录。
- `AGENTS/...` 相对路径会被解析到运行时 `backend/AGENTS/`，用于 Personal/Coding Agent 的身份和记忆文件。
- 会话、计划、工作流、预览、知识库和模型缓存都是运行时数据，不应提交到 git。
- 修改公共协议、工具 schema 或 REST 响应前，请同步更新测试和文档。

## 安全提示

- `shell_execute` 内置危险命令拦截，但仍不建议在高权限账号下长期运行。
- PyAutoGUI 的 FAILSAFE 可通过把鼠标移动到屏幕左上角触发。
- Electron 当前为本地资源加载关闭了部分 web security，打包前需继续审查安全边界。
- 真实 API Key 只应放在环境变量或本机运行时配置中。
