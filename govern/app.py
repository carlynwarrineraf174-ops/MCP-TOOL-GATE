import logging
from contextlib import asynccontextmanager, AsyncExitStack
import inspect
from pydantic import create_model
from govern.ratelimit import RateLimiter
from mcp.server.fastmcp.exceptions import ToolError

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client
from mcp.server.fastmcp import FastMCP
from mcp.server.fastmcp.exceptions import ToolError
from govern.settings import settings

limiter = RateLimiter()
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("govern.proxy")

upstream_session: ClientSession = None
exit_stack = None

@asynccontextmanager
async def lifespan(mcp_app: FastMCP):
    global upstream_session, exit_stack
    exit_stack = AsyncExitStack()

    logger.info(f"正在连接上游: {settings.upstream_command} {settings.upstream_args}")
    params = StdioServerParameters(command=settings.upstream_command, args=settings.upstream_args)

    # 关键实现点 3：保证连接成对关闭
    read, write = await exit_stack.enter_async_context(stdio_client(params))
    upstream_session = await exit_stack.enter_async_context(ClientSession(read, write))
    await upstream_session.initialize()
    logger.info("✅ 成功连接到上游 MCP Server")

    tools = await upstream_session.list_tools()

    for tool in tools.tools:
        # 关键实现点 1：重新包装成本地函数，但我们必须骗过 FastMCP 的类型解析
        def create_proxy(t_name, t_desc, t_schema):
            async def proxy_func(**kwargs):
                # ⚠️ 新增：限流拦截
                tenant_id = "default_tenant"  # 真实业务可以从前端传参或 context 获取

                # 检查是否被限流
                allowed = await limiter.is_allowed(tenant_id, t_name)
                if not allowed:
                    logger.warning(f"🛑 拦截！限流生效: {tenant_id} -> {t_name}")
                    # P1 目标：返回 JSON-RPC error
                    raise ToolError("Rate limit exceeded. Please retry later.")

                logger.info(f"✅ 放行: {t_name} | 入参: {kwargs}")
                result = await upstream_session.call_tool(t_name, kwargs)
                if getattr(result, "isError", False):
                    raise ToolError(str(result.content))
                return result.content
            # 动态生成一个假的 Pydantic 模型，强行把原版 Schema 塞给 FastMCP
            props = t_schema.get("properties", {})
            required = t_schema.get("required", [])
            fields = {}
            for k, v in props.items():
                # 1. 映射基本类型
                py_type = str if v.get("type") == "string" else int if v.get("type") == "integer" else float if v.get(
                    "type") == "number" else bool if v.get("type") == "boolean" else dict

                # 2. 完美提取原版的默认值
                if k in required:
                    default = ...  # 必填
                elif "default" in v:
                    default = v["default"]  # 如果有原版默认值，直接用！
                else:
                    default = None

                fields[k] = (py_type, default)

            if fields:
                args_model = create_model(f"{t_name}_args", **fields)
                # 暴力修改函数的签名，骗过 FastMCP
                proxy_func.__signature__ = inspect.Signature(
                    parameters=[
                        inspect.Parameter(
                            name=param,
                            kind=inspect.Parameter.KEYWORD_ONLY,
                            default=field.default,
                            annotation=field.annotation
                        ) for param, field in args_model.model_fields.items()
                    ]
                )

            proxy_func.__name__ = t_name
            proxy_func.__doc__ = t_desc
            return proxy_func

        # 注册
        proxy_mcp.add_tool(
            create_proxy(tool.name, tool.description, tool.inputSchema),
            name=tool.name,
            description=tool.description
        )

    yield

    logger.info("正在关闭上游连接...")
    await exit_stack.aclose()

# 绑定 lifespan
proxy_mcp = FastMCP("GovernProxy", lifespan=lifespan)