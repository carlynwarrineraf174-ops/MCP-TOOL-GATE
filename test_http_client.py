import asyncio
from mcp import ClientSession
from mcp.client.streamable_http import streamablehttp_client


async def main():
    url = "http://127.0.0.1:8001/mcp/"
    print(f"正在连接: {url}")
    async with streamablehttp_client(url) as (read, write, _):
        async with ClientSession(read, write) as session:
            await session.initialize()
            print("✅ 握手成功！")

            tools = await session.list_tools()
            tool_names = [t.name for t in tools.tools]
            print(f"✅ 成功拉取到工具: {tool_names}")

            # 👇 新增：专门测带 outputSchema 的工具
            if "ship_order_structured" in tool_names:
                print("\n--- 测试带 outputSchema 的工具 ---")
                res = await session.call_tool("ship_order_structured", {"order_id": "A123"})
                print(f"isError = {res.isError}")
                print(f"structuredContent = {res.structuredContent}")
                if res.isError:
                    print("❌ 失败！代理丢掉了 structuredContent")
                else:
                    print("✅ 成功透传 structuredContent")


if __name__ == "__main__":
    asyncio.run(main())