
import sys
import os
import time

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))
from govern.app import proxy_mcp

if __name__ == "__main__":
    # 启动 FastMCP
    proxy_mcp.run()
