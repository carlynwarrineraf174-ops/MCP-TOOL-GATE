"""把 MCP Server 的 tools/list 抓下来，存成一份可 diff 的快照。

用法：
    python -m gate.snapshot --server examples/demo_server.py --out snapshots/v1

产物：
    snapshots/v1/tools.json      # 工具名 -> {description, input_schema, output_schema}
    snapshots/v1/meta.json       # 采集时间 / sha256 / 工具数

为什么要存 sha256：两份快照"看起来一样"时能立刻确认字节是否相同，
省掉一次"是不是 diff 引擎有 bug"的怀疑。
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

SCHEMA_KEYS = ("input_schema", "output_schema")


def canonical(obj: object) -> str:
    """稳定的 JSON 表示：键排序 + 去掉多余空白。diff 与 sha256 都基于它。"""
    return json.dumps(obj, sort_keys=True, ensure_ascii=False, separators=(",", ":"))


def sha256_12(obj: object) -> str:
    return hashlib.sha256(canonical(obj).encode("utf-8")).hexdigest()[:12]


def tool_to_dict(tool: object) -> dict:
    """把 SDK 的 Tool 对象拍平成纯 dict —— 快照里不存任何 SDK 类型。"""
    return {
        "description": getattr(tool, "description", None) or "",
        "input_schema": getattr(tool, "inputSchema", None) or {},
        "output_schema": getattr(tool, "outputSchema", None),
    }


async def capture(server: Path, timeout: float = 30.0) -> dict:
    """起一个 stdio MCP Server 子进程，initialize 之后取 tools/list。"""
    params = StdioServerParameters(command=sys.executable, args=[str(server)])

    async def _list() -> list:
        async with stdio_client(params) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()
                result = await session.list_tools()
                return list(result.tools)

    tools = await asyncio.wait_for(_list(), timeout=timeout)
    return {t.name: tool_to_dict(t) for t in tools}


def write_snapshot(out_dir: Path, tools: dict, source: str) -> dict:
    out_dir.mkdir(parents=True, exist_ok=True)
    digest = sha256_12(tools)
    meta = {
        "source": source,
        "captured_at": datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds"),
        "tool_count": len(tools),
        "sha256_12": digest,
    }
    (out_dir / "tools.json").write_text(
        json.dumps(tools, sort_keys=True, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    (out_dir / "meta.json").write_text(
        json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return meta


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="gate.snapshot", description="抓取 MCP 工具的 schema 快照")
    ap.add_argument("--server", default="examples/demo_server.py", help="MCP Server 的 .py 路径")
    ap.add_argument("--out", required=True, help="快照输出目录，例如 snapshots/v1")
    ap.add_argument("--timeout", type=float, default=30.0, help="启动 + list 的超时秒数")
    args = ap.parse_args(argv)

    server = Path(args.server).resolve()
    if not server.exists():
        print(f"[error] 找不到 MCP Server: {server}")
        return 2

    tools = asyncio.run(capture(server, timeout=args.timeout))
    meta = write_snapshot(Path(args.out), tools, source=str(server))
    print(f"[ok] {meta['tool_count']} 个工具 -> {args.out}\\tools.json  sha256={meta['sha256_12']}")
    for name in sorted(tools):
        print(f"     - {name}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
