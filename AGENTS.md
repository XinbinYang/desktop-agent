# Desktop Agent — AI 编码代理指南

> 本文档面向 AI 编码代理。如果你是人类开发者，请优先阅读 `README.md`。

---

## 项目概述

Desktop Agent 是一个带 GUI 的**桌面级个人 Agent**，采用前后端分离架构：

- **前端**：Electron + React 18 + Vite + TailwindCSS（TypeScript）
- **后端**：Python 3.11+ + FastAPI + LiteLLM
- **通信**：WebSocket（核心实时交互）+ REST API（配置/状态查询）
- **目标平台**：Windows（主要依赖 pywinauto、pywin32、PowerShell 脚本）

Agent 基于 **ReAct 循环**运行：接收用户指令 → 调用大模型推理 → 自动选择和执行工具 → 观察结果 → 循环直至任务完成。支持多模型切换（OpenAI、Anthropic、Kimi、Ollama 本地模型）。

### 核心能力（工具集）

| 类别 | 工具 | 技术实现 |
|------|------|---------|
| 文件操作 | `file_read/write/list/search/delete` | `aiofiles` + `pathlib` |
| 终端控制 | `shell_execute/start` | `subprocess`（含危险命令拦截） |
| 浏览器自动化 | `browser_navigate/click/type/screenshot/evaluate/close` | Playwright |
| 桌面操控 | `screenshot/mouse_click/move/type/press_key/scroll/get_screen_size` | PyAutoGUI + pynput + Pillow |
| 应用控制 | `app_open/list_windows/find_window/click/type` | pywinauto + pywin32 |
| Git 版本控制 | `git_clone/status/diff/commit/pull/push/branch/remote` | subprocess git |
| 金融数据 | `wind_wsd/wss/wset/edb/tdays` | Wind 金融终端 API（可选） |
| 数据同步 | `wind_sync` | WIND → SQLite 增量同步 |
| 策略回测 | `strategy_list/backtest_run/backtest_report` | pandas + SQLite |
| 知识库（RAG） | `knowledge_index/search/list/clear` | sentence-transformers + sqlite-vec |
| 工作流录制 | `workflow_record/stop/list/run` | JSON 步骤录制与回放 |
| Worker 派发 | `dispatch_worker/parallel` | 并行子 Agent |
| MCP 外部工具 | `mcp_{server}_{tool}` (动态注册) | MCP SDK (stdio/SSE) |
| 语音输入 | `/api/transcribe` | faster-whisper（本地推理） |

---

## 项目结构

```
desktop-agent/
├── backend/                 # Python Agent 后端
│   ├── app/
│   │   ├── main.py         # FastAPI 入口 + WebSocket 路由 + REST API
│   │   ├── agent.py        # AgentSession（ReAct 循环核心）
│   │   ├── models.py       # ModelRouter（多模型路由，LiteLLM + Kimi Anthropic 兼容）
│   │   ├── config.py       # 配置管理（models.yaml 解析）
│   │   ├── transcribe.py   # Whisper 语音识别（faster-whisper）
│   │   ├── skills.py       # Superpowers 技能匹配引擎
│   │   ├── roles.py        # 内置角色管理（desktop-agent/code-expert 等）
│   │   ├── security.py     # 本地认证中间件
│   │   ├── runtime_paths.py # 运行时路径解析
│   │   ├── message_utils.py # 消息裁剪 / 工具执行公共逻辑
│   │   ├── credential_manager.py # Git 凭据管理
│   │   ├── project_manager.py    # 项目上下文管理
│   │   ├── routes/          # REST 路由模块
│   │   │   ├── settings.py
│   │   │   ├── projects.py
│   │   │   ├── knowledge.py # 知识库索引/搜索/删除 API
│   │   │   └── workflows.py
│   │   ├── tools/          # 工具实现目录
│   │   │   ├── base.py     # BaseTool / ToolResult 抽象基类
│   │   │   ├── __init__.py # ALL_TOOLS 注册表 + DynamicToolRegistry
│   │   │   ├── file_tool.py
│   │   │   ├── shell_tool.py
│   │   │   ├── browser_tool.py
│   │   │   ├── desktop_tool.py
│   │   │   ├── app_tool.py
│   │   │   ├── wind_tool.py
│   │   │   ├── wind_sync_tool.py
│   │   │   ├── backtest_tool.py
│   │   │   ├── git_tool.py
│   │   │   ├── knowledge_tool.py  # RAG 知识库工具
│   │   │   ├── workflow_tool.py
│   │   │   ├── worker_tool.py
│   │   │   └── mcp_tool.py       # MCP 工具代理
│   │   ├── rag/            # RAG 知识库引擎
│   │   │   ├── engine.py   # RAGEngine：索引、搜索、清空
│   │   │   ├── embedding.py # 嵌入模型（sentence-transformers）
│   │   │   ├── splitter.py  # 递归字符分割器
│   │   │   └── models.py   # DocumentChunk / SearchResult
│   │   └── mcp/            # MCP 集成
│   │       ├── client.py   # MCPClientWrapper（stdio/SSE 连接）
│   │       ├── manager.py  # McpManager（多服务器生命周期）
│   │       └── models.py   # McpServerConfig / McpServerStatus
│   ├── tests/              # pytest 测试
│   │   ├── conftest.py     # 共享 fixtures（client、mock_litellm、temp_dir 等）
│   │   ├── test_agent.py   # AgentSession 单元测试
│   │   ├── test_main.py    # API / WebSocket 路由测试
│   │   ├── test_models.py
│   │   ├── test_config.py
│   │   └── test_tools/     # 各工具单元测试
│   ├── sessions/           # 会话持久化 JSON 文件（运行时生成）
│   ├── preview/            # 代码预览静态文件目录（运行时生成）
│   ├── models/whisper/     # Whisper 模型缓存目录
│   ├── requirements.txt    # Python 依赖
│   ├── pytest.ini          # pytest 配置
│   └── start.py            # uvicorn 启动脚本（127.0.0.1:8765）
│
├── frontend/               # Electron + React 前端
│   ├── src/                # React 渲染进程源码
│   │   ├── App.tsx         # 主布局（三栏：侧边栏 + 聊天/终端 + 工具/预览）
│   │   ├── main.tsx        # ReactDOM 挂载入口
│   │   ├── index.css       # Tailwind 基础样式
│   │   ├── types.ts        # TypeScript 类型定义
│   │   ├── config.ts       # API_BASE / WS_BASE 常量
│   │   ├── components/
│   │   │   ├── ChatPanel.tsx      # 聊天消息面板
│   │   │   ├── Sidebar.tsx        # 左侧边栏（模型切换、快捷工具、会话列表）
│   │   │   ├── TerminalPanel.tsx  # 底部终端日志
│   │   │   ├── ToolCallView.tsx   # 右侧工具调用历史
│   │   │   ├── PreviewPanel.tsx   # 右侧预览面板（iframe 加载 /preview）
│   │   │   └── ErrorBoundary.tsx  # 全局错误边界
│   │   └── __tests__/      # Vitest 前端测试
│   │       ├── setup.ts    # 全局 mock（WebSocket 等）
│   │       ├── App.test.tsx
│   │       ├── config.test.ts
│   │       └── components/
│   ├── src-main/           # Electron 主进程
│   │   ├── main.js         # Electron 窗口、菜单、后端子进程管理
│   │   └── preload.js      # contextBridge 暴露安全 API
│   ├── dist/               # Vite 构建输出（Electron 加载）
│   ├── package.json        # npm 依赖与 electron-builder 配置
│   ├── tsconfig.json       # TypeScript 配置
│   ├── vite.config.ts      # Vite 配置（base: './', port 5173）
│   ├── tailwind.config.js  # Tailwind 配置（自定义 agent 色板）
│   └── index.html          # HTML 模板
│
├── config/
│   ├── models.yaml         # 模型提供商与 API Key 配置
│   └── mcp.yaml            # MCP Server 配置（外部工具扩展）
│
├── install.ps1 / install.bat      # 一键安装脚本（创建 venv、npm install、playwright）
├── start-all.ps1 / start-all.bat  # 一键启动脚本（后端 + Vite + Electron）
└── README.md               # 人类可读的项目说明
```

---

## 技术栈详情

### 后端

| 依赖 | 版本 | 用途 |
|------|------|------|
| fastapi | 0.115.0 | Web 框架 |
| uvicorn[standard] | 0.32.0 | ASGI 服务器 |
| websockets | 13.1 | WebSocket 支持 |
| litellm | 1.52.0 | 统一多模型调用（OpenAI/Anthropic/Ollama） |
| openai | 1.54.0 | OpenAI SDK（备用） |
| anthropic | 0.39.0 | Anthropic SDK（备用） |
| playwright | 1.48.0 | 浏览器自动化 |
| pyautogui | 0.9.54 | 桌面键鼠控制 |
| pynput | 1.7.7 | 键盘监听 |
| pillow | 11.0.0 | 图像处理 |
| psutil | 6.1.0 | 系统进程信息 |
| pywinauto | 0.6.9 | Windows 应用 UI 自动化 |
| pywin32 | 308 | Windows API 调用 |
| faster-whisper | 1.2.1 | 本地语音转文字 |
| pandas | 2.2.3 | 金融数据处理 |
| pydantic | 2.9.2 | 数据校验 |
| pyyaml | 6.0.2 | YAML 配置解析 |
| aiofiles | 24.1.0 | 异步文件 IO |
| httpx | 0.27.2 | HTTP 客户端（Kimi Anthropic 兼容端点） |

### 前端

| 依赖 | 版本 | 用途 |
|------|------|------|
| electron | ^30.0.0 | 桌面应用壳 |
| electron-builder | ^25.1.8 | 应用打包 |
| react | ^18.3.1 | UI 框架 |
| react-dom | ^18.3.1 | DOM 渲染 |
| react-markdown | ^9.0.1 | Markdown 渲染 |
| remark-gfm | ^4.0.0 | GitHub Flavored Markdown |
| lucide-react | ^0.460.0 | 图标库 |
| vite | ^6.0.0 | 构建工具 |
| @vitejs/plugin-react | ^4.3.3 | React HMR |
| typescript | ^5.6.3 | 类型系统 |
| tailwindcss | ^3.4.15 | CSS 框架 |
| vitest | ^4.1.5 | 单元测试 |
| @testing-library/react | ^16.3.2 | React 测试工具 |
| @testing-library/jest-dom | ^6.9.1 | DOM 断言扩展 |

---

## 环境要求

- **Python**: 3.11+（后端使用 Python 3.13 开发）
- **Node.js**: 18+（前端构建）
- **操作系统**: Windows（工具实现大量依赖 Windows API）
- **Playwright**: 需手动安装 Chromium（`playwright install chromium`）

---

## 安装与启动

### 首次安装

```powershell
# 一键安装（PowerShell）
.\install.ps1
```

手动步骤：
```powershell
cd backend
python -m venv venv
.\venv\Scripts\activate
pip install -r requirements.txt
playwright install chromium

cd ..\frontend
npm install
```

### 开发模式启动

```powershell
# 方式 1：一键启动
.\start-all.ps1

# 方式 2：手动分步启动
# 终端 1：后端
cd backend
.\venv\Scripts\python.exe start.py      # http://127.0.0.1:8765

# 终端 2：前端
cd frontend
npm run dev                              # Vite :5173 + Electron 窗口
```

### 生产构建

```powershell
cd frontend
npm run build        # 输出到 frontend/dist/
npm run dist         # vite build + electron-builder，输出到 frontend/release/
```

---

## 测试

### 后端测试（pytest）

```powershell
cd backend
.\venv\Scripts\activate
pytest                    # 运行全部测试
pytest -v                # 详细输出
pytest tests/test_tools/ # 仅运行工具测试
```

- 配置文件：`backend/pytest.ini`
- 模式：`asyncio_mode = auto`
- 外部 API 调用（LiteLLM）在 `conftest.py` 中被 mock，无需真实 API Key 即可运行测试。
- `temp_dir` fixture 基于 `tmp_path`，自动清理。

### 前端测试（vitest）

```powershell
cd frontend
npx vitest               # 交互模式
npx vitest run           # 单次运行
```

- 测试文件位于 `frontend/src/__tests__/`
- `setup.ts` 中 mock 了 `WebSocket`，避免 Node 环境报错。

---

## 配置说明

### 模型配置（`config/models.yaml`）

```yaml
providers:
  openai:
    base_url: https://api.openai.com/v1
    api_key: ${OPENAI_API_KEY}   # 支持环境变量或硬编码
    models:
      - id: gpt-4o
        name: GPT-4o
        context: 128000
        vision: true

  anthropic:
    base_url: https://api.anthropic.com/v1
    api_key: ${ANTHROPIC_API_KEY}
    models:
      - id: claude-3-7-sonnet-20250219
        name: Claude 3.7 Sonnet
        context: 200000
        vision: true

  kimi:
    base_url: https://api.kimi.com/coding/v1
    api_key: sk-...               # Kimi Code API Key
    models:
      - id: kimi-for-coding
        name: Kimi K2.6 (Coding)
        context: 256000
        vision: true

  local:
    base_url: http://localhost:11434/v1
    api_key: ollama
    models:
      - id: gemma3:4b
        name: Gemma 3 (4B)
        context: 32000
        vision: false

settings:
  default_model: kimi-for-coding
  default_provider: kimi
  max_iterations: 200
  auto_approve: false
  screenshot_on_step: true
```

> **注意**：`models.yaml` 中当前包含一个有效的 Kimi API Key。修改时请勿意外泄露。

### 前端常量（`frontend/src/config.ts`）

```typescript
export const API_BASE = 'http://127.0.0.1:8765';
export const WS_BASE = 'ws://127.0.0.1:8765';
```

开发模式下前端通过 `localhost:5173` 访问，生产模式下 Electron 直接加载 `file://` 协议的 `dist/index.html`，后端 CORS 已做相应配置。

---

## 代码组织与模块划分

### 后端核心模块

| 文件 | 职责 |
|------|------|
| `app/main.py` | FastAPI 应用实例、REST 端点、WebSocket 连接管理、生命周期事件 |
| `app/agent.py` | `AgentSession`：ReAct 循环、消息历史截断（保留最近 20 条）、自动截图注入、会话持久化 |
| `app/models.py` | `ModelRouter`：统一封装 LiteLLM，对 Kimi 使用 Anthropic 兼容端点以获取 `thinking` / `reasoning_content` |
| `app/config.py` | Pydantic 模型解析 `models.yaml`，支持 `${ENV_VAR}` 环境变量语法 |
| `app/transcribe.py` | faster-whisper 延迟加载、线程池异步转录 |
| `app/tools/base.py` | `BaseTool` 抽象类 + `ToolResult`（output / error / base64_image） |
| `app/tools/__init__.py` | `ALL_TOOLS` 列表、`get_tool()` / `list_tool_names()` 快捷函数 |

### 知识库（RAG）子系统

知识库使用 sentence-transformers + sqlite-vec 提供本地向量索引和语义检索。

**架构**：
- `app/rag/embedding.py` — 嵌入模型（默认 `all-MiniLM-L6-v2`，384维），首次使用时从 HuggingFace 下载
- `app/rag/splitter.py` — 递归字符分割器，默认 500 字符一块、50 字符重叠
- `app/rag/engine.py` — `RAGEngine`：索引文件/文件夹、语义搜索、列出/删除文档、清空全库
- 存储：`data/knowledge.db`（SQLite + sqlite-vec vec0 虚拟表），启用 WAL 模式

**API 端点**（`routes/knowledge.py`）：
| 方法 | 路径 | 功能 |
|------|------|------|
| `GET` | `/api/knowledge/docs` | 列出已索引文档 |
| `POST` | `/api/knowledge/index` | 索引文件/文件夹 |
| `DELETE` | `/api/knowledge/docs?path=` | 删除指定路径索引 |
| `DELETE` | `/api/knowledge` | 清空整个知识库 |
| `POST` | `/api/knowledge/search` | 语义搜索 |

**Agent 集成**：
- `AgentSession._build_system_prompt()` 在每个用户输入上自动执行 RAG 搜索（非知识类消息如"你好""截图"自动跳过）
- 相关结果（score >= 0.3）注入为 `## Relevant Knowledge Base Context` 系统提示段落
- 前端 KnowledgePanel 通过 REST API 管理索引，通过 IndexedDB 持久化已索引路径

### MCP（Model Context Protocol）集成

桌面 Agent 作为 MCP 客户端，可连接外部 MCP Server 以扩展工具能力。

**架构**：
- `app/mcp/client.py` — `MCPClientWrapper`：管理单个 MCP Server 的 stdio/SSE 连接、工具发现、ping 健康检查
- `app/mcp/manager.py` — `McpManager`：管理多个 MCP Server 的生命周期（connect/disconnect/reload/health）
- `app/tools/mcp_tool.py` — `McpToolProxy`：将 MCP 工具桥接为 Agent 的 `BaseTool`，命名规则 `mcp_{server_id}_{tool_name}`
- `app/tools/__init__.py` — `DynamicToolRegistry`：运行时动态注册/清除 MCP 工具

**配置**（`config/mcp.yaml`）：
```yaml
servers:
  filesystem:
    transport: stdio
    command: npx
    args: ["-y", "@modelcontextprotocol/server-filesystem", "/path/to/dir"]
    enabled: true
  my-api:
    transport: sse
    url: http://localhost:8080/sse
    enabled: false
```

**API 端点**（`main.py`）：
| 方法 | 路径 | 功能 |
|------|------|------|
| `GET` | `/api/mcp/servers` | 列出所有服务器及状态 |
| `POST` | `/api/mcp/servers` | 添加服务器配置 |
| `DELETE` | `/api/mcp/servers/{id}` | 删除服务器配置 |
| `POST` | `/api/mcp/servers/{id}/connect` | 连接服务器 |
| `POST` | `/api/mcp/servers/{id}/disconnect` | 断开服务器 |
| `GET` | `/api/mcp/servers/{id}/tools` | 列出服务器工具 |
| `POST` | `/api/mcp/health` | 健康检查（ping 所有连接） |

**Agent 集成**：
- 连接/断开 MCP 服务器时自动调用 `refresh_all_sessions_mcp_tools()` 刷新所有活跃会话
- 新会话创建和恢复时同步 MCP 工具
- MCP 工具调用有 60s 可配置超时（`DESKTOP_AGENT_MCP_TOOL_TIMEOUT` 环境变量）
- 应用关闭时自动 `disconnect_all()` 清理子进程
- `SAFE_DIRECT_TOOLS` 白名单不包含 MCP 工具，前端无法直接调用（必须通过 Agent）

### 添加新工具

1. 在 `backend/app/tools/` 下新建文件，继承 `BaseTool`：

```python
from app.tools.base import BaseTool, ToolResult

class MyTool(BaseTool):
    name = "my_tool"
    description = "描述"
    parameters = {
        "type": "object",
        "properties": {"arg1": {"type": "string"}},
        "required": ["arg1"]
    }

    async def execute(self, arg1: str) -> ToolResult:
        return ToolResult(output=f"结果: {arg1}")
```

2. 在 `backend/app/tools/__init__.py` 的 `ALL_TOOLS` 列表中实例化并注册。
3. **无需修改前端**，Agent 会自动通过 `/api/tools` 暴露给前端，大模型也能在 system prompt 中识别。

---

## 通信协议

### WebSocket 消息格式

前端与后端通过 `/ws/{session_id}` 建立 WebSocket 连接。

**前端 → 后端**（`msg.type`）：
- `chat`: 发送用户消息，`{ text, model_id, image_base64 }`
- `clear`: 清空当前会话
- `stop`: 中断正在运行的 Agent 循环
- `retry`: 重试最后一条 assistant 消息
- `tool_direct`: 前端直接调用工具，`{ tool_name, args }`

**后端 → 前端**（`event.type`）：
- `content`: 助手文本回复（流式拼接）
- `reasoning`: 推理过程文本（Kimi/Claude thinking）
- `tool_call`: 工具调用记录 `{ name, args, result }`
- `image`: 图片数据 `{ base64, source }`
- `status`: 状态变更 `{ status, iteration }`（`thinking` / `executing` / `completed` / `max_iterations_reached`）
- `error`: 错误信息
- `done`: 单次交互结束标记
- `cleared`: 会话已清空
- `interrupted`: 用户取消

---

## 会话持久化

- 会话数据以 JSON 格式保存在 `backend/sessions/{session_id}.json`。
- 包含字段：`session_id`, `model_id`, `messages`, `iteration`。
- 启动时自动加载历史会话；切换模型时若 model_id 不同会重置会话。
- 可通过 REST API `/api/sessions` 列出、`/api/sessions/{id}/clear` 清空、`DELETE /api/sessions/{id}` 删除。

---

## 安全注意事项

1. **Shell 命令拦截**：`shell_tool.py` 内置危险命令黑名单（如 `rm -rf /`、`format` 等）。
2. **PyAutoGUI FAILSAFE**：将鼠标移至屏幕左上角可紧急中断键鼠操作。
3. **文件大小限制**：`file_read` 拒绝读取超过 10MB 的文件。
4. **webSecurity**: Electron 中 `webSecurity: false`（用于本地静态资源加载），打包后应注意安全。
5. **API Key 存储**：`models.yaml` 中硬编码了 Kimi API Key，生产环境建议改用环境变量。
6. **CORS**：后端仅允许 `localhost:5173` / `127.0.0.1:5173`。

---

## 代码风格指南

### Python

- 使用 **双引号** 为主，f-string 格式化字符串。
- 异步优先：工具 `execute` 方法、API 处理器均为 `async def`。
- 异常处理：工具返回 `ToolResult(error=...)` 而非抛出异常，上层 `agent.py` 中捕获 `OSError`、`ValueError`、`RuntimeError`。
- 类型注解：函数参数和返回值尽量标注，使用 `from __future__ import annotations` 风格（Python 3.11+）。
- 配置读取走 `load_config()` 单例，测试中用 `reset_config_cache` fixture 重置。

### TypeScript / React

- 使用 **函数组件** + Hooks，无类组件。
- 状态管理：纯 React `useState` / `useRef` / `useCallback`，无 Redux/Zustand。
- 类型定义集中在 `src/types.ts`。
- Tailwind 类名直接写在 JSX 中，无 CSS Modules。
- Electron IPC 通过 `preload.js` 暴露，前端使用 `(window as any).electronAPI` 访问（未完整声明类型）。

---

## 测试策略

| 层级 | 工具 | 覆盖范围 |
|------|------|---------|
| 后端单元测试 | pytest | AgentSession 逻辑、各工具独立执行、API 路由、配置解析 |
| 后端集成测试 | pytest + TestClient | WebSocket 消息流、REST 端点完整链路 |
| 前端单元测试 | vitest + @testing-library/react | 组件渲染、状态交互、配置常量 |
| mock 策略 | unittest.mock | LiteLLM 调用始终 mock，避免真实 API 请求 |

**测试运行要求**：
- 后端测试不需要真实模型 API Key（`mock_litellm` fixture 已覆盖）。
- 涉及文件系统的测试使用 `tmp_path` / `temp_dir`，自动清理。
- 前端测试需 mock `WebSocket`（`setup.ts` 已提供）。

---

## 部署与打包

- **开发**：PowerShell 脚本 `start-all.ps1` 一键拉起后端 + Vite + Electron。
- **生产构建**：`npm run dist`（frontend 目录下）调用 `vite build` + `electron-builder`，输出到 `frontend/release/`。
- **后端打包**：当前 `start.py` 用于源码运行；生产打包需额外将 Python 后端封装为 exe（`electron-builder` 配置中预留了 `resources/backend/desktop-agent-backend.exe` 路径，但未配置自动构建）。
- **安装包分发**：`install.ps1` 可在新机器上完成 venv 创建、依赖安装、Playwright 浏览器下载。

---

## 常见问题

1. **后端启动失败**：检查 `backend/venv` 是否存在、端口 8765 是否被占用。
2. **前端白屏**：检查 Vite 是否已启动（`localhost:5173` 可访问），Electron 主进程控制台是否有报错。
3. **Playwright 浏览器未找到**：运行 `playwright install chromium`。
4. **模型调用失败**：检查 `config/models.yaml` 中的 `base_url` 和 `api_key`。
5. **Whisper 首次加载慢**：模型会自动下载到 `backend/models/whisper/`，首次使用需等待下载完成。
