import asyncio
from mcp import ClientSession
from mcp.client.streamable_http import streamablehttp_client


async def main():
    # 指向你正在运行的 8001 端口
    url = "http://127.0.0.1:8001/mcp/"

    print(f"正在连接: {url}")
    async with streamablehttp_client(url) as (read, write, _):
        async with ClientSession(read, write) as session:
            # 官方 SDK 会自动处理版本和 Header
            await session.initialize()
            print("✅ 握手成功！")

            # 顺便把工具列表拉出来看看
            tools = await session.list_tools()
            print(f"✅ 成功从 HTTP 网关拉取到工具: {[t.name for t in tools.tools]}")


if __name__ == "__main__":
    asyncio.run(main())