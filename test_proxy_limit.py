"""stdio 通道的限流演示：起代理（stdio 模式）→ 并发 8 次 → 期望 5 过 3 拒。

前置：Redis 可达（`127.0.0.1:6379`）。Redis 挂了会按 fail-open 全部放行，脚本会明确报错。

跑法：
    python test_proxy_limit.py      # 失败退出码 1
"""
import asyncio
import os
import sys

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client
import json

CALLS = 8
BURST = 5
EXPECT_REJECTED = CALLS - BURST
TOOL = "complex_search"
ARGS = {"query": "test", "tags": ["t1"], "mode": "fast"}


def _env() -> dict[str, str]:
    env = os.environ.copy()
    env.update({
        "GOVERN_RATELIMIT_ENABLED": "true",   # 演示脚本自己打开限流，不依赖 settings 默认值
        "GOVERN_RATELIMIT_BURST": str(BURST),
        "GOVERN_UPSTREAM_ARGS": '["examples/demo_server_rich.py"]',
        "PYTHONIOENCODING": "utf-8",
    })
    return env


async def _call(session: ClientSession, i: int) -> tuple[bool, dict | None]:
    """返回 (isError, payload)；payload 是解析后的 JSON（失败时为 None）。"""
    res = await session.call_tool(TOOL, ARGS)
    if not res.isError:
        return False, None
    try:
        return True, json.loads(res.content[0].text)
    except (json.JSONDecodeError, IndexError, AttributeError):
        return True, {"error": "unparseable", "raw": str(res.content)}


async def main() -> int:
    params = StdioServerParameters(
        command=sys.executable,
        args=["govern/proxy.py", "--transport", "stdio"],
        env=_env(),
    )
    async with stdio_client(params) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            results = await asyncio.gather(*[_call(session, i) for i in range(1, CALLS + 1)])

    rejected = [p for err, p in results if err and p and p.get("error") == "rate_limited"]
    other_errors = [p for err, p in results if err and p and p.get("error") != "rate_limited"]

    print(f"{CALLS} 次并发：通过 {len(results) - len(rejected) - len(other_errors)} / "
          f"限流 {len(rejected)} / 其它错误 {len(other_errors)}")

    if other_errors:
        print(f"❌ 出现非限流错误：{other_errors[0]}")
        return 1
    if len(rejected) != EXPECT_REJECTED:
        print(f"❌ 期望 {EXPECT_REJECTED} 次被限流，实际 {len(rejected)}。"
              f"检查 Redis 是否可达（不可达时 fail-open 全部放行）")
        return 1

    # P1-3：每个被拒的返回体里必须有 retry_after_ms
    missing_retry = [p for p in rejected if "retry_after_ms" not in p]
    if missing_retry:
        print(f"❌ 限流错误缺 retry_after_ms：{missing_retry[0]}")
        return 1

    retry_values = [p["retry_after_ms"] for p in rejected]
    print(f"   retry_after_ms 样本：{retry_values[:3]}")
    print("✅ 限流生效（stdio 通道），且返回体带 retry_after_ms")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
