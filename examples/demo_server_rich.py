from mcp.server.fastmcp import FastMCP
from typing import List, Literal
from pydantic import BaseModel, Field

mcp = FastMCP("rich-gate-target")

class Address(BaseModel):
    city: str = Field(description="城市名称，例如北京")
    street: str = Field(description="街道信息")



class ShipResult(BaseModel):
    status: str
    address: dict

@mcp.tool()
def ship_order_structured(
    order_id: str = Field(description="订单号"),
) -> ShipResult:
    """一个带结构化返回的工具，声明了 outputSchema。"""
    return ShipResult(
        status="shipped",
        address={"city": "北京", "street": "长安街"}
    )

@mcp.tool()
def complex_search(
    query: str = Field(description="搜索关键词"),
    tags: List[str] = Field(description="标签列表，支持多个"),
    mode: Literal["fast", "accurate"] = Field(description="搜索模式")
) -> dict:
    """一个包含数组、枚举、嵌套对象和详细描述的复杂检索工具。"""
    return {"query": query, "tags": tags, "mode": mode}

@mcp.tool()
def ship_order(
    order_id: str = Field(description="订单号"),
    address: Address = Field(description="收货地址")
) -> dict:
    """一个包含嵌套对象的发货工具。"""
    return {"status": "shipped", "address": address.model_dump()}

if __name__ == "__main__":
    mcp.run()