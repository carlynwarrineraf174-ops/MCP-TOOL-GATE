# tests/test_govern_passthrough.py
import asyncio
import json
import subprocess
import sys
import unittest
from pathlib import Path

from gate.snapshot import capture

ROOT = Path(__file__).resolve().parent.parent


class PassthroughTest(unittest.TestCase):
    def test_rich_server_direct_vs_proxy_sha256_equal(self):
        """直连 rich server 与过代理的快照必须逐字节一致（N-1 回归保护）。"""
        direct = asyncio.run(capture(ROOT / "examples/demo_server_rich.py"))
        proxy = asyncio.run(capture(
            ROOT / "govern/proxy.py",
            extra_args=["--transport", "stdio"],
        ))
        self.assertEqual(direct, proxy, "代理改变了 schema，不再是透明透传")


if __name__ == "__main__":
    unittest.main()