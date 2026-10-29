import asyncio
import time
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client


async def run_bench(command, args, label, concurrency=8, duration=20):
    params = StdioServerParameters(command=command, args=args)
    latencies = []
    stop_time = time.time() + duration
    request_count = 0

    async with stdio_client(params) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            print(f"🔥 开始压测: {label} (并发: {concurrency}, 持续: {duration}s)")

            start_bench_time = time.time()

            async def worker():
                nonlocal request_count
                while time.time() < stop_time:
                    t0 = time.time()
                    try:
                        await session.call_tool("get_weather", {"city": "北京"})
                    except Exception:
                        pass

                    # 丢掉前 3 秒（爬坡期）
                    if time.time() - start_bench_time > 3:
                        latencies.append((time.time() - t0) * 1000)
                        request_count += 1

            workers = [asyncio.create_task(worker()) for _ in range(concurrency)]
            await asyncio.gather(*workers)

    latencies.sort()
    if not latencies:
        print("压测时间太短，没有收集到有效数据！")
        return 0, 0, 0, 0

    p50 = latencies[int(len(latencies) * 0.5)]
    p95 = latencies[int(len(latencies) * 0.95)]
    p99 = latencies[int(len(latencies) * 0.99)]
    qps = request_count / (duration - 3)

    print(f"[{label}] QPS: {qps:.2f} | p50: {p50:.2f}ms | p95: {p95:.2f}ms | p99: {p99:.2f}ms\n")
    # 👇 关键：把 qps 也返回出去！
    return qps, p50, p95, p99


async def main():
    print("⚠️ 请确保 settings.py 里的 ratelimit_enabled = False！\n")

    direct = await run_bench("python", ["examples/demo_server.py"], "直连真实工具")
    proxy = await run_bench("python", ["govern/proxy.py"], "经过治理层代理")

    if direct and proxy:
        print("=== 最终结果对比 ===")
        # 👇 改对索引：direct[0] 是 qps，direct[2] 是 p95
        print(f"直连  QPS: {direct[0]:.2f}  p95: {direct[2]:.2f}ms")
        print(f"代理  QPS: {proxy[0]:.2f}  p95: {proxy[2]:.2f}ms")
        print(f"👉 代理开销 p95: +{(proxy[2] - direct[2]):.2f}ms")


if __name__ == "__main__":
    asyncio.run(main())