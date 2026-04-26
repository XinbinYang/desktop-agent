import sys
import os

# 确保当前目录在 Python 路径中（用于模块导入）
current_dir = os.path.dirname(os.path.abspath(__file__))
if current_dir not in sys.path:
    sys.path.insert(0, current_dir)

import uvicorn

if __name__ == "__main__":
    uvicorn.run(
        "app.main:app",
        host="127.0.0.1",
        port=8765,
        reload=False,  # 生产/打包时关闭 reload
        log_level="info",
        access_log=False,  # 减少日志噪音
    )