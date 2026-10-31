import logging
from contextlib import AsyncExitStack
import os
import contextlib
from mcp.server.streamable_http_manager import StreamableHTTPSessionManager
import uvicorn
from starlette.applications import Starlette
from starlette.routing import Mount

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client
# 👇 导入底层的 Server 和类型
from mcp.server.lowlevel import Server
from mcp.server.lowlevel.server import request_ctx
import mcp.types as types

from govern.ratelimit import RateLimiter
from govern.audit import init_db, record
from govern.settings import settings
from govern.metrics import (
    TOOL_CALLS_TOTAL,
    TOOL_DURATION_SECONDS,
    TOOL_INFLIGHT,
    RATELIMIT_REJECTED_TOTAL
)

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("govern.proxy")

limiter = RateLimiter()
upstream_session: ClientSession = None

# 👇 核心：创建底层的 Server 实例，而不是 FastMCP
proxy_server = Server("GovernProxy")


@proxy_server.list_tools()
async def handle_list_tools() -> list[types.Tool]:
    """原样透传上游的工具列表和 Schema"""
    # 直接从上游把原版的对象拿过来返回，不做任何解析
    result = await upstream_session.list_tools()
    return result.tools


def _resolve_tenant() -> str:
    """优先取 HTTP 请求头 X-Tenant-Id，取不到再回退到环境变量。

    注意：lowlevel Server 的 call_tool 回调只会传 (name, arguments)，
    不会注入 Context —— 请求信息要从 request_ctx 这个 ContextVar 里拿。
    """
    try:
        request = request_ctx.get().request
    except LookupError:
        request = None
    if request is not None:
        return request.headers.get("x-tenant-id", "anonymous")
    return os.environ.get("GOVERN_TENANT_ID", "default_tenant")


@proxy_server.call_tool()
async def handle_call_tool(
        name: str,
        arguments: dict,
) -> list[types.TextContent]:
    import time
    start_time = time.time()
    tool_name = name
    tenant_id = _resolve_tenant()

    TOOL_INFLIGHT.labels(tool=tool_name).inc()

    # 检查限流
    allowed = await limiter.is_allowed(tenant_id, tool_name)
    if not allowed:
        logger.warning(f"🛑 拦截！限流生效: {tenant_id} -> {tool_name}")
        TOOL_CALLS_TOTAL.labels(tool=tool_name, status="rejected").inc()
        RATELIMIT_REJECTED_TOTAL.labels(tenant=tenant_id, tool=tool_name).inc()
        TOOL_INFLIGHT.labels(tool=tool_name).dec()
        record(tenant_id, tool_name, arguments, "rejected_ratelimit", 0)

        # 这里暂时保持原样，P1-3 我们再去改成标准错误
        raise Exception("Rate limit exceeded.")

    logger.info(f"✅ 放行: [{tenant_id}] -> {tool_name}")

    try:
        result = await upstream_session.call_tool(tool_name, arguments)
        duration = int((time.time() - start_time) * 1000)

        TOOL_DURATION_SECONDS.labels(tool=tool_name).observe(duration / 1000.0)
        TOOL_CALLS_TOTAL.labels(tool=tool_name, status="ok").inc()
        # 记录成功的审计，带上 tenant_id
        record(tenant_id, tool_name, arguments, "ok", duration)

        return result.content
    except Exception as e:
        duration = int((time.time() - start_time) * 1000)
        TOOL_CALLS_TOTAL.labels(tool=tool_name, status="error").inc()
        record(tenant_id, tool_name, arguments, "upstream_error", duration)
        raise e
    finally:
        TOOL_INFLIGHT.labels(tool=tool_name).dec()





async def main():
    global upstream_session
    async with AsyncExitStack() as stack:
        await init_db()

        logger.info(f"正在连接上游: {settings.upstream_command} {settings.upstream_args}")
        params = StdioServerParameters(command=settings.upstream_command, args=settings.upstream_args)

        read, write = await stack.enter_async_context(stdio_client(params))
        upstream_session = await stack.enter_async_context(ClientSession(read, write))
        await upstream_session.initialize()
        logger.info("✅ 成功连接到上游 MCP Server")

        # 核心：启动 HTTP 服务
        session_manager = StreamableHTTPSessionManager(app=proxy_server)

        async with contextlib.AsyncExitStack() as async_stack:
            await async_stack.enter_async_context(session_manager.run())

            app = Starlette(
                routes=[Mount("/mcp", app=session_manager.handle_request)]
            )

            # 监听 8001 端口
            config = uvicorn.Config(app, host="0.0.0.0", port=8001, log_level="info")
            server = uvicorn.Server(config)
            await server.serve()