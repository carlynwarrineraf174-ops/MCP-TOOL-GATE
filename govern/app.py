import logging
from contextlib import AsyncExitStack
import os
import sys
import contextlib
from mcp.server.streamable_http_manager import StreamableHTTPSessionManager
import uvicorn
from starlette.applications import Starlette
from starlette.routing import Mount
from govern.errors import RateLimited, UpstreamError

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
) -> types.CallToolResult:
    import time
    import json
    start_time = time.time()
    tool_name = name
    tenant_id = _resolve_tenant()

    TOOL_INFLIGHT.labels(tool=tool_name).inc()

    # 限流检查：返回 (是否放行, retry_after_ms)
    allowed, retry_after_ms = await limiter.is_allowed(tenant_id, tool_name)
    if not allowed:
        logger.warning(f"🛑 拦截！限流生效: {tenant_id} -> {tool_name}（retry_after={retry_after_ms}ms）")
        TOOL_CALLS_TOTAL.labels(tool=tool_name, status="rejected").inc()
        RATELIMIT_REJECTED_TOTAL.labels(tenant=tenant_id, tool=tool_name).inc()
        TOOL_INFLIGHT.labels(tool=tool_name).dec()
        record(tenant_id, tool_name, arguments, "rejected_ratelimit", 0)

        err = RateLimited(retry_after_ms=retry_after_ms, tenant=tenant_id, tool=tool_name)
        return types.CallToolResult(
            isError=True,
            content=[types.TextContent(type="text", text=err.to_structured())],
        )

    logger.info(f"✅ 放行: [{tenant_id}] -> {tool_name}")

    try:
        result = await upstream_session.call_tool(tool_name, arguments)
        duration = int((time.time() - start_time) * 1000)
        TOOL_DURATION_SECONDS.labels(tool=tool_name).observe(duration / 1000.0)
        TOOL_CALLS_TOTAL.labels(tool=tool_name, status="ok").inc()
        record(tenant_id, tool_name, arguments, "ok", duration)
        return result
    except Exception as e:
        duration = int((time.time() - start_time) * 1000)
        TOOL_CALLS_TOTAL.labels(tool=tool_name, status="error").inc()
        record(tenant_id, tool_name, arguments, "upstream_error", duration)
        err = UpstreamError(tool=tool_name, reason=str(e))
        return types.CallToolResult(
            isError=True,
            content=[types.TextContent(type="text", text=err.to_structured())],
        )
    finally:
        TOOL_INFLIGHT.labels(tool=tool_name).dec()





async def _serve_http() -> None:
    """HTTP 模式：streamable HTTP 在 /mcp，默认端口见 settings.http_port。"""
    session_manager = StreamableHTTPSessionManager(app=proxy_server)
    async with contextlib.AsyncExitStack() as stack:
        await stack.enter_async_context(session_manager.run())
        app = Starlette(routes=[Mount("/mcp", app=session_manager.handle_request)])
        port = int(_cli_option("--port") or settings.http_port)
        config = uvicorn.Config(app, host="0.0.0.0", port=port, log_level="info")
        await uvicorn.Server(config).serve()


def _cli_option(flag: str) -> str | None:
    """读 `--flag value` 或 `--flag=value`（手写，避免和 uvicorn 的 argparse 冲突）。"""
    argv = sys.argv
    for i, arg in enumerate(argv):
        if arg == flag and i + 1 < len(argv):
            return argv[i + 1]
        if arg.startswith(flag + "="):
            return arg.split("=", 1)[1]
    return None


async def main() -> None:
    global upstream_session
    transport = _cli_option("--transport") or "http"

    async with AsyncExitStack() as stack:
        await init_db()

        logger.info(f"正在连接上游: {settings.upstream_command} {settings.upstream_args}")
        params = StdioServerParameters(command=settings.upstream_command, args=settings.upstream_args)
        read, write = await stack.enter_async_context(stdio_client(params))
        upstream_session = await stack.enter_async_context(ClientSession(read, write))
        await upstream_session.initialize()
        logger.info(f"✅ 成功连接到上游 MCP Server（transport={transport}）")

        if transport == "stdio":
            # ===== stdio 模式：给 bench / snapshot / 旧测试脚本用 =====
            from mcp.server.stdio import stdio_server
            async with stdio_server() as (stdio_read, stdio_write):
                await proxy_server.run(
                    stdio_read,
                    stdio_write,
                    proxy_server.create_initialization_options(),
                )
        else:
            # ===== HTTP 模式（默认）：给真实 Agent 用 =====
            await _serve_http()
