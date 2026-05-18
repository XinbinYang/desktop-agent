# 第一阶段质量审查记录

审查日期：2026-05-18

## 目标

本次审查做行为保持的中等强度清理，让仓库只保留产品代码、测试、文档和模板。运行时记忆、测试计划、截图、旧脚手架和探针脚本不再进入 git worktree。

## 基线

清理前已确认：

- 后端：`python -m pytest -q`，`754 passed`
- 前端：`npx vitest run`，`206 passed`

清理实施过程中针对 runtime 外置和路径变更做过定向验证：

- `backend`: `.\venv\Scripts\python.exe -m pytest tests/test_agent_manager.py tests/test_config.py tests/test_security.py tests/test_tools/test_file_tool.py -q`
- 结果：`74 passed`

## 已清理内容

从仓库移除的旧残留和生成物：

- `backend/plans/**` 历史测试计划文件
- `.playwright-mcp/**` 浏览器调试产物
- `backend/agent_screenshot.png`
- `backend/tests/e2e_*.png` 和 `backend/tests/e2e_golden_*.png`
- `backend/screenshot_agent.py`
- `backend/tests/e2e_browser.py`
- `frontend/test-electron*.js`
- 根目录 `package.json`、`package-lock.json` 和旧 `src/open_agent/**`
- `AGENTS/personal/memory/`、`.archive/`、`.learnings/` 等可变 Personal Agent 数据

`.gitignore` 已补充运行和测试产物规则：

- `backend/plans/`
- `backend/tests/tmp/`
- `backend/tests/e2e_screenshot*.png`
- `backend/agent_screenshot.png`
- `AGENTS/personal/memory/`
- `AGENTS/personal/.archive/`
- `AGENTS/personal/.learnings/`
- `.agent-memory/`
- `.playwright-mcp/`
- `frontend/.vite/`

## Runtime 外置

新增和调整的路径策略：

- `DESKTOP_AGENT_USER_DATA_DIR` 仍是最高优先级覆盖。
- 未设置时使用系统用户数据目录：
  - Windows：`%APPDATA%\Desktop Agent`
  - macOS：`~/Library/Application Support/Desktop Agent`
  - Linux：`$XDG_CONFIG_HOME/Desktop Agent` 或 `~/.config/Desktop Agent`
- 后端运行时根目录统一为 `<user-data>/backend`。
- `AGENTS/` 仓库目录作为 seed template；首次启动复制缺失文件到 `<user-data>/backend/AGENTS`，已有 runtime 文件不覆盖。
- `/api/agents/*/files` 和 Agent 文件工具仍保持请求/响应形状，但 `AGENTS/...` 读写目标切到 runtime AGENTS workspace。
- `config/models.yaml` 作为模板复制到 runtime `backend/config/models.yaml`，用户设置页不再修改仓库模板。

本机迁移保护：

- 清理前已把仓库中的 `AGENTS/` 复制到用户 runtime 目录。
- 同时创建备份：`C:\Users\Harrys\AppData\Roaming\Desktop Agent\backend\AGENTS-repo-migration-20260518T211426`

## 代码卫生

本次做了小范围行为保持修复：

- 删除 `backend/app/routes/agents.py` 中 `return` 之后不可达代码。
- 为 `backend/app/test_runner.py` 的测试数据类设置 `__test__ = False`，避免 pytest collection warning。
- 让 pytest 默认使用临时 `DESKTOP_AGENT_USER_DATA_DIR`，避免测试把 plan/session/workflow 写入仓库或真实用户目录。
- 增加 runtime AGENTS seeding、文件 API runtime 读取、`AGENTS/...` 文件工具映射等定向测试。

## 文档更新

- 重写 `README.md`：覆盖功能、架构、安装、启动、测试、构建、运行时目录、API Key 配置。
- 重写根 `AGENTS.md`：同步 runtime 边界、测试策略、密钥策略、安全提示和当前技术债。
- 更新 `AGENTS/personal/AGENTS.md`：明确仓库 `AGENTS/` 只是模板，Personal Agent 可变数据写入 runtime。

## 保持不变的公共接口

- WebSocket 消息协议不变。
- 工具 schema 不变。
- 现有 REST 响应结构不变。
- `/api/agents/*/files` 的请求和响应形状不变，只改变后端读写目标。
- 开发入口仍是 `backend/start.py` 和 `frontend/package.json`。
- 工作区中已有的 session runtime stop/status 增量接口被保留并测试；它们不改变既有接口语义。

## 剩余技术债

- `backend/app/agent.py` 仍然较大，后续适合拆分会话存储、prompt 构建、工具执行和 streaming 状态管理。
- `frontend/src/App.tsx` 和 `frontend/src/components/ChatPanel.tsx` 仍承担较多 UI 状态与交互职责。
- Electron 后端 exe 打包流程仍未完全自动化。
- 依赖 warning 仍需在依赖升级窗口统一处理。
- 本次未做大规模架构重写，重点是仓库清洁、runtime 边界和测试隔离。

## 收尾验证

本次清理完成后已执行：

```powershell
cd backend
.\venv\Scripts\python.exe -m pytest -q

cd ..\frontend
npx vitest run
npm run build

cd ..
git diff --check
git status --short
```

结果：

- 后端：`764 passed, 4 warnings`
- 前端：`211 passed`
- 构建：`vite build` 成功；保留已有的大 chunk warning
- `git diff --check`：无 whitespace error
- repo 下 `backend/plans/`、`backend/sessions/`、`backend/workflows/`、`.playwright-mcp/` 等运行时目录已清理
