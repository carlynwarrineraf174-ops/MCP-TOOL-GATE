"""手工自检脚本：连正在运行的 HTTP 代理，断言能握手、能拉工具、能透传 structuredContent。

跑法（先起代理：`python govern/proxy.py`）：
    python test_http_client.py

端口可用 `GOVERN_HTTP_PORT` 覆盖；失败时退出码为 1。
"""
import asyncio
import os
import sys

import httpx
from mcp import ClientSession
from mcp.client.streamable_http import streamablehttp_client

PORT = int(os.environ.get("GOVERN_HTTP_PORT", "8001"))
URL = f"http://127.0.0.1:{PORT}/mcp/"


def _client_factory(headers=None, timeout=None, auth=None):
    # trust_env=False：避免被系统代理 / NO_PROXY 里的 [::1] 干扰（httpx 会解析失败）
    return httpx.AsyncClient(headers=headers, timeout=timeout, auth=auth, trust_env=False)


async def main() -> int:
    async with streamablehttp_client(URL, httpx_client_factory=_client_factory) as (read, write, _):
        async with ClientSession(read, write) as session:
            await session.initialize()
            tools = await session.list_tools()
            names = [t.name for t in tools.tools]
            assert names, "工具列表为空：代理没连上上游？"
            print(f"✅ 握手成功：{URL}")
            print(f"✅ 拉取到 {len(names)} 个工具: {sorted(names)}")

            # 带 outputSchema 的工具：structuredContent 不能丢（N-3 回归）
            if "ship_order_structured" in names:
                res = await session.call_tool("ship_order_structured", {"order_id": "A123"})
                assert res.isError is False, f"带 outputSchema 的工具失败：{res}"
                assert res.structuredContent is not None, "structuredContent 丢了"
                assert res.structuredContent.get("status") == "shipped", res.structuredContent
                print("✅ structuredContent 透传正常")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
