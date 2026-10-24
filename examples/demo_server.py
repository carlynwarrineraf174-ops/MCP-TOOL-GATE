"""示例 MCP Server —— 门禁的"靶子"。

它只有 3 个工具，作用是给 gate/ 提供可被快照、可被改坏的 schema。
不要在这里加业务逻辑：这个文件永远保持 30 行，改坏了随时能重写。
"""

from __future__ import annotations

from mcp.server.fastmcp import FastMCP

mcp = FastMCP("demo-gate-target")


@mcp.tool()
def get_weather(city: str, unit: str = "c") -> dict:
    """查询指定城市的天气。"""
    return {"city": city, "temp_c": 21, "unit": unit}


@mcp.tool()
def query_order(order_id: str, with_items: bool = False) -> dict:
    """按订单号查询订单状态。"""
    return {"order_id": order_id, "status": "PAID", "items": [] if with_items else None}


@mcp.tool()
def search_doc(query: str, top_k: int = 3) -> dict:
    """在知识库里检索相关文档片段。"""
    return {"query": query, "hits": [{"title": "demo", "score": 0.9}][:top_k]}


if __name__ == "__main__":
    mcp.run()  # 默认 stdio，够门禁用了
