import asyncio
import os
import sys
import signal
import asyncio

# Windows 控制台默认 GBK，日志里的 ✅ / 中文会乱码；这里统一成 UTF-8。
# 注意：stdio 模式下 stdout 是协议通道，只改编码、不往 stdout 写任何东西。
for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

# 强行获取项目根目录，防止路径问题
ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
os.chdir(ROOT_DIR)
sys.path.insert(0, ROOT_DIR)

from prometheus_client import start_http_server  # noqa: E402

from govern.settings import settings  # noqa: E402
from govern.app import main  # noqa: E402


def _is_stdio() -> bool:
    """同时支持 `--transport stdio` 和 `--transport=stdio`。"""
    argv = sys.argv
    for i, arg in enumerate(argv):
        if arg == "--transport" and i + 1 < len(argv):
            return argv[i + 1] == "stdio"
        if arg.startswith("--transport="):
            return arg.split("=", 1)[1] == "stdio"
    return False

async def _run_with_sigterm():
    loop = asyncio.get_running_loop()
    stop = asyncio.Event()

    def _handle_signal(sig):
        print(f"收到信号 {sig.name}，准备优雅停机...", file=sys.stderr)
        stop.set()

    for sig in (signal.SIGTERM, signal.SIGINT):
        try:
            loop.add_signal_handler(sig, _handle_signal, sig)
        except NotImplementedError:
            # Windows 不支持 add_signal_handler，退化为 signal.signal
            signal.signal(sig, lambda s, f: _handle_signal(sig))

    task = asyncio.create_task(main())
    done, pending = await asyncio.wait(
        {task, asyncio.create_task(stop.wait())},
        return_when=asyncio.FIRST_COMPLETED,
    )
    if stop.is_set() and not task.done():
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass


if __name__ == "__main__":
    # stdio 模式下不启动 Prometheus：那个 HTTP server 会和协议抢生命周期，
    # 而且 bench / snapshot 只需要协议本身。
    if not _is_stdio() and settings.metrics_port:
        try:
            start_http_server(settings.metrics_port)
            print(f"Prometheus metrics server started on http://127.0.0.1:{settings.metrics_port}",
                  file=sys.stderr)
        except OSError:
            print(f"Warning: Port {settings.metrics_port} in use. Metrics skipped.", file=sys.stderr)

    asyncio.run(main())
