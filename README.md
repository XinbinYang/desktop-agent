# Desktop Agent — 桌面个人 Agent

一个带 GUI 的桌面级个人 Agent，支持**多模型切换**、**文件操控**、**终端执行**、**浏览器自动化**、**桌面键鼠控制**和**跨应用交互**。

架构：**Electron + React（前端）+ Python FastAPI（后端）**

---

## 功能特性

| 能力 | 工具名 | 说明 |
|------|--------|------|
| 📁 文件操作 | `file_read/write/list/search/delete` | 读写本地文件、目录浏览、搜索 |
| 🖥️ 终端控制 | `shell_execute/start` | 执行命令并流式回显，支持超时控制 |
| 🌐 浏览器 | `browser_navigate/click/type/screenshot/evaluate` | Playwright 驱动，可视化浏览器自动化 |
| 🖱️ 桌面操控 | `screenshot/mouse_click/move/type/press_key/scroll` | PyAutoGUI 键鼠控制 + 屏幕截图 |
| 🪟 应用控制 | `app_open/list_windows/find_window/click/type` | 启动程序、操作窗口 UI（Windows） |

**模型支持**：OpenAI (GPT-4o)、Anthropic (Claude 3.7)、本地 Ollama、任何兼容 OpenAI API 的端点。

---

## 项目结构

```
desktop-agent/
├── backend/                 # Python Agent 后端
│   ├── app/
│   │   ├── main.py         # FastAPI + WebSocket 服务
│   │   ├── agent.py        # ReAct Agent 循环核心
│   │   ├── models.py       # 多模型路由（LiteLLM）
│   │   ├── config.py       # 配置管理
│   │   └── tools/          # 工具实现
│   ├── requirements.txt
│   └── start.py
├── frontend/               # Electron + React 前端
│   ├── src-main/           # Electron 主进程 + Preload
│   ├── src/                # React 组件
│   ├── package.json
│   └── vite.config.ts
└── config/
    └── models.yaml         # 模型配置文件
```

---

## 环境准备

### 1. 后端环境

```bash
# 进入后端目录
cd desktop-agent/backend

# 创建虚拟环境（推荐）
python -m venv venv
venv\Scripts\activate

# 安装依赖
pip install -r requirements.txt

# 安装 Playwright 浏览器（浏览器自动化必需）
playwright install chromium
```

### 2. 配置模型

首次启动后，打开左侧“设置”面板，添加或编辑 Provider：

- OpenAI: `https://api.openai.com/v1`，填入自己的 `OPENAI_API_KEY` 或直接粘贴 API Key。
- Anthropic: `https://api.anthropic.com/v1`，填入自己的 `ANTHROPIC_API_KEY` 或直接粘贴 API Key。
- Kimi: `https://api.kimi.com/coding/v1`，填入自己的 `KIMI_API_KEY` 或直接粘贴 API Key。
- Ollama: `http://localhost:11434/v1`，API Key 可填 `ollama`。

设置页保存后会写入本机用户数据目录下的用户配置文件，不会修改仓库内的 `config/models.yaml` 模板。编辑 Provider 时 API Key 输入框留空表示保留原 key；保存后界面只显示脱敏值。

高级用户仍可使用环境变量，例如 PowerShell：

```powershell
$env:OPENAI_API_KEY="<your-api-key>"
```

> 发布说明：历史版本中若曾暴露真实 API Key，请立即在对应平台轮换旧 key。当前仓库模板只保留 `${ENV_VAR}` 占位。

### 3. 前端环境

```bash
# 进入前端目录（使用 PowerShell）
cd desktop-agent/frontend

# 安装依赖（需要 Node.js 18+）
npm install

# 或如果使用 bun/yarn/pnpm 也可以
```

---

## 启动方式

### 开发模式（推荐）

**步骤 1：启动后端**
```bash
cd desktop-agent/backend
venv\Scripts\activate
python start.py
```
后端将运行在 `http://127.0.0.1:8765`

**步骤 2：启动前端（新终端）**
```bash
cd desktop-agent/frontend
npm run dev
```
这将同时启动 Vite 开发服务器（:5173）和 Electron 窗口。

### 生产构建

```bash
cd desktop-agent/frontend
npm run build
```
输出在 `frontend/dist/`，Electron 将加载打包后的静态文件。

---

## 使用指南

### GUI 界面

- **顶部栏**：显示连接状态、当前模型下拉切换
- **左侧边栏**：快捷工具（截图、浏览器、列出窗口等）、模型设置
- **中间区域**：聊天对话，支持 Markdown、代码高亮、图片显示
- **底部面板**：终端执行日志（可折叠）
- **右侧栏**：工具调用历史记录（可展开查看参数和结果）

### 核心工作流

1. **选择模型**：顶部下拉框或左栏设置中切换 GPT/Claude/本地模型
2. **输入指令**：支持文字、图片上传、粘贴截图
3. **Agent 执行**：AI 自动分析任务 → 调用工具 → 观察结果 → 循环直到完成
4. **人工干预**：危险命令已内置拦截规则，关键操作可随时中断

### 指令示例

```
"帮我截图当前屏幕，然后打开浏览器访问百度，搜索'FastAPI 教程'"
"在 D:\\workspace 下创建一个 hello.py，写入打印当前时间的代码，然后运行它"
"列出当前所有打开的窗口，点击记事本的'文件'菜单"
"读取 C:\\Users\\admin\\Desktop\\test.txt 的内容并总结"
```

---

## 进阶：添加自定义工具

在 `backend/app/tools/` 下新建文件，继承 `BaseTool`：

```python
from app.tools.base import BaseTool, ToolResult

class MyTool(BaseTool):
    name = "my_tool"
    description = "我的自定义工具"
    parameters = {
        "type": "object",
        "properties": {"arg1": {"type": "string"}},
        "required": ["arg1"]
    }
    
    async def execute(self, arg1: str) -> ToolResult:
        return ToolResult(output=f"结果: {arg1}")
```

然后在 `backend/app/tools/__init__.py` 的 `ALL_TOOLS` 列表中注册即可。**无需修改前端**，Agent 会自动识别并使用。

---

## 安全提示

- `shell_execute` 已内置危险命令拦截（`rm -rf /`, `format` 等）
- 桌面键鼠操作依赖 PyAutoGUI 的 FAILSAFE（将鼠标移到屏幕左上角可紧急中断）
- 建议不要在高权限账户下长期运行 Agent
- 浏览器自动化使用非 headless 模式，可实时观察操作过程

---

## 后续可扩展方向

1. **向量记忆**：接入 ChromaDB，支持长期记忆和代码库 RAG
2. **MCP 协议**：集成 Model Context Protocol，复用社区工具生态
3. **语音输入**：加入 Whisper 本地语音识别
4. **视觉 Agent**：接入更强的多模态模型，实现真正的"看屏操作"
5. **任务计划器**：支持定时任务、复杂工作流编排
6. **远程模式**：后端可部署到服务器，前端作为纯客户端连接

---

## 技术栈

| 层级 | 技术 |
|------|------|
| 前端 GUI | Electron 33 + React 18 + Vite + TailwindCSS |
| 前后通信 | WebSocket + REST API |
| Agent 后端 | Python 3.11 + FastAPI + LiteLLM |
| 模型路由 | LiteLLM（统一 OpenAI/Anthropic/Ollama） |
| 浏览器 | Playwright |
| 桌面操控 | PyAutoGUI + pynput + Pillow |
| 应用控制 | pywinauto + pywin32 |

---

**当前状态**：MVP 框架已搭建完成，核心链路（聊天 → 模型路由 → 工具调用 → GUI 回显）已跑通。下一步可根据你的具体使用场景继续深化。
