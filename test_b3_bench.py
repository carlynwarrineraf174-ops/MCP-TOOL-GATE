import asyncio
import time
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client


async def main():
    params = StdioServerParameters(command="python", args=["govern/proxy.py"])
    async with stdio_client(params) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()

            print("🚀 开始发送 100 个请求压测...")
            start = time.time()

            async def req(i):
                try:
                    await session.call_tool("get_weather", {"city": "北京"})
                except Exception:
                    pass  # 忽略被限流的

            await asyncio.gather(*(req(i) for i in range(100)))
            print(f"🏁 压测结束，总耗时: {time.time() - start:.2f} 秒")

            # 👇 关键：把 sleep 放在这里！在上下文内部！
            print("⏳ 保持代理存活 30 秒，请现在去浏览器打开 http://127.0.0.1:8000 ...")
            await asyncio.sleep(30)


if __name__ == "__main__":
    asyncio.run(main())