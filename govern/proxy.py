from fastapi import FastAPI, Request, HTTPException
from pydantic import BaseModel
import logging
import time
import asyncio
import redis.asyncio as redis  # 引入异步 Redis
from prometheus_fastapi_instrumentator import Instrumentator
from prometheus_client import Counter

logging.basicConfig(filename='reports/audit.log', level=logging.INFO)
logging.getLogger().addHandler(logging.StreamHandler())

app = FastAPI(title="MCP Tool Govern Gateway")
Instrumentator().instrument(app).expose(app)

TOOL_CALL_COUNTER = Counter("mcp_tool_calls_total", "Total calls per tool", ["tool_name"])

# 连接本地 Redis
r = redis.Redis(host='localhost', port=6379, db=0, decode_responses=True)


class ToolCallRequest(BaseModel):
    tenant_id: str
    tool_name: str
    args: dict


@app.post("/api/v1/call_tool")
async def call_tool(req: ToolCallRequest, request: Request):
    current_minute = int(time.time() // 60)
    limit_key = f"rate_limit:{req.tenant_id}:{req.tool_name}:{current_minute}"

    # === 核心：使用 Redis INCR 实现原子操作 ===
    # 每次请求给这个 key 加 1，Redis 返回加完之后的结果
    current_count = await r.incr(limit_key)

    # 如果是这个窗口的第一次请求（count == 1），设置 60 秒后过期，自动清理内存
    if current_count == 1:
        await r.expire(limit_key, 60)

    # 规则：超过 5 次就拦截（HTTP 429）
    if current_count > 5:
        logging.warning(f"RATE LIMIT EXCEEDED: {limit_key}")
        raise HTTPException(status_code=429, detail="Too Many Requests.")

    # === 限流通过 ===
    logging.info(f"Tenant: {req.tenant_id} | Tool: {req.tool_name} | Count: {current_count}")
    TOOL_CALL_COUNTER.labels(tool_name=req.tool_name).inc()

    await asyncio.sleep(0.05)
    return {"status": "success", "result": f"Mock result"}


@app.on_event("shutdown")
async def shutdown():
    await r.aclose()  # 优雅关闭 Redis 连接