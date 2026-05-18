# Desktop Agent — AI 编码代理指南

> 本文档面向 AI 编码代理。人类开发者请优先阅读 `README.md`。

## 项目概览

Desktop Agent 是一个本机桌面级个人 Agent，采用前后端分离架构：

- 前端：Electron + React 18 + Vite + TailwindCSS + TypeScript
- 后端：Python 3.11+ + FastAPI + LiteLLM
- 通信：WebSocket 负责实时 Agent 交互，REST API 负责配置、状态、资源管理
- 主要平台：Windows，桌面自动化依赖 pywinauto、pywin32、PyAutoGUI 和 PowerShell

Agent 基于 ReAct 循环运行：接收用户指令，调用模型推理，选择工具，执行并观察结果，直到任务完成或触达停止条件。支持 OpenAI、Anthropic、Kimi、Ollama 和兼容 OpenAI API 的模型端点。

## 仓库边界

仓库只应保存产品代码、测试、文档和种子模板。运行时数据必须写入用户数据目录，不要写回 repo。

重要路径：

- `backend/app/runtime_paths.py`：运行时路径的唯一来源。
- `AGENTS/`：仓库内 Agent 种子模板。首次运行时复制到 runtime，之后 runtime 文件独立演进。
- `<user-data>/backend/AGENTS/`：Personal/Coding Agent 的可变身份、记忆、日记、技能和 handoff 文件。
- `<user-data>/backend/config/models.yaml`：用户模型配置副本。
- `<user-data>/backend/sessions/`、`plans/`、`workflows/`、`preview/`、`data/`：会话、计划、工作流、预览和本地数据。

`DESKTOP_AGENT_USER_DATA_DIR` 拥有最高优先级。未设置时默认目录为：

- Windows：`%APPDATA%\Desktop Agent`
- macOS：`~/Library/Application Support/Desktop Agent`
- Linux：`$XDG_CONFIG_HOME/Desktop Agent` 或 `~/.config/Desktop Agent`

编码代理写 Agent 身份或记忆文件时，应使用 `AGENTS/...` 路径或 `agents_dir()` 解析出的 runtime 路径。普通项目文件仍以仓库根作为工作区根。

## 项目结构

```text
desktop-agent/
├── AGENTS/                 # Agent 种子模板，不保存个人运行时记忆
├── backend/
│   ├── app/
│   │   ├── main.py         # FastAPI、WebSocket、REST API
│   │   ├── agent.py        # AgentSession 与 ReAct 循环
│   │   ├── runtime_paths.py # runtime/repo/bundled 路径解析
│   │   ├── agents/         # Personal/Coding Agent 管理
│   │   ├── routes/         # REST 路由
│   │   ├── tools/          # 文件、终端、浏览器、桌面、Git、RAG、MCP 等工具
│   │   ├── rag/            # 本地知识库
│   │   ├── workflow/       # 计划和工作流
│   │   └── mcp/            # MCP 客户端集成
│   ├── tests/              # pytest 测试
│   ├── requirements.txt
│   ├── pytest.ini
│   └── start.py
├── config/
│   ├── models.yaml         # 模型配置模板，使用环境变量占位
│   └── mcp.yaml
├── docs/
├── frontend/
│   ├── src/                # React 渲染进程
│   ├── src-main/           # Electron 主进程和 preload
│   ├── e2e/                # 前端 E2E 测试
│   └── package.json
└── README.md
```

根目录没有有效 npm package；前端 npm 命令必须在 `frontend/` 下运行。

## 核心模块

后端：

- `app/main.py`：应用实例、生命周期、WebSocket、REST router 注册。
- `app/agent.py`：会话加载/保存、ReAct loop、模型调用、工具执行、状态推送。
- `app/models.py`：LiteLLM 路由与 provider 适配。
- `app/config.py`：解析 `models.yaml`，支持 `${ENV_VAR}`。
- `app/security.py`：本地认证 token 与 API 中间件。
- `app/tools/`：所有 Agent 工具实现和动态 MCP 工具注册。
- `app/workflow/plan_files.py`：结构化计划保存到 runtime `plans/`。
- `app/workflow/storage.py`：工作流保存到 runtime `workflows/`。

前端：

- `frontend/src/App.tsx`：主布局与高层状态。
- `frontend/src/components/ChatPanel.tsx`：聊天与消息展示。
- `frontend/src/components/Sidebar.tsx`：模型、会话、快捷入口。
- `frontend/src-main/main.js`：Electron 窗口和后端子进程管理。
- `frontend/src-main/preload.js`：安全暴露 Electron API。

## 开发命令

后端：

```powershell
cd backend
.\venv\Scripts\python.exe start.py
.\venv\Scripts\python.exe -m pytest -q
```

前端：

```powershell
cd frontend
npm run dev
npx vitest run
npm run build
```

一键脚本：

```powershell
.\install.ps1
.\start-all.ps1
```

## 配置与密钥

`config/models.yaml` 是模板，不应包含真实密钥。使用环境变量占位：

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

应用启动时会把模板复制到 runtime `backend/config/models.yaml`。用户在设置页保存 Provider 时，只修改 runtime 配置。不要把真实 API Key 写入仓库；如果发现历史密钥泄露，应在平台侧轮换。

## 通信协议

WebSocket 路径为 `/ws/{session_id}`。

前端消息：

- `chat`：发送用户输入，可包含 `text`、`model_id`、`image_base64`
- `clear`：清空当前会话
- `stop`：中断正在运行的 Agent
- `retry`：重试最后一条 assistant 消息
- `tool_direct`：调用白名单内的安全直连工具

后端事件：

- `content`：助手文本流
- `reasoning`：模型 reasoning/thinking 文本
- `tool_call`：工具调用记录
- `image`：图片数据
- `status`：`thinking`、`executing`、`completed`、`max_iterations_reached` 等
- `error`：错误信息
- `done`：一次交互结束

除非用户明确要求，本阶段不要改变 WebSocket 协议、工具 schema 或 REST 响应结构。

## 添加工具

1. 在 `backend/app/tools/` 新建模块并继承 `BaseTool`。
2. 返回 `ToolResult(output=...)` 或 `ToolResult(error=...)`，不要让常规工具错误冒泡到 Agent loop。
3. 在 `backend/app/tools/__init__.py` 注册工具实例。
4. 为参数校验、错误分支和安全边界补测试。

## 测试策略

- 后端测试使用 pytest，LiteLLM 调用应 mock，不需要真实 API Key。
- `backend/tests/conftest.py` 会把 `DESKTOP_AGENT_USER_DATA_DIR` 指向系统临时目录，避免测试污染仓库和真实用户 runtime。
- 涉及 session、plans、workflows、AGENTS runtime 的测试应使用 `tmp_path` 或 monkeypatch runtime path。
- 前端测试使用 Vitest 和 Testing Library，WebSocket 在 setup 中 mock。
- 收尾必须运行 `git diff --check`；功能改动应尽量运行相关后端测试、前端测试和前端 build。

## 代码风格

Python：

- 使用类型注解和清晰的小函数。
- 工具与路由优先 `async def`。
- 使用 repo 现有 helper，不要新造重复路径逻辑。
- 新增运行时文件路径必须走 `runtime_paths.py`。

TypeScript / React：

- 使用函数组件和 Hooks。
- 类型集中放在 `src/types.ts` 或组件附近的明确类型定义。
- 保持现有 Tailwind 风格和组件分层。
- 不要引入新的状态管理库，除非需求明确需要。

## 安全注意

- `shell_tool.py` 有危险命令拦截，但不能视为完整沙箱。
- 文件工具有大小和路径边界，改动时必须保留这些安全检查。
- PyAutoGUI FAILSAFE 可通过鼠标移动到屏幕左上角触发。
- Electron 当前为了本地资源加载关闭了部分 web security，打包前需继续审查。
- MCP 工具必须通过 Agent 调用，不要把未知 MCP 工具加入前端直连白名单。

## 当前技术债

- `backend/app/agent.py`、`frontend/src/App.tsx`、`frontend/src/components/ChatPanel.tsx` 仍偏大，后续适合分阶段拆分。
- Electron 后端 exe 打包流程仍未完全自动化。
- 部分依赖会产生非阻塞 warning，应在依赖升级窗口统一处理。
- 第一阶段清理以行为保持为准，不做大规模架构重写。
