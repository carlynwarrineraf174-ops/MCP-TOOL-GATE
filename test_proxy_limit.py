import asyncio
import logging
from datetime import time

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

logging.basicConfig(level=logging.WARNING)  # 只看警告和错误


async def send_request(session: ClientSession, i: int):
    """模拟 Agent 发送一次工具调用"""
    try:
        # 调用 get_weather 工具
        result = await session.call_tool("get_weather", {"city": "北京"})
        print(f" [请求 {i:02d}] 成功: {result.content[0].text}")
    except Exception as e:
        # 如果被限流拦截，会进入这里
        print(f" [请求 {i:02d}] 被拦截: {e}")


async def main():
    # 启动你的代理进程
    params = StdioServerParameters(command="python", args=["govern/proxy.py"])

    async with stdio_client(params) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()

            # 并发发送 8 个请求
            print(" 开始并发发送 8 个请求（桶容量为 5）...\n")
            tasks = [send_request(session, i) for i in range(1, 9)]
            await asyncio.gather(*tasks)
            print("\n🏁 测试结束")


if __name__ == "__main__":
    asyncio.run(main())

