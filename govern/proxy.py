import sys
import os

# 1. 核心神技：强行获取项目根目录，并把当前工作目录（CWD）切换过去！
# 这样不管是谁（测试脚本、CI、还是命令行）调用它，相对路径都不会迷路。
ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
os.chdir(ROOT_DIR)
sys.path.insert(0, ROOT_DIR)

from govern.app import proxy_mcp
from prometheus_client import start_http_server

if __name__ == "__main__":
    try:
        # 启动一个 HTTP 服务在 8000 端口
        start_http_server(8000)
        print("Prometheus metrics server started on http://127.0.0.1:8000", file=sys.stderr)
    except OSError:
        print("Warning: Port 8000 in use. Metrics server skipped.", file=sys.stderr)

    # 启动 MCP 代理
    proxy_mcp.run()