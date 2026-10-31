import sys
import os
import asyncio
from prometheus_client import start_http_server

# 强行获取项目根目录，防止路径问题
ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
os.chdir(ROOT_DIR)
sys.path.insert(0, ROOT_DIR)

from govern.app import main

if __name__ == "__main__":
    try:
        start_http_server(8000)
        print("Prometheus metrics server started on http://127.0.0.1:8000", file=sys.stderr)
    except OSError:
        print("Warning: Port 8000 in use.", file=sys.stderr)

    # 运行异步入口
    asyncio.run(main())