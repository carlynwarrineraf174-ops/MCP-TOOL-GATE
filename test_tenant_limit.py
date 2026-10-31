"""租户级限流演示/自检脚本。

前提：代理已用默认配置启动（ratelimit_enabled=true, burst=5, interval=1000ms）
     python govern/proxy.py

跑法：
     python test_tenant_limit.py

判据：
     同一租户 6 个并发调用 → 5 过 1 拒（桶容量 5）
     两个租户互不影响（限流 key 是 rl:{tenant}:{tool}）
"""

import asyncio

import httpx
from mcp import ClientSession
from mcp.client.streamable_http import streamablehttp_client

URL = "http://127.0.0.1:8001/mcp/"
CALLS = 6
TOOL = "complex_search"
ARGS = {"query": "test", "tags": ["t1"], "mode": "fast"}


def _client_factory(headers=None, timeout=None, auth=None):
    """本地探活不该走系统代理（某些机器的 NO_PROXY 里带 [::1]，httpx 会解析失败）。"""
    return httpx.AsyncClient(headers=headers, timeout=timeout, auth=auth, trust_env=False)


async def burst(tenant: str) -> tuple[int, int, list[str]]:
    """一个租户建一条会话，并发打 CALLS 次；返回 (通过, 拦截, 错误详情)。"""
    async with streamablehttp_client(
        URL, headers={"X-Tenant-Id": tenant}, httpx_client_factory=_client_factory
    ) as (read, write, _):
        async with ClientSession(read, write) as session:
            await session.initialize()
            results = await asyncio.gather(
                *[session.call_tool(TOOL, ARGS) for _ in range(CALLS)]
            )

    ok = rejected = 0
    detail: list[str] = []
    for res in results:
        text = " ".join(getattr(c, "text", "") for c in res.content)
        if res.isError:
            if "rate limit" in text.lower():
                rejected += 1
            else:
                detail.append(text)          # 不是限流，是别的错，必须暴露出来
        else:
            ok += 1
    return ok, rejected, detail


async def main() -> int:
    a_ok, a_rej, a_err = await burst("tenant_A")
    b_ok, b_rej, b_err = await burst("tenant_B")

    print(f"租户 A ({CALLS} 次并发): 通过 {a_ok} / 拦截 {a_rej}")
    print(f"租户 B ({CALLS} 次并发): 通过 {b_ok} / 拦截 {b_rej}")

    for label, errs in (("A", a_err), ("B", b_err)):
        for e in errs[:1]:
            print(f"  {label} 非限流错误: {e}")

    expected_ok = CALLS - 1                   # 桶容量 5 → 恰好 1 个被拒
    if a_err or b_err:
        print("\n❌ 有非限流错误：先修代理，再看限流（很可能是 call_tool 回调签名/租户解析的问题）")
        return 1
    if a_ok == expected_ok and b_ok == expected_ok and a_rej == b_rej == 1:
        print("\n✅ 限流生效，且两个租户互不影响")
        return 0
    print("\n❌ 限流没有按预期生效：检查代理启动日志里的配置"
          "（ratelimit_enabled / burst / Redis 是否可达）")
    return 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
