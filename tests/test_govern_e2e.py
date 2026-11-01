"""治理层端到端测试：起代理 → 连 HTTP → 调工具 → 断言 structuredContent。

这个测试锁住三件事：
1. 协议透传：list_tools / call_tool 都能通
2. 结构化输出透传：带 outputSchema 的工具不报错，structuredContent 不为 None
3. 不依赖外部进程和固定端口：每次用空闲端口 + 临时 DB 起自己的代理
   （8001 经常被 docker compose 的容器占用，绝不能抢固定端口）
"""
import asyncio
import os
import shutil
import socket
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path

import httpx
from mcp import ClientSession
from mcp.client.streamable_http import streamablehttp_client

ROOT = Path(__file__).resolve().parent.parent


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def _client_factory(headers=None, timeout=None, auth=None):
    return httpx.AsyncClient(headers=headers, timeout=timeout, auth=auth, trust_env=False)


async def _check(port: int) -> None:
    url = f"http://127.0.0.1:{port}/mcp/"
    async with streamablehttp_client(url, httpx_client_factory=_client_factory) as (r, w, _):
        async with ClientSession(r, w) as session:
            await session.initialize()
            tools = await session.list_tools()
            names = [t.name for t in tools.tools]

            # 1) 协议透传：rich 靶场的工具都在
            assert "complex_search" in names, f"工具列表缺 complex_search: {names}"
            assert "ship_order_structured" in names, f"工具列表缺 ship_order_structured: {names}"

            # 2) 无 outputSchema 的工具：正常返回
            res = await session.call_tool(
                "complex_search", {"query": "test", "tags": ["t1"], "mode": "fast"}
            )
            assert res.isError is False, f"complex_search 失败: {res}"

            # 3) 带 outputSchema 的工具：structuredContent 必须透传
            res = await session.call_tool("ship_order_structured", {"order_id": "A123"})
            assert res.isError is False, f"ship_order_structured 失败（N-3 回归）：{res}"
            assert res.structuredContent is not None, f"structuredContent 丢了（N-3 回归）：{res}"
            assert res.structuredContent.get("status") == "shipped", res.structuredContent


class GovernE2ETest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.port = _free_port()
        cls.tmpdir = tempfile.mkdtemp(prefix="govern_e2e_")
        db_path = Path(cls.tmpdir, "govern.db").as_posix()

        env = os.environ.copy()
        env.update({
            "GOVERN_HTTP_PORT": str(cls.port),
            "GOVERN_METRICS_PORT": "0",          # 测试不启动 Prometheus，避免端口冲突
            "GOVERN_DB_URL": f"sqlite+aiosqlite:///{db_path}",
            "GOVERN_RATELIMIT_ENABLED": "false",
            "GOVERN_UPSTREAM_ARGS": '["examples/demo_server_rich.py"]',
            "PYTHONIOENCODING": "utf-8",
        })
        cls._log = tempfile.TemporaryFile(mode="w+", encoding="utf-8", errors="replace")
        cls.proc = subprocess.Popen(
            [sys.executable, "govern/proxy.py"],
            cwd=str(ROOT),
            env=env,
            stdout=subprocess.DEVNULL,
            stderr=cls._log,
        )

        # 等端口就绪（最多 20 秒）；子进程一旦退出就立刻报错并带上日志
        deadline = time.time() + 20
        while time.time() < deadline:
            if cls.proc.poll() is not None:
                raise RuntimeError(f"代理启动即退出（exit={cls.proc.returncode}）：\n{cls._tail()}")
            try:
                with httpx.Client(trust_env=False, timeout=1) as client:
                    client.get(f"http://127.0.0.1:{cls.port}/mcp/")
                return
            except Exception:
                time.sleep(0.3)
        raise RuntimeError(f"代理在 20 秒内没起来：\n{cls._tail()}")

    @classmethod
    def _tail(cls, limit: int = 2000) -> str:
        cls._log.flush()
        cls._log.seek(0)
        return cls._log.read()[-limit:]

    @classmethod
    def tearDownClass(cls):
        cls.proc.terminate()
        try:
            cls.proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            cls.proc.kill()
        cls._log.close()
        shutil.rmtree(cls.tmpdir, ignore_errors=True)

    def test_end_to_end(self):
        asyncio.run(_check(self.port))


if __name__ == "__main__":
    unittest.main()
