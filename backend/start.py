import sys
import os

# 强制 UTF-8 编码，避免 Windows 控制台 charmap 错误
os.environ.setdefault("PYTHONIOENCODING", "utf-8")
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8")

# 确保用户配置目录始终指向持久化路径
if not os.environ.get("DESKTOP_AGENT_USER_DATA_DIR"):
    appdata = os.environ.get("APPDATA", "")
    if not appdata:
        appdata = os.path.join(os.path.expanduser("~"), "AppData", "Roaming")
    os.environ["DESKTOP_AGENT_USER_DATA_DIR"] = os.path.join(appdata, "Desktop Agent")

# 确保当前目录在 Python 路径中（用于模块导入）
current_dir = os.path.dirname(os.path.abspath(__file__))
if current_dir not in sys.path:
    sys.path.insert(0, current_dir)

from app.windows_asyncio import patch_windows_proactor_accept

patch_windows_proactor_accept()

import uvicorn
from app.main import app

if __name__ == "__main__":
    uvicorn.run(
        app,
        host="127.0.0.1",
        port=8765,
        reload=False,  # 生产/打包时关闭 reload
        log_level="info",
        access_log=False,  # 减少日志噪音
    )
